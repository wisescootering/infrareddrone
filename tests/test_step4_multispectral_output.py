import json
import math
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

    def test_inventory_includes_only_complete_multispectral_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            multispectral = Path(temporary)
            for image_number in ("0100", "0101"):
                (multispectral / f"IRD_{image_number}_1.exif").write_text(
                    "{}", encoding="utf-8"
                )
                for band in range(1, 5):
                    if image_number == "0101" and band == 4:
                        continue
                    (multispectral / f"IRD_{image_number}_{band}.tif").write_bytes(
                        b"tif"
                    )

            pairing_data = {
                "mission_path": "C:\\Air-Mission\\mission",
                "schema_version": "1.0",
                "shoot_points": [
                    {
                        "VIS": {"FileName": f"VIS_{image_number}.DNG"},
                        "NIR": [{"rank": 1, "dt": 0.25}],
                    }
                    for image_number in ("0100", "0101")
                ],
            }

            inventory = run_after_preprocessing.build_available_shoot_points(
                pairing_data, multispectral
            )

            self.assertEqual(inventory["mission_path"], pairing_data["mission_path"])
            self.assertEqual(
                inventory["shoot_points"],
                [{"FileName": "VIS_0100.DNG", "dt": 0.25, "failed": False}],
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
                json.dumps(
                    {
                        "mission_path": str(mission),
                        "time_shift": -48.116,
                        "n_VIS": 1,
                        "n_NIR": 1,
                        "pairing_method": "nearest_time",
                        "created_at": "2026-10-29T20:44:13.203434",
                        "schema_version": "1.0",
                        "shoot_points": [shoot_point],
                    }
                ),
                encoding="utf-8",
            )
            inventory_folder = mission / "ImgIRdrone"
            inventory_folder.mkdir()
            (inventory_folder / "shoot_points.json").write_text(
                json.dumps(
                    {
                        "shoot_points": [
                            {
                                "FileName": "VIS_0100.dng",
                                "dt": 0.9,
                                "failed": True,
                                "review_note": "manually marked failed",
                            },
                            {
                                "FileName": "VIS_0999.dng",
                                "dt": 0.1,
                                "failed": True,
                            },
                        ]
                    }
                ),
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
                for band in range(2, 5):
                    (output_folder / f"IRD_0100_{band}.tif").write_bytes(b"test")
                kwargs["progress_callback"](
                    1,
                    len(sync_pairs),
                    Path(sync_pairs[0][0]).name,
                )

            def write_exif_sidecar(image_path, _vis_data):
                sidecar = image_path.with_suffix(".exif")
                sidecar.write_text("{}", encoding="utf-8")
                return sidecar

            progress_updates = []
            # Backslash continuations rather than "with (...)": that form needs Python 3.10.
            with patch("run_after_preprocessing.create_odm_folder") as create_odm_folder, \
                    patch("run_after_preprocessing.automatic_registration.process_raw_pairs",
                          side_effect=create_multispectral_output), \
                    patch("run_after_preprocessing.write_multispectral_exif",
                          side_effect=write_exif_sidecar) as write_exif:
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
            output_inventory = json.loads(
                (mission / "ImgIRdrone" / "shoot_points.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(output_inventory["mission_path"], str(mission))
            self.assertEqual(
                output_inventory["shoot_points"],
                [
                    {
                        "FileName": "VIS_0100.dng",
                        "dt": 0.1,
                        "failed": True,
                        "review_note": "manually marked failed",
                    }
                ],
            )


class MovedMissionImagesTests(unittest.TestCase):
    """shoot_points.json written before the mission folder was renamed or moved:
    the images are taken from the mission's AerialPhotography folders."""

    def test_image_path_falls_back_to_the_mission_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            (mission / "AerialPhotography" / "VIS").mkdir(parents=True)
            image = mission / "AerialPhotography" / "VIS" / "VIS_0100.dng"
            image.write_bytes(b"dng")
            gone = {"FileName": "VIS_0100.dng", "Directory": "/old/place/AerialPhotography/VIS"}
            self.assertEqual(run_after_preprocessing.image_path(gone, mission, "VIS"), image)
            here = {"FileName": "VIS_0100.dng", "Directory": str(image.parent)}
            self.assertEqual(run_after_preprocessing.image_path(here, mission, "VIS"), image)
            missing = {"FileName": "VIS_0101.dng", "Directory": "/old/place/AerialPhotography/VIS"}
            self.assertEqual(run_after_preprocessing.image_path(missing, mission, "VIS"),
                             Path("/old/place/AerialPhotography/VIS/VIS_0101.dng"))

    def test_step4_aligns_the_images_of_a_moved_mission(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            aerial = mission / "AerialPhotography"
            for band, name in (("VIS", "VIS_0100.dng"), ("NIR", "NIR_0100.RAW"), ("NIR", "NIR_0101.RAW")):
                (aerial / band).mkdir(parents=True, exist_ok=True)
                (aerial / band / name).write_bytes(b"raw")
            old = "/old/computer/FLY-20250919-1418-Somewhere/AerialPhotography"
            point = {
                "VIS": {"FileName": "VIS_0100.dng", "DateTimeOriginal": "2025-09-19T14:18:00",
                        "RelativeTimeLine": 0.0, "Directory": old + "/VIS"},
                "NIR": [
                    {"FileName": "NIR_0100.RAW", "rank": 1, "dt": 0.1,
                     "DateTimeOriginal": "2025-09-19T14:18:00", "Directory": old + "/NIR"},
                    {"FileName": "NIR_0101.RAW", "rank": 2, "dt": 0.3,
                     "DateTimeOriginal": "2025-09-19T14:18:00", "Directory": old + "/NIR"},
                ],
            }
            (aerial / "shoot_points.json").write_text(
                json.dumps({"mission_path": old, "shoot_points": [point]}), encoding="utf-8")
            seen = {}

            def process_raw_pairs(sync_pairs, **kwargs):
                seen["pairs"] = sync_pairs
                seen["redo"] = kwargs.get("redo_nir_candidates")

            with patch("run_after_preprocessing.create_odm_folder"), \
                    patch("run_after_preprocessing.automatic_registration.process_raw_pairs",
                          side_effect=process_raw_pairs):
                run_after_preprocessing.run_postprocessing(mission)

            self.assertEqual(seen["pairs"], [(aerial / "VIS" / "VIS_0100.dng",
                                              aerial / "NIR" / "NIR_0100.RAW")])
            self.assertEqual(seen["redo"], [[(aerial / "NIR" / "NIR_0100.RAW", 1),
                                             (aerial / "NIR" / "NIR_0101.RAW", 2)]])


class TheoreticalAnglesTests(unittest.TestCase):
    @staticmethod
    def _points(east=0.0, north=0.0):
        vis = {
            "UTM_x": 1000.0,
            "UTM_y": 2000.0,
            "FlightYawDegree": "+0.00",
            "GroundAltitude": 100.0,
            "DroneAltitudeSeaLevel": 146.0,
            "GimbalRollDegree": "+0.00",
            "GimbalPitchDegree": -90.0,
        }
        nir = {
            "Interpolated": {
                "UTM_x": 1000.0 + east,
                "UTM_y": 2000.0 + north,
                "FlightYawDegree": 358.0,
                "FlightPitchDegree": 1.0,
                "FlightRollDegree": -2.0,
            }
        }
        return vis, nir

    def test_static_drone_nadir_gimbal(self):
        yaw, pitch, roll = run_after_preprocessing.compute_theoretical_ir2vi_angles(
            *self._points()
        )
        lens_offset = math.degrees(math.atan(run_after_preprocessing.CNIRCVIS_0 / 46.0))
        self.assertAlmostEqual(yaw, 2.0, places=6)
        self.assertAlmostEqual(pitch, lens_offset - 1.0, places=6)
        self.assertAlmostEqual(roll, 2.0, places=6)

    def test_forward_motion_between_shots_lowers_pitch(self):
        _, static_pitch, _ = run_after_preprocessing.compute_theoretical_ir2vi_angles(
            *self._points()
        )
        _, moving_pitch, _ = run_after_preprocessing.compute_theoretical_ir2vi_angles(
            *self._points(north=4.6)
        )
        self.assertAlmostEqual(
            moving_pitch - static_pitch,
            math.degrees(math.atan(-4.6 / 46.0 + run_after_preprocessing.CNIRCVIS_0 / 46.0))
            - math.degrees(math.atan(run_after_preprocessing.CNIRCVIS_0 / 46.0)),
            places=6,
        )
        self.assertLess(moving_pitch, static_pitch)

    def test_missing_interpolation_returns_none(self):
        vis, _ = self._points()
        self.assertIsNone(
            run_after_preprocessing.compute_theoretical_ir2vi_angles(vis, {})
        )


if __name__ == "__main__":
    unittest.main()
