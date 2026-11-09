# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 5
#   Georeferencing images.  User interface
#   17/10/2026   V004
# ---------------------------------------------------------------------------------
"""Step 5 dialog: georeferencing, ODM mapping, DTM and contour lines.

``DialogGeoRef`` offers three buttons:

* **Run Geo ref**: georeferences images selected by the user
  (``IRD_Interactive_GeoRef.georef_main``). Runs in the GUI thread.
* **Run Mapping**: selects the image quartets (``ODMSelectionDialog``: maximum
  |dt|, then best mapping by image overlap or one image every n), then runs OpenDroneMap in Docker through
  ``IRD_Interactive_ODM.run_odm`` in a background worker (``ODMRunWorker``).
  The orthophoto is archived in ``mapping_MULTI/mapping_result`` and displayed
  as an RGB preview (``ODMPreviewWorker``). The DTM and contour lines are then
  generated automatically.
* **DTM + contours**: (re)builds the DTM and the contour lines of the archived
  orthophoto with a user-defined grid step (``DtmStepDialog``, ``DtmWorker``,
  ``IRD_Interactive_contours.generate_ortho_dtm``).

Long tasks run in ``QRunnable`` workers that report to the dialog only through
Qt signals; the buttons and the window are locked while ODM or the DTM run.
"""

from pathlib import Path
import numpy as np
from typing import List, Optional
import rawpy
import imageio

# ----------------------------------------------------
#     bib Multi Thread
# ----------------------------------------------------



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
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
    QDoubleSpinBox,
    QSpinBox,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
    QFormLayout,
    QDialogButtonBox,
)

# ----------------------------------------------------
#     bib matplotlib
# ----------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend. Essential here when using PyQt.

# ----------------------------------------------------
#     bib IRD_Interactive
# ----------------------------------------------------
import IRD_Interactive_help as Help
from IRD_Interactive_progress import mark_step_done
import best_mapping
import IRD_Interactive_GeoRef as GeoRef
from IRD_Interactive_contours import DEFAULT_GRID_STEP_M, generate_ortho_dtm
from IRD_Interactive_look import DIALOG_STYLE, PRIMARY_STYLE, SECONDARY_STYLE
from IRD_Interactive_ODM import (
    DockerUnavailableError,
    ODMMappingError,
    read_orthophoto_preview,
    run_odm,
)


# Shown in the preview area when no result is displayed yet.
PREVIEW_IDLE_TEXT = "The results (orthophoto, georeferenced images, maps) will be displayed here."


class ODMRunSignals(QObject):
    """Signals emitted while ODM runs outside the GUI thread."""

    log = pyqtSignal(str)
    stage = pyqtSignal(str)
    finished = pyqtSignal(dict)
    docker_unavailable = pyqtSignal(str)
    error = pyqtSignal(str)


class ODMRunWorker(QRunnable):
    """Run the complete ODM workflow without blocking the Phase 5 dialog."""

    def __init__(
        self,
        mission_folder: Path,
        dt_tolerance_s: float = 0.5,
        sample_every: int = 3,
        overlap: Optional[float] = None,
    ):
        super().__init__()
        self.mission_folder = mission_folder
        self.dt_tolerance_s = dt_tolerance_s
        self.sample_every = sample_every
        self.overlap = overlap
        self.signals = ODMRunSignals()

    def run(self) -> None:
        """Run ODM and emit ``finished`` (result), ``docker_unavailable`` or ``error``."""
        try:
            result = run_odm(
                self.mission_folder,
                dt_tolerance_s=self.dt_tolerance_s,
                sample_every=self.sample_every,
                overlap=self.overlap,
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


class ODMSelectionDialog(QDialog):
    """Collect temporal and density criteria for an ODM mapping run.

    Default: best mapping by image overlap, with the overlap chosen in Step 2 /
    Step 4 (FlightAnalytics/best_mapping.json). Applied to images that Step 4
    already selected the same way, it keeps them all."""

    def __init__(self, parent=None, mission_folder: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("ODM image selection")
        self.setMinimumWidth(440)
        choice = (best_mapping.load_choice(Path(mission_folder)) if mission_folder
                  else {"enabled": True, "overlap": best_mapping.DEFAULT_OVERLAP})

        layout = QVBoxLayout(self)
        criteria = QFormLayout()
        self.dt_tolerance = QDoubleSpinBox()
        self.dt_tolerance.setRange(0.05, 6.0)
        self.dt_tolerance.setSingleStep(0.05)
        self.dt_tolerance.setDecimals(2)
        self.dt_tolerance.setValue(0.5)
        self.dt_tolerance.setSuffix(" s")
        criteria.addRow("Maximum |dt| (NIR rank 1):", self.dt_tolerance)
        layout.addLayout(criteria)

        density_group = QGroupBox("Image density and overlap")
        density_layout = QVBoxLayout(density_group)
        self.overlap_radio = QRadioButton("Best mapping: select by image overlap (recommended)")
        self.sample_radio = QRadioButton("Select one image every n eligible images")
        self.overlap_radio.setToolTip(
            "Keep the images whose ground footprints overlap by the chosen amount: the images the map "
            "needs. On images already selected in Step 4, all of them are kept.")
        self.sample_radio.setToolTip("Keep one eligible image every n: less overlap, faster mapping.")
        for radio in (self.sample_radio, self.overlap_radio):
            Help.attach_help(radio, "btn:step5_selection", radio.toolTip(), parent=self)
        self.selection_group = QButtonGroup(self)
        self.selection_group.setExclusive(True)
        self.selection_group.addButton(self.overlap_radio)
        self.selection_group.addButton(self.sample_radio)

        density_layout.addWidget(self.overlap_radio)
        self.overlap = QSpinBox()
        self.overlap.setRange(round(best_mapping.MIN_OVERLAP * 100), round(best_mapping.MAX_OVERLAP * 100))
        self.overlap.setSingleStep(5)
        self.overlap.setSuffix(" %")
        self.overlap.setValue(round(choice["overlap"] * 100))
        overlap_form = QFormLayout()
        overlap_form.addRow("Overlap between successive images:", self.overlap)
        density_layout.addLayout(overlap_form)

        density_layout.addWidget(self.sample_radio)
        self.sample_every = QSpinBox()
        self.sample_every.setRange(1, 4)
        self.sample_every.setValue(3)
        sample_row = QFormLayout()
        sample_row.addRow("One image every:", self.sample_every)
        density_layout.addLayout(sample_row)
        layout.addWidget(density_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        (self.overlap_radio if choice["enabled"] else self.sample_radio).setChecked(True)
        self.sample_radio.toggled.connect(self._update_selection_controls)
        self._update_selection_controls()

    def _update_selection_controls(self) -> None:
        """Enable only the controls of the selected criterion."""
        sample_selected = self.sample_radio.isChecked()
        self.sample_every.setEnabled(sample_selected)
        self.overlap.setEnabled(not sample_selected)

    def selected_overlap(self) -> Optional[float]:
        """Footprint overlap (0..1) of the best mapping, None for one image every n."""
        return None if self.sample_radio.isChecked() else self.overlap.value() / 100.0

    def description(self) -> str:
        """The selection in words (confirmation and log)."""
        overlap = self.selected_overlap()
        rule = (f"best mapping, {overlap:.0%} overlap between successive images" if overlap is not None
                else f"one image every {self.sample_every.value()} eligible images")
        return f"|dt| <= {self.dt_tolerance.value():.2f} s; {rule}"


class ODMPreviewSignals(QObject):
    """Signals of ``ODMPreviewWorker``: ``ready`` (RGB array) or ``error``."""

    ready = pyqtSignal(object)
    error = pyqtSignal(str)


class DtmSignals(QObject):
    """Signals of ``DtmWorker``: ``log``, ``finished`` (paths of results) or ``error``."""

    log = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


class DtmWorker(QRunnable):
    """Build the DTM and contour lines of an orthophoto off the GUI thread."""

    def __init__(self, orthophoto_path: Path, step: float):
        super().__init__()
        self.orthophoto_path = orthophoto_path
        self.step = step
        self.signals = DtmSignals()

    def run(self) -> None:
        try:
            result = generate_ortho_dtm(
                self.orthophoto_path,
                step=self.step,
                log=self.signals.log.emit,
            )
        except Exception as error:
            self.signals.error.emit(f"{type(error).__name__}: {error}")
        else:
            self.signals.finished.emit(result)


class DtmStepDialog(QDialog):
    """Ask for the grid step used to query the terrain altitudes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DTM and contour lines")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.grid_step = QDoubleSpinBox()
        self.grid_step.setRange(1.0, 100.0)
        self.grid_step.setSingleStep(1.0)
        self.grid_step.setDecimals(1)
        self.grid_step.setValue(DEFAULT_GRID_STEP_M)
        self.grid_step.setSuffix(" m")
        form.addRow("Altitude grid step:", self.grid_step)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(
                "Altitudes are requested from the IGN API (OpenTopoData as fallback).\n"
                "A smaller step means many more requests."
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


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
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumSize(900, 600)  # Minimum window size
        self.resize(self.height_window, self.whidth_window,)  # Initial window size

        self._init_gui()
        self._connect_signals()
        self.odm_worker: Optional[ODMRunWorker] = None
        self.odm_preview_worker: Optional[ODMPreviewWorker] = None
        self.dtm_worker: Optional[DtmWorker] = None
        self.georef_results: List[str] = []
        self.odm_dt_tolerance_s = 0.5
        self.odm_sample_every = 3
        self.odm_overlap: Optional[float] = None

        # Connect the logger signal to the GUI log window.
        self.log_signal.connect(self._log)

        # Connect the image signal to the image display method.
        self.image_signal.connect(self._display_image)

        # Forward GeoRef logger messages to this dialog.
        self._log_callback = self.log_signal.emit
        GeoRef.logger.log_callback = self._log_callback

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
        self.btn_run_GeoRef.setStyleSheet(PRIMARY_STYLE)
        btn_layout.addWidget(self.btn_run_GeoRef)
        self.btn_run_Mapping = QPushButton("Run Mapping")
        self.btn_run_Mapping.setFixedWidth(180)
        self.btn_run_Mapping.setStyleSheet(PRIMARY_STYLE)
        btn_layout.addWidget(self.btn_run_Mapping)
        self.btn_run_DTM = QPushButton("DTM + contours")
        self.btn_run_DTM.setFixedWidth(180)
        self.btn_run_DTM.setStyleSheet(PRIMARY_STYLE)
        btn_layout.addWidget(self.btn_run_DTM)
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
        self.image_preview_label = QLabel(PREVIEW_IDLE_TEXT)
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumHeight(250)
        self.image_preview_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )
        main_layout.addWidget(self.image_preview_label, stretch=1)

        # Close button at the bottom
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(SECONDARY_STYLE)

        # Push the Close button to the bottom
        main_layout.addStretch()

        # Footer: the manual (?) on the left, Close always at the bottom right
        close_layout = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(36)
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.clicked.connect(lambda: Help.show_help("ch:step5", parent=self))
        close_layout.addWidget(self.btn_help)
        close_layout.addStretch()
        close_layout.addWidget(self.btn_close)

        for widget, label, tip in (
            (self.btn_run_GeoRef, "btn:step5_georef",
             "Choose images (drone DNG, or IRD_XXXX_1..4.tif groups) and georeference and orthorectify each one."),
            (self.btn_run_Mapping, "btn:step5_mapping",
             "Choose the images, then assemble them into one 4-band orthophoto with OpenDroneMap (Docker)."),
            (self.btn_run_DTM, "btn:step5_dtm",
             "Build the terrain model and the contour lines over the orthophoto (IGN altitudes, internet)."),
            (self.btn_close, "btn:step5_close", "Close this window."),
            (self.btn_help, "ch:step5", "Open the manual at Step 5."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

        main_layout.addLayout(close_layout)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.btn_run_GeoRef.clicked.connect(self.on_run_GeoRef)
        self.btn_run_Mapping.clicked.connect(self.on_run_ODM)
        self.btn_run_DTM.clicked.connect(self.on_run_DTM)
        self.btn_close.clicked.connect(self.on_close)

    # ------------------------------------------------------------------
    # Slots (placeholders)
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        """Close the dialog, refused while ODM or the DTM is running."""
        if self.odm_worker is not None or self.dtm_worker is not None:
            QMessageBox.warning(
                self,
                "Processing is running",
                "Wait for the ODM or DTM process to finish before closing this window.",
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
        # GeoRef runs on the GUI thread: repaint now instead of at the end of the run.
        self.image_preview_label.repaint()
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
            self.georef_results = []
            self.progress_label.setText("Geo Ref – running...")
            self._set_preview_text(
                "Waiting for Geo Ref...\n"
                "Each georeferenced image will be displayed here."
            )
            self.progress_label.repaint()
            GeoRef.georef_main(
                image_callback=self.image_signal.emit,
                mission_parameters=self.mission_parameters,
                result_callback=self._display_georef_result,
            )
            self.on_GeoRef_finished()

        except Exception as e:
            self.progress_bar.setValue(0)
            self._log(f"Error starting Geo Ref: {e}")
            import traceback
            traceback.print_exc()

    def _display_georef_result(self, geotiff_path: str) -> None:
        """Show the RGB bands of a georeferenced GeoTIFF once it is written."""
        self.georef_results.append(geotiff_path)
        self.progress_label.setText(f"Geo Ref – {Path(geotiff_path).name} done")
        try:
            rgb = read_orthophoto_preview(Path(geotiff_path))
        except Exception as error:
            self._log(f"Georeferenced preview failed: {type(error).__name__}: {error}")
            return
        self._show_rgb_preview(rgb)
        self.image_preview_label.repaint()
        self._log(f"Georeferenced image displayed: {geotiff_path}")

    def on_GeoRef_finished(self):
        count = len(self.georef_results)
        if count:
            message = f"Georeferencing completed: {count} image(s) georeferenced."
        else:
            message = "Georeferencing finished: no image was georeferenced."
            self._set_preview_text(PREVIEW_IDLE_TEXT)
        self.progress_label.setText(message)
        self._log(message)
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
        selection_dialog = ODMSelectionDialog(self, mission_folder)
        if selection_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.odm_dt_tolerance_s = selection_dialog.dt_tolerance.value()
        self.odm_sample_every = selection_dialog.sample_every.value()
        self.odm_overlap = selection_dialog.selected_overlap()

        confirm = QMessageBox.question(
            self,
            "Start ODM mapping",
            "This will hard-link (or copy, if the drive does not support hard "
            "links) the selected image quartets from "
            "ImgIRdrone/imgMultispectral into the prepared ODM dataset, then run "
            "ODM directly in mapping_MULTI using Docker.\n\n"
            "The orthophoto, report, shots GeoJSON, and 2.5D mesh will also be copied "
            "to mapping_MULTI/mapping_result.\n\n"
            "The processing may take a long time and use several gigabytes of memory "
            "and disk space. Existing ODM output folders or archived mapping results "
            "will not be overwritten; move or remove them manually before starting "
            "another run.\n\n"
            f"Selection: {selection_dialog.description()}.\n\n"
            f"Mission:\n{mission_folder}\n\nStart ODM now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._start_ODM_worker(
            mission_folder,
            dt_tolerance_s=self.odm_dt_tolerance_s,
            sample_every=self.odm_sample_every,
        )

    def _start_ODM_worker(
        self,
        mission_folder: Path,
        dt_tolerance_s: Optional[float] = None,
        sample_every: Optional[int] = None,
    ) -> None:
        """Start ``ODMRunWorker`` in the thread pool and lock the buttons until it ends."""
        if dt_tolerance_s is not None:
            self.odm_dt_tolerance_s = dt_tolerance_s
        if sample_every is not None:
            self.odm_sample_every = sample_every
        worker = ODMRunWorker(
            mission_folder,
            dt_tolerance_s=self.odm_dt_tolerance_s,
            sample_every=self.odm_sample_every,
            overlap=self.odm_overlap,
        )
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
        self._set_preview_text(
            "Waiting for ODM...\n"
            "The orthophoto will be displayed here when the mapping is finished."
        )
        self._log("Starting the complete ODM workflow.")
        QThreadPool.globalInstance().start(worker)

    def _on_ODM_docker_unavailable(self, message: str) -> None:
        """Offer to retry once Docker Desktop is started (the selection is then kept)."""
        self._finish_ODM_ui()
        self._log(f"Docker is unavailable: {message}")
        retry = QMessageBox.question(
            self,
            "Docker is not running",
            f"{message}\n\n"
            "Please start Docker (Docker Desktop, or the docker service on Linux) "
            "and wait until its engine is running. "
            "Then choose Retry to check the engine again, or Cancel to stop here.",
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry,
        )
        if retry == QMessageBox.StandardButton.Retry:
            self._start_ODM_worker(Path(self.folderMissionPath))
        else:
            self.progress_label.setText("ODM cancelled: Docker is unavailable.")
            self._set_preview_text(PREVIEW_IDLE_TEXT)

    def _set_preview_text(self, text: str) -> None:
        """Replace the preview image by a message (what is running, what will come)."""
        self.image_preview_label.setPixmap(QPixmap())
        self.image_preview_label.setText(text)
        self.image_preview_label.repaint()

    def _on_ODM_stage(self, stage: str) -> None:
        self.progress_label.setText(f"ODM – {stage}")

    def _finish_ODM_ui(self) -> None:
        """Release the worker and re-enable the buttons and the progress bar."""
        self.odm_worker = None
        self.btn_run_GeoRef.setEnabled(True)
        self.btn_run_Mapping.setEnabled(True)
        self.btn_close.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _on_ODM_finished(self, result: dict) -> None:
        """Display the orthophoto preview, then chain the DTM and contour lines."""
        self._finish_ODM_ui()
        orthophoto = result["orthophoto"]
        completion_message = f"Orthophoto:\n{orthophoto['path']}"
        self._log(f"ODM completed successfully: {orthophoto['path']}")
        mark_step_done(self.folderMissionPath, 5)  # Step 5 is done once the ODM mapping is
        self.progress_label.setText("ODM completed successfully.")
        self.image_preview_label.setText("Loading orthophoto preview...")
        self.image_preview_label.setPixmap(QPixmap())
        self._start_ODM_preview(Path(orthophoto["path"]))
        self._start_DTM_worker(Path(orthophoto["path"]), DEFAULT_GRID_STEP_M)
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
        """Show the RGB array (bands 1-3 of the orthophoto) in the preview zone."""
        self._show_rgb_preview(rgb)
        self._log("Orthophoto RGB preview displayed (bands 1-3).")
        self.odm_preview_worker = None

    def _show_rgb_preview(self, rgb: np.ndarray) -> None:
        """Show an 8-bit RGB array in the preview zone, keeping its aspect ratio."""
        rgb = np.ascontiguousarray(rgb)
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

    def _on_ODM_preview_error(self, error_message: str) -> None:
        self.image_preview_label.setText("Orthophoto preview could not be created.")
        self._log(f"Orthophoto preview failed: {error_message}")
        self.odm_preview_worker = None

    # --------------------------------------------
    #  DTM and contour lines
    # --------------------------------------------

    def _set_busy_buttons(self, enabled: bool) -> None:
        """Enable or disable all action buttons (disabled while the DTM is computed)."""
        for button in (
            self.btn_run_GeoRef,
            self.btn_run_Mapping,
            self.btn_run_DTM,
            self.btn_close,
        ):
            button.setEnabled(enabled)

    def on_run_DTM(self) -> None:
        """Rebuild the DTM and contour lines of the archived ODM orthophoto."""
        if self.dtm_worker is not None or self.odm_worker is not None:
            return
        orthophoto = (
            Path(self.folderMissionPath)
            / "mapping_MULTI"
            / "mapping_result"
            / "odm_orthophoto.tif"
        )
        if not orthophoto.is_file():
            QMessageBox.warning(
                self,
                "Orthophoto not found",
                f"Run the mapping first. File not found:\n{orthophoto}",
            )
            return
        dialog = DtmStepDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_DTM_worker(orthophoto, dialog.grid_step.value(), manual=True)

    def _start_DTM_worker(
        self, orthophoto_path: Path, step: float, manual: bool = False
    ) -> None:
        if self.dtm_worker is not None:
            return
        worker = DtmWorker(orthophoto_path, step)
        worker.signals.log.connect(self._log)
        worker.signals.finished.connect(
            lambda result, manual=manual: self._on_DTM_finished(result, manual)
        )
        worker.signals.error.connect(self._on_DTM_error)
        self.dtm_worker = worker
        self._set_busy_buttons(False)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("DTM and contour lines – altitude requests")
        self._log(f"Building DTM and contour lines (grid step {step:g} m).")
        QThreadPool.globalInstance().start(worker)

    def _finish_DTM_ui(self) -> None:
        self.dtm_worker = None
        self._set_busy_buttons(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _on_DTM_finished(self, result: dict, manual: bool) -> None:
        """Log the generated files; a manual run also shows the 2D map and a message box."""
        self._finish_DTM_ui()
        self.progress_label.setText("DTM and contour lines completed.")
        self._log(
            "Contour lines (QGIS): "
            f"{result['contours'] or 'skipped (GDAL not installed)'}\nDTM raster: {result['dtm']}\n"
            f"2D map: {result['map']}\n3D surface: {result['surface_3d']}"
        )
        if manual:
            # After a chained ODM run, keep the orthophoto preview on screen.
            self._display_image(result["map"])
            QMessageBox.information(
                self,
                "DTM and contour lines",
                f"Files saved next to the orthophoto:\n{Path(result['dtm']).parent}",
            )

    def _on_DTM_error(self, error_message: str) -> None:
        """Warn the user; the DTM failure never affects the archived ODM result."""
        self._finish_DTM_ui()
        self.progress_label.setText("DTM and contour lines failed.")
        self._log(f"DTM and contour lines failed: {error_message}")
        QMessageBox.warning(
            self,
            "DTM and contour lines",
            f"The DTM and contour lines could not be generated "
            f"(the ODM result is not affected):\n\n{error_message}",
        )

    def _on_ODM_error(self, error_message: str) -> None:
        """Report an ODM failure (details are in the ``odm_run_*.log`` file)."""
        self._finish_ODM_ui()
        self._log(f"ODM failed: {error_message}")
        QMessageBox.critical(
            self,
            "ODM error",
            f"The ODM workflow failed:\n\n{error_message}",
        )
        self.progress_label.setText("ODM failed.")
        self._set_preview_text("ODM failed: see the log above.")

    def done(self, result) -> None:
        """Closed: the shared GeoRef logger stops writing to this window (deleted later)."""
        super().done(result)
        if GeoRef.logger.log_callback is getattr(self, "_log_callback", None):
            GeoRef.logger.log_callback = None

    def closeEvent(self, event) -> None:
        """Refuse to close the window while ODM or the DTM is running."""
        if self.odm_worker is not None or self.dtm_worker is not None:
            QMessageBox.warning(
                self,
                "Processing is running",
                "Wait for the ODM or DTM process to finish before closing this window.",
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
