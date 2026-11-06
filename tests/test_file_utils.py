import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from irdrone.file_utils import find_ci, glob_ci, glob_path_ci, has_suffix, with_suffix_ci
from irdrone.utils import imagepath


class CaseInsensitiveFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        for name in ("VIS_0001.DNG", "VIS_0002.dng", "NIR_0001.RAW", "nir_0002.raw", "notes.txt"):
            (self.folder / name).write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, paths):
        return [Path(p).name for p in paths]

    def test_glob_ignores_case(self):
        self.assertEqual(self.names(glob_ci(self.folder, "*.dng")), ["VIS_0001.DNG", "VIS_0002.dng"])
        self.assertEqual(self.names(glob_ci(self.folder, "*.RAW")), ["NIR_0001.RAW", "nir_0002.raw"])
        self.assertEqual(glob_ci(self.folder / "missing", "*.dng"), [])

    def test_names_differing_by_case_are_listed_once(self):
        if os.name == "nt":
            self.skipTest("two names differing by case cannot coexist on Windows")
        (self.folder / "VIS_0001.dng").write_bytes(b"x")
        self.assertEqual(len(glob_ci(self.folder, "*.dng")), 2)

    def test_glob_path_and_imagepath(self):
        self.assertEqual(self.names(glob_path_ci(self.folder / "*.DNG")), ["VIS_0001.DNG", "VIS_0002.dng"])
        self.assertEqual(self.names(imagepath("*.DNG", str(self.folder))), ["VIS_0001.DNG", "VIS_0002.dng"])

    def test_find_and_suffix_helpers(self):
        self.assertEqual(find_ci(self.folder / "VIS_0001.dng").name, "VIS_0001.DNG")
        self.assertIsNone(find_ci(self.folder / "VIS_0003.dng"))
        self.assertTrue(has_suffix("a/b.RAW", "raw"))
        self.assertFalse(has_suffix("a/b.dng", ".raw"))
        self.assertEqual(with_suffix_ci("a/x.raw", ".RAW", ".dng"), "a/x.dng")
        self.assertEqual(with_suffix_ci("a/x.RAW", ".raw", ".dng"), "a/x.dng")
        self.assertEqual(with_suffix_ci("a/x.tif", ".raw", ".dng"), "a/x.tif")


if __name__ == "__main__":
    unittest.main()
