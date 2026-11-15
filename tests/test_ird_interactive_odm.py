import errno
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.enums import Resampling
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "irdrone_wizard"))
from IRD_Interactive_diskspace import DiskFullError  # noqa: E402
from IRD_Interactive_ODM import (
    _restore_output_ownership,
    resolve_docker_context,
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
    build_orthophoto_overviews,
)


_original_tempdir = tempfile.tempdir


def setUpModule():
    # The mapping code resolves paths; on Windows the default temp folder is an 8.3 short
    # path (C:\Users\RUNNER~1\...), so expected paths must start from the resolved one.
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())


def tearDownModule():
    tempfile.tempdir = _original_tempdir


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

    @patch("IRD_Interactive_ODM.subprocess.run")
    @patch("IRD_Interactive_ODM.shutil.which", return_value="docker")
    def test_check_docker_falls_back_to_current_context(self, _which, run):
        # `docker context inspect desktop-linux` fails (plain Docker Engine), info succeeds.
        run.side_effect = [
            subprocess.CompletedProcess(args=["docker"], returncode=1, stdout="", stderr="not found"),
            subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="29.9.3\n", stderr=""),
        ]

        executable, version = check_docker()

        self.assertEqual(version, "29.9.3")
        self.assertEqual(run.call_args.args[0], ["docker", "info", "--format", "{{.ServerVersion}}"])

    @patch.dict(os.environ, {"IRDRONE_DOCKER_CONTEXT": "my-context"})
    @patch("IRD_Interactive_ODM.subprocess.run")
    def test_docker_context_from_environment(self, run):
        self.assertEqual(resolve_docker_context(), "my-context")
        run.assert_not_called()

    def test_builds_docker_command_without_context(self):
        command = build_odm_command(Path("/mission/mapping_MULTI"), 3.3, docker_context=None)

        self.assertEqual(command[0:2], ["docker", "run"])

    @patch.dict(os.environ, {}, clear=False)
    @patch("IRD_Interactive_ODM.subprocess.run")
    @patch("IRD_Interactive_ODM.shutil.which", return_value="docker")
    def test_docker_desktop_context_is_kept_when_it_exists(self, _which, run):
        # Windows / Docker Desktop: the desktop-linux context exists, so every
        # Docker call keeps using it exactly as before.
        os.environ.pop("IRDRONE_DOCKER_CONTEXT", None)
        run.return_value = subprocess.CompletedProcess(
            args=["docker"], returncode=0, stdout="29.9.2\n", stderr=""
        )

        context = resolve_docker_context("docker")
        check_docker(context)
        command = build_odm_command(Path("/mission/mapping_MULTI"), 3.3, "docker", context)

        self.assertEqual(context, "desktop-linux")
        self.assertEqual(run.call_args_list[0].args[0], ["docker", "context", "inspect", "desktop-linux"])
        self.assertEqual(run.call_args.args[0][:4], ["docker", "--context", "desktop-linux", "info"])
        self.assertEqual(command[0:4], ["docker", "--context", "desktop-linux", "run"])

    @patch("IRD_Interactive_ODM.subprocess.run")
    def test_restore_ownership_does_nothing_on_windows(self, run):
        # Windows has no os.getuid: the ownership step must not call Docker.
        with tempfile.TemporaryDirectory() as tmp, \
                patch("IRD_Interactive_ODM.os", types.SimpleNamespace(environ=os.environ)):
            _restore_output_ownership(Path(tmp), "docker", "desktop-linux", print)
        run.assert_not_called()

    @patch("IRD_Interactive_ODM.subprocess.run")
    def test_restore_ownership_does_nothing_when_files_are_ours(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "odm_dem").mkdir()
            (Path(tmp) / "odm_dem" / "dem.tif").write_bytes(b"")
            _restore_output_ownership(Path(tmp), "docker", None, print)
        run.assert_not_called()

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

    def test_visible_only_mission_maps_three_bands(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            for band4 in (mission / "ImgIRdrone" / "imgMultispectral").glob("IRD_*_4.tif"):
                band4.unlink()
            (mission / "FlightAnalytics").mkdir()
            (mission / "FlightAnalytics" / "mission_parameters.json").write_text(
                json.dumps({"mission type": "visible"}), encoding="utf-8")
            manifest = build_best_mapping(mission)
            self.assertEqual(manifest["counts"]["not_ready"], 0)
            self.assertEqual(manifest["selection_rules"]["band_order"], ["red", "green", "blue"])
            self.assertEqual(list(manifest["image_quartets"][0]["files"]), ["red", "green", "blue"])
            images = prepare_odm_input(mission, manifest)
            self.assertEqual(len([p for p in images.iterdir() if p.suffix == ".tif"]),
                             3 * manifest["counts"]["ready_for_odm"])

    def test_mapping_uses_selected_time_tolerance_and_image_interval(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)

            manifest = build_best_mapping(
                mission,
                dt_tolerance_s=0.25,
                sample_every=2,
            )

            self.assertEqual(
                manifest["selection_rules"]["maximum_absolute_dt_seconds"],
                0.25,
            )
            self.assertEqual(
                manifest["selection_rules"]["sample_every_nth_eligible_pair"],
                2,
            )
            self.assertEqual(
                [
                    point["VIS"]["FileName"]
                    for point in manifest["shoot_points"]
                ],
                ["VIS_0121.DNG", "VIS_0128.DNG"],
            )

    def _add_positions(self, mission, step_m=5.0):
        """VIS positions of the Step 3 pairs: flying north at 100 m, step_m metres per image."""
        path = mission / "AerialPhotography" / "shoot_points.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for point in data["shoot_points"]:
            index = int(point["VIS"]["FileName"][4:8]) - 120
            point["VIS"].update({"DroneLatitude": 45.0 + index * step_m / 111195.0, "DroneLongitude": 3.0,
                                 "DroneAltitudeGround": 100.0, "GimbalYawDegree": 0.0})
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_mapping_selection_by_overlap_keeps_the_images_the_map_needs(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            self._add_positions(mission, step_m=10.0)

            manifest = build_best_mapping(mission, overlap=0.75)

            self.assertEqual(manifest["selection_rules"]["selection"], "overlap")
            self.assertEqual(manifest["selection_rules"]["footprint_overlap"], 0.75)
            self.assertIsNone(manifest["selection_rules"]["sample_every_nth_eligible_pair"])
            # eligible: 120 121 124 125 126 127 128 (100 m high: 25 m between images at 75 %)
            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0121.DNG", "VIS_0124.DNG", "VIS_0126.DNG", "VIS_0128.DNG"],
            )
            self.assertEqual(manifest["counts"]["ready_for_odm"], 5)

    def test_mapping_selection_by_overlap_reads_positions_with_step4_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            self._add_positions(mission, step_m=10.0)
            inventory = {"shoot_points": [
                {"FileName": f"VIS_{index:04d}.DNG", "dt": 0.1, "failed": index == 124}
                for index in (120, 121, 124, 125, 126, 127, 128)
            ]}
            (mission / "ImgIRdrone" / "shoot_points.json").write_text(json.dumps(inventory), encoding="utf-8")

            manifest = build_best_mapping(mission, overlap=0.75)

            # VIS_0124 is flagged failed in the review: never kept, the next ones fill the gap
            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0121.DNG", "VIS_0125.DNG", "VIS_0127.DNG", "VIS_0128.DNG"],
            )

    def test_mapping_selection_by_overlap_without_positions_keeps_every_eligible_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)

            manifest = build_best_mapping(mission, overlap=0.75)

            self.assertEqual(manifest["counts"]["sampled_shoot_points"], 7)

    def test_mapping_selection_rejects_out_of_range_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            for overlap in (0.2, 0.99, 75, True):
                with self.subTest(overlap=overlap):
                    with self.assertRaises(ODMMappingError):
                        build_best_mapping(mission, overlap=overlap)

    def test_mapping_selection_rejects_out_of_range_criteria(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)

            for tolerance in (0.04, 6.01, True):
                with self.subTest(dt_tolerance_s=tolerance):
                    with self.assertRaises(ODMMappingError):
                        build_best_mapping(mission, dt_tolerance_s=tolerance)
            for interval in (0, 5, 1.0, True):
                with self.subTest(sample_every=interval):
                    with self.assertRaises(ODMMappingError):
                        build_best_mapping(mission, sample_every=interval)

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

    def test_step_four_inventory_excludes_shoot_points_marked_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            inventory_path = mission / "ImgIRdrone" / "shoot_points.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "mission_path": str(mission),
                        "shoot_points": [
                            {
                                "FileName": f"VIS_{index:04d}.DNG",
                                "dt": dt,
                                "failed": 1 if index == 120 else 0,
                            }
                            for index, dt in (
                                (120, 0.5),
                                (121, -0.2),
                                (122, 0.1),
                                (123, 0.5001),
                                (124, -0.5),
                                (125, 0.2),
                                (126, 0.4),
                                (127, -0.49),
                                (128, 0.1),
                            )
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_best_mapping(mission)

            self.assertEqual(
                manifest["source_files"]["shoot_points"],
                str(inventory_path),
            )
            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0121.DNG", "VIS_0125.DNG", "VIS_0128.DNG"],
            )

    def test_images_outside_the_survey_of_step2_are_mapped_too(self):
        """No survey-phase filter: the aligned images of the whole flight are
        eligible (and the Step 2 list is not needed any more)."""
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            (mission / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").unlink()

            manifest = build_best_mapping(mission, sample_every=1)

            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0121.DNG", "VIS_0124.DNG", "VIS_0125.DNG",
                 "VIS_0126.DNG", "VIS_0127.DNG", "VIS_0128.DNG"],
            )

    def test_points_aligned_from_the_review_are_always_mapped(self):
        """Aligned on request in the review: kept whatever the time tolerance
        and the thinning, unless flagged; the other images selected as before."""
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            inventory_path = mission / "ImgIRdrone" / "shoot_points.json"
            points = []
            for index, dt in ((120, 0.5), (121, -0.2), (122, 0.1), (123, 0.5001), (124, -0.5),
                              (125, 0.2), (126, 0.4), (127, -0.49), (128, 0.1)):
                point = {"FileName": f"VIS_{index:04d}.DNG", "dt": dt, "failed": index == 124}
                if index in (122, 123, 124):          # 123: beyond 0.5 s; 124: flagged since
                    point["aligned_on_request"] = True
                points.append(point)
            inventory_path.write_text(json.dumps({"shoot_points": points}), encoding="utf-8")

            manifest = build_best_mapping(mission)

            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0122.DNG", "VIS_0123.DNG", "VIS_0125.DNG", "VIS_0128.DNG"],
            )

    def test_all_the_aligned_images_maps_every_point_not_flagged(self):
        """Step 5 "All the aligned images" (|dt| up to 6 s, one image in 1)."""
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            (mission / "ImgIRdrone" / "shoot_points.json").write_text(json.dumps({"shoot_points": [
                {"FileName": f"VIS_{index:04d}.DNG", "dt": dt, "failed": index == 125}
                for index, dt in ((120, 0.5), (121, -2.2), (122, 0.1), (123, 5.9), (125, 0.2), (128, 0.1))]}),
                encoding="utf-8")

            manifest = build_best_mapping(mission, dt_tolerance_s=6.0, sample_every=1)

            self.assertEqual(
                [point["VIS"]["FileName"] for point in manifest["shoot_points"]],
                ["VIS_0120.DNG", "VIS_0121.DNG", "VIS_0122.DNG", "VIS_0123.DNG", "VIS_0128.DNG"],
            )

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

    def _copy_selected_files(self, manifest, images_folder):
        for quartet in manifest["image_quartets"]:
            for source in quartet["files"].values():
                source_path = Path(source)
                for path in (source_path, source_path.with_suffix(".exif")):
                    if path.is_file():
                        shutil.copy2(path, images_folder / path.name)

    def test_reuses_existing_identical_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir(parents=True)
            self._copy_selected_files(manifest, images_folder)

            self.assertEqual(prepare_odm_input(mission, manifest), images_folder)

    def test_rejects_existing_files_that_differ_from_the_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            images_folder = mission / "mapping_MULTI" / "images"
            images_folder.mkdir(parents=True)
            self._copy_selected_files(manifest, images_folder)
            stale = next(images_folder.glob("*.tif"))
            stale.write_bytes(b"older run")

            with self.assertRaisesRegex(ODMMappingError, "differ from the selected"):
                prepare_odm_input(mission, manifest)

    def test_copies_when_the_storage_refuses_hard_links(self):
        # exFAT / FAT32 external drives: os.link raises "operation not permitted".
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            messages = []
            refused = OSError(errno.EPERM, "Operation not permitted")
            with patch("IRD_Interactive_ODM.os.link", side_effect=refused) as link:
                images_folder = prepare_odm_input(mission, manifest, log=messages.append)

            link.assert_called_once()  # not retried for every file
            files = list(images_folder.iterdir())
            self.assertEqual(len(files), 15)
            for path in files:
                self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(len(messages), 1)
            self.assertIn("copied", messages[0])

    def test_disk_full_while_copying_leaves_no_partial_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            manifest = build_best_mapping(mission)
            calls = []

            def copy_then_disk_full(source, target):
                calls.append(target)
                if len(calls) == 3:
                    Path(target).write_bytes(b"half")
                    raise OSError(errno.ENOSPC, "No space left on device")
                return shutil.copyfile(source, target)

            with patch("IRD_Interactive_ODM.os.link", side_effect=OSError(errno.EPERM, "no")), \
                    patch("IRD_Interactive_ODM.shutil.copy2", side_effect=copy_then_disk_full):
                with self.assertRaises(DiskFullError):
                    prepare_odm_input(mission, manifest)

            self.assertFalse((mission / "mapping_MULTI" / "images").exists())

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

    def _built_map(self, mission):
        mapping_folder = mission / "mapping_MULTI"
        (mapping_folder / "mapping_result").mkdir(parents=True)
        (mapping_folder / "mapping_result" / "ortho.tif").write_text("previous map", encoding="utf-8")
        (mapping_folder / "img_best_mappping.json").write_text(
            json.dumps({"created_at_utc": "2026-11-10T16:17:00+00:00"}), encoding="utf-8")
        return mapping_folder

    def test_a_map_already_built_is_set_aside_not_overwritten(self):
        import IRD_Interactive_ODM as ODM
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            mapping_folder = self._built_map(mission)
            self.assertIsNone(ODM.set_previous_mapping_aside(mission / "elsewhere"))
            previous = ODM.set_previous_mapping_aside(mission)
            self.assertTrue(previous.name.startswith("mapping_MULTI_20261110_"))
            self.assertEqual((previous / "mapping_result" / "ortho.tif").read_text(encoding="utf-8"),
                             "previous map")
            # a new, empty mapping folder with the same camera configuration
            self.assertEqual(sorted(p.name for p in mapping_folder.iterdir()), ["camera"])
            self.assertTrue((mapping_folder / "camera" / "camera_IRdrone.json").is_file())
            self.assertEqual(ODM.previous_mapping_details(mapping_folder), [])
            _check_mapping_outputs_available(mapping_folder)          # a new run can start
            self._built_map(mission)                                  # a second time: another name
            self.assertNotEqual(ODM.set_previous_mapping_aside(mission), previous)

    def test_an_unfinished_run_is_set_aside_too(self):
        """A run stopped or failed with no map before it leaves its input images
        (and its log): the next run sets them aside instead of refusing them."""
        import IRD_Interactive_ODM as ODM
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            mapping_folder = mission / "mapping_MULTI"
            (mapping_folder / "images").mkdir()
            (mapping_folder / "images" / "IRD_0001_1.tif").write_bytes(b"old selection")
            (mapping_folder / "odm_run_20261110_161700_000000.log").write_text("stopped", encoding="utf-8")
            self.assertEqual(len(ODM.previous_mapping_details(mapping_folder)), 2)
            previous = ODM.set_previous_mapping_aside(mission)
            self.assertIsNotNone(previous)
            self.assertTrue((previous / "images" / "IRD_0001_1.tif").is_file())
            self.assertEqual(sorted(p.name for p in mapping_folder.iterdir()), ["camera"])
            (mapping_folder / "images").mkdir()                   # an empty images folder: nothing to keep
            self.assertEqual(ODM.previous_mapping_details(mapping_folder), [])

    def test_a_failed_run_puts_the_previous_map_back(self):
        import IRD_Interactive_ODM as ODM
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            self._built_map(mission)
            log = []

            def failing_run(_mission, mapping_folder, *args):
                (mapping_folder / "odm_run.log").write_text("boom", encoding="utf-8")
                raise ODM.ODMMappingError("ODM exited with code 1")

            with patch.object(ODM, "_run_odm_in", side_effect=failing_run):
                with self.assertRaisesRegex(ODMMappingError, "code 1"):
                    ODM.run_odm(mission, log_callback=log.append)
            self.assertEqual((mission / "mapping_MULTI" / "mapping_result" / "ortho.tif").read_text(
                encoding="utf-8"), "previous map")
            failed = [p for p in mission.iterdir() if p.name.startswith("mapping_MULTI_failed_")]
            self.assertEqual(len(failed), 1)
            self.assertTrue((failed[0] / "odm_run.log").is_file())          # its log kept
            self.assertFalse(any(p.name.startswith("mapping_MULTI_2026") for p in mission.iterdir()))
            self.assertTrue(any("previous one is back" in line for line in log))

    def test_a_run_that_wrote_nothing_leaves_no_failed_folder(self):
        import IRD_Interactive_ODM as ODM
        with tempfile.TemporaryDirectory() as temporary:
            mission = Path(temporary)
            self._create_mission(mission)
            self._built_map(mission)
            with patch.object(ODM, "_run_odm_in", side_effect=ODM.DockerUnavailableError("off")):
                with self.assertRaises(ODM.DockerUnavailableError):
                    ODM.run_odm(mission)
            self.assertEqual(sorted(p.name for p in mission.iterdir() if p.name.startswith("mapping")),
                             ["mapping_MULTI"])
            self.assertTrue((mission / "mapping_MULTI" / "mapping_result" / "ortho.tif").is_file())

    def test_style_shots_geojson_adds_shot_number_and_qgis_style(self):
        import xml.etree.ElementTree as ElementTree

        from IRD_Interactive_ODM import style_shots_geojson

        with tempfile.TemporaryDirectory() as temporary:
            shots = Path(temporary) / "shots.geojson"
            shots.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"filename": "IRD_0128_1.tif"},
                                "geometry": {"type": "Point", "coordinates": [3.4, 45.1, 100]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            style_shots_geojson(shots)

            properties = json.loads(shots.read_text(encoding="utf-8"))["features"][0]["properties"]
            self.assertEqual(properties["shot"], 128)
            self.assertEqual(properties["filename"], "IRD_0128_1.tif")
            root = ElementTree.parse(shots.with_suffix(".qml")).getroot()
            self.assertEqual(root.find(".//text-style").get("fieldName"), "shot")

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
        mapping = Path("C:/mission/mapping_MULTI")
        command = build_odm_command(mapping, 3.3)

        self.assertEqual(command[0:4], ["docker", "--context", "desktop-linux", "run"])
        # "C:\\mission:/datasets" on Windows
        self.assertIn(f"{mapping.resolve().parent}:/datasets", command)
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

    def test_validates_visible_only_odm_geotiff(self):
        """A visible only mission maps red, green, blue (+ alpha): three bands are enough."""
        with tempfile.TemporaryDirectory() as temporary:
            orthophoto = Path(temporary) / "odm_orthophoto.tif"
            with rasterio.open(orthophoto, "w", driver="GTiff", width=3, height=2, count=4, dtype="uint16",
                               crs="EPSG:32631", transform=Affine(0.033, 0, 100, 0, -0.033, 200)) as dataset:
                for index, name in enumerate(("Red", "Green", "Blue"), 1):
                    dataset.write(np.full((2, 3), index, dtype=np.uint16), index)
                    dataset.set_band_description(index, name)
                dataset.write(np.full((2, 3), 4, dtype=np.uint16), 4)
            result = _validate_odm_outputs(orthophoto, ("red", "green", "blue"))
            self.assertEqual(result["band_descriptions"][:3], ["Red", "Green", "Blue"])
            with self.assertRaises(ODMMappingError):     # a multispectral mission needs the NIR
                _validate_odm_outputs(orthophoto)

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

    def _write_orthophoto_with_empty_overviews(self, orthophoto):
        """Mimic ODM: valid full-resolution pixels but all-zero overviews."""
        with rasterio.open(
            orthophoto,
            "w",
            driver="GTiff",
            width=256,
            height=128,
            count=5,
            dtype="uint16",
            crs="EPSG:32631",
            transform=Affine(0.033, 0, 100, 0, -0.033, 200),
            tiled=True,
            blockxsize=64,
            blockysize=64,
            compress="deflate",
        ) as dataset:
            dataset.build_overviews([2, 4], Resampling.average)
        with rasterio.open(orthophoto, "r+") as dataset:
            gradient = np.tile(np.arange(256, dtype=np.uint16) * 200, (128, 1))
            for band in range(1, 5):
                dataset.write(gradient, band)
            dataset.write(np.full((128, 256), 255, dtype=np.uint16), 5)
            dataset.descriptions = ("Red", "Green", "Blue", "NIR", None)
        with rasterio.open(orthophoto, overview_level=0) as overview:
            self.assertEqual(int(overview.read(1).max()), 0)

    def test_preview_ignores_empty_overviews(self):
        with tempfile.TemporaryDirectory() as temporary:
            orthophoto = Path(temporary) / "orthophoto.tif"
            self._write_orthophoto_with_empty_overviews(orthophoto)

            preview = read_orthophoto_preview(orthophoto, max_dimension=64)

            self.assertGreater(int(preview.max()), 0)

    def test_build_orthophoto_overviews_replaces_empty_overviews(self):
        with tempfile.TemporaryDirectory() as temporary:
            orthophoto = Path(temporary) / "orthophoto.tif"
            self._write_orthophoto_with_empty_overviews(orthophoto)
            with rasterio.open(orthophoto) as dataset:
                full_resolution = dataset.read()

            build_orthophoto_overviews(orthophoto)

            with rasterio.open(orthophoto) as dataset:
                np.testing.assert_array_equal(dataset.read(), full_resolution)
                self.assertEqual(dataset.descriptions[:4], ("Red", "Green", "Blue", "NIR"))
                self.assertEqual(dataset.overviews(1), [2, 4, 8, 16])
            with rasterio.open(orthophoto, overview_level=0) as overview:
                self.assertGreater(int(overview.read(1).max()), 0)
            self.assertEqual(sorted(path.name for path in Path(temporary).iterdir()), ["orthophoto.tif"])

    def test_odm_command_does_not_ask_odm_for_overviews(self):
        command = build_odm_command(Path("/mission/mapping_MULTI"), 3.3, docker_context=None)

        self.assertNotIn("--build-overviews", command)

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


class ODMEngineTests(unittest.TestCase):
    """A newer ODM image is detected; the GPU is used only if Docker can give it."""

    def test_gpu_command_uses_gpu_image_and_gpus_all(self):
        import IRD_Interactive_ODM as ODM
        command = build_odm_command(Path("/mission/mapping_MULTI"), 3.0, "docker", None, use_gpu=True)
        self.assertEqual(command[command.index("--gpus") + 1], "all")
        self.assertIn(ODM.ODM_GPU_IMAGE, command)
        self.assertLess(command.index("--gpus"), command.index(ODM.ODM_GPU_IMAGE))
        cpu = build_odm_command(Path("/mission/mapping_MULTI"), 3.0, "docker", None)
        self.assertNotIn("--gpus", cpu)
        self.assertIn(ODM.ODM_IMAGE, cpu)

    def test_local_image_info_reads_version_and_digest(self):
        import IRD_Interactive_ODM as ODM
        inspect = json.dumps({"Created": "2026-08-21T17:44:29Z",
                              "RepoDigests": ["opendronemap/odm@sha256:abc"],
                              "Config": {"Labels": {"org.opencontainers.image.version": "3.6.2"}}})
        with patch.object(ODM, "_docker_output", return_value=inspect):
            info = ODM.local_image_info()
        self.assertEqual(info["version"], "3.6.2")
        self.assertEqual(info["digests"], ["sha256:abc"])
        with patch.object(ODM, "_docker_output", return_value=None):
            self.assertIsNone(ODM.local_image_info())

    def test_update_available_compares_digests(self):
        import IRD_Interactive_ODM as ODM
        local = {"digests": ["sha256:abc"]}
        self.assertFalse(ODM.update_available(local, {"digest": "sha256:abc"}))
        self.assertTrue(ODM.update_available(local, {"digest": "sha256:new"}))
        self.assertFalse(ODM.update_available(local, None))          # offline
        self.assertFalse(ODM.update_available(None, {"digest": "x"}))  # not downloaded: no "update"

    def test_remote_image_info_offline(self):
        import IRD_Interactive_ODM as ODM
        with patch.object(ODM, "_http_json", side_effect=OSError("offline")):
            self.assertIsNone(ODM.remote_image_info())

    def test_remote_image_info_with_release(self):
        import IRD_Interactive_ODM as ODM
        answers = [{"digest": "sha256:new", "last_updated": "2026-10-02T10:00:00Z", "full_size": 5},
                   {"tag_name": "v3.7.0"}]
        with patch.object(ODM, "_http_json", side_effect=answers):
            info = ODM.remote_image_info()
        self.assertEqual((info["digest"], info["version"]), ("sha256:new", "3.7.0"))

    def test_no_nvidia_gpu_no_container_started(self):
        import IRD_Interactive_ODM as ODM
        with patch.object(ODM, "nvidia_gpu_present", return_value=False), \
                patch.object(ODM.subprocess, "run") as run:
            usable, reason = ODM.docker_gpu_available()
        self.assertFalse(usable)
        self.assertIn("no NVIDIA GPU", reason)
        run.assert_not_called()

    def test_gpu_probe_failure_explains(self):
        import IRD_Interactive_ODM as ODM
        failed = subprocess.CompletedProcess(
            args=["docker"], returncode=125, stdout="",
            stderr='docker: Error response from daemon: could not select device driver "" with capabilities: [[gpu]]\n'
                   "Run 'docker run --help' for more information\n")
        with patch.object(ODM, "nvidia_gpu_present", return_value=True), \
                patch.object(ODM.subprocess, "run", return_value=failed) as run:
            usable, reason = ODM.docker_gpu_available(probe_image=ODM.ODM_IMAGE)
        self.assertFalse(usable)
        self.assertIn("could not select device driver", reason)
        self.assertIn("--gpus", run.call_args.args[0])

    def test_gpu_probe_success(self):
        import IRD_Interactive_ODM as ODM
        ok = subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")
        with patch.object(ODM, "nvidia_gpu_present", return_value=True), \
                patch.object(ODM.subprocess, "run", return_value=ok):
            self.assertTrue(ODM.docker_gpu_available(probe_image=ODM.ODM_IMAGE)[0])

    def _engine_part_of_run(self, use_gpu, update_image, gpu_usable, local):
        """_run_odm_in up to the image selection (stopped there): the log and the pulls."""
        import IRD_Interactive_ODM as ODM
        log = []
        with patch.object(ODM, "_check_mapping_outputs_available"), \
                patch.object(ODM, "resolve_docker_context", return_value=None), \
                patch.object(ODM, "check_docker", return_value=("docker", "29.9")), \
                patch.object(ODM, "docker_gpu_available", return_value=(gpu_usable, "no toolkit")), \
                patch.object(ODM, "local_image_info", return_value=local), \
                patch.object(ODM, "pull_odm_image") as pull, \
                patch.object(ODM, "build_best_mapping", side_effect=ODM.ODMMappingError("stop")):
            with self.assertRaises(ODM.ODMMappingError):
                ODM._run_odm_in(Path("/m"), Path("/m/mapping_MULTI"), Path("/m/x.json"), log.append,
                                lambda _s: None, 0.5, 3, None, use_gpu, update_image)
        return log, pull

    def test_gpu_refused_falls_back_to_cpu(self):
        import IRD_Interactive_ODM as ODM
        log, pull = self._engine_part_of_run(True, False, False, {"version": "3.6.2"})
        self.assertTrue(any(line.startswith("The GPU is not used: no toolkit") for line in log))
        self.assertTrue(any("OpenDroneMap 3.6.2 (opendronemap/odm:latest), on the CPU." == line for line in log))
        pull.assert_not_called()

    def test_update_pulls_the_image_used(self):
        import IRD_Interactive_ODM as ODM
        _, pull = self._engine_part_of_run(True, True, True, {"version": "3.7.0"})
        self.assertEqual(pull.call_args.args[0], ODM.ODM_GPU_IMAGE)
        _, pull = self._engine_part_of_run(False, False, False, None)       # not downloaded yet
        self.assertEqual(pull.call_args.args[0], ODM.ODM_IMAGE)

    def test_engine_status_docker_off(self):
        import IRD_Interactive_ODM as ODM
        with patch.object(ODM, "resolve_docker_context", return_value=None), \
                patch.object(ODM, "check_docker", side_effect=ODM.DockerUnavailableError("off")):
            status = ODM.odm_engine_status()
        self.assertIsNone(status["docker"])
        self.assertFalse(status["gpu"])


if __name__ == "__main__":
    unittest.main()
