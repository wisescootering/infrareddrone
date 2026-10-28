import argparse
import math
from pathlib import Path
import re
import json
import subprocess
import time
from utils.utils_IRdrone_Class import ShootPoint
import automatic_registration
from utils.utils_odm import create_odm_folder, odm_mapping_optim
from config import CROP, EXIFTOOLPATH


GEOREF_METADATA_KEYS = (
    "DroneLatitude",
    "DroneLongitude",
    "GroundAltitude",
    "DroneAltitudeSeaLevel",
    "DroneAltitudeGround",
    "UTM_x",
    "UTM_y",
    "UTM_zone",
    "FlightYawDegree",
    "FlightPitchDegree",
    "FlightRollDegree",
    "GimbalYawDegree",
    "GimbalPitchDegree",
    "GimbalRollDegree",
)
VIS_FILENAME_PATTERN = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)


def build_output_traces(include_nir: bool = False, include_ndvi: bool = False) -> list[str]:
    """Return the requested output traces, with VIS and VIR as the defaults."""
    traces = ["vis", "vir"]
    if include_nir:
        traces.append("nir")
    if include_ndvi:
        traces.append("ndvi")
    return traces


def filter_shoot_points_by_image_number(
    shoot_points: list[dict],
    start_image_number: int = None,
    end_image_number: int = None,
) -> list[dict]:
    """Keep shoot points whose VIS filename number is inside the inclusive range."""
    if start_image_number is not None and start_image_number < 1:
        raise ValueError("The first VIS image number must be at least 1.")
    if end_image_number is not None and end_image_number < 1:
        raise ValueError("The last VIS image number must be at least 1.")
    if (
        start_image_number is not None
        and end_image_number is not None
        and start_image_number > end_image_number
    ):
        raise ValueError("The last VIS image number must not precede the first.")

    filtered_points = []
    for point in shoot_points:
        vis_data = point.get("VIS")
        filename = vis_data.get("FileName") if isinstance(vis_data, dict) else None
        match = (
            VIS_FILENAME_PATTERN.fullmatch(Path(filename).name)
            if isinstance(filename, str)
            else None
        )
        if match is None:
            raise ValueError(f"Unexpected visible image filename: {filename!r}")
        image_number = int(match.group(1))
        if start_image_number is not None and image_number < start_image_number:
            continue
        if end_image_number is not None and image_number > end_image_number:
            continue
        filtered_points.append(point)
    return filtered_points


def filter_shoot_points_by_time_difference(
    shoot_points: list[dict], max_time_difference_s: float
) -> list[dict]:
    """Keep shoot points whose rank-one VIS/NIR time difference is below the limit."""
    if (
        not math.isfinite(max_time_difference_s)
        or not 0.1 <= max_time_difference_s <= 6.0
    ):
        raise ValueError("Maximum time difference must be between 0.1 and 6.0 seconds.")

    filtered_points = []
    for point in shoot_points:
        nir_matches = point.get("NIR", [])
        nir_data = next(
            (
                nir
                for nir in nir_matches
                if isinstance(nir, dict) and nir.get("rank") == 1
            ),
            None,
        )
        if nir_data is None:
            continue

        vis_filename = point.get("VIS", {}).get("FileName", "<unknown>")
        try:
            raw_time_difference = nir_data["dt"]
            if isinstance(raw_time_difference, bool):
                raise TypeError("Boolean time difference is invalid.")
            time_difference = float(raw_time_difference)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid rank-1 time difference for {vis_filename}."
            ) from error
        if not math.isfinite(time_difference):
            raise ValueError(
                f"Invalid rank-1 time difference for {vis_filename}: "
                f"{time_difference}."
            )
        if abs(time_difference) < max_time_difference_s:
            filtered_points.append(point)

    return filtered_points


def write_multispectral_exif(image_path: Path, vis_data: dict) -> Path:
    """Write the Phase 5 companion metadata beside a multispectral band TIFF."""
    result = subprocess.run(
        [str(EXIFTOOLPATH), "-json", str(image_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ExifTool could not read metadata from {image_path}: "
            f"{result.stderr.strip()}"
        )

    metadata_list = json.loads(result.stdout)
    if not metadata_list or not isinstance(metadata_list[0], dict):
        raise ValueError(f"ExifTool returned no image metadata for {image_path}")

    metadata = metadata_list[0]
    metadata["FileName"] = image_path.name
    metadata["Directory"] = str(image_path.parent)
    for key in GEOREF_METADATA_KEYS:
        if key in vis_data:
            metadata[key] = vis_data[key]

    required_keys = {
        "FOV",
        "DroneLatitude",
        "DroneLongitude",
        "GroundAltitude",
        "DroneAltitudeSeaLevel",
        "DroneAltitudeGround",
        "UTM_x",
        "UTM_y",
        "UTM_zone",
        "FlightYawDegree",
        "FlightPitchDegree",
        "FlightRollDegree",
    }
    missing_keys = required_keys.difference(metadata)
    if missing_keys:
        raise ValueError(
            f"Cannot create georeferencing metadata for {image_path}; "
            f"missing fields: {', '.join(sorted(missing_keys))}"
        )

    exif_path = image_path.with_suffix(".exif")
    exif_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return exif_path


def run_postprocessing(
    preprocessed_folder: Path,
    start_image_number: int = None,
    end_image_number: int = None,
    include_ndvi: bool = False,
    include_nir: bool = False,
    alignment_modes: tuple[str, ...] = ("local",),
    max_time_difference_s: float = 0.5,
    progress_callback=None,
):
    json_file = preprocessed_folder / "AerialPhotography" / "shoot_points.json"
    assert json_file.exists(), f"JSON file does not exist: {json_file}"
    with open(json_file, "r") as f:
        shoot_points = json.load(f)
    paired_points = shoot_points["shoot_points"]
    paired_points = filter_shoot_points_by_image_number(
        paired_points, start_image_number, end_image_number
    )
    selected_point_count = len(paired_points)
    paired_points = filter_shoot_points_by_time_difference(
        paired_points, max_time_difference_s
    )
    print(
        f"Temporal filter: retained {len(paired_points)} of {selected_point_count} "
        f"shoot points (|VIS/NIR rank-1 time difference| < "
        f"{max_time_difference_s:.1f} s)."
    )
    if not paired_points:
        raise ValueError(
            "No shoot points satisfy the selected maximum VIS/NIR time difference."
        )
    if progress_callback is not None:
        progress_callback(0, len(paired_points), "")
    shoot_point_list = []

    for point in paired_points:
        vis_data = point["VIS"]
        nir_data = next((nir for nir in point["NIR"] if nir["rank"] == 1), None)

        # Enhanced initialization of ShootPoint to include more metadata
        if nir_data:
            shoot_point = ShootPoint(
                numero=vis_data["idx"],
                nameVis=vis_data["FileName"],
                nameNir=nir_data["FileName"],
                visDate=vis_data["DateTimeOriginal"],
                nirDate=nir_data["DateTimeOriginal"],
                timeLine=vis_data["RelativeTimeLine"],
                timeDeviation=nir_data["dt"],
            )

            # Populate additional attributes
            shoot_point.gpsLat = vis_data.get("DroneLatitude", 0.0)
            shoot_point.gpsLon = vis_data.get("DroneLongitude", 0.0)
            shoot_point.altGround = vis_data.get("GroundAltitude", 0.0)
            shoot_point.altGeo = vis_data.get("DroneAltitudeSeaLevel", 0.0)
            shoot_point.altTakeOff = vis_data.get("DroneAltitudeGround", 0.0)
            shoot_point.yawDrone = float(
                str(vis_data.get("FlightYawDegree", 0.0)).replace("+", "")
            )
            shoot_point.pitchDrone = vis_data.get("FlightPitchDegree", 0.0)
            shoot_point.rollDrone = float(
                str(vis_data.get("FlightRollDegree", "0")).replace("+", "")
            )

            # Correctly set VisDirectory and NirDirectory for ShootPoint
            shoot_point.VisDirectory = vis_data["Directory"]
            shoot_point.NirDirectory = nir_data["Directory"]

            # Update keys in ShootPoint to match the expected structure
            shoot_point.gpsUTM_X = vis_data.get("UTM_x", 0.0)
            shoot_point.gpsUTM_Y = vis_data.get("UTM_y", 0.0)
            shoot_point.gpsUTM_Zone = vis_data.get("UTM_zone", 0)
            shoot_point.bestSynchro = nir_data.get("BestSynchro", 0)
            shoot_point.bestMapping = nir_data.get("BestMapping", 0)

            shoot_point_list.append(shoot_point)

    print(f"Generated {len(shoot_point_list)} ShootPoint objects.")

    # Dynamically derive paths from paired_points
    matched_paths = [
        (
            Path(point["VIS"]["Directory"]) / point["VIS"]["FileName"],
            Path(nir["Directory"]) / nir["FileName"],
        )
        for point in paired_points
        for nir in point["NIR"]
        if nir["rank"] == 1
    ]
    redo_nir_candidates = [
        [
            (
                Path(nir["Directory"]) / nir["FileName"],
                nir["rank"],
            )
            for nir in sorted(
                (
                    candidate
                    for candidate in point["NIR"]
                    if isinstance(candidate, dict)
                    and isinstance(candidate.get("rank"), (int, float))
                    and not isinstance(candidate.get("rank"), bool)
                    and isinstance(candidate.get("FileName"), str)
                    and isinstance(candidate.get("Directory"), str)
                ),
                key=lambda candidate: candidate["rank"],
            )
        ]
        for point in paired_points
    ]
    # Define required variables
    out_dir = preprocessed_folder / "ImgIRdrone"
    traces = build_output_traces(include_nir, include_ndvi)
    skip = False
    # Call automatic_registration.process_raw_pairs
    create_odm_folder(
        preprocessed_folder,
        multispectral_modality="MULTI",
        extra_options=["--skip-band-alignment"],
        create_images_directory=False,
    )
    multispectral_folder = out_dir / "imgMultispectral"
    multispectral_folder.mkdir(parents=True, exist_ok=True)
    paired_points_by_filename = {
        point["VIS"]["FileName"]: point for point in paired_points
    }

    def on_image_processed(current: int, total: int, vis_filename: str) -> None:
        try:
            point = paired_points_by_filename[vis_filename]
        except KeyError as error:
            raise ValueError(
                f"Progress callback returned an unknown VIS image: {vis_filename}"
            ) from error
        vis_data = point["VIS"]
        image_number = Path(vis_filename).stem.removeprefix("VIS_")
        band_one = multispectral_folder / f"IRD_{image_number}_1.tif"
        if not band_one.is_file():
            raise FileNotFoundError(
                f"Expected multispectral band TIFF was not created: {band_one}"
            )
        sidecar = write_multispectral_exif(band_one, vis_data)
        print(f"Wrote georeferencing metadata: {sidecar}")
        if progress_callback is not None:
            progress_callback(current, total, vis_filename)

    automatic_registration.process_raw_pairs(
        matched_paths,
        out_dir=out_dir,
        crop=CROP,
        listPts=shoot_point_list,
        option_alti="sealevel",  # Example altitude option
        clean_proxy=False,  # Example clean_proxy value
        multispectral_folder=multispectral_folder,
        traces=traces,
        alignment_modes=alignment_modes,
        redo_nir_candidates=redo_nir_candidates,
        skip=skip,
        progress_callback=on_image_processed,
        max_workers=automatic_registration.available_alignment_workers(),
        # debug=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run post-processing after preprocessing."
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="preprocessed_folder",
        required=True,
        help="Path to the folder containing preprocessed data.",
    )
    parser.add_argument(
        "--start-image-number",
        dest="start_image_number",
        type=int,
        default=None,
        help="First VIS image number to process (inclusive).",
    )
    parser.add_argument(
        "--end-image-number",
        dest="end_image_number",
        type=int,
        default=None,
        help="Last VIS image number to process (inclusive).",
    )
    parser.add_argument(
        "--ndvi",
        action="store_true",
        help="Generate NDVI images in addition to the default image traces.",
    )
    parser.add_argument(
        "--nir",
        action="store_true",
        help="Generate NIR JPEG images in addition to the default VIS and VIR traces.",
    )
    parser.add_argument(
        "--alignment-modes",
        nargs="+",
        choices=("local", "global"),
        default=("local",),
        help="Alignment modes for generated NIR, VIR, and NDVI images.",
    )
    parser.add_argument(
        "--max-time-difference",
        dest="max_time_difference_s",
        type=float,
        default=0.5,
        help="Maximum absolute VIS/NIR rank-1 time difference in seconds (0.1 to 6.0).",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Emit machine-readable progress updates for the interactive UI.",
    )
    args = parser.parse_args()

    progress_started_at = time.monotonic()

    def report_progress(current: int, total: int, vis_filename: str) -> None:
        elapsed = time.monotonic() - progress_started_at
        worker_count = min(
            automatic_registration.available_alignment_workers(), total
        )
        eta = -1.0
        if current == total:
            eta = 0.0
        elif current > 0 and current % worker_count == 0:
            eta = elapsed * (total - current) / current
        print(
            f"STEP4_PROGRESS {current} {total} {vis_filename or '-'} "
            f"{elapsed:.1f} {eta:.1f}".rstrip(),
            flush=True,
        )

    preprocessed_folder = Path(args.preprocessed_folder)
    assert (
        preprocessed_folder.exists()
    ), f"Mission folder does not exist: {preprocessed_folder}"

    run_postprocessing(
        preprocessed_folder,
        start_image_number=args.start_image_number,
        end_image_number=args.end_image_number,
        include_ndvi=args.ndvi,
        include_nir=args.nir,
        alignment_modes=tuple(args.alignment_modes),
        max_time_difference_s=args.max_time_difference_s,
        progress_callback=report_progress if args.progress else None,
    )
