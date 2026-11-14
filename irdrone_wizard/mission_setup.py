# -*- coding: utf-8 -*-
"""
New mission (Step 1): find the images, describe the mission, create its folder.

No Qt here: the new mission window (IRD_Interactive_new_mission.py) uses
these functions; the copy itself is done by the Step 1 workers.

* The images are found on the SD cards: every mounted volume with a DCIM
  folder is scanned for DNG (visible, drone) and RAW (infrared, SJCam) images.
* The take-off image is the first visible image (lowest number): its EXIF
  gives the date, the time and the position of the mission.
* mission_parameters.json gets exactly the keys written by the classic Step 1
  form (Window_create_file_structure), so the next steps see no difference;
  a visible only mission (mission_type.py) also gets "mission type": "visible".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import mission_type as MT

VIS_SUFFIXES = {".dng"}
NIR_SUFFIXES = {".raw"}
GEO_PARAMETER_KEYS = {   # same as IRD_Interactive_1.GEO_PARAMETER_KEYS
    "lieu_dit": "Place name",
    "code_postal": "Postal code",
    "region": "Region",
    "pays": "Country",
}
MISSION_FOLDERS = ("AerialPhotography", "FlightAnalytics", "ImgIRdrone", "Synchro", "mapping_MULTI",
                   "cameras", "AerialPhotography/VIS", "AerialPhotography/NIR")
# A visible only mission has no infrared images and no synchronisation
VISIBLE_SKIPPED_FOLDERS = ("Synchro", "AerialPhotography/NIR")
FOLDER_ICONS = {"": "IRdrone_appli.ico", "AerialPhotography": "AerialPhoto.ico",
                "FlightAnalytics": "FlyAnalytic.ico", "ImgIRdrone": "ImgIRdrone.ico",
                "Synchro": "synchro.ico", "mapping_MULTI": "mapping_MULTI.ico", "cameras": "camera.ico"}

# Values of the form, as in the classic Step 1 form
DEFAULT_FORM = {
    "description": "",
    "pilot": "",
    "pilot_id": "",
    "vis_timelapse": 2,
    "vis_deltatime": 0.0,
    "nir_maker": "SJCam",
    "nir_model": "M20",
    "nir_format": "RAW",
    "nir_timelapse": 3,
    "nir_deltatime": -30.0,
    "filter_maker": "KOLARI VISION USA",
    "filter_band": 810,
}

_NUM = re.compile(r"(\d+)(?!.*\d)")
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


# ---------------------------------------------------------------------------
#  Image folders
# ---------------------------------------------------------------------------
@dataclass
class FolderSummary:
    folder: Path
    files: List[Path] = field(default_factory=list)   # in shooting order
    size: int = 0
    first: Optional[dt.datetime] = None               # file times (camera clock)
    last: Optional[dt.datetime] = None

    @property
    def count(self) -> int:
        return len(self.files)

    def describe(self) -> str:
        if not self.files:
            return "no image"
        text = f"{self.count} images · {human_size(self.size)}"
        if self.first and self.last:
            same_day = self.first.date() == self.last.date()
            text += (f" · {self.first:%d/%m/%Y %H:%M} → " +
                     (f"{self.last:%H:%M}" if same_day else f"{self.last:%d/%m/%Y %H:%M}"))
        return text


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def frame_number(path: Path) -> int:
    m = _NUM.search(Path(path).stem)
    return int(m.group(1)) if m else -1


def summarize(folder: Path, suffixes: Iterable[str]) -> FolderSummary:
    """Images of `folder` (not its sub-folders) with one of the suffixes."""
    suffixes = {s.lower() for s in suffixes}
    folder = Path(folder)
    out = FolderSummary(folder=folder)
    try:
        entries = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes]
    except OSError:
        return out
    entries.sort(key=lambda p: (frame_number(p), p.name))
    times = []
    for p in entries:
        try:
            st = p.stat()
        except OSError:
            continue
        out.files.append(p)
        out.size += st.st_size
        times.append(st.st_mtime)
    if times:
        out.first = dt.datetime.fromtimestamp(min(times))
        out.last = dt.datetime.fromtimestamp(max(times))
    return out


def image_folders(root: Path, suffixes: Iterable[str], depth: int = 3) -> List[FolderSummary]:
    """Folders under `root` (up to `depth` levels) holding images, most images first."""
    found = []
    root = Path(root)

    def walk(folder: Path, level: int):
        s = summarize(folder, suffixes)
        if s.count:
            found.append(s)
        if level >= depth:
            return
        try:
            subs = sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            return
        for sub in subs:
            walk(sub, level + 1)
    walk(root, 0)
    found.sort(key=lambda s: -s.count)
    return found


@dataclass
class CardImages:
    """Images found on a memory card (or any volume with a DCIM folder)."""
    volume: Path
    name: str
    band: str                 # "VIS" or "NIR"
    summary: FolderSummary


def find_card_images(volumes: Iterable[tuple]) -> List[CardImages]:
    """Visible and infrared image folders on the mounted volumes.

    `volumes`: (root path, display name). Only volumes with a DCIM folder are
    scanned (SD cards of cameras and drones): the system disks are not read."""
    out = []
    for root, name in volumes:
        dcim = Path(root) / "DCIM"
        if not dcim.is_dir():
            continue
        for band, suffixes in (("VIS", VIS_SUFFIXES), ("NIR", NIR_SUFFIXES)):
            folders = image_folders(dcim, suffixes, depth=2)
            if folders:
                out.append(CardImages(volume=Path(root), name=name or str(root), band=band, summary=folders[0]))
    return out


def clock_gap(vis: FolderSummary, nir: FolderSummary) -> Optional[float]:
    """Difference (s) between the first images of both cameras, by their file times."""
    if vis.first is None or nir.first is None:
        return None
    return (nir.first - vis.first).total_seconds()


# ---------------------------------------------------------------------------
#  Take-off image
# ---------------------------------------------------------------------------
def takeoff_image(vis: FolderSummary) -> Optional[Path]:
    """First visible image: the drone is still on the ground."""
    return vis.files[0] if vis.files else None


def flight_index(count: int) -> int:
    """An image taken during the flight: two thirds of the way (after the
    take-off, the synchronisation and the climb, in the survey)."""
    return max(0, min(count - 1, (2 * count) // 3))


def nir_preview_jpeg(nir: FolderSummary, index: int = 0) -> Optional[Path]:
    """A JPEG to show for the infrared image `index` (the RAW have no preview).
    The SJCam writes a JPEG beside the RAW, under the same name or, on the
    M20, under the next name (..._001.RAW, ..._002.JPG): the JPEG with the
    same name as the RAW, else the first JPEG that follows it."""
    if not nir.files:
        return None
    first = nir.files[max(0, min(index, len(nir.files) - 1))]
    for ext in (".JPG", ".jpg", ".jpeg", ".JPEG"):
        same = first.with_suffix(ext)
        if same.is_file():
            return same
    try:
        jpegs = sorted((p for p in nir.folder.iterdir()
                        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")),
                       key=lambda p: p.name.lower())
    except OSError:
        return None
    after = [p for p in jpegs if p.name.lower() > first.name.lower()]
    return (after or jpegs or [None])[0]


def read_takeoff(path: Path) -> dict:
    """mission_parameters_light of the classic form, from the EXIF of the take-off
    image (no network: the place is added by add_location)."""
    import IRD_Interactive_utils as Uti
    path = Path(path)
    lat_e, lon_e, alt_e, date_time, maker, model, serial = Uti.extract_exif(str(path))
    if date_time in (None, "None"):
        raise ValueError(f"No date in the EXIF of {path.name}")
    lat, lon, alt = Uti.convert_coordinates(lat_e, lon_e, alt_e)
    num = frame_number(path)
    suffix = path.suffix[1:].lower()
    light = {
        "File path": str(path),
        "original name image take-off": path.name,
        "name image take-off": f"VIS_{num:04d}.{suffix}",
        "suffix image take-off": suffix,
        "Maker": str(maker),
        "Model": str(model),
        "Body serial number": str(serial),
        "Date Exif": str(date_time),
        "GPS N-S": "N" if lat >= 0 else "S",
        "GPS E-W": "E" if lon >= 0 else "W",
        "GPS lat": lat,
        "GPS lon": lon,
        "GPS alti": 0.0,
        "GPS drone alti": alt,
        "Location": "",
    }
    return light


def add_location(light: dict, geo: Optional[dict]) -> dict:
    """Ground altitude and address (IGN / OpenStreetMap answer) into `light`."""
    geo = geo or {}
    if isinstance(geo.get("z"), (int, float)):
        light["GPS alti"] = float(geo["z"])
    light["Location"] = str(geo.get("ville") or light.get("Location") or "")
    for key in GEO_PARAMETER_KEYS.values():
        light.pop(key, None)
    for geo_key, key in GEO_PARAMETER_KEYS.items():
        value = geo.get(geo_key)
        if value is not None and str(value).strip():
            light[key] = str(value).strip()
    return light


def locate(light: dict) -> dict:
    """Ask IGN / OpenTopoData (ground altitude) and OpenStreetMap (address).
    Network: seconds; never raises (falls back to an empty answer)."""
    import IRD_interactive_geo as Geo
    try:
        geo = Geo.extract_alti_IGN([(light["GPS lat"], light["GPS lon"])], bypass=False)[0]
        geo = Geo.extract_geoTag(geo, bypass=False, verbose=False)
    except Exception as e:  # offline: the mission is created without the address
        print(f"Location not found: {e}")
        geo = {}
    return geo


def takeoff_datetime(light: dict) -> dt.datetime:
    return dt.datetime.strptime(light["Date Exif"], "%Y:%m:%d %H:%M:%S")


# ---------------------------------------------------------------------------
#  Mission parameters and folder
# ---------------------------------------------------------------------------
def clean_location(text: str) -> str:
    """Location usable in a folder name (accents kept, separators removed)."""
    return _BAD_NAME.sub("-", (text or "").strip()).strip(" .-")


def mission_folder_name(when: dt.datetime, location: str) -> str:
    loc = clean_location(location)
    return f"FLY-{when:%Y%m%d}-{when:%H%M}" + (f"-{loc}" if loc else "")


def build_mission_parameters(light: dict, form: dict, user_dir: Path, kind: str = MT.MULTISPECTRAL) -> dict:
    """mission_parameters.json content (keys of the classic Step 1 form).
    kind: mission_type.MULTISPECTRAL or VISIBLE (stored only for a visible only
    mission: a mission without the key is multispectral)."""
    if kind not in MT.TYPES:
        raise ValueError(f"Unknown mission type: {kind}")
    f = dict(DEFAULT_FORM)
    f.update({k: v for k, v in form.items() if v is not None})
    when = takeoff_datetime(light)
    folder = (Path(user_dir) / mission_folder_name(when, form.get("location", light.get("Location", ""))))
    folder_str = os.path.normpath(str(folder)).replace("\\", "/")
    params = {
        "File path mission": folder_str,
        "original File path take-off": light["File path"],
        "original name image take-off": light["original name image take-off"],
        "name image take-off": light["name image take-off"],
        "suffix image take-off": light["suffix image take-off"],
        "path mission image take-off": str(Path(folder_str) / "AerialPhotography" / "VIS" /
                                           light["name image take-off"]),
        "Body serial number": light["Body serial number"],
        "Date Exif": f"{when:%Y:%m:%d} {when:%H:%M:%S}",
        "Date": f"{when:%Y:%m:%d}",
        "Time": f"{when:%H:%M:%S}",
        "Location": clean_location(form.get("location", light.get("Location", ""))),
        "Description": str(f["description"]),
        "GPS coordinate": f"{light['GPS N-S']} {float(light['GPS lat'])} {light['GPS E-W']} {float(light['GPS lon'])}",
        "GPS N-S": light["GPS N-S"],
        "GPS lat": float(light["GPS lat"]),
        "GPS E-W": light["GPS E-W"],
        "GPS lon": float(light["GPS lon"]),
        "GPS alti": float(light.get("GPS alti") or 0.0),
        "GPS drone alti": light["GPS drone alti"],
        "Pilot": str(f["pilot"]),
        "Pilot ID": str(f["pilot_id"]),
        "camera VIS maker": light["Maker"],
        "camera VIS ID": light["Model"],
        "camera VIS timelapse": int(f["vis_timelapse"]),
        "camera VIS deltatime": float(f["vis_deltatime"]),
        "img VIS ext": Path(light["File path"]).suffix[1:],
        "camera NIR maker": str(f["nir_maker"]),
        "camera NIR ID": str(f["nir_model"]),
        "camera NIR timelapse": int(f["nir_timelapse"]),
        "camera NIR deltatime": float(f["nir_deltatime"]),
        "original img NIR ext": str(f["nir_format"]),
        "camera NIR filter maker": str(f["filter_maker"]),
        "camera NIR filter band": int(f["filter_band"]),
        "synchro": "Synchro/synchro.npy",
        "output": "ImgIRdrone",
        "visible": "AerialPhotography/VIS/*.dng",
        "nir": "AerialPhotography/NIR/*.dng",
        "AerialPhotography folder": "AerialPhotography",
        "FlightAnalytics folder": "FlightAnalytics",
        "ImgIRdrone folder": "ImgIRdrone",
        "Synchro folder": "Synchro",
        "ODM folder": "mapping_MULTI",
        "cameras folder": "cameras",
    }
    for key in GEO_PARAMETER_KEYS.values():
        if key in light:
            params[key] = light[key]
    if kind == MT.VISIBLE:
        params[MT.KEY] = MT.VISIBLE
    return params


def create_mission(params: dict, icon_dir: Optional[Path] = None) -> Path:
    """Folders of the mission (existing ones are kept), mission_parameters.json,
    the take-off image and transfer_info_VIS_dng.json (first version)."""
    base = Path(params["File path mission"])
    visible = MT.is_visible(params)
    for sub in MISSION_FOLDERS:
        if not (visible and sub in VISIBLE_SKIPPED_FOLDERS):
            (base / sub).mkdir(parents=True, exist_ok=True)
    if icon_dir is not None:
        try:
            import IRD_Interactive_utils as Uti
            for sub, icon in FOLDER_ICONS.items():
                if (Path(icon_dir) / icon).is_file() and (base / sub).is_dir():
                    Uti.change_icon(base / sub if sub else base, Path(icon_dir) / icon)
        except Exception as e:  # cosmetic
            print(f"Folder icons not set: {e}")
    with open(base / "FlightAnalytics" / "mission_parameters.json", "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=4)
    src = Path(params["original File path take-off"])
    dst = Path(params["path mission image take-off"])
    if src.is_file() and not dst.is_file():
        shutil.copy2(src, dst)
    vis = base / "AerialPhotography" / "VIS"
    info = vis / "transfer_info_VIS_dng.json"
    if not info.is_file():
        number = frame_number(Path(params["name image take-off"]))   # VIS_0161.dng -> 161
        data = {
            "spectral_band": "VIS",
            "img_suffix": "dng",
            "tkoff": {"outputFolder": str(vis), "original name": params["original name image take-off"],
                      "idMin": number, "idMax": number, "listCopiedImages": [params["name image take-off"]]},
            "sync": {"outputFolder": str(vis)},
            "fly": {"outputFolder": str(vis)},
        }
        with open(info, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    return base


def copy_sizes(vis: FolderSummary, nir: Optional[FolderSummary]) -> int:
    """Disk space the copy needs: the visible DNG plus the converted infrared
    (a DNG is about the size of its RAW). nir None: visible only mission."""
    return vis.size + (nir.size if nir is not None else 0)


def form_from_settings(values: Dict[str, object]) -> dict:
    """Saved form values (QSettings strings) cast to the DEFAULT_FORM types."""
    out = dict(DEFAULT_FORM)
    for key, default in DEFAULT_FORM.items():
        if key not in values or values[key] is None:
            continue
        try:
            out[key] = type(default)(values[key])
        except (TypeError, ValueError):
            pass
    return out


# ---------------------------------------------------------------------------
#  Details of an existing mission (Step 1 done): edited without the SD cards
# ---------------------------------------------------------------------------
# form key -> (mission_parameters.json key, type). The folder name, the take-off
# image, the date and the position are not editable: the images are already there.
EDITABLE_DETAILS = {
    "location": ("Location", str),
    "description": ("Description", str),
    "pilot": ("Pilot", str),
    "pilot_id": ("Pilot ID", str),
    "vis_timelapse": ("camera VIS timelapse", int),
    "vis_deltatime": ("camera VIS deltatime", float),
    "nir_maker": ("camera NIR maker", str),
    "nir_model": ("camera NIR ID", str),
    "nir_timelapse": ("camera NIR timelapse", int),
    "nir_deltatime": ("camera NIR deltatime", float),
    "filter_maker": ("camera NIR filter maker", str),
    "filter_band": ("camera NIR filter band", int),
}


def mission_parameters_path(folder: Path) -> Path:
    return Path(folder) / "FlightAnalytics" / "mission_parameters.json"


def read_mission_parameters(folder: Path) -> dict:
    with open(mission_parameters_path(folder), encoding="utf-8") as f:
        params = json.load(f)
    if not isinstance(params, dict):
        raise ValueError("mission_parameters.json is not a dictionary")
    return params


def details_form(params: dict) -> dict:
    """Form values of an existing mission (defaults for the missing keys)."""
    form = {}
    for k, (key, kind) in EDITABLE_DETAILS.items():
        value = params.get(key, DEFAULT_FORM.get(k, ""))
        try:
            form[k] = kind(value)
        except (TypeError, ValueError):
            form[k] = kind(DEFAULT_FORM.get(k, kind()))
    return form


def update_mission_details(folder: Path, form: dict) -> List[str]:
    """Write the edited details into mission_parameters.json (other keys kept,
    previous file kept as .bak). Returns the json keys that changed."""
    path = mission_parameters_path(folder)
    params = read_mission_parameters(folder)
    changed = []
    for k, value in form.items():
        if k not in EDITABLE_DETAILS:
            continue
        key, kind = EDITABLE_DETAILS[k]
        value = clean_location(value) if k == "location" else kind(value)
        if params.get(key) != value:
            params[key] = value
            changed.append(key)
    if changed:
        shutil.copy2(path, path.with_suffix(".json.bak"))
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    return changed
