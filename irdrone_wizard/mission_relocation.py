"""Silent recovery of a mission folder renamed or moved by hand.

The JSON files of a mission (mission_parameters.json, shoot_points.json,
transfer_info_*.json, the .exif sidecars of the images, the mapping reports...)
keep absolute paths into the mission folder. When the user renames the folder,
moves it to another disk or opens it on another computer, those paths point to
a folder that no longer exists. When a mission is opened, ``relocate_mission``
rewrites them to the folder actually opened, without asking anything.

The former location is ``File path mission`` of mission_parameters.json, which
is rewritten last: if the recovery is interrupted, it is simply done again the
next time the mission is opened. Paths outside the mission folder (the take-off
image on the SD card, the docker command...) are left as they are.
"""
import json
import os
import re
from pathlib import Path

PARAMETERS = Path("FlightAnalytics") / "mission_parameters.json"
SUFFIXES = (".json", ".exif")
MAX_SIZE = 20 * 1024 * 1024  # larger files are not mission reports: left alone


def _normalized(path) -> str:
    """Path text with '/' separators and no trailing separator."""
    return str(path).replace("\\", "/").rstrip("/")


def _is_windows_path(text: str) -> bool:
    return os.name == "nt" or bool(re.match(r"^[A-Za-z]:", text)) or "\\" in text


def _prefix_pattern(old: str):
    """Regex matching a path starting with the former mission folder, whatever
    the separators; a non-ASCII letter also matches the '?' ExifTool writes
    instead of it on Windows (G:/D?mo Florine for G:/Démo Florine)."""
    parts = []
    for char in _normalized(old):
        if char == "/":
            parts.append(r"[\\/]")
        elif ord(char) > 127:
            parts.append(f"(?:{re.escape(char)}|\\?+)")
        else:
            parts.append(re.escape(char))
    flags = re.IGNORECASE if _is_windows_path(old) else 0
    return re.compile("".join(parts) + r"(?=$|[\\/])", flags)


def _rewrite(value, pattern, new: str):
    """(value with the paths rebased, number of strings changed)."""
    if isinstance(value, str):
        match = pattern.match(value)
        if not match:
            return value, 0
        rest = value[match.end():].replace("\\", "/").lstrip("/")
        return (str(Path(new, *rest.split("/"))) if rest else new), 1
    if isinstance(value, list):
        changed = 0
        out = []
        for item in value:
            item, n = _rewrite(item, pattern, new)
            out.append(item)
            changed += n
        return out, changed
    if isinstance(value, dict):
        changed = 0
        out = {}
        for key, item in value.items():
            item, n = _rewrite(item, pattern, new)
            out[key] = item
            changed += n
        return out, changed
    return value, 0


def _rewrite_file(path: Path, pattern, new: str) -> bool:
    """Rebase the paths of one JSON file; True when it was rewritten.
    A file that cannot be read, parsed or written is left as it is."""
    try:
        if path.stat().st_size > MAX_SIZE:
            return False
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return False
    data, changed = _rewrite(data, pattern, new)
    if not changed:
        return False
    first_indent = re.search(r"\n( +)\S", text)
    indent = len(first_indent.group(1)) if first_indent else None
    tmp = path.with_name(path.name + ".relocating")
    try:
        # ASCII output (\u escapes): read back the same with any encoding.
        tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def former_location(mission: Path):
    """``File path mission`` recorded in mission_parameters.json, or None."""
    try:
        with open(Path(mission) / PARAMETERS, encoding="utf-8") as file:
            old = json.load(file).get("File path mission")
    except (OSError, ValueError, AttributeError):
        return None
    return old if isinstance(old, str) and old.strip() else None


def needs_relocation(mission: Path) -> bool:
    old = former_location(mission)
    if old is None:
        return False
    return not _prefix_pattern(old).fullmatch(str(Path(mission)))


def relocate_mission(mission: Path) -> int:
    """Rewrite the paths into the former mission folder to ``mission``.
    Returns the number of files rewritten (0 when the mission did not move)."""
    mission = Path(mission)
    if not needs_relocation(mission):
        return 0
    pattern = _prefix_pattern(former_location(mission))
    new = str(mission)
    parameters = mission / PARAMETERS
    rewritten = 0
    for root, _dirs, files in os.walk(mission):
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() in SUFFIXES and path != parameters:
                rewritten += _rewrite_file(path, pattern, new)
    # Last: the former location stays recorded until everything else is done.
    rewritten += _rewrite_file(parameters, pattern, new)
    if rewritten:
        print(f"Mission moved: paths of {rewritten} files updated to {new}")
    return rewritten
