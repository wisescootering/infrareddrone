# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 3
#   compute time_shift alignment
#   20/10/2026   V003
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

# ----------------------------------------------------
#     Resource paths
# ----------------------------------------------------
RESOURCE_ICON_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "Icon"
)

IMAGE_ARUCO_VIS_PATH = RESOURCE_ICON_DIR / "Image_ArUco_VIS.jpg"
IMAGE_ARUCO_NIR_PATH = RESOURCE_ICON_DIR / "Image_ArUco_NIR.jpg"

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
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import (
    Qt,
    QThreadPool,
    QObject,
    pyqtSignal,
    QThreadPool,
    QTimer,
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
    QDoubleSpinBox,
)


# ----------------------------------------------------
#     bib matplotlib
# ----------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # backend non interactif. Fondamental ici avec PyQt
import matplotlib.pyplot as plt

# ----------------------------------------------------
#     bib IRD_Interactive
# ----------------------------------------------------
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import safe_path
import IRD_Interactive_ArUco as Aru
from IRD_Interactive_workers import ArucoWorker
from IRD_Interactive_workers import TimeShiftWorker
from IRD_Interactive_workers import ImagePairingWorker
from IRD_Interactive_color_style import Style
from config import RAWTHERAPEEPATH, EXIFTOOLPATH
assert Path(EXIFTOOLPATH).exists(), f"ExifTool not found at {EXIFTOOLPATH}, Use environment variable EXIFTOOLPATH to set the path."
assert Path(RAWTHERAPEEPATH).exists(), f"RawTherapee not found at {RAWTHERAPEEPATH}, Use environment variable RAWTHERAPEEPATH to set the path."


class DialogSynchroAruco(QDialog):
    """
    Dialog for VIS / NIR timeline synchronization and pairing using ArUco-based angle estimation.

    Phase 3 of the processing pipeline:
      - 3.1 ArUco detection and angle extraction
      - 3.2 Time shift estimation between VIS and NIR timelines
      - 3.3 Pairing VIS and NIR images
    """

    data_signal_to_main = pyqtSignal(bool)

    def __init__(self, mission_parameters: dict, parent=None, multi_thread=True, use_aruco_cache=False):
        super().__init__(parent)

        self.multi_thread = multi_thread
        self.use_aruco_cache = use_aruco_cache

        self.mission_parameters = mission_parameters
        self.folderMissionPath = (mission_parameters.get("folderMissionPath") or mission_parameters.get("File path mission"))
        if self.folderMissionPath is None:
            QMessageBox.critical(
                self,
                "Missing mission folder",
                "The mission folder is not defined.\n"
                "Please run Phase 1 or Phase 2 first, or select a mission folder."
            )
            self.close()
            return

        self.whidth_window = 900
        self.height_window = 900
        self.setWindowTitle("Phase 3 – VIS / NIR time synchronization")
        self.setMinimumSize(900, 600)  # Minimum window size
        self.resize(self.height_window, self.whidth_window, )  # Initial window size

        self._init_gui()
        self._connect_signals()

        self.aruco_orchestrator = None
        self.aruco_results_vis = None
        self.x_vis = None
        self.y_vis = None
        self.aruco_results_nir = None
        self.x_nir = None
        self.y_nir = None

        self._animation_timer = None
        self._animation_index = 0
        self._animation_images = None

        self.image_pairing_worker = None


        self._log("Dialog initialized.")

    # ------------------------------------------------------------------
    # Graphical User Interface
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Title at the top
        title = QLabel("<b>Timeline Synchronization</b>")
        main_layout.addWidget(title)

        # Log display area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        self.log_text.setMaximumHeight(200)
        main_layout.addWidget(self.log_text)

        # Buttons: ArUco detection / Time alignment / Image pairing
        btn_layout = QHBoxLayout()

        # Button 1: ArUco detection
        self.btn_run_aruco = QPushButton("Run ArUco detection (VIS + NIR)")
        self.btn_run_aruco.setFixedWidth(280)
        btn_layout.addWidget(self.btn_run_aruco)

        # Button 2: Time alignment
        self.btn_compute_time_shift = QPushButton("Compute time alignment")
        self.btn_compute_time_shift.setFixedWidth(230)
        self.btn_compute_time_shift.setEnabled(False)
        btn_layout.addWidget(self.btn_compute_time_shift)

        # Button 3: Image pairing
        self.btn_image_pairing = QPushButton("Pair VIS / NIR images")
        self.btn_image_pairing.setFixedWidth(210)
        self.btn_image_pairing.setEnabled(False)
        btn_layout.addWidget(self.btn_image_pairing)

        # Keep the buttons aligned to the left
        btn_layout.addStretch()

        # Define the common button style
        button_style = """
            QPushButton {
                background-color: #17365D;
                color: white;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #102840;
                border-radius: 4px;
            }

            QPushButton:hover {
                background-color: #244A73;
            }

            QPushButton:pressed {
                background-color: #0F243E;
            }

            QPushButton:disabled {
                background-color: #B8C2CC;
                color: #666666;
                border: 1px solid #A0AAB4;
            }
        """

        # Apply the common style to the three main buttons
        self.btn_run_aruco.setStyleSheet(button_style)
        self.btn_compute_time_shift.setStyleSheet(button_style)
        self.btn_image_pairing.setStyleSheet(button_style)

        main_layout.addLayout(btn_layout)

        # Progress bar label
        self.progress_label = QLabel("ArUco detection – idle")
        self.progress_label.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(self.progress_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Graphic display area
        self.timeshift_plot_label = QLabel()
        self.timeshift_plot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeshift_plot_label.setMinimumHeight(600)
        self.timeshift_plot_label.setMaximumHeight(620)
        self.timeshift_plot_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )

        # Display the default ArUco image
        pixmap = QPixmap(str(IMAGE_ARUCO_VIS_PATH))

        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.timeshift_plot_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.timeshift_plot_label.setPixmap(scaled_pixmap)
        else:
            self._log(f"Unable to load image: {IMAGE_ARUCO_VIS_PATH}")

        main_layout.addWidget(self.timeshift_plot_label)

        # Close button at the bottom
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(button_style)

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
        """
        Connect the GUI buttons to their corresponding event handlers.

        Each button triggers the appropriate action when clicked.
        The Close button is connected to the dialog closing handler.
        """
        self.btn_run_aruco.clicked.connect(self.on_run_aruco)
        self.btn_compute_time_shift.clicked.connect(self.on_compute_time_shift)
        self.btn_image_pairing.clicked.connect(self.on_image_pairing)
        self.btn_close.clicked.connect(self.on_close)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        """
        Close the dialog and notify the main application.

        A log message is recorded, the data signal is emitted with
        a True value, and the dialog is closed.
        """
        self._log("Dialog closed by user.")
        self.data_signal_to_main.emit(True)
        self.close()

    # ------------------------------------------------------------------
    # ArUco detection
    # ------------------------------------------------------------------

    def on_run_aruco(self) -> None:
        """
        Step 3.1 - Start ArUco detection on VIS and NIR images.

        Initialize the ArucoOrchestrator, connect its signals to the
        dialog's handlers and GUI widgets, reset the progress bar,
        and start VIS processing.

        NIR processing is started by the orchestrator after VIS
        processing has finished.

        If an exception occurs during initialization or startup,
        reset the progress bar and report the error in the log.
        """
        try:
            self.aruco_orchestrator = ArucoOrchestrator(
                Path(self.folderMissionPath) / "AerialPhotography",
                multi_thread=self.multi_thread,
                use_aruco_cache=self.use_aruco_cache
            )

            # Connect orchestrator signals to the dialog handlers
            self.aruco_orchestrator.signals.all_finished.connect(
                self.on_all_aruco_finished
            )
            self.aruco_orchestrator.signals.error.connect(
                self._on_aruco_error
            )
            self.aruco_orchestrator.signals.log.connect(self._log)

            # Determine the number of available physical CPU cores
            max_workers = psutil.cpu_count(logical=False) or 1

            self._log(
                f"Starting ArUco detection (VIS + NIR) "
                f"using {max_workers} threads."
            )

            # Connect progress and processing-stage signals to the GUI
            self.aruco_orchestrator.signals.progress.connect(
                self.progress_bar.setValue
            )

            self.aruco_orchestrator.signals.stage.connect(
                self._on_aruco_stage
            )

            # Reset the progress bar before starting processing
            self.progress_bar.setValue(0)

            # Start VIS processing; NIR follows automatically
            self.aruco_orchestrator.start_VIS()

        except Exception as e:
            # Reset the progress bar and report the startup error
            self.progress_bar.setValue(0)
            self._log(f"Error starting ArUco orchestrator: {e}")

    def on_all_aruco_finished(self) -> None:
        """
        Handle the completion of ArUco detection for both spectral bands.

        Retrieve the detection results and their associated coordinates
        from the orchestrator, update the GUI status and log, reset the
        progress bar, and enable the time alignment button.
        """
        # Retrieve VIS detection results from the orchestrator
        self.aruco_results_vis = self.aruco_orchestrator.VIS_results
        self.x_vis = self.aruco_orchestrator.VIS_x_vals
        self.y_vis = self.aruco_orchestrator.VIS_y_vals

        # Retrieve NIR detection results from the orchestrator

        self.aruco_results_nir = self.aruco_orchestrator.NIR_results
        self.x_nir = self.aruco_orchestrator.NIR_x_vals
        self.y_nir = self.aruco_orchestrator.NIR_y_vals

        # Update the GUI status and log the number of detected results
        self.progress_label.setText(
            "ArUco detection completed successfully for VIS and NIR."
        )
        self._log(
            f"ArUco detection completed for VIS "
            f"({len(self.aruco_results_vis)}) and NIR "
            f"({len(self.aruco_results_nir)})."
        )

        # Reset the progress bar
        self.progress_bar.setValue(0)

        # Enable time alignment now that both detection stages are complete
        self.btn_compute_time_shift.setEnabled(True)

    def _on_aruco_stage(self, stage: str) -> None:
        """
        Update the GUI when the active ArUco processing stage changes.

        Args:
            stage: Description of the current processing stage.
        """
        self.progress_bar.setValue(0)
        self.progress_label.setText(stage)

        # Display the NIR ArUco image when NIR processing starts.
        if "NIR" in stage:
            pixmap = QPixmap(str(IMAGE_ARUCO_NIR_PATH))

            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.timeshift_plot_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.timeshift_plot_label.setPixmap(scaled_pixmap)
            else:
                self._log(
                    f"Unable to load image: {IMAGE_ARUCO_NIR_PATH}"
                )

    def _on_aruco_error(self, error_msg: str) -> None:
        """
        Handle an error reported during ArUco processing.

        Reset the progress bar, write the error to the log, and display
        a critical message dialog to inform the user.

        Args:
            error_msg: Description of the error reported by the worker.
        """
        self.progress_bar.setValue(0)
        self._log(f"Error during ArUco detection: {error_msg}")

        QMessageBox.critical(
            self,
            "ArUco Detection Error",
            f"An error occurred during ArUco detection:\n{error_msg}"
        )

    # ------------------------------------------------------------------
    # Time alignment
    # ------------------------------------------------------------------

    def on_compute_time_shift(self) -> None:
        """
        Step 3.2 - Start time alignment between the VIS and NIR timelines.

        Create a TimeShiftWorker using the ArUco detection results and
        their associated coordinates. Connect the worker signals to
        the corresponding handlers and submit the worker to the global
        Qt thread pool.

        If an exception occurs while creating or starting the worker,
        report the error in the log.
        """
        self.progress_bar.setValue(3)

        try:
            worker = TimeShiftWorker(
                vis_results=self.aruco_results_vis,
                vis_x=self.x_vis,
                vis_y=self.y_vis,
                nir_results=self.aruco_results_nir,
                nir_x=self.x_nir,
                nir_y=self.y_nir
            )

            # Connect worker signals to the corresponding handlers
            worker.signals.finished.connect(self._on_timeshift_finished)
            worker.signals.error.connect(self._on_aruco_error)

            # Submit the worker to the global Qt thread pool
            QThreadPool.globalInstance().start(worker)

        except Exception as e:
            self._log(f"Error starting time alignment worker: {e}")

        # Set the progress bar to its initial intermediate value
        self.progress_bar.setValue(20)

    def _on_timeshift_finished(
            self,
            time_shift: float,
            time_line_VIS: List[float],
            angles_VIS: List[float],
            time_line_NIR: List[float],
            angles_NIR: List[float],
            msg_abstract: str,
            angle_abs_for_shift_time: bool,
            angle_img_for_shift_time: bool
    ) -> None:
        """
        Finalize time-shift computation between VIS and NIR image sequences.

        This method handles three cases:
        1) Time shift successfully computed using absolute angles.
        2) Time shift computed using relative (image-based) angles.
        3) Time shift could not be computed and must be entered manually by the operator.

        It optionally generates diagnostic plots (before/after alignment),
        displays them in the GUI, and stores the resulting synchronization state.

        Parameters
        ----------
        time_shift : float
            Computed (or proposed) time shift in seconds.
        time_line_VIS : list of float
            Relative timeline for VIS images.
        angles_VIS : list of float
            Angle values for VIS images.
        time_line_NIR : list of float
            Relative timeline for NIR images.
        angles_NIR : list of float
            Angle values for NIR images.
        msg_abstract : str
            Summary message produced by the time-shift computation stage.
        angle_abs_for_shift_time : bool
            True if the time shift was computed using absolute angles.
        angle_img_for_shift_time : bool
            True if the time shift was computed using image-based angles.
        """

        # ------------------------------------------------------------------
        # Logging of computation outcome
        # ------------------------------------------------------------------
        if angle_abs_for_shift_time:
            self._log(f"Time shift computed successfully with absolute angles: {time_shift} s")
        elif angle_img_for_shift_time:
            self._log(f"Time shift computed successfully with relative angles: {time_shift} s")
        else:
            self._log(f"Time shift not computed. Use an operator value: {time_shift} s")
        self._log(msg_abstract)

        # ------------------------------------------------------------------
        # Manual input if automatic computation failed
        # ------------------------------------------------------------------
        if not (angle_abs_for_shift_time or angle_img_for_shift_time):

            dialog = TimeShiftInputDialog(self, default_value=0.0)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                time_shift = dialog.value()
                self._log(f"Manual time shift entered by operator: {time_shift} s")
                final_message = f"Manual time shift entered by operator: {time_shift} s"
            else:
                time_shift = 0.0
                self._log("Manual time shift cancelled. Using default value: 0.0 s")
                final_message = "Manual time shift cancelled. Using default value: 0.0 s"
        else:
            final_message = "Time shift successfully computed."

            # ------------------------------------------------------------------
            # 1) Save diagnostic plots (before / after alignment)
            # ------------------------------------------------------------------
            self.progress_bar.setValue(30)
            output_dir = safe_path(Path(self.folderMissionPath) / "Synchro")

            # Compute common x-limits (robust to empty timelines)
            xlim = self.compute_x_limits(
                time_line_VIS,
                time_line_NIR,
                time_shift=time_shift
            )

            # Before alignment
            plot_before = self.save_timeshift_plot(
                output_dir=output_dir,
                time_line_VIS=time_line_VIS,
                angles_VIS=angles_VIS,
                time_line_NIR=time_line_NIR,
                angles_NIR=angles_NIR,
                time_shift=time_shift,
                filename="check_time_before_alignment.png",
                xlim=xlim,
            )

            # After alignment
            time_NIR_shifted = [t + time_shift for t in time_line_NIR]

            plot_after = self.save_timeshift_plot(
                output_dir=output_dir,
                time_line_VIS=time_line_VIS,
                angles_VIS=angles_VIS,
                time_line_NIR=time_NIR_shifted,
                angles_NIR=angles_NIR,
                time_shift=time_shift,
                filename="check_time_alignment.png",
                xlim=xlim,
            )

            # ------------------------------------------------------------------
            # 2) Load and animate plots in the GUI
            # ------------------------------------------------------------------
            self.progress_bar.setValue(50)
            try:
                self.animate_timeshift_plot(
                    plot_before=plot_before,
                    plot_after=plot_after
                )
            except Exception as e:
                print(f"Error in animate_timeshift_plot: {e}")

        # ------------------------------------------------------------------
        # 3) Store internal synchronization state
        # ------------------------------------------------------------------
        self.progress_bar.setValue(70)
        self.time_shift = time_shift
        self.time_line_VIS = time_line_VIS
        self.angles_VIS = angles_VIS
        self.time_line_NIR = time_line_NIR
        self.angles_NIR = angles_NIR

        # ------------------------------------------------------------------
        # 4) Final UI update
        # ------------------------------------------------------------------
        self.progress_bar.setValue(100)
        self.progress_label.setText(final_message)
        self.btn_image_pairing.setEnabled(True)

    # ------------------------------------------------------------------
    # Image pairing
    # ------------------------------------------------------------------

    def on_image_pairing(self) -> None:
        """
        Phase 3.3 - Start VIS/NIR image pairing using the computed time shift.

        Stop any running time-shift plot animation, update the GUI status,
        create an ImagePairingWorker, connect its signals, and submit it
        to the global Qt thread pool.

        The worker performs the image pairing and reports its progress,
        completion status, or any processing error through its signals.
        """
        # Stop the phase 3.2 animation if it is still running
        self.stop_timeshift_animation()
        self.timeshift_plot_label.setText("Image pairing in progress...")

        self.progress_label.setText("Image pairing - initializing")
        self.progress_bar.setValue(0)

        # Create the image pairing worker
        self.image_pairing_worker = ImagePairingWorker(
            time_shift=self.time_shift,
            folderMissionPath=self.folderMissionPath
        )

        # Connect worker signals to the GUI handlers
        self.image_pairing_worker.signals.progress.connect(
            self.progress_bar.setValue
        )
        self.image_pairing_worker.signals.stage.connect(
            self.progress_label.setText
        )
        self.image_pairing_worker.signals.finished.connect(
            self._on_image_pairing_finished
        )
        self.image_pairing_worker.signals.error.connect(
            self._on_image_pairing_error
        )

        # Start the worker in the global Qt thread pool
        QThreadPool.globalInstance().start(self.image_pairing_worker)

    def _on_image_pairing_finished(self, pairing_result: dict) -> None:
        """
        Handle successful completion of VIS/NIR image pairing.

        Log the number of pairs reported by the worker, update the
        GUI status, and set the progress bar to 100 percent.

        Args:
            pairing_result: Dictionary containing the pairing results.
                The 'shoot_points' entry is used to determine the
                number of image pairs.
        """
        self._log(
            f"Image pairing completed "
            f"({len(pairing_result.get('shoot_points', []))} pairs)."
        )
        self.timeshift_plot_label.setText("Image pairing completed.")
        self.progress_label.setText("Image pairing completed.")
        self.progress_bar.setValue(100)

    def _on_image_pairing_error(self, message: str) -> None:
        """
        Handle an error reported during image pairing.

        Write the error message to the log and display a critical
        message dialog to inform the user.

        Args:
            message: Description of the image pairing error.
        """
        self._log(f"Image pairing error: {message}")

        QMessageBox.critical(
            self,
            "Image Pairing Error",
            message
        )

    # ------------------------------------------------------------------
    # GUI utilities
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        """
        Rescale the currently displayed plot when the dialog is resized.

        Preserve the original image aspect ratio and use smooth
        transformation to maintain display quality.

        Args:
            event: Qt resize event describing the window resize.
        """
        super().resizeEvent(event)

        if self.timeshift_plot_label.pixmap():
            scaled = self.timeshift_plot_label.pixmap().scaled(
                self.timeshift_plot_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.timeshift_plot_label.setPixmap(scaled)

    def animate_timeshift_plot(
        self,
        plot_before: Path,
        plot_after: Path,
        delay_ms: int = 1500
    ) -> None:
        """
        Alternate between two time-shift plot images at a fixed interval.

        Load both images, display the first one immediately, and start
        a QTimer that periodically switches the displayed image.

        If either image cannot be loaded, log an error and do not start
        the animation.

        Args:
            plot_before: Path to the first time-shift plot image.
            plot_after: Path to the second time-shift plot image.
            delay_ms: Delay between image changes, in milliseconds.
                Defaults to 1500 ms.
        """
        self._animation_images = [
            QPixmap(str(plot_before)),
            QPixmap(str(plot_after))
        ]
        self._animation_index = 0

        if any(pix.isNull() for pix in self._animation_images):
            self._log(
                "Failed to load one of the time-shift plot images "
                "for animation."
            )
            return

        # Display the first image
        self.timeshift_plot_label.setPixmap(
            self._animation_images[self._animation_index].scaled(
                self.timeshift_plot_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )

        # Create a timer to alternate between the images
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation_frame)
        self._animation_timer.start(delay_ms)

    def _update_animation_frame(self) -> None:
        """
        Display the next image in the time-shift plot animation.

        Cycle through the loaded images and scale the selected image
        to fit the current plot display area while preserving its
        aspect ratio.
        """
        self._animation_index = (
            self._animation_index + 1
        ) % len(self._animation_images)

        pixmap = self._animation_images[self._animation_index].scaled(
            self.timeshift_plot_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.timeshift_plot_label.setPixmap(pixmap)

    def stop_timeshift_animation(self) -> None:
        """
        Stop the time-shift plot animation if its timer is active.

        Stop the timer and schedule it for deletion to release the
        associated Qt resources.
        """
        if (
            hasattr(self, "_animation_timer")
            and self._animation_timer is not None
        ):
            if self._animation_timer.isActive():
                self._animation_timer.stop()
                self._animation_timer.deleteLater()
                self._animation_timer = None

    def compute_x_limits(
        self,
        time_line_VIS,
        time_line_NIR,
        time_shift: float = 0.0,
        padding_ratio: float = 0.05
    ) -> tuple:
        """
        Compute robust horizontal axis limits for a time-alignment plot.

        Include all VIS timestamps, the original NIR timestamps, and
        the NIR timestamps after applying the time shift. Add a margin
        on both sides to avoid placing data points directly against
        the plot boundaries.

        Args:
            time_line_VIS: Sequence of VIS timestamps, in seconds.
            time_line_NIR: Sequence of NIR timestamps, in seconds.
            time_shift: Time offset applied to the NIR timestamps,
                in seconds. Defaults to 0.0.
            padding_ratio: Fraction of the total time span to add
                as a margin on each side. Defaults to 0.05.

        Returns:
            A tuple (xmin, xmax) defining the horizontal axis limits.
            Returns (0.0, 1.0) if both input timelines are empty.
        """
        if not (time_line_VIS or time_line_NIR):
            return 0.0, 1.0  # Fallback when both timelines are empty

        # Include the original and shifted NIR timestamps
        all_times = (
            list(time_line_VIS)
            + list(time_line_NIR)
            + [t + time_shift for t in time_line_NIR]
        )

        t_min = min(all_times)
        t_max = max(all_times)

        amplitude = t_max - t_min
        padding = amplitude * padding_ratio

        return t_min - padding, t_max + padding

    def save_timeshift_plot(
        self,
        output_dir: Path,
        time_line_VIS,
        angles_VIS,
        time_line_NIR,
        angles_NIR,
        time_shift: float,
        filename: str = "check_time_alignment.png",
        xlim=None,
        ylim=None
    ):
        """
        Generate and save a plot comparing VIS and NIR angular timelines.

        Plot both spectral bands against time, optionally apply
        predefined axis limits, and include a title showing the
        estimated time shift. Save the figure to the specified output
        directory and return the resulting file path.

        If plot generation fails, log the error, display a critical
        message dialog, and return None.

        Args:
            output_dir: Directory where the plot will be saved.
            time_line_VIS: VIS timestamps, in seconds.
            angles_VIS: Angular measurements associated with VIS.
            time_line_NIR: NIR timestamps, in seconds.
            angles_NIR: Angular measurements associated with NIR.
            time_shift: Estimated time shift between VIS and NIR,
                in seconds.
            filename: Output image filename.
            xlim: Optional tuple defining the horizontal axis limits.
            ylim: Optional tuple defining the vertical axis limits.

        Returns:
            Path to the saved plot, or None if generation fails.
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / filename

            fig, ax = plt.subplots(figsize=(10, 7))

            # Plot the VIS timeline
            ax.plot(
                time_line_VIS,
                angles_VIS,
                label="VIS",
                color="g",
                lw=1.2,
                marker="o",
                markersize=5,
                markeredgewidth=0.5,
                markeredgecolor="black",
            )

            # Plot the NIR timeline
            ax.plot(
                time_line_NIR,
                angles_NIR,
                label="NIR",
                color="r",
                lw=1.2,
                marker="o",
                markersize=5,
                markeredgewidth=0.5,
                markeredgecolor="black",
            )

            # Apply optional axis limits
            if xlim:
                ax.set_xlim(xlim)

            if ylim:
                ax.set_ylim(ylim)

            # Configure plot labels, title, legend, and grid
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Angle (deg)")
            ax.set_title(
                f"Time shift VIS / NIR = {time_shift:.3f} s"
            )
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Adjust the layout and save the figure
            fig.tight_layout()
            fig.savefig(out_path, dpi=150)
            plt.close(fig)

            return out_path

        except Exception as e:
            self._log(f"Error during time-shift plot generation: {e}")

            QMessageBox.critical(
                self,
                "Time-Shift Plot Error",
                f"An error occurred while generating the time-alignment plot:\n{e}"
            )

            return None

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        """
        Append a message to the dialog's log display.

        Args:
            message: Text message to display in the log area.
        """
        self.log_text.append(message)


class ArucoOrchestrator:
    """
    Coordinate VIS and NIR ArUco detection workers and store their results.

    The VIS worker is started first. When it finishes, the NIR worker
    is started. Once both processing stages have completed, the
    all_finished signal is emitted.

    Attributes:
        folderMissionPath (str): Path to the mission folder.
        multi_thread (bool): Whether multithreaded processing is enabled.
        use_aruco_cache (bool): Whether cached ArUco detections are reused.
        VIS_results (list): Results returned by the VIS worker.
        VIS_x_vals (list): X coordinates returned by the VIS worker.
        VIS_y_vals (list): Y coordinates returned by the VIS worker.
        NIR_results (list): Results returned by the NIR worker.
        NIR_x_vals (list): X coordinates returned by the NIR worker.
        NIR_y_vals (list): Y coordinates returned by the NIR worker.
        signals (ArucoOrchestratorSignals): Signals exposed by the
            orchestrator to report errors, logs, progress, stages,
            and completion.
        thread_pool (QThreadPool): Global Qt thread pool.
    """

    def __init__(
        self,
        folderMissionPath: str,
        multi_thread: bool = False,
        use_aruco_cache: bool = False
    ) -> None:
        """
        Initialize the orchestrator and its result containers.

        Args:
            folderMissionPath: Path to the mission folder.
            multi_thread: Enable multithreaded processing if True.
            use_aruco_cache: Reuse cached ArUco detections if True.
        """
        self.folderMissionPath = folderMissionPath
        self.multi_thread = multi_thread
        self.use_aruco_cache = use_aruco_cache

        # Store VIS processing results
        self.VIS_results = []
        self.VIS_x_vals = []
        self.VIS_y_vals = []

        # Store NIR processing results
        self.NIR_results = []
        self.NIR_x_vals = []
        self.NIR_y_vals = []

        self.signals = ArucoOrchestratorSignals()

        # Track the completion status of each worker
        self._vis_done = False
        self._nir_done = False

        # Use the global Qt thread pool
        self.thread_pool = QThreadPool.globalInstance()

    def start_VIS(self) -> None:
        """
        Start the VIS ArUco detection worker.
        """
        self._start_worker(
            name_folder="VIS",
            spectral_band="VIS",
            finished_callback=self._on_vis_finished,
        )

    def start_NIR(self) -> None:
        """
        Start the NIR ArUco detection worker.
        """
        self._start_worker(
            name_folder="NIR",
            spectral_band="NIR",
            finished_callback=self._on_nir_finished,
        )

    def _start_worker(
        self,
        name_folder: str,
        spectral_band: str,
        finished_callback
    ) -> None:
        """
        Create, configure, and start an ArUco detection worker.

        Connect the worker signals to the orchestrator signals and
        to the appropriate completion callback.

        Args:
            name_folder: Name of the image subfolder ("VIS" or "NIR").
            spectral_band: Spectral band processed by the worker.
            finished_callback: Callback invoked when the worker finishes.
        """
        worker = ArucoWorker(
            folderMissionPath=self.folderMissionPath,
            name_folder=name_folder,
            spectral_band=spectral_band,
            suffix_image="dng",
            save_check_detection_img=True,
            verbose=True,
            use_aruco_cache=self.use_aruco_cache,
            multi_thread=self.multi_thread
        )

        worker.signals.finished.connect(finished_callback)
        worker.signals.error.connect(self.signals.error.emit)

        # Relay log messages from the worker to the orchestrator
        worker.signals.log.connect(self.signals.log.emit)

        # Relay progress updates and processing stages
        worker.signals.progress.connect(self.signals.progress.emit)
        worker.signals.stage.connect(self.signals.stage.emit)

        # Start the worker in the global thread pool
        self.thread_pool.start(worker)

    def _on_vis_finished(
        self,
        results: list,
        x_vals: list,
        y_vals: list
    ) -> None:
        """
        Store the VIS results and start NIR processing.

        Args:
            results: Results returned by the VIS worker.
            x_vals: X coordinates returned by the VIS worker.
            y_vals: Y coordinates returned by the VIS worker.
        """
        self.VIS_results = results
        self.VIS_x_vals = x_vals
        self.VIS_y_vals = y_vals
        self._vis_done = True

        # Start NIR processing after VIS processing has finished
        self.start_NIR()

    def _on_nir_finished(
        self,
        results: list,
        x_vals: list,
        y_vals: list
    ) -> None:
        """
        Store the NIR results and notify listeners that processing is complete.

        Args:
            results: Results returned by the NIR worker.
            x_vals: X coordinates returned by the NIR worker.
            y_vals: Y coordinates returned by the NIR worker.
        """
        self.NIR_results = results
        self.NIR_x_vals = x_vals
        self.NIR_y_vals = y_vals
        self._nir_done = True

        # Notify listeners that both processing stages are complete
        self.signals.all_finished.emit()

class ArucoOrchestratorSignals(QObject):
    """
    Define the Qt signals used by ArucoOrchestrator to communicate
    processing events and results to the rest of the application.

    This class acts as a communication interface between the
    ArucoOrchestrator and its listeners, typically the interactive
    PyQt6 GUI.

    The orchestrator coordinates ArUco detection for the VIS and NIR
    spectral bands. The actual image processing is performed by
    ArucoWorker instances running in a QThreadPool.

    Because workers may execute outside the GUI thread, they must not
    directly update GUI widgets. Instead, their signals are connected
    to the orchestrator, which relays relevant events through the
    signals defined here. Qt then delivers connected signal handlers
    according to its signal/slot connection rules.

    Signals:
        progress (int):
            Reports processing progress as an integer, typically
            representing a percentage from 0 to 100.

        stage (str):
            Identifies the spectral band currently being processed.
            Expected values are "VIS" or "NIR".

        all_finished ():
            Emitted when the orchestrator has received the NIR worker's
            completion callback, after the VIS processing stage has
            already completed.

        error (str):
            Reports an error message produced by a worker.

        log (str):
            Transmits a log message from a worker to the orchestrator's
            listeners, allowing the GUI to display processing messages.

    Usage:
        The orchestrator creates an instance of this class:

            self.signals = ArucoOrchestratorSignals()

        Other parts of the application can then connect slots to these
        signals. For example:

            self.orchestrator.signals.progress.connect(
                self.update_progress
            )

            self.orchestrator.signals.log.connect(
                self.append_log
            )

            self.orchestrator.signals.all_finished.connect(
                self.on_processing_finished
            )

        This separates processing logic from GUI presentation and
        allows the interface to react to worker events without directly
        controlling the worker threads.
    """

    # Processing progress, typically expressed as a percentage
    progress = pyqtSignal(int)
    # Name of the current processing stage: "VIS" or "NIR"
    stage = pyqtSignal(str)
    # Emitted when the complete VIS/NIR processing sequence has finished
    all_finished = pyqtSignal()
    # Error message reported by a worker
    error = pyqtSignal(str)
    # Log message forwarded by a worker
    log = pyqtSignal(str)

class TimeShiftInputDialog(QDialog):
    """
    Modal dialog allowing the operator to manually enter a time shift value.

    The dialog returns a floating-point value expressed in seconds.
    """

    def __init__(self, parent=None, default_value: float = 0.0):
        super().__init__(parent)

        self.setWindowTitle("Manual Time Shift")
        self.setModal(True)

        # ------------------------------------------------------------
        # Widgets
        # ------------------------------------------------------------
        label = QLabel(
            "Automatic VIS/NIR time alignment failed.\n\n"
            "Please enter a manual time shift value (in seconds):"
        )
        label.setWordWrap(True)

        self.spinbox = QDoubleSpinBox(self)
        self.spinbox.setDecimals(3)
        self.spinbox.setRange(-600.0, 600.0)
        self.spinbox.setSingleStep(0.1)
        self.spinbox.setValue(default_value)
        self.spinbox.setSuffix(" s")
        self.spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)

        btn_ok = QPushButton("OK", self)
        btn_cancel = QPushButton("Cancel", self)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        # ------------------------------------------------------------
        # Layouts (CRITICAL for Qt stability)
        # ------------------------------------------------------------
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(btn_ok)
        button_layout.addWidget(btn_cancel)

        main_layout = QVBoxLayout()
        main_layout.addWidget(label)
        main_layout.addWidget(self.spinbox)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def value(self) -> float:
        """
        Return the manually entered time shift value (in seconds).
        """
        return float(self.spinbox.value())




