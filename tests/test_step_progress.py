"""Finished steps are greyed out with a check mark (still clickable), from the
record kept in the mission folder (FlightAnalytics/wizard_progress.json)."""
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

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_progress as Progress  # noqa: E402

CHECK = "✅"


class ProgressRecordTest(unittest.TestCase):
    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        self.mission.mkdir()

    def test_nothing_done_for_a_new_mission(self):
        self.assertEqual(Progress.done_steps(self.mission), {})
        self.assertEqual(Progress.done_steps(None), {})

    def test_mark_done_is_saved_in_the_mission_and_notified(self):
        seen = []
        Progress.notifier.changed.connect(seen.append)
        try:
            Progress.mark_step_done(self.mission, 1)
            Progress.mark_step_done(self.mission, 3)
        finally:
            Progress.notifier.changed.disconnect(seen.append)
        self.assertEqual(sorted(Progress.done_steps(self.mission)), [1, 3])
        saved = json.loads((self.mission / Progress.PROGRESS_FILE).read_text())
        self.assertEqual(sorted(saved["done"]), ["1", "3"])
        self.assertEqual(seen, [self.mission, self.mission])

    def test_broken_record_counts_as_nothing_done(self):
        path = self.mission / Progress.PROGRESS_FILE
        path.parent.mkdir(parents=True)
        path.write_text("")
        self.assertEqual(Progress.done_steps(self.mission), {})

    def test_failure_to_record_does_not_break_the_step(self):
        with mock.patch.object(Progress, "write_json_atomic", side_effect=OSError("read-only")):
            Progress.mark_step_done(self.mission, 4)  # no exception


class MainWindowStepsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import IRD_Interactive_Main as main
        cls.main = main

    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        self.mission.mkdir()
        self.window = self.main.Main_Window()

    def text(self, step):
        return self.window.step_buttons[step][0].text()

    def test_steps_not_done_keep_their_look(self):
        for step in Progress.STEPS:
            self.assertNotIn(CHECK, self.text(step))

    def test_step1_validation_greys_step1_out(self):
        self.window.dialog_create_file_structure = mock.MagicMock()
        self.window.dialog_load_takeoff_image = mock.MagicMock()
        self.window.handle_data_from_dialog_create_file_structure(
            True, {"File path mission": str(self.mission)})
        button = self.window.step_buttons[1][0]
        self.assertTrue(button.text().startswith(CHECK))
        self.assertIn("#A9A9A9", button.styleSheet())
        self.assertTrue(button.isEnabled())  # can still be clicked
        self.assertNotIn(CHECK, self.text(2))

    def test_step_done_in_another_window_updates_the_buttons(self):
        self.window.folderMissionPath = self.mission
        self.window.mission_parameters = {"File path mission": str(self.mission)}
        Progress.mark_step_done(self.mission, 4)  # e.g. from the Step 4 window
        self.assertTrue(self.text(4).startswith(CHECK))
        self.assertIn("Click to run it again", self.window.step_buttons[4][0].toolTip())

    def test_opening_another_mission_shows_its_own_progress(self):
        Progress.mark_step_done(self.mission, 2)
        self.window.folderMissionPath = self.mission
        self.window.mission_parameters = {}
        self.window._show_current_mission()
        self.assertTrue(self.text(2).startswith(CHECK))
        other = self.mission.parent / "FLY-other"
        other.mkdir()
        self.window.folderMissionPath = other
        self.window._show_current_mission()
        self.assertNotIn(CHECK, self.text(2))


if __name__ == "__main__":
    unittest.main()
