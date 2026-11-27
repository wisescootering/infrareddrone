# -*- coding: utf-8 -*-
"""
Spectral balance of the multispectral images (Step 6). No Qt here.

Why
---
The red, green and blue bands come from the drone camera, whose automatic
white balance keeps them well balanced. The near infrared comes from another
camera, with its own exposure: in the four band images
(ImgIRdrone/imgMultispectral/IRD_XXXX_1..4.tif, red, green, blue, NIR) the NIR
is often much darker or brighter than the visible bands, and a false colour
composite (NIR, red, green) is dominated by one of them. The spectral balance
adjusts the tones of the layers so that they match.

What the user adjusts
---------------------
Six layers: "rgb" (the three visible bands together), "red", "green", "blue"
(each visible band after "rgb"), "nir", and "all" (the four bands, last: a
common look, e.g. the same S curve everywhere). Each layer has an exposure (EV), a
gamma, a contrast, a brightness and a tone curve (a monotone spline through
handles, the identity by default), applied in this order:

    x -> x * 2^exposure -> x^(1/gamma) -> (x - 0.5) * 3^contrast + 0.5
      -> + brightness / 2 -> curve(x)              (clipped to 0..1 at each step)

The 16 bit images are transformed through look-up tables (65536 entries per
band): a band of 11 Mpixels in a few tenths of a second.

"Match the NIR to the visible" (``nir_auto``) sets the exposure and the gamma of
the NIR on each image from its statistics: the median and the 98th percentile
of the NIR become those of the visible (the mean of the three bands, after
their own adjustments). The camera exposures differ from image to image: one
fixed setting cannot balance them all, this does.

Mission balance and images of their own
---------------------------------------
One balance for the whole mission (the map is built from many images: they
must be treated alike, or the mosaic shows seams). An image may get a balance
of its own (``points``), copied from the mission balance and then adjusted.

Files (ImgIRdrone/img_Bal_Multispectral)
---------------------------------------
    spectral_balance.json     the settings: the mission balance, the images
                              with a balance of their own
    IRD_XXXX_1..4.tif         the balanced bands (same format and metadata as
                              the originals: OpenDroneMap reads them)
    IRD_XXXX_1.exif           copy of the flight metadata sidecar
    IRD_XXXX_bal.json         what was applied to the image (the balance, the
                              values computed for it, the original files)

An image is "balanced" when its bands are written with its current balance and
its originals have not changed since (Step 4 realigned it: they did). The map
(Step 6, Build the map) uses the balanced bands when a balance is set, and
writes those missing or out of date first (``apply_to_manifest``).
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))

SOURCE_FOLDER = Path("ImgIRdrone") / "imgMultispectral"
BALANCE_FOLDER = Path("ImgIRdrone") / "img_Bal_Multispectral"
SETTINGS_NAME = "spectral_balance.json"
VERSION = 1

BANDS = ("red", "green", "blue", "nir")            # IRD_XXXX_1..4.tif
LAYERS = ("all", "rgb", "red", "green", "blue", "nir")     # what the user adjusts
VISIBLE_LAYERS = ("red", "green", "blue")

# Ranges of the settings (the window uses them for its sliders)
EXPOSURE_RANGE = (-4.0, 4.0)       # EV
GAMMA_RANGE = (0.25, 4.0)
CONTRAST_RANGE = (-1.0, 1.0)       # shown -100..100
BRIGHTNESS_RANGE = (-1.0, 1.0)     # shown -100..100
IDENTITY_CURVE = ((0.0, 0.0), (1.0, 1.0))

# Automatic NIR: percentiles matched, on a copy about this wide
AUTO_PERCENTILES = (50.0, 98.0)
STATS_WIDTH = 500

STATE_NONE = "none"          # no balanced bands
STATE_DONE = "done"          # balanced bands written with the current balance
STATE_STALE = "stale"        # written, but the balance or the originals changed since

_IRD = re.compile(r"^IRD_(\d+)_1\.tif$", re.IGNORECASE)


# ---------------------------------------------------------------------------
#  Settings
# ---------------------------------------------------------------------------
@dataclass
class Adjust:
    """Tone adjustment of one layer."""
    exposure: float = 0.0
    gamma: float = 1.0
    contrast: float = 0.0
    brightness: float = 0.0
    curve: Tuple[Tuple[float, float], ...] = IDENTITY_CURVE

    def is_identity(self) -> bool:
        return (abs(self.exposure) < 1e-6 and abs(self.gamma - 1.0) < 1e-6 and abs(self.contrast) < 1e-6
                and abs(self.brightness) < 1e-6 and curve_is_identity(self.curve))

    def to_json(self) -> dict:
        return {"exposure": round(self.exposure, 4), "gamma": round(self.gamma, 4),
                "contrast": round(self.contrast, 4), "brightness": round(self.brightness, 4),
                "curve": [[round(x, 4), round(y, 4)] for x, y in self.curve]}

    @classmethod
    def from_json(cls, data) -> "Adjust":
        if not isinstance(data, dict):
            return cls()

        def number(key, default, lo, hi):
            value = data.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return default
            return float(min(max(value, lo), hi))
        return cls(exposure=number("exposure", 0.0, *EXPOSURE_RANGE),
                   gamma=number("gamma", 1.0, *GAMMA_RANGE),
                   contrast=number("contrast", 0.0, *CONTRAST_RANGE),
                   brightness=number("brightness", 0.0, *BRIGHTNESS_RANGE),
                   curve=clean_curve(data.get("curve")))


@dataclass
class Balance:
    """Adjustments of the five layers, and the automatic NIR."""
    layers: Dict[str, Adjust] = field(default_factory=lambda: {k: Adjust() for k in LAYERS})
    nir_auto: bool = False

    def layer(self, name: str) -> Adjust:
        return self.layers.setdefault(name, Adjust())

    def is_identity(self) -> bool:
        return not self.nir_auto and all(self.layer(k).is_identity() for k in LAYERS)

    def copy(self) -> "Balance":
        return Balance.from_json(self.to_json())

    def to_json(self) -> dict:
        return {"nir_auto": self.nir_auto, "layers": {k: self.layer(k).to_json() for k in LAYERS}}

    @classmethod
    def from_json(cls, data) -> "Balance":
        if not isinstance(data, dict):
            return cls()
        layers = data.get("layers") if isinstance(data.get("layers"), dict) else {}
        return cls(layers={k: Adjust.from_json(layers.get(k)) for k in LAYERS},
                   nir_auto=data.get("nir_auto") is True)


@dataclass
class Settings:
    """The mission balance, and the images with a balance of their own."""
    mission: Balance = field(default_factory=Balance)
    points: Dict[int, Balance] = field(default_factory=dict)

    def balance_for(self, number: int) -> Balance:
        return self.points.get(number, self.mission)

    def has_own(self, number: int) -> bool:
        return number in self.points

    def is_identity(self) -> bool:
        return self.mission.is_identity() and all(b.is_identity() for b in self.points.values())

    def to_json(self) -> dict:
        return {"version": VERSION, "mission": self.mission.to_json(),
                "points": {f"{n:04d}": b.to_json() for n, b in sorted(self.points.items())}}

    @classmethod
    def from_json(cls, data) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        points = {}
        for key, value in (data.get("points") or {}).items() if isinstance(data.get("points"), dict) else []:
            if str(key).isdigit():
                points[int(key)] = Balance.from_json(value)
        return cls(mission=Balance.from_json(data.get("mission")), points=points)


def settings_path(mission: Path) -> Path:
    return Path(mission) / BALANCE_FOLDER / SETTINGS_NAME


def load_settings(mission: Path) -> Settings:
    """The saved settings (no balance when there are none or they cannot be read)."""
    try:
        with open(settings_path(mission), encoding="utf-8") as f:
            return Settings.from_json(json.load(f))
    except (OSError, ValueError):
        return Settings()


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_settings(mission: Path, settings: Settings) -> Path:
    path = settings_path(mission)
    _write_json(path, settings.to_json())
    return path


def is_active(mission: Path) -> bool:
    """A balance is set: the map uses the balanced bands."""
    return settings_path(mission).is_file() and not load_settings(mission).is_identity()


# ---------------------------------------------------------------------------
#  Tone curve and transfer
# ---------------------------------------------------------------------------
def clean_curve(points) -> Tuple[Tuple[float, float], ...]:
    """Handles sorted by x, in 0..1, x strictly increasing, the two ends kept
    (identity when unreadable)."""
    out = []
    try:
        for x, y in points or ():
            x, y = float(x), float(y)
            if math.isfinite(x) and math.isfinite(y):
                out.append((min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)))
    except (TypeError, ValueError):
        return IDENTITY_CURVE
    out.sort()
    kept = []
    for x, y in out:
        if kept and x - kept[-1][0] < 1e-3:
            continue
        kept.append((x, y))
    return tuple(kept) if len(kept) >= 2 else IDENTITY_CURVE


def curve_is_identity(curve) -> bool:
    return all(abs(x - y) < 1e-6 for x, y in curve) and curve[0][0] < 1e-6 and curve[-1][0] > 1 - 1e-6


def curve_eval(curve, x: np.ndarray) -> np.ndarray:
    """Monotone cubic spline (Fritsch-Carlson) through the handles: no
    overshoot between them; flat before the first and after the last."""
    xs = np.array([p[0] for p in curve], dtype=np.float64)
    ys = np.array([p[1] for p in curve], dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    n = len(xs)
    if n == 2:
        return np.interp(x, xs, ys)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.empty(n)
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, n - 1):
        if d[k - 1] * d[k] <= 0:
            m[k] = 0.0
        else:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    xc = np.clip(x, xs[0], xs[-1])
    i = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, n - 2)
    t = (xc - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    y = ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i]
         + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])
    return np.clip(y, 0.0, 1.0)


def transfer(adjust: Adjust, x: np.ndarray) -> np.ndarray:
    """The adjustment applied to values in 0..1 (see the module docstring)."""
    x = np.clip(np.asarray(x, dtype=np.float64) * 2.0 ** adjust.exposure, 0.0, 1.0)
    if abs(adjust.gamma - 1.0) > 1e-9:
        x = x ** (1.0 / adjust.gamma)
    x = (x - 0.5) * 3.0 ** adjust.contrast + 0.5 + adjust.brightness / 2.0
    x = np.clip(x, 0.0, 1.0)
    if not curve_is_identity(adjust.curve):
        x = curve_eval(adjust.curve, x)
    return x


_X16 = np.arange(65536, dtype=np.float64) / 65535.0


def own_transfer(balance: Balance, band: str, x: np.ndarray) -> np.ndarray:
    """A band through its own layers: "rgb" then its layer (visible), "nir"."""
    if band == "nir":
        return transfer(balance.layer("nir"), x)
    return transfer(balance.layer(band), transfer(balance.layer("rgb"), x))


def band_transfer(balance: Balance, band: str, x: np.ndarray) -> np.ndarray:
    """What a band goes through: its own layers, then "all" (the same for the
    four bands, last: the NIR matched to the visible stays matched)."""
    return transfer(balance.layer("all"), own_transfer(balance, band, x))


def lut16(balance: Balance, band: str) -> np.ndarray:
    """uint16 -> uint16 look-up table of a band."""
    return np.round(band_transfer(balance, band, _X16) * 65535.0).astype(np.uint16)


def lut8(balance: Balance, band: str) -> np.ndarray:
    """uint16 -> uint8 look-up table (display)."""
    return np.round(band_transfer(balance, band, _X16) * 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
#  Automatic NIR
# ---------------------------------------------------------------------------
def stats_copy(bands: np.ndarray) -> np.ndarray:
    """A small copy (H x W x 4, uint16) of the bands, by taking one pixel in k:
    the same input always gives the same copy (the preview and the written
    image compute the same automatic NIR)."""
    k = max(1, int(round(bands.shape[1] / STATS_WIDTH)))
    return np.ascontiguousarray(bands[::k, ::k])


def auto_nir(balance: Balance, small: np.ndarray) -> Tuple[float, float]:
    """(exposure, gamma) of the NIR that give it the median and the 98th
    percentile of the visible (mean of the bands after their adjustments).

    Solved exactly on the two percentiles:  (g n50)^(1/gamma) = t50  and
    (g n98)^(1/gamma) = t98."""
    vis = np.mean([own_transfer(balance, b, small[..., i].astype(np.float64) / 65535.0)
                   for i, b in enumerate(VISIBLE_LAYERS)], axis=0)
    nir = small[..., 3].astype(np.float64) / 65535.0
    t50, t98 = np.percentile(vis, AUTO_PERCENTILES)
    n50, n98 = np.percentile(nir, AUTO_PERCENTILES)
    eps = 1e-4
    t50, t98 = min(max(t50, eps), 1 - eps), min(max(t98, eps), 1.0)
    n50, n98 = max(n50, eps), max(n98, eps)
    gamma = 1.0
    if n98 > n50 * 1.01 and t98 > t50 * 1.01:
        gamma = (math.log(n98) - math.log(n50)) / (math.log(t98) - math.log(t50))
    gamma = min(max(gamma, GAMMA_RANGE[0]), GAMMA_RANGE[1])
    exposure = (gamma * math.log(t50) - math.log(n50)) / math.log(2.0)
    exposure = min(max(exposure, EXPOSURE_RANGE[0]), EXPOSURE_RANGE[1])
    return round(exposure, 4), round(gamma, 4)


def effective(balance: Balance, small: Optional[np.ndarray]) -> Balance:
    """The balance applied to an image: with the automatic NIR, its exposure
    and gamma computed on the image (``small``: ``stats_copy`` of its bands)."""
    if not balance.nir_auto or small is None:
        return balance
    out = balance.copy()
    nir = out.layer("nir")
    nir.exposure, nir.gamma = auto_nir(balance, small)
    out.nir_auto = False
    return out


# ---------------------------------------------------------------------------
#  Images of the mission
# ---------------------------------------------------------------------------
def source_paths(mission: Path, number: int) -> List[Path]:
    folder = Path(mission) / SOURCE_FOLDER
    return [folder / f"IRD_{number:04d}_{k}.tif" for k in range(1, 5)]


def balanced_paths(mission: Path, number: int) -> List[Path]:
    folder = Path(mission) / BALANCE_FOLDER
    return [folder / f"IRD_{number:04d}_{k}.tif" for k in range(1, 5)]


def record_path(mission: Path, number: int) -> Path:
    return Path(mission) / BALANCE_FOLDER / f"IRD_{number:04d}_bal.json"


def quartet_numbers(mission: Path) -> List[int]:
    """Numbers of the images whose four bands are in imgMultispectral."""
    folder = Path(mission) / SOURCE_FOLDER
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        m = _IRD.match(name)
        if m and all(p.is_file() for p in source_paths(mission, int(m.group(1)))):
            out.append(int(m.group(1)))
    return sorted(out)


def _signature(path: Path) -> List[int]:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


def _read_record(mission: Path, number: int) -> Optional[dict]:
    try:
        with open(record_path(mission, number), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def point_state(mission: Path, number: int, settings: Settings) -> str:
    """STATE_NONE, STATE_DONE or STATE_STALE (see the module docstring)."""
    record = _read_record(mission, number)
    if record is None or not all(p.is_file() for p in balanced_paths(mission, number)):
        return STATE_NONE
    if record.get("balance") != settings.balance_for(number).to_json():
        return STATE_STALE
    try:
        sources = [_signature(p) for p in source_paths(mission, number)]
    except OSError:
        return STATE_STALE
    return STATE_DONE if record.get("sources") == sources else STATE_STALE


def read_bands(paths: Sequence[Path]) -> np.ndarray:
    """The four bands, H x W x 4 uint16."""
    import cv2
    from image_io import imread
    bands = []
    for path in paths:
        band = imread(path, cv2.IMREAD_UNCHANGED)
        if band is None:
            raise OSError(f"Cannot read {path}")
        if band.ndim != 2:
            raise ValueError(f"{path.name} is not a single band image")
        if band.dtype != np.uint16:
            band = (band.astype(np.float64) * (65535.0 / (np.iinfo(band.dtype).max
                                                        if band.dtype.kind in "ui" else 1.0)))
            band = np.clip(band, 0, 65535).astype(np.uint16)
        bands.append(band)
    if len({b.shape for b in bands}) != 1:
        raise ValueError("The four bands do not have the same size")
    return np.stack(bands, axis=-1)


def apply(balance: Balance, bands: np.ndarray) -> np.ndarray:
    """The bands (H x W x 4 uint16) balanced (``balance`` already effective)."""
    out = np.empty_like(bands)
    for i, band in enumerate(BANDS):
        out[..., i] = lut16(balance, band)[bands[..., i]]
    return out


def _copy_metadata(pairs: Sequence[Tuple[Path, Path]]) -> None:
    """Every tag of each original copied to its balanced band (EXIF, GPS,
    the XMP band names OpenDroneMap reads): one ExifTool process."""
    import config as cf
    xmp_conf = Path(__file__).resolve().parent.parent / "thirdparty" / "exiftool" / "xmp.config"
    cmd = [cf.EXIFTOOLPATH]
    if xmp_conf.is_file():
        cmd += ["-config", str(xmp_conf)]
    for k, (src, dst) in enumerate(pairs):
        if k:
            cmd.append("-execute")
        cmd += ["-TagsFromFile", str(src), "-all:all", "-m", "-overwrite_original", str(dst)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as error:
        raise OSError(f"ExifTool cannot be started ({error}): the metadata of the balanced "
                      "images cannot be written") from error
    if result.returncode != 0:
        raise OSError(f"ExifTool failed on the balanced images: {result.stderr.strip()[:300]}")


def write_point(mission: Path, number: int, settings: Settings, metadata: bool = True) -> dict:
    """Write the balanced bands of an image and its IRD_XXXX_bal.json.
    Returns the record written."""
    import cv2
    import shutil
    from image_io import imwrite
    mission = Path(mission)
    sources = source_paths(mission, number)
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(f"{path.name} is missing (Step 4 writes it)")
    signatures = [_signature(p) for p in sources]
    bands = read_bands(sources)
    balance = settings.balance_for(number)
    applied = effective(balance, stats_copy(bands))
    out = apply(applied, bands)
    del bands
    targets = balanced_paths(mission, number)
    targets[0].parent.mkdir(parents=True, exist_ok=True)
    record_path(mission, number).unlink(missing_ok=True)       # incomplete until the record is written
    tmps = [t.with_name(t.stem + ".tmp.tif") for t in targets]
    for i, tmp in enumerate(tmps):
        if not imwrite(tmp, np.ascontiguousarray(out[..., i]), [cv2.IMWRITE_TIFF_COMPRESSION, 1]):
            raise OSError(f"Cannot write {tmp}")
    if metadata:
        _copy_metadata(list(zip(sources, tmps)))
    for tmp, target in zip(tmps, targets):
        os.replace(tmp, target)
    for sidecar in sources[0].parent.glob(f"IRD_{number:04d}_*.exif"):
        shutil.copy2(sidecar, targets[0].parent / sidecar.name)
    record = {
        "version": VERSION,
        "image": f"IRD_{number:04d}",
        "written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "own_balance": settings.has_own(number),
        "balance": balance.to_json(),
        "applied": applied.to_json(),
        "sources": signatures,
        "source_files": [str(p.relative_to(mission)) for p in sources],
    }
    _write_json(record_path(mission, number), record)
    return record


def remove_point(mission: Path, number: int) -> None:
    """Delete the balanced bands of an image (back to the originals)."""
    record_path(mission, number).unlink(missing_ok=True)
    for path in balanced_paths(mission, number):
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
#  The map (Step 6, Build the map)
# ---------------------------------------------------------------------------
def number_of(path) -> Optional[int]:
    m = _IRD.match(Path(path).name)
    return int(m.group(1)) if m else None


def apply_to_manifest(mission: Path, manifest: dict, log: Callable[[str], None] = print,
                      should_stop: Optional[Callable[[], bool]] = None) -> Optional[dict]:
    """With a balance set, give the map the balanced bands: those missing or
    out of date are written first, then the files of each image of the
    selection (``manifest["image_quartets"]``) point to them.

    Returns a summary {"written", "up_to_date", "images"} (None: no balance,
    the map uses the original bands)."""
    mission = Path(mission)
    if not is_active(mission):
        return None
    settings = load_settings(mission)
    quartets = manifest.get("image_quartets") or []
    written = up_to_date = 0
    for k, quartet in enumerate(quartets):
        files = quartet.get("files") or {}
        if list(files) != list(BANDS):
            continue            # not four bands (visible only mission): left as is
        number = number_of(files["red"])
        if number is None:
            continue
        if point_state(mission, number, settings) == STATE_DONE:
            up_to_date += 1
        else:
            if should_stop is not None and should_stop():
                raise InterruptedError("Spectral balance stopped")
            log(f"Spectral balance: IRD_{number:04d} ({k + 1}/{len(quartets)})")
            write_point(mission, number, settings)
            written += 1
        quartet["files"] = {band: str(path.resolve())
                            for band, path in zip(BANDS, balanced_paths(mission, number))}
    return {"written": written, "up_to_date": up_to_date, "images": written + up_to_date,
            "settings": str(settings_path(mission))}


def states(mission: Path, numbers: Iterable[int], settings: Optional[Settings] = None) -> Dict[int, str]:
    settings = settings or load_settings(mission)
    return {n: point_state(mission, n, settings) for n in numbers}
