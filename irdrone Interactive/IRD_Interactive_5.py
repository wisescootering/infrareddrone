# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 5
#   Georeferencing images.  User interface
#   17/10/2026   V004
# ---------------------------------------------------------------------------------

import os
import os.path as osp
from pathlib import Path
import numpy as np
import cv2
import matplotlib.pyplot as plt
import time
import json
from json import JSONDecodeError
from typing import List, Tuple, Optional, Sequence, Dict, Any, Union
import copy
import rawpy
import imageio

# ----------------------------------------------------
#     bib Multi Thread
# ----------------------------------------------------

import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil


# ----------------------------------------------------
#     bib PyQt 6
# ----------------------------------------------------
from PyQt6.QtGui import (
    QPixmap,
    QImage
)
from PyQt6.QtCore import (
    Qt,
    QThreadPool,
    QObject,
    QRunnable,
    pyqtSignal,
)


from PyQt6.QtWidgets import (
    QMessageBox,
    QApplication,
    QWidget,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
    QDoubleSpinBox
)

# ----------------------------------------------------
#     bib matplotlib
# ----------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend. Essential here when using PyQt.
import matplotlib.pyplot as plt

# ----------------------------------------------------
#     bib IRD_Interactive
# ----------------------------------------------------
import IRD_Interactive_utils as Uti
import IRD_Interactive_GeoRef as GeoRef
from IRD_Interactive_utils import safe_path
from IRD_Interactive_workers import TimeShiftWorker
from IRD_Interactive_workers import ImagePairingWorker
from IRD_Interactive_color_style import Style
from IRD_Interactive_styles import BUTTON_STYLE
from IRD_Interactive_ODM import (
    DockerUnavailableError,
    ODMMappingError,
    read_orthophoto_preview,
    run_odm,
)
from config import RAWTHERAPEEPATH, EXIFTOOLPATH
assert Path(EXIFTOOLPATH).exists(), f"ExifTool not found at {EXIFTOOLPATH}, Use environment variable EXIFTOOLPATH to set the path."
assert Path(RAWTHERAPEEPATH).exists(), f"RawTherapee not found at {RAWTHERAPEEPATH}, Use environment variable RAWTHERAPEEPATH to set the path."


class ODMRunSignals(QObject):
    """Signals emitted while ODM runs outside the GUI thread."""

    log = pyqtSignal(str)
    stage = pyqtSignal(str)
    finished = pyqtSignal(dict)
    docker_unavailable = pyqtSignal(str)
    error = pyqtSignal(str)


class ODMRunWorker(QRunnable):
    """Run the complete ODM workflow without blocking the Phase 5 dialog."""

    def __init__(self, mission_folder: Path):
        super().__init__()
        self.mission_folder = mission_folder
        self.signals = ODMRunSignals()

    def run(self) -> None:
        try:
            result = run_odm(
                self.mission_folder,
                log_callback=self.signals.log.emit,
                stage_callback=self.signals.stage.emit,
            )
        except DockerUnavailableError as error:
            self.signals.docker_unavailable.emit(str(error))
        except (ODMMappingError, OSError, ValueError, TypeError) as error:
            self.signals.error.emit(f"{type(error).__name__}: {error}")
        except Exception as error:
            import traceback

            self.signals.error.emit(
                f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
            )
        else:
            self.signals.finished.emit(result)


class ODMPreviewSignals(QObject):
    ready = pyqtSignal(object)
    error = pyqtSignal(str)


class ODMPreviewWorker(QRunnable):
    """Read a reduced RGB preview of an orthophoto off the GUI thread."""

    def __init__(self, orthophoto_path: Path):
        super().__init__()
        self.orthophoto_path = orthophoto_path
        self.signals = ODMPreviewSignals()

    def run(self) -> None:
        try:
            preview = read_orthophoto_preview(self.orthophoto_path)
        except Exception as error:
            self.signals.error.emit(f"{type(error).__name__}: {error}")
        else:
            self.signals.ready.emit(preview)


class DialogGeoRef(QDialog):
    """
    Dialog for georeferncing image.

    Phase 5 of the processing pipeline:
          - Post-processing
    """

    data_signal_to_main = pyqtSignal(bool)
    log_signal = pyqtSignal(str)
    image_signal = pyqtSignal(str)

    def __init__(self, mission_parameters: dict, parent=None, multi_thread=False):
        super().__init__(parent)

        self.multi_thread = multi_thread

        self.mission_parameters = mission_parameters
        self.folderMissionPath = (mission_parameters.get("folderMissionPath") or mission_parameters.get("File path mission"))
        if self.folderMissionPath is None:
            QMessageBox.critical(
                self,
                "Missing mission folder",
                "The mission folder is not defined.\n"
                "Please run step 1 or step 2 first, or select a mission folder."
            )
            self.close()
            return
        self.whidth_window = 900
        self.height_window = 900
        self.setWindowTitle("Step 5 – Georeferencing")
        self.setMinimumSize(900, 600)  # Minimum window size
        self.resize(self.height_window, self.whidth_window,)  # Initial window size

        self._init_gui()
        self._connect_signals()
        self.odm_worker: Optional[ODMRunWorker] = None
        self.odm_preview_worker: Optional[ODMPreviewWorker] = None

        # Connect the logger signal to the GUI log window.
        self.log_signal.connect(self._log)

        # Connect the image signal to the image display method.
        self.image_signal.connect(self._display_image)

        # Forward GeoRef logger messages to this dialog.
        GeoRef.logger.log_callback = self.log_signal.emit

        self._log("Dialog initialized.")

    # ------------------------------------------------------------------
    # User Interface
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Title at the top
        title = QLabel("<b>Georeferencing</b>")
        main_layout.addWidget(title)

        # Log display area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        self.log_text.setMaximumHeight(200)
        main_layout.addWidget(self.log_text)

        # GeoRef and ODM preparation buttons
        btn_layout = QHBoxLayout()
        self.btn_run_GeoRef = QPushButton("Run Geo ref")
        # Button width: approximately one third of the window
        self.btn_run_GeoRef.setFixedWidth(int(self.whidth_window/3))
        # Apply the common style to the three main buttons
        self.btn_run_GeoRef.setStyleSheet(BUTTON_STYLE)
        btn_layout.addWidget(self.btn_run_GeoRef)
        self.btn_run_Mapping = QPushButton("Run Mapping")
        self.btn_run_Mapping.setFixedWidth(180)
        self.btn_run_Mapping.setStyleSheet(BUTTON_STYLE)
        btn_layout.addWidget(self.btn_run_Mapping)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # Progress bar label (bold)
        self.progress_label = QLabel("Geo Ref ")
        self.progress_label.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(self.progress_label)

        # Progress bar above the Close button
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Image preview zone
        self.image_preview_label = QLabel("No image selected")
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumHeight(250)
        self.image_preview_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )
        main_layout.addWidget(self.image_preview_label, stretch=1)

        # Close button at the bottom
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(BUTTON_STYLE)

        # Push the Close button to the bottom
        main_layout.addStretch()

        # Align the Close button to the right
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(self.btn_close)

        main_layout.addLayout(close_layout)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.btn_run_GeoRef.clicked.connect(self.on_run_GeoRef)
        self.btn_run_Mapping.clicked.connect(self.on_run_ODM)
        self.btn_close.clicked.connect(self.on_close)

    # ------------------------------------------------------------------
    # Slots (placeholders)
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        if self.odm_worker is not None:
            QMessageBox.warning(
                self,
                "ODM is running",
                "Wait for the ODM process to finish before closing this window.",
            )
            return
        self._log("Dialog closed by user.")
        self.data_signal_to_main.emit(True)
        self.close()

    # ------------------------------------------------------------------
    #  Display image for geo ref in image preview zone
    # ------------------------------------------------------------------


    def _display_image(self, image_path: str) -> None:
        """Display an image preview while preserving its aspect ratio."""

        pixmap = QPixmap()

        if image_path.lower().endswith(".dng"):
            # Extract the embedded JPEG thumbnail from the DNG.
            with rawpy.imread(image_path) as raw:
                try:
                    thumb = raw.extract_thumb()

                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        pixmap.loadFromData(thumb.data)
                    else:
                        # Fallback if the embedded thumbnail is not JPEG.
                        rgb = raw.postprocess()
                        image_bytes = imageio.imsave(
                            imageio.RETURN_BYTES, rgb, format="png"
                        )
                        pixmap.loadFromData(image_bytes, "PNG")

                except Exception as exc:
                    self._log(
                        f"Thumbnail extraction failed: {exc}. "
                        "Using full-resolution processing."
                    )

                    # Fallback if thumbnail extraction fails.
                    rgb = raw.postprocess()
                    image_bytes = imageio.imsave(
                        imageio.RETURN_BYTES, rgb, format="png"
                    )
                    pixmap.loadFromData(image_bytes, "PNG")

        else:
            # Load TIFF and other supported formats directly.
            pixmap.load(image_path)

        if pixmap.isNull():
            self._log(f"Unable to load image for preview: {image_path}")
            return

        # Scale the preview to fit the label.
        scaled_pixmap = pixmap.scaled(
            self.image_preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.image_preview_label.setPixmap(scaled_pixmap)
        self._log(f"Image preview loaded: {image_path}")

    # ------------------------------------------------------------------
    #       Georeferencing
    # ------------------------------------------------------------------

    def on_run_GeoRef(self) -> None:
        """
        Step 5.1 – Run Georeferencing.
        """
        try:
            self.progress_bar.setValue(0)
            QMessageBox.information(
                self,
                "GeoRef",
                "Select one or more images.\n"
                "Warning: all selected images must be of the same type.\n"
                "Supported types:\n"
                "    - DNG (DJI)\n"
                "    - TIFF\n"
                "    - Multispectral TIFF: groups of four images.\n"
                "      Example: HYPERLAPSE_0121_1.tif, HYPERLAPSE_0121_2.tif, "
                "               HYPERLAPSE_0121_3.tif, HYPERLAPSE_0121_4.tif\n"
                "    In the latter case, select all four images."
            )
            GeoRef.georef_main(
                image_callback=self.image_signal.emit,
                mission_parameters=self.mission_parameters)


        except Exception as e:
            self.progress_bar.setValue(0)
            self._log(f"Error starting Geo Ref: {e}")
            import traceback
            traceback.print_exc()

    def on_GeoRef_finished(self):

        self.progress_label.setText("Georeferencing completed successfully.")
        self._log("Georeferencing completed successfully.")
        self.progress_bar.setValue(0)


    def _on_GeoRef_stage(self, stage: str):
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Geo Ref – {stage}")

    def _on_GeoRef_error(self, error_msg):
        self.progress_bar.setValue(0)
        self._log(f"Error during GeoRef: {error_msg}")
        QMessageBox.critical(
            self,
            "Geo Ref detection error",
            f"An error occurred during Geo Ref:\n{error_msg}"
        )

    # --------------------------------------------
    #  Mapping ODM
    # --------------------------------------------

    def on_run_ODM(self) -> None:
        """Prepare the selected images and start ODM in a background worker."""
        if self.odm_worker is not None:
            return

        mission_folder = Path(self.folderMissionPath)
        confirm = QMessageBox.question(
            self,
            "Start ODM mapping",
            "This will hard-link the selected image quartets from "
            "ImgIRdrone/imgMultispectral into mapping_MULTI/images, then run ODM "
            "directly in mapping_MULTI using Docker.\n\n"
            "The orthophoto, report, shots GeoJSON, and 2.5D mesh will also be copied "
            "to mapping_MULTI/mapping_result.\n\n"
            "The processing may take a long time and use several gigabytes of memory "
            "and disk space. Existing ODM output folders or archived mapping results "
            "will not be overwritten; move or remove them manually before starting "
            "another run.\n\n"
            f"Mission:\n{mission_folder}\n\nStart ODM now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._start_ODM_worker(mission_folder)

    def _start_ODM_worker(self, mission_folder: Path) -> None:
        worker = ODMRunWorker(mission_folder)
        worker.signals.log.connect(self._log)
        worker.signals.stage.connect(self._on_ODM_stage)
        worker.signals.finished.connect(self._on_ODM_finished)
        worker.signals.docker_unavailable.connect(self._on_ODM_docker_unavailable)
        worker.signals.error.connect(self._on_ODM_error)
        self.odm_worker = worker
        self.btn_run_GeoRef.setEnabled(False)
        self.btn_run_Mapping.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("ODM – starting")
        self._log("Starting the complete ODM workflow.")
        QThreadPool.globalInstance().start(worker)

    def _on_ODM_docker_unavailable(self, message: str) -> None:
        self._finish_ODM_ui()
        self._log(f"Docker Desktop is unavailable: {message}")
        retry = QMessageBox.question(
            self,
            "Docker Desktop is not running",
            f"{message}\n\n"
            "Please start Docker Desktop and wait until its engine is running. "
            "Then choose Retry to check the engine again, or Cancel to stop here.",
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        if retry == QMessageBox.StandardButton.Retry:
            self._start_ODM_worker(Path(self.folderMissionPath))
        else:
            self.progress_label.setText("ODM cancelled: Docker Desktop is unavailable.")

    def _on_ODM_stage(self, stage: str) -> None:
        self.progress_label.setText(f"ODM – {stage}")

    def _finish_ODM_ui(self) -> None:
        self.odm_worker = None
        self.btn_run_GeoRef.setEnabled(True)
        self.btn_run_Mapping.setEnabled(True)
        self.btn_close.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _on_ODM_finished(self, result: dict) -> None:
        self._finish_ODM_ui()
        orthophoto = result["orthophoto"]
        completion_message = f"Orthophoto:\n{orthophoto['path']}"
        self._log(f"ODM completed successfully: {orthophoto['path']}")
        self.progress_label.setText("ODM completed successfully.")
        self.image_preview_label.setText("Loading orthophoto preview...")
        self.image_preview_label.setPixmap(QPixmap())
        self._start_ODM_preview(Path(orthophoto["path"]))
        QMessageBox.information(
            self,
            "ODM completed",
            completion_message,
        )

    def _start_ODM_preview(self, orthophoto_path: Path) -> None:
        worker = ODMPreviewWorker(orthophoto_path)
        worker.signals.ready.connect(self._on_ODM_preview_ready)
        worker.signals.error.connect(self._on_ODM_preview_error)
        self.odm_preview_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_ODM_preview_ready(self, rgb: np.ndarray) -> None:
        height, width, _channels = rgb.shape
        image = QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        self.image_preview_label.setPixmap(
            pixmap.scaled(
                self.image_preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._log("Orthophoto RGB preview displayed (bands 1-3).")
        self.odm_preview_worker = None

    def _on_ODM_preview_error(self, error_message: str) -> None:
        self.image_preview_label.setText("Orthophoto preview could not be created.")
        self._log(f"Orthophoto preview failed: {error_message}")
        self.odm_preview_worker = None

    def _on_ODM_error(self, error_message: str) -> None:
        self._finish_ODM_ui()
        self._log(f"ODM failed: {error_message}")
        QMessageBox.critical(
            self,
            "ODM error",
            f"The ODM workflow failed:\n\n{error_message}",
        )
        self.progress_label.setText("ODM failed.")

    def closeEvent(self, event) -> None:
        if self.odm_worker is not None:
            QMessageBox.warning(
                self,
                "ODM is running",
                "Wait for the ODM process to finish before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)


    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------


    def _log(self, message: str) -> None:
        """Append a message and refresh the log display."""
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()
        self.log_text.repaint()
