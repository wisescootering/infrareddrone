"""
Case-insensitive file lookup.

Windows ignores the case of file names: ``glob("*.dng")`` also returns
``VIS_0001.DNG``. Linux and macOS do not, so camera files (``.DNG``, ``.RAW``,
``.JPG``...) were silently skipped there. These helpers give the Windows
behaviour on every system.
"""
import fnmatch
import glob
import os
from pathlib import Path
from typing import List, Optional, Union

PathLike = Union[str, "os.PathLike[str]"]


def glob_ci(folder: PathLike, pattern: str) -> List[Path]:
    """Files of ``folder`` (not recursive) whose name matches ``pattern``, ignoring case.

    Sorted. Names differing only by case (impossible on Windows) are listed once.
    Returns an empty list if ``folder`` does not exist.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    pattern = pattern.lower()
    matches = {}
    for path in sorted(folder.iterdir()):
        key = path.name.lower()
        if key not in matches and fnmatch.fnmatchcase(key, pattern):
            matches[key] = path
    return sorted(matches.values())


def glob_path_ci(path_pattern: PathLike) -> List[str]:
    """``glob.glob`` replacement, case-insensitive on the file name part only."""
    folder, pattern = os.path.split(os.fspath(path_pattern))
    if glob.has_magic(folder):  # wildcards in folders: keep the system behaviour
        return sorted(glob.glob(os.fspath(path_pattern)))
    return [str(p) for p in glob_ci(folder or ".", pattern)]


def find_ci(path: PathLike) -> Optional[Path]:
    """The file of the folder of ``path`` whose name only differs by case, spelled as on disk.

    An exact match wins. On a case-insensitive filesystem (Windows, macOS) ``path`` may exist
    under another spelling, so the folder is always listed.
    """
    path = Path(path)
    matches = glob_ci(path.parent, glob.escape(path.name))
    for match in matches:
        if match.name == path.name:
            return match
    return matches[0] if matches else None


def has_suffix(path: PathLike, *suffixes: str) -> bool:
    """True if the extension of ``path`` is one of ``suffixes`` (with or without dot), ignoring case."""
    ext = Path(path).suffix.lower()
    return any(ext == "." + s.lower().lstrip(".") for s in suffixes)


def with_suffix_ci(path: PathLike, old: str, new: str) -> str:
    """Replace the extension ``old`` of ``path`` by ``new``, ignoring the case of ``old``.

    ``path`` is returned unchanged if its extension is not ``old``.
    """
    path = os.fspath(path)
    root, ext = os.path.splitext(path)
    return root + new if ext.lower() == old.lower() else path
