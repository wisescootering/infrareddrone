"""Working folder: IRDRONE_WORKING_DIR, then the saved setting, then the default;
first-launch dialog and gear button of the wizard."""
import importlib
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

import config  # noqa: E402


class WorkingDirTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.settings = self.folder / "settings" / "settings.json"
        environment = {"IRDRONE_SETTINGS_FILE": str(self.settings)}
        self.patcher = mock.patch.dict(os.environ, environment)
        self.patcher.start()
        os.environ.pop("IRDRONE_WORKING_DIR", None)
        importlib.reload(config)

    def tearDown(self):
        self.patcher.stop()
        importlib.reload(config)

    def test_default_when_nothing_is_saved(self):
        self.assertEqual(config.WORKING_DIR_SOURCE, "default")
        self.assertEqual(config.OUTPUT_FOLDER_NAME, config.DEFAULT_WORKING_DIR)

    def test_set_working_dir_creates_saves_and_is_used_next_launch(self):
        chosen = self.folder / "missions"
        config.set_working_dir(chosen)
        self.assertTrue(chosen.is_dir())
        self.assertEqual(json.loads(self.settings.read_text())["working_dir"], str(chosen.resolve()))
        importlib.reload(config)
        self.assertEqual((config.OUTPUT_FOLDER_NAME, config.WORKING_DIR_SOURCE),
                         (chosen.resolve(), "saved"))

    def test_environment_variable_wins_over_saved_folder(self):
        config.save_user_settings(working_dir=str(self.folder / "saved"))
        with mock.patch.dict(os.environ, {"IRDRONE_WORKING_DIR": str(self.folder / "env")}):
            importlib.reload(config)
            self.assertEqual((config.OUTPUT_FOLDER_NAME, config.WORKING_DIR_SOURCE),
                             (self.folder / "env", "environment"))

    def test_unreadable_settings_file_is_ignored(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("not json")
        importlib.reload(config)
        self.assertEqual(config.WORKING_DIR_SOURCE, "default")

    def test_save_keeps_other_settings(self):
        config.save_user_settings(other=1)
        config.save_user_settings(working_dir="x")
        self.assertEqual(json.loads(self.settings.read_text()), {"other": 1, "working_dir": "x"})


class WorkingDirDialogTest(WorkingDirTest):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_first_launch_dialog_saves_the_chosen_folder(self):
        import IRD_Interactive_workdir as workdir
        importlib.reload(workdir)
        chosen = self.folder / "first"

        def accept(dialog):
            self.assertTrue(dialog.first_run)
            dialog.path_edit.setText(str(chosen))
            dialog._apply()
            return dialog.result()

        with mock.patch.object(workdir.WorkingDirDialog, "exec", accept):
            self.assertEqual(workdir.ensure_working_dir_at_startup(), chosen.resolve())
        self.assertEqual(config.WORKING_DIR_SOURCE, "saved")

    def test_first_launch_later_uses_default_without_saving(self):
        import IRD_Interactive_workdir as workdir
        importlib.reload(workdir)
        with mock.patch.object(config, "DEFAULT_WORKING_DIR", self.folder / "default"), \
                mock.patch.object(config, "OUTPUT_FOLDER_NAME", self.folder / "default"), \
                mock.patch.object(workdir.WorkingDirDialog, "exec", lambda dialog: 0):
            workdir.ensure_working_dir_at_startup()
            self.assertTrue((self.folder / "default").is_dir())
        self.assertFalse(self.settings.exists())

    def test_gear_button_changes_folder_and_label(self):
        import IRD_Interactive_workdir as workdir
        importlib.reload(workdir)
        config.set_working_dir(self.folder / "before")
        bar = workdir.WorkingDirBar()
        changes = []
        bar.changed.connect(changes.append)
        after = self.folder / "after"

        def accept(dialog):
            dialog.path_edit.setText(str(after))
            dialog._apply()
            return dialog.result()

        with mock.patch.object(workdir.WorkingDirDialog, "exec", accept):
            bar.gear.click()
        self.assertEqual(changes, [after.resolve()])
        self.assertIn(str(after.resolve()), bar.label.text())


if __name__ == "__main__":
    unittest.main()
