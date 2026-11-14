# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 6
#   Georeferencing images.  User interface
#   17/10/2026   V004
# ---------------------------------------------------------------------------------
"""Step 6 dialog: georeferencing, ODM mapping, DTM and contour lines.

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
    QTimer,
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
    QSizePolicy,
    QCheckBox,
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
from IRD_Interactive_progress import mark_step_done, notifier
import best_mapping
import mission_type
import IRD_Interactive_GeoRef as GeoRef
from IRD_Interactive_contours import DEFAULT_GRID_STEP_M, generate_ortho_dtm
import IRD_Interactive_look as Look
from IRD_Interactive_look import DIALOG_STYLE, MESSAGE_STYLE, PRIMARY_STYLE, SECONDARY_STYLE
from IRD_Interactive_ODM import (
    DockerUnavailableError,
    ODMMappingError,
    read_orthophoto_preview,
    run_odm,
)
import IRD_Interactive_ODM as ODM


# Shown in the preview area when no result is displayed yet.
PREVIEW_IDLE_TEXT = "The results (orthophoto, georeferenced images, maps) will be displayed here."
STEP_NAME = "Mapping and georeferencing"


class ODMRunSignals(QObject):
    """Signals emitted while ODM runs outside the GUI thread."""

    log = pyqtSignal(str)
    stage = pyqtSignal(str)
    finished = pyqtSignal(dict)
    docker_unavailable = pyqtSignal(str)
    error = pyqtSignal(str)


class ODMRunWorker(QRunnable):
    """Run the complete ODM workflow without blocking the Phase 6 dialog."""

    def __init__(
        self,
        mission_folder: Path,
        dt_tolerance_s: float = 0.5,
        sample_every: int = 3,
        overlap: Optional[float] = None,
        use_gpu: bool = False,
        update_image: bool = False,
    ):
        super().__init__()
        self.mission_folder = mission_folder
        self.dt_tolerance_s = dt_tolerance_s
        self.sample_every = sample_every
        self.overlap = overlap
        self.use_gpu = use_gpu
        self.update_image = update_image
        self.signals = ODMRunSignals()

    def run(self) -> None:
        """Run ODM and emit ``finished`` (result), ``docker_unavailable`` or ``error``."""
        try:
            result = run_odm(
                self.mission_folder,
                dt_tolerance_s=self.dt_tolerance_s,
                sample_every=self.sample_every,
                overlap=self.overlap,
                use_gpu=self.use_gpu,
                update_image=self.update_image,
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


class EngineStatusSignals(QObject):
    finished = pyqtSignal(dict)


class EngineStatusWorker(QRunnable):
    """ODM.odm_engine_status() (Docker, Docker Hub, a GPU test container: a few
    seconds) outside the GUI thread."""

    def __init__(self):
        super().__init__()
        self.signals = EngineStatusSignals()

    def run(self) -> None:
        try:
            status = ODM.odm_engine_status()
        except Exception as error:          # a help, never a blocker
            status = {"docker": None, "docker_error": str(error), "gpu": False, "gpu_reason": str(error)}
        self.signals.finished.emit(status)


def _day(timestamp: Optional[str]) -> str:
    """2026-08-21T13:37:27Z -> 2026-08-21."""
    return (timestamp or "")[:10] or "unknown date"


ALL_IMAGES_DT = 6.0     # "All the aligned images": the widest tolerance, that of Step 4


class ODMSelectionDialog(QDialog):
    """Collect temporal and density criteria for an ODM mapping run.

    Default: best mapping by image overlap, with the overlap chosen in Step 2 /
    Step 4 (FlightAnalytics/best_mapping.json). Applied to images that Step 4
    already selected the same way, it keeps them all."""

    check_engine = True     # the background check of OpenDroneMap (False in the tests)

    def __init__(self, parent=None, mission_folder: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("Build the map – image selection")
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(480)
        # the settings of the last run (the main window map previews them)
        settings = (ODM.selection_settings(Path(mission_folder)) if mission_folder
                    else {"dt_tolerance_s": 0.5, "sample_every": 3, "overlap": best_mapping.DEFAULT_OVERLAP})

        root = QVBoxLayout(self)
        body = QHBoxLayout()              # the choices on the left, the map of the selection on the right
        root.addLayout(body)
        layout = QVBoxLayout()
        body.addLayout(layout)
        criteria = QFormLayout()
        self.dt_tolerance = QDoubleSpinBox()
        self.dt_tolerance.setRange(0.05, 6.0)
        self.dt_tolerance.setSingleStep(0.05)
        self.dt_tolerance.setDecimals(2)
        self.dt_tolerance.setValue(settings["dt_tolerance_s"])
        self.dt_tolerance.setSuffix(" s")
        criteria.addRow("Maximum |dt| (NIR rank 1):", self.dt_tolerance)
        layout.addLayout(criteria)
        # visible only mission: no infrared, every image is synchronised
        self.visible_only = bool(mission_folder) and mission_type.is_visible(Path(mission_folder))
        criteria.setRowVisible(self.dt_tolerance, not self.visible_only)

        density_group = QGroupBox("Image density and overlap")
        density_layout = QVBoxLayout(density_group)
        self.overlap_radio = QRadioButton("Best mapping: select by image overlap (recommended)")
        self.sample_radio = QRadioButton("Select one image every n eligible images")
        self.all_radio = QRadioButton(
            f"All the {'developed' if self.visible_only else 'aligned'} images (every point of the review not flagged)")
        self.all_radio.setToolTip(
            "Map every image Step 4 aligned and the review did not flag, whatever its time difference "
            "and the overlap: the most images, the longest mapping.")
        self.overlap_radio.setToolTip(
            "Keep the images whose ground footprints overlap by the chosen amount: the images the map "
            "needs. On images already selected in Step 4, all of them are kept.")
        self.sample_radio.setToolTip("Keep one eligible image every n: less overlap, faster mapping.")
        for radio in (self.sample_radio, self.overlap_radio, self.all_radio):
            Help.attach_help(radio, "btn:step6_selection", radio.toolTip(), parent=self)
        self.selection_group = QButtonGroup(self)
        self.selection_group.setExclusive(True)
        self.selection_group.addButton(self.overlap_radio)
        self.selection_group.addButton(self.sample_radio)
        self.selection_group.addButton(self.all_radio)

        density_layout.addWidget(self.overlap_radio)
        self.overlap = QSpinBox()
        self.overlap.setRange(round(best_mapping.MIN_OVERLAP * 100), round(best_mapping.MAX_OVERLAP * 100))
        self.overlap.setSingleStep(5)
        self.overlap.setSuffix(" %")
        self.overlap.setValue(round((settings["overlap"] if settings["overlap"] is not None
                                     else best_mapping.load_choice(Path(mission_folder))["overlap"]
                                     if mission_folder else best_mapping.DEFAULT_OVERLAP) * 100))
        overlap_form = QFormLayout()
        overlap_form.addRow("Overlap between successive images:", self.overlap)
        density_layout.addLayout(overlap_form)

        density_layout.addWidget(self.sample_radio)
        self.sample_every = QSpinBox()
        self.sample_every.setRange(1, 4)
        self.sample_every.setValue(settings["sample_every"])
        sample_row = QFormLayout()
        sample_row.addRow("One image every:", self.sample_every)
        density_layout.addLayout(sample_row)
        density_layout.addWidget(self.all_radio)
        layout.addWidget(density_group)
        layout.addWidget(self._build_engine_group(mission_folder))

        note = QLabel("OpenDroneMap runs in Docker: the map can take a long time and use several "
                      "gigabytes of memory and disk space. The images are hard-linked, not copied, when "
                      "the disk allows it.")
        note.setWordWrap(True)
        note.setStyleSheet(MESSAGE_STYLE)
        layout.addWidget(note)
        if mission_folder and ODM.previous_mapping_details(Path(mission_folder) / ODM.ODM_PROJECT_NAME):
            built = (Path(mission_folder) / ODM.ODM_PROJECT_NAME / ODM.ODM_RESULTS_FOLDER
                     / "odm_orthophoto.tif").is_file()
            kept = QLabel(f"{'A map is already built' if built else 'A previous run did not finish'}: "
                          f"it is kept, renamed {ODM.ODM_PROJECT_NAME}_<date of its run>, "
                          "and the new one is built in its place (the previous one comes back if the new "
                          "one fails).")
            kept.setWordWrap(True)
            kept.setStyleSheet(MESSAGE_STYLE)
            layout.addWidget(kept)
            self.previous_map_note = kept
        layout.addStretch()
        self.map_model = None
        self.map_view = self._build_map(Path(mission_folder)) if mission_folder else None
        if self.map_view is not None:
            right = QVBoxLayout()
            right.addWidget(self.map_view, stretch=1)
            self.map_count = QLabel("")
            self.map_count.setWordWrap(True)
            self.map_count.setStyleSheet(MESSAGE_STYLE)
            right.addWidget(self.map_count)
            body.addLayout(right, stretch=1)
            self.setMinimumWidth(900)
            Look.fit_to_screen(self, parent, max_w=1150, max_h=680)
        root.addLayout(launch_buttons(
            self, "Build the map",
            "Start OpenDroneMap with these images; the terrain model and the contour lines follow.",
            "btn:step6_selection"))

        every_image = (settings["overlap"] is None and settings["sample_every"] == 1
                       and settings["dt_tolerance_s"] >= ALL_IMAGES_DT)
        (self.all_radio if every_image else self.overlap_radio if settings["overlap"] is not None
         else self.sample_radio).setChecked(True)
        if every_image:
            self.dt_tolerance.setValue(0.5)          # what the other choices start from
        for radio in (self.sample_radio, self.all_radio):
            radio.toggled.connect(self._update_selection_controls)
        self._update_selection_controls()
        if self.map_view is not None:
            # the selection drawn again once the values stop changing (spin box held down)
            self._map_timer = QTimer(self)
            self._map_timer.setSingleShot(True)
            self._map_timer.setInterval(150)
            self._map_timer.timeout.connect(self.update_map)
            for spin in (self.dt_tolerance, self.overlap, self.sample_every):
                spin.valueChanged.connect(self._map_timer.start)
            self.selection_group.buttonToggled.connect(lambda *_: self._map_timer.start())
            self.update_map()

    # ---- OpenDroneMap: installed version, a newer one, the GPU
    def _build_engine_group(self, mission_folder) -> QGroupBox:
        """Version and GPU, filled in by a background check (Docker, Internet)."""
        group = QGroupBox("OpenDroneMap")
        engine_layout = QVBoxLayout(group)
        self.engine_status_label = QLabel("Checking the installed OpenDroneMap, a newer version and the GPU…")
        self.engine_status_label.setWordWrap(True)
        self.engine_status_label.setStyleSheet(MESSAGE_STYLE)
        engine_layout.addWidget(self.engine_status_label)
        self.update_check = QCheckBox("Download the newer version before the map")
        self.update_check.setToolTip(
            "docker pull the newest OpenDroneMap image before the map (a few hundred MB to a few GB). "
            "A newer version can give a slightly different map; the previous one is not kept.")
        self.update_check.setVisible(False)
        engine_layout.addWidget(self.update_check)
        self.gpu_check = QCheckBox("Use the NVIDIA GPU (faster image matching)")
        self.gpu_check.setToolTip("Checking whether Docker can use an NVIDIA GPU…")
        self.gpu_check.setEnabled(False)
        engine_layout.addWidget(self.gpu_check)
        for widget in (self.update_check, self.gpu_check):
            Help.attach_help(widget, "btn:step6_selection", widget.toolTip(), parent=self)
        self.engine_status: Optional[dict] = None
        self.gpu_check.toggled.connect(self._show_engine_status)
        if mission_folder and self.check_engine:
            self._engine_worker = EngineStatusWorker()
            self._engine_worker.signals.finished.connect(self._on_engine_status)
            QThreadPool.globalInstance().start(self._engine_worker)
        return group

    def _on_engine_status(self, status: dict) -> None:
        self.engine_status = status
        if status.get("gpu"):
            self.gpu_check.setEnabled(True)
            self.gpu_check.setChecked(True)
        self.gpu_check.setToolTip(
            "OpenDroneMap's GPU version (opendronemap/odm:gpu) detects and matches the image "
            f"features on the graphics card.\n{status.get('gpu_reason', '')}".rstrip()
            + "\n(F1: help on this button)")
        self._show_engine_status()

    def _show_engine_status(self) -> None:
        """The text of the check, for the image used (GPU or CPU)."""
        status = self.engine_status
        if status is None:
            return
        if not status.get("docker"):
            self.engine_status_label.setText(
                "Docker is not running: OpenDroneMap is checked (and downloaded if needed) "
                "when the map starts.")
            return
        gpu = self.gpu_check.isChecked()
        local, remote, update = ((status.get("local_gpu"), status.get("remote_gpu"), status.get("update_gpu"))
                                 if gpu else (status.get("local"), status.get("remote"), status.get("update")))
        lines = []
        if local is None:
            lines.append(f"OpenDroneMap{' (GPU version)' if gpu else ''} is not downloaded yet: "
                         "it is downloaded when the map starts (Internet needed, "
                         f"{'about 3 GB' if gpu else 'about 600 MB'}).")
        else:
            lines.append(f"Installed: OpenDroneMap {local.get('version') or '(version unknown)'}"
                         f"{' GPU' if gpu else ''}, image of {_day(local.get('created'))}.")
            if update:
                newer = remote.get("version") if remote else None
                lines.append(f"A newer version is available{f' (OpenDroneMap {newer})' if newer else ''}, "
                             f"published {_day(remote.get('published') if remote else None)}.")
            elif remote is None:
                lines.append("The newest version could not be checked (no Internet?).")
            else:
                lines.append("It is the newest version.")
        if not status.get("gpu"):
            reason = (status.get("gpu_reason") or "not checked").splitlines()
            lines.append(f"GPU not used: {reason[0]}"
                         + (" (details: tooltip of the GPU box)." if len(reason) > 1 else "."))
        self.engine_status_label.setText("\n".join(lines))
        self.update_check.setVisible(bool(update))
        if not update:
            self.update_check.setChecked(False)

    def selected_use_gpu(self) -> bool:
        return self.gpu_check.isEnabled() and self.gpu_check.isChecked()

    def selected_update_image(self) -> bool:
        return not self.update_check.isHidden() and self.update_check.isChecked()

    def engine_description(self) -> str:
        """OpenDroneMap choices in words (log)."""
        return (("GPU" if self.selected_use_gpu() else "CPU")
                + (", updated to the newest version first" if self.selected_update_image() else ""))

    # ---- map: the flight, the images selected and their footprints, live
    def _build_map(self, mission: Path):
        """Map of the shoot points (None without positions): a help, never a blocker."""
        try:
            import IRD_Interactive_map as Map
            from PyQt6.QtGui import QColor
            self.mission_folder = mission
            self._selected: set = set()
            self._eligible: set = set()
            kept, eligible, other = QColor(Look.SURVEY), QColor("#6B7785"), QColor("#C5CFDA")

            def color_of(number):
                return kept if number in self._selected else eligible if number in self._eligible else other
            model = Map.map_model_for(mission, color_of=color_of, with_ortho=False,
                                      shoot_points_only=True, parent=self)
            if model is None or len(model.points) < 2:
                return None
            model.minor = lambda i: model.numbers[i] not in self._eligible
            view = Map.FlightMapView(model, compact=True)
        except Exception as error:
            print(f"Step 6 selection map unavailable: {error}")
            return None
        self.map_model = model
        view.setMinimumSize(320, 300)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.setToolTip(
            f"The flight: in green the images selected for the map and their footprints (their overlap "
            f"shows), in grey the {'developed' if self.visible_only else 'aligned'} images left out by "
            "the selection, small dots for the others.\n"
            "Wheel to zoom, drag to pan, double-click to see the whole flight.")
        view.hovered.connect(model.set_hover)
        view.picked.connect(model.set_current)
        return view

    def selection_numbers(self):
        """(selected, eligible) image numbers with the current choices (None: unknown)."""
        def numbers(selection):
            out = set()
            for _, vis, _, _ in selection["sampled_pairs"]:
                digits = "".join(c for c in Path(str(vis.get("FileName", ""))).stem if c.isdigit())
                if digits:
                    out.add(int(digits))
            return out
        try:
            dt = self.selected_dt_tolerance()
            selected = numbers(ODM.select_mapping_pairs(self.mission_folder, dt, self.selected_sample_every(),
                                                        self.selected_overlap()))
            eligible = numbers(ODM.select_mapping_pairs(self.mission_folder, dt, 1, None))
        except (ODM.ODMMappingError, OSError, ValueError, TypeError, KeyError) as error:
            print(f"Step 6 selection not computed: {error}")
            return None
        return selected, eligible

    def update_map(self) -> None:
        if self.map_model is None:
            return
        found = self.selection_numbers()
        if found is None:
            self._selected, self._eligible = set(), set()
            self.map_model.set_selection([])
            self.map_count.setText("The selection cannot be computed yet (Step 4 first).")
            return
        self._selected, self._eligible = found
        indices = (self.map_model.index_of(n) for n in sorted(self._selected))
        self.map_model.set_selection([i for i in indices if i is not None])
        done = "developed" if self.visible_only else "aligned"
        self.map_count.setText(
            f"{len(self._selected)} images selected for the map, of {len(self._eligible)} {done} "
            + ("and not flagged." if self.visible_only else
               f"within |dt| ≤ {self.selected_dt_tolerance():.2f} s and not flagged."))

    def _update_selection_controls(self) -> None:
        """Enable only the controls of the selected criterion."""
        every_image = self.all_radio.isChecked()
        self.dt_tolerance.setEnabled(not every_image)
        self.sample_every.setEnabled(self.sample_radio.isChecked())
        self.overlap.setEnabled(self.overlap_radio.isChecked())

    def selected_overlap(self) -> Optional[float]:
        """Footprint overlap (0..1) of the best mapping, None otherwise."""
        return self.overlap.value() / 100.0 if self.overlap_radio.isChecked() else None

    def selected_dt_tolerance(self) -> float:
        """Every image: Step 4 aligns only pairs within 6 s, so all of them pass."""
        return ALL_IMAGES_DT if self.all_radio.isChecked() else self.dt_tolerance.value()

    def selected_sample_every(self) -> int:
        return 1 if self.all_radio.isChecked() else self.sample_every.value()

    def short_description(self) -> str:
        """The selection in a few words (under the stage)."""
        if self.all_radio.isChecked():
            return f"all the {'developed' if self.visible_only else 'aligned'} images"
        overlap = self.selected_overlap()
        return f"overlap {overlap:.0%}" if overlap is not None else f"1 image in {self.sample_every.value()}"

    def description(self) -> str:
        """The selection in words (confirmation and log)."""
        if self.all_radio.isChecked():
            return (f"all the {'developed' if self.visible_only else 'aligned'} images not flagged "
                    "(no time tolerance, no thinning)")
        overlap = self.selected_overlap()
        rule = (f"best mapping, {overlap:.0%} overlap between successive images" if overlap is not None
                else f"one image every {self.sample_every.value()} eligible images")
        return rule if self.visible_only else f"|dt| <= {self.dt_tolerance.value():.2f} s; {rule}"


def launch_buttons(dialog: QDialog, action: str, action_tip: str, help_label: str) -> QHBoxLayout:
    """Footer of a window that starts a computation: ? on the left; Cancel, then
    the action (primary, default) on the right."""
    row = QHBoxLayout()
    dialog.btn_help = QPushButton("?")
    dialog.btn_help.setFixedWidth(36)
    dialog.btn_help.setStyleSheet(SECONDARY_STYLE)
    dialog.btn_help.clicked.connect(lambda: Help.show_help(help_label, parent=dialog))
    row.addWidget(dialog.btn_help)
    row.addStretch()
    dialog.btn_cancel = QPushButton("Cancel")
    dialog.btn_cancel.setStyleSheet(SECONDARY_STYLE)
    dialog.btn_cancel.clicked.connect(dialog.reject)
    row.addWidget(dialog.btn_cancel)
    dialog.btn_start = QPushButton(action)
    dialog.btn_start.setStyleSheet(PRIMARY_STYLE)
    dialog.btn_start.setDefault(True)
    dialog.btn_start.clicked.connect(dialog.accept)
    row.addWidget(dialog.btn_start)
    for widget, tip in ((dialog.btn_help, "Open the manual."), (dialog.btn_cancel, "Close; nothing starts."),
                        (dialog.btn_start, action_tip)):
        Help.attach_help(widget, help_label, tip, parent=dialog)
    return row


def georef_message(visible_only: bool) -> str:
    """What the image selection of Georeference images accepts, by mission type."""
    if visible_only:
        return ("Select one or more drone images (DJI DNG, e.g. AerialPhotography/VIS_0121.DNG).\n"
                "A visible only mission georeferences the DNG only.")
    return ("Select one or more images, all of the same type:\n"
            "    - drone images: DJI DNG (e.g. VIS_0121.DNG)\n"
            "    - multispectral images: groups of four TIFF\n"
            "      e.g. IRD_0121_1.tif, IRD_0121_2.tif, IRD_0121_3.tif, IRD_0121_4.tif\n"
            "      (ImgIRdrone/imgMultispectral): select all four.")


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
        self.setWindowTitle("Terrain model and contour lines")
        self.setStyleSheet(DIALOG_STYLE)
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
        note = QLabel("Altitudes are requested from the IGN API (OpenTopoData as fallback). "
                      "A smaller step means many more requests.")
        note.setWordWrap(True)
        note.setStyleSheet(MESSAGE_STYLE)
        layout.addWidget(note)
        layout.addLayout(launch_buttons(
            self, "Build", "Build the terrain model and the contour lines with this grid step.",
            "btn:step6_dtm"))


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

    Phase 6 of the processing pipeline:
          - Post-processing
    """

    data_signal_to_main = pyqtSignal(bool)
    continue_requested = pyqtSignal()     # "Continue with archiving": the main window opens Step 7
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
        self.setWindowTitle(Look.step_window_title(6, STEP_NAME, self.folderMissionPath))
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumSize(600, 480)
        Look.fit_to_screen(self, parent, max_w=900, max_h=860)

        self.odm_worker: Optional[ODMRunWorker] = None
        self.odm_preview_worker: Optional[ODMPreviewWorker] = None
        self.dtm_worker: Optional[DtmWorker] = None
        self._init_gui()
        self._connect_signals()
        self.georef_results: List[str] = []
        self.odm_dt_tolerance_s = 0.5
        self.odm_sample_every = 3
        self.odm_overlap: Optional[float] = None
        self.odm_use_gpu = False
        self.odm_update_image = False

        # Connect the logger signal to the GUI log window.
        self.log_signal.connect(self._log)

        # Connect the image signal to the image display method.
        self.image_signal.connect(self._display_image)

        # Forward GeoRef logger messages to this dialog.
        self._log_callback = self.log_signal.emit
        GeoRef.logger.log_callback = self._log_callback

        self._show_previous_result()

    # ------------------------------------------------------------------
    # User Interface
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        """Same frame as Step 3: header, stages, log, actions, progress, preview, footer."""
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(Look.step_header(6, STEP_NAME, self.folderMissionPath))

        # The map is built in stages, left to right (Georeference images is a separate tool)
        self.stages = Look.StageTracker(["Image selection", "Orthophoto (OpenDroneMap)",
                                         "Terrain model and contours"])
        main_layout.addWidget(self.stages.widget())

        # Log display area (small: the preview is the main view)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(70)
        self.log_text.setMaximumHeight(120)
        main_layout.addWidget(self.log_text)

        # Actions: the map is the main one, the others are secondary
        btn_layout = QHBoxLayout()
        self.btn_run_Mapping = QPushButton("Build the map…")
        self.btn_run_Mapping.setStyleSheet(PRIMARY_STYLE)
        btn_layout.addWidget(self.btn_run_Mapping)
        self.btn_run_DTM = QPushButton("Terrain model and contours…")
        self.btn_run_DTM.setStyleSheet(SECONDARY_STYLE)
        btn_layout.addWidget(self.btn_run_DTM)
        self.btn_run_GeoRef = QPushButton("Georeference images…")
        self.btn_run_GeoRef.setStyleSheet(SECONDARY_STYLE)
        btn_layout.addWidget(self.btn_run_GeoRef)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # Progress bar label (bold)
        self.progress_label = QLabel("Ready")
        self.progress_label.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Image preview zone
        self.image_preview_label = QLabel(PREVIEW_IDLE_TEXT)
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumHeight(250)
        self.image_preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_preview_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; color: #6B7785; }"
        )
        main_layout.addWidget(self.image_preview_label, stretch=1)

        # Footer: the manual (?) on the left, Close always at the bottom right
        close_layout = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(36)
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.clicked.connect(lambda: Help.show_help("ch:step6", parent=self))
        close_layout.addWidget(self.btn_help)
        close_layout.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(SECONDARY_STYLE)
        close_layout.addWidget(self.btn_close)
        self.btn_continue = Look.continue_button(
            "archiving", "Close this window and open Step 7: it shows what archiving frees; "
                         "nothing is deleted until you confirm there.")
        self.btn_continue.clicked.connect(self._continue_now)
        self.btn_continue.hide()               # once the map is built
        close_layout.addWidget(self.btn_continue)

        for widget, label, tip in (
            (self.btn_run_GeoRef, "btn:step6_georef",
             "Choose drone DNG images and georeference and orthorectify each one." if self._visible_only() else
             "Choose images (drone DNG, or IRD_XXXX_1..4.tif groups) and georeference and orthorectify each one."),
            (self.btn_run_Mapping, "btn:step6_mapping",
             f"Choose the images, then assemble them into one {3 if self._visible_only() else 4}-band orthophoto "
             "with OpenDroneMap (Docker). "
             "The terrain model and the contour lines follow."),
            (self.btn_run_DTM, "btn:step6_dtm",
             "Build the terrain model and the contour lines over the orthophoto again, with another "
             "grid step (IGN altitudes, internet)."),
            (self.btn_close, "btn:step6_close", "Close this window."),
            (self.btn_help, "ch:step6", "Open the manual at Step 6."),
            (self.btn_continue, "btn:step6_continue", self.btn_continue.toolTip()),
        ):
            Help.attach_help(widget, label, tip, parent=self)

        main_layout.addLayout(close_layout)

    def _visible_only(self) -> bool:
        return mission_type.is_visible(Path(self.folderMissionPath))

    def _orthophoto_path(self) -> Path:
        return Path(self.folderMissionPath) / "mapping_MULTI" / "mapping_result" / "odm_orthophoto.tif"

    def _show_previous_result(self) -> None:
        """Map built earlier: the stages are done and the orthophoto is shown (as Step 3 shows its plot)."""
        orthophoto = self._orthophoto_path()
        if not orthophoto.is_file():
            self.btn_run_DTM.setEnabled(False)      # available once the map is built
            self.progress_label.setText("Ready: start with Build the map.")
            return
        self.stages.set(0, Look.STAGE_DONE, "")
        self.stages.set(1, Look.STAGE_DONE, "mapping_result")
        self.btn_continue.show()
        if (orthophoto.parent / "ortho_dtm.tif").is_file():
            self.stages.set(2, Look.STAGE_DONE, "")
        self.progress_label.setText("Map built earlier: the orthophoto is shown below.")
        self._log(f"Orthophoto: {orthophoto}")
        self._set_preview_text("Loading orthophoto preview...")
        self._start_ODM_preview(orthophoto)

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

    def _continue_now(self) -> None:
        """Step 7 opens once this window is closed (it refuses while a Step 6 window is open)."""
        if self.odm_worker is None and self.dtm_worker is None and self.close():
            self.data_signal_to_main.emit(True)
            self.continue_requested.emit()

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
        Step 6.1 – Run Georeferencing.
        """
        try:
            self.progress_bar.setValue(0)
            QMessageBox.information(self, "Georeference images", georef_message(self._visible_only()))
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
        self.odm_dt_tolerance_s = selection_dialog.selected_dt_tolerance()
        self.odm_sample_every = selection_dialog.selected_sample_every()
        self.odm_overlap = selection_dialog.selected_overlap()
        self.odm_use_gpu = selection_dialog.selected_use_gpu()
        self.odm_update_image = selection_dialog.selected_update_image()
        self._log(f"Image selection: {selection_dialog.description()}.")
        self._log(f"OpenDroneMap: {selection_dialog.engine_description()}.")
        self.stages.set(0, Look.STAGE_DONE, selection_dialog.short_description())
        self.stages.set(2, Look.STAGE_PENDING, "")

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
            use_gpu=self.odm_use_gpu,
            update_image=self.odm_update_image,
        )
        worker.signals.log.connect(self._log)
        worker.signals.stage.connect(self._on_ODM_stage)
        worker.signals.finished.connect(self._on_ODM_finished)
        worker.signals.docker_unavailable.connect(self._on_ODM_docker_unavailable)
        worker.signals.error.connect(self._on_ODM_error)
        self.odm_worker = worker
        self.btn_run_GeoRef.setEnabled(False)
        self.btn_run_Mapping.setEnabled(False)
        self.btn_run_DTM.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.btn_continue.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("ODM – starting")
        self.stages.set(1, Look.STAGE_RUNNING, "starting")
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
            self.stages.set(1, Look.STAGE_FAILED, "Docker unavailable")
            self.progress_label.setText("ODM cancelled: Docker is unavailable.")
            self._set_preview_text(PREVIEW_IDLE_TEXT)

    def _set_preview_text(self, text: str) -> None:
        """Replace the preview image by a message (what is running, what will come)."""
        self.image_preview_label.setPixmap(QPixmap())
        self.image_preview_label.setText(text)
        self.image_preview_label.repaint()

    def _on_ODM_stage(self, stage: str) -> None:
        self.progress_label.setText(f"ODM – {stage}")
        self.stages.detail(1, stage)

    def _finish_ODM_ui(self) -> None:
        """Release the worker and re-enable the buttons and the progress bar."""
        self.odm_worker = None
        self.btn_run_GeoRef.setEnabled(True)
        self.btn_run_Mapping.setEnabled(True)
        self.btn_run_DTM.setEnabled(self._orthophoto_path().is_file())
        self.btn_close.setEnabled(True)
        self.btn_continue.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _on_ODM_finished(self, result: dict) -> None:
        """Display the orthophoto preview, then chain the DTM and contour lines."""
        self._finish_ODM_ui()
        orthophoto = result["orthophoto"]
        completion_message = f"Orthophoto:\n{orthophoto['path']}"
        self._log(f"ODM completed successfully: {orthophoto['path']}")
        mark_step_done(self.folderMissionPath, 6)  # Step 6 is done once the ODM mapping is
        self.stages.set(1, Look.STAGE_DONE, "mapping_result")
        self.btn_continue.show()
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
            self.btn_continue,
        ):
            button.setEnabled(enabled)

    def on_run_DTM(self) -> None:
        """Rebuild the DTM and contour lines of the archived ODM orthophoto."""
        if self.dtm_worker is not None or self.odm_worker is not None:
            return
        orthophoto = self._orthophoto_path()
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
        self.stages.set(2, Look.STAGE_RUNNING, f"grid step {step:g} m")
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
        self.stages.set(2, Look.STAGE_DONE, "")
        notifier.changed.emit(Path(self.folderMissionPath))   # main window: footprints on the terrain model
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
        self.stages.set(2, Look.STAGE_FAILED, "see the log")
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
        self.stages.set(1, Look.STAGE_FAILED, "see the log")
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
