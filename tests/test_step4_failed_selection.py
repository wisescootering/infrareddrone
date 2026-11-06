import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERACTIVE = ROOT / "irdrone_wizard"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(INTERACTIVE))

spec = importlib.util.spec_from_file_location(
    "ird_interactive_4", INTERACTIVE / "IRD_Interactive_4.py"
)
step4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step4)


class FailedSelectionTests(unittest.TestCase):
    def test_numbers_from_local_jpegs(self):
        numbers, ignored = step4.image_numbers_from_aligned_jpegs(
            ["C:/x/VIR_0010_local.jpg", "C:/x/VIS_0011.jpg"]
        )
        self.assertEqual(numbers, {10})
        self.assertEqual(ignored, ["VIS_0011.jpg"])

    def test_numbers_from_ndvi_nir_and_global_jpegs(self):
        numbers, ignored = step4.image_numbers_from_aligned_jpegs(
            [
                "/x/NDVI_0012_local.jpg",
                "/x/ndvi_0013_global.JPG",
                "/x/NIR_0014_global.jpg",
                "/x/VIR_0015_global.jpg",
                "/x/VIS_0016_motion_model.json",
                "/x/NDVI_0017.jpg",
            ]
        )
        self.assertEqual(numbers, {12, 13, 14, 15})
        self.assertEqual(ignored, ["VIS_0016_motion_model.json", "NDVI_0017.jpg"])

    def test_redo_check_image_prefers_vir_local_and_skips_stale_files(self):
        import os
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            self.assertIsNone(step4.redo_check_image(folder, "VIS_0020"))
            stale = folder / "VIR_0020_local.jpg"
            stale.write_bytes(b"old")
            old_time = time.time() - 3600
            os.utime(stale, (old_time, old_time))
            (folder / "NDVI_0020_global.jpg").write_bytes(b"new")
            started = time.time() - 10
            self.assertEqual(
                step4.redo_check_image(folder, "VIS_0020", started).name,
                "NDVI_0020_global.jpg",
            )
            (folder / "VIR_0020_global.jpg").write_bytes(b"new")
            self.assertEqual(
                step4.redo_check_image(folder, "VIS_0020", started).name,
                "VIR_0020_global.jpg",
            )

    def test_only_existing_points_are_updated(self):
        inventory = {
            "shoot_points": [
                {"FileName": "VIS_0010.DNG", "dt": 0.1, "failed": False},
                {"FileName": "VIS_0011.DNG", "dt": 0.2, "failed": 0},
                {"FileName": "VIS_0012.DNG", "dt": 0.3, "failed": True},
                {"FileName": "VIS_0013.DNG", "dt": 0.3, "failed": False},
            ]
        }
        result = step4.apply_failed_selection(inventory, {10, 11, 12, 999})
        self.assertEqual(result["newly_flagged"], 2)
        self.assertEqual(result["already_flagged"], 1)
        self.assertEqual(result["not_found"], [999])
        points = inventory["shoot_points"]
        self.assertIs(points[0]["failed"], True)
        self.assertEqual(points[1]["failed"], 1)
        self.assertIs(points[3]["failed"], False)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0]["dt"], 0.1)

    def test_summary(self):
        inventory = {
            "shoot_points": [
                {"FileName": "VIS_0010.DNG", "failed": True},
                {"FileName": "VIS_0011.DNG", "failed": False},
            ]
        }
        self.assertEqual(
            step4.build_failed_summary(inventory),
            {
                "failed_false": ["0011"],
                "failed_true": ["0010"],
                "count_failed_false": 1,
                "count_failed_true": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
