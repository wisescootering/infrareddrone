import argparse
from pathlib import Path
import json
import subprocess
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
    preprocessed_folder: Path, start_index: int = 0, end_index: int = None
):
    json_file = preprocessed_folder / "AerialPhotography" / "shoot_points.json"
    assert json_file.exists(), f"JSON file does not exist: {json_file}"
    with open(json_file, "r") as f:
        shoot_points = json.load(f)
    paired_points = shoot_points["shoot_points"]
    if end_index is None:
        end_index = len(paired_points)
    paired_points = paired_points[start_index : min(end_index, len(paired_points))]
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
    # Define required variables
    out_dir = preprocessed_folder / "ImgIRdrone"
    traces = ["vir"]
    skip = False
    # Call automatic_registration.process_raw_pairs
    odm_image_directory = create_odm_folder(
        preprocessed_folder,
        multispectral_modality="MULTI",
        extra_options=["--skip-band-alignment"],
    )
    automatic_registration.process_raw_pairs(
        matched_paths,
        out_dir=out_dir,
        crop=CROP,
        listPts=shoot_point_list,
        option_alti="sealevel",  # Example altitude option
        clean_proxy=False,  # Example clean_proxy value
        multispectral_folder=odm_image_directory,  # Example multispectral folder
        traces=traces,
        skip=skip,
        # debug=True
    )

    for point in paired_points:
        vis_data = point["VIS"]
        band_one = odm_image_directory / f"{Path(vis_data['FileName']).stem}_1.tif"
        if not band_one.is_file():
            raise FileNotFoundError(
                f"Expected multispectral band TIFF was not created: {band_one}"
            )
        sidecar = write_multispectral_exif(band_one, vis_data)
        print(f"Wrote georeferencing metadata: {sidecar}")


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
        "--start", dest="start_index", type=int, default=0, help="Start index."
    )
    parser.add_argument(
        "--end", dest="end_index", type=int, default=None, help="End index."
    )
    args = parser.parse_args()

    preprocessed_folder = Path(args.preprocessed_folder)
    assert (
        preprocessed_folder.exists()
    ), f"Mission folder does not exist: {preprocessed_folder}"

    run_postprocessing(
        preprocessed_folder, start_index=args.start_index, end_index=args.end_index
    )
