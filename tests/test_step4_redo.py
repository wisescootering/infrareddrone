import importlib.util
import json
import locale
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERACTIVE = ROOT / "irdrone_wizard"
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

    def test_reads_shell_script_written_by_alignment(self):
        sys.path.insert(0, str(ROOT))
        from automatic_registration import write_manual_bat_redo

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Air Mission"
            folder.mkdir()
            script = folder / "VIS_0011_REDO.sh"
            write_manual_bat_redo(
                folder / "VIS_0011.dng",
                [(folder / "NIR_0200.dng", 1), (folder / "NIR_0201.dng", 2)],
                script,
                folder / "ImgIRdrone",
                angles=(1.0, 2.0, 3.0),
            )
            arguments = step4.read_redo_command(script)
        self.assertEqual(arguments[:3], [
            "--images", str(folder / "VIS_0011.dng"), str(folder / "NIR_0200.dng"),
        ])
        self.assertEqual(arguments[arguments.index("--outdir") + 1], str(folder / "ImgIRdrone"))
        self.assertIn("--redo", arguments)

    def test_no_active_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            batch = Path(temporary) / "VIS_0011_REDO.bat"
            batch.write_text("REM python x --images a b --redo\n", encoding="ascii")
            with self.assertRaises(ValueError):
                step4.read_redo_command(batch)


class ManualRedoArgumentsTests(unittest.TestCase):
    ARGS = ["--images", "/m/VIS_0011.dng", "/m/NIR_0200.dng", "--manual", "--outdir", "/m/Out",
            "--debug", "--angles", "1.000", "-2.000", "3.000", "--traces", "vis", "nir", "--redo"]

    def test_pair_and_initial_angles(self):
        vis, nir, angles = step4.redo_pair(self.ARGS)
        self.assertEqual((vis.name, nir.name), ("VIS_0011.dng", "NIR_0200.dng"))
        self.assertEqual(angles, (1.0, -2.0, 3.0))
        self.assertIsNone(step4.redo_pair(["--images", "a", "b"])[2])
        with self.assertRaises(ValueError):
            step4.redo_pair(["--images", "a"])

    def test_aligned_by_hand_no_slider_window(self):
        arguments = step4.manual_redo_arguments(self.ARGS, (0.5, -1.25, 0.0))
        self.assertNotIn("--manual", arguments)
        self.assertNotIn("--angles", arguments)
        self.assertEqual(arguments[-4:], ["--manual-angles", "0.500", "-1.250", "0.000"])
        self.assertEqual(arguments[:3], self.ARGS[:3])
        self.assertIn("--redo", arguments)
        again = step4.manual_redo_arguments(arguments, (1, 2, 3))     # realigned once more
        self.assertEqual(again.count("--manual-angles"), 1)
        self.assertEqual(again[-3:], ["1.000", "2.000", "3.000"])
        self.assertEqual(again.count("--no-diagnostics"), 1)
        self.assertEqual(again.count("--traces"), 1)

    def test_aligned_by_hand_without_diagnostics_nor_images_the_point_never_had(self):
        """The REDO script asks for everything (recovery by hand); the wizard
        writes no diagnostic image and only the images the point has."""
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            args = [a if a != "/m/Out" else str(out) for a in self.ARGS] + ["--alignment-modes", "local", "global"]
            arguments = step4.manual_redo_arguments(args, (0, 0, 0))
            self.assertNotIn("--debug", arguments)
            self.assertIn("--no-diagnostics", arguments)
            # nothing yet for the point: the Step 4 default
            self.assertEqual(step4._option_values(arguments, "--traces"), ["vis", "vir"])
            self.assertEqual(step4._option_values(arguments, "--alignment-modes"), ["local"])
            for name in ("VIR_0011_local.jpg", "NDVI_0011_local.jpg", "NDVI_0011_global.jpg",
                         "NIR_0012_local.jpg"):                    # the last one: another point
                (out / name).write_bytes(b"jpg")
            self.assertEqual(step4.redo_outputs(out, "VIS_0011"), (["vir", "ndvi"], ["local", "global"]))
            arguments = step4.manual_redo_arguments(args, (0, 0, 0))
            self.assertEqual(step4._option_values(arguments, "--traces"), ["vis", "vir", "ndvi"])
            self.assertEqual(step4._option_values(arguments, "--alignment-modes"), ["local", "global"])
            self.assertEqual(step4._option_values(arguments, "--outdir"), [str(out)])

    def test_aligned_by_hand_with_the_debug_detail_level_is_the_full_recovery_run(self):
        arguments = step4.manual_redo_arguments(self.ARGS, (0, 0, 0), diagnostics=True)
        self.assertIn("--debug", arguments)
        self.assertNotIn("--no-diagnostics", arguments)
        self.assertEqual(step4._option_values(arguments, "--traces"), ["vis", "nir"])

    def test_cli_accepts_manual_angles(self):
        """automatic_registration.py parses --manual-angles (no window: implies --manual)."""
        text = (ROOT / "automatic_registration.py").read_text(encoding="utf-8")
        self.assertIn('"--manual-angles", nargs=3', text)
        self.assertIn("manual_window=args.manual_angles is None", text)


if __name__ == "__main__":
    unittest.main()
