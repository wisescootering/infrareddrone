# -*- coding: utf-8 -*-
"""
Step 6: spectral balance of the multispectral images (window).

    left      the layer adjusted (RGB, R, G, B or NIR), its exposure, gamma,
              contrast and brightness, its tone curve; the automatic NIR
    centre    the image of the selected point, original against balanced:
              swipe curtain, blink or side by side, in visible, NIR or false
              colours (NIR, red, green); or the map
    right     the point (Validate writes its balanced bands), the histograms
              of the four bands, the map, previous / next
    bottom    the images of the map (false colour thumbnails), a star on
              those balanced

The computations and the files are in spectral_balance.py (no Qt). The
settings are saved when the window closes; the balanced bands of an image are
written when it is validated (or all at once), and the map writes those
missing when it is built.
"""
from __future__ import annotations

import dataclasses
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThread, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
                             QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
                             QStackedWidget, QVBoxLayout, QWidget)

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))
import IRD_Interactive_map as MapV  # noqa: E402
import IRD_Interactive_review as Rv  # noqa: E402
import shoot_review as R  # noqa: E402
import spectral_balance as SB  # noqa: E402
import IRD_Interactive_look as Look  # noqa: E402
from IRD_Interactive_look import (CURSOR, DIALOG_STYLE, MESSAGE_STYLE, MUTED, PRIMARY_STYLE,  # noqa: E402
                                  PROGRESS_STYLE, SECONDARY_STYLE, SUBTITLE_STYLE, SURVEY, bgr_to_qimage,
                                  fit_to_screen, step_window_title)

WINDOW_NAME = "Spectral balance"
HELP_LABEL = "btn:step6_balance"
PREVIEW_WIDTH = 1600      # the window works on copies this wide (the files are written full size)
CACHE_POINTS = 4

BAND_COLORS = {"red": QColor("#D64541"), "green": QColor("#2E9E4F"), "blue": QColor("#2F6FD6"),
               "nir": QColor("#7B3FA0"), "rgb": QColor("#3E4C59")}
LAYER_TEXT = {"rgb": "RGB", "red": "R", "green": "G", "blue": "B", "nir": "NIR"}
LAYER_TIPS = {
    "rgb": "The three visible bands together.",
    "red": "The red band alone (after the RGB settings).",
    "green": "The green band alone (after the RGB settings).",
    "blue": "The blue band alone (after the RGB settings).",
    "nir": "The near infrared band.",
}
BALANCED_COLOR = CURSOR                 # orange: balanced bands written (star)
STALE_COLOR = QColor("#C5CFDA")         # written, but the balance or the image changed since
MODES = [  # (key, text, tooltip)
    ("swipe", "Swipe", "Original on the left of the curtain, balanced on the right: drag the curtain."),
    ("blink", "Blink", "Original and balanced shown in turn."),
    ("side", "Side by side", "Original on the left, balanced on the right."),
    ("map", "Map", "Where the image was taken: the flight, the images of the map, the ground covered by the "
                   "image; aerial photos or maps in the background (online, optional)."),
]
DISPLAYS = [  # (key, text, tooltip)
    ("vis", "Visible", "The red, green and blue bands."),
    ("nir", "NIR", "The near infrared band, in grey."),
    ("vir", "VIR", "False colours: NIR in red, red in green, green in blue (vegetation in red)."),
]


# ---------------------------------------------------------------------------
#  Images: reading in the background, rendering
# ---------------------------------------------------------------------------
class _LoadSignals(QObject):
    loaded = pyqtSignal(int, object)       # number, {"preview", "small", "width"} or {} (unreadable)


class LoadJob(QRunnable):
    """The four bands of a point: a copy PREVIEW_WIDTH wide (the view), the
    statistics copy of the automatic NIR (from the full image, as when the
    bands are written) and the full width (zoom in %)."""

    def __init__(self, mission: Path, number: int):
        super().__init__()
        self.mission, self.number = mission, number
        self.signals = _LoadSignals()

    def run(self):
        import cv2
        try:
            bands = SB.read_bands(SB.source_paths(self.mission, self.number))
            small = SB.stats_copy(bands)
            width = bands.shape[1]
            if width > PREVIEW_WIDTH:
                s = PREVIEW_WIDTH / width
                preview = cv2.resize(bands, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            else:
                preview = bands
            out = {"preview": np.ascontiguousarray(preview), "small": small, "width": width}
        except Exception as e:     # never leave the point "loading" for ever
            print(f"Spectral balance: IRD_{self.number:04d} not read ({e})")
            out = {}
        self.signals.loaded.emit(self.number, out)


def lut8_set(balance: SB.Balance) -> Dict[str, np.ndarray]:
    return {band: SB.lut8(balance, band) for band in SB.BANDS}


def band8(preview: np.ndarray, luts: Dict[str, np.ndarray], band: str) -> np.ndarray:
    return luts[band][preview[..., SB.BANDS.index(band)]]


def render(preview: np.ndarray, luts: Dict[str, np.ndarray], display: str) -> QImage:
    """The QImage of the preview through the tables: "vis", "nir" or "vir"."""
    if display == "nir":
        gray = np.ascontiguousarray(band8(preview, luts, "nir"))
        h, w = gray.shape
        return QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    order = ("red", "green", "blue") if display == "vis" else ("nir", "red", "green")
    rgb = np.ascontiguousarray(np.stack([band8(preview, luts, b) for b in order], axis=-1))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def histograms(preview: np.ndarray, luts: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    sub = preview[::2, ::2]
    return {b: np.bincount(band8(sub, luts, b).ravel(), minlength=256) for b in SB.BANDS}


IDENTITY_LUTS = lut8_set(SB.Balance())


class _WriteSignals(QObject):
    progress = pyqtSignal(int, int, int, str)     # number, done, total, error ("" = written)
    finished = pyqtSignal()


class WriteJob(QRunnable):
    """Write the balanced bands of the points, one after the other (stoppable
    between two images)."""

    def __init__(self, mission: Path, numbers: List[int], settings: SB.Settings):
        super().__init__()
        self.mission, self.numbers = mission, list(numbers)
        self.settings = SB.Settings.from_json(settings.to_json())     # a copy: the window goes on editing
        self.stopped = False
        self.running = True           # False once run() returned (read by the window when it closes)
        self.signals = _WriteSignals()

    def run(self):
        total = len(self.numbers)
        for k, number in enumerate(self.numbers):
            if self.stopped:
                break
            try:
                SB.write_point(self.mission, number, self.settings)
                error = ""
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
            self.signals.progress.emit(number, k + 1, total, error)
        self.running = False
        self.signals.finished.emit()


class ThumbThread(QThread):
    """False colour thumbnails of the points (the cache of the review)."""
    thumb = pyqtSignal(int, QImage)

    def __init__(self, output: Path, points):
        super().__init__()
        self.output, self.points = output, list(points)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for p in self.points:
            if self._stop:
                return
            path = p.vir_image or p.vis_image
            if path is None:
                continue
            try:
                img = R.cached_thumbnail(self.output, path)
            except Exception as e:
                print(f"Spectral balance: no thumbnail for {p.stem} ({e})")
                continue
            if img is not None:
                self.thumb.emit(p.number, bgr_to_qimage(img))


# ---------------------------------------------------------------------------
#  Widgets
# ---------------------------------------------------------------------------
class BalanceView(Rv.CompareView):
    """Original against balanced (images "before" and "after"), with the zoom,
    the pan and the curtain of the review."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "swipe"
        self.curtain = 0.5

    def _ref_size(self) -> QSize:
        img = self.images.get("after") or self.images.get("before")
        if isinstance(img, QImage):
            return img.size()
        return self.placeholder.size() if self.placeholder is not None else QSize(4, 3)

    def set_after(self, image: QImage):
        self.images["after"] = image
        self.pix.pop("after", None)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._drag is None)
        areas = self._areas()
        if not self.images:
            if self.placeholder is not None:
                p.drawPixmap(self._image_rect(areas[0]), self.placeholder, QRectF(self.placeholder.rect()))
            self._text(p, self.message or "Loading…", areas[0])
            return
        tag = Rv.TAG_COLOR
        if self.mode == "side":
            for area, key, cap in ((areas[0], "before", "Original"), (areas[1], "after", "Balanced")):
                self._draw(p, area, key)
                self._tag(p, area, cap, tag)
        elif self.mode == "blink":
            key = "after" if self._blink_on else "before"
            self._draw(p, areas[0], key)
            self._tag(p, areas[0], "Balanced" if self._blink_on else "Original", tag)
        else:
            area = areas[0]
            self._draw(p, area, "after")
            rect = self._image_rect(area)
            x = rect.left() + self.curtain * rect.width()
            p.save()
            p.setClipRect(QRectF(area.left(), area.top(), max(0.0, x - area.left()), area.height()))
            self._draw(p, area, "before")
            p.restore()
            if area.left() <= x <= area.right():
                p.setPen(QPen(QColor("white"), 2))
                p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                grip = QRectF(x - 9, area.center().y() - 22, 18, 44)
                p.setBrush(QColor("white"))
                p.drawRoundedRect(grip, 6, 6)
                p.setPen(QPen(Look.BLUE, 2))
                for dx in (-3, 3):
                    p.drawLine(QPointF(x + dx, grip.top() + 12), QPointF(x + dx, grip.bottom() - 12))
            self._tag(p, area, "◀ Original", tag)
            self._tag(p, area, "Balanced ▶", tag, right=True)
        if self.caption:
            p.setPen(QColor("#C5CFDA"))
            p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)
        p.setPen(QColor("#8A96A3"))
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"zoom {self.zoom * self._fit_scale():.0%}  ·  {self.hint}")


class HistogramView(QWidget):
    """Histograms of the four bands of the balanced image (the original NIR dotted)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hists: Dict[str, np.ndarray] = {}
        self.before_nir: Optional[np.ndarray] = None
        self.highlight = "nir"
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Histograms of the balanced image: red, green, blue and NIR (purple); the dotted "
                        "line is the original NIR. Balanced, the NIR spreads like the visible bands.")

    def set_data(self, hists, before_nir, highlight):
        self.hists, self.before_nir, self.highlight = hists, before_nir, highlight
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -18)
        p.fillRect(r, QColor("white"))
        p.setPen(QPen(Look.GRID, 1))
        p.drawRect(r)
        for k in (1, 2, 3):
            x = r.left() + r.width() * k / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        if not self.hists:
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "—")
            return
        series = [(b, self.hists[b]) for b in SB.BANDS if b in self.hists]
        top = max(float(np.sqrt(h[1:255]).max()) for _, h in series) or 1.0
        if self.before_nir is not None:
            top = max(top, float(np.sqrt(self.before_nir[1:255]).max()))

        def path_of(h, closed):
            path = QPainterPath()
            ys = np.minimum(np.sqrt(h) / top, 1.0)
            pts = [QPointF(r.left() + r.width() * i / 255, r.bottom() - ys[i] * (r.height() - 2)) for i in range(256)]
            if closed:
                path.moveTo(r.left(), r.bottom())
                for q in pts:
                    path.lineTo(q)
                path.lineTo(r.right(), r.bottom())
                path.closeSubpath()
            else:
                path.moveTo(pts[0])
                for q in pts[1:]:
                    path.lineTo(q)
            return path
        for band, h in series:
            c = QColor(BAND_COLORS[band])
            fill = QColor(c)
            fill.setAlpha(40)
            p.fillPath(path_of(h, True), fill)
            hl = band == self.highlight or (self.highlight == "rgb" and band != "nir")
            p.setPen(QPen(c, 2.0 if hl else 1.0))
            p.drawPath(path_of(h, False))
        if self.before_nir is not None:
            p.setPen(QPen(BAND_COLORS["nir"], 1.2, Qt.PenStyle.DotLine))
            p.drawPath(path_of(self.before_nir, False))
        # legend
        x = 2.0
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        for band in SB.BANDS:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(BAND_COLORS[band])
            p.drawRect(QRectF(x, self.height() - 12, 9, 9))
            p.setPen(Look.INK)
            text = LAYER_TEXT[band]
            p.drawText(QPointF(x + 12, self.height() - 3), text)
            x += 22 + p.fontMetrics().horizontalAdvance(text)
        p.setPen(MUTED)
        p.drawText(QRectF(x, self.height() - 16, self.width() - x - 2, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "··· NIR original")


class CurveEditor(QWidget):
    """Tone curve: click to add a handle, drag it, double-click (or right-click)
    a handle to remove it. The two ends move too (black and white points)."""
    changed = pyqtSignal()
    HANDLE = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curve: List[List[float]] = [list(p) for p in SB.IDENTITY_CURVE]
        self.color = BAND_COLORS["rgb"]
        self.hist: Optional[np.ndarray] = None
        self._drag: Optional[int] = None
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(210)
        self.setMouseTracking(True)

    def set_curve(self, curve, color, hist):
        self.curve = [list(p) for p in curve]
        self.color, self.hist = QColor(color), hist
        self.update()

    def value(self):
        return SB.clean_curve(self.curve)

    def _plot(self) -> QRectF:
        side = min(self.width(), self.height()) - 12
        return QRectF((self.width() - side) / 2, 6, side, side)

    def _to_px(self, x, y) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + x * r.width(), r.bottom() - y * r.height())

    def _from_px(self, pos):
        r = self._plot()
        return (min(max((pos.x() - r.left()) / r.width(), 0.0), 1.0),
                min(max((r.bottom() - pos.y()) / r.height(), 0.0), 1.0))

    def _handle_at(self, pos) -> Optional[int]:
        for i, (x, y) in enumerate(self.curve):
            q = self._to_px(x, y)
            if abs(q.x() - pos.x()) <= self.HANDLE and abs(q.y() - pos.y()) <= self.HANDLE:
                return i
        return None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        p.fillRect(r, QColor("white"))
        if self.hist is not None and self.hist.max() > 0:
            ys = np.sqrt(self.hist.astype(np.float64))
            ys = ys / (ys[1:255].max() or 1.0)
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            for i in range(256):
                path.lineTo(r.left() + r.width() * i / 255, r.bottom() - min(ys[i], 1.0) * r.height() * 0.9)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            p.fillPath(path, QColor(200, 207, 218, 110))
        p.setPen(QPen(Look.GRID, 1))
        for k in (1, 2, 3):
            p.drawLine(QPointF(r.left() + r.width() * k / 4, r.top()), QPointF(r.left() + r.width() * k / 4, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * k / 4), QPointF(r.right(), r.top() + r.height() * k / 4))
        p.drawRect(r)
        p.setPen(QPen(MUTED, 1, Qt.PenStyle.DashLine))
        p.drawLine(r.bottomLeft(), r.topRight())
        xs = np.linspace(0, 1, 256)
        ys = SB.curve_eval(SB.clean_curve(self.curve), xs)
        path = QPainterPath()
        path.moveTo(self._to_px(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(self._to_px(x, y))
        p.setPen(QPen(self.color, 2))
        p.drawPath(path)
        p.setBrush(QColor("white"))
        for x, y in self.curve:
            q = self._to_px(x, y)
            p.drawRect(QRectF(q.x() - 4, q.y() - 4, 8, 8))

    def mousePressEvent(self, e):
        pos = e.position()
        i = self._handle_at(pos)
        if e.button() == Qt.MouseButton.RightButton:
            self._remove(i)
            return
        if i is None:
            x, y = self._from_px(pos)
            xs = [c[0] for c in self.curve]
            if not xs[0] + 0.01 < x < xs[-1] - 0.01 or any(abs(x - c) < 0.01 for c in xs):
                return
            i = next(k for k, c in enumerate(xs) if c > x)
            self.curve.insert(i, [x, y])
            self.changed.emit()
        self._drag = i
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeAllCursor if self._handle_at(pos) is not None
                           else Qt.CursorShape.CrossCursor)
            return
        i = self._drag
        x, y = self._from_px(pos)
        lo = self.curve[i - 1][0] + 0.01 if i > 0 else 0.0
        hi = self.curve[i + 1][0] - 0.01 if i < len(self.curve) - 1 else 1.0
        self.curve[i] = [min(max(x, lo), hi), y]
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, _):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self._remove(self._handle_at(e.position()))

    def _remove(self, i):
        if i is not None and 0 < i < len(self.curve) - 1:
            del self.curve[i]
            self._drag = None
            self.changed.emit()
            self.update()


class ValueRow(QWidget):
    """A setting: its name, a slider and a box where the value can be typed.
    ``factor``: shown value / stored value (contrast stored -1..1, shown
    -100..100); ``log``: the slider moves on log2 of the value (gamma)."""
    changed = pyqtSignal(float)

    def __init__(self, name, lo, hi, decimals, step, factor=1.0, log=False, suffix="", tip=""):
        super().__init__()
        self.factor, self.log = factor, log
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.name = QLabel(name)
        self.name.setFixedWidth(72)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo * factor, hi * factor)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(82)
        self.spin.setKeyboardTracking(False)
        a, b = (np.log2(lo), np.log2(hi)) if log else (lo * factor, hi * factor)
        self.slider.setRange(int(round(a * 100)), int(round(b * 100)))
        for w in (self.name, self.slider, self.spin):
            w.setToolTip(tip)
        lay.addWidget(self.name)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v):
        shown = 2 ** (v / 100) if self.log else v / 100
        self.spin.blockSignals(True)
        self.spin.setValue(shown)
        self.spin.blockSignals(False)
        self.changed.emit(self.spin.value() / self.factor)

    def _from_spin(self, shown):
        self._set_slider(shown)
        self.changed.emit(shown / self.factor)

    def _set_slider(self, shown):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((np.log2(max(shown, 1e-6)) if self.log else shown) * 100)))
        self.slider.blockSignals(False)

    def set_value(self, value):
        """Show a stored value (no signal)."""
        self.spin.blockSignals(True)
        self.spin.setValue(value * self.factor)
        self.spin.blockSignals(False)
        self._set_slider(value * self.factor)


class BalanceStrip(Rv.ReviewStrip):
    """The images of the map: false colour thumbnails, an orange star on
    those balanced (a grey one: balanced, but out of date)."""

    def __init__(self, points, thumbs, states, own):
        super().__init__(_Points(points), thumbs, visible_only=True)
        self.states, self.own = states, own

    def _paint_gutter(self, p, chart, lane):
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        p.setPen(Rv.TAG_COLOR)
        p.drawText(QRectF(0, lane.top(), self.GUTTER - 10, lane.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Images\nof the map")
        p.setFont(self.font())

    def _state_color(self, pt):
        state = self.states.get(pt.number, SB.STATE_NONE)
        return BALANCED_COLOR if state == SB.STATE_DONE else STALE_COLOR if state == SB.STATE_STALE else SURVEY

    def _paint_status(self, p, status):
        px = self.plot_w() / max(self.i1 - self.i0, 1e-6)
        for i, pt in enumerate(self.review.points):
            x = self.x_of(i)
            if status.left() - px <= x <= status.right() + px:
                p.fillRect(QRectF(x - px / 2 + 0.5, status.top() + 1, max(px - 1, 1.0), status.height() - 2),
                           self._state_color(pt))

    def _tile(self, p, target, pt, tile_w):
        pix = self.thumbs.get(pt.number)
        if pix is not None and not pix.isNull():
            sw = pix.width() * target.width() / (tile_w - 2)
            p.drawPixmap(target, pix, QRectF((pix.width() - sw) / 2, 0, sw, pix.height()))
        else:
            p.fillRect(target, QColor("#E9EDF2"))
        p.fillRect(QRectF(target.left(), target.top(), target.width(), 4), SURVEY)   # spots the image
        state = self.states.get(pt.number, SB.STATE_NONE)
        if state != SB.STATE_NONE:
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() * 1.3)
            p.setFont(f)
            p.setPen(BALANCED_COLOR if state == SB.STATE_DONE else STALE_COLOR)
            p.drawText(QRectF(target.left() + 3, target.top() + 3, 18, 18), Qt.AlignmentFlag.AlignCenter,
                       "★" if state == SB.STATE_DONE else "☆")
            p.setFont(self.font())
        if pt.number in self.own:
            p.setPen(QColor("white"))
            p.drawText(QRectF(target.right() - 20, target.top() + 3, 17, 17), Qt.AlignmentFlag.AlignCenter, "✎")

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
            text = self.review.points[self.selected].stem
            w = p.fontMetrics().horizontalAdvance(text) + 14
            bubble = QRectF(min(max(x - w / 2, chart.left()), chart.right() - w), chart.top(), w, 20)
            p.setBrush(CURSOR)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bubble, 6, 6)
            p.setPen(QColor("white"))
            p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, text)
            p.setBrush(Qt.BrushStyle.NoBrush)


class _Points:
    def __init__(self, points):
        self.points = points


def balance_points(mission: Path) -> List[R.ReviewPoint]:
    """The images the window offers: those the next map uses (the selection of
    Step 6: aligned, not flagged, |dt| and overlap) whose four bands exist;
    every image with four bands when the selection cannot be computed."""
    quartets = set(SB.quartet_numbers(mission))
    try:
        import IRD_Interactive_ODM as ODM
        planned = ODM.planned_mapping_numbers(mission) & quartets
    except Exception as e:
        print(f"Spectral balance: selection of the map unknown ({e})")
        planned = set()
    numbers = planned or quartets
    try:
        known = {p.number: p for p in R.load_review(mission).points}
    except (FileNotFoundError, OSError, ValueError):
        known = {}
    out = []
    for n in sorted(numbers):
        pt = known.get(n) or R.ReviewPoint(number=n, stem="",
                                           vir_image=R.aligned_image(mission / R.OUTPUT_FOLDER, n))
        out.append(dataclasses.replace(pt, stem=f"IRD_{n:04d}"))
    return out


# ---------------------------------------------------------------------------
#  Dialog
# ---------------------------------------------------------------------------
class SpectralBalanceDialog(QDialog):
    """Spectral balance of the images of the map. The settings are saved when
    the window closes (Close or ✕)."""

    def __init__(self, mission: Path, parent=None):
        super().__init__(parent)
        self.mission = Path(mission)
        self.settings = SB.load_settings(self.mission)
        self._saved = self.settings.to_json()
        self._had_file = SB.settings_path(self.mission).is_file()
        self.points = balance_points(self.mission)
        self.states: Dict[int, str] = SB.states(self.mission, [p.number for p in self.points], self.settings)
        self.thumbs: Dict[int, QPixmap] = {}
        self._cache: "OrderedDict[int, dict]" = OrderedDict()
        self._loading: set = set()
        self._before: Dict[tuple, QImage] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._write_job: Optional[WriteJob] = None
        self._write_errors: List[str] = []
        self.index = 0
        self.layer = "nir"
        self.display = "vir"
        self.setWindowTitle(step_window_title(6, WINDOW_NAME, self.mission))
        self.setStyleSheet(DIALOG_STYLE)
        fit_to_screen(self, parent)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(30)
        self._render_timer.timeout.connect(self._render_after)
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.setInterval(400)
        self._state_timer.timeout.connect(self._refresh_states)
        self._build()
        self._show_layer()
        self._thumbs = ThumbThread(self.mission / R.OUTPUT_FOLDER, self.points)
        self._thumbs.thumb.connect(self._on_thumb)
        self._thumbs.start()
        if self.points:
            self.select(0)
        else:
            self.view.set_placeholder(None, "No multispectral image: run Step 4 first.")
        self._refresh_footer()

    # ---- layout
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 10)
        outer.setSpacing(8)
        header = Look.step_header(6, WINDOW_NAME, self.mission)
        self.subtitle = header.subtitle
        outer.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._scroll(self._build_settings(), 300))
        centre = QVBoxLayout()
        centre.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        for k, (key, text, tip) in enumerate(MODES):
            b = self._toggle(text, f"{tip}  (key {k + 1})")
            b.clicked.connect(lambda _=False, key=key: self.set_mode(key))
            self.mode_group.addButton(b, k)
            if key == "map":
                bar.addStretch(1)
            bar.addWidget(b)
            if key == "side":
                bar.addSpacing(16)
                self.display_group = QButtonGroup(self)
                for j, (dkey, dtext, dtip) in enumerate(DISPLAYS):
                    d = self._toggle(dtext, dtip)
                    d.clicked.connect(lambda _=False, dkey=dkey: self.set_display(dkey))
                    self.display_group.addButton(d, j)
                    bar.addWidget(d)
        self.mode_group.button(0).setChecked(True)
        self.display_group.button([d[0] for d in DISPLAYS].index(self.display)).setChecked(True)
        centre.addLayout(bar)
        self.view = BalanceView()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)
        self.map_model = self._make_map_model()
        self.big_map = self.mini_map = None
        if self.map_model is not None:
            self.big_map = MapV.FlightMapView(self.map_model)
            self.big_map.picked.connect(self._on_map_picked)
            self.big_map.hovered.connect(self.map_model.set_hover)
            self.big_map.clicked_empty.connect(lambda: self.map_model.set_current(None))
            self.view_stack.addWidget(self.big_map)
        else:
            self.mode_group.button(len(MODES) - 1).setEnabled(False)
            self.mode_group.button(len(MODES) - 1).setToolTip("No GPS position in the shoot points: no map.")
        centre.addWidget(self.view_stack, 1)
        body.addLayout(centre, 1)
        body.addWidget(self._scroll(self._build_sidebar(), 300))
        outer.addLayout(body, 1)

        self.strip = BalanceStrip(self.points, self.thumbs, self.states, set(self.settings.points))
        self.strip.setToolTip("Click to select · wheel to zoom (the times appear) · drag to pan · "
                              "double-click to see every image")
        self.strip.picked.connect(self.select)
        outer.addWidget(self.strip)

        foot = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(36)
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.clicked.connect(self._on_help)
        self.btn_reset = Look.reset_button("Put every setting back to neutral: the mission balance and the "
                                           "images with a balance of their own (the window stays open).")
        self.btn_reset.clicked.connect(self.reset_all)
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(SECONDARY_STYLE)
        self.btn_close.setFixedWidth(130)
        self.btn_close.clicked.connect(self.accept)
        foot.addWidget(self.btn_help)
        foot.addWidget(self.btn_reset)
        foot.addStretch(1)
        foot.addWidget(self.btn_close)
        outer.addLayout(foot)

        import IRD_Interactive_help as Help
        self.btn_close.setToolTip("Close; the settings are saved (the map uses them).")
        self.btn_help.setToolTip("← → previous / next image\nN next image to validate\nV validate\n"
                                 "1-3 swipe, blink, side by side\n4 map\nwheel zoom · double-click fit")
        for b in self.findChildren(QPushButton) + self.findChildren(QCheckBox):
            if b is not self.btn_help:
                Help.attach_help(b, HELP_LABEL, b.toolTip(), parent=self)
        Help.attach_help(self.btn_help, HELP_LABEL, "", parent=self)
        for b in self.findChildren(QPushButton):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for seq, slot in (("Left", lambda: self.step(-1)), ("Right", lambda: self.step(+1)),
                          ("N", self.next_to_validate), ("V", self.validate)):
            QShortcut(QKeySequence(seq), self, activated=slot)
        for k, (key, _, _) in enumerate(MODES):
            QShortcut(QKeySequence(str(k + 1)), self, activated=lambda key=key: self.set_mode(key))

    @staticmethod
    def _toggle(text, tip) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setStyleSheet(SECONDARY_STYLE)
        b.setToolTip(tip)
        return b

    @staticmethod
    def _scroll(widget, width) -> QScrollArea:
        """A side panel scrolls rather than set the window's minimum height."""
        widget.setFixedWidth(width)
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setFixedWidth(width + 14)
        area.setStyleSheet("QScrollArea { background: transparent; }")
        area.viewport().setAutoFillBackground(False)
        return area

    @staticmethod
    def _card():
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(Look.CARD_STYLE)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)
        return card, lay

    def _build_settings(self) -> QWidget:
        card, lay = self._card()
        title = QLabel("Layer adjusted")
        title.setStyleSheet("font-weight: bold; color: #17365D;")
        lay.addWidget(title)
        layers = QHBoxLayout()
        layers.setSpacing(3)
        self.layer_group = QButtonGroup(self)
        for k, key in enumerate(SB.LAYERS):
            b = self._toggle(LAYER_TEXT[key], LAYER_TIPS[key])
            b.clicked.connect(lambda _=False, key=key: self.set_layer(key))
            self.layer_group.addButton(b, k)
            layers.addWidget(b)
        lay.addLayout(layers)
        self.scope = QCheckBox("This image has a balance of its own")
        self.scope.setToolTip("Off: the settings apply to every image of the mission (recommended: the map "
                              "is a mosaic of many images, treated alike they give no seams). On: this image "
                              "gets a copy of the mission balance, then its own settings.")
        self.scope.toggled.connect(self._on_scope)
        lay.addWidget(self.scope)
        self.scope_text = QLabel()
        self.scope_text.setStyleSheet(SUBTITLE_STYLE)
        self.scope_text.setWordWrap(True)
        lay.addWidget(self.scope_text)
        self.nir_auto = QCheckBox("Match the NIR to the visible (each image)")
        self.nir_auto.setToolTip("On each image, the exposure and the gamma of the NIR are computed so that its "
                                 "median and its highlights match those of the visible. The camera exposures "
                                 "vary from image to image: this balances them all. Contrast, brightness and "
                                 "curve still apply after.")
        self.nir_auto.toggled.connect(self._on_nir_auto)
        lay.addWidget(self.nir_auto)
        self.rows = {
            "exposure": ValueRow("Exposure", *SB.EXPOSURE_RANGE, 2, 0.05, suffix=" EV",
                                 tip="Brighter or darker: x 2 per EV."),
            "gamma": ValueRow("Gamma", *SB.GAMMA_RANGE, 2, 0.05, log=True,
                              tip="Above 1 lifts the dark and mid tones, below 1 lowers them; black and "
                                  "white stay."),
            "contrast": ValueRow("Contrast", *SB.CONTRAST_RANGE, 0, 1, factor=100,
                                 tip="Spreads (or tightens) the tones around mid grey."),
            "brightness": ValueRow("Brightness", *SB.BRIGHTNESS_RANGE, 0, 1, factor=100,
                                   tip="Adds (or removes) the same amount to every tone."),
        }
        for key, row in self.rows.items():
            row.changed.connect(lambda v, key=key: self._on_value(key, v))
            lay.addWidget(row)
        self.auto_text = QLabel()
        self.auto_text.setStyleSheet(SUBTITLE_STYLE)
        self.auto_text.setWordWrap(True)
        lay.addWidget(self.auto_text)
        curve_title = QLabel("Tone curve")
        curve_title.setStyleSheet("font-weight: bold; color: #17365D;")
        curve_title.setToolTip("Click to add a handle, drag it; double-click or right-click a handle to "
                               "remove it.")
        lay.addWidget(curve_title)
        self.curve = CurveEditor()
        self.curve.setToolTip(curve_title.toolTip())
        self.curve.changed.connect(self._on_curve)
        lay.addWidget(self.curve)
        self.btn_reset_layer = QPushButton("Reset this layer")
        self.btn_reset_layer.setStyleSheet(SECONDARY_STYLE)
        self.btn_reset_layer.setToolTip("Put the settings of this layer back to neutral.")
        self.btn_reset_layer.clicked.connect(self.reset_layer)
        lay.addWidget(self.btn_reset_layer)
        note = QLabel("The map (Build the map) uses the balanced images: those not written here are "
                      "written when the map is built.")
        note.setWordWrap(True)
        note.setStyleSheet(MESSAGE_STYLE)
        lay.addWidget(note)
        lay.addStretch(1)
        return card

    def _build_sidebar(self) -> QWidget:
        card, lay = self._card()
        head = QHBoxLayout()
        self.point_title = QLabel()
        self.point_title.setStyleSheet("font-size: 15pt; font-weight: bold; color: #17365D;")
        self.point_star = QLabel()
        self.point_star.setStyleSheet(f"font-size: 16pt; color: {BALANCED_COLOR.name()};")
        head.addWidget(self.point_title)
        head.addWidget(self.point_star)
        head.addStretch(1)
        self.btn_validate = QPushButton("✓ Validate  (V)")
        self.btn_validate.setStyleSheet(PRIMARY_STYLE)
        self.btn_validate.setToolTip("Write the balanced bands of this image (IRD_XXXX_1..4.tif and "
                                     "IRD_XXXX_bal.json in ImgIRdrone/img_Bal_Multispectral): an orange star "
                                     "marks it.")
        self.btn_validate.clicked.connect(self.validate)
        head.addWidget(self.btn_validate)
        lay.addLayout(head)
        self.point_info = QLabel()
        self.point_info.setTextFormat(Qt.TextFormat.RichText)
        self.point_info.setWordWrap(True)
        self.point_info.setStyleSheet("color: #3E4C59;")
        lay.addWidget(self.point_info)
        self.hist = HistogramView()
        lay.addWidget(self.hist)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.btn_next_todo = QPushButton("Next to validate  (N)")
        for b in (self.btn_prev, self.btn_next, self.btn_next_todo):
            b.setStyleSheet(SECONDARY_STYLE)
        self.btn_prev.setFixedWidth(44)
        self.btn_next.setFixedWidth(44)
        self.btn_prev.setToolTip("Previous image (key ←)")
        self.btn_next.setToolTip("Next image (key →)")
        self.btn_next_todo.setToolTip("Next image whose balanced bands are not written, or out of date (key N).")
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(+1))
        self.btn_next_todo.clicked.connect(self.next_to_validate)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next_todo, 1)
        nav.addWidget(self.btn_next)
        lay.addLayout(nav)
        if self.map_model is not None:
            self.mini_map = MapV.FlightMapView(self.map_model, compact=True)
            self.mini_map.setFixedHeight(190)
            self.mini_map.setToolTip("Where the image was taken. Click: large map (key 4)")
            self.mini_map.picked.connect(self._on_map_picked)
            self.mini_map.clicked_empty.connect(lambda: self.set_mode("map"))
            lay.addWidget(self.mini_map)
        lay.addStretch(1)
        self.btn_write_all = QPushButton()
        self.btn_write_all.setStyleSheet(SECONDARY_STYLE)
        self.btn_write_all.setToolTip("Write the balanced bands of every image of the map not written yet "
                                      "or out of date (about a second per image, in the background).")
        self.btn_write_all.clicked.connect(self.write_all)
        lay.addWidget(self.btn_write_all)
        row = QHBoxLayout()
        self.write_bar = QProgressBar()
        self.write_bar.setTextVisible(False)
        self.write_bar.setFixedHeight(6)
        self.write_bar.setStyleSheet(PROGRESS_STYLE)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(SECONDARY_STYLE)
        self.btn_stop.setToolTip("Write no other image (the one being written finishes).")
        self.btn_stop.clicked.connect(self.stop_writing)
        row.addWidget(self.write_bar, 1)
        row.addWidget(self.btn_stop)
        self.write_row = QWidget()
        self.write_row.setLayout(row)
        self.write_row.hide()
        lay.addWidget(self.write_row)
        self.write_text = QLabel()
        self.write_text.setStyleSheet(SUBTITLE_STYLE)
        self.write_text.setWordWrap(True)
        lay.addWidget(self.write_text)
        return card

    def _make_map_model(self):
        try:
            model = MapV.map_model_for(self.mission, color_of=self._map_color, shoot_points_only=True, parent=self)
        except Exception as e:   # the map is a help, never a blocker
            print(f"Map unavailable: {e}")
            return None
        if model is not None:
            numbers = {p.number for p in self.points}
            model.image_of = self.thumbs.get
            model.minor = lambda i: model.numbers[i] not in numbers
        return model

    def _map_color(self, number):
        state = self.states.get(number)
        if state is None:
            return Rv.NOT_ALIGNED_COLOR
        return BALANCED_COLOR if state == SB.STATE_DONE else SURVEY

    # ---- the balance being edited
    def current(self) -> Optional[R.ReviewPoint]:
        return self.points[self.index] if 0 <= self.index < len(self.points) else None

    def balance(self) -> SB.Balance:
        pt = self.current()
        return self.settings.balance_for(pt.number) if pt is not None else self.settings.mission

    def adjust(self) -> SB.Adjust:
        return self.balance().layer(self.layer)

    def set_layer(self, layer):
        self.layer = layer
        if layer == "nir" and self.display == "vis":
            self.set_display("nir")
        elif layer != "nir" and self.display == "nir":
            self.set_display("vis")
        self._show_layer()

    def _show_layer(self):
        """The controls show the settings of the layer of the image."""
        self.layer_group.button(SB.LAYERS.index(self.layer)).setChecked(True)
        a = self.adjust()
        for key, row in self.rows.items():
            row.set_value(getattr(a, key))
        pt = self.current()
        own = pt is not None and self.settings.has_own(pt.number)
        self.scope.blockSignals(True)
        self.scope.setChecked(own)
        self.scope.blockSignals(False)
        self.scope.setEnabled(pt is not None)
        self.scope_text.setText(f"These settings apply to {pt.stem} only." if own else
                                "These settings apply to every image of the mission.")
        is_nir = self.layer == "nir"
        self.nir_auto.setVisible(is_nir)
        self.nir_auto.blockSignals(True)
        self.nir_auto.setChecked(self.balance().nir_auto)
        self.nir_auto.blockSignals(False)
        auto = is_nir and self.balance().nir_auto
        for key in ("exposure", "gamma"):
            self.rows[key].setEnabled(not auto)
        self._show_auto_values()
        self.curve.set_curve(a.curve, BAND_COLORS[self.layer], self._layer_hist_before())
        self._refresh_reset()

    def _show_auto_values(self):
        data = self._cache.get(self.current().number) if self.current() is not None else None
        if self.layer == "nir" and self.balance().nir_auto:
            if data:
                nir = SB.effective(self.balance(), data["small"]).layer("nir")
                self.rows["exposure"].set_value(nir.exposure)
                self.rows["gamma"].set_value(nir.gamma)
                self.auto_text.setText(f"Computed on this image: exposure {nir.exposure:+.2f} EV, "
                                       f"gamma {nir.gamma:.2f}.")
            else:
                self.auto_text.setText("Computed on each image (once it is read).")
            self.auto_text.show()
        else:
            self.auto_text.hide()

    def _layer_hist_before(self):
        """Histogram of what the tone curve of the layer receives: the image
        after the other settings of the layer (and the RGB layer for a band)."""
        data = self._cache.get(self.current().number) if self.current() is not None else None
        if not data:
            return None
        balance = SB.effective(self.balance(), data["small"])
        before_curve = dataclasses.replace(balance.layer(self.layer), curve=SB.IDENTITY_CURVE)
        x = SB.transfer(balance.layer("rgb"), SB._X16) if self.layer in SB.VISIBLE_LAYERS else SB._X16
        lut = np.round(SB.transfer(before_curve, x) * 255).astype(np.uint8)
        sub = data["preview"][::2, ::2]
        bands = SB.VISIBLE_LAYERS if self.layer == "rgb" else (self.layer,)
        return sum(np.bincount(lut[sub[..., SB.BANDS.index(b)]].ravel(), minlength=256) for b in bands)

    def _on_value(self, key, value):
        setattr(self.adjust(), key, float(value))
        self._changed()

    def _on_curve(self):
        self.adjust().curve = self.curve.value()
        self._changed()

    def _on_nir_auto(self, on):
        self.balance().nir_auto = bool(on)
        if not on:          # the values computed on this image stay: a starting point
            data = self._cache.get(self.current().number) if self.current() is not None else None
            if data:
                b = self.balance().copy()
                b.nir_auto = True
                nir = SB.effective(b, data["small"]).layer("nir")
                self.adjust().exposure, self.adjust().gamma = nir.exposure, nir.gamma
        self._show_layer()
        self._changed()

    def _on_scope(self, own):
        pt = self.current()
        if pt is None:
            return
        if own:
            self.settings.points[pt.number] = self.settings.mission.copy()
        else:
            self.settings.points.pop(pt.number, None)
        self.strip.own = set(self.settings.points)
        self._show_layer()
        self._changed()

    def reset_layer(self):
        self.balance().layers[self.layer] = SB.Adjust()
        if self.layer == "nir":
            self.balance().nir_auto = False
        self._show_layer()
        self._changed()

    def reset_all(self):
        self.settings = SB.Settings()
        self.strip.own = set()
        self._show_layer()
        self._changed()

    def _changed(self):
        self._render_timer.start()
        self._state_timer.start()
        self._refresh_reset()
        self._refresh_footer()

    def is_changed(self) -> bool:
        return self.settings.to_json() != self._saved

    def _refresh_reset(self):
        self.btn_reset.setVisible(not self.settings.is_identity())
        self.btn_reset_layer.setEnabled(not self.adjust().is_identity()
                                        or (self.layer == "nir" and self.balance().nir_auto))

    def _refresh_footer(self):
        self.btn_close.setText(Look.close_text(self.is_changed()))
        todo = sum(1 for s in self.states.values() if s != SB.STATE_DONE)
        self.btn_write_all.setText(f"Write all the balanced images ({todo})" if todo else
                                   "Every image is balanced ★")
        self.btn_write_all.setEnabled(bool(todo) and self._write_job is None and not self.settings.is_identity())

    # ---- selection
    def select(self, index: int):
        if not self.points:
            return
        self.index = int(np.clip(index, 0, len(self.points) - 1))
        self.strip.selected = self.index
        self.strip.ensure_visible(self.index)
        self.strip.update()
        self._show_point()
        self._show_layer()
        self._map_follow()
        for j in (self.index + 1, self.index - 1):
            if 0 <= j < len(self.points):
                self._load(self.points[j].number)

    def step(self, delta):
        self.select(self.index + delta)

    def next_to_validate(self):
        n = len(self.points)
        for k in range(1, n + 1):
            j = (self.index + k) % n
            if self.states.get(self.points[j].number) != SB.STATE_DONE:
                self.select(j)
                return
        self.subtitle.setText("Every image is balanced.")

    def _show_point(self):
        pt = self.current()
        self.view.caption = pt.stem + (f"  ·  {Path(pt.nir_name).stem}" if pt.nir_name else "")
        data = self._cache.get(pt.number)
        if data:
            self._cache.move_to_end(pt.number)
            self._render_all(data)
        else:
            self.view.set_placeholder(self.thumbs.get(pt.number), "Loading…")
            self.hist.set_data({}, None, self.layer)
            self._load(pt.number)
        self._refresh_point()

    def _refresh_point(self):
        pt = self.current()
        if pt is None:
            return
        state = self.states.get(pt.number, SB.STATE_NONE)
        self.point_title.setText(pt.stem)
        self.point_star.setText("★" if state == SB.STATE_DONE else "☆" if state == SB.STATE_STALE else "")
        self.point_star.setStyleSheet(f"font-size: 16pt; color: "
                                      f"{(BALANCED_COLOR if state == SB.STATE_DONE else STALE_COLOR).name()};")
        text = {SB.STATE_DONE: "Balanced: its balanced bands are written.",
                SB.STATE_STALE: "Balanced bands out of date (the settings or the image changed): validate "
                                "again.",
                SB.STATE_NONE: "Not written yet."}[state]
        lines = [f"<span style='color:#6B7785'>{self.index + 1} / {len(self.points)}</span> · {text}"]
        if pt.time is not None:
            lines.append(f"Shot at <b>{Look.fmt_time(pt.time)}</b>"
                         + (f" · {pt.altitude:.0f} m above ground" if pt.altitude is not None else ""))
        self.point_info.setText("<br>".join(lines))
        self.btn_validate.setEnabled(self._write_job is None and state != SB.STATE_DONE)
        self.btn_validate.setText("★ Validated" if state == SB.STATE_DONE else "✓ Validate  (V)")

    def _load(self, number):
        if number in self._cache or number in self._loading:
            return
        self._loading.add(number)
        job = LoadJob(self.mission, number)
        job.signals.loaded.connect(self._on_loaded)
        self._pool.start(job)

    def _on_loaded(self, number, data):
        self._loading.discard(number)
        if not data:
            if self.current() is not None and self.current().number == number:
                self.view.set_placeholder(None, "The four bands of this image cannot be read.")
            return
        self._cache[number] = data
        while len(self._cache) > CACHE_POINTS:
            old, _ = self._cache.popitem(last=False)
            for key in [k for k in self._before if k[0] == old]:
                del self._before[key]
        if self.current() is not None and self.current().number == number:
            self._render_all(data)
            self._show_layer()

    def _on_thumb(self, number, image):
        self.thumbs[number] = QPixmap.fromImage(image)
        self.strip.update()
        if self.map_model is not None:
            self.map_model.changed.emit()

    # ---- rendering
    def _before_image(self, number, data) -> QImage:
        key = (number, self.display)
        if key not in self._before:
            self._before[key] = render(data["preview"], IDENTITY_LUTS, self.display)
        return self._before[key]

    def _render_all(self, data):
        pt = self.current()
        luts = lut8_set(SB.effective(self.balance(), data["small"]))
        self.view.set_images({"before": self._before_image(pt.number, data),
                              "after": render(data["preview"], luts, self.display),
                              "width": data["width"]})
        self._show_hist(data, luts)

    def _render_after(self):
        pt = self.current()
        data = self._cache.get(pt.number) if pt is not None else None
        if not data or not self.view.has_images():
            return
        luts = lut8_set(SB.effective(self.balance(), data["small"]))
        self.view.set_after(render(data["preview"], luts, self.display))
        self._show_hist(data, luts)

    def _show_hist(self, data, luts):
        before = np.bincount((data["preview"][::2, ::2, 3] >> 8).ravel(), minlength=256)
        self.hist.set_data(histograms(data["preview"], luts), before, self.layer)
        self.curve.hist = self._layer_hist_before()
        self.curve.update()

    def set_display(self, display):
        self.display = display
        self.display_group.button([d[0] for d in DISPLAYS].index(display)).setChecked(True)
        pt = self.current()
        data = self._cache.get(pt.number) if pt is not None else None
        if data:
            self._render_all(data)

    def set_mode(self, mode):
        keys = [m[0] for m in MODES]
        if mode not in keys:
            return
        if mode == "map":
            if self.big_map is None:
                return
            self.view_stack.setCurrentWidget(self.big_map)
            self._map_follow()
        else:
            self.view_stack.setCurrentWidget(self.view)
            self.view.set_mode(mode)
        self.mode_group.button(keys.index(mode)).setChecked(True)

    # ---- map
    def _on_map_picked(self, i):
        number = self.map_model.numbers[i]
        for k, p in enumerate(self.points):
            if p.number == number:
                self.select(k)
                return

    def _map_follow(self):
        if self.map_model is None or self.current() is None:
            return
        i = self.map_model.index_of(self.current().number)
        self.map_model.set_current(i)
        if i is not None:
            for v in (self.mini_map, self.big_map):
                if v is not None and v.isVisible():
                    v.focus(i)

    # ---- states and writing
    def _refresh_states(self):
        self.states.update(SB.states(self.mission, [p.number for p in self.points], self.settings))
        self.strip.update()
        if self.map_model is not None:
            self.map_model.changed.emit()
        self._refresh_point()
        self._refresh_footer()

    def validate(self):
        pt = self.current()
        if pt is None or self._write_job is not None or self.states.get(pt.number) == SB.STATE_DONE:
            return
        self._write([pt.number])

    def write_all(self):
        if self._write_job is not None:
            return
        todo = [p.number for p in self.points if self.states.get(p.number) != SB.STATE_DONE]
        if todo:
            self._write(todo)

    def _write(self, numbers):
        self._save()
        self._write_errors = []
        job = WriteJob(self.mission, numbers, self.settings)
        job.signals.progress.connect(self._on_written)
        job.signals.finished.connect(self._on_write_finished)
        self._write_job = job
        self.write_bar.setRange(0, len(numbers))
        self.write_bar.setValue(0)
        self.write_row.setVisible(len(numbers) > 1)
        self.write_text.setText(f"Writing {len(numbers)} image(s)…")
        self._refresh_point()
        self._refresh_footer()
        QThreadPool.globalInstance().start(job)

    def _on_written(self, number, done, total, error):
        self.write_bar.setValue(done)
        if error:
            self._write_errors.append(f"IRD_{number:04d}: {error}")
        self.states[number] = SB.point_state(self.mission, number, self.settings)
        self.write_text.setText(f"Written {done} / {total}" + (f" · {len(self._write_errors)} error(s)"
                                                               if self._write_errors else ""))
        self.strip.update()
        if self.map_model is not None:
            self.map_model.changed.emit()
        self._refresh_point()

    def _on_write_finished(self):
        stopped = self._write_job is not None and self._write_job.stopped
        self._write_job = None
        self.write_row.hide()
        self.write_text.setText("Stopped." if stopped else
                                "" if not self._write_errors else "Some images were not written.")
        self._refresh_states()
        if self._write_errors:
            QMessageBox.warning(self, WINDOW_NAME, "Not written:\n" + "\n".join(self._write_errors[:10]))

    def stop_writing(self):
        if self._write_job is not None:
            self._write_job.stopped = True

    # ---- closing
    def _save(self):
        if self.is_changed() or (not self._had_file and not self.settings.is_identity()):
            SB.save_settings(self.mission, self.settings)
            self._saved = self.settings.to_json()
            self._had_file = True
            self._refresh_footer()

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help(HELP_LABEL, parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")

    def done(self, r):
        """Close, ✕ or Esc: the settings are saved (a writing in progress is stopped first)."""
        if self._write_job is not None:
            answer = QMessageBox.question(self, WINDOW_NAME, "Balanced images are being written.\n\n"
                                          "Stop after the current image and close?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            job = self._write_job
            job.stopped = True
            while job.running:            # the image being written finishes
                QThread.msleep(50)
                QApplication.processEvents()
        self._thumbs.stop()
        self._thumbs.wait(5000)
        self._pool.clear()
        self._pool.waitForDone(5000)
        try:
            self._save()
        except OSError as e:
            QMessageBox.warning(self, WINDOW_NAME, f"The settings cannot be saved:\n{e}")
            return
        super().done(QDialog.DialogCode.Accepted)
        self._cache.clear()
        self._before.clear()


def main():
    """Standalone: python IRD_Interactive_Spectral_Balance.py <mission folder>"""
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = SpectralBalanceDialog(Path(sys.argv[1]))
    dlg.show()
    app.exec()


if __name__ == "__main__":
    main()
