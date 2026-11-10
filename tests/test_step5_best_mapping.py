"""Step 5: the ODM image selection defaults to the best mapping (image overlap)."""
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

import best_mapping  # noqa: E402
import IRD_Interactive_5 as S5  # noqa: E402


class ODMSelectionDialogTest(unittest.TestCase):
    def test_default_is_overlap_at_75_percent(self):
        d = S5.ODMSelectionDialog()
        self.assertTrue(d.overlap_radio.isChecked())
        self.assertEqual(d.selected_overlap(), 0.75)
        self.assertFalse(d.sample_every.isEnabled())
        self.assertIn("best mapping, 75% overlap", d.description())

    def test_choice_of_step2_and_step4_is_used(self):
        with tempfile.TemporaryDirectory() as m:
            best_mapping.save_choice(Path(m), enabled=True, overlap=0.85)
            self.assertEqual(S5.ODMSelectionDialog(mission_folder=Path(m)).selected_overlap(), 0.85)
            best_mapping.save_choice(Path(m), enabled=False)
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.sample_radio.isChecked())
            self.assertIsNone(d.selected_overlap())
            self.assertIn("one image every 3", d.description())

    def test_settings_of_the_last_run_are_proposed(self):
        import json
        with tempfile.TemporaryDirectory() as m:
            best_mapping.save_choice(Path(m), enabled=True, overlap=0.85)
            os.utime(Path(m) / best_mapping.CHOICE_FILE, (1, 1))
            (Path(m) / "mapping_MULTI").mkdir()
            (Path(m) / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps({"selection_rules": {
                "maximum_absolute_dt_seconds": 0.4, "selection": "sample_every",
                "sample_every_nth_eligible_pair": 2, "footprint_overlap": None}}))
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.sample_radio.isChecked())
            self.assertEqual((d.dt_tolerance.value(), d.sample_every.value()), (0.4, 2))
            self.assertEqual(d.overlap.value(), 85)

    def test_all_the_aligned_images_ignores_the_criteria(self):
        import json
        d = S5.ODMSelectionDialog()
        d.all_radio.setChecked(True)
        self.assertFalse(d.dt_tolerance.isEnabled() or d.overlap.isEnabled() or d.sample_every.isEnabled())
        self.assertEqual((d.selected_dt_tolerance(), d.selected_sample_every(), d.selected_overlap()),
                         (6.0, 1, None))
        self.assertEqual(d.short_description(), "all the aligned images")
        d.overlap_radio.setChecked(True)                      # back: the criteria again
        self.assertTrue(d.dt_tolerance.isEnabled() and d.overlap.isEnabled())
        self.assertEqual(d.selected_sample_every(), d.sample_every.value())
        with tempfile.TemporaryDirectory() as m:             # proposed again after such a run
            best_mapping.save_choice(Path(m), enabled=True)
            os.utime(Path(m) / best_mapping.CHOICE_FILE, (1, 1))
            (Path(m) / "mapping_MULTI").mkdir()
            (Path(m) / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps({"selection_rules": {
                "maximum_absolute_dt_seconds": 6.0, "selection": "sample_every",
                "sample_every_nth_eligible_pair": 1, "footprint_overlap": None}}))
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.all_radio.isChecked())
            self.assertEqual(d.selected_dt_tolerance(), 6.0)

    def test_the_window_says_a_map_built_is_kept(self):
        with tempfile.TemporaryDirectory() as m:
            self.assertFalse(hasattr(S5.ODMSelectionDialog(mission_folder=Path(m)), "previous_map_note"))
            (Path(m) / "mapping_MULTI" / "mapping_result").mkdir(parents=True)
            (Path(m) / "mapping_MULTI" / "mapping_result" / "ortho.tif").write_bytes(b"x")
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertIn("kept, renamed mapping_MULTI_<date", d.previous_map_note.text())

    def test_sample_every_can_still_be_chosen(self):
        d = S5.ODMSelectionDialog()
        d.sample_radio.setChecked(True)
        self.assertTrue(d.sample_every.isEnabled())
        self.assertFalse(d.overlap.isEnabled())
        self.assertIsNone(d.selected_overlap())

    def test_worker_passes_the_overlap_to_odm(self):
        worker = S5.ODMRunWorker(Path("/mission"), dt_tolerance_s=0.4, sample_every=2, overlap=0.8)
        with mock.patch.object(S5, "run_odm", return_value={}) as run:
            worker.run()
        self.assertEqual(run.call_args.kwargs["overlap"], 0.8)
        self.assertEqual(run.call_args.kwargs["dt_tolerance_s"], 0.4)


if __name__ == "__main__":
    unittest.main()
