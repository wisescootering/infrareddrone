import argparse
from pathlib import Path
import json
from utils.utils_IRdrone_Class import ShootPoint
import automatic_registration
from utils.utils_odm import create_odm_folder, odm_mapping_optim
from config import CROP


def run_postprocessing(preprocessed_folder: Path, max_points: int = None):
    json_file = preprocessed_folder / "AerialPhotography" / "shoot_points.json"
    assert json_file.exists(), f"JSON file does not exist: {json_file}"
    with open(json_file, "r") as f:
        shoot_points = json.load(f)
    paired_points = shoot_points["shoot_points"]
    if max_points is not None:
        paired_points = paired_points[:max_points]
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
                vis_data.get("FlightYawDegree", "0").replace("+", "")
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

    # Sanity check for VIS and NIR files
    for point in paired_points:
        vis_path = Path(point["VIS"]["Directory"]) / point["VIS"]["FileName"]
        nir_path = next(
            (
                Path(nir["Directory"]) / nir["FileName"]
                for nir in point["NIR"]
                if nir["rank"] == 1
            ),
            None,
        )

        if not vis_path.exists():
            vis_path = (
                preprocessed_folder
                / "AerialPhotography"
                / "VIS"
                / point["VIS"]["FileName"]
            )
            assert vis_path.exists(), f"VIS file does not exist: {vis_path}"

        if nir_path and not nir_path.exists():
            nir_path = preprocessed_folder / "AerialPhotography" / "NIR" / nir_path.name
            assert nir_path.exists(), f"NIR file does not exist: {nir_path}"
    # Define required variables
    out_dir = preprocessed_folder / "PostProcessed"
    traces = ["vis", "nir"]  # Example traces
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
        "-n",
        "--max-points",
        dest="max_points",
        type=int,
        default=None,
        help="Maximum number of points to process.",
    )
    args = parser.parse_args()

    preprocessed_folder = Path(args.preprocessed_folder)
    assert (
        preprocessed_folder.exists()
    ), f"Mission folder does not exist: {preprocessed_folder}"

    run_postprocessing(preprocessed_folder, max_points=args.max_points)
