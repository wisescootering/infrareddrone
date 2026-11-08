# -*- coding: utf-8 -*-
"""
Map of a flight (no Qt): positions of the shoot points, ground footprint of
each image, orthophoto preview and background map tiles.

All the drawing is done in Web Mercator metres (EPSG:3857), the projection of
the online maps: a point is placed with `mercator(lat, lon)`. Over a survey
(a few hundred metres) the UTM orthophoto is placed with one affine transform
from three of its corners.

The background tiles are optional: they are fetched with a short timeout and
kept in a disk cache, so a mission seen once online is also shown offline.
Nothing here may block the review when there is no network.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

EARTH_RADIUS = 6378137.0
WORLD = 2 * math.pi * EARTH_RADIUS          # Web Mercator width in metres
USER_AGENT = "IRDrone/1.0 (+https://github.com/wisescootering/infrareddrone)"


# ---------------------------------------------------------------------------
#  Projections
# ---------------------------------------------------------------------------
def mercator(lat: float, lon: float) -> Tuple[float, float]:
    """(x, y) Web Mercator metres; y grows to the north."""
    x = EARTH_RADIUS * math.radians(lon)
    y = EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def offset_latlon(lat: float, lon: float, east: float, north: float) -> Tuple[float, float]:
    """Point `east`, `north` metres away (small distances)."""
    return (lat + math.degrees(north / EARTH_RADIUS),
            lon + math.degrees(east / (EARTH_RADIUS * math.cos(math.radians(lat)))))


def resolution(zoom: int) -> float:
    """Mercator metres per pixel of a 256 px tile at `zoom`."""
    return WORLD / (256 * 2 ** zoom)


def tile_of(x: float, y: float, zoom: int) -> Tuple[int, int]:
    """Tile (column, row) holding the mercator point."""
    n = 2 ** zoom
    return int((x + WORLD / 2) / WORLD * n), int((WORLD / 2 - y) / WORLD * n)


def tile_bounds(col: int, row: int, zoom: int) -> Tuple[float, float, float, float]:
    """(x0, y_top, x1, y_bottom) of a tile in mercator metres."""
    size = WORLD / 2 ** zoom
    x0 = -WORLD / 2 + col * size
    y_top = WORLD / 2 - row * size
    return x0, y_top, x0 + size, y_top - size


# ---------------------------------------------------------------------------
#  Shoot points and footprints
# ---------------------------------------------------------------------------
# 35 mm equivalent focal length of the visible cameras (default: 24 mm)
FOCAL_35MM = {"FC3170": 24.0, "FC7303": 24.0, "FC3582": 24.0, "FC3411": 22.0, "L1D-20c": 28.0,
              "FC220": 26.0, "FC330": 20.0}


# Measured: calibration/DJI_RAW (focal 2898 px), aligned images 3892 x 2892 px
FOV_DEGREES = {"FC3170": (67.8, 53.0)}


def field_of_view(model: str = "", aspect: float = 4 / 3) -> Tuple[float, float]:
    """(horizontal, vertical) field of view in degrees of a 4:3 visible camera."""
    if str(model).strip() in FOV_DEGREES:
        return FOV_DEGREES[str(model).strip()]
    f = FOCAL_35MM.get(str(model).strip(), 24.0)
    half_diag = math.hypot(36.0, 24.0) / 2
    half_w = half_diag * aspect / math.hypot(aspect, 1)
    half_h = half_diag / math.hypot(aspect, 1)
    return 2 * math.degrees(math.atan(half_w / f)), 2 * math.degrees(math.atan(half_h / f))


def footprint(lat: float, lon: float, height: float, yaw: float, fov: Tuple[float, float]) -> List[Tuple[float, float]]:  # noqa: E501
    """Ground corners (lat, lon) of a nadir image: top-left, top-right,
    bottom-right, bottom-left. The top of the image looks to `yaw` (degrees
    from the north, clockwise); `height` above the ground in metres."""
    h = max(float(height), 1.0)
    half_w = h * math.tan(math.radians(fov[0]) / 2)
    half_h = h * math.tan(math.radians(fov[1]) / 2)
    a = math.radians(yaw)
    fwd = (math.sin(a), math.cos(a))          # east, north of the image top
    right = (math.cos(a), -math.sin(a))
    out = []
    for x, y in ((-half_w, half_h), (half_w, half_h), (half_w, -half_h), (-half_w, -half_h)):
        east = x * right[0] + y * fwd[0]
        north = x * right[1] + y * fwd[1]
        out.append(offset_latlon(lat, lon, east, north))
    return out


@dataclass
class MapPoint:
    number: int
    stem: str
    lat: float
    lon: float
    height: Optional[float]          # above the take-off ground (DJI)
    yaw: Optional[float]             # image top, degrees from the north
    altitude: Optional[float] = None  # above the sea
    ground: Optional[float] = None    # ground under the drone (DTM or IGN), above the sea
    yaw_source: str = "compass"

    @property
    def above_ground(self) -> Optional[float]:
        """Height above the ground under the drone (above the take-off ground
        when the ground there is not known)."""
        if self.altitude is not None and self.ground is not None:
            return self.altitude - self.ground
        return self.height

    @property
    def xy(self) -> Tuple[float, float]:
        return mercator(self.lat, self.lon)


def _float(value) -> Optional[float]:
    try:
        v = float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def map_point(number: int, stem: str, vis: dict) -> Optional[MapPoint]:
    """MapPoint from the VIS entry of AerialPhotography/shoot_points.json."""
    lat, lon = _float(vis.get("DroneLatitude")), _float(vis.get("DroneLongitude"))
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    yaw = _float(vis.get("GimbalYawDegree"))
    if yaw is None:
        yaw = _float(vis.get("FlightYawDegree"))
    return MapPoint(number=number, stem=stem, lat=lat, lon=lon,
                    height=_float(vis.get("DroneAltitudeGround")), yaw=yaw,
                    altitude=_float(vis.get("DroneAltitudeSeaLevel")))


def odm_yaws(mission: Path) -> Dict[int, float]:
    """Image yaw (top of the image, degrees from the true north) of the shoot
    points solved by the mapping (Step 5): more exact than the drone compass.
    {} when the mapping is not done."""
    path = Path(mission) / "mapping_MULTI" / "mapping_result" / "shots.geojson"
    try:
        with open(path, encoding="utf-8") as f:
            features = json.load(f).get("features", [])
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for ft in features:
        try:
            props = ft["properties"]
            lon = float(ft["geometry"]["coordinates"][0])
            lat = float(ft["geometry"]["coordinates"][1])
            r = np.array(props["rotation"], float)
            digits = re.search(r"(\d+)", Path(props["filename"]).stem)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if digits is None:
            continue
        # OpenSfM: world -> camera rotation (axis-angle); image "up" is -y
        theta = float(np.linalg.norm(r))
        if theta < 1e-12:
            rot = np.eye(3)
        else:
            k = r / theta
            kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
            rot = np.eye(3) + math.sin(theta) * kx + (1 - math.cos(theta)) * kx @ kx
        up = -rot.T @ np.array([0.0, 1.0, 0.0])
        grid_yaw = math.degrees(math.atan2(up[0], up[1]))
        # the world frame is UTM: grid north -> true north
        zone_meridian = (int((lon + 180) // 6) + 1) * 6 - 183
        convergence = math.degrees(math.atan(math.tan(math.radians(lon - zone_meridian)) * math.sin(math.radians(lat))))
        out[int(digits.group(1))] = grid_yaw + convergence
    return out


def _number(stem: str, default: int) -> int:
    digits = re.search(r"(\d+)(?!.*\d)", stem)
    return int(digits.group(1)) if digits else default


def image_track(mission: Path) -> List[MapPoint]:
    """Every visible image of the mission with a position (the .exif side
    cars written in Step 1), in shooting order: the whole flight."""
    folder = Path(mission) / "AerialPhotography" / "VIS"
    try:
        sides = sorted(folder.glob("*.exif"), key=lambda p: _number(p.stem, 0))
    except OSError:
        return []
    out = []
    for side in sides:
        try:
            with open(side, encoding="utf-8") as f:
                exif = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(exif, dict):
            point = map_point(_number(side.stem, len(out)), side.stem, exif)
            if point is not None:
                out.append(point)
    return out


def phases(mission: Path) -> Dict[int, str]:
    """Image number -> "sync" / "survey", from the phases confirmed in Step 2."""
    try:
        with open(Path(mission) / "FlightAnalytics" / "flight_timeline.json", encoding="utf-8") as f:
            state = json.load(f)
        chosen = state.get("confirmed") or state.get("proposed") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for key, name in (("VIS sync", "sync"), ("VIS survey", "survey")):
        pair = chosen.get(key) if isinstance(chosen, dict) else None
        if isinstance(pair, list) and len(pair) == 2:
            a, b = (_number(Path(str(x)).stem, -1) for x in pair)
            for n in range(min(a, b), max(a, b) + 1):
                out[n] = name
    return out


def mission_track(mission: Path, shoot_points_only: bool = False) -> List[MapPoint]:
    """The paired shoot points of the mission with a position, in time order
    (before Step 3: every visible image, unless `shoot_points_only`).
    The image yaw comes from the mapping when it is done (else the gimbal)."""
    path = Path(mission) / "AerialPhotography" / "shoot_points.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not (isinstance(data, dict) and data.get("shoot_points")):
        return [] if shoot_points_only else _with_mapping_yaw(mission, image_track(mission))
    out = []
    for entry in data.get("shoot_points", []):
        vis = entry.get("VIS") if isinstance(entry, dict) else None
        if not isinstance(vis, dict):
            continue
        stem = Path(str(vis.get("FileName", ""))).stem
        digits = "".join(c for c in stem if c.isdigit())
        point = map_point(int(digits) if digits else len(out), stem, vis)
        if point is not None:
            out.append(point)
    return _with_mapping_yaw(mission, out)


def _with_mapping_yaw(mission: Path, out: List[MapPoint]) -> List[MapPoint]:
    yaws = odm_yaws(mission) if out else {}
    # the compass error measured on the mapped images corrects the others
    errors = [(yaws[p.number] - p.yaw + 180) % 360 - 180 for p in out if p.number in yaws and p.yaw is not None]
    bias = float(np.median(errors)) if errors else 0.0
    for p in out:
        if p.number in yaws:
            p.yaw = yaws[p.number]
            p.yaw_source = "mapping"
        elif errors and p.yaw is not None:
            p.yaw += bias
            p.yaw_source = "compass corrected by the mapping"
    return out


def camera_model(mission: Path) -> str:
    try:
        with open(Path(mission) / "FlightAnalytics" / "mission_parameters.json", encoding="utf-8") as f:
            return str(json.load(f).get("camera VIS ID", ""))
    except (OSError, ValueError, AttributeError):
        return ""


# ---------------------------------------------------------------------------
#  Ground under the drone: the drone altitude is measured from the take-off
#  point, the footprint needs the height above the ground under the image.
# ---------------------------------------------------------------------------
def dtm_grid_path(mission: Path) -> Path:
    return Path(mission) / "mapping_MULTI" / "mapping_result" / "ortho_dtm_grid.json"


def dtm_ground(mission: Path):
    """f(lat, lon) -> ground altitude from the terrain model of Step 5 (None
    outside it), or None when there is no terrain model."""
    try:
        with open(dtm_grid_path(mission), encoding="utf-8") as f:
            pts = json.load(f).get("points", [])
        arr = np.array([[p["lat"], p["lon"], p["z"]] for p in pts], float)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if arr.size == 0:
        return None
    lat0 = float(arr[:, 0].mean())
    k = math.cos(math.radians(lat0))
    north = np.radians(arr[:, 0]) * EARTH_RADIUS
    east = np.radians(arr[:, 1]) * EARTH_RADIUS * k

    def ground(lat, lon, reach=20.0):
        d2 = (north - math.radians(lat) * EARTH_RADIUS) ** 2 + (east - math.radians(lon) * EARTH_RADIUS * k) ** 2
        near = np.argsort(d2)[:4]
        if d2[near[0]] > reach ** 2:
            return None
        w = 1.0 / np.maximum(d2[near], 0.01)
        return float((arr[near, 2] * w).sum() / w.sum())
    return ground


IGN_ALTI_URL = ("https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
                "?lon={lons}&lat={lats}&resource=ign_rge_alti_wld&delimiter=|&zonly=true")


def ign_ground(points: List[Tuple[float, float]], timeout: float = 8.0) -> Optional[List[Optional[float]]]:
    """Ground altitudes from the IGN service (France), None when offline."""
    out: List[Optional[float]] = []
    for i in range(0, len(points), 100):
        batch = points[i:i + 100]
        url = IGN_ALTI_URL.format(lats="|".join(f"{a:.7f}" for a, _ in batch),
                                  lons="|".join(f"{b:.7f}" for _, b in batch))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                z = json.loads(resp.read().decode("utf-8")).get("elevations", [])
        except Exception:
            return None
        if len(z) != len(batch):
            return None
        out += [float(v) if isinstance(v, (int, float)) and v > -1000 else None for v in z]
    return out


def ground_cache_file(mission: Path) -> Path:
    return cache_root() / "ground" / f"{Path(mission).name}.json"


def find_ground(mission: Path, points: List[MapPoint], online: bool = True) -> str:
    """Fill `ground` of the points: terrain model of Step 5, else cached or
    online IGN altitudes (France). Returns the source used ("" if none)."""
    dtm = dtm_ground(mission)
    if dtm is not None:
        for p in points:
            p.ground = dtm(p.lat, p.lon)
        if any(p.ground is not None for p in points):
            return "terrain model"
    cache = ground_cache_file(mission)
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if not all(p.stem in cached for p in points) and online and points and in_france(points[0].lat, points[0].lon):
        z = ign_ground([(p.lat, p.lon) for p in points])
        if z is not None:
            cached.update({p.stem: v for p, v in zip(points, z)})
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(cached), encoding="utf-8")
            except OSError:
                pass
    for p in points:
        v = cached.get(p.stem)
        p.ground = float(v) if isinstance(v, (int, float)) else None
    return "IGN" if any(p.ground is not None for p in points) else ""


# ---------------------------------------------------------------------------
#  Orthophoto (Step 5)
# ---------------------------------------------------------------------------
def orthophoto_path(mission: Path) -> Path:
    return Path(mission) / "mapping_MULTI" / "mapping_result" / "odm_orthophoto.tif"


@dataclass
class OrthoPreview:
    natural: np.ndarray                    # H x W x 4 RGBA uint8
    false_color: Optional[np.ndarray]      # NIR, red, green (as the aligned images)
    corners: List[Tuple[float, float]]     # (lat, lon) top-left, top-right, bottom-left


def _stretch(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    values = band[valid]
    if values.size == 0:
        return np.zeros(band.shape, np.uint8)
    lo, hi = np.percentile(values, (0.5, 99.5))
    if hi <= lo:
        hi = lo + 1
    return (np.clip((band.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def load_orthophoto(mission: Path, max_size: int = 2048) -> Optional[OrthoPreview]:
    """Reduced orthophoto (read from the GeoTIFF overviews), None if there is
    none or it cannot be read (rasterio missing, no georeferencing...)."""
    path = orthophoto_path(mission)
    if not path.is_file():
        return None
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform as warp
    except ImportError:
        return None
    try:
        with rasterio.open(path) as ds:
            if ds.crs is None:
                return None
            scale = min(1.0, max_size / max(ds.width, ds.height))
            shape = (ds.count, max(1, int(ds.height * scale)), max(1, int(ds.width * scale)))
            data = ds.read(out_shape=shape, resampling=Resampling.average)
            names = [str(d or "").lower() for d in ds.descriptions]
            interp = [c.name for c in ds.colorinterp]
            b = ds.bounds
            xs, ys = warp(ds.crs, "EPSG:4326", [b.left, b.right, b.left], [b.top, b.top, b.bottom])
    except Exception as e:  # a broken orthophoto must not stop the review
        print(f"Orthophoto not shown: {e}")
        return None

    def band(name, fallback):
        if name in names:
            return names.index(name)
        return fallback if fallback < data.shape[0] else None

    alpha_i = interp.index("alpha") if "alpha" in interp else None
    valid = data[alpha_i] > 0 if alpha_i is not None else np.ones(data.shape[1:], bool)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    r, g, bl = band("red", 0), band("green", 1), band("blue", 2)
    if r is None or g is None or bl is None:
        return None
    red, green = _stretch(data[r], valid), _stretch(data[g], valid)
    natural = np.dstack([red, green, _stretch(data[bl], valid), alpha])
    nir_i = band("nir", 3 if data.shape[0] >= 5 else 99)
    false_color = (np.dstack([_stretch(data[nir_i], valid), red, green, alpha])
                   if nir_i is not None and nir_i != alpha_i else None)
    corners = [(ys[k], xs[k]) for k in range(3)]
    return OrthoPreview(natural=np.ascontiguousarray(natural),
                        false_color=None if false_color is None else np.ascontiguousarray(false_color),
                        corners=corners)


# ---------------------------------------------------------------------------
#  Background tiles
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TileSource:
    key: str
    name: str
    url: str                 # {z} {x} (column) {y} (row)
    attribution: str
    max_zoom: int = 19
    france_only: bool = False


TILE_SOURCES: Dict[str, TileSource] = {s.key: s for s in (
    TileSource("ign", "IGN aerial photos (France)",
               "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
               "&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM"
               "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg",
               "© IGN Géoplateforme", 19, True),
    TileSource("esri", "Esri World Imagery",
               "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
               "© Esri, Maxar, Earthstar Geographics", 19),
    TileSource("osm", "OpenStreetMap",
               "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
               "© OpenStreetMap contributors", 19),
)}
NO_BACKGROUND = "none"


def in_france(lat: float, lon: float) -> bool:
    """Metropolitan France and Corsica (rough box): IGN photos available."""
    return 41.2 <= lat <= 51.2 and -5.3 <= lon <= 9.7


def default_source(lat: Optional[float], lon: Optional[float]) -> str:
    if lat is not None and lon is not None and in_france(lat, lon):
        return "ign"
    return "esri"


def cache_root() -> Path:
    """User cache of the map (tiles, ground altitudes); IRDRONE_CACHE overrides it."""
    env = os.environ.get("IRDRONE_CACHE")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "IRDrone"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "irdrone"


def cache_dir() -> Path:
    return cache_root() / "tiles"


def tile_file(source: str, zoom: int, col: int, row: int, root: Optional[Path] = None) -> Path:
    return (root or cache_dir()) / source / str(zoom) / str(col) / f"{row}.img"


def fetch_tile(source: str, zoom: int, col: int, row: int, timeout: float = 6.0,
               root: Optional[Path] = None) -> Optional[bytes]:
    """Tile bytes from the disk cache, else from the server (then cached).
    None when it cannot be had (offline, server error): never raises."""
    path = tile_file(source, zoom, col, row, root)
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path.read_bytes()
    except OSError:
        pass
    src = TILE_SOURCES.get(source)
    if src is None:
        return None
    url = src.url.format(z=zoom, x=col, y=row)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200 or not str(resp.headers.get("Content-Type", "")).startswith("image"):
                return None
            data = resp.read()
    except Exception:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        pass
    return data
