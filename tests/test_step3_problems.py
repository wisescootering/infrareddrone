"""Step 3 failures explained: what happened and how to fix it
(IRD_Interactive_problem.py, IRD_Interactive_ArUco.py)."""
import io
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

import numpy as np  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import IRD_Interactive_ArUco as Aru  # noqa: E402
import IRD_Interactive_problem as Problem  # noqa: E402

app = QApplication.instance() or QApplication([])
_RESULT = {"angle_abs": 10.0, "angle_img": 20.0, "delta_abs_img": 10.0}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class MissionTest(unittest.TestCase):
    """A mission folder FLY-.../AerialPhotography/VIS with three DNG."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = Path(self.tmp.name) / "FLY-20220125-1159-Démo"
        self.aerial = self.mission / "AerialPhotography"
        self.names = ["VIS_0001.dng", "VIS_0002.dng", "VIS_0003.dng"]
        for name in self.names:
            (self.aerial / "VIS").mkdir(parents=True, exist_ok=True)
            (self.aerial / "VIS" / name).write_bytes(b"dng")
        write_json(self.aerial / "VIS" / "transfer_info_VIS_dng.json",
                   {"sync": {"idMin": 1, "idMax": 3, "listCopiedImages": self.names}})
        write_json(self.aerial / "VIS" / "time_line.json",
                   {"VIS": [{"img_path": f"x/{n}", "relative_timeline": float(k)} for k, n in enumerate(self.names)]})

    def tearDown(self):
        self.tmp.cleanup()

    def run_detection(self, **patches):
        stats = Aru.new_sync_stats("VIS")
        img = np.zeros((8, 8, 3), np.uint8)
        defaults = {"load_dng_for_aruco": mock.Mock(return_value=(img, "x.jpg")),
                    "detect_mobile_marker_absolute": mock.Mock(return_value=(dict(_RESULT), None, None)),
                    "read_aruco_cache": mock.Mock(return_value=None)}
        defaults.update(patches)
        with mock.patch.multiple(Aru, **defaults), mock.patch("sys.stdout", new=io.StringIO()):
            results = Aru.process_aruco_images(self.aerial, "VIS", "VIS", "dng", multi_thread=False, stats=stats,
                                               verbose=False)
        return results, stats

    def assert_fix(self, raised, *words):
        message = str(raised.exception)
        self.assertIn("How to fix:", message)
        for word in words:
            self.assertIn(word, message)


class SyncDataTests(MissionTest):
    def test_counts_of_a_good_run(self):
        (results, _, _), stats = self.run_detection()
        self.assertEqual(len(results), 3)
        self.assertEqual((stats["images"], stats["developed"], stats["detected"]), (3, 3, 3))
        self.assertIn("Visible: 3 synchronisation images, target found on 3", Aru.sync_stats_text(stats))

    def test_step1_not_done(self):
        (self.aerial / "VIS" / "transfer_info_VIS_dng.json").unlink()
        with self.assertRaises(Aru.SyncDataError) as raised:
            self.run_detection()
        self.assert_fix(raised, "Step 1")

    def test_no_synchronisation_window(self):
        write_json(self.aerial / "VIS" / "transfer_info_VIS_dng.json", {"fly": {}})
        with self.assertRaises(Aru.SyncDataError) as raised:
            self.run_detection()
        self.assert_fix(raised, "synchronisation window", "Step 2")

    def test_empty_synchronisation_window(self):
        write_json(self.aerial / "VIS" / "transfer_info_VIS_dng.json", {"sync": {"listCopiedImages": []}})
        with self.assertRaises(Aru.SyncDataError) as raised:
            self.run_detection()
        self.assert_fix(raised, "empty", "Step 2", "clock offset")

    def test_missing_time_line(self):
        """It used to be 'argument of type NoneType is not iterable'."""
        (self.aerial / "VIS" / "time_line.json").unlink()
        with self.assertRaises(Aru.SyncDataError) as raised:
            self.run_detection()
        self.assert_fix(raised, "time line", "Step 1")

    def test_image_not_in_the_time_line_is_left_out(self):
        """It used to be placed at -9999 s, wrecking the offset."""
        write_json(self.aerial / "VIS" / "time_line.json",
                   {"VIS": [{"img_path": "x/VIS_0001.dng", "relative_timeline": 0.0},
                            {"img_path": "x/VIS_0003.dng", "relative_timeline": 2.0}]})
        (results, x_vals, _), stats = self.run_detection()
        self.assertEqual([r["image"] for r in results], ["VIS_0001.dng", "VIS_0003.dng"])
        self.assertNotIn(Aru.NO_TIME, x_vals)
        self.assertEqual(stats["no_time"], ["VIS_0002.dng"])

    def test_missing_image_and_image_without_marker_counted(self):
        (self.aerial / "VIS" / "VIS_0002.dng").unlink()
        detect = mock.Mock(side_effect=[(dict(_RESULT), None, None), (None, None, None)])
        (results, _, _), stats = self.run_detection(detect_mobile_marker_absolute=detect)
        self.assertEqual(stats["missing"], ["VIS_0002.dng"])
        self.assertEqual(stats["no_marker"], ["VIS_0003.dng"])
        text = Aru.sync_stats_text(stats)
        self.assertIn("1 missing (VIS_0002.dng)", text)
        self.assertIn("1 without any marker (VIS_0003.dng)", text)

    def test_rawtherapee_developing_nothing(self):
        """Every development fails: one clear error instead of 'not enough points'."""
        def develop(path, folder, threads=None):
            raise Aru.DevelopmentError(f"RawTherapee could not develop VIS/{Path(path).name} (exit code 1).")
        with self.assertRaises(Aru.SyncDataError) as raised:
            self.run_detection(load_dng_for_aruco=mock.Mock(side_effect=develop))
        self.assert_fix(raised, "No visible synchronisation image could be developed", "Check the installation",
                        "exit code 1")

    def test_failed_development_never_reuses_the_old_image(self):
        dng = self.aerial / "VIS" / "VIS_0001.dng"
        jpeg = Path(Aru.cached_jpeg(str(dng), self.mission))
        jpeg.write_bytes(b"old image")
        os.utime(jpeg, (1_000_000_000, 1_000_000_000))          # older than the DNG
        with mock.patch.object(Aru, "require_tool", return_value="rawtherapee"), \
                mock.patch.object(Aru.subprocess, "call", return_value=1):
            with self.assertRaises(Aru.DevelopmentError) as raised:
                Aru.load_dng_for_aruco(str(dng), self.mission)
        self.assertIn("exit code 1", str(raised.exception))
        self.assertFalse(jpeg.exists())


class ExplanationTests(unittest.TestCase):
    def test_error_with_its_fix(self):
        error = Aru.SyncDataError("The list is missing.", "Run Step 1.\nThen Step 2.")
        problem = Problem.from_error(str(error), "Detection of the ArUco target")
        self.assertEqual(problem.title, "Detection of the ArUco target failed")
        self.assertEqual(problem.what, "The list is missing.")
        self.assertEqual(problem.fixes, ["Run Step 1.", "Then Step 2."])

    def test_known_system_errors(self):
        import config
        for message, words in (
                ("RawTherapee not found at C:\\RT\\rawtherapee-cli.exe. Install it from https://rawtherapee.com, "
                 "or set the environment variable RAWTHERAPEEPATH to its path.", ("RawTherapee", "RAWTHERAPEEPATH")),
                ("OSError: [Errno 28] No space left on device", ("disk is full",)),
                ("PermissionError: [Errno 13] Permission denied: 'G:\\\\Démo\\\\x.jpg'", ("another program",)),
                ("MemoryError: Unable to allocate 1.2 GiB", ("memory",)),
                ("FileNotFoundError: [Errno 2] No such file or directory: 'VIS_0001.exif'", ("EXIF", "Step 1")),
                ("ValueError: At least two NIR points are required", ("synchronisation window",)),
                ("KeyError: 'GPSLatitude'", ("Unexpected error", "Check the installation"))):
            problem = Problem.from_error(message, "Time alignment")
            text = problem.what + " " + " ".join(problem.fixes)
            for word in words:
                self.assertIn(word, text, message)
            self.assertEqual(problem.details, message)
        self.assertTrue(config)

    def test_offset_not_measured_says_why(self):
        vis = Aru.new_sync_stats("VIS")
        vis.update(images=40, developed=40, detected=0, no_marker=[f"VIS_{k:04d}.dng" for k in range(40)])
        nir = Aru.new_sync_stats("NIR")
        nir.update(images=30, not_developed=["NIR_0001.dng"], developed=29, detected=1)
        problem = Problem.offset_not_measured({"VIS": vis, "NIR": nir}, 0, 1)
        self.assertIn("found on 0 visible and 1 infrared", problem.what)
        fixes = " ".join(problem.fixes)
        self.assertIn("Check the installation", fixes)               # a development failed
        self.assertIn("synchronisation window of Step 2", fixes)      # no marker on the visible images
        self.assertIn("by hand", fixes)
        self.assertIn("40 without any marker", problem.details)


class WindowTests(unittest.TestCase):
    def test_dialog_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Synchro").mkdir()
            problem = Problem.Problem("Time alignment failed", "Too few images.", ["Do this.", "Then that."], "raw")
            dialog = Problem.ProblemDialog(problem, mission=tmp, extra="Enter the offset by hand…")
            self.assertFalse(dialog.btn_images.isHidden())
            with mock.patch("IRD_Interactive_diagnostic.check_installation") as check:
                dialog.btn_check.click()
            check.assert_called_once()
            with mock.patch("IRD_Interactive_diagnostic.create_diagnostic_report") as report:
                dialog.btn_report.click()
            self.assertEqual(Path(report.call_args.kwargs["mission"]), Path(tmp))
            self.assertFalse(report.call_args.kwargs["ask"])        # this mission, no question
            dialog.btn_extra.click()
            self.assertTrue(dialog.extra_clicked)

    def test_shown_and_printed(self):
        problem = Problem.Problem("Pairing failed", "Disk full.", ["Free space."])
        with mock.patch.object(Problem.ProblemDialog, "exec", return_value=0), \
                mock.patch("sys.stdout", new=io.StringIO()) as printed:
            self.assertFalse(Problem.show_problem(None, problem))
        self.assertIn("Pairing failed", printed.getvalue())
        self.assertIn("1. Free space.", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
