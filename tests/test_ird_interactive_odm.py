import json
import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "irdrone Interactive"))
from IRD_Interactive_ODM import (
    ODM_PROJECT_NAME,
    ODM_RESULTS_FOLDER,
    ODMMappingError,
    DockerUnavailableError,
    build_best_mapping,
    build_odm_command,
    check_docker,
    format_elapsed_duration,
    _check_mapping_outputs_available,
    _cleanup_odm_working_directories,
    _copy_mapping_results,
    prepare_odm_input,
    read_orthophoto_preview,
    _validate_odm_outputs,
)


class BestMappingTests(unittest.TestCase):
    def test_formats_elapsed_duration(self):
        self.assertEqual(format_elapsed_duration(42.2), "42 s")
        self.assertEqual(format_elapsed_duration(125), "2 min 05 s")
        self.assertEqual(format_elapsed_duration(3723), "1 h 02 min 03 s")

    @patch("IRD_Interactive_ODM.subprocess.run")
    @patch("IRD_Interactive_ODM.shutil.which", return_value="docker")
    def test_check_docker_returns_server_version(self, _which, run):
        run.return_value = subprocess.CompletedProcess(
            args=["docker"], returncode=0, stdout="29.9.2\n", stderr=""
        )

        executable, version = check_docker()

        self.assertEqual(executable, "docker")
        self.assertEqual(version, "29.9.2")
        self.assertEqual(run.call_args.args[0][1:3], ["--context", "desktop-linux"])

    @patch("IRD_Interactive_ODM.shutil.which", return_value=None)
    def test_check_docker_reports_missing_cli(self, _which):
        with self.assertRaisesRegex(DockerUnavailableError, "Docker CLI was not found"):
            check_docker()

    @patch("IRD_Interactive_ODM.subprocess.run")
    @patch("IRD_Interactive_ODM.shutil.which", return_value="docker")
    def test_check_docker_reports_unavailable_engine(self, _which, run):
        run.return_value = subprocess.CompletedProcess(
            args=["docker"], returncode=1, stdout="",
            stderr="The system cannot find the file specified.",
        )

        with self.assertRaisesRegex(DockerUnavailableError, "is not responding"):
            check_docker()

    def _create_mission(self, root):
        aerial = root / "AerialPhotography"
        vis_folder = aerial / "VIS"
        mapping = root / "mapping_MULTI"
        images = root / "ImgIRdrone" / "imgMultispectral"
        camera_folder = mapping / "camera"
        for folder in (vis_folder, images, camera_folder):
            folder.mkdir(parents=True, exist_ok=True)

        shoot_points = []
        for index, dt, rank in (
            (120, 0.5, 1),
            (121, -0.2, 1),
            (122, 0.1, 2),
            (123, 0.5001, 1),
            (124, -0.5, 1),
            (125, 0.2, 1),
            (126, 0.4, 1),
            (127, -0.49, 1),
            (128, 0.1, 1),
        ):
            shoot_points.append(
                {
                    "VIS": {"FileName": f"VIS_{index:04d}.DNG", "idx": index - 1},
                    "NIR": [{"FileName": f"NIR_{index:04d}.dng", "rank": rank, "dt": dt}],
                }
            )
            for band in range(1, 5):
                with rasterio.open(
                    images / f"IRD_{index:04d}_{band}.tif",
                    "w",
                    driver="GTiff",
                    width=8,
                    height=6,
                    count=1,
                    dtype="uint16",
                    transform=Affine(0.5, 0, 100, 0, -0.5, 200),
                ) as dataset:
                    dataset.write(np.full((6, 8), band, dtype=np.uint16), 1)
            (images / f"IRD_{index:04d}_1.exif").write_text(
                json.dumps(
                    {
                        "ImageWidth": 8,
                        "ImageHeight": 6,
                        "DroneAltitudeGround": 1.0 + (index - 120) / 100,
                    }
                ),
                encoding="utf-8",
            )

        (aerial / "shoot_points.json").write_text(
            json.dumps({"shoot_points": shoot_points}), encoding="utf-8"
        )
        (vis_folder / "transfer_info_VIS_dng.json").write_text(
            json.dumps(
                {
                    "spectral_band": "VIS",
                    "fly": {
                        "listCopiedImages": [
                            "VIS_0120.dng",
                            "VIS_0121.dng",
                            "VIS_0122.dng",
                            "VIS_0123.dng",
                            "VIS_0124.dng",
                            "VIS_0125.dng",
                            "VIS_0126.dng",
                            "VIS_0127.dng",
                            "VIS_0128.dng",
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        (camera_folder / "camera_IRdrone.json").write_text(
            json.dumps(
                {"test camera": {"width": 8, "height": 6, "focal_x": 0.5}}
            ),
            encoding="utf-8",
        )

    def test_filters_pairs_then_samples_every_third_and_builds_quartets(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)

            manifest = build_best_mapping(mission)

            self.assertEqual(manifest["counts"]["rank_one_pairs"], 8)
            self.assertEqual(manifest["counts"]["rank_one_pairs_within_dt_tolerance"], 7)
            self.assertEqual(manifest["counts"]["fly_pairs_within_dt_tolerance"], 7)
            self.assertEqual(manifest["counts"]["sampled_shoot_points"], 3)
            self.assertEqual(manifest["counts"]["ready_for_odm"], 3)
            resolution = manifest["orthophoto_resolution_estimate"]
            self.assertAlmostEqual(resolution["median_ground_sample_distance_cm"], 26.25)
            self.assertEqual(
                resolution["recommended_orthophoto_resolution_cm_per_pixel"], 26.3
            )
            self.assertEqual(resolution["estimated_capture_count"], 3)
            self.assertEqual(resolution["errors"], [])
            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0125.DNG", "VIS_0128.DNG"],
            )
            self.assertEqual(
                list(manifest["image_quartets"][0]["files"]),
                ["red", "green", "blue", "nir"],
            )
            self.assertFalse(manifest["odm_started"])
            self.assertTrue((mission / "mapping_MULTI" / "img_best_mappping.json").is_file())

    def test_missing_band_is_reported_and_not_added_as_a_ready_quartet(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            missing_band = (
                mission
                / "ImgIRdrone"
                / "imgMultispectral"
                / "IRD_0120_4.tif"
            )
            missing_band.unlink()

            manifest = build_best_mapping(mission)

            self.assertEqual(manifest["counts"]["not_ready"], 1)
            self.assertEqual(manifest["counts"]["ready_for_odm"], 2)
            self.assertEqual(len(manifest["image_quartets"]), 2)
            self.assertFalse(manifest["shoot_points"][0]["ready_for_odm"])
            self.assertTrue(manifest["shoot_points"][0]["validation_errors"])

    def test_required_mission_metadata_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ODMMappingError):
                build_best_mapping(Path(temporary))

    def test_prepares_odm_project_with_hard_links_to_only_selected_quartets(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)

            images_folder = prepare_odm_input(mission, manifest)

            self.assertEqual(
                images_folder,
                mission / "mapping_MULTI" / "images",
            )
            linked_images = sorted(path.name for path in images_folder.iterdir())
            self.assertEqual(len(linked_images), 15)
            self.assertEqual(
                [name for name in linked_images if name.endswith(".tif")],
                sorted(
                    f"IRD_{index:04d}_{band}.tif"
                    for index in (120, 125, 128)
                    for band in range(1, 5)
                ),
            )
            self.assertEqual(
                [name for name in linked_images if name.endswith(".exif")],
                [
                    "IRD_0120_1.exif",
                    "IRD_0125_1.exif",
                    "IRD_0128_1.exif",
                ],
            )
            for name in linked_images:
                self.assertTrue(
                    os.path.samefile(
                        images_folder / name,
                        mission / "ImgIRdrone" / "imgMultispectral" / name,
                    )
                )
            self.assertTrue(
                (mission / "mapping_MULTI" / "camera" / "camera_IRdrone.json").is_file()
            )
            self.assertFalse((mission / "mapping_MULTI" / ODM_PROJECT_NAME).exists())

    def test_refuses_to_use_existing_non_link_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir()
            marker = images_folder / "keep.txt"
            marker.write_text("existing data", encoding="utf-8")

            with self.assertRaisesRegex(ODMMappingError, "does not exactly match"):
                prepare_odm_input(mission, manifest)

            self.assertEqual(marker.read_text(encoding="utf-8"), "existing data")

    def test_reuses_existing_hard_link_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir(parents=True)

            for quartet in manifest["image_quartets"]:
                for source in quartet["files"].values():
                    source_path = Path(source)
                    os.link(source_path, images_folder / source_path.name)
                    sidecar = source_path.with_suffix(".exif")
                    if sidecar.is_file():
                        os.link(sidecar, images_folder / sidecar.name)

            self.assertEqual(
                prepare_odm_input(mission, manifest),
                images_folder,
            )

    def test_populates_existing_empty_images_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir()

            self.assertEqual(
                prepare_odm_input(mission, manifest),
                images_folder,
            )
            self.assertEqual(len(list(images_folder.iterdir())), 15)

    def test_rejects_copied_tiffs_instead_of_hard_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir(parents=True)

            for quartet in manifest["image_quartets"]:
                for source in quartet["files"].values():
                    source_path = Path(source)
                    (images_folder / source_path.name).write_bytes(
                        source_path.read_bytes()
                    )
                    sidecar = source_path.with_suffix(".exif")
                    if sidecar.is_file():
                        (images_folder / sidecar.name).write_bytes(
                            sidecar.read_bytes()
                        )

            with self.assertRaisesRegex(ODMMappingError, "copies rather than hard links"):
                prepare_odm_input(mission, manifest)

    def test_refuses_to_overwrite_existing_odm_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            mapping_folder = mission / "mapping_MULTI"
            (mapping_folder / "odm_orthophoto").mkdir()
            previous_result = mapping_folder / "odm_orthophoto" / "keep.tif"
            previous_result.write_text("previous output", encoding="utf-8")

            with self.assertRaisesRegex(ODMMappingError, "will not be overwritten"):
                _check_mapping_outputs_available(mapping_folder)

            self.assertEqual(
                previous_result.read_text(encoding="utf-8"),
                "previous output",
            )

    def test_copies_selected_results_to_mapping_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            mapping = Path(temporary) / "mapping_MULTI"
            sources = (
                mapping / "odm_orthophoto" / "odm_orthophoto.tif",
                mapping / "odm_report" / "report.pdf",
                mapping / "odm_report" / "shots.geojson",
                mapping / "odm_meshing" / "odm_25dmesh.ply",
                mapping / "opensfm" / "stats" / "ortho.png",
                mapping
                / "odm_georeferencing"
                / "odm_georeferenced_model.info.json",
            )
            for source in sources:
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(source.name, encoding="utf-8")
            ortho_metadata = sources[4].with_name("ortho.png.aux.xml")
            ortho_metadata.write_text("georeferencing sidecar", encoding="utf-8")

            copied = _copy_mapping_results(mapping)
            result_folder = mapping / ODM_RESULTS_FOLDER

            self.assertEqual(
                {path.name for path in result_folder.iterdir()},
                {
                    "odm_orthophoto.tif",
                    "report.pdf",
                    "shots.geojson",
                    "odm_25dmesh.ply",
                    "ortho.png",
                    "odm_georeferenced_model.info.json",
                    "ortho.png.aux.xml",
                },
            )
            self.assertEqual(len(copied), 7)
            for source in sources:
                self.assertEqual(
                    (result_folder / source.name).read_text(encoding="utf-8"),
                    source.read_text(encoding="utf-8"),
                )
            self.assertEqual(
                (result_folder / ortho_metadata.name).read_text(encoding="utf-8"),
                ortho_metadata.read_text(encoding="utf-8"),
            )

    def test_cleans_only_configured_odm_working_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            mapping = Path(temporary) / "mapping_MULTI"
            for directory_name in (
                "images",
                "odm_dem",
                "odm_filterpoints",
                "odm_georeferencing",
                "odm_meshing",
                "odm_orthophoto",
                "odm_report",
                "odm_texturing_25d",
                "opensfm",
                "camera",
            ):
                directory = mapping / directory_name
                directory.mkdir(parents=True)
                (directory / "sample").write_text("data", encoding="utf-8")
            (mapping / "images.json").write_text("{}", encoding="utf-8")
            (mapping / ODM_RESULTS_FOLDER).mkdir()

            removed = _cleanup_odm_working_directories(mapping)

            self.assertEqual(
                set(removed),
                {
                    "images",
                    "odm_dem",
                    "odm_filterpoints",
                    "odm_georeferencing",
                    "odm_meshing",
                    "odm_orthophoto",
                    "odm_report",
                    "odm_texturing_25d",
                    "opensfm",
                },
            )
            self.assertTrue((mapping / "camera").is_dir())
            self.assertTrue((mapping / "images.json").is_file())
            self.assertTrue((mapping / ODM_RESULTS_FOLDER).is_dir())

    def test_builds_docker_command_with_estimated_resolution(self):
        command = build_odm_command(Path("C:/mission/mapping_MULTI"), 3.3)

        self.assertEqual(command[0:4], ["docker", "--context", "desktop-linux", "run"])
        self.assertIn("C:\\mission:/datasets", command)
        self.assertIn("mapping_MULTI", command)
        self.assertEqual(
            command[command.index("--cameras") + 1],
            "/datasets/mapping_MULTI/camera/camera_IRdrone.json",
        )
        self.assertIn("--orthophoto-resolution", command)
        self.assertEqual(command[command.index("--orthophoto-resolution") + 1], "3.3")
        self.assertIn("--skip-band-alignment", command)
        self.assertIn("--max-concurrency", command)
        self.assertNotIn("--ignore-gsd", command)
        self.assertNotIn("--orthophoto-png", command)

    def test_validates_multispectral_odm_geotiff(self):
        with tempfile.TemporaryDirectory() as temporary:
            orthophoto = Path(temporary) / "odm_orthophoto.tif"
            with rasterio.open(
                orthophoto,
                "w",
                driver="GTiff",
                width=3,
                height=2,
                count=5,
                dtype="uint8",
                crs="EPSG:32631",
                transform=Affine(0.033, 0, 100, 0, -0.033, 200),
            ) as dataset:
                for index, name in enumerate(("Red", "Green", "Blue", "NIR"), 1):
                    dataset.write(np.full((2, 3), index, dtype=np.uint8), index)
                    dataset.set_band_description(index, name)
                dataset.write(np.full((2, 3), 5, dtype=np.uint8), 5)

            result = _validate_odm_outputs(orthophoto)

            self.assertEqual(result["band_count"], 5)
            self.assertEqual(result["crs"], "EPSG:32631")
            self.assertEqual(result["band_descriptions"][:4], ["Red", "Green", "Blue", "NIR"])
            self.assertEqual(
                result["band_labels"],
                ["Red", "Green", "Blue", "NIR", "Band 5"],
            )

    def test_reads_reduced_rgb_orthophoto_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            orthophoto = Path(temporary) / "orthophoto.tif"
            with rasterio.open(
                orthophoto,
                "w",
                driver="GTiff",
                width=240,
                height=120,
                count=4,
                dtype="uint16",
                crs="EPSG:32631",
                transform=Affine(0.033, 0, 100, 0, -0.033, 200),
            ) as dataset:
                horizontal_gradient = np.tile(
                    np.arange(240, dtype=np.uint16),
                    (120, 1),
                )
                for band, multiplier in enumerate((1, 2, 3, 4), 1):
                    dataset.write(
                        horizontal_gradient * multiplier,
                        band,
                    )

            preview = read_orthophoto_preview(orthophoto, max_dimension=80)

            self.assertEqual(preview.shape, (40, 80, 3))
            self.assertEqual(preview.dtype, np.uint8)
            self.assertGreater(int(preview.max()), 0)

    def test_missing_exif_sidecar_blocks_odm_input_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            (
                mission
                / "ImgIRdrone"
                / "imgMultispectral"
                / "IRD_0120_1.exif"
            ).unlink()

            manifest = build_best_mapping(mission)

            self.assertIsNone(
                manifest["orthophoto_resolution_estimate"][
                    "recommended_orthophoto_resolution_cm_per_pixel"
                ]
            )
            with self.assertRaisesRegex(ODMMappingError, "EXIF sidecars"):
                prepare_odm_input(mission, manifest)
            self.assertFalse((mission / "mapping_MULTI" / "images").exists())


if __name__ == "__main__":
    unittest.main()
