"""A mission folder renamed or moved by hand: when it is opened, the absolute
paths its JSON files keep are rewritten to the folder actually opened."""
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

import mission_relocation as R  # noqa: E402

OLD = "/old/computer/Air-Mission/FLY-20220125-1159-Blassac"
SD_CARD = "/media/sd/DCIM/HYPERLAPSE_0001.DNG"


def write(path, data, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_mission(folder, old=OLD):
    """Mission written at ``old``, now found at ``folder``."""
    aerial = old + "/AerialPhotography"
    write(folder / "FlightAnalytics" / "mission_parameters.json", {
        "File path mission": old,
        "original File path take-off": SD_CARD,
        "path mission image take-off": aerial + "/VIS/VIS_0001.dng",
        "Location": "Blassac",
    })
    write(folder / "AerialPhotography" / "shoot_points.json", {
        "mission_path": old,
        "shoot_points": [{
            "VIS": {"FileName": "VIS_0161.dng", "Directory": aerial + "/VIS"},
            "NIR": [{"FileName": "NIR_0150.RAW", "Directory": aerial + "/NIR", "rank": 1}],
        }],
    }, indent=4)
    write(folder / "AerialPhotography" / "VIS" / "VIS_0161.exif",
          {"FileName": "VIS_0161.dng", "Directory": aerial + "/VIS", "ImageSize": "4000x3000"})
    write(folder / "mapping_MULTI" / "img_best_mappping.json", {
        "command": ["/usr/bin/docker", "run", "-v", old + ":/datasets"],
        "log_path": old + "/mapping_MULTI/odm.log",
    })
    return folder


class RelocationTest(unittest.TestCase):
    def setUp(self):
        self.mission = make_mission(Path(tempfile.mkdtemp()) / "Démo" / "FLY-20220125-1159-Renamed")
        self.new = str(self.mission)

    def test_paths_into_the_mission_follow_it(self):
        self.assertTrue(R.needs_relocation(self.mission))
        self.assertEqual(R.relocate_mission(self.mission), 4)
        params = read(self.mission / "FlightAnalytics" / "mission_parameters.json")
        self.assertEqual(params["File path mission"], self.new)
        self.assertEqual(params["path mission image take-off"],
                         str(self.mission / "AerialPhotography" / "VIS" / "VIS_0001.dng"))
        points = read(self.mission / "AerialPhotography" / "shoot_points.json")
        self.assertEqual(points["mission_path"], self.new)
        self.assertEqual(points["shoot_points"][0]["VIS"]["Directory"],
                         str(self.mission / "AerialPhotography" / "VIS"))
        self.assertEqual(points["shoot_points"][0]["NIR"][0]["Directory"],
                         str(self.mission / "AerialPhotography" / "NIR"))
        exif = read(self.mission / "AerialPhotography" / "VIS" / "VIS_0161.exif")
        self.assertEqual(exif["Directory"], str(self.mission / "AerialPhotography" / "VIS"))
        self.assertEqual(exif["ImageSize"], "4000x3000")

    def test_paths_outside_the_mission_are_kept(self):
        R.relocate_mission(self.mission)
        params = read(self.mission / "FlightAnalytics" / "mission_parameters.json")
        self.assertEqual(params["original File path take-off"], SD_CARD)
        self.assertEqual(params["Location"], "Blassac")
        report = read(self.mission / "mapping_MULTI" / "img_best_mappping.json")
        # the record of the command that was run: not a path, kept as it was
        self.assertEqual(report["command"], ["/usr/bin/docker", "run", "-v", OLD + ":/datasets"])
        self.assertEqual(report["log_path"], str(self.mission / "mapping_MULTI" / "odm.log"))

    def test_a_folder_with_the_old_name_as_prefix_is_not_the_mission(self):
        path = self.mission / "AerialPhotography" / "other.json"
        write(path, {"a": OLD + "-copy/VIS", "b": OLD + "2"})
        R.relocate_mission(self.mission)
        self.assertEqual(read(path), {"a": OLD + "-copy/VIS", "b": OLD + "2"})

    def test_nothing_to_do_once_relocated_or_when_not_moved(self):
        R.relocate_mission(self.mission)
        self.assertFalse(R.needs_relocation(self.mission))
        self.assertEqual(R.relocate_mission(self.mission), 0)
        same = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        make_mission(same, old=str(same))
        self.assertEqual(R.relocate_mission(same), 0)

    def test_indentation_of_the_files_is_kept(self):
        R.relocate_mission(self.mission)
        text = (self.mission / "AerialPhotography" / "shoot_points.json").read_text(encoding="utf-8")
        self.assertIn('\n    "mission_path"', text)

    def test_windows_paths_and_exiftool_question_marks(self):
        old = "G:\\Démo Florine\\FLY-20220125-1159-Blassac"
        mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        write(mission / "FlightAnalytics" / "mission_parameters.json", {"File path mission": old})
        exif = mission / "AerialPhotography" / "VIS" / "VIS_0001.exif"
        write(exif, {"Directory": "g:/D?mo Florine/FLY-20220125-1159-Blassac/AerialPhotography/VIS"})
        self.assertEqual(R.relocate_mission(mission), 2)
        self.assertEqual(read(exif)["Directory"], str(mission / "AerialPhotography" / "VIS"))

    def test_interrupted_recovery_is_done_again(self):
        """The former location is rewritten last: still recorded if a file failed."""
        real = R._rewrite_file
        parameters = self.mission / "FlightAnalytics" / "mission_parameters.json"

        def failing(path, *args):
            if path == parameters:
                raise KeyboardInterrupt
            return real(path, *args)
        with mock.patch.object(R, "_rewrite_file", failing):
            with self.assertRaises(KeyboardInterrupt):
                R.relocate_mission(self.mission)
        self.assertEqual(read(parameters)["File path mission"], OLD)
        self.assertTrue(R.needs_relocation(self.mission))
        R.relocate_mission(self.mission)
        self.assertEqual(read(parameters)["File path mission"], self.new)

    def test_unreadable_files_are_left_alone(self):
        broken = self.mission / "AerialPhotography" / "broken.json"
        broken.write_text("{not json " + OLD, encoding="utf-8")
        R.relocate_mission(self.mission)
        self.assertEqual(broken.read_text(encoding="utf-8"), "{not json " + OLD)
        self.assertFalse(list(self.mission.rglob("*.relocating")))


class OpenMovedMissionTest(unittest.TestCase):
    """Opening the mission from the home page does the recovery, without a message."""

    def test_load_mission_relocates_silently(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_Main as main
        mission = make_mission(Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Moved")
        window = main.Main_Window()
        with mock.patch.object(main.QMessageBox, "critical") as critical, \
                mock.patch.object(main.QMessageBox, "information") as information:
            self.assertTrue(window.load_mission(mission))
        critical.assert_not_called()
        information.assert_not_called()
        points = read(mission / "AerialPhotography" / "shoot_points.json")
        self.assertEqual(points["shoot_points"][0]["VIS"]["Directory"],
                         str(mission / "AerialPhotography" / "VIS"))
        self.assertEqual(window.mission_parameters["File path mission"], str(mission))


if __name__ == "__main__":
    unittest.main()
