"""Accents in the mission folder ("G:\\Démo Florine\\..."): on Windows ExifTool
wrote "D?mo" in the Directory tag and every .exif path rebuilt from it was
missing ("[ERROR] in update_exif_json")."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import exiftool_reader  # noqa: E402
from config import EXIFTOOLPATH  # noqa: E402

SAMPLE = ROOT / "samples" / "505-DJI-VI.JPG"


class AccentedFolderTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / "Démo Florine" / "VIS"
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder.parents[1])

    @unittest.skipUnless(
        EXIFTOOLPATH and Path(EXIFTOOLPATH).is_file() and SAMPLE.is_file(),
        "needs ExifTool and the DJI sample",
    )
    def test_exiftool_reads_a_file_in_an_accented_folder(self):
        image = self.folder / "VIS_0001_é.jpg"
        shutil.copy(SAMPLE, image)
        metadata = exiftool_reader.read_exiftool_json(EXIFTOOLPATH, image)
        self.assertEqual(metadata["Directory"], str(self.folder))
        self.assertEqual(metadata["FileName"], image.name)
        self.assertIn("DateTimeOriginal", metadata)

    def test_timeline_updates_the_exif_files_found_on_disk(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_workers as Worker
        for index in (1, 2):
            (self.folder / f"VIS_{index:04d}.dng").write_bytes(b"dng")
            (self.folder / f"VIS_{index:04d}.exif").write_text(json.dumps({
                "FileName": f"VIS_{index:04d}.dng",
                "Directory": "G:/D?mo Florine/VIS",  # as ExifTool wrote it on Windows
                "DateTimeOriginal": f"2022:01:25 12:00:0{index}",
            }), encoding="utf-8")
        with mock.patch.object(Worker.ExifToolPersist, "start"), \
                mock.patch("builtins.print") as printed:
            Worker.CreateExif(str(self.folder), "msg", "VIS").run()
        errors = [c for c in printed.call_args_list if "ERROR" in str(c)]
        self.assertEqual(errors, [])
        for index in (1, 2):
            data = json.loads((self.folder / f"VIS_{index:04d}.exif").read_text(encoding="utf-8"))
            self.assertIn("RelativeTimeLine", data)

    def test_images_are_read_and_written_in_an_accented_folder(self):
        import numpy as np
        import cv2
        import image_io
        image = (np.arange(12 * 8 * 3) % 65535).astype(np.uint16).reshape(12, 8, 3)
        for name in ("NIR_0001_é.tif", "VIS_0001_é.png"):
            path = self.folder / name
            self.assertTrue(image_io.imwrite(path, image))
            np.testing.assert_array_equal(image_io.imread(path, cv2.IMREAD_UNCHANGED), image)
        self.assertIsNone(image_io.imread(self.folder / "missing.jpg"))


if __name__ == "__main__":
    unittest.main()
