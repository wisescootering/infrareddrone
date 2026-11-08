"""Flight map: projections, image footprints, yaw from the mapping, ground
under the drone, background tiles (offline must never block), and the map
in the review window."""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IRDRONE_CACHE"] = tempfile.mkdtemp()

import flight_map as F  # noqa: E402

LAT, LON = 45.1695, 3.4000


def distance(a, b):
    """metres between two (lat, lon)."""
    dn = math.radians(b[0] - a[0]) * F.EARTH_RADIUS
    de = math.radians(b[1] - a[1]) * F.EARTH_RADIUS * math.cos(math.radians(a[0]))
    return math.hypot(dn, de)


def make_mission(root: Path, n=5, mapping=False, yaw=-78.9):
    m = root / "FLY-20220125-1159-Blassac"
    (m / "AerialPhotography").mkdir(parents=True)
    (m / "FlightAnalytics").mkdir()
    pts = []
    for k in range(n):
        lat, lon = F.offset_latlon(LAT, LON, 20.0 * k, 0.0)
        pts.append({"VIS": {"FileName": f"VIS_{137 + k:04d}.dng", "DroneLatitude": lat, "DroneLongitude": lon,
                            "DroneAltitudeGround": 100.0, "DroneAltitudeSeaLevel": 636.7,
                            "GimbalYawDegree": f"{yaw:+.2f}", "FlightYawDegree": "+0.0"}, "NIR": []})
    (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": pts}))
    (m / "FlightAnalytics" / "mission_parameters.json").write_text(json.dumps({"camera VIS ID": "FC3170"}))
    if mapping:
        res = m / "mapping_MULTI" / "mapping_result"
        res.mkdir(parents=True)
        # camera looking down, image top towards the grid azimuth -70 deg
        a = math.radians(-70.0)
        up = np.array([math.sin(a), math.cos(a), 0.0])
        right = np.array([math.cos(a), -math.sin(a), 0.0])
        down = np.array([0.0, 0.0, -1.0])
        rot = np.vstack([right, -up, down])           # world -> camera (rows: camera axes)
        import cv2
        rvec = cv2.Rodrigues(rot)[0].ravel().tolist()
        feats = [{"type": "Feature", "properties": {"filename": "IRD_0137_2.tif", "rotation": rvec},
                  "geometry": {"type": "Point", "coordinates": [3.0, LAT, 100.0]}}]   # central meridian
        (res / "shots.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        grid = [{"lat": la, "lon": lo, "z": 556.7} for la in np.linspace(LAT - 0.002, LAT + 0.002, 9)
                for lo in np.linspace(LON - 0.002, LON + 0.003, 9)]
        (res / "ortho_dtm_grid.json").write_text(json.dumps({"points": grid}))
    return m


class GeometryTest(unittest.TestCase):
    def test_mercator_of_the_origin_and_tiles(self):
        x0, y0 = F.mercator(0, 0)
        self.assertAlmostEqual(x0, 0.0, places=6)
        self.assertAlmostEqual(y0, 0.0, places=6)
        x, y = F.mercator(LAT, LON)
        col, row = F.tile_of(x, y, 18)
        x0, yt, x1, yb = F.tile_bounds(col, row, 18)
        self.assertTrue(x0 <= x < x1 and yb < y <= yt)

    def test_calibrated_field_of_view(self):
        self.assertEqual(F.field_of_view("FC3170"), (67.8, 53.0))
        h, v = F.field_of_view("unknown")
        self.assertAlmostEqual(h, 71.6, delta=0.5)
        self.assertLess(v, h)

    def test_footprint_size_and_orientation(self):
        fov = (67.8, 53.0)
        tl, tr, br, bl = F.footprint(LAT, LON, 100.0, 0.0, fov)
        width = 2 * 100 * math.tan(math.radians(fov[0] / 2))
        self.assertAlmostEqual(distance(tl, tr), width, delta=0.2)
        self.assertGreater(tl[0], bl[0])              # yaw 0: image top to the north
        tl, tr, _, _ = F.footprint(LAT, LON, 100.0, 90.0, fov)
        self.assertGreater(tl[1], LON)                # yaw 90: top edge to the east


class MissionTest(unittest.TestCase):
    def test_track_from_the_shoot_points(self):
        m = make_mission(Path(tempfile.mkdtemp()))
        track = F.mission_track(m)
        self.assertEqual([p.number for p in track], [137, 138, 139, 140, 141])
        self.assertAlmostEqual(track[0].yaw, -78.9)
        self.assertEqual(track[0].yaw_source, "compass")
        self.assertEqual(F.camera_model(m), "FC3170")

    def test_mapping_gives_the_yaw_and_corrects_the_compass(self):
        m = make_mission(Path(tempfile.mkdtemp()), mapping=True)
        track = F.mission_track(m)
        self.assertEqual(track[0].yaw_source, "mapping")
        self.assertAlmostEqual(track[0].yaw, -70.0, delta=0.01)    # on the central meridian: no convergence
        self.assertEqual(track[1].yaw_source, "compass corrected by the mapping")
        self.assertAlmostEqual(track[1].yaw, -70.0, delta=0.01)    # same 8.9 deg compass error

    def test_ground_from_the_terrain_model(self):
        m = make_mission(Path(tempfile.mkdtemp()), mapping=True)
        track = F.mission_track(m)
        with mock.patch.object(F, "ign_ground") as ign:
            self.assertEqual(F.find_ground(m, track), "terrain model")
        ign.assert_not_called()
        self.assertAlmostEqual(track[0].above_ground, 636.7 - 556.7, delta=0.01)

    def test_offline_ground_falls_back_to_the_take_off(self):
        m = make_mission(Path(tempfile.mkdtemp()))
        track = F.mission_track(m)
        with mock.patch.object(F.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(F.find_ground(m, track), "")
        self.assertEqual(track[0].above_ground, 100.0)

    def test_no_orthophoto(self):
        self.assertIsNone(F.load_orthophoto(Path(tempfile.mkdtemp())))


class TileTest(unittest.TestCase):
    def test_offline_returns_none_without_raising(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(F.urllib.request, "urlopen", side_effect=OSError("no network")):
            self.assertIsNone(F.fetch_tile("ign", 18, 1, 2, root=root))

    def test_cached_tile_is_used_offline(self):
        root = Path(tempfile.mkdtemp())
        path = F.tile_file("esri", 18, 1, 2, root)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"jpeg")
        with mock.patch.object(F.urllib.request, "urlopen", side_effect=AssertionError("no request")):
            self.assertEqual(F.fetch_tile("esri", 18, 1, 2, root=root), b"jpeg")

    def test_default_source(self):
        self.assertEqual(F.default_source(LAT, LON), "ign")
        self.assertEqual(F.default_source(40.7, -74.0), "esri")


class MapViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import IRD_Interactive_map as MV
        self.MV = MV
        self.offline = mock.patch.object(F.urllib.request, "urlopen", side_effect=OSError("offline"))
        self.offline.start()
        self.addCleanup(self.offline.stop)

    def test_paints_and_picks_a_point_offline(self):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        m = make_mission(Path(tempfile.mkdtemp()))
        model = self.MV.map_model_for(m)
        view = self.MV.FlightMapView(model)
        view.resize(600, 400)
        view.show()
        view.fit()
        model.set_current(2)
        view.grab()                                           # paints without network
        x, y = view.to_screen(*model.xy[3])
        seen = []
        view.picked.connect(seen.append)
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(int(x), int(y)))
        self.assertEqual(seen, [3])
        self.MV.tile_cache().stop()

    def test_no_position_no_map(self):
        m = Path(tempfile.mkdtemp())
        self.assertIsNone(self.MV.map_model_for(m))


if __name__ == "__main__":
    unittest.main()
