# -*- coding: utf-8 -*-
"""
Best mapping: keep only the images the map needs (no Qt here).

A survey flown with a short interval between pictures gives far more overlap
than the mapping needs. Aligning every image costs time (Step 4) and feeding
too many near-identical images to ODM (Step 5) is slow and often makes the
map worse. The best mapping keeps a subset of the survey whose successive
ground footprints still overlap by a chosen fraction (75 % by default, the
`OVERLAP_Y` of the legacy command line `run.py --selection best-mapping`).

Selection
---------
The images are walked in shooting order. The first eligible image is kept.
Each next eligible image is compared with the last kept one: the overlap of
their ground footprints is estimated from the displacement of the drone, its
height above the ground and the camera field of view. While the overlap stays
above the target, the image is only a candidate. As soon as it falls below,
the previous candidate is kept (so two kept images always overlap by at least
the target, when the images allow it). The last eligible image is kept too:
the map reaches the end of the survey.

Overlap of two footprints (rectangles of the same size, the second shifted by
the displacement d of the drone, the image top looking to `yaw`):

    overlap = (1 - |d . up| / L_up) * (1 - |d . right| / L_right)

With a forward motion (d along the image top) this is the legacy criterion
1 - d / L_up. A lateral motion, or a turn, is measured as well.

Where it is used
----------------
* Step 2 (flight timeline): live preview on the time line and on the map, the
  choice is saved in FlightAnalytics/best_mapping.json.
* Step 4: only the selected shoot points are aligned (the VIS/NIR time
  difference is known there: only well synchronised pairs are eligible).
* Step 5: ODM image selection "by image overlap".
* Main window map: the sparse trajectory of the images kept (planned_numbers).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import flight_map as F

DEFAULT_OVERLAP = 0.75          # legacy config.OVERLAP_Y
MIN_OVERLAP = 0.50
MAX_OVERLAP = 0.95
MIN_HEIGHT = 2.0                # m: below, the footprint is meaningless (take-off, landing)
CHOICE_FILE = Path("FlightAnalytics") / "best_mapping.json"
EARTH_RADIUS = F.EARTH_RADIUS


@dataclass
class Shot:
    """One image as the selection sees it."""
    key: Any                        # whatever identifies the image for the caller
    lat: Optional[float]
    lon: Optional[float]
    height: Optional[float]         # above the ground, metres
    yaw: Optional[float]            # image top, degrees from the north (clockwise)
    eligible: bool = True


def _float(value) -> Optional[float]:
    try:
        v = float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def shot_from_vis(key: Any, vis: Dict[str, Any], eligible: bool = True) -> Shot:
    """Shot from VIS metadata (an .exif side car or the VIS entry of shoot_points.json)."""
    lat, lon = _float(vis.get("DroneLatitude")), _float(vis.get("DroneLongitude"))
    if lat is not None and lon is not None and lat == 0 and lon == 0:
        lat = lon = None
    height = _float(vis.get("DroneAltitudeGround"))
    if height is None:
        height = _float(vis.get("DroneAltitudeTakeOff"))
    yaw = _float(vis.get("GimbalYawDegree"))
    if yaw is None:
        yaw = _float(vis.get("FlightYawDegree"))
    return Shot(key, lat, lon, height, yaw, eligible)


def footprint_size(height: float, fov: Tuple[float, float]) -> Tuple[float, float]:
    """(across, along the image top) ground size in metres of a nadir image."""
    return (2 * height * math.tan(math.radians(fov[0]) / 2),
            2 * height * math.tan(math.radians(fov[1]) / 2))


def overlap(a: Shot, b: Shot, fov: Tuple[float, float]) -> Optional[float]:
    """Overlap fraction (0..1) of the footprints of a and b, None when unknown
    (no position or no height)."""
    if None in (a.lat, a.lon, b.lat, b.lon, a.height, b.height):
        return None
    height = min(a.height, b.height)
    if height < MIN_HEIGHT:
        return None
    north = math.radians(b.lat - a.lat) * EARTH_RADIUS
    east = math.radians(b.lon - a.lon) * EARTH_RADIUS * math.cos(math.radians((a.lat + b.lat) / 2))
    yaw = a.yaw if a.yaw is not None else b.yaw
    if yaw is None:                         # unknown: the drone flies to the image top
        along, across = math.hypot(east, north), 0.0
    else:
        t = math.radians(yaw)
        along = abs(east * math.sin(t) + north * math.cos(t))
        across = abs(east * math.cos(t) - north * math.sin(t))
    width, length = footprint_size(height, fov)
    return max(0.0, 1 - along / length) * max(0.0, 1 - across / width)


def select(shots: Sequence[Shot], target: float = DEFAULT_OVERLAP,
           fov: Optional[Tuple[float, float]] = None) -> List[int]:
    """Indexes (in `shots`) of the images kept for the map, in order.

    Only eligible shots are kept. An eligible shot whose overlap cannot be
    estimated (no position or height) is kept: nothing is dropped blindly."""
    fov = fov or F.field_of_view()
    kept: List[int] = []
    last: Optional[int] = None          # last kept
    candidate: Optional[int] = None     # last eligible one still overlapping enough
    for i, shot in enumerate(shots):
        if not shot.eligible:
            continue
        if last is None:
            kept.append(i)
            last = i
            continue
        ov = overlap(shots[last], shot, fov)
        if ov is not None and ov >= target:
            candidate = i
            continue
        if candidate is not None:
            kept.append(candidate)
            last, candidate = candidate, None
            ov = overlap(shots[last], shot, fov)
            if ov is not None and ov >= target:
                candidate = i
                continue
        kept.append(i)
        last = i
    if candidate is not None:
        kept.append(candidate)          # the end of the survey
    return kept


def clamp_overlap(value: Any) -> float:
    v = _float(value)
    if v is None:
        return DEFAULT_OVERLAP
    if v > 1.0:                         # given in percent
        v /= 100.0
    return min(MAX_OVERLAP, max(MIN_OVERLAP, v))


# ---------------------------------------------------------------------------
#  Shoot points of Step 3 (AerialPhotography/shoot_points.json)
# ---------------------------------------------------------------------------
def rank_one_dt(point: Dict[str, Any]) -> Optional[float]:
    nir = point.get("NIR") if isinstance(point, dict) else None
    for match in nir if isinstance(nir, list) else []:
        if isinstance(match, dict) and match.get("rank") == 1:
            if isinstance(match.get("dt"), bool):
                return None
            return _float(match.get("dt"))
    return None


def select_shoot_points(points: Sequence[Dict[str, Any]], target: float = DEFAULT_OVERLAP,
                        fov: Optional[Tuple[float, float]] = None,
                        eligible: Optional[Iterable[bool]] = None) -> List[Dict[str, Any]]:
    """Best mapping among paired shoot points (all of the survey, in order).

    `eligible[i]` False: point i is part of the flight (it counts for the
    displacement) but may not be kept, e.g. a badly synchronised pair."""
    flags = list(eligible) if eligible is not None else [True] * len(points)
    shots = [shot_from_vis(i, (p.get("VIS") if isinstance(p, dict) else None) or {}, ok)
             for i, (p, ok) in enumerate(zip(points, flags))]
    return [points[i] for i in select(shots, target, fov)]


def mission_fov(mission: Path) -> Tuple[float, float]:
    return F.field_of_view(F.camera_model(Path(mission)))


# ---------------------------------------------------------------------------
#  The choice, shared by Steps 2, 4 and 5
# ---------------------------------------------------------------------------
def load_choice(mission: Path) -> Dict[str, Any]:
    """{"enabled": bool, "overlap": 0..1}. Default: enabled at 75 %.
    Selecting again among images already selected keeps them: Step 5 can apply
    the same overlap to the images aligned by Step 4."""
    choice = {"enabled": True, "overlap": DEFAULT_OVERLAP}
    try:
        with open(Path(mission) / CHOICE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return choice
    if isinstance(data, dict):
        if isinstance(data.get("enabled"), bool):
            choice["enabled"] = data["enabled"]
        if "overlap" in data:
            choice["overlap"] = clamp_overlap(data["overlap"])
    return choice


def save_choice(mission: Path, **changes) -> Path:
    """Update FlightAnalytics/best_mapping.json with `changes` (other keys kept)."""
    path = Path(mission) / CHOICE_FILE
    data: Dict[str, Any] = {}
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict):
            data.update(old)
    except (OSError, ValueError):
        pass
    if "overlap" in changes:
        changes["overlap"] = round(clamp_overlap(changes["overlap"]), 3)
    data.update(changes)
    data.setdefault("schema_version", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    tmp.replace(path)
    return path


def _image_number(name: Any) -> Optional[int]:
    """Number of an image name, as the flight map numbers its points."""
    digits = "".join(c for c in Path(str(name)).stem if c.isdigit())
    return int(digits) if digits else None


def planned_numbers(mission: Path) -> Set[int]:
    """Numbers of the visible images kept by the best mapping, before the
    mapping of Step 5 (empty when the best mapping is off or unknown).

    The images Step 4 aligns (saved when it starts), else the preview of
    Step 2, else the selection made now over the survey of Step 2."""
    mission = Path(mission)
    choice = load_choice(mission)
    if not choice["enabled"]:
        return set()
    try:
        with open(mission / CHOICE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    for key in ("step4_selected", "preview_selected"):
        names = data.get(key) if isinstance(data, dict) else None
        if isinstance(names, list) and names:
            return {n for n in map(_image_number, names) if n is not None}
    phases = F.phases(mission)
    track = F.image_track(mission)
    shots = [Shot(p.number, p.lat, p.lon, p.height, p.yaw, phases.get(p.number) == "survey") for p in track]
    if not any(s.eligible for s in shots):
        return set()
    return {shots[i].key for i in select(shots, choice["overlap"], mission_fov(mission))}
