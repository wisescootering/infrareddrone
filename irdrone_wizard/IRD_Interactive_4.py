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
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from IRD_Interactive_look import DIALOG_STYLE, PRIMARY_STYLE, SECONDARY_STYLE, close_text, reset_button
import IRD_Interactive_look as Look
import IRD_Interactive_help as Help
from IRD_Interactive_progress import mark_step_done
import best_mapping
from config import SJCONVERTERPATH
from alignment_workers import (
    ALIGNMENT_WORKER_MEMORY_GB,
    MAX_WORKERS,
    REDO_WORKER_MEMORY_GB,
    available_alignment_workers,
    clamp_workers,
    memory_fitting_workers,
)
from manual_redo_archives import restore_manual_redo_originals


STEP_NAME = "Image processing"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSING_SCRIPT = PROJECT_ROOT / "run_after_preprocessing.py"
VIS_FILENAME_PATTERN = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)
PROGRESS_LINE_PATTERN = re.compile(
    r"^STEP4_PROGRESS (\d+) (\d+)(?: (\S+))?(?: ([\d.]+) (-?[\d.]+))?$"
)
WORKERS_LINE_PATTERN = re.compile(r"^Alignment workers: (\d+)")
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
        safe_button.setStyleSheet(SECONDARY_STYLE)
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

        self._opened = (self.workers(), self.log_level())
        self.btn_reset = reset_button("Back to the default settings: Auto workers, warnings only.")
        self.btn_reset.clicked.connect(self.reset)
        self.btn_close = QPushButton(close_text(False))
        self.btn_close.setStyleSheet(PRIMARY_STYLE)
        self.btn_close.setDefault(True)
        self.btn_close.setToolTip("Close; once a setting is changed, keep it for the next runs and sessions.")
        self.btn_close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_reset)
        buttons.addStretch()
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)
        self.workers_spin.valueChanged.connect(self._update_close)
        self.log_level_combo.currentIndexChanged.connect(self._update_close)
        self._update_close()

    def changed(self) -> bool:
        return (self.workers(), self.log_level()) != self._opened

    def _update_close(self, *_):
        self.btn_close.setText(close_text(self.changed()))
        self.btn_reset.setVisible((self.workers(), self.log_level()) != (0, LOG_LEVELS[0][0]))

    def reset(self):
        self.workers_spin.setValue(0)
        self.log_level_combo.setCurrentIndex(0)

    def reject(self):
        """Closing the window (title bar, Esc) keeps the settings, like Close."""
        self.accept()

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


def redo_workers() -> int:
    """Realignments computed at once: the Step 4 setting (0: automatic)."""
    return clamp_workers(load_worker_setting() or available_alignment_workers())


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
REDO_STAGES = [("load", "Loading the images"), ("compute", "Computing the alignment"), ("write", "Saving")]


def _option_values(arguments, option: str) -> list:
    """Values following ``option`` in a command line (up to the next option)."""
    if option not in arguments:
        return []
    values = []
    for value in arguments[arguments.index(option) + 1:]:
        if value.startswith("--"):
            break
        values.append(value)
    return values


def redo_pair(arguments) -> tuple:
    """``(visible image, infrared image, initial angles or None)`` of a REDO command."""
    images = _option_values(arguments, "--images")
    if len(images) < 2:
        raise ValueError("REDO command without its two images")
    try:
        angles = [float(v) for v in _option_values(arguments, "--angles")][:3]
    except ValueError:
        angles = []
    return Path(images[0]), Path(images[1]), (tuple(angles) if len(angles) == 3 else None)


def manual_redo_arguments(arguments, angles) -> list:
    """REDO command of a point aligned by hand in the wizard: no slider window,
    the alignment starts from the user's ``(yaw, pitch, roll)``."""
    out, skipping = [], False
    for value in arguments:
        if value.startswith("--"):
            skipping = value in ("--angles", "--manual-angles")
            if skipping or value == "--manual":
                continue
        elif skipping:
            continue
        out.append(value)
    return out + ["--manual-angles", *(f"{float(v):.3f}" for v in angles)]


class RedoRunner(QObject):
    """Realignment of shoot points whose manual alignment is already done (the
    angles are in their arguments, see ``manual_redo_arguments``): up to
    ``workers`` automatic_registration.py subprocesses at once, nothing to do
    for the user meanwhile. Points may be added while others run.

    Two points sharing an infrared image never run together (its proxy is
    written on first use). ``point_done`` gives the new aligned image (empty if
    none) or an error."""

    point_started = pyqtSignal(int, str)          # number, stem
    stage = pyqtSignal(int, str, str)             # number, stem, load / compute / write
    output = pyqtSignal(str)                      # console output / log lines
    point_done = pyqtSignal(int, str, str, str)   # number, stem, aligned image, error
    all_done = pyqtSignal()

    def __init__(self, output_folder: Path, parent=None, workers: int = 1,
                 memory_per_worker_gb: float = REDO_WORKER_MEMORY_GB):
        super().__init__(parent)
        self.output_folder = Path(output_folder)
        self.max_workers = max(1, int(workers))     # the Step 4 setting
        self.memory_per_worker_gb = memory_per_worker_gb
        self.workers = self.max_workers             # lowered to the free RAM at each run
        self._queue = []
        self.jobs = {}           # QProcess -> {"number", "stem", "nir", "started", "partial", "stage"}
        self.total = 0           # points of the run (since the runner was last idle)
        self.finished = 0

    def busy(self) -> bool:
        return bool(self._queue or self.jobs)

    def numbers(self) -> set:
        """Points waiting or running."""
        return {task[0] for task in self._queue} | {job["number"] for job in self.jobs.values()}

    def running(self) -> list:
        return list(self.jobs.values())

    def add(self, tasks) -> None:
        """Queue ``(number, stem, arguments)`` (arguments: see ``manual_redo_arguments``)."""
        tasks = [t for t in tasks if t[0] not in self.numbers()]
        if not self.busy():
            self.total = self.finished = 0
            # Measured while no redo runs: each one needs its share of RAM, or
            # the system kills them (out of memory) in the middle of a write.
            self.workers = memory_fitting_workers(self.max_workers, self.memory_per_worker_gb)
            if tasks and self.workers < self.max_workers:
                self.output.emit(
                    f"Realignments computed {self.workers} at a time (not {self.max_workers}): "
                    f"about {self.memory_per_worker_gb:g} GB of RAM each, not enough free memory.")
        self._queue.extend(tasks)
        self.total += len(tasks)
        self._fill()

    def stop(self) -> None:
        """Start no other point: the running ones finish."""
        self.total -= len(self._queue)
        self._queue = []
        if not self.jobs:
            self.all_done.emit()

    @staticmethod
    def _nir(arguments) -> str:
        images = _option_values(arguments, "--images")
        return os.path.normcase(os.path.abspath(images[1])) if len(images) > 1 else ""

    def _fill(self) -> None:
        busy_nir = {job["nir"] for job in self.jobs.values()}
        for task in list(self._queue):
            if len(self.jobs) >= self.workers:
                break
            nir = self._nir(task[2])
            if nir and nir in busy_nir:
                continue
            self._queue.remove(task)
            busy_nir.add(nir)
            self._start(task, nir)

    def _start(self, task, nir) -> None:
        number, stem, arguments = task
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda p=process: self._read_output(p))
        process.finished.connect(lambda code, status, p=process: self._on_finished(p, code, status))
        process.errorOccurred.connect(lambda error, p=process: self._on_error(p, error))
        self.jobs[process] = {"number": number, "stem": stem, "nir": nir, "started": time.time(),
                              "partial": "", "stage": "load", "arguments": list(arguments)}
        full_arguments = [str(PROJECT_ROOT / "automatic_registration.py"), *arguments]
        process.setProcessEnvironment(redo_environment())
        process.setWorkingDirectory(str(PROJECT_ROOT))
        self.output.emit(f"\nRedo {stem}: {sys.executable} {' '.join(full_arguments)}")
        self.point_started.emit(number, stem)
        process.start(sys.executable, full_arguments)

    def _read_output(self, process) -> None:
        job = self.jobs.get(process)
        if job is None:
            return
        output = job["partial"] + bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        lines = output.split("\n")
        job["partial"] = lines.pop()          # an unfinished line waits for the rest
        shown = []
        for line in lines:
            if line.startswith(STAGE_MARKER):
                job["stage"] = line[len(STAGE_MARKER):].strip()
                self.stage.emit(job["number"], job["stem"], job["stage"])
            else:
                shown.append(line.rstrip("\r"))
        text = "\n".join(shown)
        if text.strip():
            self.output.emit(text.rstrip())

    def _flush_output(self, process) -> None:
        self._read_output(process)
        job = self.jobs[process]
        if job["partial"].strip() and not job["partial"].startswith(STAGE_MARKER):
            self.output.emit(job["partial"].rstrip())
        job["partial"] = ""

    def _on_error(self, process, error) -> None:
        # A process that never started emits no "finished" signal.
        if error != QProcess.ProcessError.FailedToStart or process not in self.jobs:
            return
        self._done(process, "", f"Unable to start the redo: {process.errorString()}")

    def _on_finished(self, process, exit_code: int, exit_status) -> None:
        if process not in self.jobs:
            return
        self._flush_output(process)
        job = self.jobs[process]
        stem = job["stem"]
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            crashed = exit_status != QProcess.ExitStatus.NormalExit
            image = ""
            error = (f"Redo of {stem} stopped by the system (out of memory?)." if crashed
                     else f"Redo of {stem} failed (exit code {exit_code}).")
            restored = self._restore(job)
            if restored:
                error += f" Its previous alignment was put back ({restored} file(s))."
        else:
            found = redo_check_image(self.output_folder, stem, job["started"])
            image = str(found) if found is not None else ""
            error = "" if found is not None else \
                f"Redo of {stem}: no aligned image ({ALIGNED_JPEG_LABEL}) was generated."
        self._done(process, image, error)

    def _restore(self, job) -> int:
        """Point of a failed redo back to its state before the redo (a killed
        process cannot do it itself): number of files put back."""
        arguments = job.get("arguments") or []
        images = _option_values(arguments, "--images")
        if not images:
            return 0
        vis = Path(images[0])
        out_dir = (_option_values(arguments, "--outdir") or [None])[0]
        out_dir = Path(out_dir) if out_dir else vis.parent
        multispectral = (_option_values(arguments, "--multispectral-folder") or [None])[0]
        original_dir = out_dir / f"{vis.stem}_align_traces_manual" / "original"
        if not original_dir.is_dir():
            return 0
        try:
            restored = restore_manual_redo_originals(
                vis, out_dir, multispectral, original_dir, since=job["started"])
        except OSError as error:
            self.output.emit(f"{job['stem']}: previous alignment not put back ({error})")
            return 0
        return len(restored)

    def _done(self, process, image, error) -> None:
        job = self.jobs.pop(process)
        process.deleteLater()
        self.finished += 1
        self._fill()
        self.point_done.emit(job["number"], job["stem"], image, error)
        if not self.busy():
            self.all_done.emit()


class DialogImageProcessing(QDialog):
    """Run the post-preprocessing image pipeline for a mission.

    auto_run (chained from Step 3): the alignment starts at once with the
    survey range of Step 2, and the review of the aligned images opens when
    it is done."""

    continue_requested = pyqtSignal()     # "Continue with mapping": the main window opens Step 5

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
        self.shoot_points = shoot_points
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


        self.setWindowTitle(Look.step_window_title(4, STEP_NAME, self.mission_folder))
        self.setStyleSheet(DIALOG_STYLE)
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
        layout.addWidget(Look.step_header(4, STEP_NAME, self.mission_folder))
        intro = QLabel(
            f"{self.pair_count} preprocessed image pairs found. "
            "The inclusive image-number range is pre-filled from Step 2's "
            "visible FLY frames."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # One setting per line, the label left of its field: the window stays
        # narrow whatever the font (a row of four widgets did not).
        settings_form = QFormLayout()
        self.start_image_number = QSpinBox()
        self.start_image_number.setRange(1, self.max_image_number)
        self.start_image_number.setValue(self.start_image_number_value)
        settings_form.addRow("First VIS image number:", self.start_image_number)
        self.end_image_number = QSpinBox()
        self.end_image_number.setRange(1, self.max_image_number)
        self.end_image_number.setValue(self.end_image_number_value)
        settings_form.addRow("Last VIS image number (inclusive):", self.end_image_number)
        self.max_time_difference = QDoubleSpinBox()
        self.max_time_difference.setRange(0.1, 6.0)
        self.max_time_difference.setDecimals(1)
        self.max_time_difference.setSingleStep(0.1)
        self.max_time_difference.setValue(0.5)
        settings_form.addRow("Maximum VIS/NIR time difference (s):", self.max_time_difference)
        settings_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        layout.addLayout(settings_form)

        traces_group = QGroupBox("Generated image traces")
        traces_layout = QGridLayout(traces_group)
        self.ndvi_checkbox = QCheckBox("NDVI")
        self.ndvi_checkbox.setChecked(False)
        traces_layout.addWidget(self.ndvi_checkbox, 0, 0)
        self.nir_checkbox = QCheckBox("NIR")
        self.nir_checkbox.setChecked(False)
        traces_layout.addWidget(self.nir_checkbox, 0, 1)
        self.local_checkbox = QCheckBox("Local alignment")
        self.local_checkbox.setChecked(True)
        traces_layout.addWidget(self.local_checkbox, 1, 0)
        self.global_checkbox = QCheckBox("Global alignment")
        self.global_checkbox.setChecked(False)
        traces_layout.addWidget(self.global_checkbox, 1, 1)
        traces_layout.setColumnStretch(2, 1)
        layout.addWidget(traces_group)

        # Best mapping: the choice of Step 2 (FlightAnalytics/best_mapping.json)
        choice = best_mapping.load_choice(self.mission_folder)
        self.best_mapping_group = QGroupBox("Images aligned")
        best_row = QHBoxLayout(self.best_mapping_group)
        best_group_layout = QVBoxLayout()
        best_row.addLayout(best_group_layout, 1)
        best_layout = QHBoxLayout()
        best_group_layout.addLayout(best_layout)
        self.best_mapping_radio = QRadioButton("Best mapping: only the images the map needs")
        self.all_images_radio = QRadioButton("All the synchronised images")
        self.best_mapping_radio.setChecked(choice["enabled"])
        self.all_images_radio.setChecked(not choice["enabled"])
        best_layout.addWidget(self.best_mapping_radio)
        best_layout.addStretch()
        overlap_layout = QHBoxLayout()
        overlap_layout.addSpacing(24)
        overlap_layout.addWidget(QLabel("Overlap between kept images:"))
        self.best_mapping_overlap = QSpinBox()
        self.best_mapping_overlap.setRange(round(best_mapping.MIN_OVERLAP * 100),
                                           round(best_mapping.MAX_OVERLAP * 100))
        self.best_mapping_overlap.setSingleStep(5)
        self.best_mapping_overlap.setSuffix(" %")
        self.best_mapping_overlap.setValue(round(choice["overlap"] * 100))
        overlap_layout.addWidget(self.best_mapping_overlap)
        overlap_layout.addStretch()
        best_group_layout.addLayout(overlap_layout)
        best_group_layout.addWidget(self.all_images_radio)
        self.best_mapping_count = QLabel()
        self.best_mapping_count.setWordWrap(True)
        best_group_layout.addWidget(self.best_mapping_count)
        best_group_layout.addStretch()
        self.map_model = None
        self._map_jobs, self._map_done, self._map_workers = [], set(), 1
        self.map_view = self._build_map()
        if self.map_view is not None:
            best_row.addWidget(self.map_view, 1)
        layout.addWidget(self.best_mapping_group)
        for signal in (self.best_mapping_radio.toggled, self.best_mapping_overlap.valueChanged,
                       self.start_image_number.valueChanged, self.end_image_number.valueChanged,
                       self.max_time_difference.valueChanged):
            signal.connect(self._update_best_mapping_count)
        self._update_best_mapping_count()

        # Actions: the alignment, then the review of its result
        self.action_layout = QHBoxLayout()
        layout.addLayout(self.action_layout)

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

        # Footer: the manual (?) and settings on the left; Close, then the next step on the right
        button_layout = QHBoxLayout()
        self.run_button = QPushButton("Run alignment")
        self.run_button.clicked.connect(self._start_processing)
        self.stop_button = QPushButton("\u25A0  Stop")
        self.stop_button.setStyleSheet(
            "QPushButton { background: white; color: #B03A2E; font-weight: bold; padding: 6px 14px;"
            " border: 1px solid #E3B4AE; border-radius: 6px; } QPushButton:hover { background: #FBEDEB; }")
        self.stop_button.setToolTip("Stop the alignment. The images already aligned are kept; "
                                    "Run alignment again reuses their motion models.")
        self.stop_button.clicked.connect(self._stop_processing)
        self.stop_button.hide()
        self.close_button = QPushButton("Close")
        self.close_button.setFixedWidth(120)
        self.close_button.clicked.connect(self.close)
        self.review_button = QPushButton("Review images…")
        self.review_button.setToolTip(
            "Check the aligned images on a time line, flag the misaligned ones and realign them by hand."
        )
        self.review_button.clicked.connect(self._open_review)
        self.review_button.setEnabled(self._has_alignment_output())
        self.settings_button = QPushButton("\u2699")
        self.settings_button.setFixedWidth(36)
        # The gear glyph renders small: enlarge it, keep the button height.
        self.settings_button.setStyleSheet(
            SECONDARY_STYLE + "QPushButton { font-size: 16px; padding: 2px; }"
        )
        self.settings_button.clicked.connect(self._open_settings)
        self.help_button = QPushButton("?")
        self.help_button.setFixedWidth(36)
        self.help_button.setStyleSheet(SECONDARY_STYLE)
        self.help_button.clicked.connect(lambda: Help.show_help("ch:step4", parent=self))
        self.continue_button = Look.continue_button(
            "mapping", "Close this window and open Step 5 (the map): nothing starts until you "
                       "click Build the map.")
        self.continue_button.clicked.connect(self._continue_now)
        self.continue_button.setVisible(self._has_alignment_output())

        for widget, label, tip in (
            (self.ndvi_checkbox, "btn:step4_options", "Also write the NDVI image of each shoot point."),
            (self.nir_checkbox, "btn:step4_options", "Also write the aligned NIR image of each shoot point."),
            (self.local_checkbox, "btn:step4_options", "Write the locally aligned VIR image (VIR_XXXX_local.jpg)."),
            (self.global_checkbox, "btn:step4_options", "Write the globally aligned VIR image (VIR_XXXX_global.jpg)."),
            (self.start_image_number, "btn:step4_options", "First shoot point to align (VIS image number). Default: the survey of Step 2."),
            (self.end_image_number, "btn:step4_options", "Last shoot point to align (VIS image number, included)."),
            (self.max_time_difference, "btn:step4_options", "Shoot points whose VIS/NIR time difference exceeds this value are not processed."),
            (self.best_mapping_radio, "btn:step4_best_mapping",
             "Align only the synchronised images whose footprints overlap by the chosen amount: "
             "much less computing, and a better map (choice made in Step 2)."),
            (self.all_images_radio, "btn:step4_best_mapping",
             "Align every synchronised image of the range (more computing; Step 5 can still "
             "select the images of the map)."),
            (self.best_mapping_overlap, "btn:step4_best_mapping",
             "Overlap between the ground footprints of two successive images kept for the map "
             "(75 % recommended)."),
            (self.run_button, "btn:step4_run_alignment", "Align the VIS and NIR images of the selected shoot points (can take a long time)."),
            (self.close_button, "btn:step4_close", "Close this window."),
            (self.review_button, "ch:review", self.review_button.toolTip()),
            (self.settings_button, "btn:step4_settings", "Processing settings (worker processes / safe mode, log detail)."),
            (self.stop_button, "btn:step4_stop", self.stop_button.toolTip()),
            (self.help_button, "ch:step4", "Open the manual at Step 4."),
            (self.continue_button, "btn:step4_continue", self.continue_button.toolTip()),
        ):
            Help.attach_help(widget, label, tip, parent=self)

        # Apply the common style to the three main buttons
        self.run_button.setStyleSheet(PRIMARY_STYLE)
        self.close_button.setStyleSheet(SECONDARY_STYLE)
        self.review_button.setStyleSheet(SECONDARY_STYLE)   # ▶ is for the next step (Continue with mapping)

        self.action_layout.addWidget(self.run_button)
        self.action_layout.addWidget(self.stop_button)
        self.action_layout.addWidget(self.review_button)
        self.action_layout.addStretch()

        button_layout.addWidget(self.help_button)
        button_layout.addWidget(self.settings_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.continue_button)
        layout.addLayout(button_layout)

    def _continue_now(self) -> None:
        """Step 5 opens (nothing runs there by itself) once this window is closed."""
        if self.close():
            self.continue_requested.emit()

    def best_mapping_selection(self) -> tuple[int, int]:
        """(shoot points aligned, synchronised shoot points) with the current settings."""
        kept, synchronised = self._best_mapping_points()
        return (synchronised if kept is None else len(kept)), synchronised

    def _best_mapping_points(self) -> tuple:
        """(shoot points kept by the best mapping, None when it is off;
        number of synchronised shoot points)."""
        start, end = self.start_image_number.value(), self.end_image_number.value()
        in_range = [
            point for point in self.shoot_points
            if isinstance(point, dict) and isinstance(point.get("VIS"), dict)
            and isinstance(point["VIS"].get("FileName"), str)
            and start <= _vis_image_number(point["VIS"]["FileName"]) <= end
        ]
        limit = self.max_time_difference.value()
        flags = [(dt := best_mapping.rank_one_dt(point)) is not None and abs(dt) < limit
                 for point in in_range]
        synchronised = sum(flags)
        if not self.best_mapping_radio.isChecked():
            return None, synchronised
        kept = best_mapping.select_shoot_points(
            in_range, self.best_mapping_overlap.value() / 100.0,
            best_mapping.mission_fov(self.mission_folder), flags)
        return kept, synchronised

    def _update_best_mapping_count(self, *_args) -> None:
        self.best_mapping_overlap.setEnabled(self.best_mapping_radio.isChecked())
        try:
            kept, synchronised = self._best_mapping_points()
        except (TypeError, ValueError) as error:
            self.best_mapping_count.setText(f"(count unavailable: {error})")
            return
        if kept is not None:
            self.best_mapping_count.setText(
                f"{len(kept)} of {synchronised} synchronised shoot points will be aligned.")
        else:
            self.best_mapping_count.setText(f"All {synchronised} synchronised shoot points will be aligned.")
        self._update_map(kept)

    # ---- map: the shoot points aligned, live
    def _aligned_flags(self) -> dict:
        """VIS image number -> the shoot point is synchronised and in the range."""
        start, end = self.start_image_number.value(), self.end_image_number.value()
        limit = self.max_time_difference.value()
        flags = {}
        for point in self.shoot_points:
            try:
                number = _vis_image_number(point["VIS"]["FileName"])
            except (KeyError, TypeError, ValueError):
                continue
            dt = best_mapping.rank_one_dt(point)
            flags[number] = start <= number <= end and dt is not None and abs(dt) < limit
        return flags

    def _build_map(self):
        """Map of the shoot points (None without positions): the map is a help."""
        try:
            import flight_map as F
            import IRD_Interactive_map as Map
            from PyQt6.QtGui import QColor
            points = []
            for point in self.shoot_points:
                vis = point.get("VIS") if isinstance(point, dict) else None
                if not isinstance(vis, dict) or not isinstance(vis.get("FileName"), str):
                    continue
                mp = F.map_point(_vis_image_number(vis["FileName"]), Path(vis["FileName"]).stem, vis)
                if mp is not None:
                    points.append(mp)
            if len(points) < 2:
                return None
            synchronised, other = QColor("#4E9A3A"), QColor("#A0AAB4")
            to_do, running = QColor("#17365D"), QColor("#E8A33D")
            self._map_flags = {}

            def color_of(i):
                progress = self.map_model.progress
                if progress is not None:
                    if i in progress[0]:
                        return synchronised
                    if i in progress[1]:
                        return running
                    return to_do if self.map_model.is_selected(i) else other
                return synchronised if self._map_flags.get(points[i].number) else other
            self.map_model = Map.MapModel(
                points, fov=best_mapping.mission_fov(self.mission_folder), parent=self, color_of=color_of)
            view = Map.FlightMapView(self.map_model, compact=True)
        except Exception as error:  # never a blocker
            print(f"Step 4 map unavailable: {error}")
            self.map_model = None
            return None
        view.setMinimumSize(180, 160)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.setToolTip("Shoot points: green synchronised and in the range, grey not aligned; "
                        "the footprints of the images kept by the best mapping in green.\n"
                        "Wheel to zoom, drag to pan, double-click to see the whole flight.")
        view.hovered.connect(self.map_model.set_hover)
        view.picked.connect(self.map_model.set_current)
        return view

    def _update_map(self, kept) -> None:
        if self.map_model is None:
            return
        self.map_model.set_progress(None)
        self._map_flags = self._aligned_flags()
        if kept is None:
            self.map_model.set_selection([])
            return
        indices = (self.map_model.index_of(_vis_image_number(point["VIS"]["FileName"])) for point in kept)
        self.map_model.set_selection([i for i in indices if i is not None])

    def _set_best_mapping_enabled(self, on: bool) -> None:
        """The choice is locked while aligning; the map stays usable."""
        self.best_mapping_radio.setEnabled(on)
        self.all_images_radio.setEnabled(on)
        self.best_mapping_overlap.setEnabled(on and self.best_mapping_radio.isChecked())

    # ---- map: the progress of the alignment along the flight
    def _start_map_progress(self, kept) -> None:
        """The shoot points to align, in processing order: done in green,
        being aligned in orange (the next ones, one per worker)."""
        self._map_jobs, self._map_done = [], set()
        self._map_workers = load_worker_setting() or 1
        if self.map_model is None:
            return
        if kept is not None:
            numbers = [_vis_image_number(point["VIS"]["FileName"]) for point in kept]
        else:
            numbers = [n for n, ok in self._aligned_flags().items() if ok]
        self._map_jobs = [i for i in map(self.map_model.index_of, numbers) if i is not None]
        self.map_model.set_selection(self._map_jobs)
        self._refresh_map_progress(running=True)

    def _refresh_map_progress(self, running: bool = True) -> None:
        if self.map_model is None or not self._map_jobs:
            return
        busy = []
        if running:
            busy = [i for i in self._map_jobs if i not in self._map_done][:self._map_workers]
        self.map_model.set_progress(self._map_done, busy)

    def _map_point_done(self, filename: str) -> None:
        if self.map_model is None:
            return
        try:
            index = self.map_model.index_of(_vis_image_number(filename))
        except ValueError:
            return
        if index is not None:
            self._map_done.add(index)
            self._refresh_map_progress()

    def _fit_to_screen(self, parent=None) -> None:
        """760 x 520 (820 x 720 with the map), smaller if the screen is (centred, title bar kept)."""
        from PyQt6.QtWidgets import QApplication
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        if screen is None:
            self.resize(760, 520)
            return
        g = screen.availableGeometry()
        base_w, base_h = (820, 720) if self.map_view is not None else (760, 520)
        w = min(max(base_w, self.minimumSizeHint().width()), g.width() - 20)
        h = min(max(base_h, self.minimumSizeHint().height()), g.height() - 60)
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
        best_mapping_on = self.best_mapping_radio.isChecked()
        if best_mapping_on:
            arguments += ["--best-mapping-overlap", str(self.best_mapping_overlap.value())]
        try:
            kept, _ = self._best_mapping_points()
            best_mapping.save_choice(self.mission_folder, enabled=best_mapping_on,
                                     overlap=self.best_mapping_overlap.value() / 100.0,
                                     step4_selected=None if kept is None else
                                     [point["VIS"]["FileName"] for point in kept])
        except OSError as error:
            self.log_text.append(f"Best mapping choice not saved: {error}")
            kept = self._best_mapping_points()[0]
        self._start_map_progress(kept)
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
        self.continue_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.start_image_number.setEnabled(False)
        self.end_image_number.setEnabled(False)
        self.ndvi_checkbox.setEnabled(False)
        self.nir_checkbox.setEnabled(False)
        self.local_checkbox.setEnabled(False)
        self.global_checkbox.setEnabled(False)
        self.max_time_difference.setEnabled(False)
        self._set_best_mapping_enabled(False)
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
                self._map_point_done(filename)
            if elapsed is not None:
                status += f" — elapsed {self._format_duration(float(elapsed))}"
            if eta is not None and float(eta) >= 0:
                status += f" — estimated remaining {self._format_duration(float(eta))}"
            self.status_label.setText(status)
            return
        workers = WORKERS_LINE_PATTERN.match(line)
        if workers is not None:
            self._map_workers = max(1, int(workers.group(1)))
            self._refresh_map_progress()
        self.log_text.append(line)
        self.log_text.ensureCursorVisible()

    def _on_process_started(self) -> None:
        self.status_label.setText("Processing…")
        self.log_text.append("\nProcessing started.")

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        self._read_process_output(final=True)
        self._refresh_map_progress(running=False)
        self._processing_controls_idle()
        if self._progress_total == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1 if exit_code == 0 else 0)
        elif exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self.progress_bar.setValue(self._progress_total)
        self.run_button.setEnabled(True)
        self.review_button.setEnabled(self._has_alignment_output())
        self.continue_button.setEnabled(True)
        self.continue_button.setVisible(self._has_alignment_output())
        self.close_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.start_image_number.setEnabled(True)
        self.end_image_number.setEnabled(True)
        self.ndvi_checkbox.setEnabled(True)
        self.nir_checkbox.setEnabled(True)
        self.local_checkbox.setEnabled(True)
        self.global_checkbox.setEnabled(True)
        self.max_time_difference.setEnabled(True)
        self._set_best_mapping_enabled(True)

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
            self.continue_button.setVisible(True)
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
        self.continue_button.setEnabled(True)
        self.continue_button.setVisible(self._has_alignment_output())
        self.close_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.start_image_number.setEnabled(True)
        self.end_image_number.setEnabled(True)
        self.ndvi_checkbox.setEnabled(True)
        self.nir_checkbox.setEnabled(True)
        self.local_checkbox.setEnabled(True)
        self.global_checkbox.setEnabled(True)
        self.max_time_difference.setEnabled(True)
        self._set_best_mapping_enabled(True)
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
