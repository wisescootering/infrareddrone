import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automatic_registration import (
    _manual_redo_result_names,
    finalize_manual_redo_archives,
    prepare_manual_redo_archives,
    restore_manual_redo_originals,
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

    def test_shell_recovery_script_uses_current_interpreter(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Air Mission"
            folder.mkdir()
            script = folder / "VIS_0100_REDO.sh"
            write_manual_bat_redo(
                folder / "VIS_0100.dng",
                [(folder / "NIR_0200.dng", 1), (folder / "NIR_0201.dng", 2)],
                script,
                folder / "ImgIRdrone",
                angles=(1.0, 2.0, 3.0),
            )
            content = script.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("#!/bin/sh\n"))
            self.assertNotIn("REM", content)
            self.assertNotIn("activate", content)
            commands = [
                line for line in content.splitlines() if "automatic_registration.py" in line
            ]
            self.assertEqual(len(commands), 2)
            self.assertTrue(commands[0].startswith(f'"{sys.executable}" '))
            self.assertTrue(commands[1].startswith("# "))

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


    def test_redo_of_some_traces_only_expects_those(self):
        """A redo asked for the VIS / VIR images in local mode (the wizard, for a
        point that has no other image) is complete without the others."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            multispectral.mkdir(parents=True)
            vis = root / "VIS_0103.dng"
            (multispectral / "IRD_0103_1.exif").write_bytes(b"georef")
            debug_dir, _, archived_exif = prepare_manual_redo_archives(vis, output, multispectral)
            written = [output / "VIS_0103.jpg", output / "VIR_0103_local.jpg",
                       output / "VIS_0103_motion_model.npy", output / "VIS_0103_motion_model.json"]
            written += [multispectral / f"IRD_0103_{band}.tif" for band in range(1, 5)]
            for path in written:
                path.write_bytes(b"new")
            with self.assertRaisesRegex(FileNotFoundError, "VIR_0103_global.jpg"):
                finalize_manual_redo_archives(vis, output, multispectral, debug_dir, archived_exif)
            (debug_dir / "REDO_IN_PROGRESS.json").write_text("{}")
            finalize_manual_redo_archives(
                vis, output, multispectral, debug_dir, archived_exif,
                traces=["vis", "vir"], alignment_modes=["local"])
            self.assertFalse((debug_dir / "REDO_IN_PROGRESS.json").exists())
            for path in written:
                self.assertTrue((debug_dir / path.name).is_file())
            (output / "VIS_0103.jpg").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "VIS_0103.jpg"):
                finalize_manual_redo_archives(
                    vis, output, multispectral, debug_dir, archived_exif,
                    traces=["vis", "vir"], alignment_modes=["local"])

    def test_redo_puts_back_a_sidecar_left_in_the_archive_by_a_failed_redo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            multispectral.mkdir(parents=True)
            vis = root / "VIS_0102.dng"
            original = output / "VIS_0102_align_traces_manual" / "original"
            original.mkdir(parents=True)
            (original / "IRD_0102_1.exif").write_bytes(b"georef")

            debug_dir, _, archived_exif = prepare_manual_redo_archives(
                vis, output, multispectral
            )

            self.assertEqual((multispectral / "IRD_0102_1.exif").read_bytes(), b"georef")
            self.assertIsNotNone(archived_exif)
            for name in _manual_redo_result_names(vis):
                if name.endswith(".exif"):
                    continue
                folder = multispectral if name.startswith("IRD_") else output
                (folder / name).write_bytes(b"new")
            finalize_manual_redo_archives(
                vis, output, multispectral, debug_dir, archived_exif
            )
            self.assertEqual((multispectral / "IRD_0102_1.exif").read_bytes(), b"georef")

    def test_failed_redo_puts_back_the_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            multispectral.mkdir(parents=True)
            vis = root / "VIS_0103.dng"
            for name in _manual_redo_result_names(vis):
                folder = multispectral if name.startswith("IRD_") else output
                (folder / name).write_bytes(b"old")

            _, original_dir, _ = prepare_manual_redo_archives(vis, output, multispectral)
            # The sidecar stays in place, the regenerated outputs are moved away.
            self.assertTrue((multispectral / "IRD_0103_1.exif").is_file())
            self.assertFalse((multispectral / "IRD_0103_1.tif").exists())
            # Cut short by the failure (e.g. the process killed out of memory).
            (multispectral / "IRD_0103_1.tif").write_bytes(b"truncat")

            restored = restore_manual_redo_originals(vis, output, multispectral, original_dir)

            self.assertIn(multispectral / "IRD_0103_1.tif", restored)
            self.assertEqual((multispectral / "IRD_0103_1.tif").read_bytes(), b"old")
            for name in _manual_redo_result_names(vis):
                folder = multispectral if name.startswith("IRD_") else output
                self.assertTrue((folder / name).is_file(), name)
            self.assertEqual((multispectral / "IRD_0103_2.tif").read_bytes(), b"old")

    def test_failed_redo_removes_a_new_file_with_no_previous_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ImgIRdrone"
            multispectral = output / "imgMultispectral"
            multispectral.mkdir(parents=True)
            vis = root / "VIS_0104.dng"
            (multispectral / "IRD_0104_1.exif").write_bytes(b"georef")
            started = time.time()
            _, original_dir, _ = prepare_manual_redo_archives(vis, output, multispectral)
            (multispectral / "IRD_0104_2.tif").write_bytes(b"trunc")

            restore_manual_redo_originals(
                vis, output, multispectral, original_dir, since=started
            )

            self.assertFalse((multispectral / "IRD_0104_2.tif").exists())
            self.assertEqual((multispectral / "IRD_0104_1.exif").read_bytes(), b"georef")

    def _point_with_outputs(self, root, number):
        output = root / "ImgIRdrone"
        multispectral = output / "imgMultispectral"
        multispectral.mkdir(parents=True, exist_ok=True)
        vis = root / f"VIS_{number}.dng"
        for name in _manual_redo_result_names(vis):
            ((multispectral if name.startswith("IRD_") else output) / name).write_bytes(b"old")
        return output, multispectral, vis

    def test_a_redo_killed_mid_run_is_undone_later(self):
        import manual_redo_archives as A
        with tempfile.TemporaryDirectory() as temporary:
            output, multispectral, vis = self._point_with_outputs(Path(temporary), "0106")
            debug_dir, _, _ = prepare_manual_redo_archives(vis, output, multispectral)
            self.assertTrue((debug_dir / A.REDO_MARKER).is_file())
            # Killed (out of memory) while writing: no cleanup ran.
            (multispectral / "IRD_0106_2.tif").write_bytes(b"cut")

            recovered = A.recover_interrupted_redos(output)

            self.assertEqual(list(recovered), ["VIS_0106_align_traces_manual"])
            self.assertFalse((debug_dir / A.REDO_MARKER).exists())
            for name in _manual_redo_result_names(vis):
                folder = multispectral if name.startswith("IRD_") else output
                self.assertEqual((folder / name).read_bytes(), b"old", name)
            self.assertEqual(A.recover_interrupted_redos(output), {})

    def test_the_next_redo_first_undoes_an_interrupted_one(self):
        import manual_redo_archives as A
        with tempfile.TemporaryDirectory() as temporary:
            output, multispectral, vis = self._point_with_outputs(Path(temporary), "0107")
            prepare_manual_redo_archives(vis, output, multispectral)
            (multispectral / "IRD_0107_2.tif").write_bytes(b"cut")
            _, original_dir, _ = prepare_manual_redo_archives(vis, output, multispectral)
            # The cut-short file is not archived as the previous alignment.
            self.assertEqual(A._archived_versions(original_dir, "IRD_0107_2.tif")[-1].read_bytes(), b"old")

    def test_a_running_redo_is_left_alone(self):
        from unittest import mock
        import manual_redo_archives as A
        with tempfile.TemporaryDirectory() as temporary:
            output, multispectral, vis = self._point_with_outputs(Path(temporary), "0108")
            debug_dir, _, _ = prepare_manual_redo_archives(vis, output, multispectral)
            with mock.patch.object(A, "_redo_alive", return_value=True):
                self.assertEqual(A.recover_interrupted_redos(output), {})
            self.assertTrue((debug_dir / A.REDO_MARKER).is_file())
            self.assertFalse((output / "VIS_0108.jpg").exists())

    def test_a_complete_redo_leaves_no_marker(self):
        import manual_redo_archives as A
        with tempfile.TemporaryDirectory() as temporary:
            output, multispectral, vis = self._point_with_outputs(Path(temporary), "0109")
            debug_dir, _, archived_exif = prepare_manual_redo_archives(vis, output, multispectral)
            for name in _manual_redo_result_names(vis):
                if not name.endswith(".exif"):
                    ((multispectral if name.startswith("IRD_") else output) / name).write_bytes(b"new")
            finalize_manual_redo_archives(vis, output, multispectral, debug_dir, archived_exif)
            self.assertFalse((debug_dir / A.REDO_MARKER).exists())
            self.assertFalse((debug_dir / "Tech" / A.REDO_MARKER).exists())
            self.assertEqual(A.recover_interrupted_redos(output), {})
            self.assertEqual((output / "VIS_0109.jpg").read_bytes(), b"new")

    def test_a_redo_interrupted_before_markers_existed_gets_its_missing_outputs_back(self):
        import manual_redo_archives as A
        with tempfile.TemporaryDirectory() as temporary:
            output, multispectral, vis = self._point_with_outputs(Path(temporary), "0110")
            debug_dir, _, _ = prepare_manual_redo_archives(vis, output, multispectral)
            (debug_dir / A.REDO_MARKER).unlink()                 # as left by the older version
            (output / "VIR_0110_local.jpg").write_bytes(b"new")  # written by the redo: kept

            recovered = A.recover_interrupted_redos(output)

            self.assertEqual(list(recovered), ["VIS_0110_align_traces_manual"])
            for name in _manual_redo_result_names(vis):
                folder = multispectral if name.startswith("IRD_") else output
                self.assertTrue((folder / name).is_file(), name)
            self.assertEqual((output / "VIR_0110_local.jpg").read_bytes(), b"new")
            self.assertEqual(A.recover_interrupted_redos(output), {})

if __name__ == "__main__":
    unittest.main()
