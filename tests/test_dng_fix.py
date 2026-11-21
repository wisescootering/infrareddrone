"""irdrone/dng_fix.py: the DNG of sjcam_raw2dng readable by RawTherapee 5.11 and newer (5.13 tore it)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

import config  # noqa: E402
from irdrone import dng_fix  # noqa: E402

SAMPLE_RAW = ROOT / "samples" / "_nir.RAW"
CONVERTER = config._SJCONVERTER_FOUND and config._EXIFTOOL_FOUND


def pack_raw12(mosaic):
    """The inverse of unpack_raw12 (two 12 bits samples in 3 bytes, low bits first)."""
    flat = mosaic.reshape(-1).astype(np.uint16)
    a, b = flat[0::2], flat[1::2]
    out = np.empty(flat.size // 2 * 3, dtype=np.uint8)
    out[0::3] = a & 0xFF
    out[1::3] = ((a >> 8) & 0x0F) | ((b & 0x0F) << 4)
    out[2::3] = b >> 4
    return out.tobytes()


class UnpackTest(unittest.TestCase):
    def test_round_trip(self):
        mosaic = np.random.default_rng(0).integers(0, 4096, (6, 8), dtype=np.uint16)
        self.assertTrue(np.array_equal(dng_fix.unpack_raw12(pack_raw12(mosaic), 8, 6), mosaic))

    def test_wrong_size_is_refused(self):
        with self.assertRaises(dng_fix.DngFixError):
            dng_fix.unpack_raw12(b"\0" * 100, 8, 6)

    def test_not_a_dng_needs_no_fix(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.dng"
            path.write_bytes(b"not a tiff at all")
            self.assertFalse(dng_fix.needs_fix(path))
            self.assertFalse(dng_fix.needs_fix(Path(folder) / "missing.dng"))


@unittest.skipUnless(CONVERTER and SAMPLE_RAW.is_file(), "SJCam converter / ExifTool / sample not available")
class FixedDngTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="irdrone_dngfix_"))
        raw = cls.folder / "2022_0125_130446_023.RAW"
        shutil.copy(SAMPLE_RAW, raw)
        subprocess.run([config.SJCONVERTERPATH, "--no-color", "--thumb", "--threads", "0", "--output",
                        str(cls.folder), str(raw)], check=True, capture_output=True)
        cls.raw = raw
        cls.dng = cls.folder / "2022_0125_130446_023.dng"
        cls.original = cls.folder / "original.dng"
        shutil.copy(cls.dng, cls.original)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def fixed(self):
        copy = self.folder / "copy.dng"
        shutil.copy(self.original, copy)
        return copy

    def test_the_converter_dng_needs_the_fix_once(self):
        copy = self.fixed()
        self.assertTrue(dng_fix.needs_fix(copy))
        self.assertTrue(dng_fix.fix_sjcam_dng(copy, self.raw))
        self.assertFalse(dng_fix.needs_fix(copy))
        self.assertFalse(dng_fix.fix_sjcam_dng(copy, self.raw))      # nothing left to do

    def test_the_raw_image_is_the_mosaic_of_the_raw_file(self):
        import rawpy
        copy = self.fixed()
        dng_fix.fix_sjcam_dng(copy, self.raw)
        with rawpy.imread(str(copy)) as image:
            mosaic = image.raw_image.copy()
            self.assertEqual(image.white_level, 4095)
        self.assertTrue(np.array_equal(mosaic, dng_fix.unpack_raw12(self.raw.read_bytes(), 4608, 3456)))

    def test_the_black_level_stays_as_it_was_developed(self):
        out = subprocess.run([config.EXIFTOOLPATH, "-s3", "-SubIFD:BlackLevel", str(self.fixed())],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "200 200 200")                          # not fixed yet: the converter's value
        copy = self.fixed()
        dng_fix.fix_sjcam_dng(copy, self.raw)
        out = subprocess.run([config.EXIFTOOLPATH, "-s3", "-SubIFD:BlackLevel", str(copy)],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "0")

    def test_the_file_is_a_valid_dng_with_its_metadata(self):
        copy = self.fixed()
        dng_fix.fix_sjcam_dng(copy, self.raw)
        out = subprocess.run([config.EXIFTOOLPATH, "-validate", "-s3", "-Validate", "-DateTimeOriginal",
                              "-SubIFD:SamplesPerPixel", "-SubIFD:Compression", str(copy)],
                             capture_output=True, text=True).stdout.split("\n")
        self.assertIn("OK", out[0])
        self.assertIn("1", out)
        self.assertIn("Uncompressed", out)

    def test_conversion_applies_the_fix_to_a_dng_converted_before(self):
        from irdrone.convert_raw_to_dng import _convert_single_raw
        folder = Path(tempfile.mkdtemp(prefix="irdrone_dngfix_old_"))
        try:
            raw = folder / "2022_0125_130446_023.RAW"
            shutil.copy(SAMPLE_RAW, raw)
            shutil.copy(self.original, folder / "NIR_0023.dng")      # left by an earlier version
            dng = Path(_convert_single_raw(str(raw), config.SJCONVERTERPATH, str(folder), "0", False,
                                           config.EXIFTOOLPATH))
            self.assertFalse(dng_fix.needs_fix(dng))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
