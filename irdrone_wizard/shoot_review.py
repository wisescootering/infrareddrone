# -*- coding: utf-8 -*-
"""
Review of the aligned survey images (end of Step 4).

No Qt here: this module reads the mission folder and computes; the review
window (IRD_Interactive_review.py) shows the result.

What is reviewed
----------------
Each shoot point aligned by Step 4 (ImgIRdrone/shoot_points.json) has a
visible image (VIS_XXXX.jpg) and a false colour image (VIR_XXXX_local.jpg, or
_global) whose red channel is the aligned infrared. The user checks that both
overlap, flags the misaligned points and realigns them by hand (redo).

Automatic check
---------------
To show the doubtful points first, the residual misalignment is measured: the
image is cut in 4 x 4 tiles and, in each tile, the edges of the visible image
are matched against the edges of the infrared (phase correlation of the
gradient magnitudes, on a ~1000 px wide copy). The median tile offset, in
pixels of the full image, is ~1 px for a good alignment and grows with the
error (a 10 px shift reads ~9 px). Tiles without texture (water, sky) give a
weak correlation and are ignored.

Review state
------------
"failed" lives in ImgIRdrone/shoot_points.json (read by Step 5, which skips
those points). The scores and the points the user looked at and accepted
("checked") are kept apart, in ImgIRdrone/review.json, so the Step 4 inventory
keeps its format.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

OUTPUT_FOLDER = "ImgIRdrone"
INVENTORY = "shoot_points.json"
REVIEW_FILE = "review.json"
REVIEW_VERSION = 1

# Residual misalignment (pixels of the full image)
SHIFT_OK = 3.0          # up to this: aligned
SHIFT_SUSPICIOUS = 6.0  # beyond this: very likely misaligned
SCORE_WIDTH = 1000      # width of the copy used to measure it
SCORE_GRID = 4
MIN_TILE_RESPONSE = 0.05
MIN_TILES = 4

STATUS_OK = "ok"
STATUS_CHECK = "check"           # residual between SHIFT_OK and SHIFT_SUSPICIOUS
STATUS_SUSPICIOUS = "suspicious"
STATUS_FLAGGED = "flagged"        # failed in the inventory
STATUS_REALIGNED = "realigned"    # flagged, realigned by hand: the user confirms the new image
STATUS_UNKNOWN = "unknown"        # not measured (yet, or no texture)
STATUS_MISSING = "missing"        # no aligned image on disk

_VIS = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)


@dataclass
class ReviewPoint:
    number: int
    stem: str                              # VIS_0137
    dt: Optional[float] = None             # VIS / NIR time difference (s)
    failed: bool = False
    nir_name: Optional[str] = None
    time: Optional[float] = None           # relative VIS time line (s)
    altitude: Optional[float] = None       # above ground (m)
    vis_image: Optional[Path] = None
    vir_image: Optional[Path] = None
    redo_script: Optional[Path] = None
    motion: Optional[dict] = None          # correction of the alignment vs its initialisation
    shift: Optional[float] = None          # median residual (px)
    shift_worst: Optional[float] = None    # worst textured tile (px)
    checked: bool = False
    realigned: bool = False                # flagged, realigned by hand, not confirmed yet

    @property
    def label(self) -> str:
        return f"{self.number:04d}"

    @property
    def measured_status(self) -> str:
        if self.shift is None:
            return STATUS_UNKNOWN
        if self.shift > SHIFT_SUSPICIOUS:
            return STATUS_SUSPICIOUS
        if self.shift > SHIFT_OK:
            return STATUS_CHECK
        return STATUS_OK

    @property
    def status(self) -> str:
        if self.failed:
            return STATUS_REALIGNED if self.realigned else STATUS_FLAGGED
        if self.vir_image is None or self.vis_image is None:
            return STATUS_MISSING
        if self.checked:            # confirmed by the user: aligned
            return STATUS_OK
        return self.measured_status


@dataclass
class Review:
    mission: Path
    points: List[ReviewPoint] = field(default_factory=list)
    recovered: List[str] = field(default_factory=list)   # interrupted redos undone at load

    @property
    def output(self) -> Path:
        return self.mission / OUTPUT_FOLDER

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for p in self.points:
            out[p.status] = out.get(p.status, 0) + 1
        return out

    def by_number(self, number: int) -> Optional[ReviewPoint]:
        return next((p for p in self.points if p.number == number), None)

    def flagged(self) -> List[ReviewPoint]:
        return [p for p in self.points if p.failed]

    def suspicious(self) -> List[ReviewPoint]:
        return [p for p in self.points if p.status == STATUS_SUSPICIOUS]


# ---------------------------------------------------------------------------
#  Loading
# ---------------------------------------------------------------------------
def vis_number(filename: str) -> Optional[int]:
    m = _VIS.fullmatch(Path(filename).name)
    return int(m.group(1)) if m else None


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def aligned_image(output: Path, number: int) -> Optional[Path]:
    """VIR image of a point: local alignment first, then global."""
    for mode in ("local", "global"):
        path = output / f"VIR_{number:04d}_{mode}.jpg"
        if path.is_file():
            return path
    return None


def _pairs_by_name(mission: Path) -> Dict[str, dict]:
    data = _read_json(mission / "AerialPhotography" / INVENTORY)
    pairs = {}
    for point in (data or {}).get("shoot_points", []) if isinstance(data, dict) else []:
        vis = point.get("VIS") if isinstance(point, dict) else None
        if isinstance(vis, dict) and isinstance(vis.get("FileName"), str):
            pairs[Path(vis["FileName"]).name.casefold()] = point
    return pairs


def _motion_summary(path: Path) -> Optional[dict]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    out = {}
    corr = data.get("correction_vs_initialization")
    if isinstance(corr, dict):
        out["correction"] = {k: float(corr[k]) for k in ("yaw", "pitch", "roll")
                             if isinstance(corr.get(k), (int, float))}
    field_ = data.get("vector_field_summary")
    if isinstance(field_, dict) and isinstance(field_.get("max_abs"), (int, float)):
        out["local_max"] = float(field_["max_abs"])
    return out or None


def load_review(mission: Path) -> Review:
    """Shoot points aligned by Step 4, with their images and saved review state.

    Raises FileNotFoundError when Step 4 has not written its inventory yet."""
    mission = Path(mission)
    output = mission / OUTPUT_FOLDER
    recovered = _recover_interrupted_redos(output)
    inventory = _read_json(output / INVENTORY)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("shoot_points"), list):
        raise FileNotFoundError(f"No aligned images yet (run Step 4): {output / INVENTORY}")
    points = _inventory_points(mission, inventory)
    return Review(mission=mission, points=points, recovered=recovered)


def _inventory_points(mission: Path, inventory: dict, numbers=None) -> List[ReviewPoint]:
    """Review points of the Step 4 inventory (only ``numbers`` if given), sorted."""
    output = mission / OUTPUT_FOLDER
    pairs = _pairs_by_name(mission)
    state = load_state(mission)
    scores = state.get("scores", {})
    checked = set(state.get("checked", []))
    realigned = set(state.get("realigned", []))
    points = []
    for item in inventory["shoot_points"]:
        if not isinstance(item, dict) or not isinstance(item.get("FileName"), str):
            continue
        number = vis_number(item["FileName"])
        if number is None or (numbers is not None and number not in numbers):
            continue
        stem = Path(item["FileName"]).stem
        p = ReviewPoint(number=number, stem=stem, failed=bool(item.get("failed", False)))
        if isinstance(item.get("dt"), (int, float)):
            p.dt = float(item["dt"])
        pair = pairs.get(Path(item["FileName"]).name.casefold())
        if pair:
            vis = pair.get("VIS", {})
            if isinstance(vis.get("RelativeTimeLine"), (int, float)):
                p.time = float(vis["RelativeTimeLine"])
            if isinstance(vis.get("DroneAltitudeGround"), (int, float)):
                p.altitude = float(vis["DroneAltitudeGround"])
            nir = next((n for n in pair.get("NIR", []) if isinstance(n, dict) and n.get("rank") == 1), None)
            if nir and isinstance(nir.get("FileName"), str):
                p.nir_name = nir["FileName"]
        vis_jpg = output / f"{stem}.jpg"
        p.vis_image = vis_jpg if vis_jpg.is_file() else None
        p.vir_image = aligned_image(output, number)
        for suffix in ("_REDO.bat", "_REDO.sh"):
            if (output / f"{stem}{suffix}").is_file():
                p.redo_script = output / f"{stem}{suffix}"
                break
        p.motion = _motion_summary(output / f"{stem}_motion_model.json")
        cached = scores.get(p.label)
        if p.vir_image is not None and isinstance(cached, dict) and cached.get("key") == _file_key(p.vir_image):
            p.shift, p.shift_worst = cached.get("shift"), cached.get("worst")
        p.checked = p.label in checked
        p.realigned = p.failed and p.label in realigned
        points.append(p)
    points.sort(key=lambda q: q.number)
    return points


def statuses(mission: Path) -> Optional[Dict[int, str]]:
    """{number: status} of the shoot points as the review shows them (with the
    scores it measured), nothing changed on disk; None before Step 4."""
    mission = Path(mission)
    inventory = _read_json(mission / OUTPUT_FOLDER / INVENTORY)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("shoot_points"), list):
        return None
    return {p.number: p.status for p in _inventory_points(mission, inventory)}


def add_points(review: Review, numbers: Iterable[int]) -> List[ReviewPoint]:
    """Points of ``numbers`` that Step 4 has just aligned (now in its inventory,
    not in the review yet), added to the review in order; the others stay out."""
    numbers = {int(n) for n in numbers} - {p.number for p in review.points}
    inventory = _read_json(review.output / INVENTORY)
    if not numbers or not isinstance(inventory, dict) or not isinstance(inventory.get("shoot_points"), list):
        return []
    added = _inventory_points(review.mission, inventory, numbers)
    review.points = sorted(review.points + added, key=lambda q: q.number)
    if added:     # asked for by the user: Step 5 maps them whatever its own selection
        done = {p.number for p in added}
        for item in inventory["shoot_points"]:
            if isinstance(item, dict) and vis_number(str(item.get("FileName", ""))) in done:
                item[ALIGNED_ON_REQUEST] = True
        _write_json(review.output / INVENTORY, inventory)
    return added


ALIGNED_ON_REQUEST = "aligned_on_request"   # inventory key: aligned from the review, always mapped


MAX_ALIGN_DT = 6.0     # Step 4 limit of the VIS / NIR time difference (s)


def not_aligned_pairs(review: Review) -> Dict[int, dict]:
    """Shoot points of Step 3 that Step 4 did not align (left out by the best
    mapping, the time filter or the image range): number -> {"stem", "dt"
    (rank-one VIS / NIR time difference, None without infrared), "alignable"}."""
    aligned = {p.number for p in review.points}
    out = {}
    for name, pair in _pairs_by_name(review.mission).items():
        number = vis_number(name)
        if number is None or number in aligned:
            continue
        nir = next((n for n in pair.get("NIR", []) or [] if isinstance(n, dict) and n.get("rank") == 1), None)
        dt = nir.get("dt") if isinstance(nir, dict) else None
        dt = float(dt) if isinstance(dt, (int, float)) and not isinstance(dt, bool) else None
        out[number] = {"stem": Path(pair["VIS"]["FileName"]).stem, "dt": dt,
                       "alignable": dt is not None and abs(dt) < MAX_ALIGN_DT}
    return out


def _recover_interrupted_redos(output: Path) -> List[str]:
    """Stems of the points whose redo was interrupted (process or computer
    killed), put back to their alignment before the redo."""
    if not output.is_dir():
        return []
    try:
        from manual_redo_archives import recover_interrupted_redos
        recovered = recover_interrupted_redos(output)
    except Exception as error:          # never blocks the review
        print(f"Interrupted realignments not checked: {error}")
        return []
    return [name.removesuffix("_align_traces_manual") for name in recovered]


# ---------------------------------------------------------------------------
#  Saved state
# ---------------------------------------------------------------------------
def load_state(mission: Path) -> dict:
    data = _read_json(Path(mission) / OUTPUT_FOLDER / REVIEW_FILE)
    if not isinstance(data, dict) or data.get("version") != REVIEW_VERSION:
        return {"version": REVIEW_VERSION, "scores": {}, "checked": []}
    data.setdefault("scores", {})
    data.setdefault("checked", [])
    data.setdefault("realigned", [])
    return data


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def save_state(review: Review) -> None:
    """Scores, checked and realigned points of the review (ImgIRdrone/review.json)."""
    scores = {}
    for p in review.points:
        if p.shift is not None and p.vir_image is not None:
            scores[p.label] = {"key": _file_key(p.vir_image), "shift": p.shift, "worst": p.shift_worst}
    data = {"version": REVIEW_VERSION, "scores": scores,
            "checked": sorted(p.label for p in review.points if p.checked),
            "realigned": sorted(p.label for p in review.points if p.realigned and p.failed)}
    review.output.mkdir(parents=True, exist_ok=True)
    _write_json(review.output / REVIEW_FILE, data)


def _file_key(path: Path) -> str:
    st = Path(path).stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def set_failed(review: Review, numbers: Iterable[int], failed: bool) -> None:
    """Flag (failed=True) or unflag points in ImgIRdrone/shoot_points.json and
    rebuild shoot_points_failed_summary.json, like Step 4 does."""
    import IRD_Interactive_4 as Step4   # the same rules as the Step 4 buttons
    numbers = set(numbers)
    if not numbers:
        return
    path = review.output / INVENTORY
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if failed:
        Step4.apply_failed_selection(inventory, numbers)
    else:
        Step4.clear_failed_selection(inventory, numbers)
    _write_json(path, inventory)
    _write_json(review.output / Step4.FAILED_SUMMARY_FILENAME, Step4.build_failed_summary(inventory))
    for p in review.points:
        if p.number in numbers:
            p.failed = failed
            p.realigned = False
            if failed:
                p.checked = False


def refresh_point(review: Review, point: ReviewPoint) -> None:
    """Reload the images of a point after a redo (the score must be measured again)."""
    point.vir_image = aligned_image(review.output, point.number)
    vis_jpg = review.output / f"{point.stem}.jpg"
    point.vis_image = vis_jpg if vis_jpg.is_file() else None
    point.motion = _motion_summary(review.output / f"{point.stem}_motion_model.json")
    point.shift = point.shift_worst = None
    point.checked = False


# ---------------------------------------------------------------------------
#  Automatic check
# ---------------------------------------------------------------------------
def _gradient(img):
    import cv2
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.2)
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1)
    return np.sqrt(gx * gx + gy * gy)


def tile_shifts(vis_bgr, nir_gray, width: int = SCORE_WIDTH, grid: int = SCORE_GRID):
    """Offsets (dx, dy) of the infrared edges against the visible ones, one per
    textured tile, in pixels of the given images (the infrared drawn dx to the
    right of where it should be reads dx > 0)."""
    import cv2
    scale = min(1.0, width / vis_bgr.shape[1])
    vis = cv2.cvtColor(vis_bgr, cv2.COLOR_BGR2GRAY) if vis_bgr.ndim == 3 else vis_bgr
    if nir_gray.shape[:2] != vis.shape[:2]:
        nir_gray = cv2.resize(nir_gray, (vis.shape[1], vis.shape[0]), interpolation=cv2.INTER_AREA)
    if scale < 1.0:
        vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        nir_gray = cv2.resize(nir_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gv, gn = _gradient(vis), _gradient(nir_gray)
    h, w = gv.shape
    th, tw = h // grid, w // grid
    if th < 16 or tw < 16:
        return []
    window = cv2.createHanningWindow((tw, th), cv2.CV_32F)
    shifts = []
    for i in range(grid):
        for j in range(grid):
            a = gv[i * th:(i + 1) * th, j * tw:(j + 1) * tw]
            b = gn[i * th:(i + 1) * th, j * tw:(j + 1) * tw]
            if a.std() < 1e-3 or b.std() < 1e-3:
                continue
            a = (a - a.mean()) / a.std()
            b = (b - b.mean()) / b.std()
            (dx, dy), response = cv2.phaseCorrelate(a, b, window)
            if response >= MIN_TILE_RESPONSE:
                shifts.append((dx / scale, dy / scale))
    return shifts


def residual_shift(vis_bgr, nir_gray, width: int = SCORE_WIDTH, grid: int = SCORE_GRID):
    """(median, worst) residual offset in pixels of the full image between the
    edges of the visible and infrared images; (None, None) without texture."""
    shifts = [float(np.hypot(dx, dy)) for dx, dy in tile_shifts(vis_bgr, nir_gray, width, grid)]
    if len(shifts) < MIN_TILES:
        return None, None
    return float(np.median(shifts)), float(np.percentile(shifts, 90))


def nir_from_vir(vir_bgr):
    """The aligned infrared is the red channel of the VIR image."""
    return vir_bgr[:, :, 2]


def measure_point(point: ReviewPoint) -> None:
    """Measure the residual misalignment of a point (sets shift / shift_worst)."""
    import cv2
    from image_io import imread
    if point.vis_image is None or point.vir_image is None:
        return
    # Full decoding: the JPEG reduced decoding (IMREAD_REDUCED_*) shifts the
    # colour planes slightly and would read ~3 px on well aligned images.
    vis = imread(point.vis_image, cv2.IMREAD_COLOR)
    vir = imread(point.vir_image, cv2.IMREAD_COLOR)
    if vis is None or vir is None:
        return
    point.shift, point.shift_worst = residual_shift(vis, nir_from_vir(vir))


def thumbnail(path: Path, width: int = 200):
    """Small BGR copy of a JPEG (decoded at 1/8 size: a few milliseconds)."""
    import cv2
    from image_io import imread
    img = imread(path, cv2.IMREAD_REDUCED_COLOR_8)
    if img is None:
        return None
    if img.shape[1] > width:
        img = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
    return img


def anaglyph(vis_bgr, vir_bgr):
    """Visible in cyan, infrared in red: grey where both overlap, coloured
    fringes where they do not."""
    import cv2
    vis = cv2.cvtColor(vis_bgr, cv2.COLOR_BGR2GRAY)
    nir = nir_from_vir(vir_bgr)
    if nir.shape != vis.shape:
        nir = cv2.resize(nir, (vis.shape[1], vis.shape[0]), interpolation=cv2.INTER_AREA)

    def stretch(c):
        lo, hi = np.percentile(c[::4, ::4], (1, 99))
        return np.clip((c.astype(np.float32) - lo) * (255.0 / max(hi - lo, 1.0)), 0, 255).astype(np.uint8)
    v, n = stretch(vis), stretch(nir)
    return np.dstack([v, v, n])   # B, G = visible ; R = infrared


def measure_all(review: Review, progress: Optional[Callable[[int, int], None]] = None,
                cancelled: Optional[Callable[[], bool]] = None,
                done: Optional[Callable[[ReviewPoint], None]] = None) -> None:
    todo = [p for p in review.points if p.shift is None and p.vir_image is not None]
    for k, p in enumerate(todo):
        if cancelled and cancelled():
            return
        try:
            measure_point(p)
        except Exception as e:  # one bad image must not stop the others
            print(f"Review: {p.stem} not measured ({e})")
        if done:
            done(p)
        if progress:
            progress(k + 1, len(todo))
