"""Step 4: the alignment can be stopped; its worker processes end too."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_4 as S4  # noqa: E402

# a parent that starts a worker child, both sleeping (as the alignment and its pool)
TREE = textwrap.dedent("""
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print("child", child.pid, flush=True)
    time.sleep(60)
""")


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


class KillTreeTest(unittest.TestCase):
    def test_parent_and_workers_end(self):
        proc = subprocess.Popen([sys.executable, "-c", TREE], stdout=subprocess.PIPE, text=True)
        child = int(proc.stdout.readline().split()[1])
        S4.kill_process_tree(proc.pid)
        proc.wait(5)
        self.assertTrue(wait_for(lambda: not psutil.pid_exists(child) or
                                 psutil.Process(child).status() == psutil.STATUS_ZOMBIE))

    def test_unknown_process_is_ignored(self):
        S4.kill_process_tree(0)
        S4.kill_process_tree(2 ** 22 + 12345)


class StopButtonTest(unittest.TestCase):
    def setUp(self):
        m = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        (m / "AerialPhotography").mkdir(parents=True)
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(
            {"shoot_points": [{"VIS": {"FileName": "VIS_0137.dng"}, "NIR": []}]}))
        (m / "AerialPhotography" / "VIS").mkdir()
        (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
            {"fly": {"listCopiedImages": ["VIS_0137.dng"]}}))
        self.dialog = S4.DialogImageProcessing({"File path mission": str(m)})

    def test_stop_ends_the_run_and_reports_it(self):
        d = self.dialog
        d.run_button.hide()
        d.stop_button.show()
        d._stopped_by_user = False
        d.process.readyReadStandardOutput.disconnect()
        d.process.start(sys.executable, ["-c", TREE])
        self.assertTrue(d.process.waitForStarted(5000))
        self.assertTrue(wait_for(lambda: d.process.canReadLine()))
        child = int(bytes(d.process.readLine()).decode().split()[1])
        with mock.patch.object(S4.QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            d.stop_button.click()
        self.assertTrue(wait_for(lambda: d.process.state() == S4.QProcess.ProcessState.NotRunning))
        APP.processEvents()
        self.assertTrue(wait_for(lambda: not psutil.pid_exists(child) or
                                 psutil.Process(child).status() == psutil.STATUS_ZOMBIE))
        self.assertIn("Stopped", d.status_label.text())
        self.assertFalse(d.stop_button.isVisibleTo(d))
        self.assertTrue(d.run_button.isVisibleTo(d))
        self.assertEqual(d.run_button.text(), "Run alignment again")

    def test_answer_no_keeps_running(self):
        d = self.dialog
        d.process.start(sys.executable, ["-c", "import time; time.sleep(30)"])
        self.assertTrue(d.process.waitForStarted(5000))
        with mock.patch.object(S4.QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            d._stop_processing()
        self.assertEqual(d.process.state(), S4.QProcess.ProcessState.Running)
        d.process.kill()
        d.process.waitForFinished(5000)

    def test_not_started_on_its_own(self):
        with mock.patch.object(S4.DialogImageProcessing, "_start_processing") as start:
            S4.DialogImageProcessing({"File path mission": str(self.dialog.mission_folder)})
            wait_for(lambda: False, 0.5)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class FitTest(unittest.TestCase):
    def test_long_mission_path_does_not_widen_the_window(self):
        root = Path(tempfile.mkdtemp()) / ("very long folder name " * 6).strip() / "Missions 2022"
        m = root / "FLY-20220125-1159-Saint-Julien-de-Chapteuil-Haute-Loire"
        (m / "AerialPhotography" / "VIS").mkdir(parents=True)
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(
            {"shoot_points": [{"VIS": {"FileName": "VIS_0137.dng"}, "NIR": []}]}))
        (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
            {"fly": {"listCopiedImages": ["VIS_0137.dng"]}}))
        d = S4.DialogImageProcessing({"File path mission": str(m)})
        self.assertLess(d.minimumSizeHint().width(), 600)
        screen = APP.primaryScreen().availableGeometry()
        self.assertLessEqual(d.width(), screen.width())
        self.assertLessEqual(d.height(), screen.height())
