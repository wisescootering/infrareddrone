"""Prepare an OpenDroneMap image list from synchronized multispectral captures."""

from __future__ import annotations

import filecmp
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
import rasterio.shutil
from rasterio.enums import Resampling

from IRD_Interactive_diskspace import is_disk_full, raise_if_disk_full
import best_mapping


MANIFEST_NAME = "img_best_mappping.json"
ODM_PROJECT_NAME = "mapping_MULTI"
ODM_RESULTS_FOLDER = "mapping_result"
ODM_IMAGE = "opendronemap/odm:latest"
# Preferred Docker context (Docker Desktop). When it does not exist (e.g. plain
# Docker Engine on Linux) Docker's current context is used instead.
# Override with environment variable IRDRONE_DOCKER_CONTEXT.
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


ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# One line of the ASCII-art logo ODM prints at the end of a run.
ODM_LOGO_LINE_PATTERN = re.compile(r"^\[INFO\]\s+M\S[^\n]{60,}M$")


class DockerUnavailableError(ODMMappingError):
    """Raised when the Docker CLI or selected Docker engine is unavailable."""


def resolve_docker_context(docker_executable: str = "docker") -> Optional[str]:
    """Return the Docker context to use, or None for Docker's current context.

    Order: IRDRONE_DOCKER_CONTEXT if set, then ODM_CONTEXT (Docker Desktop) if
    that context exists, otherwise None.
    """
    if "IRDRONE_DOCKER_CONTEXT" in os.environ:
        return os.environ["IRDRONE_DOCKER_CONTEXT"].strip() or None
    try:
        inspect = subprocess.run(
            [docker_executable, "context", "inspect", ODM_CONTEXT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return ODM_CONTEXT if inspect.returncode == 0 else None


def _context_args(docker_context: Optional[str]) -> List[str]:
    return ["--context", docker_context] if docker_context else []


def check_docker(docker_context: Any = ...) -> Tuple[str, str]:
    """Return the Docker executable and server version, or explain how to start it.

    docker_context: context name, None for Docker's current context, or omitted
    to auto-detect with resolve_docker_context().
    """
    docker_executable = shutil.which("docker")
    if docker_executable is None:
        raise DockerUnavailableError(
            "Docker CLI was not found on PATH. Start or install Docker Desktop, then "
            "verify that `docker version` shows both Client and Server."
        )
    if docker_context is ...:
        docker_context = resolve_docker_context(docker_executable)
    context_label = f"Docker context '{docker_context}'" if docker_context else "Docker engine"

    try:
        docker_check = subprocess.run(
            [
                docker_executable,
                *_context_args(docker_context),
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
            f"Could not contact the {context_label}: {error}. Start Docker "
            "(Docker Desktop or the docker service) and retry."
        ) from error

    server_version = docker_check.stdout.strip()
    if docker_check.returncode != 0 or not server_version:
        details = (docker_check.stderr or docker_check.stdout).strip()
        raise DockerUnavailableError(
            f"{context_label} is not responding. Start Docker (Docker Desktop or "
            "the docker service), wait until the engine is running, then retry."
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
    docker_context: Optional[str] = ODM_CONTEXT,
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
        *_context_args(docker_context),
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


OVERVIEW_FACTORS = (2, 4, 8, 16)


def build_orthophoto_overviews(orthophoto_path: Path) -> None:
    """Give the orthophoto valid DEFLATE overviews for QGIS and other viewers.

    ODM's ``--build-overviews`` compresses them with JPEG, which cannot store the
    16-bit multispectral bands: every overview tile fails to write and stays
    empty, so zoomed-out views are black. Existing overviews are dropped by
    rewriting the raster (same pixels and compression) before building new ones.
    """
    with rasterio.open(orthophoto_path) as dataset:
        has_overviews = bool(dataset.overviews(1))
        profile = dataset.profile
    if has_overviews:
        temporary_path = orthophoto_path.with_name(orthophoto_path.stem + ".rewrite.tif")
        try:
            rasterio.shutil.copy(
                orthophoto_path,
                temporary_path,
                driver="GTiff",
                TILED="YES",
                BLOCKXSIZE=profile.get("blockxsize", 512),
                BLOCKYSIZE=profile.get("blockysize", 512),
                COMPRESS="DEFLATE",
                PREDICTOR=2,
                BIGTIFF="IF_SAFER",
            )
            os.replace(temporary_path, orthophoto_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    with rasterio.Env(COMPRESS_OVERVIEW="DEFLATE", PREDICTOR_OVERVIEW=2):
        with rasterio.open(orthophoto_path, "r+") as dataset:
            dataset.build_overviews(list(OVERVIEW_FACTORS), Resampling.average)
            dataset.update_tags(ns="rio_overview", resampling="average")


def read_orthophoto_preview(
    orthophoto_path: Path,
    max_dimension: int = 1600,
) -> np.ndarray:
    """Read and contrast-stretch a small RGB preview without loading the full raster."""
    if max_dimension < 1:
        raise ValueError("Preview maximum dimension must be positive.")

    try:
        # ODM's internal overviews can be empty (all zeros), and a decimated read
        # would be served from them, so read and average the full-resolution data.
        with rasterio.open(orthophoto_path, OVERVIEW_LEVEL="NONE") as dataset:
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
            alpha_indexes = [
                index
                for index, interpretation in enumerate(dataset.colorinterp, start=1)
                if getattr(interpretation, "name", "") == "alpha"
            ]
            if alpha_indexes:
                alpha = dataset.read(
                    alpha_indexes[0],
                    out_shape=(preview_height, preview_width),
                    resampling=Resampling.nearest,
                )
                rgb_bands = np.ma.masked_where(
                    np.broadcast_to(alpha == 0, rgb_bands.shape)
                    | np.ma.getmaskarray(rgb_bands),
                    rgb_bands,
                )
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
                    normalized = np.where(
                        valid, np.clip((band - low) / (high - low), 0, 1), 0
                    )
                    preview[:, :, channel] = np.rint(normalized * 255).astype(np.uint8)
            return preview
    except rasterio.errors.RasterioError as error:
        raise ODMMappingError(
            f"Could not read orthophoto preview {orthophoto_path}: {error}"
        ) from error


def _vis_metadata_by_name(shoot_points_path: Path) -> Dict[str, Dict[str, Any]]:
    """VIS metadata (position, height, yaw) of the Step 3 pairs, by file name ({} if unreadable)."""
    try:
        data = _load_json(shoot_points_path)
    except ODMMappingError:
        return {}
    points = data.get("shoot_points") if isinstance(data, dict) else None
    out = {}
    for point in points if isinstance(points, list) else []:
        vis = point.get("VIS") if isinstance(point, dict) else None
        if isinstance(vis, dict) and isinstance(vis.get("FileName"), str):
            out[Path(vis["FileName"]).name.casefold()] = vis
    return out


def select_mapping_pairs(
    mission_folder: Path,
    dt_tolerance_s: float = 0.5,
    sample_every: int = 3,
    overlap: Optional[float] = None,
) -> Dict[str, Any]:
    """The image selection of Step 5, nothing written: the eligible pairs
    (rank-one |dt| within the tolerance, anywhere in the flight, not flagged
    failed) thinned by ``overlap`` or one every ``sample_every``.

    Returns {"sampled_pairs", "counters", "shoot_points_path"}; each pair is
    (shoot point index, VIS, NIR match, dt)."""
    mission_folder = Path(mission_folder)
    aerial_photography = mission_folder / "AerialPhotography"
    status_shoot_points_path = mission_folder / "ImgIRdrone" / "shoot_points.json"
    shoot_points_path = (
        status_shoot_points_path
        if status_shoot_points_path.is_file()
        else aerial_photography / "shoot_points.json"
    )
    shoot_points_data = _load_json(shoot_points_path)
    if not isinstance(shoot_points_data, dict) or not isinstance(
        shoot_points_data.get("shoot_points"), list
    ):
        raise ODMMappingError(f"{shoot_points_path} must contain a 'shoot_points' list.")
    eligible_pairs: List[Tuple[int, Dict[str, Any], Dict[str, Any], float]] = []
    counters = {
        "rank_one_pairs": 0,
        "rank_one_pairs_with_valid_dt": 0,
        "rank_one_pairs_within_dt_tolerance": 0,
    }

    requested_pairs: List[Tuple[int, Dict[str, Any], Dict[str, Any], float]] = []
    source_shoot_points = shoot_points_data["shoot_points"]
    if shoot_points_path == status_shoot_points_path:
        normalized_points = []
        for shoot_point_index, shoot_point in enumerate(source_shoot_points):
            if not isinstance(shoot_point, dict):
                continue
            failed = shoot_point.get("failed", False)
            if isinstance(failed, bool):
                is_failed = failed
            elif isinstance(failed, int) and failed in (0, 1):
                is_failed = bool(failed)
            else:
                raise ODMMappingError(
                    f"Shoot point {shoot_point_index} has an invalid 'failed' status."
                )
            if is_failed:
                continue
            vis_filename = shoot_point.get("FileName")
            dt = shoot_point.get("dt")
            if not isinstance(vis_filename, str):
                raise ODMMappingError(
                    f"Shoot point {shoot_point_index} has no valid 'FileName'."
                )
            normalized_points.append(
                {
                    "VIS": {"FileName": vis_filename},
                    "NIR": [{"rank": 1, "dt": dt}],
                    "on_request": shoot_point.get("aligned_on_request") is True,
                }
            )
        source_shoot_points = normalized_points

    for shoot_point_index, shoot_point in enumerate(source_shoot_points):
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
            pair = (shoot_point_index, vis_data, nir_match, float(dt))
            if shoot_point.get("on_request"):
                requested_pairs.append(pair)     # aligned from the review: kept whatever the rules
            absolute_dt = abs(float(dt))
            if absolute_dt > dt_tolerance_s:
                continue
            counters["rank_one_pairs_within_dt_tolerance"] += 1
            eligible_pairs.append(pair)

    if overlap is None:
        sampled_pairs = eligible_pairs[::sample_every]
    else:
        vis_metadata = _vis_metadata_by_name(aerial_photography / "shoot_points.json")
        shots = [
            best_mapping.shot_from_vis(
                index,
                vis_metadata.get(Path(str(vis_data["FileName"])).name.casefold(), vis_data),
            )
            for index, (_, vis_data, _, _) in enumerate(eligible_pairs)
        ]
        kept = best_mapping.select(shots, float(overlap), best_mapping.mission_fov(mission_folder))
        sampled_pairs = [eligible_pairs[index] for index in kept]
    if requested_pairs:
        counters["aligned_on_request"] = len(requested_pairs)
        sampled = {pair[0] for pair in sampled_pairs}
        sampled_pairs = sorted(sampled_pairs + [pair for pair in requested_pairs if pair[0] not in sampled],
                               key=lambda pair: pair[0])
    return {
        "sampled_pairs": sampled_pairs,
        "counters": counters,
        "shoot_points_path": shoot_points_path,
    }


def selection_settings(mission_folder: Path) -> Dict[str, Any]:
    """Settings of the image selection the Step 5 window proposes:
    {"dt_tolerance_s", "sample_every", "overlap" (None: one image every n)}.

    Those of the last run (selection_rules of img_best_mappping.json), else
    |dt| <= 0.5 s and one image in 3; the best mapping (on/off and overlap) of
    Steps 2 and 4 when it was chosen after the last run, or without one."""
    mission_folder = Path(mission_folder)
    choice = best_mapping.load_choice(mission_folder)
    settings = {"dt_tolerance_s": 0.5, "sample_every": 3,
                "overlap": choice["overlap"] if choice["enabled"] else None}
    manifest_path = mission_folder / ODM_PROJECT_NAME / MANIFEST_NAME
    try:
        rules = _load_json(manifest_path).get("selection_rules")
    except (ODMMappingError, AttributeError):
        rules = None
    if not isinstance(rules, dict):
        return settings
    dt = rules.get("maximum_absolute_dt_seconds")
    if isinstance(dt, (int, float)) and not isinstance(dt, bool) and 0.05 <= dt <= 6.0:
        settings["dt_tolerance_s"] = float(dt)
    every = rules.get("sample_every_nth_eligible_pair")
    if isinstance(every, int) and not isinstance(every, bool) and every in (1, 2, 3, 4):
        settings["sample_every"] = every
    try:
        choice_newer = ((mission_folder / best_mapping.CHOICE_FILE).stat().st_mtime
                        > manifest_path.stat().st_mtime)
    except OSError:
        choice_newer = False
    if not choice_newer:
        overlap = rules.get("footprint_overlap")
        if rules.get("selection") == "overlap" and isinstance(overlap, (int, float)):
            settings["overlap"] = best_mapping.clamp_overlap(overlap)
        elif rules.get("selection") == "sample_every":
            settings["overlap"] = None
    return settings


def planned_mapping_numbers(mission_folder: Path) -> Set[int]:
    """Numbers of the visible images the next run of Step 5 will map with the
    settings its window proposes (`selection_settings`); empty when it cannot
    be known (before Step 4)."""
    mission_folder = Path(mission_folder)
    if not (mission_folder / "ImgIRdrone" / "shoot_points.json").is_file():
        return set()
    try:
        selection = select_mapping_pairs(mission_folder, **selection_settings(mission_folder))
    except ODMMappingError:
        return set()
    out = set()
    for _, vis_data, _, _ in selection["sampled_pairs"]:
        m = VIS_FILENAME_PATTERN.match(Path(str(vis_data["FileName"])).name)
        if m:
            out.add(int(m.group(1)))
    return out


def build_best_mapping(
    mission_folder: Path,
    dt_tolerance_s: float = 0.5,
    sample_every: int = 3,
    overlap: Optional[float] = None,
) -> Dict[str, Any]:
    """Build and save the selected shoot points and their matching TIFF quartets.

    The eligible pairs (rank-one |dt| within the tolerance, anywhere in the flight, not
    flagged failed) are thinned either by ``overlap`` (best mapping: footprint
    overlap between successive images, 0.5 to 0.95) or, when ``overlap`` is None,
    by keeping one pair every ``sample_every``."""
    mission_folder = Path(mission_folder).expanduser().resolve()
    if not mission_folder.is_dir():
        raise ODMMappingError(f"Mission folder does not exist: {mission_folder}")
    if (
        isinstance(dt_tolerance_s, bool)
        or not isinstance(dt_tolerance_s, (int, float))
        or not math.isfinite(dt_tolerance_s)
        or not 0.05 <= dt_tolerance_s <= 6.0
    ):
        raise ODMMappingError(
            "The maximum time difference must be between 0.05 and 6.0 seconds."
        )
    if (
        isinstance(sample_every, bool)
        or not isinstance(sample_every, int)
        or sample_every not in (1, 2, 3, 4)
    ):
        raise ODMMappingError("The image sampling interval must be 1, 2, 3, or 4.")
    if overlap is not None and (
        isinstance(overlap, bool)
        or not isinstance(overlap, (int, float))
        or not best_mapping.MIN_OVERLAP <= overlap <= best_mapping.MAX_OVERLAP
    ):
        raise ODMMappingError(
            f"The image overlap must be between {best_mapping.MIN_OVERLAP:.2f} and "
            f"{best_mapping.MAX_OVERLAP:.2f}."
        )

    selection = select_mapping_pairs(mission_folder, dt_tolerance_s, sample_every, overlap)
    sampled_pairs = selection["sampled_pairs"]
    counters = selection["counters"]
    shoot_points_path = selection["shoot_points_path"]
    mapping_folder = mission_folder / "mapping_MULTI"
    images_folder = mission_folder / "ImgIRdrone" / "imgMultispectral"
    camera_path = mapping_folder / "camera" / "camera_IRdrone.json"
    camera_data = _load_json(camera_path)
    if not isinstance(camera_data, dict) or not camera_data:
        raise ODMMappingError(f"{camera_path} must contain a non-empty camera configuration object.")
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
            "selection": "overlap" if overlap is not None else "sample_every",
            "sample_every_nth_eligible_pair": sample_every if overlap is None else None,
            "footprint_overlap": overlap,
            "sample_offset": 0,
            "band_order": list(BAND_NAMES),
        },
        "source_files": {
            "shoot_points": str(shoot_points_path),
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


def _link_or_copy(source: Path, target: Path, copy_mode: bool) -> bool:
    """Hard-link ``source`` to ``target``, or copy it when hard links are not
    supported (exFAT / FAT32 external drives, some network shares).

    Returns True once copying, so the next files are copied directly.
    """
    if not copy_mode:
        try:
            os.link(source, target)
            return False
        except OSError as error:
            if is_disk_full(error):
                raise
            # Any other refusal (unsupported, cross-device, permission):
            # a copy works on every storage, at the cost of disk space.
    shutil.copy2(source, target)
    return True


def _same_file_content(existing: Path, source: Path) -> bool:
    """A hard link to ``source``, or an identical copy of it."""
    if os.path.samefile(existing, source):
        return True
    return filecmp.cmp(existing, source, shallow=True)


def prepare_odm_input(
    mission_folder: Path,
    manifest: Dict[str, Any],
    log: Callable[[str], None] = print,
) -> Path:
    """Hard-link the selected TIFFs and sidecars into ODM's images folder.

    Falls back to copies when the storage does not support hard links.
    """
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
            outdated = [
                source.name
                for name, source in expected_by_name.items()
                if not _same_file_content(actual_by_name[name], source)
            ]
            if outdated:
                raise ODMMappingError(
                    "The existing ODM input contains files that differ from the selected "
                    f"sources: {', '.join(outdated)}. Remove its contents manually before "
                    "preparing the input again."
                )
            return images_folder

    if images_folder_created:
        images_folder.mkdir(parents=True)
    created_files: List[Path] = []
    copy_mode = False
    target: Optional[Path] = None
    try:
        for filename, source in expected_images:
            target = images_folder / filename
            if _link_or_copy(source, target, copy_mode) and not copy_mode:
                copy_mode = True
                log(
                    "This storage does not support hard links: the selected images "
                    "are copied into the ODM input folder (uses more disk space)."
                )
            created_files.append(target)
    except OSError as error:
        for created_file in created_files + ([target] if target else []):
            created_file.unlink(missing_ok=True)
        if images_folder_created and not any(images_folder.iterdir()):
            images_folder.rmdir()
        raise_if_disk_full(error, images_folder)
        raise ODMMappingError(
            f"Could not prepare the ODM input folder: {error}"
        ) from error

    return images_folder


def previous_mapping_details(mapping_folder: Path) -> List[str]:
    """What a previous run left in the mapping folder (empty: nothing)."""
    if not Path(mapping_folder).is_dir():
        return []
    existing_odm_outputs = [
        path.name
        for path in Path(mapping_folder).iterdir()
        if path.is_dir()
        and (
            path.name.casefold().startswith("odm_")
            or path.name.casefold() in {"opensfm", "openmvs", "stats", "entwine"}
        )
    ]
    result_folder = Path(mapping_folder) / ODM_RESULTS_FOLDER
    existing_archives = [path.name for path in result_folder.iterdir()] if result_folder.is_dir() else []
    details = []
    if existing_odm_outputs:
        details.append(f"ODM outputs: {', '.join(existing_odm_outputs)}")
    if existing_archives:
        details.append(f"archived results: {', '.join(existing_archives)}")
    return details


def _unique_folder(path: Path) -> Path:
    candidate, k = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}_{k}")
        k += 1
    return candidate


def _run_stamp(mapping_folder: Path) -> str:
    """Date of the run that built a mapping folder (its manifest), else of the folder."""
    try:
        created = _load_json(mapping_folder / MANIFEST_NAME).get("created_at_utc")
        return datetime.fromisoformat(created).astimezone().strftime("%Y%m%d_%H%M%S")
    except (ODMMappingError, AttributeError, TypeError, ValueError):
        return datetime.fromtimestamp(mapping_folder.stat().st_mtime).strftime("%Y%m%d_%H%M%S")


def set_previous_mapping_aside(mission_folder: Path) -> Optional[Path]:
    """A map already built: its folder renamed mapping_MULTI_<date of its run>
    (nothing deleted), a new mapping_MULTI with the same camera configuration.
    Returns the renamed folder, None when there was nothing to keep."""
    mapping_folder = Path(mission_folder) / ODM_PROJECT_NAME
    if not previous_mapping_details(mapping_folder):
        return None
    previous = _unique_folder(mapping_folder.with_name(f"{ODM_PROJECT_NAME}_{_run_stamp(mapping_folder)}"))
    mapping_folder.rename(previous)
    mapping_folder.mkdir()
    if (previous / "camera").is_dir():
        shutil.copytree(previous / "camera", mapping_folder / "camera")
    return previous


def _put_previous_mapping_back(mission_folder: Path, previous: Path) -> Optional[Path]:
    """The new run failed: its folder kept as mapping_MULTI_failed_<now> (removed
    when the run wrote nothing), the previous map back in mapping_MULTI.
    Returns the failed run's folder (None: removed)."""
    mapping_folder = Path(mission_folder) / ODM_PROJECT_NAME
    failed = _unique_folder(mapping_folder.with_name(
        f"{ODM_PROJECT_NAME}_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
    mapping_folder.rename(failed)
    previous.rename(mapping_folder)
    if all(path.name == "camera" for path in failed.iterdir()):     # nothing done (Docker off…)
        shutil.rmtree(failed)
        return None
    return failed


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


SHOT_MARKER_COLOR = "255,0,0,255"
SHOT_MARKER_SIZE_MM = 3.0
SHOT_LABEL_COLOR = "0,0,0,255"
SHOT_LABEL_SIZE_PT = 9.0
SHOT_IMAGE_PATTERN = re.compile(r"^IRD_(\d+)_\d+\.", re.IGNORECASE)

SHOTS_QGIS_STYLE = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology|Labeling">
  <renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0">
    <symbols>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleMarker" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option name="name" value="circle" type="QString"/>
            <Option name="color" value="{marker_color}" type="QString"/>
            <Option name="outline_color" value="0,0,0,255" type="QString"/>
            <Option name="outline_width" value="0.2" type="QString"/>
            <Option name="size" value="{marker_size}" type="QString"/>
            <Option name="size_unit" value="MM" type="QString"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="shot" isExpression="0" fontSize="{label_size}" fontSizeUnit="Point" textColor="{label_color}" fontFamily="Arial" namedStyle="Bold" fontWeight="75" textOpacity="1">
        <text-buffer bufferDraw="1" bufferSize="0.8" bufferSizeUnits="MM" bufferColor="255,255,255,255" bufferOpacity="1"/>
      </text-style>
      <placement placement="6" dist="1.5" distUnits="MM" overlapHandling="PreventOverlap"/>
      <rendering scaleVisibility="0" drawLabels="1"/>
    </settings>
  </labeling>
</qgis>
"""


def style_shots_geojson(shots_path: Path) -> None:
    """Add the shoot point number and style hints to the archived ODM shots.geojson.

    Each feature gets a `shot` property (IRD_0128_1.tif -> 128) plus simplestyle
    properties for generic GeoJSON viewers. QGIS ignores those, so a `shots.qml` sidecar
    (loaded automatically next to the layer) sets the markers and the `shot` labels.
    The original ODM properties, `filename` included, are kept.
    """
    shots_path = Path(shots_path)
    with shots_path.open("r", encoding="utf-8") as shots_file:
        data = json.load(shots_file)
    for feature in data.get("features", []):
        properties = feature.setdefault("properties", {})
        match = SHOT_IMAGE_PATTERN.match(str(properties.get("filename", "")))
        if match is not None:
            properties["shot"] = int(match.group(1))
        properties.update(
            {
                "marker-symbol": "circle",
                "marker-color": "#ff0000",
                "marker-size": "medium",
            }
        )
    _write_json_atomic(shots_path, data)
    shots_path.with_suffix(".qml").write_text(
        SHOTS_QGIS_STYLE.format(
            marker_color=SHOT_MARKER_COLOR,
            marker_size=SHOT_MARKER_SIZE_MM,
            label_color=SHOT_LABEL_COLOR,
            label_size=SHOT_LABEL_SIZE_PT,
        ),
        encoding="utf-8",
    )


def _restore_output_ownership(
    mapping_folder: Path,
    docker_executable: str,
    docker_context: Optional[str],
    log: Callable[[str], None],
) -> None:
    """Give ODM outputs back to the current user on Linux/macOS.

    With a rootful Docker engine, the ODM container writes files as root, which
    the user can then neither clean up nor delete. Nothing is done on Windows or
    when the files are already owned by the user (Docker Desktop, rootless Docker).
    """
    if not hasattr(os, "getuid"):
        return
    uid, gid = os.getuid(), os.getgid()
    if all(path.lstat().st_uid == uid for path in mapping_folder.rglob("*")):
        return
    command = [
        docker_executable,
        *_context_args(docker_context),
        "run",
        "--rm",
        "--entrypoint",
        "chown",
        "-v",
        f"{mapping_folder.parent}:/datasets",
        ODM_IMAGE,
        "-R",
        f"{uid}:{gid}",
        f"/datasets/{mapping_folder.name}",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, check=False,
    )
    if result.returncode != 0:
        log(
            "Could not give ODM outputs back to the current user: "
            + (result.stderr or result.stdout).strip()
        )


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
    dt_tolerance_s: float = 0.5,
    sample_every: int = 3,
    overlap: Optional[float] = None,
) -> Dict[str, Any]:
    """Prepare the selected dataset and run ODM through Docker."""
    mission_folder = Path(mission_folder).expanduser().resolve()
    mapping_folder = mission_folder / "mapping_MULTI"
    manifest_path = mapping_folder / MANIFEST_NAME
    worker_log = log_callback or (lambda _message: None)
    stage = stage_callback or (lambda _message: None)

    if not mapping_folder.is_dir():
        raise ODMMappingError(f"ODM mapping folder does not exist: {mapping_folder}")
    previous = set_previous_mapping_aside(mission_folder)
    if previous is not None:
        worker_log(f"The previous map is kept in {previous}; a new one is built in {mapping_folder}.")
    try:
        return _run_odm_in(mission_folder, mapping_folder, manifest_path, worker_log, stage,
                           dt_tolerance_s, sample_every, overlap)
    except BaseException:
        if previous is not None:
            try:
                failed = _put_previous_mapping_back(mission_folder, previous)
                worker_log(f"The new map failed: the previous one is back in {mapping_folder}"
                           + (f" (the failed run, with its log, is in {failed})." if failed else "."))
            except OSError as error:
                worker_log(f"The previous map could not be put back ({error}): it is in {previous}.")
        raise


def _run_odm_in(mission_folder, mapping_folder, manifest_path, worker_log, stage,
                dt_tolerance_s, sample_every, overlap) -> Dict[str, Any]:
    """run_odm in an empty mapping folder."""
    _check_mapping_outputs_available(mapping_folder)

    stage("Checking Docker")
    docker_context = resolve_docker_context(shutil.which("docker") or "docker")
    docker_executable, docker_server_version = check_docker(docker_context)
    worker_log(f"Docker Engine {docker_server_version} is available.")

    stage("Building image selection and estimating GSD")
    manifest = build_best_mapping(
        mission_folder,
        dt_tolerance_s=dt_tolerance_s,
        sample_every=sample_every,
        overlap=overlap,
    )
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
    images_folder = prepare_odm_input(mission_folder, manifest, log=worker_log)
    command = build_odm_command(
        mapping_folder, resolution_cm, docker_executable, docker_context
    )
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
                    clean_line = ANSI_ESCAPE_PATTERN.sub("", line).strip()
                    if not ODM_LOGO_LINE_PATTERN.match(clean_line):
                        worker_log(clean_line)
            return_code = process.wait()
            elapsed_seconds = time.perf_counter() - run_started_monotonic
        _restore_output_ownership(
            mapping_folder, docker_executable, docker_context, worker_log
        )
        if return_code != 0:
            raise ODMMappingError(
                f"ODM exited with code {return_code}. Review the complete log: {log_path}"
            )
        stage("Validating ODM orthophoto")
        output = _validate_odm_outputs(orthophoto_path)
        stage("Archiving selected ODM results")
        copied_results = _copy_mapping_results(mapping_folder)
        try:
            style_shots_geojson(Path(copied_results["shots"]))
        except (OSError, ValueError) as error:
            worker_log(f"Could not add shoot point labels and style to shots.geojson: {error}")
        output["path"] = copied_results["orthophoto"]
        stage("Building orthophoto overviews")
        try:
            build_orthophoto_overviews(Path(copied_results["orthophoto"]))
        except (OSError, rasterio.errors.RasterioError) as error:
            worker_log(f"Could not build the orthophoto overviews: {error}")
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
