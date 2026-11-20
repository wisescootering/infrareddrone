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
from config import EXIFTOOLPATH, SJCONVERTERPATH  # noqa: E402

SAMPLE = ROOT / "samples" / "505-DJI-VI.JPG"
RAW_SAMPLE = ROOT / "samples" / "_nir.RAW"
RAW_NAME = "2022_0125_130446_023.RAW"     # as named by the SJCam camera


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



class AccentedRawConversionTest(unittest.TestCase):
    """SJCam RAW -> DNG with accents in the SD card folder or the mission folder:
    on Windows sjcam_raw2dng and ExifTool get their command line in the ANSI
    code page ("D?mo"), so no accented path may go through it."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sd_card = self.root / "Carte SD Démo" / "DCIM"
        self.output = self.root / "Démo Florine" / "AerialPhotography" / "NIR"
        self.sd_card.mkdir(parents=True)
        self.output.mkdir(parents=True)
        self.raw = self.sd_card / RAW_NAME

    def test_no_accented_path_on_the_command_lines(self):
        import IRD_Interactive_utils as Uti
        self.raw.write_bytes(b"raw")
        calls = []

        def run(cmd, cwd=None, input=None, **kwargs):
            calls.append(cmd)
            if cmd[0] == "exiftool":
                self.assertIn(str(self.output / "NIR_0001.dng"), input)    # UTF-8, on stdin
                return mock.Mock(returncode=0, stderr="")
            output = Path(cmd[cmd.index("--output") + 1])
            self.assertTrue((Path(cwd) / cmd[-1]).is_file())    # the RAW, found from the working folder
            (output / (Path(cmd[-1]).stem + ".dng")).write_bytes(b"dng")

        with mock.patch("subprocess.run", side_effect=run):
            dng = Uti._convert_single_raw_to_dng(str(self.raw), "sjcam_raw2dng", str(self.output), "0",
                                                 False, "exiftool", dng_name="NIR_0001.dng")
        self.assertEqual(Path(dng), self.output / "NIR_0001.dng")
        self.assertEqual((self.output / "NIR_0001.dng").read_bytes(), b"dng")
        self.assertEqual(len(calls), 2)
        for cmd in calls:
            self.assertTrue(all(str(arg).isascii() for arg in cmd), cmd)
        self.assertEqual(list(Path(Uti._ascii_folder_near(self.output)).glob("irdrone_raw2dng_*")), [])

    @unittest.skipUnless(
        Path(str(SJCONVERTERPATH)).is_file() and EXIFTOOLPATH and Path(EXIFTOOLPATH).is_file()
        and RAW_SAMPLE.is_file(),
        "needs sjcam_raw2dng, ExifTool and the RAW sample",
    )
    def test_converts_from_and_to_accented_folders(self):
        import IRD_Interactive_utils as Uti
        shutil.copy(RAW_SAMPLE, self.raw)
        dng = Uti._convert_single_raw_to_dng(str(self.raw), str(SJCONVERTERPATH), str(self.output), "0",
                                             False, str(EXIFTOOLPATH), dng_name="NIR_0001.dng")
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ["NIR_0001.dng"])
        metadata = exiftool_reader.read_exiftool_json(EXIFTOOLPATH, dng)
        self.assertEqual(metadata["DateTimeOriginal"], "2022:01:25 13:04:46")


if __name__ == "__main__":
    unittest.main()
