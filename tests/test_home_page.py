"""Main window home page: recent missions, what comes next, new mission and
review entry points."""
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_home as Home  # noqa: E402
import IRD_Interactive_progress as Progress  # noqa: E402


def make_mission(root, name, done=(), when=None, **params):
    m = Path(root) / name
    (m / "FlightAnalytics").mkdir(parents=True)
    p = m / "FlightAnalytics" / "mission_parameters.json"
    p.write_text(json.dumps({"File path mission": str(m), "Date": "2022:01:25", "Time": "11:59:49",
                             "Location": "Blassac", **params}))
    for s in done:
        Progress.mark_step_done(m, s)
    if when is not None:
        for f in (m / "FlightAnalytics").iterdir():
            os.utime(f, (when, when))
    return m


class MissionsOnDiskTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_recent_missions_most_recent_first_and_only_fly_folders(self):
        now = time.time()
        make_mission(self.root, "FLY-20220101-1000-A", when=now - 100)
        make_mission(self.root, "FLY-20220102-1000-B", when=now)
        (self.root / "FLY-broken").mkdir()          # no parameters: ignored
        (self.root / "Other").mkdir()
        self.assertEqual([m.name for m in Home.recent_missions(self.root)],
                         ["FLY-20220102-1000-B", "FLY-20220101-1000-A"])

    def test_next_step(self):
        info = Home.read_mission(make_mission(self.root, "FLY-x", done=(1, 2)))
        self.assertEqual(info.next_step(), 3)
        info = Home.read_mission(make_mission(self.root, "FLY-y", done=(1, 2, 3, 4, 5)))
        self.assertIsNone(info.next_step())
        self.assertIn("25/01/2022 11:59 · Blassac", info.subtitle())

    def test_figures(self):
        m = make_mission(self.root, "FLY-z")
        (m / "AerialPhotography" / "VIS").mkdir(parents=True)
        (m / "AerialPhotography" / "VIS" / "VIS_0001.dng").write_bytes(b"")
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": [{}, {}]}))
        (m / "ImgIRdrone").mkdir()
        (m / "ImgIRdrone" / "shoot_points.json").write_text(
            json.dumps({"shoot_points": [{"failed": True}, {"failed": False}]}))
        texts = [t for t, _ in Home.mission_figures(m)]
        self.assertEqual(texts, ["1 visible · 0 infrared images", "2 pairs", "2 aligned", "⚑ 1 flagged"])


class MainWindowHomeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import IRD_Interactive_Main as main
        cls.main = main

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.window = self.main.Main_Window()

    def test_welcome_page_until_a_mission_is_loaded(self):
        self.assertEqual(self.window.home.currentIndex(), 0)
        m = make_mission(self.root, "FLY-20220125-1159-Blassac", done=(1,))
        self.window.load_mission(m)
        self.assertEqual(self.window.home.currentIndex(), 1)
        self.assertIn("Step 2", self.window.home.btn_continue.text())

    def test_continue_runs_the_next_step(self):
        m = make_mission(self.root, "FLY-20220125-1159-Blassac", done=(1, 2))
        self.window.load_mission(m)
        with mock.patch.object(self.window, "on_pre_process_images") as step3:
            self.window.home.btn_continue.click()
        step3.assert_called_once_with(auto_run=True)

    def test_created_mission_becomes_current(self):
        m = make_mission(self.root, "FLY-20220125-1159-Blassac", done=(1,))
        self.window.handle_new_mission({"File path mission": str(m)})
        self.assertEqual(self.window.folderMissionPath, m)
        self.assertIn("FLY-20220125-1159-Blassac", self.window.mission_label.text())

    def test_new_mission_then_timeline(self):
        with mock.patch.object(self.main, "NewMissionDialog") as dialog, \
                mock.patch.object(self.window, "open_window_load_set_images") as step2:
            dialog.return_value.action = "timeline"
            self.window.home.card_new.click()
        step2.assert_called_once()

    def test_classic_form_still_available(self):
        with mock.patch.object(self.main, "NewMissionDialog") as dialog, \
                mock.patch.object(self.window, "open_window_define_mission_classic") as classic:
            dialog.return_value.action = "classic"
            self.window.btn_create_mission.click()
        classic.assert_called_once()


if __name__ == "__main__":
    unittest.main()
