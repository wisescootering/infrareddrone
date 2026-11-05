import importlib.util
import json
import locale
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERACTIVE = ROOT / "irdrone Interactive"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(INTERACTIVE))

spec = importlib.util.spec_from_file_location(
    "ird_interactive_4_redo", INTERACTIVE / "IRD_Interactive_4.py"
)
step4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step4)


def make_inventory():
    return {
        "time_shift": -48.1,
        "shoot_points": [
            {"FileName": "VIS_0010.dng", "dt": 0.1, "failed": False},
            {"FileName": "VIS_0011.dng", "dt": 0.2, "failed": True},
            {"FileName": "VIS_0012.dng", "dt": 0.3, "failed": 1},
            {"FileName": "VIS_0013.dng", "dt": 0.3, "failed": 0},
        ],
    }


class RedoStatusTests(unittest.TestCase):
    def test_failed_point_names(self):
        self.assertEqual(
            step4.failed_point_names(make_inventory()),
            [(11, "VIS_0011"), (12, "VIS_0012")],
        )

    def test_clear_failed_selection_keeps_value_type(self):
        inventory = make_inventory()
        result = step4.clear_failed_selection(inventory, {10, 11, 12, 999})
        self.assertEqual(result["cleared"], 2)
        self.assertEqual(result["not_flagged"], 1)
        self.assertEqual(result["not_found"], [999])
        points = inventory["shoot_points"]
        self.assertIs(points[1]["failed"], False)
        self.assertEqual(points[2]["failed"], 0)
        self.assertNotIsInstance(points[2]["failed"], bool)
        self.assertEqual(points[1]["dt"], 0.2)

    def test_mark_points_aligned_updates_both_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            inventory_path = folder / "shoot_points.json"
            inventory_path.write_text(json.dumps(make_inventory()), encoding="utf-8")
            step4.mark_points_aligned(folder, {11})

            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            self.assertIs(inventory["shoot_points"][1]["failed"], False)
            self.assertEqual(inventory["shoot_points"][2]["failed"], 1)
            self.assertEqual(inventory["time_shift"], -48.1)
            summary = json.loads(
                (folder / step4.FAILED_SUMMARY_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["failed_true"], ["0012"])
            self.assertEqual(summary["count_failed_false"], 3)
            self.assertTrue((folder / "shoot_points.json.bak").is_file())


class ReadRedoCommandTests(unittest.TestCase):
    def test_active_command_arguments(self):
        text = (
            "REM Full recovery run\n"
            "call activate env\n"
            "REM NIR rank 1: C:\\Air Mission\\NIR_0200.dng\n"
            'python "C:\\code\\automatic_registration.py" --images "C:\\Air Mission\\VIS_0011.dng" '
            '"C:\\Air Mission\\NIR_0200.dng" --manual --outdir "C:\\Air Mission\\ImgIRdrone" --debug '
            "--angles 1.000 2.000 3.000 --traces vis nir vir ndvi --alignment-modes local global --redo\n"
            "REM REM NIR rank 2: C:\\Air Mission\\NIR_0201.dng\n"
            'REM python "C:\\code\\automatic_registration.py" --images "x" "y" --redo\n'
            "call deactivate\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / "VIS_0011_REDO.bat"
            batch.write_text(text, encoding=locale.getpreferredencoding(False))
            arguments = step4.read_redo_command(batch)
        self.assertEqual(arguments[0], "--images")
        self.assertEqual(arguments[1], "C:\\Air Mission\\VIS_0011.dng")
        self.assertEqual(arguments[2], "C:\\Air Mission\\NIR_0200.dng")
        self.assertIn("--redo", arguments)
        self.assertEqual(arguments[arguments.index("--outdir") + 1], "C:\\Air Mission\\ImgIRdrone")
        self.assertEqual(arguments[arguments.index("--angles") + 1:][:3], ["1.000", "2.000", "3.000"])

    def test_no_active_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / "VIS_0011_REDO.bat"
            batch.write_text("REM python x --images a b --redo\n", encoding="ascii")
            with self.assertRaises(ValueError):
                step4.read_redo_command(batch)


if __name__ == "__main__":
    unittest.main()
