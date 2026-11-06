# -*- coding: utf-8 -*-
"""
Disk space: warn before running out, stop cleanly when the disk is full.

Missions are large (DNG copies, NIR conversion, aligned TIFs...). A full disk
used to show up as hundreds of "[Errno 28] No space left on device" lines
while the processing went on, leaving empty or truncated files behind.

* free_bytes / folder_size / format_bytes: measures.
* DiskFullError, raise_if_disk_full: turn ENOSPC into one clear error that
  workers let through instead of logging it per file and going on.
* write_json_atomic: write to a temporary file then replace, so a full disk
  never leaves an empty .exif / .json file in place of a good one.
* confirm_free_space: dialog before a step that needs a known amount of space.
No Qt import at module level: workers in other processes can use it.
"""
import errno
import json
import os
import shutil
from pathlib import Path

# Windows: ERROR_DISK_FULL / ERROR_HANDLE_DISK_FULL (errno may be EINVAL there).
_WINDOWS_DISK_FULL = {112, 39}
# Below this, the bottom bar of the main window shows the free space in red.
LOW_SPACE_BYTES = 10 * 1024 ** 3
# Below this, a failed write / conversion is treated as 'disk full'.
DISK_NEARLY_FULL_BYTES = 200 * 1024 ** 2


class DiskFullError(OSError):
    """The disk is full: stop the processing, the user must free space."""

    def __init__(self, path, original=None):
        self.path = Path(path) if path else None
        free = free_bytes(self.path) if self.path else None
        where = f" holding {self.path}" if self.path else ""
        left = f" ({format_bytes(free)} left)" if free is not None else ""
        super().__init__(
            errno.ENOSPC,
            f"The disk{where} is full{left}.\n"
            "Free some space, or choose another working folder with the ⚙ button "
            "at the bottom of the main window, then run the step again.")
        self.original = original

    def __str__(self):
        return self.strerror


def is_disk_full(error):
    """True if the exception means 'no space left on device'."""
    if isinstance(error, DiskFullError):
        return True
    if not isinstance(error, OSError):
        return False
    return (error.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1))
            or getattr(error, "winerror", None) in _WINDOWS_DISK_FULL)


def raise_if_disk_full(error, path=None):
    """Re-raise a disk-full OSError as DiskFullError (other errors: no-op)."""
    if isinstance(error, DiskFullError):
        raise error
    if is_disk_full(error):
        raise DiskFullError(path or getattr(error, "filename", None), error) from error


def free_bytes(path):
    """Free space on the disk holding path (first existing parent); None if unknown."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def folder_size(folder, suffixes=None):
    """Total size of the files directly in folder (optionally only these suffixes)."""
    total = 0
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file() and (suffixes is None or
                                    Path(entry.name).suffix.lower() in suffixes):
                total += entry.stat().st_size
        except OSError:
            pass
    return total


def format_bytes(size):
    if size is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def write_json_atomic(path, data, **dump_options):
    """Write JSON to path through a temporary file: on error (disk full...) the
    previous content of path is kept. Disk full raises DiskFullError."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(data, file, **dump_options)
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise_if_disk_full(error, path)
        raise


def space_shortage(folder, needed):
    """(free, needed) when the disk holding folder has less than needed, else None."""
    free = free_bytes(folder)
    if free is None or free >= needed:
        return None
    return free, needed


def confirm_free_space(parent, folder, needed, what):
    """Before a step: if the disk lacks space, ask whether to go on anyway.
    Returns True to continue."""
    shortage = space_shortage(folder, needed)
    if shortage is None:
        return True
    from PyQt6.QtWidgets import QMessageBox
    free, needed = shortage
    answer = QMessageBox.warning(
        parent, "Not enough disk space",
        f"{what} needs about {format_bytes(needed)}, but only {format_bytes(free)} "
        f"is free on the disk holding\n{folder}\n\n"
        "Free some space, or choose another working folder with the ⚙ button at the "
        "bottom of the main window.\n\nContinue anyway?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def is_valid_json_file(path):
    """True if path holds a JSON object. Used as the 'already done' test for the
    .exif sidecar files: an empty or truncated one (left by a full disk) is redone."""
    try:
        with open(path, encoding="utf-8") as file:
            return isinstance(json.load(file), dict)
    except (OSError, ValueError):
        return False
