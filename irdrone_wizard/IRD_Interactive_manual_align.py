# -*- coding: utf-8 -*-
"""
Align by hand (Step 4 review): every flagged point, one after the other, then
the alignments are computed together.

    list          the points to realign: ○ to place, ✓ placed, – skipped
    view          the visible image (undistorted) and the infrared warped with
                  the yaw / pitch / roll set here, shown like in the review:
                  overlay, curtain, blink, side by side, optionally edges only
    side panel    yaw, pitch, roll; "Fit" (the measured offset of the edges is
                  turned into yaw and pitch); the mismatch measured live

Nothing heavy runs while the user places the images: the previews are about
1600 px wide and the warp takes a few milliseconds. Once the points are
placed, "Compute" hands their angles back to the review, which runs
automatic_registration.py --manual-angles on all of them in the background (the
automatic alignment refines from those angles, as after the old slider window)
and asks to confirm each result at the end.

The matplotlib slider window (automatic_registration.py --manual) stays for the
command line.

Standalone:  python IRD_Interactive_manual_align.py <mission folder>
             (the flagged points; prints the angles, computes nothing)
"""
from __future__ import annotations

import math
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QSizePolicy, QSlider, QToolButton, QVBoxLayout)

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shoot_review as R  # noqa: E402
from IRD_Interactive_look import (CARD_STYLE, DIALOG_STYLE, NUDGE_STYLE, PRIMARY_STYLE,  # noqa: E402
                                  SECONDARY_STYLE, SUBTITLE_STYLE, TITLE_STYLE, chip, fit_to_screen, set_chip)

PREVIEW_WIDTH = 1600          # width of the images moved by hand
ANGLE_RANGE = {"yaw": 30.0, "pitch": 30.0, "roll": 5.0}   # same ranges as the slider window
STEP = 0.05                   # degrees per arrow key (Shift: x10), ~2-3 px of the full image
SLIDER_UNITS = 100            # slider positions per degree
ANGLES = ("yaw", "pitch", "roll")
MEASURE_WIDTH = 1000          # width of the copy the offset is measured on
CLOSE_ENOUGH = 10.0           # px of the full image: the automatic alignment does the rest

TODO, PLACED, SKIPPED = "todo", "placed", "skipped"
STATE_LOOK = {TODO: ("○", "#6B7785"), PLACED: ("✓", "#2E7D32"), SKIPPED: ("–", "#A0AAB4")}

MODES = [  # (key, text, tooltip)
    ("ana", "Overlay", "Visible in cyan, infrared in red: move the infrared until the edges are single."),
    ("swipe", "Swipe", "Visible on the left of the curtain, infrared on the right."),
    ("blink", "Blink", "Visible and infrared in turn: the infrared jumps while it is misplaced."),
    ("side", "Side by side", "Visible and infrared next to each other."),
]


# ---------------------------------------------------------------------------
#  Images (no Qt)
# ---------------------------------------------------------------------------
_CALIBRATIONS = None


def calibrations() -> dict:
    """Visible (distortion removed, as in automatic_registration.align_raw) and
    infrared camera calibrations."""
    global _CALIBRATIONS
    if _CALIBRATIONS is None:
        import irdrone.utils as ut
        ref = ut.cameracalibration(camera="DJI_RAW")
        undistorted = deepcopy(ref)
        undistorted["dist"] = undistorted["dist"] * 0.
        _CALIBRATIONS = {"refcalib": ref, "refcalib_undistorted": undistorted,
                         "movingcalib": ut.cameracalibration(camera="M20_RAW")}
    return _CALIBRATIONS


def _to_uint8(img) -> np.ndarray:
    if img.dtype == np.uint8:
        return img
    if img.dtype == np.uint16:
        return (img >> 8).astype(np.uint8)
    img = img.astype(np.float32)
    top = 1.0 if float(np.nanmax(img[::8, ::8])) <= 1.5 else 255.0
    return (np.clip(img / top, 0.0, 1.0) * 255).astype(np.uint8)


@dataclass
class Preview:
    vis: np.ndarray        # RGB uint8, distortion removed, about PREVIEW_WIDTH wide
    nir: np.ndarray        # RGB uint8, reduced by the same factor
    scale: float           # preview / full resolution

    @property
    def focal(self) -> float:
        """Focal length of the visible camera, in preview pixels."""
        return float(calibrations()["refcalib"]["mtx"][0, 0]) * self.scale


def load_preview(vis_path, nir_path, width: int = PREVIEW_WIDTH) -> Preview:
    """Read both images (RAW / DNG: a few seconds) and keep reduced copies."""
    import cv2
    import irdrone.process as pr
    from registration.warp_flow import warp
    cals = calibrations()
    vis = _to_uint8(pr.Image(str(vis_path)).data)
    vis = _to_uint8(warp(vis, cals["refcalib"], np.eye(3)))
    scale = min(1.0, width / vis.shape[1])
    nir = _to_uint8(pr.Image(str(nir_path)).data)
    if scale < 1.0:
        vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        nir = cv2.resize(nir, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return Preview(np.ascontiguousarray(vis), np.ascontiguousarray(nir), scale)


def warp_preview(preview: Preview, angles) -> np.ndarray:
    """The infrared seen from the visible camera, rotated by (yaw, pitch, roll) degrees."""
    from irdrone.semi_auto_registration import manual_warp
    cals = calibrations()
    yaw, pitch, roll = angles
    return manual_warp(preview.vis, preview.nir, yaw, pitch, roll,
                       refcalib=cals["refcalib_undistorted"], movingcalib=cals["movingcalib"],
                       geometric_scale=preview.scale)


def _stretch(channel, valid=None) -> np.ndarray:
    sample = channel[::4, ::4]
    if valid is not None:
        sample = sample[valid[::4, ::4]]
    if sample.size < 16:
        return np.zeros(channel.shape, np.uint8)
    lo, hi = np.percentile(sample, (1, 99))
    return np.clip((channel.astype(np.float32) - lo) * (255.0 / max(hi - lo, 1.0)), 0, 255).astype(np.uint8)


def _edges(gray) -> np.ndarray:
    g = R._gradient(gray)
    top = float(np.percentile(g[::4, ::4], 99)) or 1.0
    return np.clip(g * (255.0 / top), 0, 255).astype(np.uint8)


def display_arrays(vis_rgb, warped_rgb, edges: bool = False) -> dict:
    """BGR images for the compare view: "vis" and "vir" (red = infrared)."""
    import cv2
    nir = warped_rgb.astype(np.float32).mean(axis=2)
    nir8 = _stretch(nir, nir > 0)
    if edges:
        gv = _edges(cv2.cvtColor(vis_rgb, cv2.COLOR_RGB2GRAY))
        gn = _edges(nir8)
        return {"vis": np.dstack([gv, gv, gv]), "vir": np.dstack([gn, gn, gn])}
    vis_bgr = np.ascontiguousarray(vis_rgb[:, :, ::-1])
    return {"vis": vis_bgr, "vir": np.dstack([vis_rgb[:, :, 1], vis_rgb[:, :, 0], nir8])}


def measure_offset(vis_bgr, nir_gray) -> Optional[Tuple[float, float]]:
    """Median offset (dx, dy) of the infrared edges against the visible ones, in
    pixels of the given images; None without enough texture."""
    shifts = R.tile_shifts(vis_bgr, nir_gray, width=MEASURE_WIDTH)
    if len(shifts) < R.MIN_TILES:
        return None
    d = np.array(shifts)
    return float(np.median(d[:, 0])), float(np.median(d[:, 1]))


def describe_offset(offset) -> str:
    """Rich text of a measured offset (pixels of the full image)."""
    if offset is None:
        return "<span style='color:#6B7785'>Offset: not measurable here (too little texture, or too far).</span>"
    dx, dy = offset
    length = math.hypot(dx, dy)
    if length < CLOSE_ENOUGH:
        return f"<span style='color:#2E7D32'>✓ Offset ≈ {length:.0f} px: well placed.</span>"
    parts = [f"{abs(dx):.0f} px {'right' if dx > 0 else 'left'}" if abs(dx) >= 1 else "",
             f"{abs(dy):.0f} px {'down' if dy > 0 else 'up'}" if abs(dy) >= 1 else ""]
    return ("<span style='color:#C26A00'>Infrared ≈ " + ", ".join(p for p in parts if p)
            + " of the visible.</span> <span style='color:#6B7785'>F fits it.</span>")


def move_angles(angles, dx: float, dy: float, focal: float) -> tuple:
    """Angles that move the infrared by (dx, dy) pixels (right, down) for a focal
    length ``focal`` in the same pixels: +yaw moves it right, +pitch down."""
    yaw, pitch, roll = angles
    return (yaw + math.degrees(math.atan2(dx, focal)), pitch + math.degrees(math.atan2(dy, focal)), roll)


def clamp_angles(angles) -> tuple:
    return tuple(min(max(v, -ANGLE_RANGE[k]), ANGLE_RANGE[k]) for k, v in zip(ANGLES, angles))


# ---------------------------------------------------------------------------
#  Background loading
# ---------------------------------------------------------------------------
class _LoadSignals(QObject):
    loaded = pyqtSignal(int, object)      # number, Preview
    failed = pyqtSignal(int, str)


class _LoadJob(QRunnable):
    def __init__(self, item, signals, done: set):
        super().__init__()
        self.item, self.signals, self.done = item, signals, done

    def run(self):
        if self.item.number in self.done:      # asked twice (jumped to it first)
            return
        self.done.add(self.item.number)
        try:
            preview = load_preview(self.item.vis_path, self.item.nir_path)
        except Exception as e:  # noqa: BLE001 (any unreadable image: report it, keep the others)
            self.signals.failed.emit(self.item.number, f"{type(e).__name__}: {e}")
            return
        self.signals.loaded.emit(self.item.number, preview)


@dataclass
class AlignItem:
    number: int
    stem: str
    arguments: list                 # of its REDO command
    vis_path: Path
    nir_path: Path
    initial: tuple = (0.0, 0.0, 0.0)
    angles: tuple = (0.0, 0.0, 0.0)
    state: str = TODO
    preview: Optional[Preview] = None
    error: str = ""
    offset: Optional[tuple] = None  # last offset measured (dx, dy), px of the full image


def items_from_queue(queue) -> List[AlignItem]:
    """``(number, stem, REDO arguments)`` -> items (the unreadable commands are left out)."""
    import IRD_Interactive_4 as Step4
    items = []
    for number, stem, arguments in queue:
        try:
            vis, nir, angles = Step4.redo_pair(arguments)
        except ValueError as e:
            print(f"{stem}: cannot be aligned by hand ({e})")
            continue
        angles = tuple(angles) if angles is not None else (0.0, 0.0, 0.0)
        items.append(AlignItem(number, stem, list(arguments), vis, nir, angles, angles))
    return items


# ---------------------------------------------------------------------------
#  View: the review's compare view, the infrared dragged with the right button
# ---------------------------------------------------------------------------
def _compare_view_class():
    import IRD_Interactive_review as RV

    class AlignView(RV.CompareView):
        """Right-drag (or Shift + drag) moves the infrared; emits the move in
        pixels of the shown images since the drag started."""
        moved = pyqtSignal(float, float)
        move_started = pyqtSignal()
        move_finished = pyqtSignal()
        hint = "right-drag (or Shift + drag) moves the infrared · wheel zoom · drag pan · double-click fit"

        def _image_scale(self):
            size = self._ref_size()
            return self._image_rect(self._areas()[0]).width() / max(size.width(), 1)

        def mousePressEvent(self, e):
            moving = (e.button() == Qt.MouseButton.RightButton or
                      (e.button() == Qt.MouseButton.LeftButton
                       and e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            if moving and self.arrays:
                self._drag = ("move", e.position())
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                self.move_started.emit()
                return
            super().mousePressEvent(e)

        def mouseMoveEvent(self, e):
            if self._drag and self._drag[0] == "move":
                start = self._drag[1]
                s = self._image_scale()
                self.moved.emit((e.position().x() - start.x()) / s, (e.position().y() - start.y()) / s)
                return
            super().mouseMoveEvent(e)

        def mouseReleaseEvent(self, e):
            if self._drag and self._drag[0] == "move":
                self.move_finished.emit()
            super().mouseReleaseEvent(e)

        def contextMenuEvent(self, e):
            e.accept()                     # the right button moves the infrared

    return AlignView


# ---------------------------------------------------------------------------
#  Window
# ---------------------------------------------------------------------------
class ManualAlignDialog(QDialog):
    """Place the infrared of each point by hand; ``placed()`` once accepted."""
    INTRO = "Place every point, then compute them all at once: no waiting between points."

    def __init__(self, items: List[AlignItem], mission_name: str = "", parent=None):
        super().__init__(parent)
        self.items = items
        self.index = 0
        self._edges = False
        self._move_from = None          # angles when a drag started
        self._updating = False
        self.setWindowTitle("Step 4 – Align by hand" + (f" · {mission_name}" if mission_name else ""))
        self.setStyleSheet(DIALOG_STYLE)
        fit_to_screen(self, parent)
        calibrations()                  # read once, before the loading thread uses them
        self._signals = _LoadSignals(self)
        self._signals.loaded.connect(self._on_loaded)
        self._signals.failed.connect(self._on_failed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)  # one at a time: the point shown first, then in order
        self._requested: set = set()
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.setInterval(250)
        self._measure_timer.timeout.connect(self._measure)
        self._build()
        for k, item in enumerate(self.items):
            self._pool.start(_LoadJob(item, self._signals, self._requested), -k)
        self.select(0)

    # ---- layout
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 10)
        outer.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("Align the infrared by hand")
        title.setStyleSheet(TITLE_STYLE)
        self.subtitle = QLabel(self.INTRO)
        self.subtitle.setStyleSheet(SUBTITLE_STYLE)
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(title)
        head.addWidget(self.subtitle, 1)
        self.chip_placed = chip("#2E7D32")
        self.chip_todo = chip("#6B7785")
        self.chip_skipped = chip("#A0AAB4")
        for c in (self.chip_placed, self.chip_todo, self.chip_skipped):
            head.addWidget(c)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.list = QListWidget()
        self.list.setFixedWidth(170)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setStyleSheet("QListWidget { background: white; border: 1px solid #DDE3EA; border-radius: 8px; }"
                                "QListWidget::item { padding: 5px 6px; }"
                                "QListWidget::item:selected { background: #DCE8F5; color: #17365D; }")
        for item in self.items:
            self.list.addItem(QListWidgetItem())
        self.list.currentRowChanged.connect(lambda row: self.select(row) if row != self.index else None)
        body.addWidget(self.list)

        center = QVBoxLayout()
        center.setSpacing(6)
        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        for k, (key, text, tip) in enumerate(MODES):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setStyleSheet(SECONDARY_STYLE)
            b.setToolTip(f"{tip}  (key {k + 1})")
            b.clicked.connect(lambda _=False, key=key: self.set_mode(key))
            self.mode_group.addButton(b, k)
            modes.addWidget(b)
        self.mode_group.button(0).setChecked(True)
        self.edges_box = QCheckBox("Edges only  (G)")
        self.edges_box.setToolTip("Show the outlines of both images: easier on fields and forests, where "
                                  "the infrared and the visible look different.")
        self.edges_box.toggled.connect(self.set_edges)
        modes.addSpacing(10)
        modes.addWidget(self.edges_box)
        modes.addStretch(1)
        center.addLayout(modes)
        self.view = _compare_view_class()()
        self.view.mode = "overlay"
        self.view.moved.connect(self._on_drag)
        self.view.move_started.connect(self._on_drag_start)
        self.view.move_finished.connect(lambda: self._measure_timer.start())
        center.addWidget(self.view, 1)
        body.addLayout(center, 1)
        body.addWidget(self._build_side())
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.setFixedWidth(36)
        self.btn_help.setToolTip("Arrows: move the infrared (Shift: 10 times more)\nQ / E: rotate it\n"
                                 "Right-drag in the image: move it\nF: fit automatically\n"
                                 "Enter: placed, next point\nS: skip this point\n1-4 display · G edges only")
        self.btn_help.clicked.connect(self._on_help)
        self.btn_skip = QPushButton("Skip this point  (S)")
        self.btn_skip.setStyleSheet(SECONDARY_STYLE)
        self.btn_skip.setToolTip("Leave this point out: it stays flagged misaligned (Step 5 skips it).")
        self.btn_skip.clicked.connect(self.skip)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(SECONDARY_STYLE)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setStyleSheet(SECONDARY_STYLE)
        self.btn_prev.setFixedWidth(44)
        self.btn_prev.setToolTip("Previous point")
        self.btn_prev.clicked.connect(lambda: self.select(self.index - 1))
        self.btn_next = QPushButton("Placed, next  ▶")
        self.btn_next.setStyleSheet(SECONDARY_STYLE)
        self.btn_next.setToolTip("This point is placed: go to the next one to place (Enter).")
        self.btn_next.clicked.connect(self.place_and_next)
        self.btn_compute = QPushButton()
        self.btn_compute.setStyleSheet(PRIMARY_STYLE)
        self.btn_compute.setToolTip("Compute the alignment of every placed point, together in the background, "
                                    "starting from where you placed them. You confirm the results in the review.")
        self.btn_compute.clicked.connect(self.compute)
        foot.addWidget(self.btn_help)
        foot.addWidget(self.btn_skip)
        foot.addStretch(1)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_prev)
        foot.addWidget(self.btn_next)
        foot.addWidget(self.btn_compute)
        outer.addLayout(foot)

        try:
            import IRD_Interactive_help as Help
            for widget in (self.btn_compute, self.btn_next, self.btn_skip, self.btn_fit, self.btn_reset):
                Help.attach_help(widget, "btn:review_redo", widget.toolTip(), parent=self)
            Help.attach_help(self.btn_help, "btn:review_redo", "", parent=self)
        except Exception as e:  # help is a convenience
            print(f"Help not attached: {e}")

        for b in self.findChildren(QPushButton) + self.findChildren(QToolButton) + [self.edges_box]:
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        keys = [("Left", lambda: self.nudge(-1, 0)), ("Right", lambda: self.nudge(1, 0)),
                ("Up", lambda: self.nudge(0, -1)), ("Down", lambda: self.nudge(0, 1)),
                ("Shift+Left", lambda: self.nudge(-10, 0)), ("Shift+Right", lambda: self.nudge(10, 0)),
                ("Shift+Up", lambda: self.nudge(0, -10)), ("Shift+Down", lambda: self.nudge(0, 10)),
                ("Q", lambda: self.rotate(-1)), ("E", lambda: self.rotate(1)),
                ("Shift+Q", lambda: self.rotate(-10)), ("Shift+E", lambda: self.rotate(10)),
                ("F", self.fit), ("S", self.skip), ("Return", self.place_and_next), ("Enter", self.place_and_next),
                ("G", lambda: self.edges_box.toggle())]
        keys += [(str(k + 1), lambda key=key: self.set_mode(key)) for k, (key, _t, _tip) in enumerate(MODES)]
        for seq, slot in keys:
            QShortcut(QKeySequence(seq), self, activated=slot)

    def _build_side(self):
        side = QFrame()
        side.setObjectName("card")
        side.setStyleSheet(CARD_STYLE)
        side.setFixedWidth(290)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.point_title = QLabel()
        self.point_title.setStyleSheet("font-size: 15pt; font-weight: bold; color: #17365D;")
        self.point_state = QLabel()
        self.point_state.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.point_title)
        lay.addWidget(self.point_state)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.spins, self.sliders = {}, {}
        names = {"yaw": ("Yaw", "◀", "▶", "Left / right: slider for a quick move, ◀ ▶ or the arrow keys to refine"),
                 "pitch": ("Pitch", "▲", "▼", "Up / down: slider for a quick move, ▲ ▼ or the arrow keys to refine"),
                 "roll": ("Roll", "↺", "↻", "Rotation: slider for a quick move, ↺ ↻ or Q / E to refine")}
        for k, key in enumerate(ANGLES):
            text, minus, plus, tip = names[key]
            label = QLabel(f"<b>{text}</b>")
            label.setToolTip(tip)
            spin = QDoubleSpinBox()
            spin.setRange(-ANGLE_RANGE[key], ANGLE_RANGE[key])
            spin.setDecimals(2)
            spin.setSingleStep(STEP)
            spin.setSuffix(" °")
            spin.setKeyboardTracking(False)
            spin.setToolTip(tip)
            spin.valueChanged.connect(lambda _v: self._on_spin())
            spin.installEventFilter(self)       # the arrow keys move the infrared, even from here
            # The slider: a quick move, the end buttons (and keys) to refine, in the direction they show
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-round(ANGLE_RANGE[key] * SLIDER_UNITS), round(ANGLE_RANGE[key] * SLIDER_UNITS))
            slider.setPageStep(round(10 * STEP * SLIDER_UNITS))
            slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            slider.setToolTip(tip)
            slider.valueChanged.connect(lambda v, key=key: self._on_slider(key, v))
            b_minus, b_plus = QToolButton(), QToolButton()
            for b, sign, arrow in ((b_minus, -1, minus), (b_plus, 1, plus)):
                b.setText(arrow)
                b.setStyleSheet(NUDGE_STYLE)
                b.setAutoRepeat(True)
                b.setToolTip(tip)
                b.clicked.connect(lambda _=False, key=key, sign=sign: self._step_angle(key, sign))
            grid.addWidget(label, 2 * k, 0, 1, 2)
            grid.addWidget(spin, 2 * k, 2, 1, 2)
            grid.addWidget(b_minus, 2 * k + 1, 0)
            grid.addWidget(slider, 2 * k + 1, 1, 1, 2)
            grid.addWidget(b_plus, 2 * k + 1, 3)
            grid.setRowMinimumHeight(2 * k + 1, 30)
            self.spins[key] = spin
            self.sliders[key] = slider
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        buttons = QHBoxLayout()
        self.btn_fit = QPushButton("Fit  (F)")
        self.btn_fit.setStyleSheet(SECONDARY_STYLE)
        self.btn_fit.setToolTip("Measure the offset between the edges of both images and move the infrared by "
                                "that much (yaw and pitch). Works once the images roughly overlap.")
        self.btn_fit.clicked.connect(self.fit)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setStyleSheet(SECONDARY_STYLE)
        self.btn_reset.setToolTip("Back to the angles of the previous alignment.")
        self.btn_reset.clicked.connect(self.reset)
        buttons.addWidget(self.btn_fit, 1)
        buttons.addWidget(self.btn_reset, 1)
        lay.addLayout(buttons)
        self.offset_label = QLabel()
        self.offset_label.setTextFormat(Qt.TextFormat.RichText)
        self.offset_label.setWordWrap(True)
        self.offset_label.setToolTip("Measured between the edges of both images, in pixels of the full image.")
        lay.addWidget(self.offset_label)
        tip = QLabel("Roughly is enough: the automatic alignment refines from where you leave the infrared.<br><br>"
                     "<b>Sliders</b> for a quick move, then <b>◀ ▶ ▲ ▼</b> or the <b>arrow keys</b> to refine "
                     "(Shift: ×10) · <b>Q / E</b> rotate · <b>right-drag</b> in the image · "
                     "<b>F</b> fit · <b>Enter</b> next")
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #6B7785;")
        lay.addWidget(tip)
        lay.addStretch(1)
        return side

    ARROWS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}

    def eventFilter(self, obj, event):
        """In a value box too, the arrow keys move the infrared as everywhere in
        the window (a box would only step its own angle, the pitch upside down)."""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and obj in self.spins.values() and event.key() in self.ARROWS:
            dx, dy = self.ARROWS[event.key()]
            k = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.nudge(dx * k, dy * k)
            return True
        return super().eventFilter(obj, event)

    # ---- state
    def current(self) -> Optional[AlignItem]:
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def placed(self) -> List[AlignItem]:
        return [i for i in self.items if i.state == PLACED]

    def _refresh_list(self):
        for row, item in enumerate(self.items):
            icon, color = STATE_LOOK[item.state]
            w = self.list.item(row)
            w.setText(f"{icon}  {item.stem}" + ("   ⚠" if item.error else ""))
            w.setForeground(QColor(color if item.state != TODO else "#1F2933"))
            w.setToolTip(item.error or {TODO: "To place", PLACED: "Placed", SKIPPED: "Skipped"}[item.state])
        n = {s: sum(1 for i in self.items if i.state == s) for s in STATE_LOOK}
        set_chip(self.chip_placed, f"✓ {n[PLACED]} placed" if n[PLACED] else "")
        set_chip(self.chip_todo, f"○ {n[TODO]} to place" if n[TODO] else "")
        set_chip(self.chip_skipped, f"– {n[SKIPPED]} skipped" if n[SKIPPED] else "")
        self.btn_compute.setText(f"Compute {n[PLACED]} alignment{'s' if n[PLACED] != 1 else ''}  ▶")
        self.btn_compute.setEnabled(n[PLACED] > 0)
        self.btn_prev.setEnabled(self.index > 0)

    def _refresh_point(self):
        item = self.current()
        if item is None:
            return
        self.point_title.setText(item.stem)
        icon, color = STATE_LOOK[item.state]
        text = {TODO: "To place", PLACED: "Placed", SKIPPED: "Skipped: stays flagged"}[item.state]
        self.point_state.setText(f"<span style='color:{color}'>{icon} {text}</span>"
                                 f"&nbsp;&nbsp;<span style='color:#6B7785'>{self.index + 1} / {len(self.items)}</span>")
        self._updating = True
        for key, value in zip(ANGLES, item.angles):
            self.spins[key].setValue(value)
            self.sliders[key].setValue(round(value * SLIDER_UNITS))
        self._updating = False
        ready = item.preview is not None
        for w in list(self.spins.values()) + list(self.sliders.values()) + [self.btn_fit, self.btn_reset]:
            w.setEnabled(ready)
        self.offset_label.setText(describe_offset(item.offset) if ready else "")

    # ---- navigation
    def select(self, index: int):
        if not self.items:
            return
        self.index = min(max(index, 0), len(self.items) - 1)
        item = self.current()
        self.subtitle.setText(self.INTRO)
        if self.list.currentRow() != self.index:
            self.list.setCurrentRow(self.index)
        if item.preview is None and item.number not in self._requested:
            self._pool.start(_LoadJob(item, self._signals, self._requested), 1000)
        self._refresh_list()
        self._refresh_point()
        self._show()

    def _next_todo(self) -> Optional[int]:
        n = len(self.items)
        for k in range(1, n + 1):
            j = (self.index + k) % n
            if self.items[j].state == TODO:
                return j
        return None

    def place_and_next(self):
        item = self.current()
        if item is None or item.preview is None:
            return
        item.state = PLACED
        nxt = self._next_todo()
        if nxt is None:
            self._refresh_list()
            self._refresh_point()
            self.subtitle.setText("Every point is placed: compute them.")
            return
        self.select(nxt)

    def skip(self):
        item = self.current()
        if item is None:
            return
        item.state = SKIPPED
        nxt = self._next_todo()
        if nxt is None:
            self._refresh_list()
            self._refresh_point()
        else:
            self.select(nxt)

    # ---- display
    def set_mode(self, key):
        k = next(i for i, (m, _t, _tip) in enumerate(MODES) if m == key)
        self.mode_group.button(k).setChecked(True)
        self.view.set_mode("overlay" if key == "ana" else key)

    def set_edges(self, on: bool):
        self._edges = bool(on)
        self._show()

    def _show(self, measure: bool = True):
        item = self.current()
        if item is None:
            return
        if item.preview is None:
            self.view.set_placeholder(None, f"{item.stem}: {item.error}" if item.error
                                      else f"Loading {item.stem}…")
            return
        warped = warp_preview(item.preview, item.angles)
        self.view.set_images(display_arrays(item.preview.vis, warped, self._edges))
        self.view.caption = f"{item.stem}  ·  yaw {item.angles[0]:+.2f}°  pitch {item.angles[1]:+.2f}°  " \
                            f"roll {item.angles[2]:+.2f}°"
        if measure:
            self._measure_timer.start()

    def _measure(self, item: Optional[AlignItem] = None):
        item = item or self.current()
        if item is None or item.preview is None:
            return None
        arrays = display_arrays(item.preview.vis, warp_preview(item.preview, item.angles))
        offset = measure_offset(arrays["vis"], arrays["vir"][:, :, 2])
        item.offset = None if offset is None else (offset[0] / item.preview.scale, offset[1] / item.preview.scale)
        if item is self.current():
            self.offset_label.setText(describe_offset(item.offset))
        return offset

    def _on_loaded(self, number, preview):
        item = next((i for i in self.items if i.number == number), None)
        if item is None:
            return
        item.preview = preview
        if item is self.current():
            self._refresh_point()
            self._show()

    def _on_failed(self, number, error):
        item = next((i for i in self.items if i.number == number), None)
        if item is None:
            return
        item.error = f"images not readable ({error})"
        item.state = SKIPPED
        self._refresh_list()
        if item is self.current():
            self._refresh_point()
            self._show()

    # ---- moving the infrared
    def set_angles(self, angles, measure: bool = True):
        item = self.current()
        if item is None or item.preview is None:
            return
        item.angles = clamp_angles(angles)
        if item.state == TODO:
            item.state = PLACED          # moved by the user: placed
            self._refresh_list()
        self._refresh_point()
        self._show(measure)

    def _on_spin(self):
        if self._updating:
            return
        self.set_angles(tuple(self.spins[k].value() for k in ANGLES))

    def _on_slider(self, key, value):
        item = self.current()
        if self._updating or item is None:
            return
        angles = list(item.angles)
        angles[ANGLES.index(key)] = value / SLIDER_UNITS
        self.set_angles(tuple(angles))

    def _step_angle(self, key, sign):
        item = self.current()
        if item is None:
            return
        angles = list(item.angles)
        angles[ANGLES.index(key)] += sign * STEP
        self.set_angles(tuple(angles))

    def nudge(self, dx_steps, dy_steps):
        item = self.current()
        if item is None:
            return
        yaw, pitch, roll = item.angles
        self.set_angles((yaw + dx_steps * STEP, pitch + dy_steps * STEP, roll))

    def rotate(self, steps):
        item = self.current()
        if item is None:
            return
        yaw, pitch, roll = item.angles
        self.set_angles((yaw, pitch, roll + steps * STEP))

    def _on_drag_start(self):
        item = self.current()
        self._move_from = item.angles if item is not None else None

    def _on_drag(self, dx, dy):
        item = self.current()
        if item is None or item.preview is None or self._move_from is None:
            return
        # the view shows the preview images at their own size: dx, dy are preview pixels
        self.set_angles(move_angles(self._move_from, dx, dy, item.preview.focal), measure=False)

    def fit(self):
        """Move the infrared by the offset measured between the edges (twice:
        the second pass corrects the first); keep the result only if better."""
        item = self.current()
        if item is None or item.preview is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            start, start_offset = item.angles, item.offset
            if start_offset is None:
                self._measure(item)
                start_offset = item.offset
            angles = start
            for _ in range(2):
                item.angles = angles
                offset = self._measure(item)
                if offset is None:
                    break
                angles = move_angles(angles, -offset[0], -offset[1], item.preview.focal)
            item.angles = clamp_angles(angles)
            self._measure(item)
            if item.offset is None or (start_offset is not None
                                       and math.hypot(*item.offset) > math.hypot(*start_offset)):
                item.angles, item.offset = start, start_offset
                self.subtitle.setText(f"{item.stem}: no better position found automatically, "
                                      "move the infrared by hand closer first.")
            else:
                self.subtitle.setText(f"{item.stem}: fitted.")
                if item.state == TODO:
                    item.state = PLACED
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_list()
        self._refresh_point()
        self._show(measure=False)

    def reset(self):
        item = self.current()
        if item is not None:
            self.set_angles(item.initial)

    # ---- end
    def compute(self):
        placed = self.placed()
        if not placed:
            return
        todo = [i for i in self.items if i.state == TODO]
        if todo and QMessageBox.question(
                self, "Align by hand",
                f"{len(todo)} point(s) not placed yet: they are left out and stay flagged.\n\n"
                f"Compute the {len(placed)} placed point(s)?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Ok:
            return
        self.accept()

    def reject(self):
        if any(i.state == PLACED for i in self.items) and QMessageBox.question(
                self, "Align by hand", "Forget the points placed by hand?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        ) != QMessageBox.StandardButton.Discard:
            return
        super().reject()

    def done(self, r):
        self._measure_timer.stop()
        self._pool.clear()               # the loads not started
        self._pool.waitForDone()         # the one running (a few seconds at most)
        super().done(r)

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help("btn:review_redo", parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")


def main():
    """Standalone: python IRD_Interactive_manual_align.py <mission folder>"""
    import IRD_Interactive_4 as Step4
    app = QApplication.instance() or QApplication(sys.argv)
    mission = Path(sys.argv[1])
    review = R.load_review(mission)
    queue = Step4.redo_queue(review.output, [(p.number, p.stem) for p in review.flagged()
                                             if p.redo_script is not None])
    dlg = ManualAlignDialog(items_from_queue(queue), mission.name)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        for item in dlg.placed():
            print(item.stem, " ".join(f"{v:.3f}" for v in item.angles))
    app.quit()


if __name__ == "__main__":
    main()
