"""Review (Step 5) of a visible only mission: the developed visible images, to
check (no misalignment to measure), flagged when bad, nothing to realign."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import mission_type as MT  # noqa: E402
import shoot_review as R  # noqa: E402


def visible_mission(numbers=(140, 141, 142), developed=(140, 141, 142)):
    mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Visible"
    out = mission / "ImgIRdrone"
    out.mkdir(parents=True)
    (mission / "FlightAnalytics").mkdir()
    (mission / "FlightAnalytics" / "mission_parameters.json").write_text(
        json.dumps({"File path mission": str(mission), MT.KEY: MT.VISIBLE}))
    rng = np.random.default_rng(0)
    for n in developed:
        cv2.imwrite(str(out / f"VIS_{n:04d}.jpg"), (rng.random((60, 80, 3)) * 255).astype(np.uint8))
    (out / "shoot_points.json").write_text(json.dumps({"shoot_points": [
        {"FileName": f"VIS_{n:04d}.dng", "dt": 0.0, "failed": False} for n in developed]}))
    (mission / "AerialPhotography").mkdir()
    (mission / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": [
        {"VIS": {"FileName": f"VIS_{n:04d}.dng", "RelativeTimeLine": 2.0 * n, "DroneAltitudeGround": 100.0},
         "NIR": []} for n in numbers]}))
    return mission


class ModelTest(unittest.TestCase):
    def test_developed_points_are_to_check_not_missing(self):
        review = R.load_review(visible_mission(developed=(140, 141)))
        self.assertTrue(all(p.visible_only for p in review.points))
        self.assertEqual([p.status for p in review.points], [R.STATUS_UNKNOWN] * 2)
        p = review.points[0]
        p.checked = True
        self.assertEqual(p.status, R.STATUS_OK)
        p.failed = True
        self.assertEqual(p.status, R.STATUS_FLAGGED)
        p.vis_image, p.failed = None, False
        self.assertEqual(p.status, R.STATUS_MISSING)

    def test_points_left_out_can_be_developed_on_request(self):
        review = R.load_review(visible_mission(developed=(140,)))
        left = R.not_aligned_pairs(review)
        self.assertEqual(set(left), {141, 142})
        self.assertTrue(all(v["alignable"] and v["dt"] is None for v in left.values()))

    def test_point_image_falls_back_on_the_visible_image(self):
        out = visible_mission() / "ImgIRdrone"
        self.assertIsNone(R.aligned_image(out, 140))
        self.assertEqual(R.point_image(out, 140), out / "VIS_0140.jpg")
        self.assertIsNone(R.point_image(out, 999))


class WindowTest(unittest.TestCase):
    def dialog(self, mission):
        import IRD_Interactive_review as RV
        d = RV.ReviewDialog(mission)
        d.scan.wait(10000)
        APP.processEvents()
        self.addCleanup(d.done, 0)
        return d

    def test_image_alone_good_and_flag(self):
        import IRD_Interactive_review as RV
        mission = visible_mission()
        d = self.dialog(mission)
        self.assertIn("developed", d.windowTitle())
        self.assertEqual(d.view.mode, "visible")
        self.assertEqual([m[0] for m in d.modes], ["visible", "map"])
        self.assertFalse(d.btn_good.isHidden())
        self.assertTrue(d.btn_redo.isHidden())
        self.assertTrue(d.gauge.isHidden())
        self.assertNotIn("REDO", d.point_info.text())
        self.assertTrue(d.btn_open.isEnabled())                 # the visible image opens full size
        self.assertIn("To check", d.point_status.text())
        first = d.current()
        d._confirm_key()                                        # Y: good, then the next to check
        self.assertTrue(first.checked)
        self.assertEqual(first.status, R.STATUS_OK)
        self.assertNotEqual(d.current().number, first.number)
        saved = json.loads((mission / "ImgIRdrone" / R.REVIEW_FILE).read_text())
        self.assertIn(first.label, saved["checked"])
        d.toggle_flag()
        inventory = json.loads((mission / "ImgIRdrone" / "shoot_points.json").read_text())
        self.assertEqual(sum(p["failed"] for p in inventory["shoot_points"]), 1)
        self.assertFalse(d.btn_good.isEnabled())                # flagged: not good
        self.assertIn("checked", d.chips[R.STATUS_OK].text())
        d.set_mode("overlay")                                   # not a mode of this mission: ignored
        self.assertEqual(d.view.mode, "visible")
        self.assertEqual(RV.VISIBLE_STATUS_TEXT[R.STATUS_UNKNOWN], "To check")

    def test_points_left_out_are_developed_from_the_map(self):
        d = self.dialog(visible_mission(developed=(140,)))
        stem, detail, action, possible = d.map_menu_content(141)
        self.assertEqual((stem, detail, action, possible), ("VIS_0141", "Not developed by Step 4",
                                                             "Develop this point", True))
        self.assertIsNone(d.map_menu_content(140))


if __name__ == "__main__":
    unittest.main()
