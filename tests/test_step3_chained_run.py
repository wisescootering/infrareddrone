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

    def measured(self, d):
        with mock.patch.object(d, "_save_and_show_alignment_plots"):
            d._on_timeshift_finished(3.2, [0.0, 1.0], [1.0, 2.0], [0.0, 1.0], [1.0, 2.0], "ok", True, False)

    def test_measured_offset_waits_for_the_user_to_check_the_curves(self):
        d = self.dialog(True)
        with mock.patch.object(d, "on_image_pairing") as pair:
            self.measured(d)
            pair.assert_not_called()
            self.assertEqual(d.stages.states[1], Look.STAGE_DONE)
            self.assertTrue(d.btn_sync_ok.isVisibleTo(d))
            self.assertIn("overlap?", d.sync_question.text())
            d.btn_sync_ok.click()
            pair.assert_called_once()
        self.assertFalse(d.btn_sync_ok.isVisibleTo(d))

    def test_adjust_by_hand_from_the_confirmation(self):
        d = self.dialog(True)
        self.measured(d)
        with mock.patch.object(S3, "TimeShiftAdjustDialog") as adjust, \
                mock.patch.object(d, "_save_and_show_alignment_plots"), \
                mock.patch.object(d, "on_image_pairing") as pair:
            adjust.return_value.exec.return_value = S3.QDialog.DialogCode.Accepted
            adjust.return_value.value.return_value = 3.5
            d.btn_sync_adjust.click()
            pair.assert_not_called()                    # still waiting for the confirmation
            self.assertEqual(d.time_shift, 3.5)
            d.btn_sync_ok.click()
            pair.assert_called_once()

    def test_y_key_answers_yes_only_when_asked(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d = self.dialog(True)
        d.show()
        with mock.patch.object(d, "on_image_pairing") as pair:
            QTest.keyClick(d, Qt.Key.Key_Y)
            pair.assert_not_called()                       # nothing asked yet
            self.measured(d)
            QTest.keyClick(d, Qt.Key.Key_Y)
            pair.assert_called_once()
        d.close()

    def test_manual_mode_hides_the_confirmation(self):
        d = self.dialog(True)
        self.measured(d)
        d._set_manual_mode(True)
        self.assertFalse(d.btn_sync_ok.isVisibleTo(d))

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


class Step3ReopenedTest(unittest.TestCase):
    """Step 3 opened again after it was done: the saved result is shown."""

    def setUp(self):
        import json
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        (self.mission / "FlightAnalytics").mkdir(parents=True)
        (self.mission / "AerialPhotography").mkdir()
        (self.mission / "Synchro").mkdir()
        (self.mission / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(
            {"time_shift": -30.99, "created_at": "2026-11-08T11:42:46", "shoot_points": [{}, {}, {}]}))
        from PyQt6.QtGui import QPixmap
        for name in ("check_time_alignment.png", "check_time_before_alignment.png"):
            pix = QPixmap(40, 30)
            pix.fill()
            pix.save(str(self.mission / "Synchro" / name))

    def dialog(self):
        with mock.patch.object(S3.DialogSynchroAruco, "on_run_aruco"):
            return S3.DialogSynchroAruco({"folderMissionPath": str(self.mission)})

    def test_shows_the_offset_pairs_and_aligned_curves(self):
        d = self.dialog()
        self.assertEqual(d.stages.states[:3], [Look.STAGE_DONE] * 3)
        self.assertIn("-30.99", d.auto_label.text())
        self.assertIn("3 pairs", d.auto_label.text())
        self.assertIn("08/11/2026", d.auto_label.text())
        self.assertEqual(d.time_shift, -30.99)
        self.assertTrue(d.btn_before.isVisibleTo(d))
        self.assertTrue(d.btn_continue.isVisibleTo(d))
        d.btn_before.click()
        self.assertEqual(d.btn_before.text(), "After alignment")

    def test_not_done_yet_shows_nothing_old(self):
        (self.mission / "AerialPhotography" / "shoot_points.json").unlink()
        d = self.dialog()
        self.assertEqual(d.stages.states[1], Look.STAGE_PENDING)
        self.assertFalse(d.btn_before.isVisibleTo(d))
