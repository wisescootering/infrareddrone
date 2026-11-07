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

    def write_step1_files(self, *names):
        for name in names:
            path = self.mission / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"VIS": []}')

    def test_step1_found_from_its_files_for_older_missions(self):
        self.write_step1_files(*(name for name, _ in Progress.STEP_OUTPUTS[1]))
        self.assertEqual(list(Progress.done_steps(self.mission)), [1])

    def test_step1_started_but_not_finished_is_not_done(self):
        # mission_parameters.json is written as soon as Step 1 starts
        self.write_step1_files(Progress.STEP_OUTPUTS[1][0][0], Progress.STEP_OUTPUTS[1][1][0])
        self.assertEqual(Progress.done_steps(self.mission), {})
        (self.mission / Progress.STEP_OUTPUTS[1][2][0]).parent.mkdir(parents=True)
        (self.mission / Progress.STEP_OUTPUTS[1][2][0]).write_text("")  # left by a full disk
        self.assertEqual(Progress.done_steps(self.mission), {})

    def write(self, name, content):
        path = self.mission / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_steps_3_to_6_found_from_their_final_outputs(self):
        self.write("AerialPhotography/shoot_points.json", '{"time_shift": 1.2, "shoot_points": [{}]}')
        self.write("ImgIRdrone/shoot_points.json", '{"shoot_points": [{}]}')
        self.write("mapping_MULTI/mapping_result/odm_orthophoto.tif", "tif")
        self.write("archive_manifest.json", "{}")
        self.assertEqual(list(Progress.done_steps(self.mission)), [3, 4, 5, 6])

    def test_step3_needs_the_pairing_not_only_aruco_and_delay(self):
        self.write("Synchro/check_time_alignment.png", "png")       # time shift computed
        self.write("Synchro/Check_ARUCO/VIS_0001_aruco.jpg", "jpg")  # ArUco detected
        self.assertEqual(Progress.done_steps(self.mission), {})
        self.write("AerialPhotography/shoot_points.json", '{"shoot_points": []}')  # no pair
        self.assertEqual(Progress.done_steps(self.mission), {})

    def test_record_and_outputs_combine(self):
        Progress.mark_step_done(self.mission, 2)
        self.write("AerialPhotography/shoot_points.json", '{"shoot_points": [{}]}')
        self.assertEqual(list(Progress.done_steps(self.mission)), [2, 3])


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


class _MissionHelpers(unittest.TestCase):
    """Main window + mission folders on disk."""

    @classmethod
    def setUpClass(cls):
        import IRD_Interactive_Main as main
        cls.main = main

    def make_mission(self, name, done=()):
        mission = Path(tempfile.mkdtemp()) / name
        (mission / "FlightAnalytics").mkdir(parents=True)
        (mission / "FlightAnalytics" / "mission_parameters.json").write_text(
            json.dumps({"File path mission": "/other/computer/" + name, "Location": "Blassac"}))
        for step in done:
            Progress.mark_step_done(mission, step)
        return mission

    def open(self, window, mission):
        with mock.patch.object(self.main.Uti, "choose_mission_folder_phase_2", return_value=(mission, True)):
            window.btn_open_mission.click()



class OpenMissionButtonTest(_MissionHelpers):
    """'Change mission...' at the bottom: switch to an existing mission directly."""

    def test_open_shows_the_mission_and_its_done_steps(self):
        window = self.main.Main_Window()
        mission = self.make_mission("FLY-20220125-1159-Blassac", done=(1, 2, 3))
        self.open(window, mission)
        self.assertEqual(window.folderMissionPath, mission)
        self.assertIn("FLY-20220125-1159-Blassac", window.mission_label.text())
        texts = [window.step_buttons[s][0].text() for s in Progress.STEPS]
        self.assertEqual([t.startswith(CHECK) for t in texts], [True, True, True, False, False, False])
        # a step opened afterwards uses this mission without asking again
        self.assertTrue(window.ensure_mission_parameters())

    def test_switching_mission_replaces_the_previous_one(self):
        window = self.main.Main_Window()
        self.open(window, self.make_mission("FLY-A", done=(1,)))
        second = self.make_mission("FLY-B")
        self.open(window, second)
        self.assertEqual(window.mission_parameters["folderMissionPath"], second)
        self.assertNotIn(CHECK, window.step_buttons[1][0].text())

    def test_cancel_keeps_the_current_mission(self):
        window = self.main.Main_Window()
        first = self.make_mission("FLY-A")
        self.open(window, first)
        with mock.patch.object(self.main.Uti, "choose_mission_folder_phase_2", return_value=(None, False)):
            window.btn_open_mission.click()
        self.assertEqual(window.folderMissionPath, first)

    def test_refused_while_a_step_window_is_open(self):
        window = self.main.Main_Window()
        window.dialog_image_processing = mock.MagicMock()
        window.dialog_image_processing.isVisible.return_value = True
        with mock.patch.object(self.main.QMessageBox, "warning") as warning, \
                mock.patch.object(self.main.Uti, "choose_mission_folder_phase_2") as choose:
            window.btn_open_mission.click()
        choose.assert_not_called()
        self.assertIn("Step 4", warning.call_args[0][2])


class Step2UsesCurrentMissionTest(_MissionHelpers):
    """Step 2 asks for the mission folder only when no mission is loaded."""

    def click_step2(self, window, chooser):
        with mock.patch.object(self.main.Uti, "choose_mission_folder_phase_2", chooser), \
                mock.patch.object(self.main.QMessageBox, "information"), \
                mock.patch.object(self.main, "LoadVisNirImagesDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            window.btn_load_images.click()
        return dialog

    def test_asked_once_then_reused(self):
        window = self.main.Main_Window()
        mission = self.make_mission("FLY-A")
        params = json.loads((mission / "FlightAnalytics" / "mission_parameters.json").read_text())
        params.update({"path mission image take-off": str(mission / "VIS_0001.dng"),
                       "original File path take-off": str(mission / "VIS_0001.dng")})
        (mission / "FlightAnalytics" / "mission_parameters.json").write_text(json.dumps(params))
        chooser = mock.MagicMock(return_value=(mission, True))
        dialog = self.click_step2(window, chooser)
        self.click_step2(window, chooser)
        self.assertEqual(chooser.call_count, 1)
        self.assertEqual(dialog.call_args.kwargs["folderMission"], mission)

    def test_not_asked_after_open_mission(self):
        window = self.main.Main_Window()
        mission = self.make_mission("FLY-B")
        self.open(window, mission)
        chooser = mock.MagicMock()
        self.click_step2(window, chooser)
        chooser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
