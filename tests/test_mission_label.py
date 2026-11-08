"""Mission shown at the bottom of the main window once Step 1 defined it
(or once another step loaded an existing mission)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_workdir as workdir  # noqa: E402

MISSION = {
    "File path mission": "/old/computer/Air-Mission/FLY-20220524-1715-Chalivoy-Milon",
    "Location": "Chalivoy-Milon",
    "Date": "2022-05-24",
    "Pilot": "Alain",
}


class MissionLabelTest(unittest.TestCase):
    def test_hint_before_any_mission(self):
        label = workdir.MissionLabel()
        self.assertIn("Step 1", label.text())
        self.assertIsNone(label.folder)

    def test_mission_name_and_details(self):
        label = workdir.MissionLabel()
        label.set_mission(MISSION)
        self.assertIn("FLY-20220524-1715-Chalivoy-Milon", label.text())
        self.assertIn("Location: Chalivoy-Milon", label.toolTip())
        self.assertIn("Pilot: Alain", label.toolTip())

    def test_folder_chosen_in_this_session_wins(self):
        # mission_parameters.json may hold the path of the computer that created it
        label = workdir.MissionLabel()
        label.set_mission(MISSION, folder="/here/FLY-20220524-1715-Chalivoy-Milon")
        self.assertEqual(label.folder, Path("/here/FLY-20220524-1715-Chalivoy-Milon"))
        parameters = dict(MISSION, folderMissionPath="/injected/FLY-1")
        label.set_mission(parameters)
        self.assertEqual(label.folder, Path("/injected/FLY-1"))


class MainWindowMissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import IRD_Interactive_Main as main
        cls.main = main

    def test_step1_validation_shows_the_mission(self):
        window = self.main.Main_Window()
        self.assertEqual(window.home.currentIndex(), 0)          # welcome page
        window.dialog_create_file_structure = mock.MagicMock()
        window.dialog_load_takeoff_image = mock.MagicMock()
        window.handle_data_from_dialog_create_file_structure(True, dict(MISSION))
        self.assertEqual(window.home.m_title.text(), "FLY-20220524-1715-Chalivoy-Milon")

    def test_step1_cancel_keeps_the_hint(self):
        window = self.main.Main_Window()
        window.dialog_load_takeoff_image = mock.MagicMock()
        window.handle_data_from_dialog_create_file_structure(False, {})
        self.assertEqual(window.home.currentIndex(), 0)          # still the welcome page


if __name__ == "__main__":
    unittest.main()
