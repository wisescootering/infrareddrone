# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 5
#   Digital terrain model (DTM) and contour lines over the ODM orthophoto.
#
#   1. Read the orthophoto footprint (UTM).
#   2. Build a regular grid (south-north / west-east axes) centred on the footprint
#      and always covering it.
#   3. Convert the grid to lat/lon and query the elevation APIs (IGN, then
#      OpenTopoData as fallback) through IRD_interactive_geo.get_altitudes.
#   4. Build a spline DTM and export: elevation GeoTIFF, QGIS contour lines
#      (1 m equidistance), shaded 2D map and 3D surface.
# ---------------------------------------------------------------------------------
"""DTM and contour lines of the ODM orthophoto (Step 5, "DTM + contours").

Entry point: ``generate_ortho_dtm``. Output files are written next to the
orthophoto (``mapping_MULTI/mapping_result``); an existing file is never
overwritten (a numeric suffix is added). They are named ``ortho_dtm.tif``
(elevation raster), ``ortho_contours.geojson`` + ``.qml`` (contour lines every
1 m, bold every 10 m, with the QGIS style), ``ortho_dtm_map.png`` (2D shaded map
with UTM grid), ``ortho_dtm_3d.png`` and ``ortho_dtm_grid.json`` (grid points
and altitude sources).

The altitudes are requested online (IGN, OpenTopoData as fallback), so the
number of grid points is capped (``DEFAULT_MAX_GRID_POINTS``) by enlarging the
step. The computation fails with ``AltitudeUnavailableError`` if one altitude is
missing, without any effect on the ODM results.
"""

import json
import math
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from matplotlib import colormaps, patheffects
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LightSource, Normalize
from matplotlib.figure import Figure

import IRD_Interactive_GeoRef as GeoRef
from IRD_interactive_geo import get_altitudes

DEFAULT_GRID_STEP_M = 10.0
# palette name -> (colormap or None for plain grey hillshade, contour colour)
MAP_PALETTES = {
    "gray": (None, "saddlebrown"),
    "sepia": ("YlOrBr", "black"),
    "cividis": ("cividis", "white"),
    "terrain": ("terrain", "saddlebrown"),
}
DEFAULT_MAP_PALETTE = "gray"
# Darkest shade is a 90 % grey (10 % brightness) instead of pure black
SHADE_DARKEST_LEVEL = 0.10
UTM_GRID_STEP_M = 50.0
UTM_GRID_COLOR = "#7fb2e5"
DEFAULT_MAX_GRID_POINTS = 5000
DEFAULT_RASTER_RESOLUTION_M = 1.0
MAX_RASTER_SIDE_PIXELS = 4000
CONTOUR_MINOR_M = 1.0
CONTOUR_MAJOR_M = 10.0
UNAVAILABLE_ALTITUDE = -99999.0


class AltitudeUnavailableError(RuntimeError):
    """Raised when the elevation APIs did not provide every grid altitude."""


def read_orthophoto_extent(orthophoto_path) -> tuple:
    """Return ((left, bottom, right, top), utm_zone) of a north-hemisphere UTM raster."""
    with rasterio.open(orthophoto_path) as dataset:
        bounds = tuple(dataset.bounds)
        epsg = dataset.crs.to_epsg() if dataset.crs is not None else None
    if epsg is None or not 32601 <= epsg <= 32660:
        raise ValueError(
            f"The orthophoto must use a north-hemisphere UTM CRS (EPSG 326xx), got {epsg}."
        )
    return (bounds[0], bounds[1], bounds[2], bounds[3]), epsg - 32600


def build_regular_grid(
    bounds,
    step: float = DEFAULT_GRID_STEP_M,
    margin_cells: int = 1,
    max_points: int = DEFAULT_MAX_GRID_POINTS,
) -> tuple:
    """Regular west-east / south-north grid centred on the footprint centre.

    The grid always covers the footprint, extended by ``margin_cells`` cells on
    each side. The step is increased when the point count would exceed
    ``max_points``. Returns ``(Xg, Yg, step_used)`` with ascending axes.
    """
    left, bottom, right, top = bounds
    if not step > 0:
        raise ValueError("The grid step must be positive.")
    center_x, center_y = (left + right) / 2.0, (bottom + top) / 2.0
    half_x, half_y = (right - left) / 2.0, (top - bottom) / 2.0

    step_used = float(step)
    while True:
        n_x = math.ceil(half_x / step_used) + margin_cells
        n_y = math.ceil(half_y / step_used) + margin_cells
        n_x, n_y = max(n_x, 1), max(n_y, 1)
        n_points = (2 * n_x + 1) * (2 * n_y + 1)
        if n_points <= max_points:
            break
        step_used *= math.sqrt(n_points / max_points) * 1.02

    x = center_x + step_used * np.arange(-n_x, n_x + 1)
    y = center_y + step_used * np.arange(-n_y, n_y + 1)
    Xg, Yg = np.meshgrid(x, y)
    return Xg, Yg, step_used


def fetch_grid_altitudes(
    Xg,
    Yg,
    zone: int,
    altitude_getter: Callable = get_altitudes,
    log: Callable[[str], None] = print,
) -> tuple:
    """Query the elevation APIs for every grid point; fail if any is missing."""
    shape = Xg.shape
    coordinates = [
        GeoRef.UTM2geo(float(x), float(y), zone)
        for x, y in zip(Xg.ravel(), Yg.ravel())
    ]
    log(f"Requesting {len(coordinates)} altitudes (IGN, OpenTopoData as fallback).")
    results = altitude_getter(coordinates, verbose=True)
    if results is None or len(results) != len(coordinates):
        raise AltitudeUnavailableError(
            "The elevation API returned an unexpected number of points."
        )

    z_values = np.array([float(point["z"]) for point in results])
    sources = [str(point.get("acc", "")) for point in results]
    missing = [
        index
        for index, (z, source) in enumerate(zip(z_values, sources))
        if z <= UNAVAILABLE_ALTITUDE + 1 or source in ("unavailable", "IGN_error")
        or not math.isfinite(z)
    ]
    if missing:
        raise AltitudeUnavailableError(
            f"{len(missing)} of {len(coordinates)} grid altitudes are unavailable "
            "(no response from IGN or OpenTopoData)."
        )
    counts = {source: sources.count(source) for source in sorted(set(sources))}
    return z_values.reshape(shape), coordinates, counts


def build_dtm(Xg, Yg, Zg):
    """Quadratic spline DTM; returns altitude(X, Y)."""
    return GeoRef.build_MNT_interpolator(
        Xg, Yg, Zg, method="RectBivariateSpline_quadratic", type_grid="regular"
    )


def sample_dtm_raster(altitude, bounds, resolution: float = DEFAULT_RASTER_RESOLUTION_M):
    """Evaluate the DTM on a north-up raster covering ``bounds``.

    Returns ``(elevation, transform, resolution_used)``.
    """
    left, bottom, right, top = bounds
    resolution = float(resolution)
    side = max(right - left, top - bottom)
    resolution = max(resolution, side / MAX_RASTER_SIDE_PIXELS)
    width = max(int(math.ceil((right - left) / resolution)), 1)
    height = max(int(math.ceil((top - bottom) / resolution)), 1)
    x = left + (np.arange(width) + 0.5) * resolution
    y = top - (np.arange(height) + 0.5) * resolution
    X, Y = np.meshgrid(x, y)
    elevation = altitude(X, Y).astype(np.float32)
    return elevation, from_origin(left, top, resolution, resolution), resolution


def _draw_north_arrow(axis) -> None:
    """Discreet geographic-north arrow in the upper-right corner (UTM grid north)."""
    outline = [patheffects.withStroke(linewidth=2.5, foreground="white")]
    axis.annotate(
        "", xy=(0.955, 0.955), xytext=(0.955, 0.88), xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color="0.15", lw=1.4,
                        path_effects=outline, shrinkA=0, shrinkB=0),
    )
    axis.text(0.955, 0.865, "N", transform=axis.transAxes, ha="center", va="top",
              fontsize=10, fontweight="bold", color="0.15", path_effects=outline)


def _utm_grid_spacing(extent_m: float, base: float = UTM_GRID_STEP_M) -> float:
    """UTM grid spacing: ``base`` m, coarsened so that a map shows <= 12 lines per axis."""
    spacing = base
    for factor in (1, 2, 4, 10, 20, 40, 100, 200, 400, 1000):
        spacing = base * factor
        if extent_m / spacing <= 12:
            break
    return spacing


def plot_dtm_map(path, elevation, bounds, Xg, Yg, title,
                 palette: str = DEFAULT_MAP_PALETTE, note: str = ""):
    """Shaded relief, contour lines, UTM grid, grid points and a north arrow.

    ``title`` is drawn above the map, ``note`` (data source) small at the bottom right.
    """
    if palette not in MAP_PALETTES:
        raise ValueError(f"Unknown palette {palette!r}; choose from {sorted(MAP_PALETTES)}.")
    colormap_name, contour_color = MAP_PALETTES[palette]

    left, bottom, right, top = bounds
    figure = Figure(figsize=(10, 8))
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111)
    extent = (left, right, bottom, top)
    height, width = elevation.shape
    res_x, res_y = (right - left) / width, (top - bottom) / height
    light = LightSource(azdeg=315, altdeg=45)
    if colormap_name is None:
        shade = light.hillshade(elevation, vert_exag=1.0, dx=res_x, dy=res_y)
        shade = SHADE_DARKEST_LEVEL + (1.0 - SHADE_DARKEST_LEVEL) * shade
        axis.imshow(shade, cmap="gray", vmin=0.0, vmax=1.0, extent=extent, origin="upper")
    else:
        colormap = colormaps[colormap_name]
        rgb = light.shade(elevation, cmap=colormap, vert_exag=1.0, dx=res_x, dy=res_y,
                          blend_mode="overlay")
        rgb[..., :3] = SHADE_DARKEST_LEVEL + (1.0 - SHADE_DARKEST_LEVEL) * rgb[..., :3]
        axis.imshow(rgb, extent=extent, origin="upper")
        z_low, z_high = float(np.nanmin(elevation)), float(np.nanmax(elevation))
        mappable = ScalarMappable(norm=Normalize(z_low, z_high), cmap=colormap)
        figure.colorbar(mappable, ax=axis, shrink=0.7, pad=0.02, label="Altitude (m)")
    xs = left + (np.arange(width) + 0.5) * res_x
    ys = top - (np.arange(height) + 0.5) * res_y
    z_min, z_max = float(np.nanmin(elevation)), float(np.nanmax(elevation))
    minor = np.arange(math.floor(z_min), math.ceil(z_max) + CONTOUR_MINOR_M, CONTOUR_MINOR_M)
    major = [level for level in minor if level % CONTOUR_MAJOR_M == 0]
    if len(minor) > 1:
        axis.contour(xs, ys, elevation, levels=minor, colors=contour_color,
                     linewidths=0.3, alpha=0.7)
    if major:
        labelled = axis.contour(xs, ys, elevation, levels=major, colors=contour_color,
                                linewidths=1.0)
        axis.clabel(labelled, fmt="%d m", fontsize=7)
    axis.scatter(Xg.ravel(), Yg.ravel(), s=2, c="black", alpha=0.5)

    # UTM grid on round coordinates (IGN Top25 style: thin light blue lines)
    spacing = _utm_grid_spacing(max(right - left, top - bottom))
    x_ticks = np.arange(math.ceil(left / spacing) * spacing, right + 1e-6, spacing)
    y_ticks = np.arange(math.ceil(bottom / spacing) * spacing, top + 1e-6, spacing)
    axis.set_xticks(x_ticks)
    axis.set_yticks(y_ticks)
    axis.tick_params(labelsize=7)
    axis.tick_params(axis="x", labelrotation=45)
    axis.set_axisbelow(False)
    axis.grid(True, color=UTM_GRID_COLOR, linewidth=0.5, alpha=0.9)

    axis.set_xlim(left, right)
    axis.set_ylim(bottom, top)
    axis.set_aspect("equal")
    axis.set_xlabel("UTM east (m)")
    axis.set_ylabel("UTM north (m)")
    axis.set_title(title)
    axis.ticklabel_format(useOffset=False, style="plain")
    if note:
        # Same line as the x label: measure the label position after layout
        figure.canvas.draw()
        label_box = axis.xaxis.label.get_window_extent().transformed(axis.transAxes.inverted())
        axis.text(1.0, (label_box.y0 + label_box.y1) / 2.0, note, transform=axis.transAxes,
                  ha="right", va="center", fontsize=7, color="0.35")
    _draw_north_arrow(axis)
    figure.savefig(path, dpi=200, bbox_inches="tight")

def plot_dtm_3d(path, altitude, Xg, Yg, Zg, title, n_dense: int = 120):
    """3D DTM surface with the grid points drawn on it."""
    x0, x1 = float(Xg.min()), float(Xg.max())
    y0, y1 = float(Yg.min()), float(Yg.max())
    xd, yd = np.meshgrid(np.linspace(x0, x1, n_dense), np.linspace(y0, y1, n_dense))
    zd = altitude(xd, yd)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    figure = Figure(figsize=(10, 8))
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111, projection="3d")
    axis.plot_surface(xd - cx, yd - cy, zd, cmap="terrain", alpha=0.75,
                      linewidth=0.1, antialiased=True)
    axis.scatter(Xg.ravel() - cx, Yg.ravel() - cy, Zg.ravel(), color="darkgreen", s=3)

    extent = max(x1 - x0, y1 - y0)
    relief = max(float(zd.max() - zd.min()), 0.1)
    visual_relief = min(max(3.0 * relief, 0.15 * extent), 0.5 * extent)
    axis.set_box_aspect((x1 - x0, y1 - y0, visual_relief))
    axis.set_proj_type("ortho")
    axis.set_xlabel("West-East (m from centre)")
    axis.set_ylabel("South-North (m from centre)")
    axis.set_zlabel("Altitude (m)")
    axis.set_title(f"{title}\n(vertical exaggeration x{visual_relief / relief:.1f})")
    figure.savefig(path, dpi=200, bbox_inches="tight")


def _mission_name(orthophoto_path: Path) -> str:
    """Mission folder name when the orthophoto is in <mission>/mapping_MULTI/mapping_result."""
    parents = Path(orthophoto_path).resolve().parents
    if len(parents) > 2 and parents[0].name == "mapping_result" and parents[1].name == "mapping_MULTI":
        return parents[2].name
    return ""


def generate_ortho_dtm(
    orthophoto_path,
    output_folder: Optional[Path] = None,
    step: float = DEFAULT_GRID_STEP_M,
    log: Callable[[str], None] = print,
    altitude_getter: Callable = get_altitudes,
    palette: str = DEFAULT_MAP_PALETTE,
) -> dict:
    """Run the complete DTM / contour workflow and return the generated paths."""
    orthophoto_path = Path(orthophoto_path)
    if not orthophoto_path.is_file():
        raise FileNotFoundError(f"Orthophoto not found: {orthophoto_path}")
    output_folder = Path(output_folder) if output_folder else orthophoto_path.parent

    bounds, zone = read_orthophoto_extent(orthophoto_path)
    Xg, Yg, step_used = build_regular_grid(bounds, step=step)
    if step_used > step:
        log(f"Grid step increased from {step:g} m to {step_used:.1f} m "
            f"to keep at most {DEFAULT_MAX_GRID_POINTS} points.")
    log(f"DTM grid: {Xg.shape[1]} x {Xg.shape[0]} points, step {step_used:.1f} m, UTM zone {zone}N.")

    Zg, coordinates, source_counts = fetch_grid_altitudes(
        Xg, Yg, zone, altitude_getter=altitude_getter, log=log
    )
    log("Altitude sources: " + ", ".join(f"{k}: {v}" for k, v in source_counts.items()))
    if set(source_counts) - {"IGN"}:
        log("Warning: some altitudes do not come from IGN (lower accuracy).")

    altitude = build_dtm(Xg, Yg, Zg)
    elevation, transform, resolution = sample_dtm_raster(altitude, bounds)
    crs = CRS.from_epsg(32600 + zone)

    dtm_path = GeoRef.get_unique_path(output_folder / "ortho_dtm.tif")
    GeoRef.write_geotiff_affine(dtm_path, elevation, transform, crs, no_data=np.nan)

    contour_path = qml_path = None
    if GeoRef.GDAL_AVAILABLE:
        contour_path = GeoRef.get_unique_path(output_folder / "ortho_contours.geojson")
        GeoRef.generate_contours_dual(
            elevation, transform, crs, contour_path,
            interval_minor=CONTOUR_MINOR_M, interval_major=CONTOUR_MAJOR_M,
        )
        qml_path = contour_path.with_suffix(".qml")
        GeoRef.generate_qml_style_qgis(qml_path, style="IGN", label_on_line=True)
    else:
        log("Warning: GDAL not installed, contour lines (.geojson) skipped.")

    source_label = ", ".join("\u00a9 IGN-France" if name == "IGN" else name for name in source_counts)
    title = f"DTM from {source_label} - grid step {step_used:.0f} m"
    map_path = GeoRef.get_unique_path(output_folder / "ortho_dtm_map.png")
    mission_name = _mission_name(orthophoto_path)
    source_note = title
    plot_dtm_map(map_path, elevation, bounds, Xg, Yg, mission_name or source_note,
                 palette=palette, note=source_note if mission_name else "")
    surface_path = GeoRef.get_unique_path(output_folder / "ortho_dtm_3d.png")
    plot_dtm_3d(surface_path, altitude, Xg, Yg, Zg, title)

    report_path = GeoRef.get_unique_path(output_folder / "ortho_dtm_grid.json")
    report = {
        "orthophoto": str(orthophoto_path),
        "utm_epsg": 32600 + zone,
        "orthophoto_bounds": list(bounds),
        "grid_step_m": step_used,
        "grid_size": [int(Xg.shape[1]), int(Xg.shape[0])],
        "raster_resolution_m": resolution,
        "interpolation": "RectBivariateSpline_quadratic",
        "altitude_sources": source_counts,
        "z_min": float(np.min(Zg)),
        "z_max": float(np.max(Zg)),
        "points": [
            {"x": float(x), "y": float(y), "lat": lat, "lon": lon, "z": float(z)}
            for x, y, (lat, lon), z in zip(
                Xg.ravel(), Yg.ravel(), coordinates, Zg.ravel()
            )
        ],
    }
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")

    log(f"DTM and contour lines saved in {output_folder}")
    return {
        "dtm": str(dtm_path),
        "contours": str(contour_path) if contour_path else None,
        "contours_style": str(qml_path) if qml_path else None,
        "map": str(map_path),
        "surface_3d": str(surface_path),
        "grid": str(report_path),
        "grid_step_m": step_used,
    }
