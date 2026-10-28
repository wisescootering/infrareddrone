# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 4
#   Process preprocessed VIS / NIR image pairs.
# ---------------------------------------------------------------------------------

import json
import os
from pathlib import Path
import re
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QCheckBox,
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

from IRD_Interactive_styles import BUTTON_STYLE
from config import SJCONVERTERPATH


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSING_SCRIPT = PROJECT_ROOT / "run_after_preprocessing.py"
VIS_FILENAME_PATTERN = re.compile(r"^VIS_(\d+)\.dng$", re.IGNORECASE)
PROGRESS_LINE_PATTERN = re.compile(
    r"^STEP4_PROGRESS (\d+) (\d+)(?: (\S+))?(?: ([\d.]+) (-?[\d.]+))?$"
)


def _vis_image_number(filename: str) -> int:
    match = VIS_FILENAME_PATTERN.fullmatch(Path(filename).name)
    if match is None:
        raise ValueError(f"Unexpected visible image filename: {filename!r}")
    return int(match.group(1))


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
        self.run_button = QPushButton("Run alignmnent")
        self.run_button.clicked.connect(self._start_processing)
        button_layout.addWidget(self.run_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        # Apply the common style to the three main buttons
        self.run_button.setStyleSheet(BUTTON_STYLE)
        self.close_button.setStyleSheet(BUTTON_STYLE)

        layout.addLayout(button_layout)

    def _start_processing(self) -> None:
        start = self.start_image_number.value()
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

        environment = QProcessEnvironment.systemEnvironment()
        python_path = os.environ.get("PYTHONPATH", "")
        project_python_path = str(PROJECT_ROOT)
        if python_path:
            project_python_path = os.pathsep.join(
                (project_python_path, python_path)
            )
        environment.insert("PYTHONPATH", project_python_path)
        environment.insert("SJCONVERTERPATH", str(SJCONVERTERPATH))
        self.process.setProcessEnvironment(environment)
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
        self.close_button.setEnabled(False)
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
        self.close_button.setEnabled(True)
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
        self.close_button.setEnabled(True)
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
        if self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(
                self,
                "Processing in progress",
                "Wait for image processing to finish before closing this window.",
            )
            event.ignore()
            return
        event.accept()
