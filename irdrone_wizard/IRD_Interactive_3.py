# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 3
#   compute time_shift alignment
#   20/10/2026   V003
# ---------------------------------------------------------------------------------

import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import re
from typing import List, Optional, Sequence

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

# Minimum display time of each ArUco check image during detection (ms).
# Short enough for the mobile marker to visibly spin, long enough to keep
# the GUI responsive when images arrive from several threads.
CHECK_IMAGE_HOLD_MS = 200


def _natural_key(name: str) -> list:
    """Sort key comparing the numbers in a file name numerically (IMG_9 < IMG_10)."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", name)]

# ----------------------------------------------------
#     bib Multi Thread
# ----------------------------------------------------

import psutil


# ----------------------------------------------------
#     bib PyQt 6
# ----------------------------------------------------
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import (
    Qt,
    QObject,
    pyqtSignal,
    QThreadPool,
    QTimer,
)
from PyQt6.QtWidgets import (
    QMessageBox,
    QFrame,
    QApplication,
    QSizePolicy,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
    QDoubleSpinBox,
    QSlider,
)


# ----------------------------------------------------
#     bib matplotlib
# ----------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # backend non interactif. Fondamental ici avec PyQt
# Explicit Qt canvas for the interactive adjustment dialog (pyplot stays on Agg).
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

# ----------------------------------------------------
#     bib IRD_Interactive
# ----------------------------------------------------
import IRD_Interactive_help as Help
from IRD_Interactive_progress import mark_step_done
from IRD_Interactive_utils import safe_path
import IRD_Interactive_ArUco as Aru
from IRD_Interactive_workers import ArucoWorker
from IRD_Interactive_workers import TimeShiftWorker
from IRD_Interactive_workers import ImagePairingWorker
import flight_timeline as FT
import IRD_Interactive_look as Look


class DialogSynchroAruco(QDialog):
    """
    Dialog for VIS / NIR timeline synchronization and pairing using ArUco-based angle estimation.

    Phase 3 of the processing pipeline:
      - 3.1 ArUco detection and angle extraction
      - 3.2 Time shift estimation between VIS and NIR timelines
      - 3.3 Pairing VIS and NIR images
    """

    data_signal_to_main = pyqtSignal(bool)
    # Chained run (from Step 2): the pairing is done, go on with Step 4
    continue_requested = pyqtSignal()

    def __init__(self, mission_parameters: dict, parent=None, multi_thread=True, use_aruco_cache=False,
                 auto_run=False):
        super().__init__(parent)
        # Opened from the Step 2 flight timeline: detection and time alignment
        # run by themselves; the user checks the alignment plot, then pairs.
        self.auto_run = auto_run

        self.multi_thread = multi_thread
        self.use_aruco_cache = use_aruco_cache

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

        self.setWindowTitle("Step 3 – VIS / NIR time synchronization")
        self.setStyleSheet(Look.DIALOG_STYLE)
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        if screen is None:
            screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_width = min(900, int(screen_geometry.width() * 0.92))
        window_height = min(760, int(screen_geometry.height() * 0.90))
        self.setMinimumSize(min(600, window_width), min(480, window_height))
        self.setGeometry(
            screen_geometry.x() + (screen_geometry.width() - window_width) // 2,
            screen_geometry.y() + (screen_geometry.height() - window_height) // 2,
            window_width,
            window_height,
        )

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

        # Live display of the check images saved during ArUco detection
        self._pending_check_image = None
        self._last_check_image_key = None
        self._check_image_timer = QTimer(self)
        self._check_image_timer.setSingleShot(True)
        self._check_image_timer.timeout.connect(self._show_pending_check_image)

        self.image_pairing_worker = None
        self.image_pairing_done = False
        self.time_shift = 0.0
        self.computed_time_shift = 0.0
        self.time_line_VIS = []
        self.angles_VIS = []
        self.time_line_NIR = []
        self.angles_NIR = []


        self._awaiting_sync = False      # chained run: alignment plot shown, waiting for the user
        self._plot_after = None

        self._log("Dialog initialized.")
        self._set_manual_mode(not self.auto_run)
        if not self.auto_run:
            self._show_previous_result()
        if self.auto_run:
            self._log("Started from the flight timeline: detection, time alignment and pairing run automatically.")
            QTimer.singleShot(400, self.on_run_aruco)

    # ------------------------------------------------------------------
    # Graphical User Interface
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Title at the top
        title = QLabel("<b>Timeline Synchronization</b>")
        main_layout.addWidget(title)

        # Chained run: the three stages and what comes next, no button to click
        self.stages = Look.StageTracker(["Target detection", "Clock alignment", "Image pairing",
                                         "Image processing"])
        main_layout.addWidget(self.stages.widget())
        auto_bar = QHBoxLayout()
        self.auto_label = QLabel("")
        self.auto_label.setStyleSheet("color: #6B7785;")
        self.auto_label.setWordWrap(True)
        self.btn_manual = QPushButton("Manual mode…")
        self.btn_manual.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_manual.setToolTip("Stop the automatic chaining and run each stage yourself "
                                   "(check or adjust the time alignment before pairing).")
        self.btn_manual.clicked.connect(lambda: self._set_manual_mode(True))
        self.btn_continue = QPushButton("Image processing  ▶")
        self.btn_continue.setStyleSheet(Look.PRIMARY_STYLE)
        self.btn_continue.setToolTip("Close this window and open Step 4 (alignment of the image pairs): "
                                     "it starts when you click Run alignment.")
        self.btn_continue.clicked.connect(self._continue_now)
        # Chained run: one question before the pairing, Yes / No
        big = ("QPushButton {{ background: {bg}; color: {fg}; border: {border}; border-radius: 8px;"
               " padding: 8px 18px; font-size: 12pt; font-weight: bold; min-width: 190px; min-height: 44px; }}"
               " QPushButton:hover {{ background: {hover}; }}")
        self.btn_sync_ok = QPushButton("✓  Yes  (Y)\npair the images")
        self.btn_sync_ok.setStyleSheet(big.format(bg="#2E7D32", fg="white", border="none", hover="#276B2B"))
        self.btn_sync_ok.setToolTip("The green (visible) and red (infrared) curves lie on each other: "
                                    "the clock offset is right, the images are paired.")
        self.btn_sync_ok.clicked.connect(self._confirm_sync)
        self.btn_sync_adjust = QPushButton("✗  No  (N)\nadjust them by hand")
        self.btn_sync_adjust.setStyleSheet(big.format(bg="white", fg="#B03A2E", border="2px solid #E3B4AE",
                                                      hover="#FBEDEB"))
        self.btn_sync_adjust.setToolTip("Slide the infrared curve onto the visible one, then answer again.")
        self.btn_sync_adjust.clicked.connect(self.on_adjust_time_shift)
        self.btn_continue.hide()
        self.sync_banner = QFrame()
        self.sync_banner.setObjectName("syncbanner")
        self.sync_banner.setStyleSheet("#syncbanner { background: #FFF4E0; border: 1px solid #F0D29A;"
                                       " border-radius: 10px; } QLabel { background: transparent; }")
        banner = QHBoxLayout(self.sync_banner)
        banner.setContentsMargins(16, 10, 16, 10)
        banner.setSpacing(12)
        self.sync_question = QLabel("<span style='font-size:15pt; font-weight:bold; color:#1F2933'>"
                                    "Do the two curves overlap?</span><br>"
                                    "<span style='color:#2E7D32; font-weight:bold'>●</span> visible &nbsp; "
                                    "<span style='color:#C62828; font-weight:bold'>●</span> infrared")
        self.sync_question.setWordWrap(True)
        banner.addWidget(self.sync_question, 1)
        banner.addWidget(self.btn_sync_adjust)
        banner.addWidget(self.btn_sync_ok)
        self.sync_banner.hide()
        from PyQt6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Y"), self, activated=lambda: self._awaiting_sync and self._confirm_sync())
        QShortcut(QKeySequence("N"), self, activated=lambda: self._awaiting_sync and self.on_adjust_time_shift())
        auto_bar.addWidget(self.auto_label, 1)
        auto_bar.addWidget(self.btn_manual)
        auto_bar.addWidget(self.btn_continue)
        main_layout.addLayout(auto_bar)

        # Log display area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(70)
        self.log_text.setMaximumHeight(120)
        main_layout.addWidget(self.log_text)

        # Buttons: ArUco detection / Time alignment / Image pairing.
        # No fixed pixel widths: each button takes the width of its text, so
        # they never overlap with a larger font (Windows display scaling).
        btn_layout = QHBoxLayout()

        # Button 1: ArUco detection
        self.btn_run_aruco = QPushButton("Run ArUco detection (VIS + NIR)")
        btn_layout.addWidget(self.btn_run_aruco)

        # Button 2: Time alignment
        self.btn_compute_time_shift = QPushButton("Compute time alignment")
        self.btn_compute_time_shift.setEnabled(False)
        btn_layout.addWidget(self.btn_compute_time_shift)

        # Button 2b: manual adjustment of the time alignment
        self.btn_adjust_time_shift = QPushButton("Adjust alignment...")
        self.btn_adjust_time_shift.setEnabled(False)
        btn_layout.addWidget(self.btn_adjust_time_shift)

        # Button 3: Image pairing
        self.btn_image_pairing = QPushButton("Pair VIS / NIR images")
        self.btn_image_pairing.setEnabled(False)
        btn_layout.addWidget(self.btn_image_pairing)

        # Keep the buttons aligned to the left
        btn_layout.addStretch()
        self._substep_buttons = (self.btn_run_aruco, self.btn_compute_time_shift,
                                 self.btn_adjust_time_shift, self.btn_image_pairing)

        # The stages one by one (manual mode): the chained run stays the main action
        for button in self._substep_buttons:
            button.setStyleSheet(Look.SECONDARY_STYLE)

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
        self.timeshift_plot_label.setMinimumHeight(220)
        self.timeshift_plot_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.timeshift_plot_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )

        # Display the default ArUco image
        pixmap = QPixmap(str(IMAGE_ARUCO_VIS_PATH))

        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.timeshift_plot_label.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.timeshift_plot_label.setPixmap(scaled_pixmap)
        else:
            self._log(f"Unable to load image: {IMAGE_ARUCO_VIS_PATH}")

        main_layout.addWidget(self.sync_banner)
        main_layout.addWidget(self.timeshift_plot_label, 1)

        # Close button at the bottom
        # Step 3 done earlier: the saved plot, after or before the alignment
        self.btn_before = QPushButton("Before alignment")
        self.btn_before.setCheckable(True)
        self.btn_before.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_before.setToolTip("Show the curves before the clock offset was applied.")
        self.btn_before.toggled.connect(self._toggle_before)
        self.btn_before.hide()
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(Look.SECONDARY_STYLE)


        # Footer: the manual (?) on the left, Close always at the bottom right
        close_layout = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(36)
        self.btn_help.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_help.clicked.connect(lambda: Help.show_help("ch:step3", parent=self))
        close_layout.addWidget(self.btn_help)
        close_layout.addWidget(self.btn_before)
        close_layout.addStretch()
        close_layout.addWidget(self.btn_close)

        for widget, label, tip in (
            (self.btn_run_aruco, "btn:step3_aruco", "Detect the ArUco targets in the synchronisation images of both cameras."),
            (self.btn_compute_time_shift, "btn:step3_time_shift", "Compute the time offset between the VIS and NIR cameras."),
            (self.btn_adjust_time_shift, "btn:step3_adjust", "Move the NIR curve with a slider to correct the time offset by hand."),
            (self.btn_image_pairing, "btn:step3_pairing", "Pair each VIS image with the closest NIR images in time."),
            (self.btn_close, "btn:step3_close", "Close this window."),
            (self.btn_help, "ch:step3", "Open the manual at Step 3."),
            (self.btn_sync_ok, "btn:step3_overlap", self.btn_sync_ok.toolTip()),
            (self.btn_sync_adjust, "btn:step3_overlap", self.btn_sync_adjust.toolTip()),
            (self.btn_manual, "btn:step3_manual", self.btn_manual.toolTip()),
            (self.btn_continue, "btn:step3_continue", self.btn_continue.toolTip()),
            (self.btn_before, "btn:step3_before", self.btn_before.toolTip()),
        ):
            Help.attach_help(widget, label, tip, parent=self)

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
        self.btn_adjust_time_shift.clicked.connect(self.on_adjust_time_shift)
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
        self.btn_before.hide()          # a new run replaces the earlier result
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
            self.aruco_orchestrator.signals.check_image.connect(
                self._on_check_image
            )

            # Reset the progress bar before starting processing
            self.progress_bar.setValue(0)
            self.stages.set(0, Look.STAGE_RUNNING, "visible, then infrared")
            for k in (1, 2):
                self.stages.set(k, Look.STAGE_PENDING, "")

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

        # Stop the live display of check images (the label is reused by the next steps)
        self._reset_check_image_display()

        # Enable time alignment now that both detection stages are complete
        self.btn_compute_time_shift.setEnabled(True)
        self.stages.set(0, Look.STAGE_DONE,
                        f"{len(self.aruco_results_vis)} visible · {len(self.aruco_results_nir)} infrared")
        if self.auto_run:
            QTimer.singleShot(0, self.on_compute_time_shift)

    def _on_aruco_stage(self, stage: str) -> None:
        """
        Update the GUI when the active ArUco processing stage changes.

        Args:
            stage: Description of the current processing stage.
        """
        self.progress_bar.setValue(0)
        self.progress_label.setText(stage)

        # Back to the generic image of the band that starts; drop pending check images
        self._reset_check_image_display()
        generic_path = IMAGE_ARUCO_NIR_PATH if "NIR" in stage else IMAGE_ARUCO_VIS_PATH
        self._show_image_file(generic_path)

    def _reset_check_image_display(self) -> None:
        """
        Stop the hold timer and forget any pending or last shown check image.
        """
        self._pending_check_image = None
        self._last_check_image_key = None
        timer = getattr(self, "_check_image_timer", None)
        if timer is not None:
            timer.stop()

    def _show_image_file(self, image_path: Path) -> bool:
        """
        Display an image file in the central label, keeping its aspect ratio.

        Args:
            image_path: Path of the image to display.

        Returns:
            True if the image was loaded and displayed, False otherwise.
        """
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._log(f"Unable to load image: {image_path}")
            return False
        self.timeshift_plot_label.setPixmap(
            pixmap.scaled(
                self.timeshift_plot_label.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )
        return True

    def _on_check_image(self, image_path: str) -> None:
        """
        Display a check image saved during ArUco detection.

        Images arrive much faster than they can be read (several per second
        in multi-thread mode). The first one is shown immediately and kept for
        CHECK_IMAGE_HOLD_MS; during this time only the most recent image is
        remembered and shown when the delay expires.

        Worker threads finish out of order: an image older (by file name, i.e.
        capture order) than the one shown or pending is ignored, so that the
        mobile marker is seen rotating forward instead of jittering.

        Args:
            image_path: Path of the check image just saved.
        """
        key = _natural_key(Path(image_path).name)
        newest = self._last_check_image_key
        if self._pending_check_image is not None:
            newest = _natural_key(Path(self._pending_check_image).name)
        if newest is not None and key <= newest:
            return
        self._pending_check_image = image_path
        if self._check_image_timer.isActive():
            return
        self._show_pending_check_image()

    def _show_pending_check_image(self) -> None:
        """
        Show the pending check image (if any) and restart the hold delay.
        """
        image_path = self._pending_check_image
        self._pending_check_image = None
        if image_path is None:
            return
        self._show_image_file(Path(image_path))
        self._last_check_image_key = _natural_key(Path(image_path).name)
        self._check_image_timer.start(CHECK_IMAGE_HOLD_MS)

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
        running = next((k for k, s in enumerate(self.stages.states) if s == Look.STAGE_RUNNING), 0)
        self.stages.set(running, Look.STAGE_FAILED, "see the log")
        if self.auto_run:
            self._set_manual_mode(True)

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
        self.stages.set(1, Look.STAGE_RUNNING, "")

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

            # 1) Save the diagnostic plots (before / after alignment)
            # 2) and animate them in the GUI
            self.progress_bar.setValue(30)
            self._save_and_show_alignment_plots(
                time_shift, time_line_VIS, angles_VIS, time_line_NIR, angles_NIR
            )
            self.progress_bar.setValue(50)

        # ------------------------------------------------------------------
        # 3) Store internal synchronization state
        # ------------------------------------------------------------------
        self.progress_bar.setValue(70)
        self.time_shift = time_shift
        self.computed_time_shift = time_shift
        self.time_line_VIS = time_line_VIS
        self.angles_VIS = angles_VIS
        self.time_line_NIR = time_line_NIR
        self.angles_NIR = angles_NIR
        # The curves can be adjusted by hand whenever both cameras have samples.
        self.btn_adjust_time_shift.setEnabled(
            len(time_line_VIS) >= 1 and len(time_line_NIR) >= 2
        )

        # ------------------------------------------------------------------
        # 4) Final UI update
        # ------------------------------------------------------------------
        self.progress_bar.setValue(100)
        self.progress_label.setText(final_message)
        self.btn_image_pairing.setEnabled(True)
        computed = angle_abs_for_shift_time or angle_img_for_shift_time
        self.stages.set(1, Look.STAGE_DONE if computed else Look.STAGE_FAILED,
                        f"infrared {time_shift:+.2f} s" + ("" if computed else " (entered)"))
        if self.auto_run and computed:
            # Chained: the user checks that the two curves overlap, then the pairing runs
            self._ask_sync_confirmation()
        elif self.auto_run:
            # The offset could not be measured: the user takes over
            self._set_manual_mode(True)
            self.btn_image_pairing.setDefault(True)
            self.btn_image_pairing.setFocus()
            self.progress_label.setText(final_message + "  Check the alignment, then pair the images.")

    def _save_and_show_alignment_plots(
            self,
            time_shift: float,
            time_line_VIS: List[float],
            angles_VIS: List[float],
            time_line_NIR: List[float],
            angles_NIR: List[float],
    ) -> None:
        """Save check_time_before_alignment.png / check_time_alignment.png and animate them."""
        self.stop_timeshift_animation()
        output_dir = safe_path(Path(self.folderMissionPath) / "Synchro")

        # Common x-limits (robust to empty timelines)
        xlim = self.compute_x_limits(time_line_VIS, time_line_NIR, time_shift=time_shift)

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
        plot_after = self.save_timeshift_plot(
            output_dir=output_dir,
            time_line_VIS=time_line_VIS,
            angles_VIS=angles_VIS,
            time_line_NIR=[t + time_shift for t in time_line_NIR],
            angles_NIR=angles_NIR,
            time_shift=time_shift,
            filename="check_time_alignment.png",
            xlim=xlim,
        )
        self._plot_after = plot_after
        if self._awaiting_sync and self._show_plot_after():
            return          # confirmation: the aligned curves stay on screen
        try:
            self.animate_timeshift_plot(plot_before=plot_before, plot_after=plot_after)
        except Exception as e:
            print(f"Error in animate_timeshift_plot: {e}")

    def _show_plot_after(self) -> bool:
        """Aligned curves, fixed (no before/after animation)."""
        self.stop_timeshift_animation()
        if self._plot_after is None:
            return False
        return self._show_image_file(Path(self._plot_after))

    def on_adjust_time_shift(self) -> None:
        """Step 3.2b - Let the operator correct the time shift with a slider."""
        dialog = TimeShiftAdjustDialog(
            self.time_line_VIS,
            self.angles_VIS,
            self.time_line_NIR,
            self.angles_NIR,
            time_shift=self.time_shift,
            computed_time_shift=self.computed_time_shift,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_shift = dialog.value()
        if abs(new_shift - self.time_shift) < 1e-9:
            self._log("Time alignment unchanged.")
            return
        self._log(
            f"Time shift adjusted by the operator: {self.time_shift:.3f} s -> {new_shift:.3f} s "
            f"(computed: {self.computed_time_shift:.3f} s)"
        )
        self.time_shift = new_shift
        self._save_and_show_alignment_plots(
            new_shift, self.time_line_VIS, self.angles_VIS, self.time_line_NIR, self.angles_NIR
        )
        self.progress_label.setText(f"Time shift adjusted manually: {new_shift:.3f} s")
        if self.image_pairing_done:
            self._log("Run 'Pair VIS / NIR images' again to apply the new time shift.")
            QMessageBox.information(
                self,
                "Time shift changed",
                "The images were already paired with the previous time shift.\n"
                "Run 'Pair VIS / NIR images' again to apply the new one.",
            )

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
        self.stages.set(2, Look.STAGE_RUNNING, "")

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
        self.image_pairing_done = True
        mark_step_done(self.folderMissionPath, 3)
        # The precise offset places the NIR survey window from the VIS one
        try:
            nir_info = FT.update_nir_survey_from_vis(Path(self.folderMissionPath), self.time_shift)
            if nir_info is not None:
                self._log("Infrared survey window updated from the visible one.")
        except Exception as e:
            self._log(f"Infrared survey window not updated: {e}")
        self.timeshift_plot_label.setText("Image pairing completed.")
        self.progress_label.setText("Image pairing completed.")
        self.progress_bar.setValue(100)
        self.stages.set(2, Look.STAGE_DONE, f"{len(pairing_result.get('shoot_points', []))} pairs")
        if self.auto_run:
            self._paired_ready()
        else:
            self.btn_continue.show()

    def _on_image_pairing_error(self, message: str) -> None:
        """
        Handle an error reported during image pairing.

        Write the error message to the log and display a critical
        message dialog to inform the user.

        Args:
            message: Description of the image pairing error.
        """
        self._log(f"Image pairing error: {message}")
        self.stages.set(2, Look.STAGE_FAILED, "see the log")

        QMessageBox.critical(
            self,
            "Image Pairing Error",
            message
        )

    # ------------------------------------------------------------------
    # Chained run (auto_run) / manual mode
    # ------------------------------------------------------------------
    def _set_manual_mode(self, manual: bool) -> None:
        """Manual: the four stage buttons, each run by the user (classic Step 3).
        Automatic: the stages follow each other, only the tracker is shown."""
        if manual and self.auto_run:
            self._log("Manual mode: run each stage with its button.")
        self.auto_run = not manual
        for b in self._substep_buttons:
            b.setVisible(manual)
        self.btn_manual.setVisible(not manual)
        if manual:
            self._hide_sync_confirmation()
            self.auto_label.setText("")
        else:
            self.auto_label.setText("Automatic: detection, clock alignment and pairing follow each other.")

    def previous_result(self) -> Optional[dict]:
        """What an earlier run of Step 3 left: offset, pairs, plots (None if not run)."""
        folder = Path(self.folderMissionPath)
        try:
            with open(folder / "AerialPhotography" / "shoot_points.json", encoding="utf-8") as f:
                data = json.load(f)
            time_shift = float(data["time_shift"])
            pairs = len(data.get("shoot_points", []))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        synchro = folder / "Synchro"
        after, before = synchro / "check_time_alignment.png", synchro / "check_time_before_alignment.png"
        return {"time_shift": time_shift, "pairs": pairs, "date": str(data.get("created_at", ""))[:10],
                "after": after if after.is_file() else None, "before": before if before.is_file() else None}

    def _show_previous_result(self) -> None:
        """Step 3 opened again: show what was found (aligned curves, offset, pairs)."""
        prev = self.previous_result()
        if prev is None:
            return
        self._previous = prev
        self.time_shift = self.computed_time_shift = prev["time_shift"]
        self.stages.set(0, Look.STAGE_DONE, "done earlier")
        self.stages.set(1, Look.STAGE_DONE, f"infrared {prev['time_shift']:+.2f} s")
        self.stages.set(2, Look.STAGE_DONE, f"{prev['pairs']} pairs")
        y, m, d = (prev["date"].split("-") + ["", "", ""])[:3]
        when = f" on {d}/{m}/{y}" if d else ""
        self.auto_label.setText(f"Synchronised{when}: infrared clock offset {prev['time_shift']:+.2f} s, "
                                f"{prev['pairs']} pairs. Run the stages again below to redo it.")
        self.progress_label.setText("Step 3 already done: clock alignment checked on the curves below.")
        self.progress_bar.setValue(100)
        if prev["after"] is not None:
            self._plot_after = prev["after"]
            self.btn_before.setVisible(prev["before"] is not None)
            QTimer.singleShot(0, self._show_plot_after)
        self.btn_continue.show()

    def _toggle_before(self, on: bool) -> None:
        prev = getattr(self, "_previous", None)
        if prev is None:
            return
        self.stop_timeshift_animation()
        self._show_image_file(Path(prev["before"] if on else prev["after"]))
        self.btn_before.setText("After alignment" if on else "Before alignment")

    def _ask_sync_confirmation(self) -> None:
        """Chained run: show the aligned curves and wait for the user's word."""
        self._awaiting_sync = True
        self._show_plot_after()
        self.stages.detail(1, f"infrared {self.time_shift:+.2f} s · check the curves")
        self.auto_label.setText("Clocks aligned: one check before the pairing.")
        self.sync_banner.show()
        QTimer.singleShot(0, self._show_plot_after)     # scaled once the banner has its place
        self.btn_sync_ok.setDefault(True)
        self.btn_sync_ok.setFocus()
        self.btn_manual.hide()

    def _hide_sync_confirmation(self) -> None:
        self._awaiting_sync = False
        self.sync_banner.hide()

    def _confirm_sync(self) -> None:
        self._hide_sync_confirmation()
        self._log(f"Clock alignment confirmed by the user: {self.time_shift:.3f} s")
        self.stages.detail(1, f"infrared {self.time_shift:+.2f} s · checked")
        self.auto_label.setText("Clocks aligned: pairing the images…")
        if self.auto_run and not self.image_pairing_done:
            self.on_image_pairing()

    def _paired_ready(self) -> None:
        """Chained run done: Step 4 is long, the user starts it (never on its own)."""
        self.btn_continue.show()
        self.btn_continue.setDefault(True)
        self.btn_continue.setFocus()
        self.btn_manual.hide()
        self.stages.set(3, Look.STAGE_PENDING, "when you are ready")
        self.auto_label.setText("Cameras synchronised and images paired. The alignment (Step 4) is long: "
                                "open it when you are ready.")

    def _continue_now(self) -> None:
        self.stages.set(3, Look.STAGE_RUNNING, "")
        self.continue_requested.emit()
        self.data_signal_to_main.emit(True)
        self.close()

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
                self.timeshift_plot_label.contentsRect().size(),
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
                self.timeshift_plot_label.contentsRect().size(),
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
            self.timeshift_plot_label.contentsRect().size(),
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
        worker.signals.check_image.connect(self.signals.check_image.emit)

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
    # Path of a check image (Synchro/Check_ARUCO) just saved by a worker
    check_image = pyqtSignal(str)

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

        btn_ok.setStyleSheet(Look.PRIMARY_STYLE)
        btn_cancel.setStyleSheet(Look.SECONDARY_STYLE)
        btn_ok.setDefault(True)
        btn_ok.setToolTip("Use this clock offset (seconds added to the infrared times).")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        # ------------------------------------------------------------
        # Layouts (CRITICAL for Qt stability)
        # ------------------------------------------------------------
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(btn_cancel)
        button_layout.addWidget(btn_ok)

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



class TimeShiftAdjustDialog(QDialog):
    """
    Correct the VIS / NIR time shift by hand.

    The VIS curve stays fixed; the NIR curve moves with the slider (NIR time
    + time shift, the convention of the alignment plot and the image pairing).
    The NIR curve at the computed shift stays visible as a dashed reference,
    and the RMS angle gap between both curves is updated live.
    """

    SLIDER_UNITS_PER_SECOND = 1000  # 1 ms resolution

    def __init__(
        self,
        time_line_VIS: Sequence[float],
        angles_VIS: Sequence[float],
        time_line_NIR: Sequence[float],
        angles_NIR: Sequence[float],
        time_shift: float,
        computed_time_shift: Optional[float] = None,
        parent=None,
    ):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

        self.setWindowTitle("Adjust VIS / NIR time alignment")
        self.setModal(True)
        self.resize(1000, 720)

        self.t_vis = np.asarray(time_line_VIS, dtype=float)
        self.a_vis = np.asarray(angles_VIS, dtype=float)
        self.t_nir = np.asarray(time_line_NIR, dtype=float)
        self.a_nir = np.asarray(angles_NIR, dtype=float)
        self.computed_time_shift = (
            float(time_shift) if computed_time_shift is None or not np.isfinite(computed_time_shift)
            else float(computed_time_shift)
        )
        self._updating = False

        # Slider half-range: 20 % of the recorded span, at least 2 s.
        spans = [np.ptp(t) for t in (self.t_vis, self.t_nir) if t.size > 1]
        self.window_s = max(2.0, 0.2 * max(spans, default=0.0))

        # ---------------- Plot ----------------
        # Constrained layout keeps the title (updated on every move) inside the figure.
        self.figure = Figure(figsize=(10, 6), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        # VIS drawn above NIR with larger markers so both stay visible when they overlap.
        self.ax.plot(
            self.t_vis, self.a_vis, label="VIS", color="g", lw=1.2, zorder=3,
            marker="o", markersize=7, markeredgewidth=0.5, markeredgecolor="black",
            markerfacecolor="none",
        )
        self.ax.plot(
            self.t_nir + self.computed_time_shift, self.a_nir,
            label=f"NIR at computed shift ({self.computed_time_shift:.3f} s)",
            color="r", lw=1.0, ls="--", alpha=0.35,
        )
        (self.nir_line,) = self.ax.plot(
            self.t_nir + time_shift, self.a_nir, label="NIR (adjusted)", color="r", lw=1.2,
            marker="o", markersize=5, markeredgewidth=0.5, markeredgecolor="black",
        )
        all_times = np.concatenate([self.t_vis, self.t_nir + self.computed_time_shift])
        if all_times.size:
            padding = 0.05 * max(np.ptp(all_times), 1e-6) + self.window_s
            self.ax.set_xlim(all_times.min() - padding, all_times.max() + padding)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Angle (deg)")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend(loc="best")

        # ---------------- Controls ----------------
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setSingleStep(1)     # arrow keys: 1 ms
        self.slider.setPageStep(100)     # page up / down: 0.1 s
        self._center_slider(time_shift)

        self.spinbox = QDoubleSpinBox(self)
        self.spinbox.setDecimals(3)
        self.spinbox.setRange(-600.0, 600.0)
        self.spinbox.setSingleStep(0.01)
        self.spinbox.setSuffix(" s")
        self.spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.spinbox.setValue(time_shift)

        self.info_label = QLabel(self)
        self.info_label.setWordWrap(True)

        btn_reset = QPushButton("Reset to computed", self)
        btn_apply = QPushButton("Apply", self)
        btn_cancel = QPushButton("Cancel", self)
        btn_reset.setToolTip("Back to the offset computed from the targets.")
        btn_apply.setToolTip("Keep this offset: the curves after alignment are drawn again with it.")
        btn_cancel.setToolTip("Close without changing the offset.")
        for button in (btn_reset, btn_cancel):
            button.setStyleSheet(Look.SECONDARY_STYLE)
        btn_apply.setStyleSheet(Look.PRIMARY_STYLE)
        btn_apply.setDefault(True)

        self.slider.valueChanged.connect(self._on_slider)
        self.spinbox.valueChanged.connect(self._on_spinbox)
        btn_reset.clicked.connect(lambda: self.spinbox.setValue(self.computed_time_shift))
        btn_apply.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        # ---------------- Layout ----------------
        help_label = QLabel(
            "Drag the slider until the red NIR curve lies on the green VIS curve. "
            "Arrow keys move by 1 ms, Page Up / Down by 0.1 s; type a value for a larger change. "
            "Use the toolbar magnifier to zoom on a detail.",
            self,
        )
        help_label.setWordWrap(True)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Time shift:", self))
        slider_row.addWidget(self.slider, stretch=1)
        slider_row.addWidget(self.spinbox)

        button_row = QHBoxLayout()
        button_row.addWidget(btn_reset)
        button_row.addStretch()
        button_row.addWidget(btn_cancel)
        button_row.addWidget(btn_apply)

        layout = QVBoxLayout(self)
        layout.addWidget(help_label)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, stretch=1)
        layout.addLayout(slider_row)
        layout.addWidget(self.info_label)
        layout.addLayout(button_row)

        self._computed_rms, _ = Aru.angle_mismatch_rms(
            self.t_vis, self.a_vis, self.t_nir, self.a_nir, self.computed_time_shift
        )
        self._update_plot(time_shift)

    # ------------------------------------------------------------------
    def _center_slider(self, time_shift: float) -> None:
        """Center the slider range on ``time_shift`` (+/- window_s)."""
        units = self.SLIDER_UNITS_PER_SECOND
        center = int(round(time_shift * units))
        half = int(round(self.window_s * units))
        self.slider.blockSignals(True)
        self.slider.setRange(center - half, center + half)
        self.slider.setValue(center)
        self.slider.blockSignals(False)

    def _on_slider(self, position: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.spinbox.setValue(position / self.SLIDER_UNITS_PER_SECOND)
        self._updating = False
        self._update_plot(self.value())

    def _on_spinbox(self, value: float) -> None:
        if self._updating:
            return
        position = int(round(value * self.SLIDER_UNITS_PER_SECOND))
        if not self.slider.minimum() <= position <= self.slider.maximum():
            self._center_slider(value)
        else:
            self._updating = True
            self.slider.setValue(position)
            self._updating = False
        self._update_plot(value)

    def _update_plot(self, time_shift: float) -> None:
        self.nir_line.set_xdata(self.t_nir + time_shift)
        self.ax.set_title(f"Time shift VIS / NIR = {time_shift:.3f} s")
        self.canvas.draw_idle()

        rms, count = Aru.angle_mismatch_rms(
            self.t_vis, self.a_vis, self.t_nir, self.a_nir, time_shift
        )
        delta = time_shift - self.computed_time_shift
        text = (
            f"Time shift: <b>{time_shift:.3f} s</b> "
            f"(computed {self.computed_time_shift:.3f} s, change {delta:+.3f} s). "
        )
        if rms is None:
            text += "<span style='color:#b00'>The curves do not overlap.</span>"
        else:
            text += f"RMS angle gap: <b>{rms:.2f}°</b> on {count} VIS images"
            if self._computed_rms is not None:
                text += f" (computed shift: {self._computed_rms:.2f}°)"
            text += "."
        self.info_label.setText(text)

    def value(self) -> float:
        """Return the selected time shift (seconds)."""
        return float(self.spinbox.value())
