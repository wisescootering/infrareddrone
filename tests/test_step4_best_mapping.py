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
        self.assertTrue(d.best_mapping_checkbox.isChecked())
        self.assertEqual(d.best_mapping_overlap.value(), 75)
        kept, synchronised = d.best_mapping_selection()
        self.assertEqual(synchronised, 48)
        self.assertLess(kept, synchronised // 3)
        self.assertIn(f"{kept} of 48", d.best_mapping_count.text())

    def test_choice_of_step2_is_used(self):
        d = self.dialog(choice={"enabled": False, "overlap": 0.9})
        self.assertFalse(d.best_mapping_checkbox.isChecked())
        self.assertEqual(d.best_mapping_overlap.value(), 90)
        self.assertFalse(d.best_mapping_overlap.isEnabled())
        self.assertEqual(d.best_mapping_selection(), (48, 48))
        d.best_mapping_checkbox.setChecked(True)
        self.assertLess(d.best_mapping_selection()[0], 48)

    def test_run_passes_the_overlap_and_saves_the_choice(self):
        d = self.dialog()
        d.best_mapping_overlap.setValue(80)
        with mock.patch.object(d.process, "start") as start:
            d._start_processing()
        arguments = start.call_args[0][1]
        self.assertEqual(arguments[arguments.index("--best-mapping-overlap") + 1], "80")
        self.assertEqual(best_mapping.load_choice(d.mission_folder), {"enabled": True, "overlap": 0.8})

    def test_run_without_best_mapping(self):
        d = self.dialog()
        d.best_mapping_checkbox.setChecked(False)
        with mock.patch.object(d.process, "start") as start:
            d._start_processing()
        self.assertNotIn("--best-mapping-overlap", start.call_args[0][1])
        self.assertFalse(best_mapping.load_choice(d.mission_folder)["enabled"])


if __name__ == "__main__":
    unittest.main()
