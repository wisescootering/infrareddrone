"""Diagnostic report (diagnostic.py, ⚙ options button, irdrone_diagnostic.bat)
and session log of the wizard (session_log.py)."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

import config  # noqa: E402
import diagnostic  # noqa: E402
import session_log  # noqa: E402


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(config, "SETTINGS_FILE", self.tmp / "settings" / "settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_zip(self, path):
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_aruco_selftest_finds_the_five_markers(self):
        result = diagnostic.selftest_aruco()
        self.assertTrue(result["ok"], result)

    def test_installation_only_report(self):
        zip_path = diagnostic.create_report(output=self.tmp / "out", quick=True)
        files = self.read_zip(zip_path)
        self.assertIn("report.txt", files)
        report = json.loads(files["report.json"])
        install = report["installation"]
        self.assertEqual(install["python"]["executable"], sys.executable)
        self.assertIn("opencv", install)
        self.assertEqual(set(install["tools"]), {"ExifTool", "RawTherapee", "SJCam RAW converter"})
        self.assertTrue(report["selftests"]["accented_folder"]["ok"], report["selftests"])
        self.assertNotIn("sync_images", report)
        self.assertIn("Summary", files["report.txt"].decode("utf-8"))

    def test_two_opencv_packages_are_reported(self):
        report = {"installation": {"packages": {"opencv-python": "4.8", "opencv-contrib-python": "5.0"}},
                  "selftests": {"aruco": {"ok": True, "status": "ok"}}}
        self.assertTrue(any("Several OpenCV" in line for line in diagnostic._verdicts(report)))

    def test_mission_sync_images_checked_without_touching_the_mission(self):
        import cv2
        mission = self.tmp / "Démo" / "FLY-20220125-1159-Blassac"
        aerial = mission / "AerialPhotography"
        for band in ("VIS", "NIR"):
            names = [f"{band}_0001.dng", f"{band}_0002.dng"]
            for name in names:
                (aerial / band).mkdir(parents=True, exist_ok=True)
                (aerial / band / name).write_bytes(b"dng")
            write_json(aerial / band / f"transfer_info_{band}_dng.json",
                       {"sync": {"idMin": 1, "idMax": 2, "listCopiedImages": names}})
        # NIR_0001: a cached image of another picture, older than its DNG
        cache = mission / "Synchro" / "NIR" / "NIR_0001_RawTherapee.jpg"
        import IRD_Interactive_ArUco as Aru         # the path Step 3 uses
        self.assertEqual(Path(Aru.cached_jpeg(str(aerial / "NIR" / "NIR_0001.dng"), mission)), cache)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(cache), np.full((60, 60, 3), 128, np.uint8))
        os.utime(cache, (1_000_000_000, 1_000_000_000))
        target = diagnostic.synthetic_target()
        before = sorted(p.relative_to(mission) for p in mission.rglob("*"))

        def develop(path, work, threads=None):
            return target.copy(), str(Path(work) / "x.jpg")

        with mock.patch("IRD_Interactive_ArUco.load_dng_for_aruco", side_effect=develop):
            zip_path = diagnostic.create_report(mission, output=self.tmp / "out", quick=True)
        self.assertEqual(sorted(p.relative_to(mission) for p in mission.rglob("*")), before)  # untouched
        files = self.read_zip(zip_path)
        report = json.loads(files["report.json"])
        nir = report["sync_images"]["NIR"]
        self.assertEqual(nir["with_mobile_marker_developed"], 2)
        self.assertEqual((nir["cached_images"], nir["with_mobile_marker_cached"], nir["cached_older_than_dng"]),
                         (1, 0, 1))
        verdicts = "\n".join(report["verdicts"])
        self.assertIn("older than their DNG", verdicts)
        self.assertIn("the cache in Synchro is wrong", verdicts)
        self.assertTrue(any(name.startswith("images/NIR_") for name in files))
        self.assertEqual(report["mission"]["NIR"]["sync"]["count"], 2)

    def test_command_line(self):
        output = self.tmp / "cli"
        with mock.patch("sys.stdout", new=io.StringIO()) as printed:
            self.assertEqual(diagnostic.main(["--output", str(output), "--quick"]), 0)
        self.assertIn("Diagnostic report written", printed.getvalue())
        self.assertIn("Self-tests", printed.getvalue())         # the whole report is printed
        self.assertEqual(len(list(output.glob("irdrone_diagnostic_*.zip"))), 1)


class SessionLogTest(unittest.TestCase):
    def test_console_copied_and_old_logs_removed(self):
        folder = Path(tempfile.mkdtemp())
        for k in range(session_log.KEEP_LOGS + 3):
            (folder / f"irdrone_20200101_0000{k:02d}.log").write_text("old")
        stdout, stderr = sys.stdout, sys.stderr
        console = io.StringIO()
        try:
            sys.stdout = console
            with mock.patch.object(session_log, "_started", None):
                path = session_log.start(folder)
                print("Aucun marqueur détecté")
                sys.stdout.flush()
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        self.assertIn("Aucun marqueur détecté", console.getvalue())           # still on the console
        self.assertIn("Aucun marqueur détecté", path.read_text(encoding="utf-8"))
        self.assertEqual(len(list(folder.glob("irdrone_*.log"))), session_log.KEEP_LOGS)


class OptionsButtonTest(unittest.TestCase):
    def test_gear_dialog_has_the_diagnostic_button(self):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import IRD_Interactive_workdir as Workdir
        dialog = Workdir.WorkingDirDialog()
        self.assertTrue(dialog.btn_diagnostic.toolTip())
        with mock.patch("IRD_Interactive_diagnostic.create_diagnostic_report") as create:
            dialog.btn_diagnostic.click()
        create.assert_called_once()


class CheckInstallationWindowTest(unittest.TestCase):
    """First page card, "Check the installation" window, report text shown."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, thread):
        from PyQt6.QtCore import QCoreApplication
        while not thread.wait(50):
            QCoreApplication.processEvents()
        for _ in range(5):
            QCoreApplication.processEvents()

    def test_home_card_asks_for_the_check(self):
        import IRD_Interactive_home as Home
        home = Home.HomePage()
        emitted = []
        home.check_installation.connect(lambda: emitted.append(True))
        home.card_check.click()
        self.assertEqual(emitted, [True])

    def test_options_dialog_has_the_check_button(self):
        import IRD_Interactive_workdir as Workdir
        dialog = Workdir.WorkingDirDialog()
        with mock.patch("IRD_Interactive_diagnostic.check_installation") as check:
            dialog.btn_check.click()
        check.assert_called_once()

    def test_window_shows_each_check_and_the_verdict(self):
        import IRD_Interactive_diagnostic as Diagnostic
        dialog = Diagnostic.SelfTestDialog(names=("python", "tiff"))
        with mock.patch("sys.stdout", new=io.StringIO()) as printed:
            dialog.start()
            self.wait(dialog.thread)
        self.assertEqual(set(dialog.results), {"python", "tiff"})
        self.assertIn("16 bits TIFF", dialog.rows["tiff"].text.text())
        self.assertFalse(dialog.verdict.isHidden())
        self.assertIn("Installation OK", dialog.verdict.text())
        self.assertIn("[OK     ] 16 bits TIFF", printed.getvalue())        # printed in the console
        dialog.btn_copy.click()
        from PyQt6.QtGui import QGuiApplication
        self.assertIn("16 bits TIFF", QGuiApplication.clipboard().text())

    def test_failed_check_shows_how_to_fix(self):
        import IRD_Interactive_diagnostic as Diagnostic
        import selftests
        checks = (("boom", "Boom", lambda ctx: (_ for _ in ()).throw(
            selftests.CheckError("It broke.", "Do this."))),)
        with mock.patch.object(selftests, "CHECKS", checks):
            dialog = Diagnostic.SelfTestDialog()
            with mock.patch("sys.stdout", new=io.StringIO()):
                dialog.start()
                self.wait(dialog.thread)
        text = dialog.rows["boom"].text.text()
        self.assertIn("It broke.", text)
        self.assertIn("How to fix:", text)
        self.assertIn("FAILED", dialog.verdict.text())

    def test_report_text_is_shown_and_printed(self):
        import IRD_Interactive_diagnostic as Diagnostic
        tmp = Path(tempfile.mkdtemp())
        zip_path = tmp / "irdrone_diagnostic_test.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("report.txt", "IRDrone diagnostic report\nSummary: all good")
        shown = []
        with mock.patch.object(config, "OUTPUT_FOLDER_NAME", str(tmp)), \
                mock.patch.object(Diagnostic.diagnostic, "create_report", return_value=zip_path), \
                mock.patch.object(Diagnostic.ReportTextDialog, "exec",
                                  lambda dialog: shown.append(dialog.view.toPlainText())), \
                mock.patch("sys.stdout", new=io.StringIO()) as printed:
            thread = Diagnostic.create_diagnostic_report(ask=False, checks={"python": {}})
            self.wait(thread)
        self.assertEqual(shown, ["IRDrone diagnostic report\nSummary: all good"])
        self.assertIn("Summary: all good", printed.getvalue())
        self.assertEqual(thread.checks, {"python": {}})        # the checks are not run again


if __name__ == "__main__":
    unittest.main()
