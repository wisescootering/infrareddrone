"""Step 4: the best mapping choice of Step 2 aligns only the images the map needs."""
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

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_4 as S4  # noqa: E402
import best_mapping  # noqa: E402


def mission(points=60, step=3.0, choice=None):
    m = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
    (m / "AerialPhotography" / "VIS").mkdir(parents=True)
    shoot_points = [
        {"VIS": {"FileName": f"VIS_{n:04d}.dng", "DroneLatitude": 45.0 + n * step / 111195.0,
                 "DroneLongitude": 3.0, "DroneAltitudeGround": 100.0, "GimbalYawDegree": 0.0},
         "NIR": [{"rank": 1, "dt": 0.1 if n % 5 else 0.9}]}
        for n in range(1, points + 1)
    ]
    (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": shoot_points}))
    (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
        {"fly": {"listCopiedImages": [p["VIS"]["FileName"] for p in shoot_points]}}))
    if choice is not None:
        best_mapping.save_choice(m, **choice)
    return m


class Step4BestMappingTest(unittest.TestCase):
    def dialog(self, **kwargs):
        return S4.DialogImageProcessing({"File path mission": str(mission(**kwargs))})

    def test_enabled_by_default_and_counted(self):
        d = self.dialog()
        self.assertTrue(d.best_mapping_radio.isChecked())
        self.assertFalse(d.all_images_radio.isChecked())
        self.assertEqual(d.best_mapping_overlap.value(), 75)
        kept, synchronised = d.best_mapping_selection()
        self.assertEqual(synchronised, 48)
        self.assertLess(kept, synchronised // 3)
        self.assertIn(f"{kept} of 48", d.best_mapping_count.text())

    def test_choice_of_step2_is_used(self):
        d = self.dialog(choice={"enabled": False, "overlap": 0.9})
        self.assertTrue(d.all_images_radio.isChecked())
        self.assertEqual(d.best_mapping_overlap.value(), 90)
        self.assertFalse(d.best_mapping_overlap.isEnabled())
        self.assertEqual(d.best_mapping_selection(), (48, 48))
        d.best_mapping_radio.setChecked(True)
        self.assertFalse(d.all_images_radio.isChecked())
        self.assertLess(d.best_mapping_selection()[0], 48)

    def test_run_passes_the_overlap_and_saves_the_choice(self):
        d = self.dialog()
        d.best_mapping_overlap.setValue(80)
        with mock.patch.object(d.process, "start") as start:
            d._start_processing()
        arguments = start.call_args[0][1]
        self.assertEqual(arguments[arguments.index("--best-mapping-overlap") + 1], "80")
        self.assertEqual(best_mapping.load_choice(d.mission_folder), {"enabled": True, "overlap": 0.8})
        saved = json.loads((d.mission_folder / best_mapping.CHOICE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["step4_selected"]), d.best_mapping_selection()[0])
        self.assertEqual(best_mapping.planned_numbers(d.mission_folder),
                         {int(name[4:8]) for name in saved["step4_selected"]})

    def test_run_without_best_mapping(self):
        d = self.dialog()
        d.all_images_radio.setChecked(True)
        self.assertFalse(d.best_mapping_radio.isChecked())
        with mock.patch.object(d.process, "start") as start:
            d._start_processing()
        self.assertNotIn("--best-mapping-overlap", start.call_args[0][1])
        self.assertFalse(best_mapping.load_choice(d.mission_folder)["enabled"])

    def test_map_shows_the_shoot_points_aligned(self):
        d = self.dialog()
        self.assertIsNotNone(d.map_view)
        kept, _ = d.best_mapping_selection()
        self.assertEqual(len(d.map_model.selection), kept)
        flags = d._aligned_flags()
        self.assertEqual(sum(flags.values()), 48)                  # every fifth pair badly synchronised
        d.best_mapping_overlap.setValue(90)
        self.assertEqual(len(d.map_model.selection), d.best_mapping_selection()[0])
        d.end_image_number.setValue(30)
        self.assertTrue(all(d.map_model.numbers[i] <= 30 for i in d.map_model.selection))
        d.all_images_radio.setChecked(True)
        self.assertEqual(d.map_model.selection, [])
        d.map_view.grab()

    def test_no_map_without_positions(self):
        m = mission()
        data = json.loads((m / "AerialPhotography" / "shoot_points.json").read_text())
        for point in data["shoot_points"]:
            del point["VIS"]["DroneLatitude"]
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(data))
        d = S4.DialogImageProcessing({"File path mission": str(m)})
        self.assertIsNone(d.map_view)
        self.assertEqual(d.best_mapping_selection()[1], 48)

    def test_options_have_tool_tips(self):
        d = self.dialog()
        for widget in (d.best_mapping_radio, d.all_images_radio, d.best_mapping_overlap):
            self.assertTrue(widget.toolTip().strip())


if __name__ == "__main__":
    unittest.main()
