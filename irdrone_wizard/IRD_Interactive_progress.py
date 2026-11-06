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
STEPS = (1, 2, 3, 4, 5, 6)


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


def done_steps(folder):
    """{step number: completion date} for the mission in folder."""
    if folder is None:
        return {}
    path = Path(folder) / PROGRESS_FILE
    if not is_valid_json_file(path):
        return {}
    import json
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return {int(step): date for step, date in data.get("done", {}).items()
            if str(step).isdigit() and int(step) in STEPS}


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
        write_json_atomic(path, {"done": {str(k): v for k, v in sorted(steps.items())}}, indent=2)
        notifier.changed.emit(folder)
    except Exception as error:
        print(f"[WARNING] could not record that step {step} is done: {error}")
