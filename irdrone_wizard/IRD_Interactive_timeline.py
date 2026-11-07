# -*- coding: utf-8 -*-
"""
Step 2 - Flight timeline.

The synchronisation and survey phases are detected automatically
(flight_timeline.py) and shown on one time line:

    keypoint cards   Sync start | Sync end | Survey start | Survey end   (real images)
    large preview    visible + infrared frame under the mouse
    time line        altitude profile, phase bands, target detections,
                     visible and infrared filmstrips on a common time axis

The user only checks, and drags a band edge (or nudges a keypoint with the
arrows) when needed. Infrared images are placed on the visible time line with
the coarse offset found from the rotating target; their survey window follows
the visible one, so they never need to be looked at.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QImage, QKeySequence, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QShortcut)
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                             QProgressBar, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

sys.path.append(str(Path(__file__).resolve().parent))
import flight_timeline as FT  # noqa: E402

# ---------------------------------------------------------------------------
#  Look
# ---------------------------------------------------------------------------
INK = QColor("#1F2933")
MUTED = QColor("#6B7785")
GRID = QColor("#E4E8EE")
PANEL = QColor("#F5F7FA")
BLUE = QColor("#17365D")
SYNC = QColor("#7B3FA0")
SURVEY = QColor("#2E7D32")
NIR_ACCENT = QColor("#B03A2E")
CURSOR = QColor("#E8A33D")

PHASE_COLORS = {"sync": SYNC, "survey": SURVEY}
KEYPOINTS = [  # (card title, phase, edge)
    ("Sync start", "sync", "first"),
    ("Sync end", "sync", "last"),
    ("Survey start", "survey", "first"),
    ("Survey end", "survey", "last"),
]

PRIMARY_STYLE = """
QPushButton { background-color: #17365D; color: white; font-weight: bold; padding: 9px 18px;
              border: none; border-radius: 6px; }
QPushButton:hover { background-color: #244A73; }
QPushButton:disabled { background-color: #B8C2CC; color: #666666; }
"""
SECONDARY_STYLE = """
QPushButton { background-color: white; color: #17365D; padding: 8px 14px;
              border: 1px solid #C5CFDA; border-radius: 6px; }
QPushButton:hover { background-color: #EEF3F8; }
QPushButton:disabled { color: #A0AAB4; }
"""
NUDGE_STYLE = """
QToolButton { background: white; color: #17365D; border: 1px solid #C5CFDA; border-radius: 4px;
              min-width: 22px; min-height: 20px; font-weight: bold; }
QToolButton:hover { background: #EEF3F8; }
QToolButton:disabled { color: #C5CFDA; border-color: #E4E8EE; }
"""


def fmt_time(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t // 60)}:{t % 60:04.1f}"


def bgr_to_pixmap(img) -> QPixmap:
    img = np.ascontiguousarray(img[:, :, ::-1])   # BGR -> RGB
    h, w = img.shape[:2]
    return QPixmap.fromImage(QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())


# ---------------------------------------------------------------------------
#  Model shared by the views
# ---------------------------------------------------------------------------
class TimelineModel:
    """Frames of both bands, the windows being edited and the VIS/NIR offset."""

    def __init__(self, mission: Path, vis: FT.BandAnalysis, nir: FT.BandAnalysis,
                 proposal: FT.TimelineProposal):
        self.mission = Path(mission)
        self.vis, self.nir, self.proposal = vis, nir, proposal
        self.t_vis = vis.times
        self.t_nir = nir.times
        self.shift = proposal.time_shift
        self.windows: Dict[str, Optional[FT.Window]] = {}
        self.reset()
        self._thumbs: Dict[str, QPixmap] = {}
        self._previews: "OrderedDict[str, QPixmap]" = OrderedDict()
        self.vis_rot = self._in_segments(vis)
        self.nir_rot = self._in_segments(nir)

    @staticmethod
    def _in_segments(band):
        flags = np.zeros(len(band.frames), dtype=bool)
        for w in band.segments:
            flags[w.first:w.last + 1] = True
        return flags

    def reset(self):
        p = self.proposal
        self.windows = {"VIS sync": p.vis_sync, "NIR sync": p.nir_sync,
                        "VIS survey": p.vis_survey, "NIR survey": p.nir_survey}

    def band(self, name):
        return self.vis if name == "VIS" else self.nir

    def times_on_vis_axis(self, name) -> np.ndarray:
        """Frame times of a band on the common (visible) time axis."""
        if name == "VIS":
            return self.t_vis
        return self.t_nir + (self.shift or 0.0)

    def nearest(self, name, t) -> Optional[int]:
        times = self.times_on_vis_axis(name)
        if len(times) == 0:
            return None
        return int(np.argmin(np.abs(times - t)))

    def span(self):
        ts = [self.t_vis]
        if len(self.t_nir):
            ts.append(self.times_on_vis_axis("NIR"))
        lo = min(float(t[0]) for t in ts)
        hi = max(float(t[-1]) for t in ts)
        pad = 0.01 * (hi - lo + 1)
        return lo - pad, hi + pad

    def set_edge(self, key, edge, index):
        """Move one edge of a window, keeping first <= last. Updates the NIR survey."""
        w = self.windows.get(key)
        band = self.band(key.split()[0])
        index = int(np.clip(index, 0, len(band.frames) - 1))
        if w is None:
            w = FT.Window(index, index)
        first, last = w.first, w.last
        if edge == "first":
            first = min(index, last)
        else:
            last = max(index, first)
        self.windows[key] = FT.Window(first, last)
        if key == "VIS survey":
            self.update_nir_survey()

    def update_nir_survey(self):
        if self.shift is not None and len(self.t_nir):
            self.windows["NIR survey"] = FT.derived_window(self.t_vis, self.windows["VIS survey"],
                                                           self.t_nir, self.shift)

    # ---- images
    def thumb(self, name, index) -> Optional[QPixmap]:
        band = self.band(name)
        if index is None or not (0 <= index < len(band.frames)):
            return None
        fname = band.frames[index].name
        key = name + fname
        pix = self._thumbs.get(key)
        if pix is None:
            path = FT.thumbnail_path(self.mission, name, fname)
            pix = QPixmap(str(path)) if path.is_file() else QPixmap()
            self._thumbs[key] = pix
        return pix if not pix.isNull() else None

    def preview(self, name, index) -> Optional[QPixmap]:
        """Large preview (embedded JPEG of the DNG), small LRU cache."""
        band = self.band(name)
        if index is None or not (0 <= index < len(band.frames)):
            return None
        fname = band.frames[index].name
        key = name + fname
        if key in self._previews:
            self._previews.move_to_end(key)
            return self._previews[key]
        try:
            img = FT.read_preview(FT.band_folder(self.mission, name) / fname, full_fallback=False)
        except Exception:
            img = None
        pix = bgr_to_pixmap(img) if img is not None else self.thumb(name, index)
        if pix is None:
            return None
        self._previews[key] = pix
        if len(self._previews) > 40:
            self._previews.popitem(last=False)
        return pix


# ---------------------------------------------------------------------------
#  Time line view (custom painted)
# ---------------------------------------------------------------------------
class TimelineView(QWidget):
    """Altitude chart, phase bands, target detections and filmstrips on one time axis.

    Mouse: hover to preview, drag a band edge to move it, wheel to zoom,
    drag the background to pan, double-click to see the whole flight."""

    hovered = pyqtSignal(float)          # time on the visible axis
    left = pyqtSignal()
    edited = pyqtSignal(str, str)        # window key, edge
    picked = pyqtSignal(str, str)        # window key, edge (clicked on a handle)

    GUTTER = 78
    CHART_H = 150
    DOTS_H = 12
    LANE_H = 62
    AXIS_H = 24
    GAP = 6

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.m = model
        self.t0, self.t1 = model.span()
        self.hover_t: Optional[float] = None
        self.selected: Optional[tuple] = None    # (key, edge)
        self._drag = None                        # (key, edge) or ("pan", x0, t0, t1)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(self.total_height())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.alt_max = max([f.alt for f in model.vis.frames if f.alt is not None] or [1.0])

    # ---- geometry
    def total_height(self):
        return 8 + self.CHART_H + self.DOTS_H + self.GAP + self.LANE_H + self.DOTS_H + self.GAP + \
            self.LANE_H + self.AXIS_H + 4

    def rows(self):
        y = 8
        chart = QRectF(self.GUTTER, y, self.plot_w(), self.CHART_H)
        y += self.CHART_H
        vis_dots = QRectF(self.GUTTER, y, self.plot_w(), self.DOTS_H)
        y += self.DOTS_H + self.GAP
        vis_lane = QRectF(self.GUTTER, y, self.plot_w(), self.LANE_H)
        y += self.LANE_H
        nir_dots = QRectF(self.GUTTER, y, self.plot_w(), self.DOTS_H)
        y += self.DOTS_H + self.GAP
        nir_lane = QRectF(self.GUTTER, y, self.plot_w(), self.LANE_H)
        y += self.LANE_H
        axis = QRectF(self.GUTTER, y, self.plot_w(), self.AXIS_H)
        return dict(chart=chart, vis_dots=vis_dots, vis_lane=vis_lane,
                    nir_dots=nir_dots, nir_lane=nir_lane, axis=axis)

    def plot_w(self):
        return max(10, self.width() - self.GUTTER - 14)

    def x_of(self, t):
        return self.GUTTER + (t - self.t0) / (self.t1 - self.t0) * self.plot_w()

    def t_of(self, x):
        return self.t0 + (x - self.GUTTER) / self.plot_w() * (self.t1 - self.t0)

    def band_span(self, key):
        """Vertical extent of the phase band of a window."""
        r = self.rows()
        if key.startswith("VIS"):
            return r["chart"].top(), r["vis_lane"].bottom()
        return r["nir_dots"].top(), r["nir_lane"].bottom()

    def edge_time(self, key, edge):
        w = self.m.windows.get(key)
        if w is None:
            return None
        times = self.m.times_on_vis_axis(key.split()[0])
        idx = w.first if edge == "first" else w.last
        # The band covers whole frames: edges half a frame out
        period = self.m.band(key.split()[0]).period()
        return float(times[idx]) + (-0.5 if edge == "first" else 0.5) * period

    def editable(self, key):
        return not (key == "NIR survey" and self.m.shift is not None)

    def handle_at(self, pos):
        best, best_d = None, 7.0
        for key in ("VIS sync", "VIS survey", "NIR sync", "NIR survey"):
            if not self.editable(key):
                continue
            y0, y1 = self.band_span(key)
            if not (y0 - 4 <= pos.y() <= y1 + 4):
                continue
            for edge in ("first", "last"):
                t = self.edge_time(key, edge)
                if t is None:
                    continue
                d = abs(self.x_of(t) - pos.x())
                if d < best_d:
                    best, best_d = (key, edge), d
        return best

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        r = self.rows()
        p.save()
        p.setClipRect(QRectF(self.GUTTER, 0, self.plot_w(), self.height()))
        self._paint_chart(p, r["chart"])
        self._paint_dots(p, r["vis_dots"], "VIS")
        self._paint_lane(p, r["vis_lane"], "VIS")
        self._paint_dots(p, r["nir_dots"], "NIR")
        self._paint_lane(p, r["nir_lane"], "NIR")
        self._paint_outside_veil(p, r)
        self._paint_bands(p)
        self._paint_handles(p)
        self._paint_cursor(p, r)
        p.restore()
        self._paint_axis(p, r["axis"])
        self._paint_gutter(p, r)

    def _paint_gutter(self, p, r):
        p.setPen(MUTED)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        al = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        p.drawText(QRectF(0, r["chart"].top(), self.GUTTER - 10, 16), al, f"{self.alt_max:.0f} m")
        p.drawText(QRectF(0, r["chart"].bottom() - 16, self.GUTTER - 10, 16), al, "0 m")
        p.drawText(QRectF(0, r["chart"].center().y() - 8, self.GUTTER - 10, 16), al, "Altitude")
        fb = QFont(f)
        fb.setBold(True)
        p.setFont(fb)
        p.setPen(BLUE)
        p.drawText(QRectF(0, r["vis_lane"].top(), self.GUTTER - 10, r["vis_lane"].height()), al, "Visible")
        p.setPen(NIR_ACCENT)
        p.drawText(QRectF(0, r["nir_lane"].top(), self.GUTTER - 10, r["nir_lane"].height()), al, "Infrared")
        p.setFont(f)
        p.setPen(MUTED)
        p.drawText(QRectF(0, r["vis_dots"].top() - 2, self.GUTTER - 10, 14), al, "target")
        p.drawText(QRectF(0, r["nir_dots"].top() - 2, self.GUTTER - 10, 14), al, "target")

    def _paint_chart(self, p, rect):
        p.setPen(QPen(GRID, 1))
        for k in range(5):
            y = rect.bottom() - k * rect.height() / 4
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        frames = self.m.vis.frames
        pts = [(self.x_of(t), f.alt) for t, f in zip(self.m.t_vis, frames) if f.alt is not None]
        if not pts:
            p.setPen(MUTED)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No altitude in the visible images")
            return
        scale = (rect.height() - 6) / max(self.alt_max, 1e-6)
        path = QPainterPath()
        path.moveTo(pts[0][0], rect.bottom() - pts[0][1] * scale)
        for x, a in pts[1:]:
            path.lineTo(x, rect.bottom() - a * scale)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1][0], rect.bottom())
        fill.lineTo(pts[0][0], rect.bottom())
        fill.closeSubpath()
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        c0, c1 = QColor(BLUE), QColor(BLUE)
        c0.setAlpha(70)
        c1.setAlpha(8)
        grad.setColorAt(0, c0)
        grad.setColorAt(1, c1)
        p.fillPath(fill, QBrush(grad))
        p.setPen(QPen(BLUE, 2))
        p.drawPath(path)

    def _paint_bands(self, p):
        for key, w in self.m.windows.items():
            if w is None:
                continue
            color = PHASE_COLORS["sync" if "sync" in key else "survey"]
            x0, x1 = self.x_of(self.edge_time(key, "first")), self.x_of(self.edge_time(key, "last"))
            y0, y1 = self.band_span(key)
            fill = QColor(color)
            fill.setAlpha(30)
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            p.fillRect(rect, fill)
            p.fillRect(QRectF(x0, y1 - 4, x1 - x0, 4), color)   # strip under the filmstrip
            if not self.editable(key):   # derived from the visible survey: hatched
                hatch = QColor(color)
                hatch.setAlpha(60)
                p.fillRect(rect, QBrush(hatch, Qt.BrushStyle.BDiagPattern))
            # Phase label: a pill at the top of the visible band, at the bottom of the infrared one
            label = {"VIS sync": "Synchronisation", "VIS survey": "Survey",
                     "NIR sync": "IR sync", "NIR survey": "IR survey · follows visible"}[key]
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 0.85)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(label) + 12
            if x1 - x0 > tw + 8:
                py = y0 + 4 if key.startswith("VIS") else y1 - 20
                pill = QRectF(x0 + 8, py, tw, 16)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 225))
                p.drawRoundedRect(pill, 8, 8)
                p.setPen(color)
                p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(self.font())

    def _paint_outside_veil(self, p, r):
        """Dim the filmstrip frames that belong to no phase: the selection stands out."""
        veil = QColor(250, 251, 252, 150)
        for name, lane in (("VIS", r["vis_lane"]), ("NIR", r["nir_lane"])):
            spans = sorted((self.x_of(self.edge_time(k, "first")), self.x_of(self.edge_time(k, "last")))
                           for k, w in self.m.windows.items() if w is not None and k.startswith(name))
            x = lane.left()
            for a, b in spans + [(lane.right(), lane.right())]:
                if a > x:
                    p.fillRect(QRectF(x, lane.top(), a - x, lane.height()), veil)
                x = max(x, b)

    def _paint_dots(self, p, rect, name):
        band = self.m.band(name)
        rot = self.m.vis_rot if name == "VIS" else self.m.nir_rot
        times = self.m.times_on_vis_axis(name)
        cy = rect.center().y()
        for i, f in enumerate(band.frames):
            if not f.scanned:
                continue
            x = self.x_of(times[i])
            if x < rect.left() - 5 or x > rect.right() + 5:
                continue
            if f.marker_angle is None:
                p.setPen(QPen(QColor("#C5CFDA"), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(x, cy), 2.0, 2.0)
            else:
                c = SYNC if rot[i] else MUTED
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(QPointF(x, cy), 3.0, 3.0)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_lane(self, p, rect, name):
        band = self.m.band(name)
        p.fillRect(rect, PANEL)
        if not band.frames:
            p.setPen(MUTED)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No infrared image")
            return
        times = self.m.times_on_vis_axis(name)
        tile_w = rect.height() * 4 / 3
        lo, hi = float(times[0]), float(times[-1])
        x_lo, x_hi = self.x_of(lo), self.x_of(hi)
        # Slots of one thumbnail: each shows the frame nearest to its centre
        start = max(rect.left(), x_lo - tile_w / 2)
        stop = min(rect.right(), x_hi + tile_w / 2)
        x = start
        while x < stop:
            w = min(tile_w, stop - x)
            idx = self.m.nearest(name, self.t_of(x + w / 2))
            pix = self.m.thumb(name, idx)
            target = QRectF(x + 1, rect.top() + 1, w - 2, rect.height() - 2)
            if pix is not None:
                sw = pix.width() * (w - 2) / tile_w
                src = QRectF((pix.width() - sw) / 2, 0, sw, pix.height())
                p.drawPixmap(target, pix, src)
            x += tile_w
        # Frame ticks when zoomed in enough to tell them apart
        px_per_frame = abs(self.x_of(times[-1]) - self.x_of(times[0])) / max(1, len(times) - 1)
        if px_per_frame > 5:
            p.setPen(QPen(QColor(255, 255, 255, 160), 1))
            for t in times:
                xt = self.x_of(t)
                p.drawLine(QPointF(xt, rect.bottom() - 5), QPointF(xt, rect.bottom()))
        # Outside the recording: veil
        veil = QColor(255, 255, 255, 200)
        if x_lo > rect.left():
            p.fillRect(QRectF(rect.left(), rect.top(), x_lo - rect.left() - tile_w / 2, rect.height()), veil)
        if name == "NIR" and self.m.shift is None:
            p.setPen(NIR_ACCENT)
            p.drawText(rect.adjusted(6, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       "not aligned yet: placed from its first image")

    def _paint_handles(self, p):
        for key in ("VIS sync", "VIS survey", "NIR sync", "NIR survey"):
            if self.m.windows.get(key) is None or not self.editable(key):
                continue
            color = PHASE_COLORS["sync" if "sync" in key else "survey"]
            y0, y1 = self.band_span(key)
            for edge in ("first", "last"):
                x = self.x_of(self.edge_time(key, edge))
                sel = self.selected == (key, edge)
                p.setPen(QPen(color, 3 if sel else 2))
                p.drawLine(QPointF(x, y0), QPointF(x, y1))
                grip = QRectF(x - 5, (y0 + y1) / 2 - 12, 10, 24)
                p.setBrush(color if sel else QColor("white"))
                p.setPen(QPen(color, 2))
                p.drawRoundedRect(grip, 4, 4)
                p.setPen(QPen(QColor("white") if sel else color, 1))
                for dy in (-4, 0, 4):
                    cy = grip.center().y() + dy
                    p.drawLine(QPointF(x - 2, cy), QPointF(x + 2, cy))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_cursor(self, p, r):
        if self.hover_t is None:
            return
        x = self.x_of(self.hover_t)
        p.setPen(QPen(CURSOR, 1.5))
        p.drawLine(QPointF(x, r["chart"].top()), QPointF(x, r["nir_lane"].bottom()))
        # Altitude bubble
        idx = self.m.nearest("VIS", self.hover_t)
        alt = self.m.vis.frames[idx].alt if idx is not None else None
        text = fmt_time(self.hover_t) + (f"  ·  {alt:.1f} m" if alt is not None else "")
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 14
        bx = min(max(x - w / 2, r["chart"].left()), r["chart"].right() - w)
        bubble = QRectF(bx, r["chart"].top(), w, 20)
        p.setBrush(CURSOR)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(bubble, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_axis(self, p, rect):
        span = self.t1 - self.t0
        steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200]
        step = next((s for s in steps if span / s <= max(4, self.plot_w() / 90)), steps[-1])
        p.setPen(MUTED)
        t = np.ceil(self.t0 / step) * step
        while t <= self.t1:
            x = self.x_of(t)
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.top() + 4))
            sign, a = ("-" if t < 0 else ""), abs(int(round(t)))
            p.drawText(QRectF(x - 40, rect.top() + 4, 80, 16), Qt.AlignmentFlag.AlignCenter,
                       f"{sign}{a // 60}:{a % 60:02d}")
            t += step

    # ---- interaction
    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag and self._drag[0] == "pan":
            _, x0, t0, t1 = self._drag
            dt = (pos.x() - x0) / self.plot_w() * (t1 - t0)
            self.t0, self.t1 = t0 - dt, t1 - dt
            self.update()
            return
        if self._drag:
            key, edge = self._drag
            band = key.split()[0]
            idx = self.m.nearest(band, self.t_of(pos.x()))
            if idx is not None:
                self.m.set_edge(key, edge, idx)
                self.edited.emit(key, edge)
        if pos.x() >= self.GUTTER:
            self.hover_t = self.t_of(pos.x())
            self.hovered.emit(self.hover_t)
        h = self.handle_at(pos)
        self.setCursor(Qt.CursorShape.SizeHorCursor if (h or (self._drag and self._drag[0] != "pan"))
                       else Qt.CursorShape.CrossCursor)
        self.update()

    def leaveEvent(self, _):
        self.hover_t = None
        self.left.emit()
        self.update()

    def mousePressEvent(self, e):
        pos = e.position()
        h = self.handle_at(pos)
        if h and e.button() == Qt.MouseButton.LeftButton:
            self._drag = h
            self.selected = h
            self.picked.emit(*h)
        else:
            self._drag = ("pan", pos.x(), self.t0, self.t1)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseReleaseEvent(self, _):
        self._drag = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDoubleClickEvent(self, _):
        self.t0, self.t1 = self.m.span()
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps == 0:
            return
        tc = self.t_of(e.position().x())
        factor = 0.8 ** steps
        lo, hi = self.m.span()
        new_span = min(hi - lo, max(10.0, (self.t1 - self.t0) * factor))
        a = (tc - self.t0) / (self.t1 - self.t0)
        self.t0 = tc - a * new_span
        self.t1 = self.t0 + new_span
        self.update()

    def focus_on(self, t0, t1):
        pad = 0.15 * (t1 - t0) + 5
        self.t0, self.t1 = t0 - pad, t1 + pad
        self.update()


# ---------------------------------------------------------------------------
#  Keypoint card (real images of a keypoint, with nudge buttons)
# ---------------------------------------------------------------------------
class ImageTile(QLabel):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #E9EDF2; border-radius: 4px; color: #6B7785;")

    def show_pixmap(self, pix: Optional[QPixmap], placeholder=""):
        if pix is None:
            self.setPixmap(QPixmap())
            self.setText(placeholder)
            return
        self.setText("")
        self.setPixmap(pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
                       .copy(0, 0, self.width(), self.height()))


class KeypointCard(QFrame):
    nudged = pyqtSignal(str, str, int)    # window key, edge, delta
    clicked = pyqtSignal(str)             # phase/edge id "sync:first"

    def __init__(self, title, phase, edge, parent=None):
        super().__init__(parent)
        self.phase, self.edge = phase, edge
        self.color = PHASE_COLORS[phase]
        self.setObjectName("card")
        self.set_selected(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setStyleSheet(f"color: {self.color.name()}; font-weight: bold; font-size: 11pt;")
        lay.addWidget(head)
        imgs = QHBoxLayout()
        imgs.setSpacing(6)
        self.vis_tile = ImageTile(150, 112)
        self.nir_tile = ImageTile(150, 112)
        imgs.addWidget(self.vis_tile)
        imgs.addWidget(self.nir_tile)
        lay.addLayout(imgs)
        self.rows = {}
        for band, color in (("VIS", BLUE), ("NIR", NIR_ACCENT)):
            row = QHBoxLayout()
            row.setSpacing(4)
            lab = QLabel()
            lab.setStyleSheet(f"color: {color.name()};")
            lab.setTextFormat(Qt.TextFormat.RichText)
            prev, nxt = QToolButton(), QToolButton()
            prev.setText("◀")
            nxt.setText("▶")
            for b, d in ((prev, -1), (nxt, +1)):
                b.setStyleSheet(NUDGE_STYLE)
                b.setAutoRepeat(True)
                b.setToolTip("Previous / next image")
                b.clicked.connect(lambda _=False, band=band, d=d:
                                  self.nudged.emit(f"{band} {self.phase}", self.edge, d))
            row.addWidget(lab, 1)
            row.addWidget(prev)
            row.addWidget(nxt)
            lay.addLayout(row)
            self.rows[band] = (lab, prev, nxt)

    def set_selected(self, on):
        border = self.color.name() if on else "#DDE3EA"
        width = 2 if on else 1
        self.setStyleSheet(f"#card {{ background: white; border: {width}px solid {border}; border-radius: 8px; }}")

    def mousePressEvent(self, _):
        self.clicked.emit(f"{self.phase}:{self.edge}")

    def refresh(self, m: TimelineModel):
        for band, tile in (("VIS", self.vis_tile), ("NIR", self.nir_tile)):
            key = f"{band} {self.phase}"
            w = m.windows.get(key)
            lab, prev, nxt = self.rows[band]
            derived = key == "NIR survey" and m.shift is not None
            prev.setEnabled(w is not None and not derived)
            nxt.setEnabled(w is not None and not derived)
            if w is None:
                tile.show_pixmap(None, "—")
                lab.setText(f"<b>{'Visible' if band == 'VIS' else 'Infrared'}</b> · not set")
                continue
            idx = w.first if self.edge == "first" else w.last
            f = m.band(band).frames[idx]
            tile.show_pixmap(m.thumb(band, idx), f.name)
            t = m.times_on_vis_axis(band)[idx]
            extra = f" · {f.alt:.1f} m" if f.alt is not None else ""
            note = " · <i>follows visible</i>" if derived else ""
            lab.setText(f"<b>{Path(f.name).stem}</b> · {fmt_time(t)}{extra}{note}")


# ---------------------------------------------------------------------------
#  Analysis thread
# ---------------------------------------------------------------------------
class AnalysisThread(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, mission):
        super().__init__()
        self.mission = mission
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            result = FT.analyse_mission(self.mission, progress=self.progress.emit,
                                        cancelled=lambda: self._stop)
            self.done.emit(result)
        except InterruptedError:
            pass
        except Exception as e:  # shown to the user
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
#  Dialog
# ---------------------------------------------------------------------------
class FlightTimelineDialog(QDialog):
    """Step 2. Accepted when the user confirms; `action` tells what to do next:
    "synchronize" (open Step 3), "close", or "classic" (rejected: open the classic selection)."""

    def __init__(self, mission: Path, parent=None):
        super().__init__(parent)
        self.mission = Path(mission)
        self.action = "close"
        self.model: Optional[TimelineModel] = None
        self.view: Optional[TimelineView] = None
        self.cards = []
        self.setWindowTitle(f"Step 2 – Flight timeline · {self.mission.name}")
        self.setStyleSheet("QDialog { background: #FAFBFC; } QLabel { color: #1F2933; }")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        w, h = min(1500, int(g.width() * 0.95)), min(1000, int(g.height() * 0.95))
        self.setGeometry(g.x() + (g.width() - w) // 2, g.y() + (g.height() - h) // 2, w, h)
        self._build()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._show_hover_preview)
        self._pending_t = None
        self.thread = AnalysisThread(self.mission)
        self.thread.progress.connect(self._on_progress)
        self.thread.done.connect(self._on_analysed)
        self.thread.failed.connect(self._on_failed)
        self.thread.start()

    # ---- layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        # Header
        head = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Flight timeline")
        title.setStyleSheet("font-size: 17pt; font-weight: bold; color: #17365D;")
        self.subtitle = QLabel("Reading the images of the mission…")
        self.subtitle.setStyleSheet("color: #6B7785;")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_target = self._chip(SYNC)
        self.chip_shift = self._chip(NIR_ACCENT)
        self.chip_survey = self._chip(SURVEY)
        for c in (self.chip_target, self.chip_shift, self.chip_survey):
            chips.addWidget(c)
        head.addLayout(chips)
        root.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet("QProgressBar { background: #E4E8EE; border: none; border-radius: 3px; }"
                                    "QProgressBar::chunk { background: #17365D; border-radius: 3px; }")
        root.addWidget(self.progress)
        self.messages = QLabel()
        self.messages.setWordWrap(True)
        self.messages.setStyleSheet("background: #FFF4E0; color: #7A4B00; border-radius: 6px; padding: 6px 10px;")
        self.messages.hide()
        root.addWidget(self.messages)

        # Keypoint cards
        cards = QHBoxLayout()
        cards.setSpacing(10)
        for title_, phase, edge in KEYPOINTS:
            c = KeypointCard(title_, phase, edge)
            c.nudged.connect(self._on_nudge)
            c.clicked.connect(self._on_card_clicked)
            c.setEnabled(False)
            cards.addWidget(c)
            self.cards.append(c)
        root.addLayout(cards)

        # Preview + time line
        mid = QHBoxLayout()
        mid.setSpacing(10)
        self.preview_box = QFrame()
        self.preview_box.setObjectName("pv")
        self.preview_box.setStyleSheet("#pv { background: white; border: 1px solid #DDE3EA; border-radius: 8px; }")
        pv = QGridLayout(self.preview_box)
        pv.setContentsMargins(10, 8, 10, 8)
        self.pv_vis = ImageTile(400, 300)
        self.pv_nir = ImageTile(400, 300)
        self.pv_vis_cap = QLabel("Visible")
        self.pv_nir_cap = QLabel("Infrared")
        for lab in (self.pv_vis_cap, self.pv_nir_cap):
            lab.setTextFormat(Qt.TextFormat.RichText)
        pv.addWidget(self.pv_vis, 0, 0)
        pv.addWidget(self.pv_nir, 0, 1)
        pv.addWidget(self.pv_vis_cap, 1, 0)
        pv.addWidget(self.pv_nir_cap, 1, 1)
        mid.addStretch(1)
        mid.addWidget(self.preview_box)
        mid.addStretch(1)
        root.addLayout(mid, 1)

        self.view_holder = QVBoxLayout()
        root.addLayout(self.view_holder)
        hint = QLabel("Hover to preview · drag a band edge to adjust · ◀ ▶ or the arrow keys to nudge "
                      "the selected keypoint · wheel to zoom · drag to pan · double-click to see the whole flight")
        hint.setStyleSheet("color: #8A94A0; font-size: 9pt;")
        root.addWidget(hint)

        # Footer
        foot = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.setFixedWidth(36)
        self.btn_help.clicked.connect(self._on_help)
        self.btn_classic = QPushButton("Classic selection…")
        self.btn_classic.setStyleSheet(SECONDARY_STYLE)
        self.btn_classic.setToolTip("Pick the 5 reference images of each camera by hand (previous Step 2).")
        self.btn_classic.clicked.connect(self._on_classic)
        self.btn_reset = QPushButton("Back to detection")
        self.btn_reset.setStyleSheet(SECONDARY_STYLE)
        self.btn_reset.setToolTip("Undo the manual changes.")
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.setEnabled(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(SECONDARY_STYLE)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Save only")
        self.btn_save.setStyleSheet(SECONDARY_STYLE)
        self.btn_save.setToolTip("Save the phases and close (Step 3 can be run later).")
        self.btn_save.clicked.connect(lambda: self._confirm("close"))
        self.btn_confirm = QPushButton("Confirm and synchronize  ▶")
        self.btn_confirm.setStyleSheet(PRIMARY_STYLE)
        self.btn_confirm.setToolTip("Save the phases and run Step 3 (camera synchronisation).")
        self.btn_confirm.clicked.connect(lambda: self._confirm("synchronize"))
        for b in (self.btn_save, self.btn_confirm):
            b.setEnabled(False)
        foot.addWidget(self.btn_help)
        foot.addWidget(self.btn_classic)
        foot.addWidget(self.btn_reset)
        foot.addStretch(1)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_save)
        foot.addWidget(self.btn_confirm)
        root.addLayout(foot)

        try:
            import IRD_Interactive_help as Help
            for widget, label in ((self.btn_confirm, "btn:step2_confirm"), (self.btn_save, "btn:step2_confirm"),
                                  (self.btn_classic, "btn:step2_classic")):
                Help.attach_help(widget, label, widget.toolTip(), parent=self)
        except Exception as e:  # help is a convenience
            print(f"Help not attached: {e}")

        for seq, d in (("Left", -1), ("Right", +1)):
            QShortcut(QKeySequence(seq), self, activated=lambda d=d: self._nudge_selected(d))

    @staticmethod
    def _chip(color):
        lab = QLabel()
        bg = QColor(color)
        lab.setStyleSheet(f"background: rgba({bg.red()},{bg.green()},{bg.blue()},28);"
                          f"color: {bg.name()}; border-radius: 10px; padding: 4px 10px; font-weight: bold;")
        lab.hide()
        return lab

    @staticmethod
    def _set_chip(lab, text, tip=""):
        lab.setText(text)
        lab.setToolTip(tip)
        lab.setVisible(bool(text))

    # ---- analysis
    def _on_progress(self, pct, text):
        self.progress.setValue(pct)
        self.subtitle.setText(text)

    def _on_failed(self, message):
        self.progress.hide()
        self.subtitle.setText("The automatic detection failed.")
        QMessageBox.warning(self, "Flight timeline",
                            f"The images could not be analysed:\n{message}\n\n"
                            "Use the classic selection instead.")

    def _on_analysed(self, result):
        vis, nir, proposal = result
        self.progress.hide()
        self.model = TimelineModel(self.mission, vis, nir, proposal)
        self._restore_saved()
        self.view = TimelineView(self.model)
        self.view.hovered.connect(self._on_hover)
        self.view.left.connect(self._show_selected_preview)
        self.view.edited.connect(self._on_edited)
        self.view.picked.connect(lambda key, edge: self._select(key.split()[1], edge))
        self.view_holder.addWidget(self.view)
        n = len(vis.frames)
        self.subtitle.setText(
            f"{n} visible and {len(nir.frames)} infrared images. Phases detected from the altitude and "
            "the rotating target: check them, adjust if needed, then confirm.")
        self._fill_chips()
        if proposal.messages:
            self.messages.setText("⚠  " + "\n⚠  ".join(proposal.messages))
            self.messages.show()
        for c in self.cards:
            c.setEnabled(True)
        for b in (self.btn_save, self.btn_confirm, self.btn_reset):
            b.setEnabled(True)
        self._select("sync", "first")
        self._refresh()

    def _restore_saved(self):
        """A mission confirmed before reopens with the confirmed windows."""
        state = FT.load_state(self.mission)
        if not state:
            return
        m = self.model
        for key, pair in (state.get("confirmed") or {}).items():
            band = m.band(key.split()[0])
            w = FT.window_from_names(band.frames, pair)
            if w is not None and key in m.windows:
                m.windows[key] = w
        m.update_nir_survey()

    def _fill_chips(self):
        p, m = self.model.proposal, self.model
        found = m.vis.segments and (m.nir.segments or not m.nir.frames)
        self._set_chip(self.chip_target, "✓ Target found" if found else "",
                       "The rotating ArUco target was found on the visible and infrared previews.")
        self._set_chip(self.chip_shift, f"✓ Infrared aligned  {m.shift:+.1f} s" if m.shift is not None else "",
                       "Coarse offset between the camera clocks, from the target rotation seen by both "
                       f"cameras (fit {p.shift_rms or 0:.1f}°). Step 3 computes it precisely.")
        w = m.windows.get("VIS survey")
        text = ""
        if w is not None:
            alts = [f.alt for f in m.vis.frames[w.first:w.last + 1] if f.alt is not None]
            text = f"✓ Survey {len(w)} images" + (f" · {np.median(alts):.0f} m" if alts else "")
        self._set_chip(self.chip_survey, text)

    # ---- selection / editing
    def _select(self, phase, edge):
        self.selected = (phase, edge)
        for c in self.cards:
            c.set_selected((c.phase, c.edge) == self.selected)
        if self.view:
            self.view.selected = (f"VIS {phase}", edge)
            self.view.update()
        self._show_selected_preview()

    def _on_card_clicked(self, ident):
        phase, edge = ident.split(":")
        self._select(phase, edge)
        if self.view and self.model.windows.get(f"VIS {phase}") is not None:
            t = self.view.edge_time(f"VIS {phase}", edge)
            if not (self.view.t0 < t < self.view.t1):
                lo, hi = self.model.span()
                self.view.t0, self.view.t1 = lo, hi
                self.view.update()

    def _on_nudge(self, key, edge, delta):
        m = self.model
        w = m.windows.get(key)
        if w is None:
            return
        idx = (w.first if edge == "first" else w.last) + delta
        m.set_edge(key, edge, idx)
        self._select(key.split()[1], edge)
        self._show_keypoint_preview(key, edge)
        self._refresh()

    def _nudge_selected(self, delta):
        if self.model and getattr(self, "selected", None):
            phase, edge = self.selected
            key = self.view.selected[0] if self.view and self.view.selected else f"VIS {phase}"
            self._on_nudge(key, edge, delta)

    def _on_edited(self, key, edge):
        self._show_keypoint_preview(key, edge, live=True)
        self._refresh()

    def _on_reset(self):
        self.model.reset()
        self._select("sync", "first")
        self._refresh()

    def _refresh(self):
        for c in self.cards:
            c.refresh(self.model)
        self._fill_chips()
        if self.view:
            self.view.update()

    # ---- previews
    def _on_hover(self, t):
        self._pending_t = t
        if not self._preview_timer.isActive():
            self._preview_timer.start(25)

    def _show_hover_preview(self):
        if self._pending_t is None or self.model is None:
            return
        t = self._pending_t
        self._show_pair(self.model.nearest("VIS", t), self.model.nearest("NIR", t), t)

    def _show_selected_preview(self):
        if self.model is None or not getattr(self, "selected", None):
            return
        phase, edge = self.selected
        self._show_keypoint_preview(f"VIS {phase}", edge)

    def _show_keypoint_preview(self, key, edge, live=False):
        m = self.model
        band, phase = key.split()
        w = m.windows.get(key)
        if w is None:
            return
        idx = w.first if edge == "first" else w.last
        t = float(m.times_on_vis_axis(band)[idx])
        other = "NIR" if band == "VIS" else "VIS"
        ow = m.windows.get(f"{other} {phase}")
        oidx = (ow.first if edge == "first" else ow.last) if ow is not None else m.nearest(other, t)
        vis_idx, nir_idx = (idx, oidx) if band == "VIS" else (oidx, idx)
        self._show_pair(vis_idx, nir_idx, t)

    def _show_pair(self, vis_idx, nir_idx, t):
        m = self.model
        for band, idx, tile, cap, color in (("VIS", vis_idx, self.pv_vis, self.pv_vis_cap, BLUE),
                                            ("NIR", nir_idx, self.pv_nir, self.pv_nir_cap, NIR_ACCENT)):
            frames = m.band(band).frames
            if idx is None or not frames:
                tile.show_pixmap(None, "—")
                cap.setText("")
                continue
            tile.show_pixmap(m.preview(band, idx))
            f = frames[idx]
            tb = float(m.times_on_vis_axis(band)[idx])
            bits = [f"<b style='color:{color.name()}'>{'Visible' if band == 'VIS' else 'Infrared'}</b>",
                    Path(f.name).stem, fmt_time(tb)]
            if f.alt is not None:
                bits.append(f"{f.alt:.1f} m")
            if f.scanned:
                bits.append("target turning" if (m.vis_rot if band == "VIS" else m.nir_rot)[idx]
                            else ("target still" if f.marker_angle is not None else "no target"))
            cap.setText("  ·  ".join(bits))

    # ---- closing
    def _confirm(self, action):
        m = self.model
        missing = [k for k in ("VIS sync", "VIS survey") if m.windows.get(k) is None]
        if m.nir.frames and m.windows.get("NIR sync") is None:
            missing.append("NIR sync")
        if missing:
            QMessageBox.warning(self, "Flight timeline", "Please define: " + ", ".join(missing))
            return
        if len(m.windows["NIR sync"] or []) < 2 if m.nir.frames else False:
            QMessageBox.warning(self, "Flight timeline",
                                "The infrared synchronisation needs at least two images.")
            return
        try:
            FT.write_transfer_info(self.mission, "VIS", m.vis.frames, m.windows["VIS sync"], m.windows["VIS survey"])
            if m.nir.frames:
                FT.write_transfer_info(self.mission, "NIR", m.nir.frames, m.windows["NIR sync"],
                                       m.windows.get("NIR survey"))
            FT.save_state(self.mission, m.vis, m.nir, m.proposal, dict(m.windows), m.shift)
        except OSError as e:
            QMessageBox.critical(self, "Flight timeline", f"Could not save the selection:\n{e}")
            return
        self.action = action
        self.accept()

    def _on_classic(self):
        self.action = "classic"
        self.reject()

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help("ch:step2", parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")

    def done(self, r):
        if self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)
        super().done(r)


def main():
    """Standalone: python IRD_Interactive_timeline.py <mission folder>"""
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = FlightTimelineDialog(Path(sys.argv[1]))
    dlg.show()
    app.exec()
    print("action:", dlg.action, "result:", dlg.result())


if __name__ == "__main__":
    main()
