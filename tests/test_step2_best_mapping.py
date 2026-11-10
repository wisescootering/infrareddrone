"""Step 2: the best mapping is previewed live on the time line and on the map."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IRDRONE_CACHE", tempfile.mkdtemp())

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import best_mapping as BM  # noqa: E402
import flight_timeline as FT  # noqa: E402
import IRD_Interactive_timeline as T  # noqa: E402


def make_mission(positions=True, choice=None):
    """20 frames on the ground (sync), then 80 frames at 100 m flying north 3 m apart."""
    mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Test"
    for band, n, period in (("VIS", 100, 2.0), ("NIR", 60, 3.0)):
        folder = mission / "AerialPhotography" / band
        folder.mkdir(parents=True)
        items = []
        for i in range(n):
            name = f"{band}_{i + 1:04d}.dng"
            (folder / name).write_bytes(b"")
            meta = {}
            if band == "VIS":
                height = 0.6 if i < 20 else 100.0
                meta = {"DroneAltitudeTakeOff": height, "DroneAltitudeGround": height, "GimbalYawDegree": 0.0}
                if positions:
                    meta.update({"DroneLatitude": 45.0 + max(0, i - 20) * 3.0 / 111195.0, "DroneLongitude": 3.0})
            (folder / name).with_suffix(".exif").write_text(json.dumps(meta))
            items.append({"img_path": name, "relative_timeline": i * period})
        (folder / "time_line.json").write_text(json.dumps({band: items}))
    if choice is not None:
        BM.save_choice(mission, **choice)
    return mission


def open_dialog(mission):
    with mock.patch.object(T.AnalysisThread, "start"):
        dialog = T.FlightTimelineDialog(mission)
    vis = FT.BandAnalysis("VIS", FT.list_frames(mission, "VIS"))
    nir = FT.BandAnalysis("NIR", FT.list_frames(mission, "NIR"))
    proposal = FT.TimelineProposal(FT.Window(5, 15), FT.Window(3, 10), FT.Window(20, 99), FT.Window(13, 59), 0.0)
    dialog._on_analysed((vis, nir, proposal))
    return dialog


class Step2BestMappingTest(unittest.TestCase):
    def test_preview_keeps_a_few_survey_images(self):
        d = open_dialog(make_mission())
        kept = d.model.bm_selected
        self.assertTrue(d.bm_check.isChecked())
        self.assertEqual(d.bm_overlap.value(), 75)
        self.assertGreater(len(kept), 2)
        self.assertLess(len(kept), 30)
        self.assertTrue(all(20 <= i <= 99 for i in kept))
        self.assertEqual((kept[0], kept[-1]), (20, 99))
        self.assertIn(f"{len(kept)}</b> of 80 survey images", d.bm_summary.text())

    def test_map_shows_the_footprints_of_the_images_kept(self):
        d = open_dialog(make_mission())
        self.assertIsNotNone(d.map_model)
        self.assertEqual(len(d.map_model.selection), len(d.model.bm_selected))
        d.map_view.picked.emit(d._map_index[50])
        self.assertEqual(d.map_model.current, d._map_index[50])
        self.assertIn("VIS_0051", d.pv_vis_cap.text())

    def test_overlap_and_survey_edits_update_the_selection(self):
        d = open_dialog(make_mission())
        before = len(d.model.bm_selected)
        d.bm_overlap.setValue(90)
        self.assertGreater(len(d.model.bm_selected), before)
        d._on_nudge("VIS survey", "last", -40)
        self.assertTrue(all(i <= 59 for i in d.model.bm_selected))
        self.assertEqual(len(d.map_model.selection), len(d.model.bm_selected))

    def test_disabled_keeps_everything(self):
        d = open_dialog(make_mission(choice={"enabled": False, "overlap": 0.8}))
        self.assertFalse(d.bm_check.isChecked())
        self.assertEqual(d.bm_overlap.value(), 80)
        self.assertEqual(d.model.bm_selected, [])
        self.assertIn("All the 80 survey images", d.bm_summary.text())

    def test_without_positions_no_map_and_everything_kept(self):
        d = open_dialog(make_mission(positions=False))
        self.assertIsNone(d.map_model)
        self.assertEqual(d.model.bm_selected, list(range(20, 100)))
        self.assertIn("No position", d.bm_summary.text())

    def test_confirm_saves_the_choice(self):
        mission = make_mission()
        d = open_dialog(mission)
        d.bm_overlap.setValue(80)
        d._confirm("close")
        self.assertEqual(BM.load_choice(mission), {"enabled": True, "overlap": 0.8})
        saved = json.loads((mission / BM.CHOICE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["preview_selected"], [d.model.vis.frames[i].name for i in d.model.bm_selected])

    def test_close_saves_and_reset_keeps_the_window_open(self):
        mission = make_mission()
        d = open_dialog(mission)
        self.assertEqual(d.btn_close.text(), "Save and close")      # never saved
        self.assertTrue(d.btn_reset.isHidden())                     # the detection as it is
        d.bm_overlap.setValue(80)
        d._on_nudge("VIS survey", "last", -40)
        self.assertFalse(d.btn_reset.isHidden())
        d.btn_reset.click()
        self.assertEqual(d.model.windows["VIS survey"], d.model.proposal.vis_survey)
        self.assertTrue(d.btn_reset.isHidden())
        self.assertEqual(d.result(), 0)                  # still open
        d.btn_close.click()
        self.assertEqual((d.result(), d.action), (d.DialogCode.Accepted, "close"))
        self.assertEqual(BM.load_choice(mission), {"enabled": True, "overlap": 0.8})
        again = open_dialog(mission)                     # saved: Close until something changes
        self.assertEqual(again.btn_close.text(), "Close")
        again.bm_overlap.setValue(85)
        self.assertEqual(again.btn_close.text(), "Save and close")
        again.bm_overlap.setValue(80)
        self.assertEqual(again.btn_close.text(), "Close")

    def test_closing_during_the_analysis_saves_nothing(self):
        mission = make_mission()
        with mock.patch.object(T.AnalysisThread, "start"):
            d = T.FlightTimelineDialog(mission)
        d.reject()
        self.assertEqual(d.result(), d.DialogCode.Rejected)
        self.assertFalse((mission / BM.CHOICE_FILE).exists())

    def test_controls_have_tool_tips(self):
        d = open_dialog(make_mission())
        for widget in (d.bm_check, d.bm_overlap):
            self.assertTrue(widget.toolTip().strip())


if __name__ == "__main__":
    unittest.main()
