import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automatic_registration import write_manual_bat_redo


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
                self.assertIn("--traces vis nir vir ndvi", command)
                self.assertIn("--alignment-modes local global", command)
                self.assertIn(str(multispectral), command)
            self.assertIn(str(nir_rank_1), commands[0])
            self.assertIn(str(nir_rank_2), commands[1])
            self.assertIn("NIR rank 2", content)


if __name__ == "__main__":
    unittest.main()
