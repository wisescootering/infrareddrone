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


def step4_done(m: Path, numbers, failed=(), dt=None):
    """Step 4 inventory (ImgIRdrone/shoot_points.json) and the flight list of Step 1."""
    dt = dt or {}
    (m / "ImgIRdrone").mkdir()
    (m / "ImgIRdrone" / "shoot_points.json").write_text(json.dumps({"shoot_points": [
        {"FileName": f"VIS_{n:04d}.dng", "dt": dt.get(n, 0.1), "failed": n in failed} for n in numbers]}))
    (m / "AerialPhotography" / "VIS").mkdir(exist_ok=True)
    (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
        {"fly": {"listCopiedImages": [f"VIS_{n:04d}.dng" for n in numbers]}}))


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

    def test_sparse_trajectory_of_the_mapping_orthophoto_shown_or_not(self):
        """Main window, the mapping done: only the shoot points used by the
        mapping are drawn and picked, orthophoto shown or not; their footprints
        while it is hidden."""
        m = make_mission(Path(tempfile.mkdtemp()), n=7)
        (m / "mapping_MULTI" / "mapping_result").mkdir(parents=True)
        (m / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps(
            {"image_quartets": [{"VIS_filename": f"VIS_{n:04d}.dng"} for n in (137, 140, 143)]}))
        self.assertEqual(F.mapped_numbers(m), {137, 140, 143})
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertEqual(model.mapped, [])                          # no orthophoto: not a mapping done
        F.orthophoto_path(m).write_bytes(b"")
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertEqual((model.mapped_by, model.visible()), ("mapping", [0, 3, 6]))   # not loaded yet
        self.assertEqual(model.footprints_kept(), [0, 3, 6])
        rgba = np.zeros((4, 4, 4), np.uint8)
        model.set_ortho(F.OrthoPreview(rgba, rgba, [(LAT, LON), (LAT, LON + 1e-3), (LAT - 1e-3, LON)]))
        model.set_ortho_mode("natural")
        self.assertTrue(model.sparse)
        self.assertEqual(model.visible(), [0, 3, 6])
        view = self.MV.FlightMapView(model)
        view.resize(600, 400)
        view.show()
        view.fit()
        view.grab()
        x, y = view.to_screen(*model.xy[1])
        self.assertIsNone(view.nearest(x, y, radius=3))              # not used by the mapping
        x, y = view.to_screen(*model.xy[3])
        self.assertEqual(view.nearest(x, y), 3)
        self.assertEqual(model.footprints_kept(), [])                # on the orthophoto: no footprints
        model.set_ortho_mode("hidden")                               # orthophoto hidden: still the mapping
        self.assertEqual(model.visible(), [0, 3, 6])
        self.assertEqual(model.footprints_kept(), [0, 3, 6])
        # the review keeps every shoot point
        self.assertEqual(self.MV.map_model_for(m, with_ortho=False).mapped, [])
        self.MV.tile_cache().stop()

    def test_sparse_trajectory_of_the_best_mapping_before_the_mapping(self):
        """Main window, before Step 5: the shoot points kept by the best
        mapping, with their footprints; Layers ▾ shows every image again."""
        import best_mapping as BM
        m = make_mission(Path(tempfile.mkdtemp()), n=7)
        BM.save_choice(m, step4_selected=[f"VIS_{n:04d}.dng" for n in (137, 140, 143)])
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertTrue(model.planned and model.sparse)
        self.assertEqual(model.visible(), [0, 3, 6])
        self.assertEqual(model.footprints_kept(), [0, 3, 6])
        view = self.MV.FlightMapView(model)
        view.resize(600, 400)
        view.show()
        view.fit()
        view.grab()
        self.assertTrue(view.act_mapped.isChecked())
        view.act_mapped.trigger()                                    # every image again
        self.assertEqual(model.visible(), list(range(7)))
        self.assertEqual(model.footprints_kept(), [])
        # best mapping off: the whole flight
        BM.save_choice(m, enabled=False)
        self.assertEqual(self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True).mapped, [])
        # the mapping done: its images, not the plan
        BM.save_choice(m, enabled=True)
        (m / "mapping_MULTI" / "mapping_result").mkdir(parents=True)
        (m / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps(
            {"image_quartets": [{"VIS_filename": "VIS_0138.dng"}]}))
        F.orthophoto_path(m).write_bytes(b"")
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertEqual((model.mapped, model.planned, model.sparse), ([1], False, True))
        self.MV.tile_cache().stop()

    def test_main_map_after_step4_shows_the_points_as_the_review(self):
        """Main window, after Step 4, before the map of Step 5: every shoot
        point in the colour of its review status, the ones Step 4 did not
        align as small grey dots (as in the review), nothing thinned out."""
        import cv2
        import shoot_review as R
        import IRD_Interactive_review as Rv
        m = make_mission(Path(tempfile.mkdtemp()), n=7)
        step4_done(m, (137, 138, 140, 141, 142, 143), failed={141})        # 139 left out by Step 4
        img = np.full((30, 40, 3), 128, np.uint8)
        for n in (137, 138):                                              # their images: not measured yet
            cv2.imwrite(str(m / "ImgIRdrone" / f"VIS_{n:04d}.jpg"), img)
            cv2.imwrite(str(m / "ImgIRdrone" / f"VIR_{n:04d}_local.jpg"), img)
        statuses = R.statuses(m)
        self.assertEqual(statuses, {137: "unknown", 138: "unknown", 140: "missing", 141: "flagged",
                                    142: "missing", 143: "missing"})
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertFalse(model.sparse)
        self.assertEqual(model.visible(), list(range(7)))                 # every point, like the review
        for i, n in enumerate(model.numbers):
            expected = Rv.STATUS_COLORS[statuses[n]] if n in statuses else Rv.NOT_ALIGNED_COLOR
            self.assertEqual(model.color_of(i).name(), expected.name(), n)
        self.assertTrue(model.minor(model.index_of(139)))                 # not aligned: small grey dot
        self.assertFalse(model.minor(model.index_of(137)))
        self.assertFalse(model.minor(model.index_of(141)))
        view = self.MV.FlightMapView(model)
        view.resize(600, 400)
        view.show()
        view.fit()
        view.grab()                                                       # paints
        self.assertIsNone(R.statuses(m.parent / "nothing"))              # before Step 4
        self.MV.tile_cache().stop()

    def test_main_map_once_the_map_is_built_is_still_the_twin_of_the_review(self):
        """The map of Step 5 built from some of the points: the main window
        still shows every point of the review (its orthophoto underneath)."""
        import shoot_review as R
        m = make_mission(Path(tempfile.mkdtemp()), n=7)
        step4_done(m, range(137, 144), failed={141})
        (m / "mapping_MULTI" / "mapping_result").mkdir(parents=True)
        (m / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps({
            "image_quartets": [{"VIS_filename": f"VIS_{n:04d}.dng"} for n in (137, 143)]}))
        F.orthophoto_path(m).write_bytes(b"")
        model = self.MV.map_model_for(m, with_ortho=False, sparse_mapping=True)
        self.assertFalse(model.sparse)
        self.assertEqual(model.visible(), list(range(7)))
        self.assertEqual({n for i, n in enumerate(model.numbers) if not model.minor(i)},
                         {n for n, s in R.statuses(m).items() if s != "missing"})
        self.MV.tile_cache().stop()

    def test_the_aligned_image_in_its_footprint_is_not_tinted(self):
        from PyQt6.QtGui import QColor, QPixmap
        m = make_mission(Path(tempfile.mkdtemp()))
        model = self.MV.map_model_for(m, with_ortho=False)
        pix = QPixmap(40, 30)
        pix.fill(QColor("#808080"))
        model.image_of = lambda _n: pix
        model.cursor_in_point_color = True
        model.color_of = lambda _i: QColor("#B03A2E")
        view = self.MV.FlightMapView(model)
        view.resize(600, 400)
        view.show()
        view.fit()
        view.res /= 4                                          # zoom on the image
        model.set_current(2)
        view.center = model.xy[2]
        x, y = view.to_screen(*model.xy[2])
        img = view.grab().toImage()
        c = img.pixelColor(int(x) + 25, int(y) + 12)            # inside the image, off the dot
        self.assertLessEqual(c.red() - min(c.green(), c.blue()), 2)       # still grey: no red tint
        self.MV.tile_cache().stop()

    def test_images_of_the_mapping_from_the_odm_shots(self):
        m = make_mission(Path(tempfile.mkdtemp()), mapping=True)
        self.assertEqual(F.mapped_numbers(m), {137})
        self.assertEqual(F.mapped_numbers(Path(tempfile.mkdtemp())), set())

    def test_no_position_no_map(self):
        m = Path(tempfile.mkdtemp())
        self.assertIsNone(self.MV.map_model_for(m))


if __name__ == "__main__":
    unittest.main()
