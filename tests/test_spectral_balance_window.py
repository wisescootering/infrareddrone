"""Spectral balance window (Step 6): the settings edit the balanced image,
Validate writes the bands of the image, Close saves the settings; the Step 6
button opens it only for a multispectral mission with its four band images."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IRDRONE_CACHE", tempfile.mkdtemp())

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_Spectral_Balance as W  # noqa: E402
import spectral_balance as SB  # noqa: E402
from test_spectral_balance import make_quartets  # noqa: E402


def settle(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        APP.processEvents()
        time.sleep(0.01)
    QThreadPool.globalInstance().waitForDone(5000)
    APP.processEvents()


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mission = Path(self.tmp.name) / "FLY-20260101-1000-Test"
        make_quartets(self.mission, numbers=(45, 46))
        # no metadata to copy in these synthetic images (and maybe no ExifTool)
        patcher = mock.patch.object(SB, "_copy_metadata", lambda pairs: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def dialog(self):
        d = W.SpectralBalanceDialog(self.mission)
        self.addCleanup(d.deleteLater)
        d.resize(1300, 850)
        d.show()
        for _ in range(50):          # the bands of the first image are read in the background
            settle(0.05)
            if d.view.has_images():
                break
        return d

    def test_opens_on_the_images_and_shows_them(self):
        d = self.dialog()
        self.assertEqual([p.stem for p in d.points], ["IRD_0045", "IRD_0046"])
        self.assertTrue(d.view.has_images())
        self.assertEqual(d.btn_close.text(), "Close")
        self.assertTrue(d.btn_reset.isHidden())
        self.assertEqual(set(d.hist.hists), set(SB.BANDS))

    def test_a_setting_changes_the_balanced_image_and_close_saves_it(self):
        d = self.dialog()
        before = d.view.images["after"].copy()
        d.set_layer("nir")
        d.rows["exposure"].spin.setValue(1.0)
        settle(0.2)
        self.assertNotEqual(d.view.images["after"], before)
        self.assertEqual(d.settings.mission.layer("nir").exposure, 1.0)
        self.assertEqual(d.btn_close.text(), "Save and close")
        self.assertFalse(d.btn_reset.isHidden())
        d.reject()                       # the cross also saves
        saved = SB.load_settings(self.mission)
        self.assertEqual(saved.mission.layer("nir").exposure, 1.0)
        self.assertTrue(SB.is_active(self.mission))

    def test_closing_without_change_writes_nothing(self):
        d = self.dialog()
        d.accept()
        self.assertFalse(SB.settings_path(self.mission).exists())

    def test_automatic_nir_shows_the_values_of_the_image(self):
        d = self.dialog()
        d.set_layer("nir")
        d.nir_auto.setChecked(True)
        settle(0.1)
        self.assertFalse(d.rows["exposure"].isEnabled())
        self.assertIn("Computed on this image", d.auto_text.text())
        self.assertGreater(d.rows["exposure"].spin.value(), 1.0)      # the synthetic NIR is dark

    def test_validate_writes_the_image_and_stars_it(self):
        d = self.dialog()
        d.set_layer("nir")
        d.rows["gamma"].spin.setValue(1.5)
        d.validate()
        for _ in range(100):
            settle(0.05)
            if d._write_job is None:
                break
        self.assertEqual(d.states[45], SB.STATE_DONE)
        self.assertEqual(d.states[46], SB.STATE_NONE)
        self.assertTrue(SB.record_path(self.mission, 45).is_file())
        self.assertEqual(d.btn_validate.text(), "★ Validated")
        self.assertIn("(1)", d.btn_write_all.text())
        # the mission balance changes: the written image is out of date
        d.rows["gamma"].spin.setValue(1.2)
        settle(0.6)
        self.assertEqual(d.states[45], SB.STATE_STALE)

    def test_an_image_with_its_own_balance(self):
        d = self.dialog()
        d.set_layer("nir")
        d.scope.setChecked(True)
        d.rows["exposure"].spin.setValue(-1.0)
        self.assertEqual(d.settings.points[45].layer("nir").exposure, -1.0)
        self.assertEqual(d.settings.mission.layer("nir").exposure, 0.0)
        d.step(+1)
        self.assertEqual(d.rows["exposure"].spin.value(), 0.0)          # 46 follows the mission
        self.assertFalse(d.scope.isChecked())
        d.accept()
        data = json.loads(SB.settings_path(self.mission).read_text())
        self.assertEqual(list(data["points"]), ["0045"])

    def test_curve_handle_added_by_a_click(self):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        d = self.dialog()
        d.set_layer("rgb")
        c = d.curve
        r = c._plot()
        QTest.mouseClick(c, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.top() + r.height() * 0.3)))
        settle(0.1)
        curve = d.settings.mission.layer("rgb").curve
        self.assertEqual(len(curve), 3)
        self.assertGreater(curve[1][1], 0.6)       # lifted mid tones


class Step6ButtonTest(unittest.TestCase):
    def test_button_follows_the_mission(self):
        import IRD_Interactive_5 as S6
        with tempfile.TemporaryDirectory() as tmp:
            mission = Path(tmp) / "FLY-20260101-1000-Test"
            (mission / "FlightAnalytics").mkdir(parents=True)
            d = S6.DialogGeoRef({"File path mission": str(mission)})
            self.addCleanup(d.deleteLater)
            self.assertFalse(d.btn_run_Balance.isEnabled())         # no band image yet
            make_quartets(mission, numbers=(45,))
            d._refresh_balance_button()
            self.assertTrue(d.btn_run_Balance.isEnabled())
            (mission / "FlightAnalytics" / "mission_parameters.json").write_text(
                json.dumps({"mission type": "visible"}), encoding="utf-8")
            d._refresh_balance_button()
            self.assertFalse(d.btn_run_Balance.isEnabled())         # visible only: no NIR


if __name__ == "__main__":
    unittest.main()
