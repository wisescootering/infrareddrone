# -*- coding: utf-8 -*-
"""
Shoot points of a visible only mission (mission_type.VISIBLE).

A multispectral mission gets AerialPhotography/shoot_points.json from the
image pairing of Step 3: one point per visible image with its two nearest
infrared images. A visible only mission has nothing to pair: Step 2 writes the
same file with the visible metadata only and an empty "NIR" list, so Steps 4
to 6 (survey range, best mapping, maps) read it as they read the pairs.
No Qt here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from irdrone.file_utils import glob_ci  # noqa: E402
from IRD_Interactive_diskspace import write_json_atomic  # noqa: E402

SHOOT_POINTS = Path("AerialPhotography") / "shoot_points.json"
PAIRING_METHOD = "visible_only"
# Metadata of a visible image kept in a shoot point (same keys as the Step 3 pairing)
VIS_KEYS = (
    "FileName", "Directory", "DateTimeOriginal", "RelativeTimeLine",
    "DroneLatitude", "DroneLongitude", "GroundAltitude", "DroneAltitudeSeaLevel", "DroneAltitudeGround",
    "UTM_x", "UTM_y", "UTM_zone",
    "FlightYawDegree", "FlightPitchDegree", "FlightRollDegree",
    "GimbalYawDegree", "GimbalPitchDegree", "GimbalRollDegree",
    "DistanceToLastPoint", "CapToLastPoint", "CumulDistance",
)


def vis_entry(index: int, exif: dict) -> dict:
    """The "VIS" part of a shoot point: index in the VIS folder, then VIS_KEYS."""
    entry = {"idx": index}
    entry.update({key: exif.get(key) for key in VIS_KEYS})
    return entry


def vis_sidecars(mission: Path) -> list:
    """EXIF side cars (.exif, written by Step 1) of the visible images, in name order."""
    folder = Path(mission) / "AerialPhotography" / "VIS"
    out = []
    for image in glob_ci(folder, "*.dng"):
        sidecar = folder / f"{image.stem}.exif"
        if sidecar.is_file():
            with open(sidecar, encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def build_shoot_points(mission: Path) -> dict:
    """AerialPhotography/shoot_points.json content of a visible only mission."""
    sidecars = vis_sidecars(mission)
    if not sidecars:
        raise FileNotFoundError(f"No visible image with its EXIF side car in {Path(mission) / 'AerialPhotography' / 'VIS'}")
    return {
        "mission_path": str(mission),
        "time_shift": None,
        "n_VIS": len(sidecars),
        "n_NIR": 0,
        "pairing_method": PAIRING_METHOD,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "1.0",
        "shoot_points": [{"VIS": vis_entry(i, exif), "NIR": []} for i, exif in enumerate(sidecars)],
    }


def write_shoot_points(mission: Path) -> Path:
    """Write AerialPhotography/shoot_points.json (atomic) and return its path."""
    path = Path(mission) / SHOOT_POINTS
    write_json_atomic(path, build_shoot_points(mission), indent=4, ensure_ascii=False)
    return path
