"""Bottom bar of the mission page: the size of the mission folder, measured
outside the GUI thread."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_diskspace as Disk  # noqa: E402
from IRD_Interactive_workdir import MissionSizeLabel  # noqa: E402


def settle():
    for _ in range(3):
        QThreadPool.globalInstance().waitForDone(5000)
        APP.processEvents()


class MissionSizeLabelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mission = Path(tmp.name) / "FLY-20260101-1200-test"
        (self.mission / "ImgIRdrone").mkdir(parents=True)
        (self.mission / "a.bin").write_bytes(b"x" * 3000)
        (self.mission / "ImgIRdrone" / "b.bin").write_bytes(b"x" * 5000)
        self.label = MissionSizeLabel()
        self.addCleanup(self.label.deleteLater)

    def test_shows_the_size_of_the_whole_folder(self):
        self.label.set_folder(self.mission)
        settle()
        self.assertIn("Mission size", self.label.text())
        self.assertIn(Disk.format_bytes(8000), self.label.text())

    def test_refresh_follows_the_folder(self):
        self.label.show()
        self.label.set_folder(self.mission)
        settle()
        (self.mission / "ImgIRdrone" / "b.bin").unlink()
        self.label.refresh()
        settle()
        self.assertIn(Disk.format_bytes(3000), self.label.text())

    def test_no_mission_no_size(self):
        self.label.set_folder(None)
        settle()
        self.assertEqual(self.label.text(), "")


if __name__ == "__main__":
    unittest.main()
