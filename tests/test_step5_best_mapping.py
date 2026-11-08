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
