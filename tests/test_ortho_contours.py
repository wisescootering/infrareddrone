import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone Interactive"))

import rasterio
from rasterio.transform import from_origin

import IRD_Interactive_GeoRef as GeoRef
import IRD_Interactive_contours as contours


def fake_altitudes(coordinates, verbose=False, bypass=False):
    """Deterministic slope: 1 m of altitude per 0.0001 deg of latitude above 45 deg."""
    return [
        {"lat": lat, "lon": lon, "z": 100.0 + (lat - 45.0) * 10000.0, "acc": "IGN"}
        for lat, lon in coordinates
    ]


def make_orthophoto(path, left=500000.0, top=4986000.0, width=60, height=40, res=5.0):
    data = np.ones((1, height, width), dtype=np.uint8)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs="EPSG:32631", transform=from_origin(left, top, res, res),
    ) as dst:
        dst.write(data)


class GridTests(unittest.TestCase):
    def test_grid_covers_bounds_and_is_regular(self):
        bounds = (500000.0, 4985800.0, 500303.0, 4986000.0)
        Xg, Yg, step = contours.build_regular_grid(bounds, step=10.0)
        self.assertEqual(step, 10.0)
        self.assertLessEqual(Xg.min(), bounds[0])
        self.assertGreaterEqual(Xg.max(), bounds[2])
        self.assertLessEqual(Yg.min(), bounds[1])
        self.assertGreaterEqual(Yg.max(), bounds[3])
        self.assertTrue(np.allclose(np.diff(Xg[0]), 10.0))
        self.assertTrue(np.allclose(np.diff(Yg[:, 0]), 10.0))
        center_x, center_y = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        self.assertIn(center_x, Xg[0])
        self.assertIn(center_y, Yg[:, 0])

    def test_step_grows_when_too_many_points(self):
        bounds = (0.0, 0.0, 20000.0, 20000.0)
        Xg, Yg, step = contours.build_regular_grid(bounds, step=10.0, max_points=5000)
        self.assertGreater(step, 10.0)
        self.assertLessEqual(Xg.size, 5000)
        self.assertLessEqual(Xg.min(), 0.0)
        self.assertGreaterEqual(Xg.max(), 20000.0)


class WorkflowTests(unittest.TestCase):
    def test_utm_grid_spacing_and_mission_name(self):
        self.assertEqual(contours._utm_grid_spacing(400.0), 50.0)
        self.assertGreater(contours._utm_grid_spacing(5000.0), 50.0)
        mission = Path("C:/Air-Mission/FLY-20220524-1715-Chalivoy-Milon")
        ortho = mission / "mapping_MULTI" / "mapping_result" / "odm_orthophoto.tif"
        self.assertEqual(contours._mission_name(ortho), mission.name)
        self.assertEqual(contours._mission_name(Path("other") / "x.tif"), "")

    def test_map_palettes(self):
        z = np.add.outer(np.linspace(0, 5, 20), np.linspace(0, 5, 30))
        bounds = (0.0, 0.0, 30.0, 20.0)
        Xg, Yg = np.meshgrid(np.arange(0, 31, 10.0), np.arange(0, 21, 10.0))
        with tempfile.TemporaryDirectory() as temporary:
            for palette in contours.MAP_PALETTES:
                path = Path(temporary) / f"{palette}.png"
                contours.plot_dtm_map(path, z, bounds, Xg, Yg, "t", palette=palette)
                self.assertTrue(path.is_file())
            with self.assertRaises(ValueError):
                contours.plot_dtm_map(Path(temporary) / "x.png", z, bounds, Xg, Yg, "t",
                                      palette="unknown")

    def test_extent_rejects_non_utm(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wgs.tif"
            with rasterio.open(
                path, "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8",
                crs="EPSG:4326", transform=from_origin(0, 1, 0.5, 0.5),
            ) as dst:
                dst.write(np.ones((1, 2, 2), dtype=np.uint8))
            with self.assertRaises(ValueError):
                contours.read_orthophoto_extent(path)

    def test_missing_altitudes_are_rejected(self):
        Xg, Yg, _ = contours.build_regular_grid((0.0, 0.0, 30.0, 30.0), step=10.0)

        def failing(coordinates, verbose=False):
            return [{"lat": a, "lon": b, "z": 0, "acc": "unavailable"} for a, b in coordinates]

        with self.assertRaises(contours.AltitudeUnavailableError):
            contours.fetch_grid_altitudes(Xg, Yg, 31, altitude_getter=failing, log=lambda m: None)

    def test_full_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            ortho = folder / "odm_orthophoto.tif"
            make_orthophoto(ortho)
            result = contours.generate_ortho_dtm(
                ortho, step=10.0, log=lambda m: None, altitude_getter=fake_altitudes
            )
            keys = ["dtm", "map", "surface_3d", "grid"]
            if GeoRef.GDAL_AVAILABLE:  # contour lines need GDAL
                keys += ["contours", "contours_style"]
            else:
                self.assertIsNone(result["contours"])
            for key in keys:
                self.assertTrue(Path(result[key]).is_file(), key)
            with rasterio.open(result["dtm"]) as dtm:
                self.assertEqual(dtm.crs.to_epsg(), 32631)
                values = dtm.read(1)
                self.assertTrue(np.isfinite(values).all())
                # north is up: altitude must increase toward the top rows
                self.assertGreater(values[0].mean(), values[-1].mean())
            if not GeoRef.GDAL_AVAILABLE:
                return
            from osgeo import ogr
            datasource = ogr.Open(result["contours"])
            layer = datasource.GetLayer()
            elevations = {round(feature.GetField("elev"), 3) for feature in layer}
            self.assertTrue(elevations)
            self.assertTrue(all(abs(e - round(e)) < 1e-6 for e in elevations))
            layer = datasource = None


if __name__ == "__main__":
    unittest.main()
