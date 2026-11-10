# -*- coding: utf-8 -*-
"""
Which wizard steps are done for a mission.

Each step calls mark_step_done() when it really completes (not when its window
is closed). The record lives in the mission folder,
FlightAnalytics/wizard_progress.json, so reopening a mission shows its progress.
The main window listens to `notifier.changed` to grey the finished steps out.
"""
import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from IRD_Interactive_diskspace import is_valid_json_file, write_json_atomic

PROGRESS_FILE = Path("FlightAnalytics") / "wizard_progress.json"
# 1 mission, 2 flight timeline, 3 synchronise, 4 align, 5 review, 6 map, 7 archive
STEPS = (1, 2, 3, 4, 5, 6, 7)
REVIEW, MAP, ARCHIVE = 5, 6, 7
# Version 1 of the record (no "version" key) had six steps: the review was part
# of Step 4, 5 was the map and 6 the archive.
RECORD_VERSION = 2


class _Notifier(QObject):
    changed = pyqtSignal(object)  # mission folder (Path)


notifier = _Notifier()


def mission_folder(mission_parameters, folder=None):
    """Mission folder: the one chosen in this session first
    (mission_parameters.json may hold a path from another computer)."""
    if folder:
        return Path(folder)
    if not mission_parameters:
        return None
    for key in ("folderMissionPath", "File path mission"):
        if mission_parameters.get(key):
            return Path(mission_parameters[key])
    return None


# For missions processed before the progress record existed (or outside the
# wizard), a step also counts as done when the files it writes at its very end
# are there. Earlier outputs are not enough, e.g. mission_parameters.json is
# written as soon as Step 1 starts, the ArUco images and the delay plots of
# Step 3 before its image pairing. Step 2 has no output of its own: not guessed.
def _json_with_points(path):
    """JSON object with a non-empty 'shoot_points' list."""
    if not is_valid_json_file(path):
        return False
    import json
    with open(path, encoding="utf-8") as file:
        return bool(json.load(file).get("shoot_points"))


def _file_exists(path):
    return path.is_file() and path.stat().st_size > 0


STEP_OUTPUTS = {
    # Step 1: the EXIF stage of each band writes time_line.json after the copy / conversion
    1: ((Path("FlightAnalytics") / "mission_parameters.json", is_valid_json_file),
        (Path("AerialPhotography") / "VIS" / "time_line.json", is_valid_json_file),
        (Path("AerialPhotography") / "NIR" / "time_line.json", is_valid_json_file)),
    # Step 3: written by the image pairing (time shift + VIS / NIR pairs), its last stage
    3: ((Path("AerialPhotography") / "shoot_points.json", _json_with_points),),
    # Step 4: inventory written at the end of the alignment
    4: ((Path("ImgIRdrone") / "shoot_points.json", _json_with_points),),
    # Step 5: statuses saved when the review is closed
    REVIEW: ((Path("ImgIRdrone") / "review.json", is_valid_json_file),),
    # Step 6: orthophoto copied once ODM succeeded
    MAP: ((Path("mapping_MULTI") / "mapping_result" / "odm_orthophoto.tif", _file_exists),),
    # Step 7: written by the archiving
    ARCHIVE: ((Path("archive_manifest.json"), is_valid_json_file),),
}


def _done_from_outputs(folder, step):
    """Completion date of step guessed from its output files, or None."""
    paths = []
    for name, check in STEP_OUTPUTS.get(step, ()):
        path = Path(folder) / name
        try:
            if not check(path):
                return None
        except (OSError, ValueError, AttributeError):
            return None
        paths.append(path)
    if not paths:
        return None
    latest = max(path.stat().st_mtime for path in paths)
    return datetime.datetime.fromtimestamp(latest).isoformat(timespec="seconds")


def done_steps(folder):
    """{step number: completion date} for the mission in folder."""
    if folder is None:
        return {}
    steps = {}
    path = Path(folder) / PROGRESS_FILE
    if is_valid_json_file(path):
        import json
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        steps = {int(step): date for step, date in data.get("done", {}).items()
                 if str(step).isdigit() and int(step) in STEPS}
        if data.get("version", 1) < 2:
            steps = _from_six_steps(steps)
    for step in STEP_OUTPUTS:
        if step not in steps:
            found = _done_from_outputs(folder, step)
            if found:
                steps[step] = found
    # a mission mapped (or archived) went through the review, even with no review.json
    later = [steps[s] for s in (MAP, ARCHIVE) if s in steps]
    if later and REVIEW not in steps and 4 in steps:
        steps[REVIEW] = min(later)
    return dict(sorted(steps.items()))


def _from_six_steps(steps):
    """Record of version 1 (review inside Step 4, 5 map, 6 archive) in the
    numbering of version 2."""
    return {(s + 1 if s >= REVIEW else s): date for s, date in steps.items() if s <= 6}


def mark_step_done(folder, step):
    """Record that step is done for the mission in folder. Never raises: the
    progress display must not break a step that succeeded."""
    if folder is None:
        return
    try:
        folder = Path(folder)
        steps = done_steps(folder)
        steps[step] = datetime.datetime.now().isoformat(timespec="seconds")
        path = folder / PROGRESS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, {"version": RECORD_VERSION,
                                 "done": {str(k): v for k, v in sorted(steps.items())}}, indent=2)
        notifier.changed.emit(folder)
    except Exception as error:
        print(f"[WARNING] could not record that step {step} is done: {error}")
