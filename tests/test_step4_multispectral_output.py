import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_after_preprocessing


class Step4MultispectralOutputTests(unittest.TestCase):
    def test_nir_trace_is_optional_and_disabled_by_default(self):
        self.assertEqual(
            run_after_preprocessing.build_output_traces(),
            ["vis", "vir"],
        )
        self.assertEqual(
            run_after_preprocessing.build_output_traces(include_nir=True),
            ["vis", "vir", "nir"],
        )
        self.assertEqual(
            run_after_preprocessing.build_output_traces(
                include_nir=True,
                include_ndvi=True,
            ),
            ["vis", "vir", "nir", "ndvi"],
        )

    def test_multispectral_tiffs_and_sidecars_use_imgirdrone_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            aerial = mission / "AerialPhotography"
            aerial.mkdir()
            shoot_point = {
                "VIS": {
                    "FileName": "VIS_0100.dng",
                    "idx": 99,
                    "DateTimeOriginal": "2025-09-19T14:18:00",
                    "RelativeTimeLine": 0.0,
                    "Directory": str(aerial),
                },
                "NIR": [
                    {
                        "FileName": "NIR_0100.dng",
                        "rank": 1,
                        "dt": 0.1,
                        "DateTimeOriginal": "2025-09-19T14:18:00",
                        "Directory": str(aerial),
                    }
                ],
            }
            (aerial / "shoot_points.json").write_text(
                json.dumps({"shoot_points": [shoot_point]}),
                encoding="utf-8",
            )

            def create_multispectral_output(sync_pairs, **kwargs):
                self.assertEqual(kwargs["traces"], ["vis", "vir"])
                output_folder = kwargs["multispectral_folder"]
                self.assertEqual(
                    output_folder,
                    mission / "ImgIRdrone" / "imgMultispectral",
                )
                self.assertTrue(output_folder.is_dir())
                (output_folder / "IRD_0100_1.tif").write_bytes(b"test")
                kwargs["progress_callback"](
                    1,
                    len(sync_pairs),
                    Path(sync_pairs[0][0]).name,
                )

            progress_updates = []
            with (
                patch("run_after_preprocessing.create_odm_folder") as create_odm_folder,
                patch(
                    "run_after_preprocessing.automatic_registration.process_raw_pairs",
                    side_effect=create_multispectral_output,
                ),
                patch(
                    "run_after_preprocessing.write_multispectral_exif"
                ) as write_exif,
            ):
                run_after_preprocessing.run_postprocessing(
                    mission,
                    progress_callback=lambda current, total, filename: (
                        progress_updates.append((current, total, filename))
                    ),
                )

            create_odm_folder.assert_called_once_with(
                mission,
                multispectral_modality="MULTI",
                extra_options=["--skip-band-alignment"],
                create_images_directory=False,
            )
            write_exif.assert_called_once_with(
                mission / "ImgIRdrone" / "imgMultispectral" / "IRD_0100_1.tif",
                shoot_point["VIS"],
            )
            self.assertEqual(
                progress_updates,
                [(0, 1, ""), (1, 1, "VIS_0100.dng")],
            )
            self.assertFalse((mission / "mapping_MULTI" / "images").exists())


if __name__ == "__main__":
    unittest.main()
