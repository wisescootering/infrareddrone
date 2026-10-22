# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 4
#   Process preprocessed VIS / NIR image pairs.
# ---------------------------------------------------------------------------------

import json
import os
from pathlib import Path
import sys

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from config import SJCONVERTERPATH


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSING_SCRIPT = PROJECT_ROOT / "run_after_preprocessing.py"


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
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.started.connect(self._on_process_started)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)

        self.setWindowTitle("Step 4 – Image processing")
        self.resize(700, 500)
        self._init_gui()

    def _init_gui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Mission:</b> {self.mission_folder}"))
        layout.addWidget(
            QLabel(
                f"{self.pair_count} preprocessed image pairs found. "
                "The end index is exclusive."
            )
        )

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Start index:"))
        self.start_index = QSpinBox()
        self.start_index.setRange(0, self.pair_count)
        self.start_index.setValue(0)
        range_layout.addWidget(self.start_index)

        range_layout.addWidget(QLabel("End index:"))
        self.end_index = QSpinBox()
        self.end_index.setRange(0, self.pair_count)
        self.end_index.setValue(self.pair_count)
        range_layout.addWidget(self.end_index)
        range_layout.addStretch()
        layout.addLayout(range_layout)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.run_button = QPushButton("Run processing")
        self.run_button.clicked.connect(self._start_processing)
        button_layout.addWidget(self.run_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)

    def _start_processing(self) -> None:
        start = self.start_index.value()
        end = self.end_index.value()
        if start >= end:
            QMessageBox.warning(
                self,
                "Invalid image range",
                "The end index must be greater than the start index.",
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
            "--start",
            str(start),
            "--end",
            str(end),
        ]
        self.log_text.append(
            f"Running: {sys.executable} {' '.join(arguments)}"
        )
        self.status_label.setText("Starting processing…")
        self.progress_bar.setRange(0, 0)
        self.run_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.start_index.setEnabled(False)
        self.end_index.setEnabled(False)
        self.process.start(sys.executable, arguments)

    def _read_process_output(self) -> None:
        output = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if output:
            self.log_text.moveCursor(self.log_text.textCursor().MoveOperation.End)
            self.log_text.insertPlainText(output)
            self.log_text.ensureCursorVisible()

    def _on_process_started(self) -> None:
        self.status_label.setText("Processing…")
        self.log_text.append("\nProcessing started.")

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        self._read_process_output()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if exit_code == 0 else 0)
        self.run_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.start_index.setEnabled(True)
        self.end_index.setEnabled(True)

        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
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
        self.start_index.setEnabled(True)
        self.end_index.setEnabled(True)
        self.log_text.append(f"\nUnable to start processing: {self.process.errorString()}")

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
