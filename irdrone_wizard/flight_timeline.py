# -*- coding: utf-8 -*-
"""
Automatic detection of the flight phases (Step 2 "Flight timeline").

No Qt here: this module only reads the mission folder and computes. The dialog
(IRD_Interactive_timeline.py) shows the result and lets the user refine it.

How the phases are found
------------------------
* Every DNG (DJI and SJCam) embeds a ~1000 px JPEG preview. Reading it takes a
  few milliseconds, so the whole mission is scanned in seconds, without
  RawTherapee. The previews also feed the filmstrips of the dialog.
* Visible (VIS): the altitude above take-off (EXIF) gives the low hover at the
  start (synchronisation) and the high plateau (survey).
* Synchronisation: the angle of the rotating ArUco marker (id 0) is measured on
  the previews of the frames taken near the ground. The turntable rotates at
  constant speed, so the frames where it really rotates form runs where the
  angle changes steadily ("rotation segments"). Static frames (turntable not yet
  started), direction reversals and the take-off are excluded.
* Infrared (NIR) has no altitude: its previews are scanned from the start until
  the marker is lost for good (the drone climbed). The NIR clock is unreliable
  (often off by an hour), so the NIR angle curve is matched against the VIS one:
  the same rotation seen by both cameras gives a coarse VIS/NIR time offset
  (about a second). Step 3 then computes the precise offset on full images.
* Once the offset is known, the VIS survey window defines the NIR one: the user
  never has to look at the infrared images.

Time convention (same as Step 3): a NIR frame taken at t_NIR (relative NIR time
line) is at t_NIR + time_shift on the VIS time line.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

MOBILE_ID = 0                      # rotating marker of the synchronisation target
FIXED_IDS = (5, 22, 16, 13)        # fixed markers around the turntable
THUMB_HEIGHT = 120                 # filmstrip thumbnails (pixels)
CACHE_VERSION = 1
STATE_FILE = Path("FlightAnalytics") / "flight_timeline.json"
CACHE_DIR = Path("Synchro") / "Thumbnails"

# Rotation detection
MIN_ROTATION_SPEED = 1.5           # deg/s, below: the turntable is considered still
SPEED_TOLERANCE = 0.3              # a step belongs to a segment if |w| is within 30% of its median
MIN_SEGMENT_FRAMES = 3
# Hover / survey detection
HOVER_MARGIN = 3.0                 # m above the starting altitude still counted as hover
NIR_LOST_FRAMES = 6                # NIR scan stops after that many frames without marker (after a sighting)

Progress = Optional[Callable[[int, str], None]]


# ---------------------------------------------------------------------------
#  Data
# ---------------------------------------------------------------------------
@dataclass
class Frame:
    """One image of a band, with what the analysis found on its preview."""
    name: str                       # VIS_0012.dng
    number: int                     # 12
    t: float                        # relative time line (s)
    alt: Optional[float] = None     # altitude above take-off (m), VIS only
    marker_angle: Optional[float] = None   # angle of marker 0 in the image (deg)
    marker_size: Optional[float] = None    # side of marker 0 in preview pixels
    scanned: bool = False           # marker detection was run on this frame


@dataclass
class Window:
    """Inclusive range of frame positions (indexes in the band frame list)."""
    first: int
    last: int

    def __len__(self):
        return max(0, self.last - self.first + 1)

    def as_list(self):
        return [self.first, self.last]


@dataclass
class BandAnalysis:
    band: str
    frames: List[Frame]
    segments: List[Window] = field(default_factory=list)   # rotation segments
    hover: Optional[Window] = None                          # VIS low hover / NIR marker run

    @property
    def times(self) -> np.ndarray:
        return np.array([f.t for f in self.frames], dtype=float)

    def period(self) -> float:
        t = self.times
        return float(np.median(np.diff(t))) if len(t) > 1 else 1.0


@dataclass
class TimelineProposal:
    """What the dialog shows first. Windows are frame positions."""
    vis_sync: Optional[Window]
    nir_sync: Optional[Window]
    vis_survey: Optional[Window]
    nir_survey: Optional[Window]
    time_shift: Optional[float]     # coarse VIS/NIR offset (s), None when not found
    shift_rms: Optional[float] = None
    messages: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
#  Mission folder reading
# ---------------------------------------------------------------------------
_NUM = re.compile(r"_(\d+)$")


def frame_number(name: str) -> int:
    m = _NUM.search(Path(name).stem)
    return int(m.group(1)) if m else -1


def band_folder(mission: Path, band: str) -> Path:
    return Path(mission) / "AerialPhotography" / band


def list_frames(mission: Path, band: str) -> List[Frame]:
    """Frames of a band in shooting order, with their relative time and altitude.

    Times come from time_line.json (written by Step 1 and used by Step 3), the
    altitude from the .exif side car. Missing pieces fall back on the side car
    RelativeTimeLine, then on the frame number."""
    folder = band_folder(mission, band)
    files = sorted((p for p in folder.glob("*") if p.suffix.lower() == ".dng"),
                   key=lambda p: frame_number(p.name))
    times: Dict[str, float] = {}
    tl = folder / "time_line.json"
    if tl.is_file():
        try:
            with open(tl, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get(band, []) if isinstance(data, dict) else []:
                times[item["img_path"]] = float(item["relative_timeline"])
        except (OSError, ValueError, KeyError, TypeError):
            times = {}
    frames = []
    for i, p in enumerate(files):
        exif = {}
        side = p.with_suffix(".exif")
        if side.is_file():
            try:
                with open(side, encoding="utf-8") as f:
                    exif = json.load(f)
            except (OSError, ValueError):
                exif = {}
        t = times.get(p.name, exif.get("RelativeTimeLine"))
        alt = exif.get("DroneAltitudeTakeOff")
        frames.append(Frame(name=p.name, number=frame_number(p.name),
                            t=float(t) if t is not None else float(i),
                            alt=float(alt) if isinstance(alt, (int, float)) else None))
    return frames


# ---------------------------------------------------------------------------
#  Previews and marker detection
# ---------------------------------------------------------------------------
def read_preview(path: Path, full_fallback: bool = True):
    """BGR preview of a DNG: the embedded JPEG (fast), else a half size demosaic."""
    import cv2
    import rawpy
    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = cv2.imdecode(np.frombuffer(thumb.data, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                return cv2.cvtColor(np.asarray(thumb.data), cv2.COLOR_RGB2BGR)
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            pass
        if not full_fallback:
            return None
        rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


_DETECTOR = None


def _aruco_detector():
    global _DETECTOR
    if _DETECTOR is None:
        import cv2
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        _DETECTOR = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    return _DETECTOR


def detect_mobile_marker(img) -> Tuple[Optional[float], Optional[float]]:
    """(angle in degrees, side in pixels) of the rotating marker, (None, None) if not seen.

    The angle is the direction of the first marker edge in the image, the same
    for both cameras up to their mounting: enough for a coarse synchronisation."""
    import cv2
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _aruco_detector().detectMarkers(gray)
    if ids is None:
        return None, None
    for c, i in zip(corners, ids.flatten()):
        if int(i) == MOBILE_ID:
            q = c[0]
            v = q[1] - q[0]
            return float(np.degrees(np.arctan2(v[1], v[0]))), float(np.hypot(*v))
    return None, None


def thumbnail_path(mission: Path, band: str, name: str) -> Path:
    return Path(mission) / CACHE_DIR / band / (Path(name).stem + ".jpg")


def _cache_file(mission: Path, band: str) -> Path:
    return Path(mission) / CACHE_DIR / f"detections_{band}.json"


def _load_cache(mission: Path, band: str) -> Dict[str, dict]:
    try:
        with open(_cache_file(mission, band), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == CACHE_VERSION:
            return data.get("frames", {})
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def _save_cache(mission: Path, band: str, cache: Dict[str, dict]) -> None:
    path = _cache_file(mission, band)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "frames": cache}, f)
        tmp.replace(path)
    except OSError:
        pass  # a cache: never block the analysis


def _file_key(path: Path) -> str:
    try:
        st = path.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return ""


class FrameScanner:
    """Reads previews once: writes the filmstrip thumbnail and, on request,
    detects the marker. Results are cached in Synchro/Thumbnails."""

    def __init__(self, mission: Path, band: str):
        self.mission = Path(mission)
        self.band = band
        self.cache = _load_cache(self.mission, band)
        self.dirty = False

    def process(self, frame: Frame, detect: bool) -> None:
        import cv2
        path = band_folder(self.mission, self.band) / frame.name
        key = _file_key(path)
        entry = self.cache.get(frame.name)
        if entry and entry.get("key") != key:
            entry = None
        thumb = thumbnail_path(self.mission, self.band, frame.name)
        need_thumb = not thumb.is_file()
        need_detect = detect and not (entry and entry.get("scanned"))
        if need_thumb or need_detect:
            img = read_preview(path)
            if img is None:
                return
            if need_thumb:
                h, w = img.shape[:2]
                small = cv2.resize(img, (max(1, round(w * THUMB_HEIGHT / h)), THUMB_HEIGHT),
                                   interpolation=cv2.INTER_AREA)
                thumb.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(thumb), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if need_detect:
                angle, size = detect_mobile_marker(img)
                entry = {"key": key, "scanned": True, "angle": angle, "size": size}
                self.cache[frame.name] = entry
                self.dirty = True
        if entry and entry.get("scanned"):
            frame.scanned = True
            frame.marker_angle = entry.get("angle")
            frame.marker_size = entry.get("size")

    def save(self) -> None:
        if self.dirty:
            _save_cache(self.mission, self.band, self.cache)
            self.dirty = False


# ---------------------------------------------------------------------------
#  Phase detection (pure functions, unit tested)
# ---------------------------------------------------------------------------
def wrap180(a):
    """Angle(s) brought back to [-180, 180)."""
    return (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0


def low_hover_window(alts: Sequence[Optional[float]], margin: float = HOVER_MARGIN) -> Optional[Window]:
    """Frames at the start of the flight close to the starting altitude (hover over the target).

    Ends at the first frame of a sustained climb or descent (two frames more than
    the margin away: a take-off from a summit flies down)."""
    a = [x for x in alts]
    known = [x for x in a[:10] if x is not None]
    if not known:
        return None
    base = float(np.median(known))
    last = None
    i = 0
    while i < len(a):
        x = a[i]
        if x is not None and abs(x - base) > margin:
            nxt = a[i + 1] if i + 1 < len(a) else x
            if nxt is None or abs(nxt - base) > margin:
                break
        last = i
        i += 1
    return Window(0, last) if last is not None else None


def survey_window(alts: Sequence[Optional[float]], min_frames: int = 5) -> Optional[Window]:
    """Longest run of frames on the survey plateau, the farthest from take-off.

    The altitudes are relative to take-off: their absolute value is the height
    difference with it, so a flight down from a summit (negative altitudes) is
    handled like a climb. The plateau is the 90th percentile of that difference;
    a frame is on it when within max(3 m, 6 %) of it. Single-frame drops are bridged."""
    a = np.abs(np.array([np.nan if x is None else x for x in alts], dtype=float))
    if len(a) == 0 or np.all(np.isnan(a)):
        return None
    top = float(np.nanpercentile(a, 90))
    if top < HOVER_MARGIN * 2:
        return None  # never left the ground
    tol = max(3.0, 0.06 * top)
    on = np.abs(a - top) <= tol
    # Bridge isolated gaps (one frame)
    for i in range(1, len(on) - 1):
        if not on[i] and on[i - 1] and on[i + 1]:
            on[i] = True
    best, start = None, None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if best is None or i - start > len(best):
                best = Window(start, i - 1)
            start = None
    if best is None or len(best) < min_frames:
        return None
    return best


def rotation_segments(times: Sequence[float], angles: Sequence[Optional[float]],
                      max_gap: Optional[float] = None) -> List[Window]:
    """Runs of frames where the marker turns steadily in one direction.

    angles: marker angle per frame (None when not seen). Each step between two
    consecutive frames that both see the marker has an angular speed; a run is
    made of consecutive steps of the same sign whose speed stays within
    SPEED_TOLERANCE of the run median (constant speed turntable). The frame
    where the turntable starts, stops or reverses is left out when the step
    leading to it is too slow."""
    t = np.asarray(times, dtype=float)
    n = len(t)
    if n < 2:
        return []
    if max_gap is None:
        max_gap = 2.5 * float(np.median(np.diff(t)))
    # Step speeds
    speed = np.full(n - 1, np.nan)
    for i in range(n - 1):
        a0, a1 = angles[i], angles[i + 1]
        dt = t[i + 1] - t[i]
        if a0 is None or a1 is None or dt <= 0 or dt > max_gap:
            continue
        speed[i] = float(wrap180(a1 - a0)) / dt
    moving = np.abs(speed) >= MIN_ROTATION_SPEED   # nan -> False
    sign = np.sign(np.nan_to_num(speed))
    # Runs of moving steps with the same sign
    runs = []
    i = 0
    while i < n - 1:
        if not moving[i]:
            i += 1
            continue
        j = i
        while j + 1 < n - 1 and moving[j + 1] and sign[j + 1] == sign[i]:
            j += 1
        runs.append((i, j))
        i = j + 1
    segments = []
    for i, j in runs:
        steps = list(range(i, j + 1))
        med = float(np.median(np.abs(speed[steps])))
        ok = [k for k in steps if abs(abs(speed[k]) - med) <= SPEED_TOLERANCE * med]
        if not ok:
            continue
        # Keep the longest contiguous block of consistent steps
        blocks, cur = [], [ok[0]]
        for k in ok[1:]:
            if k == cur[-1] + 1:
                cur.append(k)
            else:
                blocks.append(cur)
                cur = [k]
        blocks.append(cur)
        block = max(blocks, key=len)
        first, last = block[0], block[-1] + 1     # step k joins frames k and k+1
        if last - first + 1 >= MIN_SEGMENT_FRAMES:
            segments.append(Window(first, last))
    return segments


def _unwrapped(times, angles) -> Tuple[np.ndarray, np.ndarray]:
    """Times and unwrapped angles of the frames that see the marker."""
    pts = [(t, a) for t, a in zip(times, angles) if a is not None]
    if not pts:
        return np.zeros(0), np.zeros(0)
    t = np.array([p[0] for p in pts], dtype=float)
    a = np.unwrap(np.radians([p[1] for p in pts]))
    return t, np.degrees(a)


def coarse_time_shift(vis_t, vis_angles, nir_t, nir_angles,
                      step: float = 0.1, min_overlap: float = 0.6
                      ) -> Tuple[Optional[float], Optional[float]]:
    """Coarse VIS/NIR offset from the marker angle curves seen by both cameras.

    Searches the shift s (s) minimising the angular mismatch between the VIS
    angles and the NIR angles moved to t_NIR + s, up to a constant (the two
    cameras are not mounted exactly the same way). Only the frames seeing the
    marker count. The curve must have some structure (rotation start, stop or
    reversal); a turntable turning at constant speed during the whole hover is
    ambiguous by nature, the precise Step 3 calculation removes the ambiguity.

    Returns (shift, rms in degrees), (None, None) when no reliable overlap."""
    tv, av = _unwrapped(vis_t, vis_angles)
    tn, an = _unwrapped(nir_t, nir_angles)
    if len(tv) < 3 or len(tn) < 3:
        return None, None
    period_n = float(np.median(np.diff(tn)))
    # NIR samples too far apart cannot be interpolated
    gaps = np.diff(tn) > 2.5 * period_n
    period_v = float(np.median(np.diff(tv)))
    nir_span_in_vis = (tn[-1] - tn[0]) / period_v
    need = max(3, int(min_overlap * min(len(tv), nir_span_in_vis)))
    lo = tv[0] - tn[-1]
    hi = tv[-1] - tn[0]
    best = (None, None)
    best_cost = np.inf
    for s in np.arange(lo, hi + step, step):
        x = tv - s                             # VIS time seen on the NIR time line
        inside = (x >= tn[0]) & (x <= tn[-1])
        if inside.sum() < need:
            continue
        xi = x[inside]
        k = np.clip(np.searchsorted(tn, xi) - 1, 0, len(tn) - 2)
        valid = ~gaps[k]
        if valid.sum() < need:
            continue
        an_i = np.interp(xi[valid], tn, an)
        d = wrap180(av[inside][valid] - an_i)
        c = math.degrees(math.atan2(np.mean(np.sin(np.radians(d))), np.mean(np.cos(np.radians(d)))))
        r = wrap180(d - c)
        cost = float(np.sqrt(np.mean(r ** 2)))
        # Favour larger overlaps a little when the fit is equally good
        cost_cmp = cost / math.sqrt(valid.sum())
        if cost_cmp < best_cost:
            best_cost = cost_cmp
            best = (round(float(s), 2), cost)
    if best[0] is None or best[1] > 15.0:
        return None, None
    return best


def match_segments(vis: BandAnalysis, nir: BandAnalysis, shift: Optional[float]
                   ) -> Tuple[Optional[Window], Optional[Window]]:
    """Choose the VIS and NIR rotation segments recording the same turn.

    With a time shift: the pair with the largest time overlap. Without: the
    longest VIS segment and the NIR segment of closest duration and same
    direction."""
    tv, tn = vis.times, nir.times
    if not vis.segments:
        return None, (max(nir.segments, key=len) if nir.segments else None)
    if not nir.segments:
        return max(vis.segments, key=lambda w: tv[w.last] - tv[w.first]), None

    def direction(band: BandAnalysis, w: Window) -> float:
        a0, a1 = band.frames[w.first].marker_angle, band.frames[w.first + 1].marker_angle
        return float(np.sign(wrap180(a1 - a0)))

    best, best_score = (None, None), -np.inf
    for wv in vis.segments:
        v0, v1 = tv[wv.first], tv[wv.last]
        for wn in nir.segments:
            n0, n1 = tn[wn.first], tn[wn.last]
            if direction(vis, wv) != direction(nir, wn):
                continue
            if shift is not None:
                score = min(v1, n1 + shift) - max(v0, n0 + shift)
            else:
                score = -abs((v1 - v0) - (n1 - n0)) + 1e-3 * (v1 - v0)
            if score > best_score:
                best, best_score = (wv, wn), score
    if best[0] is None or (shift is not None and best_score <= 0):
        return max(vis.segments, key=len), max(nir.segments, key=len)
    return best


def derived_window(vis_times: np.ndarray, vis_window: Window,
                   nir_times: np.ndarray, shift: float) -> Optional[Window]:
    """NIR frames covering a VIS window once on the VIS time line.

    One NIR frame is added on each side so that the first and last VIS frames
    can be paired with a NIR frame before and after them."""
    if vis_window is None or shift is None or len(nir_times) == 0:
        return None
    t0, t1 = vis_times[vis_window.first], vis_times[vis_window.last]
    tn = np.asarray(nir_times) + shift
    inside = np.where((tn >= t0) & (tn <= t1))[0]
    if len(inside) == 0:
        k = int(np.argmin(np.abs(tn - 0.5 * (t0 + t1))))
        return Window(k, k)
    return Window(max(0, int(inside[0]) - 1), min(len(tn) - 1, int(inside[-1]) + 1))


# ---------------------------------------------------------------------------
#  Whole mission analysis
# ---------------------------------------------------------------------------
def analyse_mission(mission: Path, progress: Progress = None,
                    cancelled: Callable[[], bool] = lambda: False
                    ) -> Tuple[BandAnalysis, BandAnalysis, TimelineProposal]:
    """Scan both bands and propose the phases.

    progress(percent, text) is called along the way. Marker detection runs only
    where it can matter: VIS frames of the low hover, NIR frames from the start
    until the marker is lost for good."""
    mission = Path(mission)
    report = progress or (lambda p, s: None)
    vis_frames = list_frames(mission, "VIS")
    nir_frames = list_frames(mission, "NIR")
    if not vis_frames:
        raise FileNotFoundError(f"No VIS image in {band_folder(mission, 'VIS')}")
    vis = BandAnalysis("VIS", vis_frames)
    nir = BandAnalysis("NIR", nir_frames)
    total = max(1, len(vis_frames) + len(nir_frames))
    done = 0

    # ---- VIS: altitude first, marker only during the low hover
    vis.hover = low_hover_window([f.alt for f in vis_frames])
    scan_until = vis.hover.last if vis.hover else len(vis_frames) - 1
    scanner = FrameScanner(mission, "VIS")
    lost = 0
    for i, f in enumerate(vis_frames):
        if cancelled():
            scanner.save()
            raise InterruptedError
        detect = i <= scan_until
        if vis.hover is None and lost >= NIR_LOST_FRAMES:
            detect = False   # no altitude: same early stop as NIR
        scanner.process(f, detect)
        if vis.hover is None and f.scanned:
            seen_before = any(x.marker_angle is not None for x in vis_frames[:i])
            lost = lost + 1 if (f.marker_angle is None and seen_before) else 0
        done += 1
        report(int(100 * done / total), f"Reading the visible images ({i + 1}/{len(vis_frames)})")
    scanner.save()

    # ---- NIR: scan from the start until the marker is lost for good
    scanner = FrameScanner(mission, "NIR")
    seen, lost = False, 0
    last_seen = None
    for i, f in enumerate(nir_frames):
        if cancelled():
            scanner.save()
            raise InterruptedError
        detect = not (seen and lost >= NIR_LOST_FRAMES) and i < max(20, int(0.7 * len(nir_frames)))
        scanner.process(f, detect)
        if detect and f.scanned:
            if f.marker_angle is not None:
                seen, lost, last_seen = True, 0, i
            elif seen:
                lost += 1
        done += 1
        report(int(100 * done / total), f"Reading the infrared images ({i + 1}/{len(nir_frames)})")
    scanner.save()
    if last_seen is not None:
        first_seen = next(i for i, f in enumerate(nir_frames) if f.marker_angle is not None)
        nir.hover = Window(first_seen, last_seen)

    # ---- Rotation segments, coarse shift, windows
    vis.segments = rotation_segments(vis.times, [f.marker_angle for f in vis_frames])
    nir.segments = rotation_segments(nir.times, [f.marker_angle for f in nir_frames]) if nir_frames else []
    messages = []
    shift, rms = (None, None)
    if nir_frames:
        shift, rms = coarse_time_shift(vis.times, [f.marker_angle for f in vis_frames],
                                       nir.times, [f.marker_angle for f in nir_frames])
    vis_sync, nir_sync = match_segments(vis, nir, shift) if (vis.segments or nir.segments) else (None, None)
    if vis_sync is None:
        vis_sync = vis.hover
        messages.append("The rotating target was not found on the visible images: "
                        "the synchronisation window is the low hover, check it.")
    if nir_frames and nir_sync is None:
        messages.append("The rotating target was not found on the infrared images: "
                        "set the infrared synchronisation window by hand.")
    if nir_frames and shift is None:
        messages.append("The infrared images could not be placed on the visible time line "
                        "automatically: Step 3 will compute the offset.")
    vis_survey = survey_window([f.alt for f in vis_frames])
    if vis_survey is None:
        start = (vis.hover.last + 1) if vis.hover else 0
        vis_survey = Window(min(start, len(vis_frames) - 1), len(vis_frames) - 1)
        messages.append("No altitude plateau found: the survey window covers the rest of the flight.")
    nir_survey = derived_window(vis.times, vis_survey, nir.times, shift) if nir_frames else None
    report(100, "Done")
    return vis, nir, TimelineProposal(vis_sync, nir_sync, vis_survey, nir_survey, shift, rms, messages)


# ---------------------------------------------------------------------------
#  Saving the selection (same files as the classic Step 2)
# ---------------------------------------------------------------------------
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    tmp.replace(path)


def _transfer_section(folder: Path, frames: List[Frame], window: Optional[Window]) -> dict:
    names = [f.name for f in frames[window.first:window.last + 1]] if window else []
    return {
        "outputFolder": str(folder),
        "idMin": frames[window.first].number if window else -1,
        "idMax": frames[window.last].number if window else -1,
        "listCopiedImages": names,
    }


def write_transfer_info(mission: Path, band: str, frames: List[Frame],
                        sync: Optional[Window], fly: Optional[Window]) -> Path:
    """Write AerialPhotography/<band>/transfer_info_<band>_dng.json.

    Same structure as the classic Step 2, read by Steps 3, 4 and the mapping.
    The take-off section written by Step 1 is kept (it holds the original SD
    card name); when absent, the first frame is the take-off frame."""
    folder = band_folder(mission, band)
    path = folder / f"transfer_info_{band}_dng.json"
    old = {}
    if path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f) or {}
        except (OSError, ValueError):
            old = {}
    tkoff = old.get("tkoff") if isinstance(old.get("tkoff"), dict) and old["tkoff"].get("listCopiedImages") else None
    if tkoff is None and frames:
        tkoff = {"outputFolder": str(folder), "original name": frames[0].name,
                 "idMin": frames[0].number, "idMax": frames[0].number,
                 "listCopiedImages": [frames[0].name]}
    data = {
        "spectral_band": band,
        "img_suffix": "dng",
        "inputFolder": str(folder),
        "tkoff": tkoff,
        "sync": _transfer_section(folder, frames, sync),
        "fly": _transfer_section(folder, frames, fly),
        "selected_by": "flight_timeline",
    }
    _write_json(path, data)
    return path


def save_state(mission: Path, vis: BandAnalysis, nir: BandAnalysis, proposal: TimelineProposal,
               chosen: Dict[str, Optional[Window]], time_shift: Optional[float]) -> Path:
    """FlightAnalytics/flight_timeline.json: what was proposed and what was confirmed."""
    def names(band, w):
        return None if w is None else [band.frames[w.first].name, band.frames[w.last].name]
    data = {
        "schema_version": 1,
        "coarse_time_shift": proposal.time_shift,
        "coarse_time_shift_rms_deg": proposal.shift_rms,
        "time_shift_used": time_shift,
        "proposed": {
            "VIS sync": names(vis, proposal.vis_sync), "NIR sync": names(nir, proposal.nir_sync),
            "VIS survey": names(vis, proposal.vis_survey), "NIR survey": names(nir, proposal.nir_survey),
        },
        "confirmed": {key: names(vis if key.startswith("VIS") else nir, w) for key, w in chosen.items()},
    }
    path = Path(mission) / STATE_FILE
    _write_json(path, data)
    return path


def update_nir_survey_from_vis(mission: Path, time_shift: float) -> Optional[Path]:
    """After Step 3: the precise offset places the NIR survey window from the VIS one.

    Rewrites only the 'fly' section of transfer_info_NIR_dng.json. Returns the
    file written, None when the VIS survey window or the NIR frames are missing."""
    mission = Path(mission)
    vis_info = band_folder(mission, "VIS") / "transfer_info_VIS_dng.json"
    nir_info = band_folder(mission, "NIR") / "transfer_info_NIR_dng.json"
    try:
        with open(vis_info, encoding="utf-8") as f:
            fly = json.load(f).get("fly") or {}
        with open(nir_info, encoding="utf-8") as f:
            nir_data = json.load(f)
    except (OSError, ValueError):
        return None
    vis_frames = list_frames(mission, "VIS")
    nir_frames = list_frames(mission, "NIR")
    names = [f.name for f in vis_frames]
    sel = fly.get("listCopiedImages") or []
    if not sel or not nir_frames or sel[0] not in names or sel[-1] not in names:
        return None
    w = Window(names.index(sel[0]), names.index(sel[-1]))
    vt = np.array([f.t for f in vis_frames])
    nt = np.array([f.t for f in nir_frames])
    nw = derived_window(vt, w, nt, time_shift)
    if nw is None:
        return None
    nir_data["fly"] = _transfer_section(band_folder(mission, "NIR"), nir_frames, nw)
    _write_json(nir_info, nir_data)
    return nir_info


def load_state(mission: Path) -> Optional[dict]:
    try:
        with open(Path(mission) / STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def window_from_names(frames: List[Frame], pair) -> Optional[Window]:
    """Window from [first name, last name] (saved state), None if not found."""
    if not pair:
        return None
    names = [f.name for f in frames]
    try:
        a, b = names.index(pair[0]), names.index(pair[1])
    except ValueError:
        return None
    return Window(min(a, b), max(a, b))


def to_dict(obj):
    return asdict(obj)
