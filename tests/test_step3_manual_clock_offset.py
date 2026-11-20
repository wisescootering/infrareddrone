"""Step 3, advanced option (⚙): flights without the ArUco target are paired from
a clock offset typed by the user. Hidden, and Step 3 unchanged, when the
option is off (the default)."""
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

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

APP = QApplication.instance() or QApplication([])

import config  # noqa: E402
import IRD_Interactive_3 as S3  # noqa: E402
import IRD_Interactive_look as Look  # noqa: E402
import IRD_Interactive_workdir as Workdir  # noqa: E402


def write_time_line(mission, band, first_date):
    folder = mission / "AerialPhotography" / band
    folder.mkdir(parents=True, exist_ok=True)
    entries = [{"img_path": f"{band}_0001.dng", "date_img": first_date, "relative_timeline": 0.0},
               {"img_path": f"{band}_0002.dng", "date_img": first_date, "relative_timeline": 2.0}]
    (folder / "time_line.json").write_text(json.dumps({band: entries}), encoding="utf-8")


class ClockOffsetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(config, "SETTINGS_FILE", self.tmp / "settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mission = self.tmp / "FLY-20220125-1159-Blassac"
        (self.mission / "FlightAnalytics").mkdir(parents=True)
        # Same dates as a real flight: NIR clock 3864 s later at the first image,
        # the ArUco target gave a time shift of -31 s (NIR clock ahead by 3895 s).
        write_time_line(self.mission, "VIS", "2022-01-25T11:59:49")
        write_time_line(self.mission, "NIR", "2022-01-25T13:04:13")

    def dialog(self, auto_run=False):
        d = S3.DialogSynchroAruco({"folderMissionPath": str(self.mission)}, auto_run=auto_run)
        self.addCleanup(d._start_timer.stop)
        return d

    def test_option_is_off_by_default_and_saved(self):
        self.assertFalse(config.manual_clock_offset_enabled())
        config.set_manual_clock_offset_enabled(True)
        self.assertTrue(config.manual_clock_offset_enabled())
        self.assertTrue(json.loads(config.SETTINGS_FILE.read_text())[config.MANUAL_CLOCK_OFFSET_KEY])

    def test_clock_offset_to_time_shift(self):
        origins = S3.timeline_origins(self.mission)
        self.assertAlmostEqual(origins[1] - origins[0], 3864.0)
        self.assertAlmostEqual(S3.time_shift_from_clock_offset(3895.0, origins), -31.0)
        self.assertAlmostEqual(S3.clock_offset_from_time_shift(-31.0, origins), 3895.0)
        self.assertIsNone(S3.timeline_origins(self.tmp / "nowhere"))

    def test_button_hidden_and_chained_run_unchanged_when_off(self):
        with mock.patch.object(S3.DialogSynchroAruco, "on_run_aruco"):
            d = self.dialog(auto_run=True)
            self.assertFalse(d.btn_clock_offset.isVisibleTo(d))
            self.assertTrue(d._start_timer.isActive())          # detection starts as before

    def test_button_shown_and_nothing_starts_when_on(self):
        config.set_manual_clock_offset_enabled(True)
        d = self.dialog(auto_run=True)
        self.assertTrue(d.btn_clock_offset.isVisibleTo(d))
        self.assertFalse(d._start_timer.isActive())             # the flight may have no target
        d._set_manual_mode(True)
        self.assertTrue(d.btn_clock_offset.isVisibleTo(d))

    def test_entered_offset_pairs_without_detection(self):
        config.set_manual_clock_offset_enabled(True)
        d = self.dialog()
        synchro = self.mission / "Synchro"
        synchro.mkdir()
        (synchro / "check_time_alignment.png").write_bytes(b"old")
        with mock.patch.object(S3.ClockOffsetDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                mock.patch.object(S3.ClockOffsetDialog, "value", return_value=3895.0), \
                mock.patch.object(d, "on_image_pairing") as pair, \
                mock.patch.object(d, "on_run_aruco") as detect:
            d.btn_clock_offset.click()
            pair.assert_called_once()
            detect.assert_not_called()
        self.assertAlmostEqual(d.time_shift, -31.0)
        self.assertEqual(d.stages.states[0], Look.STAGE_SKIPPED)
        self.assertEqual(d.stages.states[1], Look.STAGE_DONE)
        self.assertFalse((synchro / "check_time_alignment.png").exists())   # plots of another offset

    def test_cancel_changes_nothing(self):
        config.set_manual_clock_offset_enabled(True)
        d = self.dialog()
        with mock.patch.object(S3.ClockOffsetDialog, "exec", return_value=QDialog.DialogCode.Rejected), \
                mock.patch.object(d, "on_image_pairing") as pair:
            d.btn_clock_offset.click()
            pair.assert_not_called()
        self.assertEqual(d.time_shift, 0.0)

    def test_dialog_prefills_the_current_offset(self):
        origins = S3.timeline_origins(self.mission)
        dialog = S3.ClockOffsetDialog(origins, S3.clock_offset_from_time_shift(-31.0, origins))
        self.assertAlmostEqual(dialog.value(), 3895.0)
        self.assertIn("-31.00", dialog.result_label.text())

    def test_gear_dialog_saves_the_option(self):
        with mock.patch.object(config, "set_working_dir"):
            dialog = Workdir.WorkingDirDialog()
            self.assertFalse(dialog.manual_offset_box.isChecked())
            dialog.manual_offset_box.setChecked(True)
            dialog._apply()
        self.assertTrue(config.manual_clock_offset_enabled())
        self.assertIsNone(Workdir.WorkingDirDialog(first_run=True).manual_offset_box)


if __name__ == "__main__":
    unittest.main()
