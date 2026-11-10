# -*- coding: utf-8 -*-
"""
Review of the aligned survey images (end of Step 4).

    header        counts: aligned / to check / flagged / no image
    compare view  the visible image and the aligned infrared of the selected
                  point: swipe curtain, blink, red/cyan overlay or side by side;
                  wheel to zoom, drag to pan (misalignments are a few pixels)
    sidebar       the point: time, altitude, infrared match, measured residual,
                  Flag, previous / next
    time line     every shoot point of the survey: residual misalignment chart
                  and a filmstrip coloured by status (hover to preview)

The doubtful points (residual misalignment measured automatically, see
shoot_review.py) stand out in orange; the user flags the bad ones (F) and
realigns them by hand: the alignment window (IRD_Interactive_manual_align.py)
takes every flagged point in turn, then their alignments are computed together
in the background (the review stays usable) and each new image is confirmed
here ("realigned, to confirm" in purple).
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThread, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                             QScrollArea, QStackedWidget,
                             QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shoot_review as R  # noqa: E402
import IRD_Interactive_map as MapV  # noqa: E402
from IRD_Interactive_look import (BLUE, CURSOR, DANGER_STYLE, DIALOG_STYLE, GRID, MESSAGE_STYLE,  # noqa: E402
                                  MUTED, PANEL, PRIMARY_STYLE, PROGRESS_STYLE, SECONDARY_STYLE,
                                  SUBTITLE_STYLE, TITLE_STYLE, bgr_to_qimage, chip, fit_to_screen, fmt_time,
                                  set_chip)

STATUS_COLORS = {
    R.STATUS_OK: QColor("#2E7D32"),
    R.STATUS_CHECKED: QColor("#1565C0"),
    R.STATUS_CHECK: QColor("#E0A030"),
    R.STATUS_SUSPICIOUS: QColor("#D35400"),
    R.STATUS_FLAGGED: QColor("#B03A2E"),
    R.STATUS_REALIGNED: QColor("#7B3FA0"),
    R.STATUS_UNKNOWN: QColor("#9AA5B1"),
    R.STATUS_MISSING: QColor("#C5CFDA"),
}
STATUS_TEXT = {
    R.STATUS_OK: "Aligned",
    R.STATUS_CHECKED: "Confirmed by you",      # a realigned point confirmed (or checked before)
    R.STATUS_CHECK: "To check",
    R.STATUS_SUSPICIOUS: "Probably misaligned",
    R.STATUS_FLAGGED: "Flagged: left out of the map",
    R.STATUS_REALIGNED: "Realigned, to confirm",
    R.STATUS_UNKNOWN: "Not measured",
    R.STATUS_MISSING: "No aligned image",
}
NOT_ALIGNED_COLOR = QColor("#A0AAB4")      # map: a shoot point Step 4 did not align
LEGEND_ORDER = (R.STATUS_OK, R.STATUS_CHECKED, R.STATUS_CHECK, R.STATUS_UNKNOWN, R.STATUS_SUSPICIOUS,
                R.STATUS_FLAGGED, R.STATUS_REALIGNED, R.STATUS_MISSING)
# Points worth a look, in this order, for "Next to review"
TO_REVIEW = (R.STATUS_REALIGNED, R.STATUS_SUSPICIOUS, R.STATUS_CHECK, R.STATUS_UNKNOWN)

TAG_COLOR = QColor("#1F2933")      # labels on the images: neutral, the colours are the images'
DEFAULT_MODE = "overlay"           # doubled edges show a misalignment at a glance
MODES = [  # (key, button text, tooltip)
    ("swipe", "Swipe", "Visible on the left of the curtain, aligned infrared (false colours) on the right. "
                       "Drag the curtain: roads, hedges and buildings must continue across it."),
    ("blink", "Blink", "Visible and infrared shown in turn: a misaligned image jumps."),
    ("overlay", "Overlay", "Visible in cyan, infrared in red (vegetation is naturally red). Aligned: "
                           "edges are single and sharp. Misaligned: every edge is doubled, red on one side, "
                           "cyan on the other."),
    ("side", "Side by side", "Visible and aligned infrared next to each other."),
    ("map", "Map", "Where the image was taken: the flight, the ground covered by the image, the orthophoto "
                   "of Step 5 when it is built and aerial photos (online, optional)."),
]
MAX_VIEW_WIDTH = 3000     # the compare view works on copies at most this wide


# ---------------------------------------------------------------------------
#  Background work: thumbnails, measurements, full images
# ---------------------------------------------------------------------------
class ScanThread(QThread):
    """Thumbnails of every point (fast), then the misalignment measurements."""
    thumb = pyqtSignal(int, QImage)
    measured = pyqtSignal(int)
    progress = pyqtSignal(int, int)

    def __init__(self, review: R.Review, numbers=None):
        super().__init__()
        self.review = review
        self.numbers = None if numbers is None else set(numbers)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        points = [p for p in self.review.points if self.numbers is None or p.number in self.numbers]
        for p in points:
            if self._stop:
                return
            path = p.vir_image or p.vis_image
            img = R.thumbnail(path) if path is not None else None
            if img is not None:
                self.thumb.emit(p.number, bgr_to_qimage(img))
        todo = [p for p in points if p.shift is None and p.vir_image is not None]
        for k, p in enumerate(todo):
            if self._stop:
                return
            try:
                R.measure_point(p)
            except Exception as e:  # one bad image must not stop the others
                print(f"Review: {p.stem} not measured ({e})")
            self.measured.emit(p.number)
            self.progress.emit(k + 1, len(todo))


class _LoadSignals(QObject):
    loaded = pyqtSignal(int, object)    # number, {"vis": array, "vir": array}


class LoadJob(QRunnable):
    def __init__(self, point: R.ReviewPoint):
        super().__init__()
        self.point = point
        self.signals = _LoadSignals()

    def run(self):
        import cv2
        from image_io import imread
        out = {}
        for key, path in (("vis", self.point.vis_image), ("vir", self.point.vir_image)):
            img = imread(path) if path is not None else None
            if img is not None and img.shape[1] > MAX_VIEW_WIDTH:
                s = MAX_VIEW_WIDTH / img.shape[1]
                img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            out[key] = img
        self.signals.loaded.emit(self.point.number, out)


# ---------------------------------------------------------------------------
#  Compare view
# ---------------------------------------------------------------------------
class CompareView(QWidget):
    """Visible / aligned infrared of one point, with zoom and pan.

    Images: "vis" (visible), "vir" (false colours), "nir" (infrared, grey),
    "ana" (red/cyan overlay), made on demand from the two loaded arrays."""
    hint = "wheel to zoom, drag to pan, double-click to fit"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mode = DEFAULT_MODE
        self.status_color: Optional[QColor] = None    # frame in the colour of the point's status
        self.arrays: Dict[str, np.ndarray] = {}
        self.pix: Dict[str, QPixmap] = {}
        self.placeholder: Optional[QPixmap] = None
        self.message = ""
        self.caption = ""
        self.curtain = 0.5
        self.zoom = 1.0            # 1 = whole image in the view
        self.center = QPointF(0.5, 0.5)   # image point at the view centre (0..1)
        self._drag = None
        self._blink_on = False
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(550)
        self.blink_timer.timeout.connect(self._blink)

    # ---- content
    def set_placeholder(self, pix: Optional[QPixmap], message=""):
        self.arrays, self.pix = {}, {}
        self.placeholder = pix
        self.message = message
        self.update()

    def set_images(self, arrays: dict):
        self.arrays = {k: v for k, v in arrays.items() if v is not None}
        self.pix = {}
        self.placeholder = None
        self.message = "" if self.arrays else "The images of this point cannot be read."
        self.update()

    def has_images(self):
        return bool(self.arrays)

    def image(self, key) -> Optional[QPixmap]:
        if key in self.pix:
            return self.pix[key]
        vis, vir = self.arrays.get("vis"), self.arrays.get("vir")
        img = None
        if key == "vis":
            img = vis
        elif key == "vir":
            img = vir
        elif key == "nir" and vir is not None:
            img = R.nir_from_vir(vir)
        elif key == "ana" and vis is not None and vir is not None:
            img = R.anaglyph(vis, vir)
        if img is None:
            return None
        self.pix[key] = QPixmap.fromImage(bgr_to_qimage(img))
        return self.pix[key]

    def set_mode(self, mode):
        self.mode = mode
        if mode == "blink":
            self.blink_timer.start()
        else:
            self.blink_timer.stop()
        self.update()

    def _blink(self):
        self._blink_on = not self._blink_on
        self.update()

    # ---- geometry: image (0..1 coordinates) <-> widget
    def _ref_size(self) -> QSize:
        p = self.image("vis") or self.image("vir") or self.placeholder
        return p.size() if p is not None else QSize(4, 3)

    def _areas(self) -> List[QRectF]:
        r = QRectF(self.rect()).adjusted(4, 4, -4, -24)
        if self.mode == "side":
            w = (r.width() - 8) / 2
            return [QRectF(r.left(), r.top(), w, r.height()), QRectF(r.left() + w + 8, r.top(), w, r.height())]
        return [r]

    def _image_rect(self, area: QRectF) -> QRectF:
        """Where the whole image is drawn in `area` (may be larger than the area once zoomed)."""
        size = self._ref_size()
        fit = min(area.width() / size.width(), area.height() / size.height())
        s = fit * self.zoom
        w, h = size.width() * s, size.height() * s
        return QRectF(area.center().x() - self.center.x() * w, area.center().y() - self.center.y() * h, w, h)

    def _clamp_center(self):
        half = 0.5 / self.zoom
        self.center = QPointF(min(max(self.center.x(), half), 1 - half) if self.zoom > 1 else 0.5,
                              min(max(self.center.y(), half), 1 - half) if self.zoom > 1 else 0.5)

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#11161D"))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._drag is None)
        if not self.arrays:
            area = self._areas()[0]
            if self.placeholder is not None:
                p.drawPixmap(self._image_rect(area), self.placeholder, QRectF(self.placeholder.rect()))
            self._text(p, self.message or "Loading…", area)
            return
        areas = self._areas()
        if self.mode == "side":
            for area, key, cap in ((areas[0], "vis", "Visible"), (areas[1], "vir", "Aligned infrared")):
                self._draw(p, area, key)
                self._tag(p, area, cap, TAG_COLOR)
        elif self.mode == "swipe":
            area = areas[0]
            self._draw(p, area, "vir")
            rect = self._image_rect(area)
            x = rect.left() + self.curtain * rect.width()
            p.save()
            p.setClipRect(QRectF(area.left(), area.top(), max(0.0, x - area.left()), area.height()))
            self._draw(p, area, "vis")
            p.restore()
            if area.left() <= x <= area.right():
                p.setPen(QPen(QColor("white"), 2))
                p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                grip = QRectF(x - 9, area.center().y() - 22, 18, 44)
                p.setBrush(QColor("white"))
                p.drawRoundedRect(grip, 6, 6)
                p.setPen(QPen(BLUE, 2))
                for dx in (-3, 3):
                    p.drawLine(QPointF(x + dx, grip.top() + 12), QPointF(x + dx, grip.bottom() - 12))
            self._tag(p, area, "◀ Visible", TAG_COLOR)
            self._tag(p, area, "Aligned infrared ▶", TAG_COLOR, right=True)
        elif self.mode == "blink":
            key = "nir" if self._blink_on else "vis"
            self._draw(p, areas[0], key)
            self._tag(p, areas[0], "Infrared" if self._blink_on else "Visible", TAG_COLOR)
        else:
            self._draw(p, areas[0], "ana")
            self._tag(p, areas[0], "Visible cyan · infrared red · doubled edges = misaligned", TAG_COLOR)
        self._paint_status_frame(p)
        if self.caption:
            p.setPen(QColor("#C5CFDA"))
            p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)
        zoom = f"{self.zoom * self._fit_scale():.0%}"
        p.setPen(QColor("#8A96A3"))
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"zoom {zoom}  ·  {self.hint}")

    def _paint_status_frame(self, p):
        if self.status_color is None:
            return
        p.setPen(QPen(self.status_color, 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self.rect()).adjusted(3, 3, -3, -3))

    def set_status_color(self, color: Optional[QColor]):
        self.status_color = color
        self.update()

    def _fit_scale(self):
        area, size = self._areas()[0], self._ref_size()
        full = max(size.width(), 1)
        vis = self.arrays.get("vis")
        if vis is not None:   # relative to the original image, not the reduced copy
            full = size.width() * (max(vis.shape[1], 1) / max(size.width(), 1))
        fit = min(area.width() / size.width(), area.height() / size.height())
        return fit * size.width() / full

    def _draw(self, p, area, key):
        pix = self.image(key)
        if pix is None:
            self._text(p, "Not available", area)
            return
        p.save()
        # intersect: keeps the curtain clip of the swipe mode
        p.setClipRect(area, Qt.ClipOperation.IntersectClip)
        p.drawPixmap(self._image_rect(area), pix, QRectF(pix.rect()))
        p.restore()

    def _tag(self, p, area, text, color, right=False):
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 16
        r = QRectF(area.right() - w - 8 if right else area.left() + 8, area.top() + 8, w, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(color)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(self.font())

    def _text(self, p, text, area):
        p.setPen(QColor("#C5CFDA"))
        p.drawText(area, Qt.AlignmentFlag.AlignCenter, text)

    # ---- interaction
    def _near_curtain(self, pos):
        if self.mode != "swipe" or not self.arrays:
            return False
        rect = self._image_rect(self._areas()[0])
        return abs(rect.left() + self.curtain * rect.width() - pos.x()) < 12

    def mousePressEvent(self, e):
        pos = e.position()
        if self._near_curtain(pos):
            self._drag = ("curtain",)
        else:
            self._drag = ("pan", pos, QPointF(self.center))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag and self._drag[0] == "curtain":
            rect = self._image_rect(self._areas()[0])
            self.curtain = min(max((pos.x() - rect.left()) / max(rect.width(), 1), 0.0), 1.0)
            self.update()
            return
        if self._drag and self._drag[0] == "pan":
            _, start, c0 = self._drag
            rect = self._image_rect(self._areas()[0])
            self.center = QPointF(c0.x() - (pos.x() - start.x()) / rect.width(),
                                  c0.y() - (pos.y() - start.y()) / rect.height())
            self._clamp_center()
            self.update()
            return
        self.setCursor(Qt.CursorShape.SizeHorCursor if self._near_curtain(pos) else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.zoom > 1.01:
            self.zoom, self.center = 1.0, QPointF(0.5, 0.5)
        else:
            self.zoom_at(e.position(), 4.0)
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(e.position(), 1.25 ** steps)

    def zoom_at(self, pos, factor):
        area = next((a for a in self._areas() if a.contains(pos)), self._areas()[0])
        rect = self._image_rect(area)
        # image point under the mouse stays under the mouse
        u = (pos.x() - rect.left()) / max(rect.width(), 1)
        v = (pos.y() - rect.top()) / max(rect.height(), 1)
        new_zoom = min(max(self.zoom * factor, 1.0), 40.0)
        k = self.zoom / new_zoom
        self.center = QPointF(u + (self.center.x() - u) * k, v + (self.center.y() - v) * k)
        self.zoom = new_zoom
        self._clamp_center()
        self.update()


# ---------------------------------------------------------------------------
#  Time line of the shoot points
# ---------------------------------------------------------------------------
class ReviewStrip(QWidget):
    """Residual misalignment chart over a filmstrip of the shoot points.

    Hover to preview, click to select, wheel to zoom, drag to pan,
    double-click to see the whole survey."""

    hovered = pyqtSignal(int)        # point index
    left = pyqtSignal()
    picked = pyqtSignal(int)

    GUTTER = 92
    CHART_H = 70
    LANE_H = 64
    STATUS_H = 8
    AXIS_H = 20

    def __init__(self, review: R.Review, thumbs: Dict[int, QPixmap], parent=None):
        super().__init__(parent)
        self.review = review
        self.thumbs = thumbs
        self.selected = 0
        self.hover: Optional[int] = None
        self._drag = None
        n = max(1, len(review.points))
        self.i0, self.i1 = -0.5, n - 0.5
        self.setMouseTracking(True)
        self.setFixedHeight(8 + self.CHART_H + 6 + self.LANE_H + self.STATUS_H + self.AXIS_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def plot_w(self):
        return max(10, self.width() - self.GUTTER - 12)

    def x_of(self, i):
        return self.GUTTER + (i - self.i0) / (self.i1 - self.i0) * self.plot_w()

    def i_of(self, x):
        return self.i0 + (x - self.GUTTER) / self.plot_w() * (self.i1 - self.i0)

    def index_at(self, x) -> Optional[int]:
        n = len(self.review.points)
        if n == 0 or x < self.GUTTER:
            return None
        return int(np.clip(round(self.i_of(x)), 0, n - 1))

    def rows(self):
        y = 8
        chart = QRectF(self.GUTTER, y, self.plot_w(), self.CHART_H)
        y += self.CHART_H + 6
        lane = QRectF(self.GUTTER, y, self.plot_w(), self.LANE_H)
        y += self.LANE_H
        status = QRectF(self.GUTTER, y, self.plot_w(), self.STATUS_H)
        y += self.STATUS_H
        axis = QRectF(self.GUTTER, y, self.plot_w(), self.AXIS_H)
        return chart, lane, status, axis

    def ensure_visible(self, i):
        if not (self.i0 + 0.5 <= i <= self.i1 - 0.5):
            span = self.i1 - self.i0
            self.i0 = i - span / 2
            self.i1 = self.i0 + span
            self._clamp()

    def _clamp(self):
        n = len(self.review.points)
        span = self.i1 - self.i0
        if self.i0 < -0.5:
            self.i0, self.i1 = -0.5, -0.5 + span
        if self.i1 > n - 0.5:
            self.i0, self.i1 = max(-0.5, n - 0.5 - span), n - 0.5

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        chart, lane, status, axis = self.rows()
        p.save()
        p.setClipRect(QRectF(self.GUTTER, 0, self.plot_w(), self.height()))
        self._paint_chart(p, chart)
        self._paint_lane(p, lane)
        self._paint_status(p, status)
        self._paint_cursor(p, chart, status)
        p.restore()
        self._paint_axis(p, axis)
        self._paint_gutter(p, chart, lane)

    def _paint_gutter(self, p, chart, lane):
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        al = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        p.setPen(MUTED)
        p.drawText(QRectF(0, chart.top(), self.GUTTER - 10, 32), al | Qt.TextFlag.TextWordWrap,
                   "Residual\nmisalignment")
        y_ok = self._y_of(R.SHIFT_OK, chart)
        y_bad = self._y_of(R.SHIFT_SUSPICIOUS, chart)
        p.drawText(QRectF(0, y_ok - 8, self.GUTTER - 10, 16), al, f"{R.SHIFT_OK:g} px")
        p.drawText(QRectF(0, y_bad - 8, self.GUTTER - 10, 16), al, f"{R.SHIFT_SUSPICIOUS:g} px")
        fb = QFont(f)
        fb.setBold(True)
        p.setFont(fb)
        p.setPen(TAG_COLOR)
        p.drawText(QRectF(0, lane.top(), self.GUTTER - 10, lane.height()), al, "Aligned\nimages")
        p.setFont(self.font())

    CHART_MAX = 12.0

    def _y_of(self, v, chart):
        return chart.bottom() - min(v, self.CHART_MAX) / self.CHART_MAX * (chart.height() - 4)

    def _paint_chart(self, p, chart):
        p.fillRect(chart, QColor("#FBFCFD"))
        for v, c in ((R.SHIFT_OK, STATUS_COLORS[R.STATUS_CHECK]), (R.SHIFT_SUSPICIOUS, STATUS_COLORS[R.STATUS_SUSPICIOUS])):
            pen = QPen(c, 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            y = self._y_of(v, chart)
            p.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
        n = len(self.review.points)
        px = self.plot_w() / max(self.i1 - self.i0, 1e-6)
        bw = max(1.5, min(px * 0.7, 18))
        for i, pt in enumerate(self.review.points):
            x = self.x_of(i)
            if x < chart.left() - bw or x > chart.right() + bw:
                continue
            color = STATUS_COLORS[pt.status]
            if pt.shift is None:
                p.setPen(QPen(QColor("#C5CFDA"), 1))
                p.drawLine(QPointF(x, chart.bottom() - 3), QPointF(x, chart.bottom()))
                continue
            y = self._y_of(pt.shift, chart)
            p.fillRect(QRectF(x - bw / 2, y, bw, chart.bottom() - y), color)
            if pt.shift > self.CHART_MAX:   # off the chart: arrow tip
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(x - bw / 2, chart.top() + 4), QPointF(x, chart.top()))
                p.drawLine(QPointF(x + bw / 2, chart.top() + 4), QPointF(x, chart.top()))
        if n == 0:
            p.setPen(MUTED)
            p.drawText(chart, Qt.AlignmentFlag.AlignCenter, "No shoot point")

    def _paint_lane(self, p, lane):
        p.fillRect(lane, PANEL)
        n = len(self.review.points)
        if n == 0:
            return
        tile_w = lane.height() * 4 / 3
        start = max(lane.left(), self.x_of(0) - tile_w / 2)
        stop = min(lane.right(), self.x_of(n - 1) + tile_w / 2)
        px_per_point = self.plot_w() / max(self.i1 - self.i0, 1e-6)
        if px_per_point >= tile_w:   # room for every image: centred on its point
            for i, pt in enumerate(self.review.points):
                x = self.x_of(i)
                if x + tile_w / 2 < lane.left() or x - tile_w / 2 > lane.right():
                    continue
                self._tile(p, QRectF(x - tile_w / 2 + 1, lane.top() + 1, tile_w - 2, lane.height() - 2), pt, tile_w)
        else:   # slots of one thumbnail: each shows the point nearest to its centre
            x = start
            while x < stop:
                w = min(tile_w, stop - x)
                i = self.index_at(x + w / 2)
                if i is not None:
                    self._tile(p, QRectF(x + 1, lane.top() + 1, w - 2, lane.height() - 2),
                               self.review.points[i], tile_w)
                x += tile_w

    def _tile(self, p, target, pt, tile_w):
        pix = self.thumbs.get(pt.number)
        if pix is not None and not pix.isNull():
            sw = pix.width() * target.width() / (tile_w - 2)
            src = QRectF((pix.width() - sw) / 2, 0, sw, pix.height())
            p.drawPixmap(target, pix, src)
        else:
            p.fillRect(target, QColor("#E9EDF2"))
        if pt.failed:   # flag in the corner
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(STATUS_COLORS[R.STATUS_FLAGGED])
            p.drawRoundedRect(QRectF(target.left() + 3, target.top() + 3, 16, 16), 3, 3)
            p.setPen(QColor("white"))
            p.drawText(QRectF(target.left() + 3, target.top() + 3, 16, 16), Qt.AlignmentFlag.AlignCenter, "⚑")
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif pt.checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(STATUS_COLORS[R.STATUS_CHECKED])
            p.drawEllipse(QRectF(target.left() + 3, target.top() + 3, 15, 15))
            p.setPen(QColor("white"))
            p.drawText(QRectF(target.left() + 3, target.top() + 3, 15, 15), Qt.AlignmentFlag.AlignCenter, "✓")
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_status(self, p, status):
        px = self.plot_w() / max(self.i1 - self.i0, 1e-6)
        for i, pt in enumerate(self.review.points):
            x = self.x_of(i)
            if x < status.left() - px or x > status.right() + px:
                continue
            p.fillRect(QRectF(x - px / 2, status.top() + 1, px + 0.5, status.height() - 2), STATUS_COLORS[pt.status])

    def _paint_cursor(self, p, chart, status):
        for i, color, width in ((self.hover, QColor(CURSOR.red(), CURSOR.green(), CURSOR.blue(), 150), 1.5),
                                (self.selected, CURSOR, 2.5)):
            if i is None or not (0 <= i < len(self.review.points)):
                continue
            x = self.x_of(i)
            p.setPen(QPen(color, width))
            p.drawLine(QPointF(x, chart.top()), QPointF(x, status.bottom()))
        if self.selected is not None and 0 <= self.selected < len(self.review.points):
            x = self.x_of(self.selected)
            pt = self.review.points[self.selected]
            text = pt.stem + (f" · {pt.shift:.1f} px" if pt.shift is not None else "")
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 14
            bx = min(max(x - w / 2, chart.left()), chart.right() - w)
            bubble = QRectF(bx, chart.top(), w, 20)
            p.setBrush(CURSOR)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bubble, 6, 6)
            p.setPen(QColor("white"))
            p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, text)
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_axis(self, p, axis):
        n = len(self.review.points)
        if n == 0:
            return
        p.setPen(MUTED)
        span = self.i1 - self.i0
        step = next((s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500) if span / s <= max(4, self.plot_w() / 70)), 1000)
        i = int(np.ceil(max(self.i0, 0) / step) * step)
        while i <= min(self.i1, n - 1):
            x = self.x_of(i)
            pt = self.review.points[i]
            label = pt.label + (f"  {fmt_time(pt.time)}" if pt.time is not None and span <= 40 else "")
            p.drawLine(QPointF(x, axis.top()), QPointF(x, axis.top() + 4))
            p.drawText(QRectF(x - 60, axis.top() + 3, 120, 16), Qt.AlignmentFlag.AlignCenter, label)
            i += step

    # ---- interaction
    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None:
            x0, a, b = self._drag[:3]
            di = (pos.x() - x0) / self.plot_w() * (b - a)
            if abs(pos.x() - x0) > 3:
                self._drag = (x0, a, b, True)
                self.i0, self.i1 = a - di, b - di
                self._clamp()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
            return
        i = self.index_at(pos.x())
        if i != self.hover:
            self.hover = i
            if i is not None:
                self.hovered.emit(i)
            self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.left.emit()
        self.update()

    def mousePressEvent(self, e):
        self._drag = (e.position().x(), self.i0, self.i1)

    def mouseReleaseEvent(self, e):
        dragged = self._drag is not None and len(self._drag) == 4
        self._drag = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not dragged:
            i = self.index_at(e.position().x())
            if i is not None:
                self.picked.emit(i)

    def mouseDoubleClickEvent(self, _):
        self.i0, self.i1 = -0.5, max(1, len(self.review.points)) - 0.5
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        n = len(self.review.points)
        if steps == 0 or n == 0:
            return
        ic = self.i_of(e.position().x())
        span = min(n, max(4.0, (self.i1 - self.i0) * 0.8 ** steps))
        a = (ic - self.i0) / (self.i1 - self.i0)
        self.i0 = ic - a * span
        self.i1 = self.i0 + span
        self._clamp()
        self.update()


# ---------------------------------------------------------------------------
#  Dialog
# ---------------------------------------------------------------------------
class ReviewDialog(QDialog):
    """Review of the aligned images. Writes the flags at once (shoot_points.json)."""

    def __init__(self, mission: Path, parent=None):
        super().__init__(parent)
        self.mission = Path(mission)
        self.review = R.load_review(self.mission)   # FileNotFoundError: Step 4 not run
        self.thumbs: Dict[int, QPixmap] = {}
        self._scans: List[ScanThread] = []
        self._cache: "OrderedDict[int, dict]" = OrderedDict()
        self._loading = set()
        self.index = 0
        self._hover_index: Optional[int] = None
        self._redo_errors: List[str] = []
        self.setWindowTitle(f"Step 4 – Review the aligned images · {self.mission.name}")
        self.setStyleSheet(DIALOG_STYLE)
        fit_to_screen(self, parent)
        self._build()
        import IRD_Interactive_4 as Step4
        self._aligning_by_hand = False        # the alignment window is open
        self._redo_report_pending = False     # alignments finished meanwhile, not reported yet
        self._redo_errors = []
        self.redo_runner = Step4.RedoRunner(self.review.output, self, workers=Step4.redo_workers())
        self.redo_runner.output.connect(lambda text: print(text))
        self.redo_runner.point_started.connect(lambda *_: self._update_banner())
        self.redo_runner.stage.connect(lambda *_: self._update_banner())
        self.redo_runner.point_done.connect(self._on_redo_done)
        self.redo_runner.all_done.connect(self._on_redo_all_done)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_hovered)
        self._user_moved = False     # until then, the end of the scan shows the worst point
        self._refresh_counts()
        self._start_scan()
        if self.review.points:
            self.select(self._first_to_review(), by_user=False)
        self._update_banner()

    # ---- layout
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 10)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("Review the aligned images")
        title.setStyleSheet(TITLE_STYLE)
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet(SUBTITLE_STYLE)
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(title)
        head.addWidget(self.subtitle, 1)
        self.chips = {}
        for status, tip in ((R.STATUS_OK, "Measured aligned (residual below "
                                          f"{R.SHIFT_OK:g} px) or realigned and confirmed by you."),
                            (R.STATUS_CHECK, "Residual misalignment between "
                                             f"{R.SHIFT_OK:g} and {R.SHIFT_SUSPICIOUS:g} px, or not measurable: have a look."),
                            (R.STATUS_SUSPICIOUS, f"Residual misalignment above {R.SHIFT_SUSPICIOUS:g} px."),
                            (R.STATUS_FLAGGED, "Flagged: left out of the map (Step 5) until realigned and "
                                               "confirmed."),
                            (R.STATUS_REALIGNED, "Realigned by hand: check the new image and confirm it "
                                                 "(skipped by Step 5 until then)."),
                            (R.STATUS_MISSING, "The alignment wrote no image for these points.")):
            c = chip(STATUS_COLORS[status], "", tip)
            self.chips[status] = c
            head.addWidget(c)
        outer.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(PROGRESS_STYLE)
        outer.addWidget(self.progress)
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner.setStyleSheet("#banner { background: #EAF2FB; border: 1px solid #B9D3EE; border-radius: 8px; }")
        banner_col = QVBoxLayout(self.banner)
        banner_col.setContentsMargins(12, 6, 8, 8)
        banner_col.setSpacing(6)
        bl = QHBoxLayout()
        banner_col.addLayout(bl)
        self.banner_text = QLabel()
        self.banner_text.setTextFormat(Qt.TextFormat.RichText)
        self.banner_text.setWordWrap(True)     # a long image name must not widen the window
        self.btn_accept_redo = QPushButton("✓ Yes, aligned")
        self.btn_accept_redo.setStyleSheet(PRIMARY_STYLE)
        self.btn_accept_redo.clicked.connect(lambda: self._verdict(True))
        self.btn_reject_redo = QPushButton("✗ Still misaligned")
        self.btn_reject_redo.setStyleSheet(DANGER_STYLE)
        self.btn_reject_redo.clicked.connect(lambda: self._verdict(False))
        self.btn_accept_all = QPushButton()
        self.btn_accept_all.setStyleSheet(SECONDARY_STYLE)
        self.btn_accept_all.clicked.connect(self._accept_all)
        self.btn_stop_redo = QPushButton("Stop")
        self.btn_stop_redo.setStyleSheet(SECONDARY_STYLE)
        self.btn_stop_redo.setToolTip("Start no other alignment: the ones running finish, the others stay flagged.")
        self.btn_stop_redo.clicked.connect(self._stop_redo)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.btn_stop_redo)
        bl.addWidget(self.btn_accept_all)
        bl.addWidget(self.btn_reject_redo)
        bl.addWidget(self.btn_accept_redo)
        # progress of the alignments computing in the background
        self.redo_box = QWidget()
        rl = QVBoxLayout(self.redo_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.redo_bar = QProgressBar()
        self.redo_bar.setTextVisible(False)
        self.redo_bar.setFixedHeight(5)
        self.redo_bar.setStyleSheet(PROGRESS_STYLE)
        rl.addWidget(self.redo_bar)
        banner_col.addWidget(self.redo_box)
        self.redo_box.hide()
        self._redo_clock = QTimer(self)
        self._redo_clock.setInterval(1000)
        self._redo_clock.timeout.connect(self._update_banner)
        self.banner.hide()
        outer.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(6)
        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        for k, (key, text, tip) in enumerate(MODES):
            b = QPushButton(f"{text}")
            b.setCheckable(True)
            b.setStyleSheet(SECONDARY_STYLE)
            b.setToolTip(f"{tip}  (key {k + 1})")
            b.clicked.connect(lambda _=False, key=key: self.set_mode(key))
            self.mode_group.addButton(b, k)
            modes.addWidget(b)
        self.mode_group.button([m[0] for m in MODES].index(DEFAULT_MODE)).setChecked(True)
        modes.addStretch(1)
        self.btn_open = QPushButton("Open full size")
        self.btn_open.setStyleSheet(SECONDARY_STYLE)
        self.btn_open.setToolTip("Open the aligned image in the default image viewer.")
        self.btn_open.clicked.connect(self._open_full_size)
        modes.addWidget(self.btn_open)
        left.addLayout(modes)
        self.view = CompareView()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)
        self.map_model = self._make_map_model()
        self.big_map = None
        if self.map_model is not None:
            self.big_map = MapV.FlightMapView(self.map_model)
            self.big_map.picked.connect(self._on_map_picked)
            self.big_map.hovered.connect(self._on_map_hovered)
            self.big_map.clicked_empty.connect(self._clear_map_selection)
            self.view_stack.addWidget(self.big_map)
        else:
            self.mode_group.button(len(MODES) - 1).setEnabled(False)
            self.mode_group.button(len(MODES) - 1).setToolTip("No GPS position in the shoot points: no map.")
        left.addWidget(self.view_stack, 1)
        body.addLayout(left, 1)
        # The side panel scrolls rather than set the window's minimum height: the
        # redo banner then takes its room from the image, the window keeps its size.
        side_scroll = QScrollArea()
        side_scroll.setWidget(self._build_sidebar())
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setFixedWidth(side_scroll.widget().width() + 14)
        side_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        side_scroll.viewport().setAutoFillBackground(False)
        body.addWidget(side_scroll)
        outer.addLayout(body, 1)

        self.strip = ReviewStrip(self.review, self.thumbs)
        self.strip.setToolTip("Hover to preview · click to select · wheel to zoom · drag to pan · "
                              "double-click to see the whole survey")
        self.strip.hovered.connect(self._on_strip_hover)
        self.strip.left.connect(self._on_strip_left)
        self.strip.picked.connect(self.select)
        outer.addWidget(self.strip)

        foot = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.setFixedWidth(36)
        self.btn_help.clicked.connect(self._on_help)
        self.btn_help.setToolTip("← → previous / next point\nN next point to review\nF flag / unflag\n"
                                 "Y realigned point: yes, aligned\n"
                                 "1-4 compare mode\n5 map\n"
                                 "wheel zoom · double-click fit")
        self.btn_flag_suspicious = QPushButton()
        self.btn_flag_suspicious.setStyleSheet(SECONDARY_STYLE)
        self.btn_flag_suspicious.setToolTip("Flag every point measured as probably misaligned "
                                            f"(residual above {R.SHIFT_SUSPICIOUS:g} px).")
        self.btn_flag_suspicious.clicked.connect(self._flag_suspicious)
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(SECONDARY_STYLE)
        self.btn_close.clicked.connect(self.accept)
        self.btn_redo = QPushButton()
        self.btn_redo.setStyleSheet(PRIMARY_STYLE)
        self.btn_redo.setToolTip("Place the infrared of every flagged point by hand, one after the other, then "
                                 "their alignments are computed together in the background. You confirm the "
                                 "new images here.")
        self.btn_redo.clicked.connect(self._redo_flagged)
        foot.addWidget(self.btn_help)
        foot.addWidget(self.btn_flag_suspicious)
        foot.addStretch(1)
        foot.addWidget(self.btn_redo)
        foot.addWidget(self.btn_close)     # Close always at the bottom right
        outer.addLayout(foot)

        try:
            import IRD_Interactive_help as Help
            self.btn_close.setToolTip("Close the review. What you flagged and confirmed is already saved.")
            self.btn_prev.setToolTip("Previous point (key ←)")
            self.btn_next.setToolTip("Next point (key →)")
            self.btn_next_review.setToolTip("Next point that still needs a look: realigned to confirm, "
                                            "measured as doubtful or not measured (key N).")
            self.btn_accept_redo.setToolTip("The realigned image is right: the point is no longer flagged (key Y).")
            self.btn_reject_redo.setToolTip("Still misaligned: the point stays flagged (it can be realigned again).")
            self.btn_accept_all.setToolTip("Every realigned point is right: none of them is flagged any more.")
            for widget, label in ((self.btn_redo, "btn:review_redo"),
                                  (self.btn_flag, "btn:review_decide"),
                                  (self.btn_flag_suspicious, "btn:review_decide"),
                                  (self.btn_prev, "btn:review_navigation"), (self.btn_next, "btn:review_navigation"),
                                  (self.btn_next_review, "btn:review_navigation"),
                                  (self.btn_open, "btn:review_compare"), (self.btn_close, "btn:review_navigation"),
                                  (self.btn_accept_redo, "btn:review_redo"), (self.btn_reject_redo, "btn:review_redo"),
                                  (self.btn_accept_all, "btn:review_redo"), (self.btn_stop_redo, "btn:review_redo")):
                Help.attach_help(widget, label, widget.toolTip(), parent=self)
            for b in self.mode_group.buttons():
                label = "btn:review_map" if b is self.mode_group.button(len(MODES) - 1) else "btn:review_compare"
                Help.attach_help(b, label, b.toolTip(), parent=self)
            Help.attach_help(self.btn_help, "ch:review", "", parent=self)   # keeps the keys as tool tip
        except Exception as e:  # help is a convenience
            print(f"Help not attached: {e}")

        # the keys go to the window (not also to the focused button)
        for b in self.findChildren(QPushButton):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for seq, slot in (("Left", lambda: self.step(-1)), ("Right", lambda: self.step(+1)),
                          ("N", self.next_to_review), ("F", self.toggle_flag),
                          ("1", lambda: self.set_mode("swipe")), ("2", lambda: self.set_mode("blink")),
                          ("3", lambda: self.set_mode("overlay")), ("4", lambda: self.set_mode("side")),
                          ("5", lambda: self.set_mode("map")), ("Y", self._confirm_key)):
            QShortcut(QKeySequence(seq), self, activated=slot)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("card")
        side.setStyleSheet("#card { background: white; border: 1px solid #DDE3EA; border-radius: 8px; }")
        side.setFixedWidth(300)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.point_title = QLabel()
        self.point_title.setStyleSheet("font-size: 15pt; font-weight: bold; color: #17365D;")
        self.point_status = QLabel()
        self.point_status.setTextFormat(Qt.TextFormat.RichText)
        self.point_info = QLabel()
        self.point_info.setTextFormat(Qt.TextFormat.RichText)
        self.point_info.setWordWrap(True)
        self.point_info.setStyleSheet("color: #3E4C59;")
        self.gauge = ShiftGauge()
        lay.addWidget(self.point_title)
        lay.addWidget(self.point_status)
        lay.addWidget(self.gauge)
        lay.addWidget(self.point_info)
        lay.addSpacing(6)
        self.btn_flag = QPushButton("⚑ Flag: leave out of the map   (F)")
        self.btn_flag.setCheckable(True)
        self.btn_flag.setStyleSheet(DANGER_STYLE)
        self.btn_flag.setToolTip("Flag this point (misaligned, blurred, black area at the edge…): it is left out "
                                 "of the map (Step 5) until it is realigned by hand and confirmed. "
                                 "Leave it flagged if it cannot be recovered.")
        self.btn_flag.clicked.connect(self.toggle_flag)
        lay.addWidget(self.btn_flag)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.btn_next_review = QPushButton("Next to review  (N)")
        for b in (self.btn_prev, self.btn_next, self.btn_next_review):
            b.setStyleSheet(SECONDARY_STYLE)
        self.btn_prev.setFixedWidth(44)
        self.btn_next.setFixedWidth(44)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(+1))
        self.btn_next_review.clicked.connect(self.next_to_review)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next_review, 1)
        nav.addWidget(self.btn_next)
        lay.addLayout(nav)
        lay.addStretch(1)
        # where the image was taken (click: the large map); keyboard help on "?"
        self.mini_map = None
        if self.map_model is not None:
            self.mini_map = MapV.FlightMapView(self.map_model, compact=True)
            self.mini_map.setFixedHeight(200)
            self.mini_map.setToolTip("Where the image was taken. Click: large map (key 5)")
            self.mini_map.picked.connect(self._on_map_picked)
            self.mini_map.clicked_empty.connect(lambda: self.set_mode("map"))
            lay.addWidget(self.mini_map)
        else:
            keys = QLabel("<b>Keyboard</b><br>← →&nbsp; previous / next<br>N&nbsp; next point to review<br>"
                          "F&nbsp; flag / unflag<br>1 2 3 4&nbsp; swipe, blink, overlay, "
                          "side by side")
            keys.setTextFormat(Qt.TextFormat.RichText)
            keys.setStyleSheet("color: #6B7785; background: #F5F7FA; border-radius: 6px; padding: 8px;")
            lay.addWidget(keys)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setStyleSheet("color: #6B7785;")
        lay.addWidget(self.legend)
        return side

    def legend_counts(self):
        """[(colour, text, count)] of the legend under the mini map: only the
        kinds of points present."""
        counts = self.review.counts()
        out = [(STATUS_COLORS[s], STATUS_TEXT[s], counts.get(s, 0)) for s in LEGEND_ORDER]
        if self.map_model is not None:
            outside = sum(1 for n in self.map_model.numbers if self.review.by_number(n) is None)
            out.append((NOT_ALIGNED_COLOR, "Not aligned (Step 4)", outside))
        return [row for row in out if row[2]]

    def _refresh_legend(self):
        self.legend.setText("".join(
            f"<span style='color:{color.name()}'>■</span>&nbsp;{text}&nbsp;<b>{count}</b><br>"
            for color, text, count in self.legend_counts()))

    # ---- background scan
    def _start_scan(self, numbers=None):
        """Scan in the background (a new scan after a redo may run beside the first one)."""
        self.scan = ScanThread(self.review, numbers)
        self._scans.append(self.scan)
        self.scan.finished.connect(lambda s=self.scan: self._scans.remove(s) if s in self._scans else None)
        self.scan.thumb.connect(self._on_thumb)
        self.scan.measured.connect(self._on_measured)
        self.scan.progress.connect(self._on_scan_progress)
        self.scan.finished.connect(self._on_scan_finished)
        todo = sum(1 for p in self.review.points if p.shift is None and p.vir_image is not None
                   and (numbers is None or p.number in numbers))
        self.progress.setVisible(todo > 0)
        self.progress.setRange(0, max(1, todo))
        self.progress.setValue(0)
        self.scan.start()

    def _on_thumb(self, number, image):
        self.thumbs[number] = QPixmap.fromImage(image)
        self.strip.update()
        if self.map_model is not None and self.current() is not None and self.current().number == number:
            self.map_model.changed.emit()
        if self.current() is not None and self.current().number == number and not self.view.has_images():
            self.view.set_placeholder(self.thumbs[number], "Loading…")

    def _on_measured(self, _number):
        if self.map_model is not None:
            self.map_model.changed.emit()      # point colours
        self._refresh_counts()
        self._refresh_point()
        self.strip.update()

    def _on_scan_progress(self, k, n):
        self.progress.setValue(k)
        self.subtitle.setText(f"Measuring the residual misalignment… {k}/{n}")

    def _on_scan_finished(self):
        if any(s.isRunning() for s in self._scans if s is not self.sender()):
            return
        self.progress.hide()
        if not self._user_moved and self.review.points:
            self.select(self._first_to_review(), by_user=False)
        try:
            R.save_state(self.review)
        except OSError as e:
            print(f"Review state not saved: {e}")
        self._refresh_counts()

    # ---- selection
    def current(self) -> Optional[R.ReviewPoint]:
        if 0 <= self.index < len(self.review.points):
            return self.review.points[self.index]
        return None

    def _first_to_review(self) -> int:
        for status in (R.STATUS_REALIGNED, R.STATUS_FLAGGED) + TO_REVIEW:
            for i, p in enumerate(self.review.points):
                if p.status == status:
                    return i
        return 0

    def select(self, index: int, by_user: bool = True):
        if not self.review.points:
            return
        self._user_moved = self._user_moved or by_user
        self.index = int(np.clip(index, 0, len(self.review.points) - 1))
        self.strip.selected = self.index
        self.strip.ensure_visible(self.index)
        self.strip.update()
        self._show_point(self.index)
        self._refresh_point()
        self._update_banner()
        self._map_follow()
        # prefetch the neighbours
        for j in (self.index + 1, self.index - 1):
            if 0 <= j < len(self.review.points):
                self._load(self.review.points[j])

    def step(self, delta):
        self.select(self.index + delta)

    def next_to_review(self):
        n = len(self.review.points)
        for k in range(1, n + 1):
            j = (self.index + k) % n
            if self.review.points[j].status in TO_REVIEW:
                self.select(j)
                return
        self.subtitle.setText("Nothing left to review: every measured point is aligned, checked or flagged.")

    # ---- images
    def _load(self, point: R.ReviewPoint):
        if point.number in self._cache or point.number in self._loading:
            return
        if point.vis_image is None and point.vir_image is None:
            return
        self._loading.add(point.number)
        job = LoadJob(point)
        job.signals.loaded.connect(self._on_loaded)
        QThreadPool.globalInstance().start(job)

    def _on_loaded(self, number, arrays):
        self._loading.discard(number)
        self._cache[number] = arrays
        while len(self._cache) > 4:
            self._cache.popitem(last=False)
        shown = self._shown_index()
        if shown is not None and self.review.points[shown].number == number:
            self.view.set_images(arrays)

    def _shown_index(self):
        return self._hover_index if self._hover_index is not None else self.index

    def _show_point(self, index):
        pt = self.review.points[index]
        self.view.set_status_color(STATUS_COLORS[pt.status])
        self.view.caption = (f"{pt.stem}  ·  " + STATUS_TEXT[pt.status]
                             + (f"  ·  {pt.vir_image.name}" if pt.vir_image is not None else ""))
        if pt.number in self._cache:
            self._cache.move_to_end(pt.number)
            self.view.set_images(self._cache[pt.number])
        elif pt.vir_image is None and pt.vis_image is None:
            self.view.set_placeholder(None, "The alignment wrote no image for this point.")
        else:
            self.view.set_placeholder(self.thumbs.get(pt.number), "Loading…")
            self._load(pt)

    def _on_strip_hover(self, i):
        self._hover_index = i
        if self.map_model is not None and 0 <= i < len(self.review.points):
            self.map_model.set_hover(self.map_model.index_of(self.review.points[i].number))
        self._hover_timer.start(60)

    def _show_hovered(self):
        if self._hover_index is not None:
            self._show_point(self._hover_index)

    def _on_strip_left(self):
        self._hover_index = None
        if self.map_model is not None:
            self.map_model.set_hover(None)
        self._hover_timer.stop()
        if self.current() is not None:
            self._show_point(self.index)

    def set_mode(self, mode):
        keys = [m[0] for m in MODES]
        if mode == "map":
            if self.big_map is None:
                return
            self.view_stack.setCurrentWidget(self.big_map)
            if self.current() is not None:
                i = self.map_model.index_of(self.current().number)
                if i is not None:
                    self.big_map.focus(i)
        else:
            self.view_stack.setCurrentWidget(self.view)
            self.view.set_mode(mode)
        self.mode_group.button(keys.index(mode)).setChecked(True)

    # ---- map
    def _make_map_model(self):
        try:
            model = MapV.map_model_for(self.mission, color_of=self._map_color, shoot_points_only=True, parent=self)
        except Exception as e:  # the map is a help, never a blocker
            print(f"Map unavailable: {e}")
            return None
        if model is not None:
            model.image_of = self.thumbs.get       # aligned image (thumbnail) in its footprint
            model.cursor_in_point_color = True     # the footprint in the colour of the point's status
            model.minor = lambda i: self._map_status(model.numbers[i]) in (None, R.STATUS_MISSING)
        return model

    def _map_status(self, number):
        """Status of a point of the map (None: not aligned by Step 4)."""
        pt = self.review.by_number(number)
        return pt.status if pt is not None else None

    def _map_color(self, number):
        status = self._map_status(number)
        return STATUS_COLORS[status] if status is not None else NOT_ALIGNED_COLOR

    def _on_map_picked(self, i):
        number = self.map_model.numbers[i]
        for k, p in enumerate(self.review.points):
            if p.number == number:
                self.select(k)
                return

    def _on_map_hovered(self, i):
        self.map_model.set_hover(i)

    def _clear_map_selection(self):
        """Click on the large map outside any point: no point selected on the
        map, the trajectory alone (no footprint, no image); a click on a point
        or a move along the strip selects one again."""
        self.map_model.set_current(None)

    def _map_follow(self):
        if self.map_model is None or self.current() is None:
            return
        i = self.map_model.index_of(self.current().number)
        self.map_model.set_current(i)
        if i is not None:
            for v in (self.mini_map, self.big_map):
                if v is not None and v.isVisible():
                    v.focus(i)

    # ---- point details
    def _refresh_point(self):
        pt = self.current()
        if pt is None:
            self.point_title.setText("No shoot point")
            for b in (self.btn_flag, self.btn_prev, self.btn_next, self.btn_next_review):
                b.setEnabled(False)
            return
        color = STATUS_COLORS[pt.status]
        if self._hover_index is None:
            self.view.set_status_color(color)          # flagged / checked: the frame follows at once
        self.point_title.setText(pt.stem)
        self.point_status.setText(f"<span style='background:{color.name()}; color:white; border-radius:8px;'>"
                                  f"&nbsp;{STATUS_TEXT[pt.status]}&nbsp;</span>"
                                  f"&nbsp;&nbsp;<span style='color:#6B7785'>{self.index + 1} / "
                                  f"{len(self.review.points)}</span>")
        self.gauge.set_value(pt.shift, pt.shift_worst)
        lines = []
        if pt.time is not None:
            lines.append(f"Shot at <b>{fmt_time(pt.time)}</b>" +
                         (f" · {pt.altitude:.0f} m above ground" if pt.altitude is not None else ""))
        if pt.nir_name:
            lines.append(f"Infrared <b>{Path(pt.nir_name).stem}</b>" +
                         (f" · Δt {pt.dt:+.2f} s" if pt.dt is not None else ""))
        if pt.motion and pt.motion.get("correction"):
            c = pt.motion["correction"]
            lines.append("Automatic correction: " + ", ".join(f"{k} {v:+.2f}°" for k, v in c.items() if abs(v) > 1e-6))
        if pt.redo_script is None:
            lines.append("<span style='color:#B03A2E'>No REDO script: cannot be realigned by hand.</span>")
        self.point_info.setText("<br>".join(lines))
        self.btn_flag.setChecked(pt.failed)
        self.btn_flag.setText("⚑ Flagged: out of the map   (F)" if pt.failed else "⚑ Flag: leave out of the map   (F)")
        self.btn_open.setEnabled(pt.vir_image is not None)
        for b in (self.btn_flag, self.btn_prev, self.btn_next, self.btn_next_review):
            b.setEnabled(True)
        self.view.caption = (f"{pt.stem}  ·  " + STATUS_TEXT[pt.status]
                             + (f"  ·  {pt.vir_image.name}" if pt.vir_image is not None else ""))
        self.view.update()

    def _refresh_counts(self):
        self._refresh_legend()
        counts = self.review.counts()
        ok = counts.get(R.STATUS_OK, 0) + counts.get(R.STATUS_CHECKED, 0)
        check = counts.get(R.STATUS_CHECK, 0) + counts.get(R.STATUS_UNKNOWN, 0)
        set_chip(self.chips[R.STATUS_OK], f"✓ {ok} aligned" if ok else "", self.chips[R.STATUS_OK].toolTip())
        set_chip(self.chips[R.STATUS_CHECK], f"? {check} to check" if check else "", self.chips[R.STATUS_CHECK].toolTip())
        sus = counts.get(R.STATUS_SUSPICIOUS, 0)
        set_chip(self.chips[R.STATUS_SUSPICIOUS], f"! {sus} probably misaligned" if sus else "",
                 self.chips[R.STATUS_SUSPICIOUS].toolTip())
        fl = counts.get(R.STATUS_FLAGGED, 0)
        set_chip(self.chips[R.STATUS_FLAGGED], f"⚑ {fl} flagged · out of the map" if fl else "",
                 self.chips[R.STATUS_FLAGGED].toolTip())
        re = counts.get(R.STATUS_REALIGNED, 0)
        set_chip(self.chips[R.STATUS_REALIGNED], f"◆ {re} to confirm" if re else "",
                 self.chips[R.STATUS_REALIGNED].toolTip())
        miss = counts.get(R.STATUS_MISSING, 0)
        set_chip(self.chips[R.STATUS_MISSING], f"— {miss} no image" if miss else "",
                 self.chips[R.STATUS_MISSING].toolTip())
        if not self.progress.isVisible():
            n = len(self.review.points)
            self.subtitle.setText(
                f"{n} shoot points. Check that the visible and infrared images overlap; "
                "flag the misaligned ones, then realign them by hand." if n else
                "No shoot point was aligned: run Step 4 first.")
        redoable = self._redoable()
        self.btn_redo.setText(f"Realign {len(redoable)} flagged by hand  ▶" if redoable else "Realign flagged by hand  ▶")
        self.btn_redo.setEnabled(bool(redoable))
        sus_points = [p for p in self.review.suspicious()]
        self.btn_flag_suspicious.setText(f"Flag the {len(sus_points)} probably misaligned" if sus_points
                                         else "Flag the probably misaligned")
        self.btn_flag_suspicious.setEnabled(bool(sus_points))
        self.btn_flag_suspicious.setVisible(bool(sus_points))   # nothing measured as misaligned: no button

    def redo_runner_busy(self):
        runner = getattr(self, "redo_runner", None)
        return runner is not None and runner.busy()

    def _computing(self) -> set:
        """Points whose alignment is waiting or running."""
        runner = getattr(self, "redo_runner", None)
        return runner.numbers() if runner is not None else set()

    def _redoable(self) -> List[R.ReviewPoint]:
        """Flagged points that can be realigned by hand now (not computing, not
        waiting for the user's verdict on a new alignment)."""
        computing = self._computing()
        return [p for p in self.review.flagged() if p.status == R.STATUS_FLAGGED and p.redo_script is not None
                and p.number not in computing]

    # ---- decisions
    def _set_failed(self, points, failed):
        try:
            R.set_failed(self.review, [p.number for p in points], failed)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Review", f"Unable to update shoot_points.json:\n{e}")
            return False
        self._after_change()
        return True

    def toggle_flag(self):
        pt = self.current()
        if pt is None or pt.number in self._computing():
            self._refresh_point()
            return
        self._set_failed([pt], not pt.failed)

    def _flag_suspicious(self):
        points = self.review.suspicious()
        if points and self._set_failed(points, True):
            self.subtitle.setText(f"{len(points)} point(s) flagged.")

    def _after_change(self):
        if self.map_model is not None:
            self.map_model.changed.emit()
        try:
            R.save_state(self.review)
        except OSError as e:
            print(f"Review state not saved: {e}")
        self._refresh_counts()
        self._refresh_point()
        self.strip.update()

    # ---- redo by hand: place every point, compute them together, confirm
    def _redo_flagged(self):
        import IRD_Interactive_4 as Step4
        import IRD_Interactive_manual_align as M
        points = self._redoable()
        queue = Step4.redo_queue(self.review.output, [(p.number, p.stem) for p in points],
                                 log=lambda m: print(m))
        items = M.items_from_queue(queue)
        if not items:
            QMessageBox.warning(self, "Review", "No flagged point can be realigned (no REDO script).")
            return
        # Each point computes as soon as it is placed, while the next one is placed
        dialog = M.ManualAlignDialog(items, self.mission.name, self,
                                     send_now=lambda item: self._compute_realigned([item]))
        self._aligning_by_hand = True
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._aligning_by_hand = False
        if accepted:
            self._compute_realigned(dialog.placed())
        if self._redo_report_pending and not self.redo_runner.busy():
            self._on_redo_all_done()          # finished while the window was open

    def _compute_realigned(self, items):
        """Realign the points placed by hand (angles in ``items``), in the background."""
        import IRD_Interactive_4 as Step4
        if not items:
            return
        for item in items:
            pt = self.review.by_number(item.number)
            if pt is not None:
                pt.realigned = False          # a new result is coming
        if not self.redo_runner.busy() and not self._redo_report_pending:
            self._redo_errors = []
        self.redo_runner.add([(i.number, i.stem, Step4.manual_redo_arguments(i.arguments, i.angles))
                              for i in items])
        self._redo_clock.start()
        self._after_change()

    def _stop_redo(self):
        self.redo_runner.stop()
        self._update_banner()

    def _update_banner(self):
        """Alignments computing (progress, Stop) and / or the realigned point shown
        to confirm (Yes / Still misaligned / All aligned)."""
        if not hasattr(self, "redo_runner"):
            return
        import time as _time
        import IRD_Interactive_4 as Step4
        runner = self.redo_runner
        lines = []
        computing = runner.busy()
        if computing:
            running = runner.running()
            done, total = runner.finished, max(runner.total, 1)
            now = ", ".join(f"<b>{job['stem']}</b> ({self.REDO_HINTS.get(job['stage'], job['stage'])} "
                            f"{fmt_time(_time.time() - job['started'])[:-2]})" for job in running)
            waiting = len(runner.numbers()) - len(running)
            lines.append(f"Computing the alignments: {done} of {runner.total} done"
                         + (f" · {now}" if now else "") + (f" · {waiting} waiting" if waiting else "")
                         + " <span style='color:#6B7785'>— keep reviewing meanwhile.</span>")
            stage_rank = {key: k for k, (key, _title) in enumerate(Step4.REDO_STAGES)}
            steps = len(stage_rank) or 1
            self.redo_bar.setRange(0, total * steps)
            self.redo_bar.setValue(done * steps + sum(stage_rank.get(job["stage"], 0) for job in running))
        to_confirm = [p for p in self.review.points if p.status == R.STATUS_REALIGNED]
        pt = self.current()
        confirm = pt is not None and pt.status == R.STATUS_REALIGNED
        if confirm:
            lines.append(f"<b>{pt.stem}</b> realigned. Is it right now? Check it with the curtain, blink or "
                         "overlay.")
        elif to_confirm:
            lines.append(f"{len(to_confirm)} realigned point(s) to confirm (◆ purple): "
                         "N goes to the next one.")
        self.banner_text.setText("<br>".join(lines))
        self.redo_box.setVisible(computing)
        self.btn_stop_redo.setVisible(computing and bool(runner.numbers() - {j["number"] for j in runner.running()}))
        self.btn_accept_redo.setVisible(confirm)
        self.btn_reject_redo.setVisible(confirm)
        self.btn_accept_all.setText(f"✓ All {len(to_confirm)} aligned")
        self.btn_accept_all.setVisible(len(to_confirm) > 1)
        self.banner.setVisible(bool(lines))

    REDO_HINTS = {
        "load": "loading",
        "compute": "computing",
        "write": "saving",
    }

    def _on_redo_done(self, number, stem, image, error):
        pt = self.review.by_number(number)
        if error or pt is None:
            self._redo_errors.append(error or f"{stem}: unknown point")
            print(error)
            if pt is not None:          # back to its images before the redo: shown again from disk
                R.refresh_point(self.review, pt)
                self._cache.pop(number, None)
                self.thumbs.pop(number, None)
                self._start_scan({number})
                if self.current() is pt:
                    self._show_point(self.index)
        else:
            R.refresh_point(self.review, pt)
            pt.realigned = pt.failed
            self._cache.pop(number, None)
            self.thumbs.pop(number, None)
            self._start_scan({number})
            if self.current() is pt:
                self._show_point(self.index)
        self._after_change()
        self._update_banner()

    def _on_redo_all_done(self):
        if self._aligning_by_hand:            # reported once the alignment window is closed
            self._redo_report_pending = True
            self._refresh_counts()
            self._update_banner()
            return
        self._redo_report_pending = False
        self._redo_clock.stop()
        to_confirm = [p for p in self.review.points if p.status == R.STATUS_REALIGNED]
        errors = self._redo_errors
        self._refresh_counts()
        self.subtitle.setText(f"Alignments computed: {len(to_confirm)} realigned point(s) to confirm"
                              + (f", {len(errors)} error(s)." if errors else "."))
        cur = self.current()
        if to_confirm and (cur is None or cur.status != R.STATUS_REALIGNED):
            self.select(self.review.points.index(to_confirm[0]), by_user=False)
        self._update_banner()
        if errors:
            QMessageBox.warning(self, "Realign by hand", "\n".join(errors))

    def _confirm_key(self):
        pt = self.current()
        if pt is not None and pt.status == R.STATUS_REALIGNED:
            self._verdict(True)

    def _verdict(self, aligned: bool):
        pt = self.current()
        if pt is None or pt.status != R.STATUS_REALIGNED:
            return
        if aligned:
            if not self._set_failed([pt], False):
                return
            pt.checked = True
        pt.realigned = False                  # rejected: flagged again, to realign
        self._after_change()
        nxt = next((j for j in list(range(self.index + 1, len(self.review.points))) + list(range(self.index))
                    if self.review.points[j].status == R.STATUS_REALIGNED), None)
        if nxt is not None:
            self.select(nxt)
        else:
            self._update_banner()

    def _accept_all(self):
        points = [p for p in self.review.points if p.status == R.STATUS_REALIGNED]
        if not points or not self._set_failed(points, False):
            return
        for p in points:
            p.checked = True
        self._after_change()
        self._update_banner()
        self.subtitle.setText(f"{len(points)} realigned point(s) confirmed.")

    # ---- misc
    def _open_full_size(self):
        pt = self.current()
        if pt is None or pt.vir_image is None:
            return
        try:
            import IRD_Interactive_help as Help
            if not Help.open_with_default_app(pt.vir_image):
                raise OSError(f"No application available to open {pt.vir_image}")
        except OSError as e:
            QMessageBox.warning(self, "Unable to open the image", str(e))

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help("ch:review", parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")

    def done(self, r):
        if self.redo_runner_busy():
            QMessageBox.information(
                self, "Review", "Alignments are still being computed: wait for them before closing "
                "(Stop starts no new one).")
            return
        for scan in list(self._scans):
            scan.stop()
        for scan in list(self._scans):
            scan.wait(5000)
        try:
            R.save_state(self.review)
        except OSError:
            pass
        super().done(r)


class ShiftGauge(QWidget):
    """Residual misalignment on a 0-12 px scale, with the two thresholds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = None
        self.worst = None
        self.setFixedHeight(48)

    def set_value(self, value, worst):
        self.value, self.worst = value, worst
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(0, 20, self.width() - 1, 10)
        top = 12.0

        def x(v):
            return bar.left() + min(v, top) / top * bar.width()
        segments = ((0, R.SHIFT_OK, STATUS_COLORS[R.STATUS_OK]),
                    (R.SHIFT_OK, R.SHIFT_SUSPICIOUS, STATUS_COLORS[R.STATUS_CHECK]),
                    (R.SHIFT_SUSPICIOUS, top, STATUS_COLORS[R.STATUS_SUSPICIOUS]))
        for a, b, c in segments:
            c2 = QColor(c)
            c2.setAlpha(60)
            p.fillRect(QRectF(x(a), bar.top(), x(b) - x(a), bar.height()), c2)
        p.setPen(MUTED)
        if self.value is None:
            p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignLeft, "Residual misalignment: —")
            self.setToolTip("Not measured (yet), or no texture to measure it.")
            return
        self.setToolTip(f"Median over the textured areas of the image: {self.value:.1f} px; "
                        f"worst area: {self.worst:.1f} px." if self.worst is not None else "")
        if self.worst is not None:
            p.setPen(QPen(MUTED, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x(self.worst), bar.top() - 2), QPointF(x(self.worst), bar.bottom() + 2))
        color = (STATUS_COLORS[R.STATUS_OK] if self.value <= R.SHIFT_OK else
                 STATUS_COLORS[R.STATUS_CHECK] if self.value <= R.SHIFT_SUSPICIOUS else
                 STATUS_COLORS[R.STATUS_SUSPICIOUS])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(x(self.value), bar.center().y()), 7, 7)
        p.setPen(QColor("#3E4C59"))
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignLeft,
                   f"Residual misalignment ≈ {self.value:.1f} px")
        p.setPen(MUTED)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.85)
        p.setFont(f)
        for v in (0, R.SHIFT_OK, R.SHIFT_SUSPICIOUS, top):
            label = f"{v:g}" + (" px" if v == top else "")
            r = QRectF(x(v) - 20, 32, 40, 14)
            r.moveLeft(min(max(r.left(), 0), self.width() - r.width()))
            al = (Qt.AlignmentFlag.AlignLeft if v == 0 else
                  Qt.AlignmentFlag.AlignRight if v == top else Qt.AlignmentFlag.AlignHCenter)
            p.drawText(r, al, label)


_ = (BLUE, GRID, MESSAGE_STYLE)   # part of the shared look, kept for later use


def main():
    """Standalone: python IRD_Interactive_review.py <mission folder>"""
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = ReviewDialog(Path(sys.argv[1]))
    dlg.show()
    app.exec()


if __name__ == "__main__":
    main()
