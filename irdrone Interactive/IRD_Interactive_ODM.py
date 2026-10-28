"""Prepare an OpenDroneMap image list from synchronized multispectral captures."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling


MANIFEST_NAME = "img_best_mappping.json"
ODM_PROJECT_NAME = "mapping_MULTI"
ODM_RESULTS_FOLDER = "mapping_result"
ODM_IMAGE = "opendronemap/odm:latest"
ODM_CONTEXT = "desktop-linux"
ODM_MAX_CONCURRENCY = 4
BAND_NAMES = ("red", "green", "blue", "nir")
VIS_FILENAME_PATTERN = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)
ODM_RESULT_FILES = {
    "orthophoto": Path("odm_orthophoto") / "odm_orthophoto.tif",
    "report": Path("odm_report") / "report.pdf",
    "mesh": Path("odm_meshing") / "odm_25dmesh.ply",
}
ODM_WORKING_DIRECTORIES = (
    "images",
    "odm_dem",
    "odm_filterpoints",
    "odm_georeferencing",
    "odm_meshing",
    "odm_orthophoto",
    "odm_report",
    "odm_texturing_25d",
    "opensfm",
)


class ODMMappingError(ValueError):
    """Raised when required mission mapping metadata is missing or invalid."""


class DockerUnavailableError(ODMMappingError):
    """Raised when the Docker CLI or selected Docker engine is unavailable."""


def check_docker() -> Tuple[str, str]:
    """Return the Docker executable and server version, or explain how to start it."""
    docker_executable = shutil.which("docker")
    if docker_executable is None:
        raise DockerUnavailableError(
            "Docker CLI was not found on PATH. Start or install Docker Desktop, then "
            "verify that `docker --context desktop-linux version` shows both Client "
            "and Server."
        )

    try:
        docker_check = subprocess.run(
            [
                docker_executable,
                "--context",
                ODM_CONTEXT,
                "info",
                "--format",
                "{{.ServerVersion}}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DockerUnavailableError(
            f"Could not contact Docker Desktop: {error}. Start Docker Desktop and "
            "retry."
        ) from error

    server_version = docker_check.stdout.strip()
    if docker_check.returncode != 0 or not server_version:
        details = (docker_check.stderr or docker_check.stdout).strip()
        raise DockerUnavailableError(
            f"Docker Desktop context '{ODM_CONTEXT}' is not responding. Start Docker "
            "Desktop, wait until it reports that the engine is running, then retry."
            + (f"\nDocker response: {details}" if details else "")
        )
    return docker_executable, server_version


def _load_json(path: Path) -> Any:
    """Load a UTF-8 JSON file and report errors with its path."""
    try:
        with path.open("r", encoding="utf-8-sig") as json_file:
            return json.load(json_file)
    except FileNotFoundError as error:
        raise ODMMappingError(f"Required mission file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ODMMappingError(
            f"Invalid JSON in {path} at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error


def _image_number(filename: str, shoot_point_index: int) -> str:
    """Extract the capture number from a VIS DNG filename."""
    match = VIS_FILENAME_PATTERN.fullmatch(Path(filename).name)
    if match is None:
        raise ODMMappingError(
            f"Shoot point {shoot_point_index} has an unexpected VIS filename: {filename!r}"
        )
    return match.group(1)


def _validate_quartet(paths: Dict[str, Path]) -> Tuple[bool, Optional[List[int]], List[str]]:
    """Check that all four source TIFFs are readable single-band images of equal size."""
    errors: List[str] = []
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        errors.extend(f"Missing TIFF: {path}" for path in missing)
        return False, None, errors

    reference_shape: Optional[List[int]] = None
    reference_dtype: Optional[str] = None
    for path in paths.values():
        try:
            with rasterio.open(path) as dataset:
                shape = [dataset.width, dataset.height]
                if dataset.count != 1:
                    errors.append(
                        f"{path.name} contains {dataset.count} bands; expected a single-band TIFF."
                    )
                if reference_shape is None:
                    reference_shape = shape
                    reference_dtype = dataset.dtypes[0]
                elif shape != reference_shape:
                    errors.append(
                        f"{path.name} has dimensions {shape}; expected {reference_shape}."
                    )
                elif dataset.dtypes[0] != reference_dtype:
                    errors.append(
                        f"{path.name} has dtype {dataset.dtypes[0]}; expected {reference_dtype}."
                    )
        except (rasterio.errors.RasterioError, OSError) as error:
            errors.append(f"Could not read {path}: {error}")

    return not errors, reference_shape, errors


def _positive_number(value: Any, description: str) -> float:
    """Parse a positive finite number from numeric EXIF or camera metadata."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ODMMappingError(f"{description} must be a positive number.")
    try:
        number = float(value)
    except ValueError as error:
        raise ODMMappingError(f"{description} must be a positive number.") from error
    if not math.isfinite(number) or number <= 0:
        raise ODMMappingError(f"{description} must be a positive finite number.")
    return number


def _estimate_orthophoto_resolution(
    shoot_point_records: List[Dict[str, Any]],
    images_folder: Path,
    camera_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Estimate a safe ODM output resolution from flight altitude and camera intrinsics."""
    estimates: List[Dict[str, Any]] = []
    errors: List[str] = []

    for record in shoot_point_records:
        if not record["ready_for_odm"]:
            continue

        image_number = record["image_number"]
        exif_path = images_folder / f"IRD_{image_number}_1.exif"
        try:
            exif_data = _load_json(exif_path)
            if not isinstance(exif_data, dict):
                raise ODMMappingError(f"{exif_path} must contain a JSON object.")

            width = exif_data.get("ImageWidth")
            height = exif_data.get("ImageHeight")
            if (
                isinstance(width, bool)
                or not isinstance(width, int)
                or isinstance(height, bool)
                or not isinstance(height, int)
            ):
                raise ODMMappingError(
                    f"{exif_path} must contain integer ImageWidth and ImageHeight values."
                )
            expected_dimensions = record["dimensions_width_height"]
            if expected_dimensions != [width, height]:
                raise ODMMappingError(
                    f"{exif_path} dimensions [{width}, {height}] do not match the TIFF "
                    f"dimensions {expected_dimensions}."
                )

            matching_cameras = [
                camera
                for camera in camera_data.values()
                if isinstance(camera, dict)
                and camera.get("width") == width
                and camera.get("height") == height
            ]
            if len(matching_cameras) != 1:
                raise ODMMappingError(
                    f"{camera_data!r} must define exactly one camera model matching "
                    f"{width}x{height}."
                )
            focal_x = _positive_number(
                matching_cameras[0].get("focal_x"),
                f"{exif_path} matching camera focal_x",
            )
            altitude_m = _positive_number(
                exif_data.get("DroneAltitudeGround"),
                f"{exif_path} DroneAltitudeGround",
            )
            gsd_cm = altitude_m / (focal_x * width) * 100.0
            record["estimated_ground_sample_distance_cm"] = gsd_cm
            estimates.append(
                {
                    "VIS_filename": record["VIS"]["FileName"],
                    "sidecar": str(exif_path),
                    "drone_altitude_above_ground_m": altitude_m,
                    "camera_focal_x_normalized": focal_x,
                    "ground_sample_distance_cm": gsd_cm,
                }
            )
        except ODMMappingError as error:
            record["ground_sample_distance_error"] = str(error)
            errors.append(str(error))

    gsd_values = [estimate["ground_sample_distance_cm"] for estimate in estimates]
    ready_capture_count = sum(record["ready_for_odm"] for record in shoot_point_records)
    estimates_complete = len(estimates) == ready_capture_count and not errors
    median_gsd_cm = statistics.median(gsd_values) if estimates_complete and gsd_values else None
    recommended_resolution_cm = (
        math.ceil(median_gsd_cm * 10.0) / 10.0 if median_gsd_cm is not None else None
    )
    return {
        "method": "DroneAltitudeGround / (camera focal_x * ImageWidth), converted to cm/pixel",
        "source": "ImgIRdrone/imgMultispectral/IRD_XXXX_1.exif",
        "assumption": "Camera is pointed approximately at nadir; local terrain variation is not modeled.",
        "estimated_capture_count": len(estimates),
        "min_ground_sample_distance_cm": min(gsd_values) if gsd_values else None,
        "median_ground_sample_distance_cm": median_gsd_cm,
        "max_ground_sample_distance_cm": max(gsd_values) if gsd_values else None,
        "recommended_orthophoto_resolution_cm_per_pixel": recommended_resolution_cm,
        "recommendation": "Median capture GSD rounded up to the next 0.1 cm/pixel",
        "errors": errors,
        "per_capture_estimates": estimates,
    }


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write a UTF-8 JSON manifest atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f"{path.stem}_",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as json_file:
            temporary_path = Path(json_file.name)
            json.dump(data, json_file, indent=2, ensure_ascii=False)
            json_file.write("\n")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _write_odm_run_status(
    manifest_path: Path,
    status: str,
    command: List[str],
    log_path: Path,
    started_at: str,
    finished_at: Optional[str] = None,
    exit_code: Optional[int] = None,
    elapsed_seconds: Optional[float] = None,
) -> None:
    """Persist the command and current state of an ODM execution."""
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ODMMappingError(f"Invalid mapping manifest: {manifest_path}")
    manifest["odm_started"] = status in ("running", "completed", "failed")
    manifest["odm_run"] = {
        "status": status,
        "command": command,
        "log_path": str(log_path),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "exit_code": exit_code,
        "elapsed_seconds": elapsed_seconds,
    }
    _write_json_atomic(manifest_path, manifest)


def format_elapsed_duration(elapsed_seconds: float) -> str:
    """Format an elapsed duration as hours, minutes, and seconds."""
    total_seconds = max(0, round(elapsed_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {seconds:02d} s"
    if minutes:
        return f"{minutes} min {seconds:02d} s"
    return f"{seconds} s"


def build_odm_command(
    mapping_folder: Path,
    orthophoto_resolution_cm: float,
    docker_executable: str = "docker",
) -> List[str]:
    """Build the Docker command for the mission's mapping_MULTI project."""
    resolution = _positive_number(
        orthophoto_resolution_cm,
        "Orthophoto resolution in cm per pixel",
    )
    mapping_folder = Path(mapping_folder).expanduser().resolve()
    mission_folder = mapping_folder.parent
    camera_path = (
        Path("/datasets")
        / mapping_folder.name
        / "camera"
        / "camera_IRdrone.json"
    )
    return [
        docker_executable,
        "--context",
        ODM_CONTEXT,
        "run",
        "--rm",
        "-v",
        f"{mission_folder}:/datasets",
        ODM_IMAGE,
        "--project-path",
        "/datasets",
        ODM_PROJECT_NAME,
        "--cameras",
        str(camera_path).replace("\\", "/"),
        "--orthophoto-resolution",
        f"{resolution:.1f}",
        "--fast-orthophoto",
        "--use-exif",
        "--force-gps",
        "--build-overviews",
        "--skip-band-alignment",
        "--use-fixed-camera-params",
        "--max-concurrency",
        str(ODM_MAX_CONCURRENCY),
    ]


def _validate_odm_outputs(orthophoto_path: Path) -> Dict[str, Any]:
    """Validate that ODM produced a readable, georeferenced four-band orthophoto."""
    if not orthophoto_path.is_file():
        raise ODMMappingError(f"ODM completed without producing {orthophoto_path}")
    try:
        with rasterio.open(orthophoto_path) as dataset:
            if dataset.count < 4:
                raise ODMMappingError(
                    f"ODM orthophoto contains {dataset.count} bands; at least four are required."
                )
            expected_descriptions = ("red", "green", "blue", "nir")
            actual_descriptions = tuple(
                (description or "").casefold() for description in dataset.descriptions[:4]
            )
            if actual_descriptions != expected_descriptions:
                raise ODMMappingError(
                    "ODM orthophoto band descriptions are unexpected: "
                    f"{dataset.descriptions[:4]}"
                )
            if dataset.crs is None:
                raise ODMMappingError("ODM orthophoto has no coordinate reference system.")
            band_labels = [
                description
                or (
                    "Alpha"
                    if getattr(dataset.colorinterp[index - 1], "name", "") == "alpha"
                    else f"Band {index}"
                )
                for index, description in enumerate(dataset.descriptions, start=1)
            ]
            return {
                "path": str(orthophoto_path),
                "width": dataset.width,
                "height": dataset.height,
                "band_count": dataset.count,
                "band_descriptions": list(dataset.descriptions),
                "band_labels": band_labels,
                "crs": dataset.crs.to_string(),
                "resolution": list(dataset.res),
            }
    except rasterio.errors.RasterioError as error:
        raise ODMMappingError(f"Could not read ODM orthophoto {orthophoto_path}: {error}") from error


def read_orthophoto_preview(
    orthophoto_path: Path,
    max_dimension: int = 1600,
) -> np.ndarray:
    """Read and contrast-stretch a small RGB preview without loading the full raster."""
    if max_dimension < 1:
        raise ValueError("Preview maximum dimension must be positive.")

    try:
        with rasterio.open(orthophoto_path) as dataset:
            if dataset.count < 3:
                raise ODMMappingError(
                    f"Cannot create RGB preview from an orthophoto with "
                    f"{dataset.count} bands."
                )
            scale = min(1.0, max_dimension / max(dataset.width, dataset.height))
            preview_width = max(1, round(dataset.width * scale))
            preview_height = max(1, round(dataset.height * scale))
            rgb_bands = dataset.read(
                indexes=(1, 2, 3),
                out_shape=(3, preview_height, preview_width),
                resampling=Resampling.average,
                masked=True,
            )
            rgb_bands = np.ma.asarray(rgb_bands)
            preview = np.zeros(
                (preview_height, preview_width, 3),
                dtype=np.uint8,
            )
            for channel in range(3):
                band = np.asarray(
                    rgb_bands[channel].astype(np.float32).filled(np.nan),
                    dtype=np.float32,
                )
                valid = np.isfinite(band)
                if not np.any(valid):
                    continue
                low, high = np.percentile(band[valid], (2, 98))
                if high <= low:
                    low = float(np.min(band[valid]))
                    high = float(np.max(band[valid]))
                if high > low:
                    normalized = np.clip((band - low) / (high - low), 0, 1)
                    preview[:, :, channel] = np.rint(normalized * 255).astype(np.uint8)
            return preview
    except rasterio.errors.RasterioError as error:
        raise ODMMappingError(
            f"Could not read orthophoto preview {orthophoto_path}: {error}"
        ) from error


def build_best_mapping(
    mission_folder: Path,
    dt_tolerance_s: float = 0.5,
    sample_every: int = 3,
) -> Dict[str, Any]:
    """Build and save the selected shoot points and their matching TIFF quartets."""
    mission_folder = Path(mission_folder).expanduser().resolve()
    if not mission_folder.is_dir():
        raise ODMMappingError(f"Mission folder does not exist: {mission_folder}")
    if not math.isfinite(dt_tolerance_s) or dt_tolerance_s < 0:
        raise ODMMappingError("The maximum time difference must be a finite, non-negative value.")
    if sample_every < 1:
        raise ODMMappingError("The sampling interval must be at least 1.")

    aerial_photography = mission_folder / "AerialPhotography"
    shoot_points_path = aerial_photography / "shoot_points.json"
    transfer_info_path = aerial_photography / "VIS" / "transfer_info_VIS_dng.json"
    mapping_folder = mission_folder / "mapping_MULTI"
    images_folder = mission_folder / "ImgIRdrone" / "imgMultispectral"
    camera_path = mapping_folder / "camera" / "camera_IRdrone.json"

    shoot_points_data = _load_json(shoot_points_path)
    if not isinstance(shoot_points_data, dict) or not isinstance(
        shoot_points_data.get("shoot_points"), list
    ):
        raise ODMMappingError(f"{shoot_points_path} must contain a 'shoot_points' list.")
    transfer_data = _load_json(transfer_info_path)
    fly_section = transfer_data.get("fly") if isinstance(transfer_data, dict) else None
    fly_images = fly_section.get("listCopiedImages") if isinstance(fly_section, dict) else None
    if not isinstance(fly_images, list) or not all(isinstance(name, str) for name in fly_images):
        raise ODMMappingError(
            f"{transfer_info_path} must contain 'fly.listCopiedImages' as a list of filenames."
        )
    camera_data = _load_json(camera_path)
    if not isinstance(camera_data, dict) or not camera_data:
        raise ODMMappingError(f"{camera_path} must contain a non-empty camera configuration object.")

    fly_filenames: Set[str] = {Path(filename).name.casefold() for filename in fly_images}
    eligible_pairs: List[Tuple[int, Dict[str, Any], Dict[str, Any], float]] = []
    counters = {
        "rank_one_pairs": 0,
        "rank_one_pairs_with_valid_dt": 0,
        "rank_one_pairs_within_dt_tolerance": 0,
        "fly_pairs_within_dt_tolerance": 0,
    }

    for shoot_point_index, shoot_point in enumerate(shoot_points_data["shoot_points"]):
        if not isinstance(shoot_point, dict):
            continue
        vis_data = shoot_point.get("VIS")
        nir_matches = shoot_point.get("NIR")
        if not isinstance(vis_data, dict) or not isinstance(nir_matches, list):
            continue
        vis_filename = vis_data.get("FileName")
        if not isinstance(vis_filename, str):
            continue

        for nir_match in nir_matches:
            if not isinstance(nir_match, dict):
                continue
            rank = nir_match.get("rank")
            if isinstance(rank, bool) or not isinstance(rank, (int, float)) or rank != 1:
                continue
            counters["rank_one_pairs"] += 1
            dt = nir_match.get("dt")
            if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt):
                continue
            counters["rank_one_pairs_with_valid_dt"] += 1
            absolute_dt = abs(float(dt))
            if absolute_dt > dt_tolerance_s:
                continue
            counters["rank_one_pairs_within_dt_tolerance"] += 1
            if Path(vis_filename).name.casefold() not in fly_filenames:
                continue
            counters["fly_pairs_within_dt_tolerance"] += 1
            eligible_pairs.append((shoot_point_index, vis_data, nir_match, float(dt)))

    sampled_pairs = eligible_pairs[::sample_every]
    shoot_point_records: List[Dict[str, Any]] = []
    image_quartets: List[Dict[str, Any]] = []
    for selection_index, (shoot_point_index, vis_data, nir_match, dt) in enumerate(sampled_pairs):
        vis_filename = str(vis_data["FileName"])
        image_number = _image_number(vis_filename, shoot_point_index)
        band_paths = {
            band_name: (images_folder / f"IRD_{image_number}_{band_index}.tif").resolve()
            for band_index, band_name in enumerate(BAND_NAMES, start=1)
        }
        ready, dimensions, errors = _validate_quartet(band_paths)
        record = {
            "selection_index": selection_index,
            "shoot_point_index": shoot_point_index,
            "VIS": vis_data,
            "NIR_rank_1": nir_match,
            "dt_seconds": dt,
            "absolute_dt_seconds": abs(dt),
            "image_number": image_number,
            "files": {name: str(path) for name, path in band_paths.items()},
            "dimensions_width_height": dimensions,
            "ready_for_odm": ready,
            "validation_errors": errors,
        }
        shoot_point_records.append(record)
        if ready:
            image_quartets.append(
                {
                    "selection_index": selection_index,
                    "shoot_point_index": shoot_point_index,
                    "VIS_filename": vis_filename,
                    "dt_seconds": dt,
                    "files": record["files"],
                }
            )

    ready_count = len(image_quartets)
    resolution_estimate = _estimate_orthophoto_resolution(
        shoot_point_records,
        images_folder,
        camera_data,
    )
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mission_path": str(mission_folder),
        "selection_rules": {
            "nir_rank": 1,
            "maximum_absolute_dt_seconds": dt_tolerance_s,
            "vis_transfer_section": "fly.listCopiedImages",
            "sample_every_nth_eligible_pair": sample_every,
            "sample_offset": 0,
            "band_order": list(BAND_NAMES),
        },
        "source_files": {
            "shoot_points": str(shoot_points_path),
            "vis_transfer_info": str(transfer_info_path),
            "camera_configuration": str(camera_path),
        },
        "camera_configuration": camera_data,
        "orthophoto_resolution_estimate": resolution_estimate,
        "counts": {
            **counters,
            "sampled_shoot_points": len(sampled_pairs),
            "ready_for_odm": ready_count,
            "not_ready": len(sampled_pairs) - ready_count,
        },
        "shoot_points": shoot_point_records,
        "image_quartets": image_quartets,
        "odm_started": False,
    }
    manifest_path = mapping_folder / MANIFEST_NAME
    _write_json_atomic(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def prepare_odm_input(mission_folder: Path, manifest: Dict[str, Any]) -> Path:
    """Hard-link the selected TIFFs and sidecars into ODM's images folder."""
    mission_folder = Path(mission_folder).expanduser().resolve()
    mapping_folder = mission_folder / "mapping_MULTI"
    images_folder = mapping_folder / "images"
    camera_path = mapping_folder / "camera" / "camera_IRdrone.json"

    if not camera_path.is_file():
        raise ODMMappingError(f"ODM camera configuration was not found: {camera_path}")

    counts = manifest.get("counts")
    quartets = manifest.get("image_quartets")
    if not isinstance(counts, dict) or not isinstance(quartets, list):
        raise ODMMappingError("The mapping manifest has an invalid structure.")
    if counts.get("not_ready") != 0 or len(quartets) != counts.get("sampled_shoot_points"):
        raise ODMMappingError(
            "The selected image set contains incomplete TIFF quartets. "
            "Resolve the manifest validation errors before preparing ODM input."
        )
    if not quartets:
        raise ODMMappingError("No complete TIFF quartets are available for ODM.")
    resolution_estimate = manifest.get("orthophoto_resolution_estimate")
    recommended_resolution = (
        resolution_estimate.get("recommended_orthophoto_resolution_cm_per_pixel")
        if isinstance(resolution_estimate, dict)
        else None
    )
    if (
        isinstance(recommended_resolution, bool)
        or not isinstance(recommended_resolution, (int, float))
        or not math.isfinite(recommended_resolution)
        or recommended_resolution <= 0
    ):
        errors = (
            resolution_estimate.get("errors", [])
            if isinstance(resolution_estimate, dict)
            else []
        )
        detail = "\n".join(errors) if errors else "No valid resolution estimate is available."
        raise ODMMappingError(
            "Could not determine the ODM orthophoto resolution from the EXIF sidecars "
            f"and camera calibration:\n{detail}"
        )

    expected_images: List[Tuple[str, Path]] = []
    for quartet in quartets:
        files = quartet.get("files") if isinstance(quartet, dict) else None
        if not isinstance(files, dict) or set(files) != set(BAND_NAMES):
            raise ODMMappingError("A selected image quartet does not define all four bands.")
        for band_name in BAND_NAMES:
            source = Path(files[band_name]).resolve()
            if not source.is_file():
                raise ODMMappingError(f"Selected TIFF was not found: {source}")
            expected_images.append((source.name, source))
            sidecar = source.with_suffix(".exif")
            if sidecar.is_file():
                expected_images.append((sidecar.name, sidecar.resolve()))

    if len({name.casefold() for name, _ in expected_images}) != len(expected_images):
        raise ODMMappingError("The selected images contain duplicate filenames.")

    expected_by_name = {name.casefold(): source for name, source in expected_images}
    images_folder_created = not images_folder.exists()
    if images_folder.exists():
        if not images_folder.is_dir():
            raise ODMMappingError(f"ODM input path is not a directory: {images_folder}")
        actual_files = list(images_folder.iterdir())
        if actual_files:
            actual_by_name = {
                path.name.casefold(): path for path in actual_files if path.is_file()
            }
            if (
                len(actual_files) != len(expected_images)
                or set(actual_by_name) != set(expected_by_name)
            ):
                raise ODMMappingError(
                    f"The existing ODM images folder does not exactly match the current "
                    f"selection: {images_folder}. Remove its contents manually before "
                    "preparing the input."
                )
            not_linked = [
                source.name
                for name, source in expected_by_name.items()
                if not os.path.samefile(actual_by_name[name], source)
            ]
            if not_linked:
                raise ODMMappingError(
                    "The existing ODM input contains files that are copies rather than hard "
                    f"links to the selected sources: {', '.join(not_linked)}. Remove its "
                    "contents manually before preparing the input again."
                )
            return images_folder

    if images_folder_created:
        images_folder.mkdir(parents=True)
    created_links: List[Path] = []
    try:
        for filename, source in expected_images:
            target = images_folder / filename
            os.link(source, target)
            created_links.append(target)
    except OSError as error:
        for created_link in created_links:
            created_link.unlink(missing_ok=True)
        if images_folder_created and not any(images_folder.iterdir()):
            images_folder.rmdir()
        raise ODMMappingError(
            f"Could not prepare the ODM input folder with hard links: {error}"
        ) from error

    return images_folder


def _check_mapping_outputs_available(mapping_folder: Path) -> None:
    """Prevent ODM from overwriting prior reconstructions or archived deliverables."""
    existing_odm_outputs = [
        path.name
        for path in mapping_folder.iterdir()
        if path.is_dir()
        and (
            path.name.casefold().startswith("odm_")
            or path.name.casefold() in {"opensfm", "openmvs", "stats", "entwine"}
        )
    ]
    result_folder = mapping_folder / ODM_RESULTS_FOLDER
    existing_archives = (
        [path.name for path in result_folder.iterdir()]
        if result_folder.is_dir()
        else []
    )
    if existing_odm_outputs or existing_archives:
        details = []
        if existing_odm_outputs:
            details.append(f"ODM outputs: {', '.join(existing_odm_outputs)}")
        if existing_archives:
            details.append(f"archived results: {', '.join(existing_archives)}")
        raise ODMMappingError(
            "Existing mapping results will not be overwritten. Move or remove them "
            "manually before starting another ODM run (" + "; ".join(details) + ")."
        )


def _copy_mapping_results(mapping_folder: Path) -> Dict[str, str]:
    """Copy the selected ODM deliverables into mapping_result before cleanup."""
    sources = {
        "orthophoto": mapping_folder / ODM_RESULT_FILES["orthophoto"],
        "report": mapping_folder / ODM_RESULT_FILES["report"],
        "mesh": mapping_folder / ODM_RESULT_FILES["mesh"],
    }
    shots_candidates = (
        mapping_folder / "odm_georeferencing" / "shots.geojson",
        mapping_folder / "odm_report" / "shots.geojson",
    )
    shots_source = next((path for path in shots_candidates if path.is_file()), None)
    if shots_source is None:
        raise ODMMappingError(
            "ODM did not produce shots.geojson in odm_georeferencing or odm_report."
        )
    sources["shots"] = shots_source
    ortho_preview_candidates = (
        mapping_folder / "opensfm" / "stats" / "ortho.png",
        mapping_folder / "opensfm" / "ortho.png",
    )
    ortho_preview = next(
        (path for path in ortho_preview_candidates if path.is_file()),
        None,
    )
    if ortho_preview is None:
        raise ODMMappingError(
            "ODM did not produce ortho.png in opensfm/stats or opensfm."
        )
    sources["ortho_preview"] = ortho_preview
    georeferencing_info_candidates = (
        mapping_folder
        / "odm_georeferencing"
        / "odm_georeferenced_model.info.json",
        mapping_folder
        / "odm_georeferencing"
        / "odm_georeferencing_model.info.json",
    )
    georeferencing_info = next(
        (path for path in georeferencing_info_candidates if path.is_file()),
        None,
    )
    if georeferencing_info is None:
        raise ODMMappingError(
            "ODM did not produce the georeferenced model info JSON in odm_georeferencing."
        )
    sources["georeferencing_info"] = georeferencing_info
    ortho_preview_sidecar = ortho_preview.with_name(ortho_preview.name + ".aux.xml")
    if ortho_preview_sidecar.is_file():
        sources["ortho_preview_metadata"] = ortho_preview_sidecar

    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise ODMMappingError(
            "ODM completed but required mapping deliverables are missing: "
            + ", ".join(missing)
        )

    result_folder = mapping_folder / ODM_RESULTS_FOLDER
    existing_destinations = [
        result_folder / source.name
        for source in sources.values()
        if (result_folder / source.name).exists()
    ]
    if existing_destinations:
        raise ODMMappingError(
            "Refusing to overwrite existing mapping results: "
            + ", ".join(str(path) for path in existing_destinations)
        )
    result_folder_created = not result_folder.exists()
    result_folder.mkdir(exist_ok=True)
    copied: Dict[str, str] = {}
    created_destinations: List[Path] = []
    try:
        for name, source in sources.items():
            destination = result_folder / source.name
            shutil.copy2(source, destination)
            created_destinations.append(destination)
            copied[name] = str(destination)
    except OSError as error:
        for destination in created_destinations:
            destination.unlink(missing_ok=True)
        if result_folder_created:
            result_folder.rmdir()
        raise ODMMappingError(
            f"Could not copy ODM deliverables to {result_folder}: {error}"
        ) from error
    return copied


def _cleanup_odm_working_directories(mapping_folder: Path) -> List[str]:
    """Remove only ODM working directories after deliverables have been archived."""
    removed: List[str] = []
    for directory_name in ODM_WORKING_DIRECTORIES:
        directory = mapping_folder / directory_name
        if directory.is_dir():
            try:
                shutil.rmtree(directory)
            except OSError as error:
                raise ODMMappingError(
                    f"Could not remove ODM working directory {directory}: {error}"
                ) from error
            removed.append(directory_name)
        elif directory.exists():
            raise ODMMappingError(
                f"Expected an ODM working directory but found a non-directory path: {directory}"
            )
    return removed


def run_odm(
    mission_folder: Path,
    log_callback: Optional[Callable[[str], None]] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Prepare the selected dataset and run ODM through the Docker Desktop engine."""
    mission_folder = Path(mission_folder).expanduser().resolve()
    mapping_folder = mission_folder / "mapping_MULTI"
    manifest_path = mapping_folder / MANIFEST_NAME
    worker_log = log_callback or (lambda _message: None)
    stage = stage_callback or (lambda _message: None)

    if not mapping_folder.is_dir():
        raise ODMMappingError(f"ODM mapping folder does not exist: {mapping_folder}")
    _check_mapping_outputs_available(mapping_folder)

    stage("Checking Docker Desktop")
    docker_executable, docker_server_version = check_docker()
    worker_log(f"Docker Engine {docker_server_version} is available.")

    stage("Building image selection and estimating GSD")
    manifest = build_best_mapping(mission_folder, sample_every=3)
    counts = manifest["counts"]
    if counts["not_ready"] or not counts["ready_for_odm"]:
        raise ODMMappingError(
            f"ODM needs complete image quartets; "
            f"{counts['not_ready']} of {counts['sampled_shoot_points']} selected "
            "quartets are incomplete."
        )
    resolution_cm = manifest["orthophoto_resolution_estimate"][
        "recommended_orthophoto_resolution_cm_per_pixel"
    ]

    stage("Preparing selected TIFF quartets")
    images_folder = prepare_odm_input(mission_folder, manifest)
    command = build_odm_command(mapping_folder, resolution_cm, docker_executable)
    timestamp = datetime.now(timezone.utc)
    started_at = timestamp.isoformat()
    log_path = mapping_folder / f"odm_run_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.log"
    orthophoto_path = mapping_folder / ODM_RESULT_FILES["orthophoto"]
    _write_odm_run_status(
        manifest_path,
        "running",
        command,
        log_path,
        started_at,
    )

    worker_log(
        f"Running ODM on {counts['ready_for_odm']} image quartets "
        f"({counts['ready_for_odm'] * len(BAND_NAMES)} TIFFs)."
    )
    worker_log(f"Orthophoto resolution: {resolution_cm:.1f} cm/pixel.")
    worker_log(f"ODM command: {subprocess.list2cmdline(command)}")
    worker_log(f"Full ODM output will be saved to: {log_path}")
    stage("Running ODM reconstruction and orthophoto generation")

    process: Optional[subprocess.Popen[str]] = None
    return_code: Optional[int] = None
    run_started_monotonic: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as log_file:
            log_file.write(subprocess.list2cmdline(command) + "\n\n")
            log_file.flush()
            run_started_monotonic = time.perf_counter()
            process = subprocess.Popen(
                command,
                cwd=str(mapping_folder),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if process.stdout is None:
                raise ODMMappingError("Could not read output from the ODM process.")
            for line in process.stdout:
                log_file.write(line)
                if (
                    line.startswith("[INFO]")
                    or line.startswith("[WARNING]")
                    or line.startswith("[ERROR]")
                    or line.startswith("ERROR")
                    or "[INFO]" in line
                    or "[WARNING]" in line
                    or "[ERROR]" in line
                    or "ODM app finished" in line
                ):
                    worker_log(line.strip())
            return_code = process.wait()
            elapsed_seconds = time.perf_counter() - run_started_monotonic
        if return_code != 0:
            raise ODMMappingError(
                f"ODM exited with code {return_code}. Review the complete log: {log_path}"
            )
        stage("Validating ODM orthophoto")
        output = _validate_odm_outputs(orthophoto_path)
        stage("Archiving selected ODM results")
        copied_results = _copy_mapping_results(mapping_folder)
        output["path"] = copied_results["orthophoto"]
        stage("Cleaning ODM working directories")
        removed_directories = _cleanup_odm_working_directories(mapping_folder)
        finished_at = datetime.now(timezone.utc).isoformat()
        _write_odm_run_status(
            manifest_path,
            "completed",
            command,
            log_path,
            started_at,
            finished_at,
            return_code,
            elapsed_seconds,
        )
        worker_log(f"ODM calculation time: {format_elapsed_duration(elapsed_seconds)}.")
        worker_log(f"ODM completed successfully: {orthophoto_path}")
        worker_log(
            f"Orthophoto preserved at: {copied_results['orthophoto']}"
        )
        worker_log(
            "Removed ODM working directories: "
            + (", ".join(removed_directories) if removed_directories else "none")
        )
        return {
            "manifest_path": str(manifest_path),
            "images_folder": str(images_folder),
            "log_path": str(log_path),
            "orthophoto": output,
            "mapping_result_folder": str(mapping_folder / ODM_RESULTS_FOLDER),
            "copied_results": copied_results,
            "removed_working_directories": removed_directories,
            "selected_quartets": counts["ready_for_odm"],
            "resolution_cm_per_pixel": resolution_cm,
            "docker_server_version": docker_server_version,
            "elapsed_seconds": elapsed_seconds,
            "command": command,
        }
    except Exception:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        finished_at = datetime.now(timezone.utc).isoformat()
        if run_started_monotonic is not None and elapsed_seconds is None:
            elapsed_seconds = time.perf_counter() - run_started_monotonic
        _write_odm_run_status(
            manifest_path,
            "failed",
            command,
            log_path,
            started_at,
            finished_at,
            return_code,
            elapsed_seconds,
        )
        raise
