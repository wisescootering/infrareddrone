"""Installation self-tests (selftests.py, "Check the installation" in the wizard)."""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

import config  # noqa: E402
import selftests  # noqa: E402

RAWTHERAPEE = config._RAWTHERAPEE_FOUND
SJCAM = config._SJCONVERTER_FOUND and config._EXIFTOOL_FOUND


def run(*names, log=lambda text: None):
    return selftests.run_checks(names, log=log)


def missing_tool(variable):
    """config._TOOLS with ``variable`` not found."""
    tools = tuple((label, var, "/nowhere/tool", False if var == variable else found, need, hint)
                  for label, var, path, found, need, hint in config._TOOLS)
    return mock.patch.object(config, "_TOOLS", tools)


class QuickChecksTest(unittest.TestCase):
    def test_python_opencv_aruco_tiff_accents_pass(self):
        results = run("python", "packages", "opencv", "accented_folder", "tiff", "aruco", "processes")
        for name, result in results.items():
            self.assertTrue(result["ok"], (name, result))
        self.assertLess(max(results["aruco"]["data"]["angle_errors_deg"].values()), 3)

    def test_alignment_finds_a_known_shift(self):
        result = run("alignment")["alignment"]
        self.assertEqual(result["status"], selftests.OK, result)
        self.assertLess(result["data"]["error_px"], 1.5)

    def test_broken_alignment_is_reported_with_a_fix(self):
        import registration.rigid as rigid

        class Identity:
            model = np.eye(3)
        with mock.patch.object(rigid, "pyramidal_search", side_effect=lambda *a, **k: Identity()):
            result = run("alignment")["alignment"]
        self.assertEqual(result["status"], selftests.FAILED)
        self.assertIn("pixels", result["detail"])
        self.assertIn("numpy", result["fix"])

    def test_missing_rawtherapee_fails_and_skips_the_developments(self):
        with missing_tool("RAWTHERAPEEPATH"):
            results = run("rawtherapee", "dng_step3", "dng_step4", "sjcam_step3")
        self.assertEqual(results["rawtherapee"]["status"], selftests.FAILED)
        self.assertIn("RAWTHERAPEEPATH", results["rawtherapee"]["fix"])
        self.assertIn("rawtherapee.com", results["rawtherapee"]["fix"])
        for name in ("dng_step3", "dng_step4", "sjcam_step3"):
            self.assertEqual(results[name]["status"], selftests.SKIPPED, name)
            self.assertIn("RawTherapee", results[name]["detail"])

    def test_tool_that_does_not_run_fails(self):
        tools = tuple((label, var, sys.executable if var == "SJCONVERTERPATH" else path,
                       True if var == "SJCONVERTERPATH" else found, need, hint)
                      for label, var, path, found, need, hint in config._TOOLS)
        with mock.patch.object(config, "_TOOLS", tools), \
                mock.patch.object(selftests, "_run", return_value=(1, "")):
            result = run("sjcam_converter")["sjcam_converter"]
        self.assertEqual(result["status"], selftests.FAILED)
        self.assertIn("does not run", result["detail"])

    def test_missing_package_is_named_with_the_pip_command(self):
        modules = selftests.MODULES + (("not_a_real_module_irdrone", "irdrone-fake", "a test", True),)
        with mock.patch.object(selftests, "MODULES", modules):
            result = run("packages")["packages"]
        self.assertEqual(result["status"], selftests.FAILED)
        self.assertIn("irdrone-fake", result["detail"])
        self.assertIn("pip install -r requirements.txt", result["fix"])

    def test_opencv_without_aruco_fails(self):
        import types
        without_aruco = types.SimpleNamespace(__version__="4.8.0", __file__="cv2.pyd")
        with mock.patch.dict(sys.modules, {"cv2": without_aruco}):
            result = run("opencv")["opencv"]
        self.assertEqual(result["status"], selftests.FAILED)
        self.assertIn("opencv-contrib-python", result["fix"])

    def test_black_development_is_detected(self):
        with self.assertRaises(selftests.CheckError) as raised:
            selftests._check_not_flat(np.zeros((20, 20, 3), np.uint8), "The image", 0, 255, "fix it")
        self.assertIn("uniform", raised.exception.detail)
        image = np.zeros((20, 20), np.uint8)
        image[::2] = 9
        with self.assertRaises(selftests.CheckError) as raised:
            selftests._check_not_flat(image, "The image", 0, 255, "fix it")
        self.assertIn("black", raised.exception.detail)

    def test_unexpected_error_is_a_failure_with_traceback(self):
        checks = (("boom", "Boom", lambda ctx: 1 / 0),)
        with mock.patch.object(selftests, "CHECKS", checks):
            result = selftests.run_checks(log=lambda text: None)["boom"]
        self.assertEqual(result["status"], selftests.FAILED)
        self.assertIn("ZeroDivisionError", result["detail"])
        self.assertIn("traceback", result["data"])

    def test_text_and_command_line(self):
        results = run("python", "tiff")
        text = selftests.text(results)
        self.assertIn("[OK     ] 16 bits TIFF", text)
        self.assertIn("Installation OK", text)
        with mock.patch.object(selftests, "QUICK", ("python",)), \
                mock.patch("sys.stdout", new=io.StringIO()) as printed:
            self.assertEqual(selftests.main(["--quick"]), 0)
        self.assertIn("[OK     ] Python", printed.getvalue())

    def test_failed_summary(self):
        results = {"a": {"status": selftests.FAILED}, "b": {"status": selftests.OK}}
        self.assertIn("1 check(s) FAILED", selftests.summary(results)[0])


@unittest.skipUnless(RAWTHERAPEE and config._EXIFTOOL_FOUND, "RawTherapee / ExifTool not installed")
class DjiDngTest(unittest.TestCase):
    def test_dji_dng_metadata_and_developments(self):
        results = run("exiftool", "rawtherapee", "tiff", "dng_exif", "dng_step3", "dng_step4")
        for name, result in results.items():
            self.assertEqual(result["status"], selftests.OK, (name, result))
        self.assertEqual(results["dng_step3"]["data"]["shape"][:2], [2992, 3992])
        self.assertEqual(results["dng_step4"]["data"]["dtype"], "float32")


@unittest.skipUnless(RAWTHERAPEE and SJCAM, "SJCam converter / RawTherapee / ExifTool not installed")
class SjcamRawTest(unittest.TestCase):
    def test_sjcam_raw_converted_dated_and_developed(self):
        results = run("exiftool", "rawtherapee", "sjcam_converter", "tiff", "sjcam_raw", "sjcam_step3",
                      "sjcam_step4")
        for name, result in results.items():
            self.assertEqual(result["status"], selftests.OK, (name, result))
        self.assertEqual(results["sjcam_raw"]["data"]["DateTimeOriginal"], selftests.SAMPLE_RAW_DATE)
        self.assertEqual(results["sjcam_raw"]["data"]["dng"], "NIR_0023.dng")


if __name__ == "__main__":
    unittest.main()
