"""Step 3 opened from the flight timeline: the stages follow each other and
Step 4 starts after a short countdown, unless the user takes over."""
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

import IRD_Interactive_3 as S3  # noqa: E402
import IRD_Interactive_look as Look  # noqa: E402


class ChainedStep3Test(unittest.TestCase):
    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        (self.mission / "FlightAnalytics").mkdir(parents=True)

    def dialog(self, auto_run):
        with mock.patch.object(S3.DialogSynchroAruco, "on_run_aruco"):
            return S3.DialogSynchroAruco({"folderMissionPath": str(self.mission)}, auto_run=auto_run)

    def test_chained_run_hides_the_stage_buttons(self):
        d = self.dialog(True)
        self.assertFalse(d.btn_run_aruco.isVisibleTo(d))
        self.assertTrue(d.btn_manual.isVisibleTo(d))

    def test_classic_run_shows_them(self):
        d = self.dialog(False)
        self.assertTrue(d.btn_image_pairing.isVisibleTo(d))
        self.assertFalse(d.btn_manual.isVisibleTo(d))

    def test_measured_offset_pairs_without_a_click(self):
        d = self.dialog(True)
        with mock.patch.object(S3.QTimer, "singleShot") as later, \
                mock.patch.object(d, "_save_and_show_alignment_plots"):
            d._on_timeshift_finished(3.2, [0.0, 1.0], [1.0, 2.0], [0.0, 1.0], [1.0, 2.0], "ok", True, False)
        later.assert_called_once()
        self.assertEqual(later.call_args.args[1], d._auto_pair)
        self.assertEqual(d.stages.states[1], Look.STAGE_DONE)

    def test_pairing_done_counts_down_then_continues(self):
        d = self.dialog(True)
        seen = []
        d.continue_requested.connect(lambda: seen.append(True))
        d._on_image_pairing_finished({"shoot_points": [{}, {}]})
        self.assertTrue(d._continue_timer.isActive())
        for _ in range(d.CONTINUE_DELAY_S):
            d._continue_tick()
        self.assertEqual(seen, [True])

    def test_stay_here_cancels_the_countdown(self):
        d = self.dialog(True)
        seen = []
        d.continue_requested.connect(lambda: seen.append(True))
        d._on_image_pairing_finished({"shoot_points": [{}]})
        d._stay_here()
        self.assertFalse(d._continue_timer.isActive())
        self.assertEqual(seen, [])

    def test_manual_mode_stops_the_chaining(self):
        d = self.dialog(True)
        d._set_manual_mode(True)
        self.assertFalse(d.auto_run)
        self.assertTrue(d.btn_compute_time_shift.isVisibleTo(d))


if __name__ == "__main__":
    unittest.main()
