# -*- coding: utf-8 -*-
"""Step 6 logic: archiving (cleaning) of a mission folder.

The mission folder is cleaned in place and the operation is irreversible
(files are deleted, not sent to the recycle bin). Only the essential elements
that would allow the mission to be processed again are kept:

* root: ``AerialPhotography``, ``cameras``, ``FlightAnalytics``, ``ImgIRdrone``,
  ``mapping_MULTI`` (and ``mapping_MULTI_*``), ``Synchro``, ``desktop.ini`` (everything else is deleted);
* ``AerialPhotography``: the ``VIS`` and ``NIR`` folders, ``shoot_points.json``;
* ``AerialPhotography/VIS`` and ``NIR``: ``<BAND>_XXXX.dng`` and ``.exif``,
  ``time_line.json``, ``transfer_info_<BAND>_dng.json``;
* ``cameras``, ``FlightAnalytics``, ``mapping_MULTI`` and the previous maps
  (``mapping_MULTI_<date>``, set aside by Step 5): untouched;
* ``ImgIRdrone``: ``VIS_XXXX.jpg``, ``VIR_XXXX_local.jpg``,
  ``VIS_XXXX_motion_model.npy``, ``NDVI_XXXX_local.jpg``, ``NIR_XXXX_local.jpg``,
  ``shoot_points.json``, ``shoot_points_failed_summary.json``;
* ``Synchro``: ``check_time_alignment.png``, ``check_time_before_alignment.png``.

``desktop.ini`` is kept wherever it exists. All name comparisons ignore case.
Missing folders are never created. The module has no Qt dependency:
``build_plan`` only reads the disk, ``execute_archive`` deletes.
"""

import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

MANIFEST_NAME = "archive_manifest.json"
LOG_NAME = "archive_log.txt"
SCHEMA_VERSION = "1.0"

_FLAGS = re.IGNORECASE
_DESKTOP = re.compile(r"^desktop\.ini$", _FLAGS)

# Root folders kept as they are (no cleaning inside).
UNTOUCHED_DIRS = ("cameras", "flightanalytics", "mapping_multi")
# Root folders that are cleaned inside.
CLEANED_DIRS = ("aerialphotography", "imgirdrone", "synchro")


@dataclass
class DeleteItem:
    """A top-level entry (file or folder) that will be deleted."""

    path: Path
    folder: str          # label of the cleaned folder it belongs to
    is_dir: bool
    size: int
    n_files: int


@dataclass
class ArchivePlan:
    """Result of the analysis of a mission folder."""

    mission: Path
    delete_items: List[DeleteItem] = field(default_factory=list)
    kept_counts: Dict[str, int] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    already_archived: bool = False
    mission_bytes: int = 0    # size of the whole mission folder when analysed

    @property
    def final_bytes(self) -> int:
        """Size of the mission folder once archived."""
        return max(self.mission_bytes - self.total_bytes, 0)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.delete_items)

    @property
    def total_files(self) -> int:
        return sum(item.n_files for item in self.delete_items)

    def summary_lines(self) -> List[str]:
        """Human readable summary of what would be (or was) deleted."""
        lines = []
        by_folder: Dict[str, List[DeleteItem]] = {}
        for item in self.delete_items:
            by_folder.setdefault(item.folder, []).append(item)
        for folder, items in by_folder.items():
            n_files = sum(i.n_files for i in items)
            size = sum(i.size for i in items)
            lines.append(f"{folder}: {n_files} file(s) to delete ({format_size(size)})")
            for item in items:
                if item.is_dir:
                    lines.append(f"      folder  {item.path.name}  ({format_size(item.size)})")
        for folder, count in self.kept_counts.items():
            lines.append(f"{folder}: {count} file(s) kept")
        for name in self.missing:
            lines.append(f"Missing (not created): {name}")
        lines.append(f"Total to delete: {self.total_files} file(s), {format_size(self.total_bytes)}")
        return lines


def format_size(n_bytes: float) -> str:
    """Format a size in bytes with a readable unit."""
    value = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _lp(path) -> str:
    """Path usable beyond the 260 characters limit on Windows."""
    p = os.path.abspath(str(path))
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        p = "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p
    return p


def _is_link(path) -> bool:
    """True for symbolic links and Windows junctions (never followed)."""
    try:
        st = os.lstat(_lp(path))
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _children(folder: Path) -> List[Tuple[str, Path, bool]]:
    """List (name, path, is_dir) of the entries of a folder."""
    result = []
    with os.scandir(_lp(folder)) as it:
        for entry in it:
            is_dir = entry.is_dir(follow_symlinks=False) and not _is_link(entry.path)
            result.append((entry.name, folder / entry.name, is_dir))
    return result


def _find(folder: Path, name: str) -> Optional[Path]:
    """Find an entry of a folder ignoring case."""
    try:
        for entry_name, path, _ in _children(folder):
            if entry_name.lower() == name.lower():
                return path
    except OSError:
        pass
    return None


def _tree_size(path: Path) -> Tuple[int, int]:
    """Return (bytes, number of files) of a file or folder, links not followed."""
    if _is_link(path):
        return 0, 1
    try:
        if not os.path.isdir(_lp(path)):
            return os.lstat(_lp(path)).st_size, 1
    except OSError:
        return 0, 1
    total, count = 0, 0
    try:
        for _, child, is_dir in _children(path):
            if is_dir:
                size, n = _tree_size(child)
            else:
                try:
                    size, n = os.lstat(_lp(child)).st_size, 1
                except OSError:
                    size, n = 0, 1
            total += size
            count += n
    except OSError:
        pass
    return total, count


def mission_size(mission) -> int:
    """Size in bytes of a whole mission folder (links not followed)."""
    return _tree_size(Path(mission))[0]


def _band_patterns(band: str) -> List[re.Pattern]:
    return [
        re.compile(rf"^{band}_\d+\.dng$", _FLAGS),
        re.compile(rf"^{band}_\d+\.exif$", _FLAGS),
        re.compile(r"^time_line\.json$", _FLAGS),
        re.compile(rf"^transfer_info_{band}_dng\.json$", _FLAGS),
        _DESKTOP,
    ]


KEEP_FILES_AERIAL = [re.compile(r"^shoot_points\.json$", _FLAGS), _DESKTOP]
KEEP_FILES_IMG = [
    re.compile(r"^VIS_\d+\.jpg$", _FLAGS),
    re.compile(r"^VIR_\d+_local\.jpg$", _FLAGS),
    re.compile(r"^VIS_\d+_motion_model\.npy$", _FLAGS),
    re.compile(r"^NDVI_\d+_local\.jpg$", _FLAGS),
    re.compile(r"^NIR_\d+_local\.jpg$", _FLAGS),
    re.compile(r"^shoot_points\.json$", _FLAGS),
    re.compile(r"^shoot_points_failed_summary\.json$", _FLAGS),
    _DESKTOP,
]
KEEP_FILES_SYNCHRO = [
    re.compile(r"^check_time_alignment\.png$", _FLAGS),
    re.compile(r"^check_time_before_alignment\.png$", _FLAGS),
    _DESKTOP,
]


def _scan_folder(plan: ArchivePlan, folder: Path, label: str,
                 keep_files: List[re.Pattern], keep_dirs: Tuple[str, ...] = ()) -> None:
    """Fill the plan with the entries to delete in one folder (not recursive)."""
    kept = 0
    for name, path, is_dir in _children(folder):
        if is_dir and name.lower() in keep_dirs:
            continue
        if not is_dir and any(p.match(name) for p in keep_files):
            kept += 1
            continue
        size, n_files = _tree_size(path)
        plan.delete_items.append(DeleteItem(path, label, is_dir, size, n_files))
    plan.kept_counts[label] = kept


def read_manifest(mission: Path) -> Optional[dict]:
    """Return the archive manifest of a mission, None if absent or unreadable."""
    path = _find(Path(mission), MANIFEST_NAME)
    if path is None:
        return None
    try:
        with open(_lp(path), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_plan(mission) -> ArchivePlan:
    """Analyse a mission folder. Nothing is modified on disk."""
    mission = Path(mission)
    plan = ArchivePlan(mission=mission)
    if not mission.is_dir():
        plan.blockers.append(f"The mission folder does not exist: {mission}")
        return plan
    plan.mission_bytes = mission_size(mission)

    manifest = read_manifest(mission)
    if manifest is not None and manifest.get("status") == "completed":
        plan.already_archived = True
        plan.blockers.append(
            f"This mission was already archived on {manifest.get('archived_at', '?')}."
        )
        return plan
    if manifest is not None:
        plan.warnings.append("A previous archiving ended with errors: it is resumed.")

    aerial = _find(mission, "AerialPhotography")
    flight = _find(mission, "FlightAnalytics")
    img = _find(mission, "ImgIRdrone")
    synchro = _find(mission, "Synchro")

    # Consistency checks: without these files the mission cannot be processed again.
    required = []
    if flight is None or _find(flight, "mission_parameters.json") is None:
        required.append("FlightAnalytics\\mission_parameters.json")
    if aerial is None:
        required.append("AerialPhotography")
    else:
        if _find(aerial, "shoot_points.json") is None:
            required.append("AerialPhotography\\shoot_points.json")
        for band in ("VIS", "NIR"):
            band_dir = _find(aerial, band)
            if band_dir is None:
                required.append(f"AerialPhotography\\{band}")
                continue
            if _find(band_dir, "time_line.json") is None:
                required.append(f"AerialPhotography\\{band}\\time_line.json")
            if _find(band_dir, f"transfer_info_{band}_dng.json") is None:
                required.append(f"AerialPhotography\\{band}\\transfer_info_{band}_dng.json")
    if img is None or _find(img, "shoot_points.json") is None:
        required.append("ImgIRdrone\\shoot_points.json")
    for name in required:
        plan.blockers.append(f"Required file or folder missing: {name}")
    if plan.blockers:
        return plan

    # Root level
    root_kept = 0
    for name, path, is_dir in _children(mission):
        lower = name.lower()
        if is_dir and (lower in UNTOUCHED_DIRS or lower in CLEANED_DIRS
                       or lower.startswith("mapping_multi_")):     # previous maps of Step 5
            root_kept += 1
        elif not is_dir and (_DESKTOP.match(name) or lower in (MANIFEST_NAME, LOG_NAME, ICON_NAME.lower())):
            root_kept += 1
        else:
            size, n_files = _tree_size(path)
            plan.delete_items.append(DeleteItem(path, "Mission root", is_dir, size, n_files))
    plan.kept_counts["Mission root"] = root_kept
    for name in ("cameras", "mapping_MULTI"):
        if _find(mission, name) is None:
            plan.missing.append(name)
    if synchro is None:
        plan.missing.append("Synchro")

    _scan_folder(plan, aerial, "AerialPhotography", KEEP_FILES_AERIAL, keep_dirs=("vis", "nir"))
    for band in ("VIS", "NIR"):
        _scan_folder(plan, _find(aerial, band), f"AerialPhotography\\{band}", _band_patterns(band))
    _scan_folder(plan, img, "ImgIRdrone", KEEP_FILES_IMG)
    if synchro is not None:
        _scan_folder(plan, synchro, "Synchro", KEEP_FILES_SYNCHRO)
    return plan


def _remove_file(path: Path) -> None:
    try:
        os.remove(_lp(path))
    except PermissionError:
        os.chmod(_lp(path), stat.S_IWRITE)
        os.remove(_lp(path))


def _delete_tree(path: Path, on_file: Callable[[int], None], errors: List[Tuple[str, str]]) -> None:
    """Delete a file or folder. Errors are collected and the deletion goes on."""
    try:
        if _is_link(path):
            try:
                os.remove(_lp(path))
            except OSError:
                os.rmdir(_lp(path))
            on_file(0)
            return
        if not os.path.isdir(_lp(path)):
            size = os.lstat(_lp(path)).st_size
            _remove_file(path)
            on_file(size)
            return
        for _, child, _ in _children(path):
            _delete_tree(child, on_file, errors)
        os.rmdir(_lp(path))
    except OSError as exc:
        errors.append((str(path), str(exc)))


def execute_archive(plan: ArchivePlan,
                    log: Callable[[str], None] = print,
                    progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Delete everything listed in the plan, then write the manifest.

    Errors on a file (locked file for example) do not stop the operation.
    ``progress(done_bytes, total_bytes)`` is called after each deleted file.
    Returns the manifest dictionary.
    """
    if plan.blockers:
        raise RuntimeError("The plan has blockers: " + "; ".join(plan.blockers))
    mission = plan.mission
    log_path = mission / LOG_NAME

    def write_log(message: str) -> None:
        log(message)
        try:
            with open(_lp(log_path), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
        except OSError:
            pass

    started = datetime.now()
    write_log(f"Archiving of {mission} started.")
    total = max(plan.total_bytes, 1)
    done = [0]
    errors: List[Tuple[str, str]] = []

    def on_file(size: int) -> None:
        done[0] += size
        if progress is not None:
            progress(min(done[0], total), total)

    for item in plan.delete_items:
        before = len(errors)
        write_log(f"Deleting {item.path.name} ({format_size(item.size)})")
        _delete_tree(item.path, on_file, errors)
        for path, message in errors[before:]:
            write_log(f"  ERROR {path}: {message}")
    if progress is not None:
        progress(total, total)

    status = "completed" if not errors else "completed_with_errors"
    manifest = {
        "mission_path": str(mission),
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "archived_at": started.isoformat(timespec="seconds"),
        "deleted_bytes": done[0],
        "kept_counts": plan.kept_counts,
        "deleted_items": [
            {"name": i.path.name, "folder": i.folder, "is_dir": i.is_dir,
             "bytes": i.size, "files": i.n_files}
            for i in plan.delete_items
        ],
        "errors": [{"path": p, "message": m} for p, m in errors],
    }
    with open(_lp(mission / MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    if status == "completed":
        try:
            if set_archive_folder_icon(mission):
                write_log("Mission folder icon changed.")
        except Exception as e:  # cosmetic only: never fail the archiving for an icon
            write_log(f"Folder icon not changed: {e}")
    write_log(f"Archiving finished ({status}): {format_size(done[0])} freed, {len(errors)} error(s).")
    return manifest


ICON_NAME = "IRDrone_archive.ico"
ICON_SOURCE = Path(__file__).resolve().parent.parent / "resources" / "Icon" / ICON_NAME


def _read_text_auto(path: Path) -> str:
    """Read a desktop.ini file (UTF-16 with BOM when written by Windows, otherwise ANSI/UTF-8)."""
    raw = Path(_lp(path)).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("mbcs")


def set_archive_folder_icon(mission: Path) -> bool:
    """Show the IRDrone archive icon on the mission folder (Windows only).

    The icon is copied inside the mission folder (hidden) so that it follows the folder
    if it is moved. The ``[.ShellClassInfo]`` section of ``desktop.ini`` is updated and
    the other lines are preserved. Returns False if the icon is unavailable or not on Windows.
    """
    if os.name != "nt" or not ICON_SOURCE.is_file():
        return False
    import ctypes
    import shutil
    set_attr = ctypes.windll.kernel32.SetFileAttributesW
    hidden_system = 0x2 | 0x4

    icon_dest = mission / ICON_NAME
    if icon_dest.exists():
        set_attr(str(icon_dest), 0x80)
    shutil.copyfile(ICON_SOURCE, icon_dest)
    set_attr(str(icon_dest), hidden_system)

    ini = _find(mission, "desktop.ini") or (mission / "desktop.ini")
    lines: List[str] = []
    if ini.exists():
        lines = _read_text_auto(ini).splitlines()
        set_attr(str(ini), 0x80)
    out: List[str] = []
    in_section, found = False, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if in_section and not found:
                out += [f"IconResource={ICON_NAME},0"]
                found = True
            in_section = stripped.lower() == "[.shellclassinfo]"
        elif in_section and stripped.lower().startswith(("iconresource=", "iconfile=", "iconindex=")):
            continue
        out.append(line)
        if in_section and not found and stripped.lower() == "[.shellclassinfo]":
            out.append(f"IconResource={ICON_NAME},0")
            found = True
    if not found:
        out += ["[.ShellClassInfo]", f"IconResource={ICON_NAME},0"]
    with open(str(ini), "w", encoding="utf-16", newline="") as f:
        f.write("\r\n".join(out) + "\r\n")
    set_attr(str(ini), hidden_system)
    # Explorer only reads desktop.ini of a folder flagged read-only or system
    set_attr(str(mission), 0x1 | 0x10)
    ctypes.windll.shell32.SHChangeNotify(0x00002000, 0x1000, ctypes.c_wchar_p(str(mission)), None)
    return True
