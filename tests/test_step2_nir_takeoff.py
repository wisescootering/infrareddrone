import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "irdrone_wizard"))

from PyQt6.QtWidgets import QApplication

from IRD_Interactive_2 import LoadVisNirImagesDialog

_app = QApplication.instance() or QApplication([])


class FirstNirImageTests(unittest.TestCase):
    def test_first_dng_by_name_ignoring_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ["NIR_0003.dng", "NIR_0001.exif", "time_line.json", "NIR_0002.DNG", "NIR_0010.dng"]:
                (folder / name).touch()
            first = LoadVisNirImagesDialog.first_image_in_folder(folder, "dng")
            self.assertEqual(first, folder / "NIR_0002.DNG")

    def test_none_when_no_image_or_no_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(LoadVisNirImagesDialog.first_image_in_folder(Path(tmp), "dng"))
            self.assertIsNone(LoadVisNirImagesDialog.first_image_in_folder(Path(tmp) / "missing", "dng"))


if __name__ == "__main__":
    unittest.main()
