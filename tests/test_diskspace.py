"""Disk full: one clear error instead of one per file, no empty or half-written
files left behind, and empty .exif files (from an earlier full disk) redone."""
import errno
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

import IRD_Interactive_diskspace as Disk  # noqa: E402

DISK_FULL = OSError(errno.ENOSPC, "No space left on device")


class DiskSpaceTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_disk_full_detection(self):
        self.assertTrue(Disk.is_disk_full(DISK_FULL))
        self.assertFalse(Disk.is_disk_full(OSError(errno.EACCES, "denied")))
        self.assertFalse(Disk.is_disk_full(ValueError()))
        windows = OSError(errno.EINVAL, "disk full")
        windows.winerror = 112
        self.assertTrue(Disk.is_disk_full(windows))

    def test_raise_if_disk_full(self):
        with self.assertRaises(Disk.DiskFullError) as caught:
            Disk.raise_if_disk_full(DISK_FULL, self.folder)
        self.assertIn("is full", str(caught.exception))
        self.assertIn("⚙", str(caught.exception))  # tells where to change the folder
        Disk.raise_if_disk_full(OSError(errno.EACCES, "denied"))  # not disk full: no-op

    def test_atomic_json_keeps_the_previous_content_when_the_disk_is_full(self):
        path = self.folder / "VIS_0001.exif"
        path.write_text('{"good": 1}')
        with mock.patch("IRD_Interactive_diskspace.json.dump", side_effect=DISK_FULL):
            with self.assertRaises(Disk.DiskFullError):
                Disk.write_json_atomic(path, {"new": 2})
        self.assertEqual(json.loads(path.read_text()), {"good": 1})
        self.assertEqual(list(self.folder.iterdir()), [path])  # no .tmp left behind

    def test_atomic_json_writes(self):
        path = self.folder / "a.json"
        Disk.write_json_atomic(path, {"a": 1})
        self.assertEqual(json.loads(path.read_text()), {"a": 1})

    def test_valid_json_file(self):
        empty = self.folder / "empty.exif"
        empty.write_text("")
        good = self.folder / "good.exif"
        good.write_text('{"a": 1}')
        self.assertFalse(Disk.is_valid_json_file(empty))
        self.assertFalse(Disk.is_valid_json_file(self.folder / "missing.exif"))
        self.assertTrue(Disk.is_valid_json_file(good))

    def test_folder_size_and_shortage(self):
        (self.folder / "a.dng").write_bytes(b"x" * 100)
        (self.folder / "b.DNG").write_bytes(b"x" * 50)
        (self.folder / "c.txt").write_bytes(b"x" * 1000)
        self.assertEqual(Disk.folder_size(self.folder, {".dng"}), 150)
        self.assertIsNone(Disk.space_shortage(self.folder, 1))
        with mock.patch.object(Disk, "free_bytes", return_value=10):
            self.assertEqual(Disk.space_shortage(self.folder, 100), (10, 100))

    def test_format_bytes(self):
        self.assertEqual(Disk.format_bytes(64 * 1024), "64 KB")
        self.assertEqual(Disk.format_bytes(31 * 1024 ** 3), "31.0 GB")


class CopyTest(unittest.TestCase):
    def test_half_copied_image_is_removed_and_the_copy_stops(self):
        import IRD_Interactive_utils as Uti
        folder = Path(tempfile.mkdtemp())
        source, target = folder / "in", folder / "out"
        source.mkdir()
        target.mkdir()
        (source / "HYPERLAPSE_0001.DNG").write_bytes(b"raw")

        def partial_copy(src, dst):
            Path(dst).write_bytes(b"r")  # half written, then the disk is full
            raise DISK_FULL

        with mock.patch("IRD_Interactive_utils.shutil.copy2", side_effect=partial_copy):
            with self.assertRaises(Disk.DiskFullError):
                Uti.copy_and_rename_images(source, "HYPERLAPSE_0001.DNG", target, "VIS_0001.DNG")
        self.assertFalse((target / "VIS_0001.DNG").exists())


class CreateExifTest(unittest.TestCase):
    def test_empty_exif_files_are_redone(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_workers as Worker
        folder = Path(tempfile.mkdtemp())
        for name in ("VIS_0001", "VIS_0002"):
            (folder / f"{name}.dng").write_bytes(b"dng")
        (folder / "VIS_0001.exif").write_text("")             # left by a full disk
        (folder / "VIS_0002.exif").write_text('{"ok": true}')  # good: kept
        redone = []

        def read_exif(path, _exiftool):
            redone.append(Path(path).name)
            return {}

        with mock.patch.object(Worker.ExifToolPersist, "start"), \
                mock.patch.object(Worker.Uti, "read_exif_and_write_json", side_effect=read_exif), \
                mock.patch.object(Worker.Uti, "list_tempo_time_line", return_value=[]), \
                mock.patch.object(Worker.Uti, "time_line_analyser_images", return_value={"VIS": []}), \
                mock.patch.object(Worker.Uti, "save_time_line_json"):
            worker = Worker.CreateExif(str(folder), "msg", "VIS")
            worker.run()
        self.assertEqual(redone, ["VIS_0001.dng"])

    def test_disk_full_stops_with_one_clear_error(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_workers as Worker
        folder = Path(tempfile.mkdtemp())
        for index in range(20):
            (folder / f"VIS_{index:04d}.dng").write_bytes(b"dng")
        errors = []
        with mock.patch.object(Worker.ExifToolPersist, "start"), \
                mock.patch.object(Worker.Uti, "read_exif_and_write_json",
                                  side_effect=Disk.DiskFullError(folder)):
            worker = Worker.CreateExif(str(folder), "msg", "VIS")
            worker.error.connect(errors.append)
            worker.run()
        self.assertEqual(len(errors), 1)
        self.assertIn("is full", errors[0])


class Step1NirCancelTest(unittest.TestCase):
    """Cancelling the NIR image choice used to crash on Path(None)."""

    def test_cancel_stops_step1_cleanly(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_1 as Step1
        window = mock.MagicMock()
        window.mission_parameters = {"File path mission": tempfile.mkdtemp()}
        window.load_NIR_directory.return_value = None
        done = mock.MagicMock()
        with mock.patch.object(Step1.Uti, "show_info_message"), \
                mock.patch.object(Step1.Worker, "Transfer_NIR") as transfer:
            Step1.Window_create_file_structure.start_transfer_NIR(window, done)
        transfer.assert_not_called()
        done.assert_not_called()
        window._stop_pipeline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
