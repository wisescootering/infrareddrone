# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 4
#   Process preprocessed VIS / NIR image pairs.
# ---------------------------------------------------------------------------------

import json
import locale
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import time

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from IRD_Interactive_styles import BUTTON_STYLE, colored_button_style
import IRD_Interactive_help as Help
from IRD_Interactive_progress import mark_step_done
from config import SJCONVERTERPATH
from alignment_workers import (
    ALIGNMENT_WORKER_MEMORY_GB,
    MAX_WORKERS,
    available_alignment_workers,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSING_SCRIPT = PROJECT_ROOT / "run_after_preprocessing.py"
VIS_FILENAME_PATTERN = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)
PROGRESS_LINE_PATTERN = re.compile(
    r"^STEP4_PROGRESS (\d+) (\d+)(?: (\S+))?(?: ([\d.]+) (-?[\d.]+))?$"
)
# Aligned images written by automatic_registration: {trace}_{number}_{mode}.jpg
# for the VIR / NIR / NDVI traces and the local / global alignment modes.
ALIGNED_TRACES = ("VIR", "NDVI", "NIR")
ALIGNMENT_MODES = ("local", "global")
ALIGNED_JPEG_PATTERN = re.compile(
    r"^(?:VIR|NDVI|NIR)_(\d+)_(?:local|global)\.jpg$", re.IGNORECASE
)
ALIGNED_JPEG_LABEL = "VIR / NDVI / NIR _XXXX_local or _global.jpg"
FAILED_SUMMARY_FILENAME = "shoot_points_failed_summary.json"
# Same as automatic_registration.REDO_SCRIPT_SUFFIX (not imported: heavy module).
REDO_BATCH_SUFFIX = "_REDO.bat" if os.name == "nt" else "_REDO.sh"
SETTINGS_ORGANIZATION = "IRdrone"
SETTINGS_APPLICATION = "IRD_Interactive"
WORKERS_SETTING_KEY = "step4/alignment_workers"
LOG_LEVEL_SETTING_KEY = "step4/log_level"
# (run_after_preprocessing.py --log-level value, label shown in the settings)
LOG_LEVELS = (
    ("warning", "Warnings only"),
    ("info", "Info (processing steps)"),
    ("debug", "Debug (detailed timings)"),
)


def kill_process_tree(pid: int, timeout: float = 3.0) -> None:
    """End a process and every process it started (the alignment workers of
    the ProcessPoolExecutor): terminate, then kill what is left."""
    if not pid:
        return
    try:
        import psutil
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
    except Exception:
        return
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    try:
        _gone, alive = psutil.wait_procs(procs, timeout=timeout)
    except Exception:
        alive = procs
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def load_worker_setting() -> int:
    """Saved number of alignment workers; 0 means automatic."""
    try:
        value = int(_settings().value(WORKERS_SETTING_KEY, 0))
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def save_worker_setting(value: int) -> None:
    _settings().setValue(WORKERS_SETTING_KEY, max(0, int(value)))


def load_log_level_setting() -> str:
    """Saved console detail level of the processing script."""
    value = str(_settings().value(LOG_LEVEL_SETTING_KEY, LOG_LEVELS[0][0]))
    return value if value in dict(LOG_LEVELS) else LOG_LEVELS[0][0]


def save_log_level_setting(value: str) -> None:
    if value not in dict(LOG_LEVELS):
        raise ValueError(f"Unknown log level: {value!r}")
    _settings().setValue(LOG_LEVEL_SETTING_KEY, value)


class Step4SettingsDialog(QDialog):
    """Processing settings of Step 4 (opened with the gear button)."""

    def __init__(self, workers: int, log_level: str = LOG_LEVELS[0][0], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step 4 – Settings")
        layout = QVBoxLayout(self)

        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("Alignment worker processes:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, min(MAX_WORKERS, max(1, os.cpu_count() or 1)))
        self.workers_spin.setSpecialValueText(
            f"Auto ({available_alignment_workers()})"
        )
        self.workers_spin.setValue(workers)
        self.workers_spin.setMinimumWidth(110)
        workers_layout.addWidget(self.workers_spin)
        safe_button = QPushButton("Safe mode (1)")
        safe_button.setStyleSheet(BUTTON_STYLE)
        safe_button.clicked.connect(lambda: self.workers_spin.setValue(1))
        safe_button.setToolTip("One worker only: slower, but the least memory. "
                               "Use it if the computer freezes or the run is killed.")
        workers_layout.addWidget(safe_button)
        workers_layout.addStretch()
        layout.addLayout(workers_layout)

        explanation = QLabel(
            "Each worker aligns one shoot point and needs about "
            f"{ALIGNMENT_WORKER_MEMORY_GB:g} GB of memory. Auto uses the physical "
            "cores, limited by the RAM available when the run starts. "
            "Use 1 (safe mode) if the computer freezes or the run is killed. "
            "The choice is remembered for the next sessions; each run writes in "
            "the log the number of workers this computer can take."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        log_layout = QHBoxLayout()
        log_layout.addWidget(QLabel("Log detail:"))
        self.log_level_combo = QComboBox()
        for value, label in LOG_LEVELS:
            self.log_level_combo.addItem(label, value)
        index = self.log_level_combo.findData(log_level)
        self.log_level_combo.setCurrentIndex(max(0, index))
        log_layout.addWidget(self.log_level_combo)
        log_layout.addStretch()
        layout.addLayout(log_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def workers(self) -> int:
        return self.workers_spin.value()

    def log_level(self) -> str:
        return self.log_level_combo.currentData()



def redo_check_image(output_folder: Path, vis_stem: str, written_after: float = 0.0):
    """Aligned image to show after a redo: VIR first, local before global.

    Only files written after ``written_after`` (redo start time) are considered,
    so an image left by an earlier run with other options is never shown.
    """
    image_number = vis_stem.removeprefix("VIS_")
    for trace in ALIGNED_TRACES:
        for mode in ALIGNMENT_MODES:
            path = output_folder / f"{trace}_{image_number}_{mode}.jpg"
            # 1 s margin: some file systems store coarse modification times.
            if path.is_file() and path.stat().st_mtime >= written_after - 1.0:
                return path
    return None


def apply_failed_selection(inventory: dict, selected_numbers) -> dict:
    """Set ``failed`` on existing shoot points selected by the user (in place).

    Returns the counts of newly flagged points, already flagged points and
    selected numbers absent from the inventory.
    """
    points = inventory.get("shoot_points")
    if not isinstance(points, list):
        raise ValueError("shoot_points.json has no shoot_points list.")
    remaining = set(selected_numbers)
    newly_flagged = 0
    already_flagged = 0
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("FileName"), str):
            continue
        number = _vis_image_number(point["FileName"])
        if number not in remaining:
            continue
        remaining.discard(number)
        current = point.get("failed", False)
        if current:
            already_flagged += 1
            continue
        point["failed"] = 1 if isinstance(current, int) and not isinstance(
            current, bool
        ) else True
        newly_flagged += 1
    return {
        "newly_flagged": newly_flagged,
        "already_flagged": already_flagged,
        "not_found": sorted(remaining),
    }


def build_failed_summary(inventory: dict) -> dict:
    """List the point numbers (zero-padded) by ``failed`` status."""
    failed_true, failed_false = [], []
    for point in inventory.get("shoot_points", []):
        if not isinstance(point, dict) or not isinstance(point.get("FileName"), str):
            continue
        label = f"{_vis_image_number(point['FileName']):04d}"
        (failed_true if point.get("failed", False) else failed_false).append(label)
    return {
        "failed_false": failed_false,
        "failed_true": failed_true,
        "count_failed_false": len(failed_false),
        "count_failed_true": len(failed_true),
    }


def failed_point_names(inventory: dict) -> list[tuple[int, str]]:
    """Return ``(number, VIS file stem)`` of the points flagged failed, sorted by number."""
    names = []
    for point in inventory.get("shoot_points", []):
        if not isinstance(point, dict) or not isinstance(point.get("FileName"), str):
            continue
        if point.get("failed", False):
            names.append((_vis_image_number(point["FileName"]), Path(point["FileName"]).stem))
    return sorted(names)


def clear_failed_selection(inventory: dict, selected_numbers) -> dict:
    """Reset ``failed`` on existing shoot points once their alignment is validated (in place).

    Returns the counts of cleared points, points that were not flagged and
    selected numbers absent from the inventory.
    """
    points = inventory.get("shoot_points")
    if not isinstance(points, list):
        raise ValueError("shoot_points.json has no shoot_points list.")
    remaining = set(selected_numbers)
    cleared = 0
    not_flagged = 0
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("FileName"), str):
            continue
        number = _vis_image_number(point["FileName"])
        if number not in remaining:
            continue
        remaining.discard(number)
        current = point.get("failed", False)
        if not current:
            not_flagged += 1
            continue
        point["failed"] = 0 if isinstance(current, int) and not isinstance(
            current, bool
        ) else False
        cleared += 1
    return {"cleared": cleared, "not_flagged": not_flagged, "not_found": sorted(remaining)}


def mark_points_aligned(output_folder: Path, numbers) -> dict:
    """Clear ``failed`` in shoot_points.json and rebuild shoot_points_failed_summary.json."""
    output_folder = Path(output_folder)
    inventory_path = output_folder / "shoot_points.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    result = clear_failed_selection(inventory, numbers)
    shutil.copy2(inventory_path, inventory_path.with_name(inventory_path.name + ".bak"))
    _write_json_atomic(inventory_path, inventory)
    _write_json_atomic(output_folder / FAILED_SUMMARY_FILENAME, build_failed_summary(inventory))
    return result


def read_redo_command(batch_path: Path) -> list[str]:
    """Arguments of the active command of a ``VIS_XXXX_REDO.bat`` (or ``.sh``) file.

    The script written by the alignment keeps one active command running
    ``automatic_registration.py``; the alternatives (other NIR ranks) are commented
    with ``REM`` (Windows) or ``#``. The interpreter and the script are dropped:
    the caller supplies them.
    """
    text = Path(batch_path).read_text(encoding=locale.getpreferredencoding(False), errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.lower().startswith("rem"):
            continue
        tokens = [token.strip('"') for token in shlex.split(stripped, posix=False)]
        if len(tokens) < 2 or not tokens[1].endswith("automatic_registration.py"):
            continue
        arguments = tokens[2:]
        if "--images" not in arguments or "--redo" not in arguments:
            raise ValueError(f"Unexpected REDO command in {Path(batch_path).name}")
        return arguments
    raise ValueError(f"No active command found in {Path(batch_path).name}")


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def _vis_image_number(filename: str) -> int:
    match = VIS_FILENAME_PATTERN.fullmatch(Path(filename).name)
    if match is None:
        raise ValueError(f"Unexpected visible image filename: {filename!r}")
    return int(match.group(1))


def redo_environment() -> QProcessEnvironment:
    """Environment of the processing subprocesses (project modules and SJ converter)."""
    environment = QProcessEnvironment.systemEnvironment()
    python_path = os.environ.get("PYTHONPATH", "")
    project_python_path = str(PROJECT_ROOT)
    if python_path:
        project_python_path = os.pathsep.join((project_python_path, python_path))
    environment.insert("PYTHONPATH", project_python_path)
    environment.insert("SJCONVERTERPATH", str(SJCONVERTERPATH))
    return environment


def redo_queue(output_folder: Path, points, log=print) -> list:
    """``(number, stem, arguments)`` of the points ``(number, stem)`` that have a
    readable REDO script; the others are reported through ``log``."""
    queue = []
    for number, stem in points:
        try:
            arguments = read_redo_command(Path(output_folder) / f"{stem}{REDO_BATCH_SUFFIX}")
        except (OSError, ValueError) as error:
            log(f"{stem}: redo skipped ({error})")
            continue
        queue.append((number, stem, arguments))
    return queue


STAGE_MARKER = "IRDRONE_STAGE "   # printed by automatic_registration.py (manual redo)
REDO_STAGES = [("load", "Loading the images"), ("manual", "Align by hand"),
               ("compute", "Computing the alignment"), ("write", "Saving")]


class RedoRunner(QObject):
    """Manual realignment of shoot points, one subprocess at a time.

    Each point runs automatic_registration.py with the arguments of its REDO
    script: a slider window opens, the user aligns VIS and NIR by hand and
    closes it, the alignment is recomputed. ``point_done`` gives the new
    aligned image (empty if none) or an error; the next point starts once the
    slots connected to ``point_done`` have returned (they may ask the user),
    or, with ``pause_between``, when ``resume()`` is called."""

    point_started = pyqtSignal(int, str)          # number, stem
    stage = pyqtSignal(int, str, str)             # number, stem, load / manual / compute / write
    output = pyqtSignal(str)                      # console output / log lines
    point_done = pyqtSignal(int, str, str, str)   # number, stem, aligned image, error
    all_done = pyqtSignal()

    def __init__(self, output_folder: Path, parent=None, pause_between: bool = False):
        super().__init__(parent)
        self.output_folder = Path(output_folder)
        self.pause_between = pause_between
        self._paused = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self._queue = []
        self.current = None
        self._started_at = 0.0
        self._partial = ""
        self.total = 0           # points of the run, and the rank of the current one
        self.rank = 0

    def busy(self) -> bool:
        return (self.current is not None or self._paused
                or self.process.state() != QProcess.ProcessState.NotRunning)

    def start(self, queue) -> None:
        self._queue = list(queue)
        self.total, self.rank = len(self._queue), 0
        self._start_next()

    def resume(self) -> None:
        """Start the next point (``pause_between``: after the user's verdict)."""
        if self._paused:
            self._paused = False
            self._start_next()

    def _point_finished(self) -> None:
        """pause_between: wait for resume() before the next point."""
        self.current = None
        self._paused = True

    def _start_next(self) -> None:
        if not self._queue:
            self.current = None
            self.all_done.emit()
            return
        number, stem, arguments = self._queue.pop(0)
        self.current = (number, stem)
        self.rank += 1
        self._partial = ""
        self._started_at = time.time()
        full_arguments = [str(PROJECT_ROOT / "automatic_registration.py"), *arguments]
        self.process.setProcessEnvironment(redo_environment())
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.output.emit(f"\nRedo {stem}: {sys.executable} {' '.join(full_arguments)}")
        self.point_started.emit(number, stem)
        self.process.start(sys.executable, full_arguments)

    def _read_output(self) -> None:
        output = self._partial + bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        lines = output.split("\n")
        self._partial = lines.pop()          # an unfinished line waits for the rest
        shown = []
        for line in lines:
            if line.startswith(STAGE_MARKER):
                if self.current is not None:
                    self.stage.emit(self.current[0], self.current[1], line[len(STAGE_MARKER):].strip())
            else:
                shown.append(line.rstrip("\r"))
        text = "\n".join(shown)
        if text.strip():
            self.output.emit(text.rstrip())

    def _flush_output(self) -> None:
        self._read_output()
        if self._partial.strip() and not self._partial.startswith(STAGE_MARKER):
            self.output.emit(self._partial.rstrip())
        self._partial = ""

    def _on_error(self, error) -> None:
        # A process that never started emits no "finished" signal.
        if error != QProcess.ProcessError.FailedToStart:
            return
        number, stem = self.current
        error = f"Unable to start the redo: {self.process.errorString()}"
        if self.pause_between:
            self._point_finished()
            self.point_done.emit(number, stem, "", error)
        else:
            self.point_done.emit(number, stem, "", error)
            self._start_next()

    def _on_finished(self, exit_code: int, exit_status) -> None:
        self._flush_output()
        number, stem = self.current
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            image, error = "", f"Redo of {stem} failed (exit code {exit_code})."
        else:
            found = redo_check_image(self.output_folder, stem, self._started_at)
            image = str(found) if found is not None else ""
            error = "" if found is not None else \
                f"Redo of {stem}: no aligned image ({ALIGNED_JPEG_LABEL}) was generated."
        if self.pause_between:
            self._point_finished()          # paused before the slots run: they may resume()
            self.point_done.emit(number, stem, image, error)
        else:
            self.point_done.emit(number, stem, image, error)
            self._start_next()


class DialogImageProcessing(QDialog):
    """Run the post-preprocessing image pipeline for a mission.

    auto_run (chained from Step 3): the alignment starts at once with the
    survey range of Step 2, and the review of the aligned images opens when
    it is done."""

    def __init__(self, mission_parameters: dict, parent=None, auto_run: bool = False):
        super().__init__(parent)
        self.auto_run = auto_run

        mission_folder = (
            mission_parameters.get("folderMissionPath")
            or mission_parameters.get("File path mission")
        )
        if not mission_folder:
            raise ValueError("The mission folder is not defined.")

        self.mission_folder = Path(mission_folder).expanduser().resolve()
        if not self.mission_folder.is_dir():
            raise FileNotFoundError(f"Mission folder does not exist: {self.mission_folder}")
        if not PROCESSING_SCRIPT.is_file():
            raise FileNotFoundError(f"Processing script does not exist: {PROCESSING_SCRIPT}")

        shoot_points_file = (
            self.mission_folder / "AerialPhotography" / "shoot_points.json"
        )
        if not shoot_points_file.is_file():
            raise FileNotFoundError(
                "Phase 3 output was not found. Run Step 3 first:\n"
                f"{shoot_points_file}"
            )

        with shoot_points_file.open("r", encoding="utf-8") as file:
            shoot_points_data = json.load(file)
        shoot_points = shoot_points_data.get("shoot_points")
        if not isinstance(shoot_points, list) or not shoot_points:
            raise ValueError(f"No image pairs were found in {shoot_points_file}")

        self.pair_count = len(shoot_points)
        image_numbers = [
            _vis_image_number(point["VIS"]["FileName"])
            for point in shoot_points
            if isinstance(point, dict)
            and isinstance(point.get("VIS"), dict)
            and isinstance(point["VIS"].get("FileName"), str)
        ]
        if not image_numbers:
            raise ValueError(
                f"No valid visible image names were found in {shoot_points_file}"
            )
        self.max_image_number = max(image_numbers)
        (
            self.start_image_number_value,
            self.end_image_number_value,
        ) = self._get_fly_image_range(shoot_points)
        self.process = QProcess(self)
        self._process_output_buffer = ""
        self._progress_total = 0
        self._last_elapsed_seconds = None
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.started.connect(self._on_process_started)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)


        self.setWindowTitle("Step 4 – Image processing")
        self._init_gui()
        self._fit_to_screen(parent)
        if self.auto_run:
            self.log_text.append("Started after the synchronisation: the alignment runs at once "
                                 "with the survey range of the flight timeline.")
            QTimer.singleShot(300, self._start_processing)

    def _get_fly_image_range(self, shoot_points: list[dict]) -> tuple[int, int]:
        transfer_info_file = (
            self.mission_folder
            / "AerialPhotography"
            / "VIS"
            / "transfer_info_VIS_dng.json"
        )
        if not transfer_info_file.is_file():
            raise FileNotFoundError(
                f"Step 2 visible-image selection was not found: {transfer_info_file}"
            )

        with transfer_info_file.open("r", encoding="utf-8") as file:
            transfer_info = json.load(file)
        if not isinstance(transfer_info, dict):
            raise ValueError(f"Invalid Step 2 selection data in {transfer_info_file}")
        fly_data = transfer_info.get("fly")
        copied_images = (
            fly_data.get("listCopiedImages") if isinstance(fly_data, dict) else None
        )
        if not isinstance(copied_images, list) or not copied_images:
            raise ValueError(
                f"No Step 2 visible FLY frames were found in {transfer_info_file}"
            )

        fly_filenames = {
            Path(filename).name.casefold()
            for filename in copied_images
            if isinstance(filename, str) and filename
        }
        image_numbers = []
        for point in shoot_points:
            visible_data = point.get("VIS") if isinstance(point, dict) else None
            filename = (
                visible_data.get("FileName")
                if isinstance(visible_data, dict)
                else None
            )
            if (
                isinstance(filename, str)
                and Path(filename).name.casefold() in fly_filenames
            ):
                image_numbers.append(_vis_image_number(filename))

        if not image_numbers:
            raise ValueError(
                "Step 2 visible FLY frames do not match any Step 3 image pairs."
            )

        return min(image_numbers), max(image_numbers)

    def _init_gui(self) -> None:
        layout = QVBoxLayout(self)
        # The labels wrap and the mission is named, its path in the tool tip:
        # nothing makes the window wider than the screen (long paths, display scaling).
        mission_label = QLabel(f"<b>Mission:</b> {self.mission_folder.name}")
        mission_label.setToolTip(str(self.mission_folder))
        mission_label.setWordWrap(True)
        layout.addWidget(mission_label)
        intro = QLabel(
            f"{self.pair_count} preprocessed image pairs found. "
            "The inclusive image-number range is pre-filled from Step 2's "
            "visible FLY frames."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("First VIS image number:"))
        self.start_image_number = QSpinBox()
        self.start_image_number.setRange(1, self.max_image_number)
        self.start_image_number.setValue(self.start_image_number_value)
        range_layout.addWidget(self.start_image_number)

        range_layout.addWidget(QLabel("Last VIS image number (inclusive):"))
        self.end_image_number = QSpinBox()
        self.end_image_number.setRange(1, self.max_image_number)
        self.end_image_number.setValue(self.end_image_number_value)
        range_layout.addWidget(self.end_image_number)
        range_layout.addStretch()
        layout.addLayout(range_layout)

        traces_group = QGroupBox("Generated image traces")
        traces_layout = QHBoxLayout(traces_group)
        self.ndvi_checkbox = QCheckBox("NDVI")
        self.ndvi_checkbox.setChecked(False)
        traces_layout.addWidget(self.ndvi_checkbox)
        self.nir_checkbox = QCheckBox("NIR")
        self.nir_checkbox.setChecked(False)
        traces_layout.addWidget(self.nir_checkbox)
        self.local_checkbox = QCheckBox("Local alignment")
        self.local_checkbox.setChecked(True)
        traces_layout.addWidget(self.local_checkbox)
        self.global_checkbox = QCheckBox("Global alignment")
        self.global_checkbox.setChecked(False)
        traces_layout.addWidget(self.global_checkbox)
        traces_layout.addStretch()
        layout.addWidget(traces_group)

        time_difference_layout = QHBoxLayout()
        time_difference_layout.addWidget(
            QLabel("Maximum VIS/NIR time difference (s):")
        )
        self.max_time_difference = QDoubleSpinBox()
        self.max_time_difference.setRange(0.1, 6.0)
        self.max_time_difference.setDecimals(1)
        self.max_time_difference.setSingleStep(0.1)
        self.max_time_difference.setValue(0.5)
        time_difference_layout.addWidget(self.max_time_difference)
        time_difference_layout.addStretch()
        layout.addLayout(time_difference_layout)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.run_button = QPushButton("Run alignment")
        self.run_button.clicked.connect(self._start_processing)
        button_layout.addWidget(self.run_button)
        self.stop_button = QPushButton("\u25A0  Stop")
        self.stop_button.setStyleSheet(
            "QPushButton { background: white; color: #B03A2E; font-weight: bold; padding: 6px 14px;"
            " border: 1px solid #E3B4AE; border-radius: 6px; } QPushButton:hover { background: #FBEDEB; }")
        self.stop_button.setToolTip("Stop the alignment. The images already aligned are kept; "
                                    "Run alignment again reuses their motion models.")
        self.stop_button.clicked.connect(self._stop_processing)
        self.stop_button.hide()
        button_layout.addWidget(self.stop_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        self.review_button = QPushButton("Review images  \u25B6")
        self.review_button.setToolTip(
            "Check the aligned images on a time line, flag the misaligned ones and realign them by hand."
        )
        self.review_button.clicked.connect(self._open_review)
        self.review_button.setEnabled(self._has_alignment_output())
        button_layout.addWidget(self.review_button)
        self.settings_button = QPushButton("\u2699")
        self.settings_button.setFixedWidth(30)
        # The gear glyph renders small: enlarge it, keep the button height.
        self.settings_button.setStyleSheet(
            BUTTON_STYLE + "QPushButton { font-size: 16px; padding: 2px; }"
        )
        self.settings_button.clicked.connect(self._open_settings)
        button_layout.addWidget(self.settings_button)
        self.help_button = QPushButton("?")
        self.help_button.setFixedWidth(30)
        self.help_button.setStyleSheet(BUTTON_STYLE)
        self.help_button.clicked.connect(lambda: Help.show_help("ch:step4", parent=self))
        button_layout.addWidget(self.help_button)

        for widget, label, tip in (
            (self.ndvi_checkbox, "btn:step4_options", "Also write the NDVI image of each shoot point."),
            (self.nir_checkbox, "btn:step4_options", "Also write the aligned NIR image of each shoot point."),
            (self.local_checkbox, "btn:step4_options", "Write the locally aligned VIR image (VIR_XXXX_local.jpg)."),
            (self.global_checkbox, "btn:step4_options", "Write the globally aligned VIR image (VIR_XXXX_global.jpg)."),
            (self.start_image_number, "btn:step4_options", "First shoot point to align (VIS image number). Default: the survey of Step 2."),
            (self.end_image_number, "btn:step4_options", "Last shoot point to align (VIS image number, included)."),
            (self.max_time_difference, "btn:step4_options", "Shoot points whose VIS/NIR time difference exceeds this value are not processed."),
            (self.run_button, "btn:step4_run_alignment", "Align the VIS and NIR images of the selected shoot points (can take a long time)."),
            (self.close_button, "btn:step4_close", "Close this window."),
            (self.review_button, "ch:review", self.review_button.toolTip()),
            (self.settings_button, "btn:step4_settings", "Processing settings (worker processes / safe mode, log detail)."),
            (self.stop_button, "btn:step4_stop", self.stop_button.toolTip()),
            (self.help_button, "ch:step4", "Open the manual at Step 4."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

        # Apply the common style to the three main buttons
        self.run_button.setStyleSheet(BUTTON_STYLE)
        self.close_button.setStyleSheet(BUTTON_STYLE)
        self.review_button.setStyleSheet(colored_button_style("#2E7D32"))

        layout.addLayout(button_layout)

    def _fit_to_screen(self, parent=None) -> None:
        """760 x 520, smaller if the screen is (centred, title bar kept)."""
        from PyQt6.QtWidgets import QApplication
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        if screen is None:
            self.resize(760, 520)
            return
        g = screen.availableGeometry()
        w = min(max(760, self.minimumSizeHint().width()), g.width() - 20)
        h = min(max(520, self.minimumSizeHint().height()), g.height() - 60)
        self.setGeometry(g.x() + (g.width() - w) // 2, g.y() + (g.height() - h) // 2, w, h)

    def _has_alignment_output(self) -> bool:
        return (self.mission_folder / "ImgIRdrone" / "shoot_points.json").is_file()

    def _open_review(self) -> None:
        """Review window (modal): flags and redo are done there."""
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            from IRD_Interactive_review import ReviewDialog
            dialog = ReviewDialog(self.mission_folder, parent=self)
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(self, "Review unavailable", str(error))
            return
        dialog.exec()

    def _open_settings(self) -> None:
        dialog = Step4SettingsDialog(
            load_worker_setting(), load_log_level_setting(), parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            save_worker_setting(dialog.workers())
            save_log_level_setting(dialog.log_level())

    @staticmethod
    def _project_environment() -> QProcessEnvironment:
        """Environment of the processing subprocesses (project modules and SJ converter)."""
        return redo_environment()

    def _append_log(self, text: str) -> None:
        self.log_text.append(text)
        self.log_text.ensureCursorVisible()

    def _start_processing(self) -> None:
        start =  self.start_image_number.value()
        end = self.end_image_number.value()
        if start > end:
            QMessageBox.warning(
                self,
                "Invalid image range",
                "The last image number must be greater than or equal to the first.",
            )
            return

        alignment_modes = []
        if self.local_checkbox.isChecked():
            alignment_modes.append("local")
        if self.global_checkbox.isChecked():
            alignment_modes.append("global")
        if not alignment_modes:
            QMessageBox.warning(
                self,
                "No alignment mode selected",
                "Select at least one alignment mode: local or global.",
            )
            return

        self.process.setProcessEnvironment(self._project_environment())
        self.process.setWorkingDirectory(str(PROJECT_ROOT))

        arguments = [
            str(PROCESSING_SCRIPT),
            "-i",
            str(self.mission_folder),
            "--start-image-number",
            str(start),
            "--end-image-number",
            str(end),
            "--alignment-modes",
            *alignment_modes,
            "--max-time-difference",
            f"{self.max_time_difference.value():.1f}",
            "--workers",
            str(load_worker_setting()),
            "--log-level",
            load_log_level_setting(),
            "--progress",
        ]
        if self.ndvi_checkbox.isChecked():
            arguments.append("--ndvi")
        if self.nir_checkbox.isChecked():
            arguments.append("--nir")
        self.log_text.append(
            f"Running: {sys.executable} {' '.join(arguments)}"
        )
        self.status_label.setText("Starting processing…")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("%p%")
        self._process_output_buffer = ""
        self._progress_total = 0
        self._last_elapsed_seconds = None
        self.run_button.setEnabled(False)
        self.review_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.start_image_number.setEnabled(False)
        self.end_image_number.setEnabled(False)
        self.ndvi_checkbox.setEnabled(False)
        self.nir_checkbox.setEnabled(False)
        self.local_checkbox.setEnabled(False)
        self.global_checkbox.setEnabled(False)
        self.max_time_difference.setEnabled(False)
        self._stopped_by_user = False
        self.run_button.hide()
        self.stop_button.show()
        self.process.start(sys.executable, arguments)

    def _stop_processing(self) -> None:
        """Stop button: ends the alignment and its worker processes."""
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        answer = QMessageBox.question(
            self, "Stop the alignment",
            "Stop the alignment now?\n\nThe images already aligned are kept. "
            "Run alignment again later: the images already done reuse their motion model.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._stopped_by_user = True
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping…")
        self.log_text.append("\nStopping the alignment (asked by the user)…")
        kill_process_tree(self.process.processId())
        if not self.process.waitForFinished(5000):
            self.process.kill()

    def _processing_controls_idle(self) -> None:
        self.stop_button.hide()
        self.stop_button.setEnabled(True)
        self.run_button.show()

    def _read_process_output(self, final: bool = False) -> None:
        output = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._process_output_buffer += output
        lines = self._process_output_buffer.splitlines(keepends=True)
        self._process_output_buffer = ""
        for line in lines:
            if line.endswith(("\n", "\r")) or final:
                self._handle_process_output_line(line.rstrip("\r\n"))
            else:
                self._process_output_buffer = line
        if final and self._process_output_buffer:
            self._handle_process_output_line(self._process_output_buffer)
            self._process_output_buffer = ""

    def _handle_process_output_line(self, line: str) -> None:
        progress_match = PROGRESS_LINE_PATTERN.fullmatch(line)
        if progress_match is not None:
            current = int(progress_match.group(1))
            total = int(progress_match.group(2))
            filename = progress_match.group(3) or ""
            elapsed = progress_match.group(4)
            eta = progress_match.group(5)
            if total < 1 or current < 0 or current > total:
                return
            if elapsed is not None:
                self._last_elapsed_seconds = float(elapsed)
            if self._progress_total != total:
                self._progress_total = total
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(0)
            self.progress_bar.setValue(current)
            status = f"Images processed: {current} of {total}"
            if filename and filename != "-":
                status += f" — {filename}"
            if elapsed is not None:
                status += f" — elapsed {self._format_duration(float(elapsed))}"
            if eta is not None and float(eta) >= 0:
                status += f" — estimated remaining {self._format_duration(float(eta))}"
            self.status_label.setText(status)
            return
        self.log_text.append(line)
        self.log_text.ensureCursorVisible()

    def _on_process_started(self) -> None:
        self.status_label.setText("Processing…")
        self.log_text.append("\nProcessing started.")

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        self._read_process_output(final=True)
        self._processing_controls_idle()
        if self._progress_total == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1 if exit_code == 0 else 0)
        elif exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self.progress_bar.setValue(self._progress_total)
        self.run_button.setEnabled(True)
        self.review_button.setEnabled(self._has_alignment_output())
        self.close_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.start_image_number.setEnabled(True)
        self.end_image_number.setEnabled(True)
        self.ndvi_checkbox.setEnabled(True)
        self.nir_checkbox.setEnabled(True)
        self.local_checkbox.setEnabled(True)
        self.global_checkbox.setEnabled(True)
        self.max_time_difference.setEnabled(True)

        if getattr(self, "_stopped_by_user", False):
            self._stopped_by_user = False
            done = self.progress_bar.value() if self._progress_total else 0
            text = (f"Stopped: {done} of {self._progress_total} images aligned."
                    if self._progress_total else "Stopped.")
            self.status_label.setText(text + " Run alignment to go on.")
            self.log_text.append("\n" + text)
            self.run_button.setText("Run alignment again")
            return
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            if self._last_elapsed_seconds is not None and self._progress_total:
                average = self._last_elapsed_seconds / self._progress_total
                self.status_label.setText(
                    "Processing completed in "
                    f"{self._format_duration(self._last_elapsed_seconds)} "
                    f"(average {self._format_duration(average)} per image)."
                )
            else:
                self.status_label.setText("Processing completed successfully.")
            self.log_text.append("\nProcessing completed successfully.")
            mark_step_done(self.mission_folder, 4)
            self.review_button.setEnabled(True)
            self.review_button.setDefault(True)
            self.review_button.setFocus()
            if self.auto_run:
                self.auto_run = False
                QTimer.singleShot(400, self._open_review)
        else:
            self.status_label.setText(f"Processing failed (exit code {exit_code}).")
            self.log_text.append(f"\nProcessing failed (exit code {exit_code}).")

    def _on_process_error(self, error) -> None:
        if getattr(self, "_stopped_by_user", False):
            return               # killed on purpose: _on_process_finished reports it
        if error != QProcess.ProcessError.FailedToStart:
            self.log_text.append(f"\nProcessing process error: {self.process.errorString()}")
            return

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._processing_controls_idle()
        self.status_label.setText("Unable to start processing.")
        self.run_button.setEnabled(True)
        self.review_button.setEnabled(self._has_alignment_output())
        self.close_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.start_image_number.setEnabled(True)
        self.end_image_number.setEnabled(True)
        self.ndvi_checkbox.setEnabled(True)
        self.nir_checkbox.setEnabled(True)
        self.local_checkbox.setEnabled(True)
        self.global_checkbox.setEnabled(True)
        self.max_time_difference.setEnabled(True)
        self.log_text.append(
            f"\nUnable to start processing: {self.process.errorString()}"
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = max(0, round(seconds))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} h {minutes:02d} min"
        if minutes:
            return f"{minutes} min {seconds:02d} s"
        return f"{seconds} s"

    def closeEvent(self, event) -> None:
        if (
            self.process.state() != QProcess.ProcessState.NotRunning
        ):
            QMessageBox.information(
                self,
                "Processing in progress",
                "Wait for image processing to finish, or stop it, before closing this window.",
            )
            event.ignore()
            return
        event.accept()
