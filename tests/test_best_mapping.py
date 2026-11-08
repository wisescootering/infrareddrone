"""Best mapping: the images kept for the map (irdrone_wizard/best_mapping.py)."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import best_mapping as B  # noqa: E402

FOV = (67.8, 53.0)
LAT0, LON0 = 45.0, 3.0


def north_of(metres):
    return LAT0 + math.degrees(metres / B.EARTH_RADIUS)


def east_of(metres):
    return LON0 + math.degrees(metres / (B.EARTH_RADIUS * math.cos(math.radians(LAT0))))


def line(n, step, height=100.0, yaw=0.0, east=False, eligible=None):
    """n shots `step` metres apart, flying north (or east), image top to `yaw`."""
    out = []
    for i in range(n):
        lat, lon = (LAT0, east_of(i * step)) if east else (north_of(i * step), LON0)
        ok = True if eligible is None else eligible(i)
        out.append(B.Shot(i, lat, lon, height, yaw, ok))
    return out


class OverlapTests(unittest.TestCase):
    def test_forward_motion_is_the_legacy_criterion(self):
        length = B.footprint_size(100.0, FOV)[1]
        a, b = line(2, 0.25 * length)
        self.assertAlmostEqual(B.overlap(a, b, FOV), 0.75, places=3)

    def test_lateral_motion_uses_the_image_width(self):
        width = B.footprint_size(100.0, FOV)[0]
        a, b = line(2, 0.25 * width, east=True)       # image top to the north, flying east
        self.assertAlmostEqual(B.overlap(a, b, FOV), 0.75, places=3)

    def test_unknown_height_or_position(self):
        a, b = line(2, 10)
        b.height = None
        self.assertIsNone(B.overlap(a, b, FOV))
        b.height, b.lat = 100.0, None
        self.assertIsNone(B.overlap(a, b, FOV))

    def test_on_the_ground_is_unknown(self):
        a, b = line(2, 1, height=1.0)
        self.assertIsNone(B.overlap(a, b, FOV))


class SelectTests(unittest.TestCase):
    def test_kept_images_overlap_by_the_target(self):
        shots = line(100, 3.0)
        kept = B.select(shots, 0.75, FOV)
        self.assertEqual(kept[0], 0)
        self.assertEqual(kept[-1], 99)              # the end of the survey
        self.assertLess(len(kept), 30)
        for a, b in zip(kept, kept[1:]):
            self.assertGreaterEqual(B.overlap(shots[a], shots[b], FOV), 0.75 - 1e-9)
        # ... and no more than needed: the next image would be under the target
        for a, b in zip(kept, kept[1:-1]):
            self.assertLess(B.overlap(shots[a], shots[b + 1], FOV), 0.75)

    def test_higher_overlap_keeps_more(self):
        shots = line(100, 3.0)
        counts = [len(B.select(shots, ov, FOV)) for ov in (0.6, 0.75, 0.9)]
        self.assertEqual(counts, sorted(counts))
        self.assertLess(counts[0], counts[2])

    def test_selection_of_a_selection_is_the_same(self):
        shots = line(120, 2.5)
        kept = B.select(shots, 0.75, FOV)
        again = [B.Shot(s.key, s.lat, s.lon, s.height, s.yaw, i in kept) for i, s in enumerate(shots)]
        self.assertEqual(B.select(again, 0.75, FOV), kept)

    def test_ineligible_images_are_never_kept(self):
        shots = line(100, 3.0, eligible=lambda i: i % 2 == 0)
        kept = B.select(shots, 0.75, FOV)
        self.assertTrue(all(i % 2 == 0 for i in kept))

    def test_too_far_apart_keeps_everything(self):
        shots = line(10, 500.0)
        self.assertEqual(B.select(shots, 0.75, FOV), list(range(10)))

    def test_unknown_overlap_keeps_the_image(self):
        shots = line(20, 1.0)
        shots[10].height = None
        self.assertIn(10, B.select(shots, 0.75, FOV))

    def test_empty(self):
        self.assertEqual(B.select([], 0.75, FOV), [])
        self.assertEqual(B.select(line(5, 1, eligible=lambda i: False), 0.75, FOV), [])


def shoot_point(i, step, dt):
    return {"VIS": {"FileName": f"VIS_{i + 1:04d}.dng", "DroneLatitude": north_of(i * step),
                    "DroneLongitude": LON0, "DroneAltitudeGround": "100.0", "GimbalYawDegree": "+0.0"},
            "NIR": [{"rank": 1, "dt": dt}, {"rank": 2, "dt": 2.0}]}


class ShootPointTests(unittest.TestCase):
    def test_badly_synchronised_pairs_count_for_the_motion_but_are_not_kept(self):
        points = [shoot_point(i, 3.0, 0.1 if i % 3 else 0.9) for i in range(60)]
        flags = [abs(B.rank_one_dt(p)) < 0.5 for p in points]
        kept = B.select_shoot_points(points, 0.75, FOV, flags)
        self.assertTrue(kept)
        self.assertTrue(all(abs(B.rank_one_dt(p)) < 0.5 for p in kept))
        self.assertLess(len(kept), sum(flags))

    def test_rank_one_dt(self):
        self.assertEqual(B.rank_one_dt(shoot_point(0, 1, -0.25)), -0.25)
        self.assertIsNone(B.rank_one_dt({"NIR": [{"rank": 2, "dt": 1}]}))
        self.assertIsNone(B.rank_one_dt({"NIR": [{"rank": 1, "dt": True}]}))


class ChoiceTests(unittest.TestCase):
    def test_default_is_enabled_at_75_percent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(B.load_choice(Path(d)),
                             {"enabled": True, "overlap": 0.75})

    def test_saved_and_merged(self):
        with tempfile.TemporaryDirectory() as d:
            B.save_choice(Path(d), enabled=False, overlap=80)
            B.save_choice(Path(d), selected=["VIS_0001.dng"])
            self.assertEqual(B.load_choice(Path(d)), {"enabled": False, "overlap": 0.8})
            data = json.loads((Path(d) / B.CHOICE_FILE).read_text(encoding="utf-8"))
            self.assertEqual(data["selected"], ["VIS_0001.dng"])

    def test_invalid_file_gives_the_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / B.CHOICE_FILE
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertTrue(B.load_choice(Path(d))["enabled"])
            path.write_text(json.dumps({"enabled": "yes", "overlap": 3}), encoding="utf-8")
            self.assertEqual(B.load_choice(Path(d))["overlap"], B.MIN_OVERLAP)


class PlannedNumbersTests(unittest.TestCase):
    """The images kept by the best mapping, drawn on the main window map."""

    def mission(self, n=100):
        m = Path(tempfile.mkdtemp())
        vis = m / "AerialPhotography" / "VIS"
        vis.mkdir(parents=True)
        for i in range(n):
            (vis / f"VIS_{i + 1:04d}.exif").write_text(json.dumps(
                {"DroneLatitude": north_of(i * 3.0), "DroneLongitude": LON0,
                 "DroneAltitudeGround": 100.0, "GimbalYawDegree": 0.0}))
        (m / "FlightAnalytics").mkdir()
        (m / "FlightAnalytics" / "flight_timeline.json").write_text(json.dumps(
            {"confirmed": {"VIS survey": ["VIS_0011.dng", "VIS_0090.dng"]}}))
        return m

    def test_selection_of_the_survey_when_nothing_saved(self):
        m = self.mission()
        planned = B.planned_numbers(m)
        self.assertEqual((min(planned), max(planned)), (11, 90))
        self.assertLess(len(planned), 30)
        B.save_choice(m, overlap=0.9)
        self.assertGreater(len(B.planned_numbers(m)), len(planned))

    def test_step4_then_step2_selection(self):
        m = self.mission()
        B.save_choice(m, preview_selected=["VIS_0011.dng", "VIS_0050.dng"])
        self.assertEqual(B.planned_numbers(m), {11, 50})
        B.save_choice(m, step4_selected=["VIS_0012.dng", "VIS_0051.dng"])
        self.assertEqual(B.planned_numbers(m), {12, 51})

    def test_off_or_no_survey(self):
        m = self.mission()
        B.save_choice(m, enabled=False, step4_selected=["VIS_0012.dng"])
        self.assertEqual(B.planned_numbers(m), set())
        self.assertEqual(B.planned_numbers(Path(tempfile.mkdtemp())), set())


if __name__ == "__main__":
    unittest.main()
