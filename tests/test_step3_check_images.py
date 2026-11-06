import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "irdrone_wizard"))

import numpy as np
import cv2
from PyQt6.QtWidgets import QApplication

import IRD_Interactive_3 as Step3

_app = QApplication.instance() or QApplication([])


def _write(folder: Path, name: str, value: int) -> str:
    path = folder / name
    cv2.imwrite(str(path), np.full((40, 60, 3), value, np.uint8))
    return str(path)


class CheckImageDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.dialog = Step3.DialogSynchroAruco({"folderMissionPath": str(self.folder)})
        self.shown = []
        self.dialog._show_image_file = lambda p: self.shown.append(Path(p).name) or True

    def tearDown(self):
        self.dialog._reset_check_image_display()
        self.tmp.cleanup()

    def test_first_image_shown_then_only_latest_after_hold(self):
        paths = [_write(self.folder, f"VIS_{i}_aruco.jpg", i * 40) for i in range(4)]
        for p in paths:
            self.dialog._on_check_image(p)
        self.assertEqual(self.shown, ["VIS_0_aruco.jpg"])
        self.assertTrue(self.dialog._check_image_timer.isActive())
        self.dialog._check_image_timer.stop()
        self.dialog._show_pending_check_image()
        self.assertEqual(self.shown, ["VIS_0_aruco.jpg", "VIS_3_aruco.jpg"])

    def test_stage_change_shows_generic_image_and_drops_pending(self):
        self.dialog._on_check_image(_write(self.folder, "VIS_0_aruco.jpg", 10))
        self.dialog._on_check_image(_write(self.folder, "VIS_1_aruco.jpg", 20))
        self.dialog._on_aruco_stage("Detect ArUco NIR")
        self.assertEqual(self.shown[-1], "Image_ArUco_NIR.jpg")
        self.assertIsNone(self.dialog._pending_check_image)
        self.assertFalse(self.dialog._check_image_timer.isActive())
        self.dialog._on_aruco_stage("Detect ArUco VIS")
        self.assertEqual(self.shown[-1], "Image_ArUco_VIS.jpg")


if __name__ == "__main__":
    unittest.main()
