import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automatic_registration import (
    _manual_redo_result_names,
    finalize_manual_redo_archives,
    prepare_manual_redo_archives,
    write_manual_bat_redo,
)


class ManualRedoBatchTests(unittest.TestCase):
    def test_single_recovery_batch_enables_full_debug_and_all_traces(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            vis = folder / "VIS_0100.dng"
            nir_rank_1 = folder / "NIR_0200.dng"
            nir_rank_2 = folder / "NIR_0201.dng"
            batch = folder / "VIS_0100_REDO.bat"
            output = folder / "ImgIRdrone"
            multispectral = folder / "imgMultispectral"

            write_manual_bat_redo(
                vis,
                [(nir_rank_1, 1), (nir_rank_2, 2)],
                batch,
                output,
                multispectral_folder=multispectral,
                angles=(1.0, 2.0, 3.0),
            )

            content = batch.read_text(encoding="utf-8")
            commands = [
                line for line in content.splitlines() if "automatic_registration.py" in line
            ]
            self.assertEqual(len(commands), 2)
            self.assertFalse(commands[0].startswith("REM "))
            self.assertTrue(commands[1].startswith("REM "))
            for command in commands:
                self.assertIn("--debug", command)
                self.assertIn("--redo", command)
                self.assertIn("--traces vis nir vir ndvi", command)
                self.assertIn("--alignment-modes local global", command)
                self.assertIn(str(multispectral), command)
            self.assertIn(str(nir_rank_1), commands[0])
            self.assertIn(str(nir_rank_2), commands[1])
            self.assertIn("NIR rank 2", content)

    def test_redo_archives_previous_outputs_and_new_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            output.mkdir()
            multispectral.mkdir()
            vis = root / "VIS_0100.dng"
            debug_dir = output / "VIS_0100_align_traces_manual"
            debug_dir.mkdir()

            old_outputs = {
                output / "VIS_0100.jpg",
                output / "VIR_0100_local.jpg",
                output / "VIS_0100_motion_model.npy",
                multispectral / "IRD_0100_1.exif",
                *(multispectral / f"IRD_0100_{band}.tif" for band in range(1, 5)),
            }
            for path in old_outputs:
                path.write_bytes(b"old")
            (debug_dir / "old_cost.png").write_bytes(b"old diagnostic")
            (debug_dir / "motion_model.npy").write_bytes(b"stale model")

            prepared_debug, original_dir, archived_exif = (
                prepare_manual_redo_archives(vis, output, multispectral)
            )

            self.assertEqual(prepared_debug, debug_dir)
            self.assertTrue((original_dir / "VIS_0100.jpg").is_file())
            self.assertTrue((original_dir / "VIR_0100_local.jpg").is_file())
            self.assertTrue((original_dir / "VIS_0100_motion_model.npy").is_file())
            self.assertTrue((original_dir / "IRD_0100_4.tif").is_file())
            self.assertTrue((debug_dir / "Tech" / "old_cost.png").is_file())
            self.assertTrue((debug_dir / "Tech" / "motion_model.npy").is_file())
            self.assertEqual(archived_exif.name, "IRD_0100_1.exif")

            new_outputs = []
            for name in _manual_redo_result_names(vis):
                path = (
                    multispectral if name.startswith("IRD_") else output
                ) / name
                if name != "IRD_0100_1.exif":
                    path.write_bytes(b"new")
                new_outputs.append(path)
            (debug_dir / "motion_model.npy").write_bytes(b"new model")
            (debug_dir / "new_cost.png").write_bytes(b"new diagnostic")

            finalize_manual_redo_archives(
                vis, output, multispectral, debug_dir, archived_exif
            )

            for path in new_outputs:
                self.assertTrue(path.is_file())
                self.assertEqual(
                    (debug_dir / path.name).read_bytes(),
                    b"old" if path.name.endswith(".exif") else b"new",
                )
            self.assertTrue((multispectral / "IRD_0100_1.exif").is_file())
            self.assertEqual(
                (debug_dir / "IRD_0100_1.exif").read_bytes(),
                b"old",
            )
            self.assertTrue((debug_dir / "Tech" / "new_cost.png").is_file())

    def test_redo_archives_diagnostics_when_added_image_has_no_exif_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            output.mkdir()
            multispectral.mkdir()
            vis = root / "VIS_0101.dng"
            debug_dir = output / "VIS_0101_align_traces_manual"
            debug_dir.mkdir()

            prepared_debug, _, archived_exif = prepare_manual_redo_archives(
                vis, output, multispectral
            )
            self.assertEqual(prepared_debug, debug_dir)
            self.assertIsNone(archived_exif)

            result_names = _manual_redo_result_names(vis)
            result_names.remove("IRD_0101_1.exif")
            for name in result_names:
                folder = multispectral if name.startswith("IRD_") else output
                (folder / name).write_bytes(b"new")
            (debug_dir / "alignment_diagnostic.png").write_bytes(b"diagnostic")

            with self.assertRaisesRegex(
                FileNotFoundError, "IRD_0101_1.exif"
            ):
                finalize_manual_redo_archives(
                    vis, output, multispectral, debug_dir, archived_exif
                )
            self.assertFalse((multispectral / "IRD_0101_1.exif").exists())
            self.assertTrue((debug_dir / "VIS_0101.jpg").is_file())
            self.assertTrue(
                (debug_dir / "Tech" / "alignment_diagnostic.png").is_file()
            )


if __name__ == "__main__":
    unittest.main()
