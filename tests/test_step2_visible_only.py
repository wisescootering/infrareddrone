"""Step 2 of a visible only mission: the survey phase only (no target, no
synchronisation, no infrared), and the visible shoot points Steps 4 to 6 read
instead of the Step 3 pairs."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IRDRONE_CACHE", tempfile.mkdtemp())

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import flight_timeline as FT  # noqa: E402
import IRD_Interactive_timeline as T  # noqa: E402
import mission_type as MT  # noqa: E402
import visible_mission as VM  # noqa: E402


def make_visible_mission(n=60):
    """20 frames on the ground, then n - 20 frames at 100 m flying north 3 m apart; no NIR folder."""
    mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Visible"
    folder = mission / "AerialPhotography" / "VIS"
    folder.mkdir(parents=True)
    (mission / "FlightAnalytics").mkdir()
    (mission / "FlightAnalytics" / "mission_parameters.json").write_text(
        json.dumps({"File path mission": str(mission), MT.KEY: MT.VISIBLE}))
    items = []
    for i in range(n):
        name = f"VIS_{i + 1:04d}.dng"
        (folder / name).write_bytes(b"")
        height = 0.6 if i < 20 else 100.0
        (folder / name).with_suffix(".exif").write_text(json.dumps({
            "FileName": name, "Directory": str(folder), "RelativeTimeLine": 2.0 * i,
            "DroneAltitudeTakeOff": height, "DroneAltitudeGround": height, "GimbalYawDegree": 0.0,
            "DroneLatitude": 45.0 + max(0, i - 20) * 3.0 / 111195.0, "DroneLongitude": 3.0,
            "UTM_x": 500000.0, "UTM_y": 4980000.0 + 3.0 * max(0, i - 20), "UTM_zone": 31,
            "Model": "FC3170"}))
        items.append({"img_path": name, "relative_timeline": 2.0 * i})
    (folder / "time_line.json").write_text(json.dumps({"VIS": items}))
    return mission


class AnalysisTest(unittest.TestCase):
    def test_no_target_detection_no_sync_window(self):
        mission = make_visible_mission()
        with mock.patch.object(FT, "read_preview", return_value=None), \
                mock.patch.object(FT, "detect_mobile_marker") as detect:
            vis, nir, proposal = FT.analyse_mission(mission)
        detect.assert_not_called()
        self.assertEqual(nir.frames, [])
        self.assertIsNone(proposal.vis_sync)
        self.assertIsNone(proposal.nir_sync)
        self.assertIsNone(proposal.time_shift)
        self.assertEqual((proposal.vis_survey.first, proposal.vis_survey.last), (20, 59))
        self.assertFalse(any("target" in m for m in proposal.messages))


class ShootPointsTest(unittest.TestCase):
    def test_one_point_per_visible_image_no_infrared(self):
        mission = make_visible_mission(30)
        path = VM.write_shoot_points(mission)
        data = json.loads(path.read_text())
        self.assertEqual(path, mission / "AerialPhotography" / "shoot_points.json")
        self.assertEqual((data["n_VIS"], data["n_NIR"], data["pairing_method"]), (30, 0, "visible_only"))
        self.assertEqual(len(data["shoot_points"]), 30)
        first = data["shoot_points"][0]
        self.assertEqual(first["NIR"], [])
        self.assertEqual(first["VIS"]["idx"], 0)
        self.assertEqual(first["VIS"]["FileName"], "VIS_0001.dng")
        self.assertEqual(list(first["VIS"])[1:], list(VM.VIS_KEYS))   # the keys of the Step 3 pairs
        self.assertNotIn("Model", first["VIS"])

    def test_no_side_car_no_shoot_points(self):
        mission = Path(tempfile.mkdtemp())
        with self.assertRaises(FileNotFoundError):
            VM.write_shoot_points(mission)


class DialogTest(unittest.TestCase):
    def open_dialog(self, mission):
        with mock.patch.object(T.AnalysisThread, "start"):
            dialog = T.FlightTimelineDialog(mission)
        vis = FT.BandAnalysis("VIS", FT.list_frames(mission, "VIS"))
        nir = FT.BandAnalysis("NIR", [])
        proposal = FT.TimelineProposal(None, None, FT.Window(20, 59), None, None)
        dialog._on_analysed((vis, nir, proposal))
        return dialog

    def test_survey_only_and_confirm_writes_the_shoot_points(self):
        mission = make_visible_mission()
        d = self.open_dialog(mission)
        self.assertTrue(d.visible_only)
        self.assertTrue(all(c.isHidden() for c in d.cards if c.phase == "sync"))
        self.assertTrue(d.pv_nir.isHidden())
        self.assertTrue(d.btn_classic.isHidden())
        self.assertIn("development", d.btn_confirm.text())
        self.assertEqual(d.selected, ("survey", "first"))
        self.assertIn("of 40 survey images", d.bm_summary.text())
        self.assertIn("less to develop", d.bm_summary.text())
        self.assertIsNone(d._not_ready())
        d.view.resize(900, d.view.sizeHint().height())
        d.view.grab()                                  # paints without the infrared rows
        self.assertLess(d.view.sizeHint().height(), T.TimelineView.LANE_H * 2 + T.TimelineView.CHART_H)
        d._confirm("step3")
        self.assertEqual(d.action, "step3")
        points = json.loads((mission / VM.SHOOT_POINTS).read_text())["shoot_points"]
        self.assertEqual(len(points), 60)
        fly = json.loads((mission / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").read_text())["fly"]
        self.assertEqual(fly["listCopiedImages"][0], "VIS_0021.dng")
        self.assertFalse((mission / "AerialPhotography" / "NIR" / "transfer_info_NIR_dng.json").exists())

    def test_survey_needed(self):
        d = self.open_dialog(make_visible_mission())
        d.model.windows["VIS survey"] = None
        self.assertIn("VIS survey", d._not_ready())


if __name__ == "__main__":
    unittest.main()
