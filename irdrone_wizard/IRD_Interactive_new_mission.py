# -*- coding: utf-8 -*-
"""
Step 1 - New mission, in one window and three pages:

    1 Images   the visible (drone, DNG) and infrared (SJCam, RAW) images are
               found on the SD cards; the first visible image is the take-off
    2 Mission  date, time and place come from the take-off image (address from
               OpenStreetMap); the user adds a description, the pilot and checks
               the cameras (remembered for the next mission)
    3 Copy     the mission folder is created, the images copied and converted,
               their EXIF read; "Flight timeline" goes on with Step 2

The classic two-window form stays available ("Classic form...").
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6 import QtCore
from PyQt6.QtCore import QSettings, QStorageInfo, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
                             QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))
import mission_setup as MS  # noqa: E402
import IRD_Interactive_look as Look  # noqa: E402

SETTINGS = ("IRdrone", "IRD_Interactive")
FORM_KEY = "new_mission/"
PAGES = ["Images", "Mission", "Copy"]
COPY_STAGES = ["Copy visible", "Read visible EXIF", "Convert infrared", "Read infrared EXIF", "Ground altitude"]


def mounted_volumes():
    """(root, name) of the mounted volumes."""
    out = []
    for v in QStorageInfo.mountedVolumes():
        if v.isValid() and v.isReady():
            out.append((v.rootPath(), v.displayName() or v.rootPath()))
    return out


def load_form_settings() -> dict:
    s = QSettings(*SETTINGS)
    return MS.form_from_settings({k: s.value(FORM_KEY + k) for k in MS.DEFAULT_FORM})


def save_form_settings(form: dict) -> None:
    s = QSettings(*SETTINGS)
    for k in MS.DEFAULT_FORM:
        if k != "description" and k in form:
            s.setValue(FORM_KEY + k, form[k])


# ---------------------------------------------------------------------------
#  Background work
# ---------------------------------------------------------------------------
class LocateThread(QThread):
    """Ground altitude and address of the take-off (network)."""
    located = pyqtSignal(dict)

    def __init__(self, light):
        super().__init__()
        self.light = dict(light)

    def run(self):
        self.located.emit(MS.locate(self.light))


class MissionCopy(QtCore.QObject):
    """The Step 1 workers, one after the other (copy, EXIF, conversion, altitude)."""
    stage = pyqtSignal(int, str, str)       # index, state, detail
    progress = pyqtSignal(int, str)         # percent, text
    finished = pyqtSignal(bool, str)        # ok, message

    def __init__(self, params: dict, vis_folder: Path, nir_folder: Path, parent=None):
        super().__init__(parent)
        self.params = params
        self.vis_in, self.nir_in = Path(vis_folder), Path(nir_folder)
        base = Path(params["File path mission"])
        self.vis_out = base / "AerialPhotography" / "VIS"
        self.nir_out = base / "AerialPhotography" / "NIR"
        self.analytics = base / "FlightAnalytics"
        self._threads = []
        self._index = -1
        self.failed = False

    def start(self):
        self._index = -1
        self._next()

    def _next(self, *_):
        if self.failed:
            return
        if self._index >= 0:
            self.stage.emit(self._index, Look.STAGE_DONE, "")
        self._index += 1
        if self._index >= len(COPY_STAGES):
            self.finished.emit(True, "Mission created.")
            return
        self.stage.emit(self._index, Look.STAGE_RUNNING, "")
        self.progress.emit(0, COPY_STAGES[self._index] + "…")
        import IRD_Interactive_workers as Worker
        k = self._index
        if k == 0:
            worker = Worker.Transfer_VIS(self.vis_in, self.vis_out)
        elif k == 1:
            worker = Worker.CreateExif(str(self.vis_out), "EXIF VIS", spectral_band="VIS")
        elif k == 2:
            worker = Worker.Transfer_NIR(self.nir_in, self.nir_out)
        elif k == 3:
            worker = Worker.CreateExif(str(self.nir_out), "EXIF NIR", spectral_band="NIR")
        else:
            worker = Worker.Alti_GPS(self.vis_out)
            worker.plot_data.connect(self._save_profile)
        self._run(worker)

    def _run(self, worker):
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda pct: self.progress.emit(int(pct), f"{COPY_STAGES[self._index]}… {pct}%"))
        worker.error.connect(self._on_error)
        worker.error.connect(thread.quit)
        worker.finished.connect(thread.quit)
        # queued: the next worker starts from the GUI thread
        worker.finished.connect(lambda *_: QtCore.QTimer.singleShot(0, self._next))
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _on_error(self, message):
        self.failed = True
        self.stage.emit(self._index, Look.STAGE_FAILED, "")
        self.finished.emit(False, f"{COPY_STAGES[self._index]}: {message}")

    def _save_profile(self, distance, ground, drone):
        """Altitude profile of the flight (FlightAnalytics/fly_vertical_profil.png), as the classic Step 1."""
        try:
            import matplotlib
            matplotlib.use("Agg", force=False)
            from matplotlib.figure import Figure
            fig = Figure(figsize=(12, 5))
            ax = fig.add_subplot(111)
            ax.plot(distance, drone, label="Drone")
            ax.plot(distance, ground, label="Ground")
            ax.set_xlabel("Cumulated distance (m)")
            ax.set_ylabel("Normalised altitude (m)")
            ax.set_title("Drone / ground altitude profile")
            ax.grid(True)
            ax.legend()
            fig.tight_layout()
            fig.savefig(self.analytics / "fly_vertical_profil.png", dpi=150)
        except Exception as e:  # cosmetic
            print(f"Altitude profile not saved: {e}")

    def running(self):
        return any(t.isRunning() for t, _ in self._threads if _alive(t))


def _alive(obj):
    try:
        obj.objectName()
        return True
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
#  Widgets
# ---------------------------------------------------------------------------
class SourceCard(QFrame):
    """One camera: where its images are, how many, a preview."""
    choose = pyqtSignal(str)        # band

    def __init__(self, band, title, subtitle, parent=None):
        super().__init__(parent)
        self.band = band
        self.setObjectName("card")
        self.setStyleSheet(Look.CARD_STYLE)
        color = Look.BLUE if band == "VIS" else Look.NIR_ACCENT
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        self.preview = QLabel()
        self.preview.setFixedSize(192, 144)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #E9EDF2; border-radius: 6px; color: #6B7785;")
        lay.addWidget(self.preview)
        text = QVBoxLayout()
        text.setSpacing(4)
        head = QLabel(title)
        head.setStyleSheet(f"color: {color.name()}; font-size: 12pt; font-weight: bold;")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color: #6B7785;")
        self.where = QLabel("Not found yet")
        self.where.setTextFormat(Qt.TextFormat.RichText)
        self.where.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setStyleSheet("color: #3E4C59;")
        self.extra = QLabel()
        self.extra.setTextFormat(Qt.TextFormat.RichText)
        self.extra.setStyleSheet("color: #6B7785;")
        self.extra.setOpenExternalLinks(False)
        text.addWidget(head)
        text.addWidget(sub)
        text.addSpacing(4)
        text.addWidget(self.where)
        text.addWidget(self.summary)
        text.addWidget(self.extra)
        text.addStretch(1)
        lay.addLayout(text, 1)
        self.btn = QPushButton("Choose folder…")
        self.btn.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn.clicked.connect(lambda: self.choose.emit(self.band))
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignTop)
        self.set_found(None)

    def set_found(self, summary: Optional[MS.FolderSummary], origin: str = ""):
        if summary is None or not summary.count:
            self.where.setText("<span style='color:#B03A2E'>No image yet.</span> Insert the SD card, "
                               "or choose the folder of the images.")
            self.summary.setText("")
            self.extra.setText("")
            self.preview.setPixmap(QPixmap())
            self.preview.setText("—")
            self.btn.setText("Choose folder…")
            return
        self.where.setText(f"<b>{origin}</b><br><span style='color:#6B7785'>{summary.folder}</span>"
                           if origin else f"<span style='color:#6B7785'>{summary.folder}</span>")
        self.summary.setText("✓ " + summary.describe())
        self.btn.setText("Change…")

    def set_preview(self, pix: Optional[QPixmap], placeholder=""):
        if pix is None or pix.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(placeholder)
            return
        self.preview.setText("")
        self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                          Qt.TransformationMode.SmoothTransformation)
                               .copy(0, 0, self.preview.width(), self.preview.height()))


# ---------------------------------------------------------------------------
#  Dialog
# ---------------------------------------------------------------------------
class NewMissionDialog(QDialog):
    """Step 1. `mission_created(params)` once the copy is done; `action` tells
    what to do when the window is closed: "timeline" (open Step 2), "classic"
    (open the classic form) or "close"."""

    mission_created = pyqtSignal(dict)

    def __init__(self, user_dir: Path, parent=None, scan=True):
        super().__init__(parent)
        self.user_dir = Path(user_dir)
        self.action = "close"
        self.vis: Optional[MS.FolderSummary] = None
        self.nir: Optional[MS.FolderSummary] = None
        self.takeoff: Optional[Path] = None
        self.light: Optional[dict] = None
        self.geo: Optional[dict] = None
        self.params: Optional[dict] = None
        self.copy: Optional[MissionCopy] = None
        self.locate_thread: Optional[LocateThread] = None
        self._copy_started = 0.0
        self.setWindowTitle("Step 1 – New mission")
        self.setStyleSheet(Look.DIALOG_STYLE + " QLineEdit { padding: 4px; "
                           "border: 1px solid #C5CFDA; border-radius: 4px; background: white; }")
        Look.fit_to_screen(self, parent, max_w=1100, max_h=780)
        self._build()
        self._go(0)
        if scan:
            QtCore.QTimer.singleShot(0, self.scan_cards)

    # ---- layout
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 12)
        outer.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("New mission")
        title.setStyleSheet(Look.TITLE_STYLE)
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet(Look.SUBTITLE_STYLE)
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(self.subtitle, 1)
        outer.addLayout(head)
        self.pages_bar = Look.StageTracker([f"{k + 1}  {name}" for k, name in enumerate(PAGES)])
        outer.addWidget(self.pages_bar.widget())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_images())
        self.stack.addWidget(self._page_mission())
        self.stack.addWidget(self._page_copy())
        outer.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_help.setFixedWidth(36)
        self.btn_help.clicked.connect(self._on_help)
        self.btn_classic = QPushButton("Classic form…")
        self.btn_classic.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_classic.setToolTip("Define the mission with the previous Step 1 windows "
                                    "(take-off image first, then the form).")
        self.btn_classic.clicked.connect(self._on_classic)
        self.btn_back = QPushButton("◀  Back")
        self.btn_back.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_next = QPushButton()
        self.btn_next.setStyleSheet(Look.PRIMARY_STYLE)
        self.btn_next.clicked.connect(self._on_next)
        foot.addWidget(self.btn_help)
        foot.addWidget(self.btn_classic)
        foot.addStretch(1)
        foot.addWidget(self.btn_back)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_next)
        outer.addLayout(foot)

    def _page_images(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.card_vis = SourceCard("VIS", "Visible images", "Drone camera · DNG")
        self.card_nir = SourceCard("NIR", "Infrared images", "SJCam camera · RAW")
        self.card_vis.choose.connect(self._choose_folder)
        self.card_nir.choose.connect(self._choose_folder)
        self.card_vis.extra.linkActivated.connect(lambda _: self._choose_takeoff())
        lay.addWidget(self.card_vis)
        lay.addWidget(self.card_nir)
        row = QHBoxLayout()
        self.clock_note = QLabel()
        self.clock_note.setStyleSheet(Look.MESSAGE_STYLE)
        self.clock_note.hide()
        self.btn_rescan = QPushButton("Look for SD cards again")
        self.btn_rescan.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_rescan.clicked.connect(self.scan_cards)
        row.addWidget(self.clock_note, 1)
        row.addStretch(0)
        row.addWidget(self.btn_rescan)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _page_mission(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        left = QFrame()
        left.setObjectName("card")
        left.setStyleSheet(Look.CARD_STYLE)
        left.setFixedWidth(360)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        self.takeoff_pix = QLabel()
        self.takeoff_pix.setFixedSize(336, 252)
        self.takeoff_pix.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.takeoff_pix.setStyleSheet("background: #E9EDF2; border-radius: 6px; color: #6B7785;")
        self.takeoff_info = QLabel()
        self.takeoff_info.setTextFormat(Qt.TextFormat.RichText)
        self.takeoff_info.setWordWrap(True)
        self.place_info = QLabel()
        self.place_info.setTextFormat(Qt.TextFormat.RichText)
        self.place_info.setWordWrap(True)
        self.place_info.setOpenExternalLinks(True)
        ll.addWidget(self.takeoff_pix)
        ll.addWidget(self.takeoff_info)
        ll.addWidget(self.place_info)
        ll.addStretch(1)
        lay.addWidget(left)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.folder_name = QLabel()
        self.folder_name.setStyleSheet("font-size: 13pt; font-weight: bold; color: #17365D;")
        self.folder_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_where = QLabel()
        self.folder_where.setStyleSheet("color: #6B7785;")
        self.folder_where.setWordWrap(True)
        right.addWidget(QLabel("Mission folder"))
        right.addWidget(self.folder_name)
        right.addWidget(self.folder_where)
        right.addSpacing(6)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setVerticalSpacing(8)
        saved = load_form_settings()
        self.f_location = QLineEdit()
        self.f_location.setPlaceholderText("Town or place (part of the folder name)")
        self.f_location.textChanged.connect(self._update_folder_name)
        self.f_description = QLineEdit()
        self.f_description.setPlaceholderText("e.g. Vineyard survey, plot 12")
        self.f_pilot = QLineEdit(str(saved["pilot"]))
        self.f_pilot_id = QLineEdit(str(saved["pilot_id"]))
        self.f_pilot_id.setPlaceholderText("Remote pilot registration number")
        form.addRow("Location", self.f_location)
        form.addRow("Description", self.f_description)
        form.addRow("Pilot", self.f_pilot)
        form.addRow("Pilot ID", self.f_pilot_id)
        right.addLayout(form)
        self.btn_cameras = QPushButton("▸  Cameras and filter")
        self.btn_cameras.setCheckable(True)
        self.btn_cameras.setStyleSheet("QPushButton { text-align: left; border: none; color: #17365D; "
                                       "font-weight: bold; padding: 6px 0; } ")
        self.btn_cameras.toggled.connect(self._toggle_cameras)
        right.addWidget(self.btn_cameras)
        self.cameras_box = QWidget()
        grid = QGridLayout(self.cameras_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        self.f_vis_camera = QLabel()
        self.f_vis_timelapse = self._spin(saved["vis_timelapse"], 1, 60, " s")
        self.f_vis_delta = self._dspin(saved["vis_deltatime"])
        self.f_nir_maker = QLineEdit(str(saved["nir_maker"]))
        self.f_nir_model = QLineEdit(str(saved["nir_model"]))
        self.f_nir_format = QLineEdit(str(saved["nir_format"]))
        self.f_nir_timelapse = self._spin(saved["nir_timelapse"], 1, 60, " s")
        self.f_nir_delta = self._dspin(saved["nir_deltatime"])
        self.f_filter_maker = QLineEdit(str(saved["filter_maker"]))
        self.f_filter_band = self._spin(saved["filter_band"], 300, 1200, " nm")
        rows = [("Visible camera", self.f_vis_camera, None),
                ("Visible interval · clock delta", self.f_vis_timelapse, self.f_vis_delta),
                ("Infrared camera", self.f_nir_maker, self.f_nir_model),
                ("Infrared format", self.f_nir_format, None),
                ("Infrared interval · clock delta", self.f_nir_timelapse, self.f_nir_delta),
                ("Filter maker · band", self.f_filter_maker, self.f_filter_band)]
        for r, (label, a, b) in enumerate(rows):
            lab = QLabel(label)
            lab.setStyleSheet("color: #6B7785;")
            grid.addWidget(lab, r, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(a, r, 1)
            if b is not None:
                grid.addWidget(b, r, 2)
        self.cameras_box.hide()
        right.addWidget(self.cameras_box)
        right.addStretch(1)
        self.disk_note = QLabel()
        self.disk_note.setWordWrap(True)
        self.disk_note.setStyleSheet("color: #6B7785;")
        right.addWidget(self.disk_note)
        lay.addLayout(right, 1)
        return page

    def _page_copy(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.copy_summary = QLabel()
        self.copy_summary.setTextFormat(Qt.TextFormat.RichText)
        self.copy_summary.setWordWrap(True)
        self.copy_summary.setObjectName("card")
        self.copy_summary.setStyleSheet("#card { background: white; border: 1px solid #DDE3EA; border-radius: 8px;"
                                        " padding: 10px 14px; }")
        lay.addWidget(self.copy_summary)
        self.copy_stages = Look.StageTracker(COPY_STAGES)
        lay.addWidget(self.copy_stages.widget())
        self.copy_text = QLabel("Waiting…")
        self.copy_text.setStyleSheet("font-weight: bold;")
        self.copy_bar = QProgressBar()
        self.copy_bar.setTextVisible(False)
        self.copy_bar.setFixedHeight(8)
        self.copy_bar.setStyleSheet(Look.PROGRESS_STYLE)
        lay.addWidget(self.copy_text)
        lay.addWidget(self.copy_bar)
        self.done_card = QFrame()
        self.done_card.setObjectName("done")
        self.done_card.setStyleSheet("#done { background: #EDF7EE; border: 1px solid #B9DDBB; border-radius: 8px; }")
        dl = QVBoxLayout(self.done_card)
        dl.setContentsMargins(16, 12, 16, 12)
        self.done_title = QLabel()
        self.done_title.setStyleSheet("font-size: 13pt; font-weight: bold; color: #2E7D32;")
        self.done_text = QLabel()
        self.done_text.setWordWrap(True)
        self.done_text.setTextFormat(Qt.TextFormat.RichText)
        self.done_text.setOpenExternalLinks(False)
        self.done_text.linkActivated.connect(self._open_folder)
        dl.addWidget(self.done_title)
        dl.addWidget(self.done_text)
        self.done_card.hide()
        lay.addWidget(self.done_card)
        lay.addStretch(1)
        return page

    @staticmethod
    def _spin(value, lo, hi, suffix=""):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(int(value))
        s.setSuffix(suffix)
        return s

    @staticmethod
    def _dspin(value):
        s = QDoubleSpinBox()
        s.setRange(-7200.0, 7200.0)
        s.setDecimals(2)
        s.setSuffix(" s")
        s.setValue(float(value))
        return s

    def _toggle_cameras(self, on):
        self.cameras_box.setVisible(on)
        self.btn_cameras.setText(("▾" if on else "▸") + "  Cameras and filter")

    # ---- navigation
    def _go(self, page):
        page = max(0, min(page, len(PAGES) - 1))
        self.stack.setCurrentIndex(page)
        for k in range(len(PAGES)):
            state = Look.STAGE_DONE if k < page else Look.STAGE_RUNNING if k == page else Look.STAGE_PENDING
            self.pages_bar.set(k, state)
        self.btn_back.setVisible(page == 1)
        self.btn_classic.setVisible(page == 0)
        self.btn_cancel.setVisible(page < 2)
        if page == 0:
            self.subtitle.setText("Insert the SD cards of the drone and of the infrared camera: "
                                  "the images are found automatically.")
            self.btn_next.setText("Next  ▶")
            self._check_page_images()
        elif page == 1:
            self.subtitle.setText("Date, time and place come from the first visible image. "
                                  "Add a description and check the pilot.")
            self.btn_next.setText("Create the mission and copy the images  ▶")
            self.btn_next.setEnabled(self.geo is not None)
            self._update_folder_name()
        else:
            self.subtitle.setText("Copying the images to the mission folder: it takes a few minutes.")
            self.btn_next.setText("Flight timeline  ▶")
            self.btn_next.setEnabled(False)

    def _on_next(self):
        page = self.stack.currentIndex()
        if page == 0:
            if self._prepare_mission_page():
                self._go(1)
        elif page == 1:
            self._start_copy()
        else:
            self.action = "timeline"
            self.accept()

    def _check_page_images(self):
        ok = bool(self.vis and self.vis.count and self.nir and self.nir.count and self.takeoff)
        if self.stack.currentIndex() == 0:
            self.btn_next.setEnabled(ok)
        gap = MS.clock_gap(self.vis, self.nir) if (self.vis and self.nir) else None
        if gap is not None and abs(gap) > 120:
            hours, rest = divmod(int(abs(gap)), 3600)
            text = (f"The infrared clock is {'ahead' if gap > 0 else 'behind'} by "
                    + (f"{hours} h {rest // 60:02d} min" if hours else f"{rest // 60} min")
                    + ". Nothing to do: Step 3 synchronises the cameras on the rotating target.")
            if abs(gap) > 2 * 86400:
                text = "⚠  The visible and infrared images are days apart: are they from the same flight?"
            self.clock_note.setText(text)
            self.clock_note.show()
        else:
            self.clock_note.hide()

    # ---- page 1: images
    def scan_cards(self):
        found = MS.find_card_images(mounted_volumes())
        for band in ("VIS", "NIR"):
            current = self.vis if band == "VIS" else self.nir
            if current is not None and current.count:
                continue   # chosen by the user: kept
            hit = next((c for c in found if c.band == band), None)
            if hit is not None:
                self._set_source(band, hit.summary, f"SD card “{hit.name}”")
        self.subtitle.setText("Insert the SD cards of the drone and of the infrared camera: "
                              "the images are found automatically." if not found else
                              "Images found on the SD card(s). Check them, then go on.")

    def _choose_folder(self, band):
        start = str((self.vis if band == "VIS" else self.nir).folder) if \
            (self.vis if band == "VIS" else self.nir) else str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Folder of the visible images (DNG)" if band == "VIS" else "Folder of the infrared images (RAW)",
            start)
        if not folder:
            return
        suffixes = MS.VIS_SUFFIXES if band == "VIS" else MS.NIR_SUFFIXES
        summary = MS.summarize(Path(folder), suffixes)
        if not summary.count:   # the user chose the card or DCIM: look below
            below = MS.image_folders(Path(folder), suffixes, depth=3)
            if below:
                summary = below[0]
        if not summary.count:
            QMessageBox.warning(self, "New mission",
                                f"No {'DNG' if band == 'VIS' else 'RAW'} image in this folder.")
            return
        self._set_source(band, summary, "")

    def _set_source(self, band, summary, origin):
        if band == "VIS":
            self.vis = summary
            self.card_vis.set_found(summary, origin)
            self._set_takeoff(MS.takeoff_image(summary))
        else:
            self.nir = summary
            self.card_nir.set_found(summary, origin)
            jpg = next((summary.folder / (f.stem + ext) for f in summary.files[:1]
                        for ext in (".JPG", ".jpg") if (summary.folder / (f.stem + ext)).is_file()), None)
            self.card_nir.set_preview(QPixmap(str(jpg)) if jpg else None, "RAW\n(no preview)")
        self._check_page_images()

    def _set_takeoff(self, path: Optional[Path]):
        self.takeoff = path
        self.light, self.geo = None, None
        if path is None:
            return
        self.card_vis.extra.setText(f"Take-off image: <b>{path.name}</b> · <a href='#'>change…</a>")
        pix = self._dng_preview(path)
        self.card_vis.set_preview(pix, "no preview")

    @staticmethod
    def _dng_preview(path) -> Optional[QPixmap]:
        try:
            import flight_timeline as FT
            img = FT.read_preview(Path(path), full_fallback=False)
            return Look.bgr_to_pixmap(img) if img is not None else None
        except Exception as e:
            print(f"No preview for {path}: {e}")
            return None

    def _choose_takeoff(self):
        if not self.vis:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Take-off image (drone still on the ground)",
                                              str(self.vis.folder), "Images (*.dng *.DNG)")
        if name:
            self._set_takeoff(Path(name))
            self._check_page_images()

    # ---- page 2: mission
    def _prepare_mission_page(self) -> bool:
        if self.light is None:
            try:
                self.light = MS.read_takeoff(self.takeoff)
            except Exception as e:
                QMessageBox.warning(self, "New mission", f"The take-off image cannot be read:\n{e}")
                return False
        when = MS.takeoff_datetime(self.light)
        pix = self.card_vis.preview.pixmap()
        big = self._dng_preview(self.takeoff)
        if big is not None:
            self.takeoff_pix.setPixmap(big.scaled(self.takeoff_pix.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        elif pix is not None:
            self.takeoff_pix.setPixmap(pix)
        lat, lon = float(self.light["GPS lat"]), float(self.light["GPS lon"])
        self.takeoff_info.setText(
            f"<b>{when:%d/%m/%Y · %H:%M}</b><br>"
            f"<span style='color:#6B7785'>Take-off image {self.takeoff.name} · "
            f"{self.light['Maker']} {self.light['Model']}</span>")
        maps = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=16/{lat:.6f}/{lon:.6f}"
        self._coords = (f"{abs(lat):.5f}° {self.light['GPS N-S']}, {abs(lon):.5f}° {self.light['GPS E-W']}"
                        f" · <a href='{maps}'>map</a>")
        self.f_vis_camera.setText(f"{self.light['Maker']} {self.light['Model']}")
        if self.geo is None:
            self.place_info.setText(f"📍 Locating the take-off…<br><span style='color:#6B7785'>{self._coords}</span>")
            self.locate_thread = LocateThread(self.light)
            self.locate_thread.located.connect(self._on_located)
            self.locate_thread.start()
        free = _free_bytes(self.user_dir)
        need = MS.copy_sizes(self.vis, self.nir)
        self.disk_note.setText(f"Copy: about {MS.human_size(need)}" +
                               (f" · {MS.human_size(free)} free on the disk" if free is not None else "") +
                               (" · ⚠ not enough space" if free is not None and free < need else ""))
        return True

    def _on_located(self, geo):
        self.geo = geo or {}
        MS.add_location(self.light, self.geo)
        if not self.f_location.text().strip():
            self.f_location.setText(self.light.get("Location", ""))
        bits = [self.geo.get(k) for k in ("lieu_dit", "ville", "dept", "pays") if self.geo.get(k)]
        ground = self.geo.get("z")
        self.place_info.setText(
            ("📍 <b>" + " · ".join(str(b) for b in bits) + "</b>" if bits else "📍 Address not found (offline?)")
            + f"<br><span style='color:#6B7785'>{self._coords}"
            + (f" · ground {ground:.0f} m" if isinstance(ground, (int, float)) and ground else "") + "</span>")
        if self.stack.currentIndex() == 1:
            self.btn_next.setEnabled(True)
        self._update_folder_name()

    def form_values(self) -> dict:
        return {
            "location": self.f_location.text(),
            "description": self.f_description.text(),
            "pilot": self.f_pilot.text(),
            "pilot_id": self.f_pilot_id.text(),
            "vis_timelapse": self.f_vis_timelapse.value(),
            "vis_deltatime": self.f_vis_delta.value(),
            "nir_maker": self.f_nir_maker.text(),
            "nir_model": self.f_nir_model.text(),
            "nir_format": self.f_nir_format.text(),
            "nir_timelapse": self.f_nir_timelapse.value(),
            "nir_deltatime": self.f_nir_delta.value(),
            "filter_maker": self.f_filter_maker.text(),
            "filter_band": self.f_filter_band.value(),
        }

    def _update_folder_name(self):
        if self.light is None:
            return
        name = MS.mission_folder_name(MS.takeoff_datetime(self.light), self.f_location.text())
        self.folder_name.setText(name)
        exists = (self.user_dir / name).exists()
        self.folder_where.setText(f"in {self.user_dir}" + ("  ·  already exists: its images are kept and completed"
                                                            if exists else ""))

    # ---- page 3: copy
    def _start_copy(self):
        form = self.form_values()
        try:
            self.params = MS.build_mission_parameters(self.light, form, self.user_dir)
        except (KeyError, ValueError) as e:
            QMessageBox.warning(self, "New mission", f"Incomplete mission information: {e}")
            return
        import IRD_Interactive_diskspace as Disk
        base = Path(self.params["File path mission"])
        base.parent.mkdir(parents=True, exist_ok=True)
        needed = MS.copy_sizes(self.vis, self.nir) + Disk.DISK_NEARLY_FULL_BYTES
        if not Disk.confirm_free_space(self, base.parent, needed, "Step 1 (copy of the images)"):
            return
        save_form_settings(form)
        try:
            from IRD_Interactive_utils import Prefrence_Screen
            icon_dir = Path(Prefrence_Screen().default_app_dir) / "Icon"
        except Exception:
            icon_dir = None
        try:
            MS.create_mission(self.params, icon_dir)
        except OSError as e:
            QMessageBox.critical(self, "New mission", f"The mission folder cannot be created:\n{e}")
            return
        self._go(2)
        self.copy_summary.setText(
            f"<span style='font-size:13pt; font-weight:bold; color:#17365D'>{base.name}</span><br>"
            f"<span style='color:#6B7785'>{base}</span><br><br>"
            f"<b style='color:#17365D'>Visible</b> {self.vis.count} images from {self.vis.folder}<br>"
            f"<b style='color:#B03A2E'>Infrared</b> {self.nir.count} images from {self.nir.folder}, "
            "converted from RAW to DNG<br><br>"
            "<span style='color:#6B7785'>The SD cards are only read. Keep them in until the copy is done.</span>")
        self._copy_started = time.time()
        self.copy = MissionCopy(self.params, self.vis.folder, self.nir.folder, self)
        self.copy.stage.connect(self.copy_stages.set)
        self.copy.progress.connect(self._on_copy_progress)
        self.copy.finished.connect(self._on_copy_finished)
        self.copy.start()

    def _on_copy_progress(self, pct, text):
        self.copy_bar.setValue(pct)
        self.copy_text.setText(text)

    def _on_copy_finished(self, ok, message):
        if not ok:
            self.copy_text.setText("✗ " + message)
            self.copy_text.setStyleSheet("font-weight: bold; color: #B03A2E;")
            self.btn_cancel.setText("Close")
            self.btn_cancel.show()
            QMessageBox.warning(self, "New mission", message + "\n\nThe images already copied are kept: "
                                "run the new mission again to finish it.")
            return
        import IRD_Interactive_progress as Progress
        base = Path(self.params["File path mission"])
        Progress.mark_step_done(base, 1)
        minutes = (time.time() - self._copy_started) / 60
        self.copy_bar.setValue(100)
        self.copy_text.setText(f"Done in {minutes:.0f} min." if minutes >= 1 else "Done.")
        self.pages_bar.set(2, Look.STAGE_DONE)
        self.subtitle.setText("The mission is ready.")
        self.done_title.setText(f"✓  Mission {base.name} created")
        self.done_text.setText(
            f"{self.vis.count} visible and {self.nir.count} infrared images copied to "
            f"<a href='open'>{base}</a>.<br><br>"
            "<b>Next: the flight timeline.</b> The synchronisation and survey phases are detected "
            "automatically; you only check them, then the rest of the processing runs on its own.")
        self.done_card.show()
        self.btn_next.setEnabled(True)
        self.btn_next.setDefault(True)
        self.btn_next.setFocus()
        self.btn_cancel.setText("Close")
        self.btn_cancel.show()
        self.mission_created.emit(self.params)

    def _open_folder(self, _link):
        if self.params:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.params["File path mission"]))

    # ---- misc
    def _on_classic(self):
        self.action = "classic"
        self.reject()

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help("ch:step1", parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")

    def done(self, r):
        if self.copy is not None and self.copy.running():
            QMessageBox.information(self, "New mission", "Wait for the copy to finish before closing.")
            return
        if self.locate_thread is not None and self.locate_thread.isRunning():
            self.locate_thread.wait(8000)
        super().done(r)


def _free_bytes(folder: Path):
    try:
        from IRD_Interactive_diskspace import free_bytes
        p = Path(folder)
        while not p.exists() and p.parent != p:
            p = p.parent
        return free_bytes(p)
    except Exception:
        return None


def main():
    """Standalone: python IRD_Interactive_new_mission.py [working folder]"""
    app = QApplication.instance() or QApplication(sys.argv)
    import config
    dlg = NewMissionDialog(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(config.OUTPUT_FOLDER_NAME))
    dlg.show()
    app.exec()
    print("action:", dlg.action)


if __name__ == "__main__":
    main()
