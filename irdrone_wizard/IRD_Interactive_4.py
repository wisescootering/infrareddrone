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

from PyQt6.QtCore import QProcess, QProcessEnvironment, QSettings, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from IRD_Interactive_styles import BUTTON_STYLE
import IRD_Interactive_help as Help
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
        workers_layout.addWidget(safe_button)
        workers_layout.addStretch()
        layout.addLayout(workers_layout)

        explanation = QLabel(
            "Each worker aligns one shoot point and needs about "
            f"{ALIGNMENT_WORKER_MEMORY_GB:g} GB of memory. Auto uses the physical "
            "cores, limited by the RAM available when the run starts. "
            "Use 1 (safe mode) if the computer freezes or the run is killed."
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


def select_aligned_jpegs(parent, folder: Path) -> list[str]:
    """Ask for aligned VIR / NDVI / NIR images with the native file explorer."""
    files, _ = QFileDialog.getOpenFileNames(
        parent,
        "Select misaligned images",
        str(folder),
        "Aligned images (VIR_*.jpg NDVI_*.jpg NIR_*.jpg);;All files (*)",
    )
    return files


def image_numbers_from_aligned_jpegs(paths) -> tuple[set[int], list[str]]:
    """Return the image numbers of aligned VIR / NDVI / NIR images and the ignored names."""
    numbers = set()
    ignored = []
    for path in paths:
        name = Path(path).name
        match = ALIGNED_JPEG_PATTERN.fullmatch(name)
        if match is None:
            ignored.append(name)
        else:
            numbers.add(int(match.group(1)))
    return numbers, ignored


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


class RedoSelectionDialog(QDialog):
    """Let the user tick the failed shoot points to realign manually."""

    def __init__(self, entries, parent=None):
        """``entries``: list of ``(number, VIS stem, REDO batch available)``."""
        super().__init__(parent)
        self.setWindowTitle("Redo misaligned points")
        self.resize(420, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Shoot points flagged as failed.\n"
                "Tick the ones to realign manually (a slider window will open for each)."
            )
        )
        self.list_widget = QListWidget()
        for number, stem, available in entries:
            item = QListWidgetItem(stem)
            item.setData(Qt.ItemDataRole.UserRole, number)
            if available:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(f"{stem}{REDO_BATCH_SUFFIX} not found: run the alignment again.")
                item.setText(f"{stem}  (no REDO file)")
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        select_layout = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        select_none = QPushButton("Clear")
        select_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        select_layout.addWidget(select_all)
        select_layout.addWidget(select_none)
        select_layout.addStretch()
        layout.addLayout(select_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("Start redo")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        ok_button.setStyleSheet(BUTTON_STYLE)
        cancel_button.setStyleSheet(BUTTON_STYLE)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def _set_all(self, state) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def selected_numbers(self) -> list[int]:
        return [
            self.list_widget.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list_widget.count())
            if self.list_widget.item(row).checkState() == Qt.CheckState.Checked
        ]


class AlignmentCheckDialog(QDialog):
    """Show the regenerated VIR image and ask whether it is correctly aligned."""

    def __init__(self, image_path: Path, title: str, parent=None):
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{self.image_path.name}</b> – is this image correctly aligned?"))

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(self.image_path))
        if pixmap.isNull():
            image_label.setText("Unable to display the image.")
        else:
            available = self.screen().availableGeometry()
            pixmap = pixmap.scaled(
                int(available.width() * 0.8),
                int(available.height() * 0.7),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            image_label.setPixmap(pixmap)
        layout.addWidget(image_label)

        button_layout = QHBoxLayout()
        open_button = QPushButton("Open full size")
        open_button.clicked.connect(self._open_full_size)
        yes_button = QPushButton("Yes, aligned")
        yes_button.clicked.connect(self.accept)
        no_button = QPushButton("No, still misaligned")
        no_button.clicked.connect(self.reject)
        for button in (open_button, yes_button, no_button):
            button.setStyleSheet(BUTTON_STYLE)
        button_layout.addWidget(open_button)
        button_layout.addStretch()
        button_layout.addWidget(yes_button)
        button_layout.addWidget(no_button)
        layout.addLayout(button_layout)

    def _open_full_size(self) -> None:
        try:
            if not Help.open_with_default_app(self.image_path):
                raise OSError(f"No application available to open {self.image_path}")
        except OSError as error:
            QMessageBox.warning(self, "Unable to open the image", str(error))


class DialogImageProcessing(QDialog):
    """Run the post-preprocessing image pipeline for a mission."""

    def __init__(self, mission_parameters: dict, parent=None):
        super().__init__(parent)

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

        # Manual redo of failed shoot points (one subprocess at a time).
        self.redo_process = QProcess(self)
        self.redo_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.redo_process.readyReadStandardOutput.connect(self._read_redo_output)
        self.redo_process.finished.connect(self._on_redo_finished)
        self.redo_process.errorOccurred.connect(self._on_redo_error)
        self._redo_queue = []
        self._redo_current = None
        self._redo_started_at = 0.0
        self._redo_validated = []
        self._redo_rejected = []
        self._redo_errors = []

        self.setWindowTitle("Step 4 – Image processing")
        self.resize(700, 500)
        self._init_gui()

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
        layout.addWidget(QLabel(f"<b>Mission:</b> {self.mission_folder}"))
        layout.addWidget(
            QLabel(
                f"{self.pair_count} preprocessed image pairs found. "
                "The inclusive image-number range is pre-filled from Step 2's "
                "visible FLY frames."
            )
        )

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
        self.flag_button = QPushButton("Flag misaligned points")
        self.flag_button.clicked.connect(self._flag_misaligned_points)
        self.flag_button.setStyleSheet(BUTTON_STYLE)
        button_layout.addWidget(self.flag_button)
        self.redo_button = QPushButton("Redo misaligned points")
        self.redo_button.clicked.connect(self._redo_misaligned_points)
        self.redo_button.setStyleSheet(BUTTON_STYLE)
        button_layout.addWidget(self.redo_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
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
            (self.max_time_difference, "btn:step4_options", "Shoot points whose VIS/NIR time difference exceeds this value are not processed."),
            (self.run_button, "btn:step4_run_alignment", "Align the VIS and NIR images of the selected shoot points (can take a long time)."),
            (self.flag_button, "btn:step4_flag_misaligned", "Select in the explorer the misaligned VIR images and flag them as failed."),
            (self.redo_button, "btn:step4_redo", "Manually realign the shoot points flagged as failed, then validate the result."),
            (self.close_button, "btn:step4_close", "Close this window."),
            (self.settings_button, "btn:step4_options", "Processing settings (worker processes / safe mode, log detail)."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

        # Apply the common style to the three main buttons
        self.run_button.setStyleSheet(BUTTON_STYLE)
        self.close_button.setStyleSheet(BUTTON_STYLE)

        layout.addLayout(button_layout)

    def _open_settings(self) -> None:
        dialog = Step4SettingsDialog(
            load_worker_setting(), load_log_level_setting(), parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            save_worker_setting(dialog.workers())
            save_log_level_setting(dialog.log_level())

    def _flag_misaligned_points(self) -> None:
        output_folder = self.mission_folder / "ImgIRdrone"
        inventory_path = output_folder / "shoot_points.json"
        if not inventory_path.is_file():
            QMessageBox.warning(
                self,
                "Alignment output not found",
                f"Run the alignment first. File not found:\n{inventory_path}",
            )
            return

        QMessageBox.information(
            self,
            "Flag misaligned points",
            f"Select the images ({ALIGNED_JPEG_LABEL}) that you consider "
            "misaligned. The matching shoot points will be marked as failed.",
        )
        selected_files = select_aligned_jpegs(self, output_folder)
        if not selected_files:
            return

        numbers, ignored = image_numbers_from_aligned_jpegs(selected_files)
        if ignored:
            self.log_text.append(
                f"Ignored files (not {ALIGNED_JPEG_LABEL}): " + ", ".join(ignored)
            )
        if not numbers:
            QMessageBox.warning(
                self, "No valid image", f"No {ALIGNED_JPEG_LABEL} image was selected."
            )
            return

        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            result = apply_failed_selection(inventory, numbers)
            shutil.copy2(inventory_path, inventory_path.with_name(
                inventory_path.name + ".bak"
            ))
            _write_json_atomic(inventory_path, inventory)
            _write_json_atomic(
                output_folder / FAILED_SUMMARY_FILENAME,
                build_failed_summary(inventory),
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Unable to update shoot points", str(error))
            return

        message = (
            f"{result['newly_flagged']} shoot point(s) marked as failed, "
            f"{result['already_flagged']} already failed."
        )
        if result["not_found"]:
            message += " Not in shoot_points.json (ignored): " + ", ".join(
                f"{number:04d}" for number in result["not_found"]
            )
        self.log_text.append(message)
        self.status_label.setText(message)
        QMessageBox.information(self, "Shoot points updated", message)

    @staticmethod
    def _project_environment() -> QProcessEnvironment:
        """Environment of the processing subprocesses (project modules and SJ converter)."""
        environment = QProcessEnvironment.systemEnvironment()
        python_path = os.environ.get("PYTHONPATH", "")
        project_python_path = str(PROJECT_ROOT)
        if python_path:
            project_python_path = os.pathsep.join((project_python_path, python_path))
        environment.insert("PYTHONPATH", project_python_path)
        environment.insert("SJCONVERTERPATH", str(SJCONVERTERPATH))
        return environment

    def _set_redo_busy(self, busy: bool) -> None:
        for button in (self.run_button, self.flag_button, self.redo_button, self.close_button):
            button.setEnabled(not busy)

    def _redo_misaligned_points(self) -> None:
        """Realign manually the failed shoot points chosen by the user, then validate them."""
        output_folder = self.mission_folder / "ImgIRdrone"
        inventory_path = output_folder / "shoot_points.json"
        if not inventory_path.is_file():
            QMessageBox.warning(
                self,
                "Alignment output not found",
                f"Run the alignment first. File not found:\n{inventory_path}",
            )
            return
        if not (output_folder / FAILED_SUMMARY_FILENAME).is_file():
            QMessageBox.information(
                self,
                "Misaligned points not flagged yet",
                "No list of failed shoot points exists yet.\n\n"
                f"Examine the images of the ImgIRdrone folder ({ALIGNED_JPEG_LABEL}), "
                "use 'Flag misaligned points' to mark the misaligned ones, "
                "then come back here.",
            )
            return
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            failed = failed_point_names(inventory)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Unable to read shoot points", str(error))
            return
        if not failed:
            QMessageBox.information(
                self,
                "No failed shoot point",
                "No shoot point is flagged as failed.\n"
                "Use 'Flag misaligned points' to mark the misaligned ones first.",
            )
            return

        entries = [
            (number, stem, (output_folder / f"{stem}{REDO_BATCH_SUFFIX}").is_file())
            for number, stem in failed
        ]
        dialog = RedoSelectionDialog(entries, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = set(dialog.selected_numbers())
        if not selected:
            return

        queue = []
        for number, stem in failed:
            if number not in selected:
                continue
            try:
                arguments = read_redo_command(output_folder / f"{stem}{REDO_BATCH_SUFFIX}")
            except (OSError, ValueError) as error:
                self.log_text.append(f"{stem}: redo skipped ({error})")
                continue
            queue.append((number, stem, arguments))
        if not queue:
            QMessageBox.warning(self, "Nothing to redo", "No selected point can be realigned.")
            return

        QMessageBox.information(
            self,
            "Manual alignment",
            "A slider window opens for each selected point. Adjust yaw, pitch and roll "
            "until VIS and NIR overlap, then close that window: the alignment is "
            "recomputed and the new VIR image is shown for validation.",
        )
        self._redo_queue = queue
        self._redo_validated = []
        self._redo_rejected = []
        self._redo_errors = []
        self._set_redo_busy(True)
        self._start_next_redo()

    def _start_next_redo(self) -> None:
        if not self._redo_queue:
            self._finish_redo()
            return
        number, stem, arguments = self._redo_queue.pop(0)
        self._redo_current = (number, stem)
        self._redo_started_at = time.time()
        full_arguments = [str(PROJECT_ROOT / "automatic_registration.py"), *arguments]
        self.redo_process.setProcessEnvironment(self._project_environment())
        self.redo_process.setWorkingDirectory(str(PROJECT_ROOT))
        self.log_text.append(f"\nRedo {stem}: {sys.executable} {' '.join(full_arguments)}")
        self.status_label.setText(
            f"Redo {stem}: adjust the sliders, then close the window to continue."
        )
        self.progress_bar.setRange(0, 0)
        self.redo_process.start(sys.executable, full_arguments)

    def _read_redo_output(self) -> None:
        output = bytes(self.redo_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if output.strip():
            self.log_text.append(output.rstrip())
            self.log_text.ensureCursorVisible()

    def _on_redo_error(self, error) -> None:
        # A process that never started emits no "finished" signal.
        if error != QProcess.ProcessError.FailedToStart:
            return
        stem = self._redo_current[1]
        self.log_text.append(f"Unable to start the redo of {stem}: {self.redo_process.errorString()}")
        self._redo_errors.append(stem)
        self._start_next_redo()

    def _on_redo_finished(self, exit_code: int, exit_status) -> None:
        self._read_redo_output()
        number, stem = self._redo_current
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self.log_text.append(f"Redo of {stem} failed (exit code {exit_code}).")
            self._redo_errors.append(stem)
            self._start_next_redo()
            return

        output_folder = self.mission_folder / "ImgIRdrone"
        vir_path = redo_check_image(output_folder, stem, self._redo_started_at)
        if vir_path is None:
            self.log_text.append(
                f"Redo of {stem}: no aligned image ({ALIGNED_JPEG_LABEL}) was generated."
            )
            self._redo_errors.append(stem)
            self._start_next_redo()
            return

        check = AlignmentCheckDialog(vir_path, f"{stem} – new alignment", self)
        if check.exec() == QDialog.DialogCode.Accepted:
            try:
                mark_points_aligned(output_folder, {number})
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Unable to update shoot points", str(error))
                self._redo_errors.append(stem)
            else:
                self._redo_validated.append(stem)
                self.log_text.append(f"{stem}: alignment validated, shoot point no longer failed.")
        else:
            self._redo_rejected.append(stem)
            self.log_text.append(f"{stem}: alignment rejected, shoot point still failed.")
        self._start_next_redo()

    def _finish_redo(self) -> None:
        self._redo_current = None
        self._set_redo_busy(False)
        message = (
            f"Redo finished: {len(self._redo_validated)} validated, "
            f"{len(self._redo_rejected)} still misaligned, "
            f"{len(self._redo_errors)} error(s)."
        )
        self.status_label.setText(message)
        self.log_text.append(message)
        QMessageBox.information(self, "Redo finished", message)

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
        self.flag_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.start_image_number.setEnabled(False)
        self.end_image_number.setEnabled(False)
        self.ndvi_checkbox.setEnabled(False)
        self.nir_checkbox.setEnabled(False)
        self.local_checkbox.setEnabled(False)
        self.global_checkbox.setEnabled(False)
        self.max_time_difference.setEnabled(False)
        self.process.start(sys.executable, arguments)

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
        if self._progress_total == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1 if exit_code == 0 else 0)
        elif exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self.progress_bar.setValue(self._progress_total)
        self.run_button.setEnabled(True)
        self.flag_button.setEnabled(True)
        self.redo_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.start_image_number.setEnabled(True)
        self.end_image_number.setEnabled(True)
        self.ndvi_checkbox.setEnabled(True)
        self.nir_checkbox.setEnabled(True)
        self.local_checkbox.setEnabled(True)
        self.global_checkbox.setEnabled(True)
        self.max_time_difference.setEnabled(True)

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
        else:
            self.status_label.setText(f"Processing failed (exit code {exit_code}).")
            self.log_text.append(f"\nProcessing failed (exit code {exit_code}).")

    def _on_process_error(self, error) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            self.log_text.append(f"\nProcessing process error: {self.process.errorString()}")
            return

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText("Unable to start processing.")
        self.run_button.setEnabled(True)
        self.flag_button.setEnabled(True)
        self.redo_button.setEnabled(True)
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
            or self.redo_process.state() != QProcess.ProcessState.NotRunning
        ):
            QMessageBox.information(
                self,
                "Processing in progress",
                "Wait for image processing to finish before closing this window.",
            )
            event.ignore()
            return
        event.accept()
