"""Windows that edit something: ↺ next to ? (stays open), Close that becomes
"Save and close" once something changed, closing the window keeps the change."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "irdrone_wizard"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_3 as S3  # noqa: E402
import IRD_Interactive_4 as S4  # noqa: E402


class _Dialogs(unittest.TestCase):
    """Deletes its dialogs (a matplotlib canvas left to the interpreter exit can crash it)."""

    def keep(self, dialog):
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(APP.processEvents)
        return dialog


class Step3AdjustTest(_Dialogs):
    def dialog(self):
        t = [0.0, 1.0, 2.0, 3.0]
        a = [0.0, 90.0, 180.0, 270.0]
        return self.keep(S3.TimeShiftAdjustDialog(t, a, t, a, time_shift=0.5, computed_time_shift=0.0))

    def test_close_label_and_reset(self):
        d = self.dialog()
        self.assertEqual((d.btn_reset.text(), d.btn_close.text()), ("↺", "Close"))
        self.assertFalse(d.btn_reset.isHidden())         # 0.5 s, computed 0 s
        d.btn_reset.click()                              # back to the computed offset
        self.assertEqual(d.value(), 0.0)
        self.assertTrue(d.btn_reset.isHidden())
        self.assertEqual(d.btn_close.text(), "Save and close")
        self.assertEqual(d.result(), 0)                  # still open
        d.spinbox.setValue(0.5)
        self.assertEqual(d.btn_close.text(), "Close")

    def test_closing_the_window_keeps_the_offset(self):
        d = self.dialog()
        d.spinbox.setValue(1.25)
        d.reject()
        self.assertEqual(d.result(), d.DialogCode.Accepted)
        self.assertEqual(d.value(), 1.25)


class Step4SettingsTest(_Dialogs):
    def test_defaults_nothing_to_reset(self):
        self.assertTrue(self.keep(S4.Step4SettingsDialog(0)).btn_reset.isHidden())

    def test_close_label_and_reset(self):
        d = self.keep(S4.Step4SettingsDialog(1, S4.LOG_LEVELS[1][0]))
        self.assertEqual((d.btn_reset.text(), d.btn_close.text()), ("↺", "Close"))
        self.assertFalse(d.btn_reset.isHidden())         # not the defaults
        d.btn_reset.click()                              # defaults: Auto, warnings only
        self.assertEqual((d.workers(), d.log_level()), (0, S4.LOG_LEVELS[0][0]))
        self.assertTrue(d.btn_reset.isHidden())
        self.assertEqual(d.btn_close.text(), "Save and close")
        d.reject()                                       # title bar / Esc: kept, like Close
        self.assertEqual(d.result(), d.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()
