# -*- coding: utf-8 -*-
"""
Flight map widget: background map (aerial photos, optional, online), the
orthophoto of Step 5 when it is built, the flight and the ground footprint of
the current image.

    wheel        zoom around the mouse
    drag         pan
    click        pick the nearest shoot point (signal `picked`)
    Layers ▾     background source, orthophoto natural / infrared colours

A model built with `mapped` (the main window) draws the sparse trajectory
of the map: only the shoot points it uses (the mapping done, else the ones
the next run of Step 5 will map), the whole flight faint behind, the flagged
ones in red; with their ground footprints while no orthophoto is shown.
Layers ▾ shows every image again.

Several views can share one `MapModel` (mini map and large map of the review).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, QSettings, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
                         QPolygonF, QTransform)
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget

import flight_map as F
import IRD_Interactive_look as Look

SETTINGS_KEY = "flight_map/"
FLAGGED_COLOR = QColor("#B03A2E")       # flagged in the review: left out of the map (as in the review)


# ---------------------------------------------------------------------------
#  Background tiles: fetched in the background, shared by every view
# ---------------------------------------------------------------------------
class _TileSignals(QObject):
    done = pyqtSignal(str, int, int, int, bytes)       # source, z, x, y, data (b"" = failed)


class _TileJob(QRunnable):
    def __init__(self, key, signals):
        super().__init__()
        self.key, self.signals = key, signals

    def run(self):
        source, z, x, y = self.key
        data = F.fetch_tile(source, z, x, y)
        try:
            self.signals.done.emit(source, z, x, y, data or b"")
        except RuntimeError:      # the application is closing
            pass


class TileCache(QObject):
    """In-memory tiles; missing ones are fetched (at most a few at a time).
    After repeated failures the source is given up for the session: offline."""
    changed = pyqtSignal()
    MAX_FAILURES = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles: Dict[tuple, Optional[QPixmap]] = {}
        self.pending = set()
        self.failures: Dict[str, int] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.signals = _TileSignals()
        self.signals.done.connect(self._on_done)

    def offline(self, source: str) -> bool:
        return self.failures.get(source, 0) >= self.MAX_FAILURES

    def get(self, key) -> Optional[QPixmap]:
        """Tile pixmap, or None (requested if needed)."""
        if key in self.tiles:
            return self.tiles[key]
        if key not in self.pending and not self.offline(key[0]):
            self.pending.add(key)
            self.pool.start(_TileJob(key, self.signals))
        return None

    def _on_done(self, source, z, x, y, data):
        key = (source, z, x, y)
        self.pending.discard(key)
        pix = QPixmap()
        if data and pix.loadFromData(data):
            self.tiles[key] = pix
            self.failures[source] = 0
        else:
            self.tiles[key] = None
            self.failures[source] = self.failures.get(source, 0) + 1
        self.changed.emit()

    def stop(self):
        """Drop the queued requests, wait for the running ones, free the pixmaps.
        Called while the application still exists: a QPixmap destroyed after it (module
        globals are freed at interpreter exit) crashes the process when it closes."""
        global _TILES
        self.pool.clear()
        self.pool.waitForDone(2000)
        self.tiles.clear()
        self.pending.clear()
        if _TILES is self:
            _TILES = None


_TILES: Optional[TileCache] = None


def tile_cache() -> TileCache:
    global _TILES
    if _TILES is None:
        _TILES = TileCache()
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:       # pending requests are dropped when the application quits
            app.aboutToQuit.connect(_TILES.stop)
    return _TILES


# ---------------------------------------------------------------------------
#  What is drawn: shared by the views of a window
# ---------------------------------------------------------------------------
class MapModel(QObject):
    """Points, footprints, orthophoto and the layer choices."""
    changed = pyqtSignal()

    def __init__(self, points: List[F.MapPoint], fov=None, ortho: Optional[F.OrthoPreview] = None,
                 color_of: Optional[Callable[[int], QColor]] = None, path: Optional[List[F.MapPoint]] = None,
                 mapped=None, mapped_by: str = "mapping", flagged=None, built=None, parent=None):
        super().__init__(parent)
        self.points = points
        # the whole flight (line), the points are the shoot points on it
        self.path_xy = [p.xy for p in path] if path else None
        self.numbers = [p.number for p in points]
        self._index = {n: i for i, n in enumerate(self.numbers)}
        self.xy = [p.xy for p in points]
        # indices of the shoot points used by the mapping of Step 5
        self.mapped = [i for i, n in enumerate(self.numbers) if n in mapped] if mapped else []
        # "mapping" (Step 5 done), "next mapping" (Step 4 done: the images the
        # next run of Step 5 will map) or "best mapping" (planned in Steps 2 and 4)
        self.mapped_by = mapped_by
        # numbers of the images of the map built (Step 5 done), when the points
        # drawn are the ones of the next run ("next mapping")
        self.built = set(built or ())
        # indices of the shoot points flagged in the review: left out of the map
        self.flagged = [i for i, n in enumerate(self.numbers) if n in flagged] if flagged else []
        self.show_mapped = True             # Layers ▾ "Only the images of the mapping"
        self.fov = fov or F.field_of_view()
        self.color_of = color_of
        self._footprints: Dict[int, List[Tuple[float, float]]] = {}
        self.current: Optional[int] = None
        self.ground_source = ""
        self.hover: Optional[int] = None
        self.ortho_images: Dict[str, QImage] = {}
        self.ortho_corners = None
        self.set_ortho(ortho)
        s = QSettings("IRDrone", "IRDrone")
        lat = points[0].lat if points else None
        lon = points[0].lon if points else None
        self.source = str(s.value(SETTINGS_KEY + "source", "") or F.default_source(lat, lon))
        if self.source != F.NO_BACKGROUND and self.source not in F.TILE_SOURCES:
            self.source = F.default_source(lat, lon)
        self.ortho_mode = str(s.value(SETTINGS_KEY + "ortho", "natural") or "natural")
        self.show_image = str(s.value(SETTINGS_KEY + "image", "true")) != "false"
        self.image_of: Optional[Callable[[int], Optional[QPixmap]]] = None    # number -> image (thumbnail)
        # the current footprint in the colour of its point (review: its status), not the cursor orange
        self.cursor_in_point_color = False
        # minor(index): a secondary point (review: not aligned), a small dot until zoomed in
        self.minor: Optional[Callable[[int], bool]] = None
        # images kept for the map (best mapping): footprints drawn, bigger dots
        self.selection: List[int] = []
        self._selection_set = set()
        # progress of a computation over the selection (Step 4 alignment):
        # None, or the indices done and the ones being processed
        self.progress: Optional[Tuple[set, set]] = None

    def set_selection(self, indices):
        self.selection = list(indices)
        self._selection_set = set(self.selection)
        self.changed.emit()

    def is_selected(self, index: int) -> bool:
        return index in self._selection_set

    def set_progress(self, done=None, running=None):
        """Show the progress over the selection (None, None: no progress)."""
        self.progress = None if done is None else (set(done), set(running or ()))
        self.changed.emit()

    def grounds_found(self, source):
        """The ground under the points is known: footprints computed again."""
        self.ground_source = source
        self._footprints.clear()
        self.changed.emit()

    def index_of(self, number) -> Optional[int]:
        return self._index.get(number)

    def set_ortho(self, ortho: Optional[F.OrthoPreview]):
        self.ortho_images = {}
        self.ortho_corners = None
        if ortho is not None:
            self.ortho_images["natural"] = _rgba_qimage(ortho.natural)
            if ortho.false_color is not None:
                self.ortho_images["infrared"] = _rgba_qimage(ortho.false_color)
            self.ortho_corners = [F.mercator(lat, lon) for lat, lon in ortho.corners]
        self.changed.emit()

    @property
    def planned(self) -> bool:
        """The mapped points are the best mapping planned (no mapping yet)."""
        return self.mapped_by in ("best mapping", "next mapping")

    @property
    def sparse(self) -> bool:
        """Only the shoot points of the map (and the flagged ones), orthophoto
        shown or not; Layers ▾ shows every image again."""
        return bool((self.mapped or self.flagged) and self.show_mapped)

    @property
    def ortho_shown(self) -> bool:
        return bool(self.ortho_images) and self.ortho_mode in self.ortho_images

    def set_show_mapped(self, on: bool):
        self.show_mapped = bool(on)
        self.changed.emit()

    def footprints_kept(self) -> List[int]:
        """Indices whose footprints show the coverage: the images kept in
        Step 2, or the best mapping planned on the main window map."""
        if self.selection:
            return self.selection
        return self.mapped if self.sparse and not self.ortho_shown else []

    def visible(self) -> List[int]:
        """Indices of the points drawn (and picked): the flagged ones too."""
        return sorted(set(self.mapped) | set(self.flagged)) if self.sparse else list(range(len(self.xy)))

    def footprint(self, index: int) -> Optional[List[Tuple[float, float]]]:
        """Footprint corners in mercator metres (None without height or yaw)."""
        if index in self._footprints:
            return self._footprints[index]
        p = self.points[index]
        fp = None
        h = p.above_ground
        if h is not None and p.yaw is not None and h > 2:
            fp = [F.mercator(lat, lon) for lat, lon in F.footprint(p.lat, p.lon, h, p.yaw, self.fov)]
        self._footprints[index] = fp
        return fp

    def set_source(self, key: str):
        self.source = key
        QSettings("IRDrone", "IRDrone").setValue(SETTINGS_KEY + "source", key)
        self.changed.emit()

    def set_ortho_mode(self, mode: str):
        self.ortho_mode = mode
        QSettings("IRDrone", "IRDrone").setValue(SETTINGS_KEY + "ortho", mode)
        self.changed.emit()

    def set_show_image(self, on: bool):
        self.show_image = bool(on)
        QSettings("IRDrone", "IRDrone").setValue(SETTINGS_KEY + "image", "true" if on else "false")
        self.changed.emit()

    def image(self, index: Optional[int]) -> Optional[QPixmap]:
        if index is None or self.image_of is None or not (0 <= index < len(self.points)):
            return None
        try:
            pix = self.image_of(self.points[index].number)
        except Exception:
            return None
        return pix if pix is not None and not pix.isNull() else None

    def set_current(self, index: Optional[int]):
        self.current = index
        self.changed.emit()

    def set_hover(self, index: Optional[int]):
        if index != self.hover:
            self.hover = index
            self.changed.emit()

    def bounds(self) -> Optional[Tuple[float, float, float, float]]:
        xs = [x for x, _ in self.xy]
        ys = [y for _, y in self.xy]
        if self.ortho_corners:
            (x0, y0), (x1, _), (_, y2) = self.ortho_corners
            xs += [x0, x1]
            ys += [y0, y2]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


def _rgba_qimage(arr) -> QImage:
    import numpy as np
    a = np.ascontiguousarray(arr)
    h, w = a.shape[:2]
    return QImage(a.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


# ---------------------------------------------------------------------------
#  The view
# ---------------------------------------------------------------------------
class FlightMapView(QWidget):
    picked = pyqtSignal(int)
    hovered = pyqtSignal(object)          # index or None
    clicked_empty = pyqtSignal()          # click outside any point (the mini map expands)

    def __init__(self, model: MapModel, compact: bool = False, parent=None):
        super().__init__(parent)
        self.model = model
        self.compact = compact
        self.res = 1.0                    # mercator metres per pixel
        self.center = (0.0, 0.0)
        self._fitted = False
        self._press = None
        self._dragged = False
        self.setMouseTracking(True)
        self.setMinimumSize(120, 100)
        model.changed.connect(self._on_model_changed)
        tile_cache().changed.connect(self.update)
        self.btn_layers = QToolButton(self)
        self.btn_layers.setText("Layers ▾" if not compact else "▾")
        self.btn_layers.setToolTip("Background map and orthophoto")
        self.btn_layers.setStyleSheet("QToolButton { background: rgba(255,255,255,230); color: #17365D;"
                                      " border: 1px solid #C5CFDA; border-radius: 4px; padding: 2px 6px;"
                                      " font-weight: bold; } QToolButton::menu-indicator { image: none; }")
        self.btn_layers.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_layers.setMenu(self._layers_menu())
        self.btn_layers.move(6, 6)
        self.btn_fit = QToolButton(self)
        self.btn_fit.setText("⤢")
        self.btn_fit.setToolTip("Whole flight")
        self.btn_fit.setStyleSheet(self.btn_layers.styleSheet())
        self.btn_fit.clicked.connect(self.fit)
        self.btn_fit.setVisible(not compact)
        try:   # F1: the map section of the manual (a help, never a blocker)
            import IRD_Interactive_help as Help
            Help.attach_help(self.btn_layers, "btn:home_map",
                             "Background (IGN aerial photos, Esri, OpenStreetMap or none, from the internet) "
                             "and orthophoto of Step 5 (natural or false colours).", parent=self)
            Help.attach_help(self.btn_fit, "btn:home_map", "Show the whole flight (or double-click the map).",
                             parent=self)
        except Exception as e:
            print(f"Map help not attached: {e}")

    # ---- layers menu
    def _layers_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addSection("Background")
        group = QActionGroup(menu)
        for key, name in [(k, s.name) for k, s in F.TILE_SOURCES.items()] + [(F.NO_BACKGROUND, "None")]:
            act = QAction(name, menu, checkable=True)
            act.setChecked(self.model.source == key)
            act.triggered.connect(lambda _=False, k=key: self.model.set_source(k))
            group.addAction(act)
            menu.addAction(act)
        menu.addSection("Orthophoto (Step 5)")
        group2 = QActionGroup(menu)
        for key, name in (("natural", "Natural colours"), ("infrared", "Infrared false colours"),
                          ("hidden", "Hidden")):
            act = QAction(name, menu, checkable=True)
            act.setChecked(self.model.ortho_mode == key)
            act.setEnabled(bool(self.model.ortho_images) and (key != "infrared" or
                                                               "infrared" in self.model.ortho_images))
            act.triggered.connect(lambda _=False, k=key: self.model.set_ortho_mode(k))
            group2.addAction(act)
            menu.addAction(act)
        if self.model.mapped:
            menu.addSection("Trajectory")
            self.act_mapped = QAction("Only the images of the best mapping"
                                      if self.model.mapped_by == "best mapping" and not self.model.flagged
                                      else "Only the images of the map (and the flagged ones)",
                                      menu, checkable=True)
            self.act_mapped.setChecked(self.model.show_mapped)
            self.act_mapped.triggered.connect(self.model.set_show_mapped)
            menu.addAction(self.act_mapped)
        if not self.compact:
            menu.addSection("Shoot point")
            self.act_image = QAction("Aligned image in its footprint", menu, checkable=True)
            self.act_image.setChecked(self.model.show_image)
            self.act_image.triggered.connect(self.model.set_show_image)
            menu.addAction(self.act_image)
        menu.aboutToShow.connect(lambda: self._sync_menu(menu))
        return menu

    def _sync_menu(self, menu):
        keys = list(F.TILE_SOURCES) + [F.NO_BACKGROUND, "natural", "infrared", "hidden"]
        extra = (getattr(self, "act_image", None), getattr(self, "act_mapped", None))
        acts = [a for a in menu.actions() if not a.isSeparator() and a not in extra]
        if getattr(self, "act_mapped", None) is not None:
            self.act_mapped.setChecked(self.model.show_mapped)
        for key, act in zip(keys, acts):
            act.setChecked(key in (self.model.source, self.model.ortho_mode))
            if key in ("natural", "infrared", "hidden"):
                act.setEnabled(bool(self.model.ortho_images) and (key != "infrared" or
                                                                   "infrared" in self.model.ortho_images))

    # ---- view
    def fit(self):
        b = self.model.bounds()
        if b is None or self.width() < 10:
            return
        x0, y0, x1, y1 = b
        margin = 1.15
        self.res = max((x1 - x0) * margin / max(self.width(), 1), (y1 - y0) * margin / max(self.height(), 1), 0.05)
        self.center = ((x0 + x1) / 2, (y0 + y1) / 2)
        self._fitted = True
        self.update()

    def focus(self, index: int, zoom_in: bool = False):
        """Keep the point in view (re-centred when near the border)."""
        if not (0 <= index < len(self.model.xy)):
            return
        x, y = self.model.xy[index]
        if zoom_in:
            fp = self.model.footprint(index)
            if fp:
                span = max(max(p[0] for p in fp) - min(p[0] for p in fp), max(p[1] for p in fp) - min(p[1] for p in fp))
                self.res = max(span * 3 / max(min(self.width(), self.height()), 1), 0.05)
            self.center = (x, y)
        else:
            sx, sy = self.to_screen(x, y)
            m = 0.2
            if not (self.width() * m < sx < self.width() * (1 - m) and self.height() * m < sy < self.height() * (1 - m)):
                self.center = (x, y)
        self.update()

    def to_screen(self, x, y) -> Tuple[float, float]:
        return (self.width() / 2 + (x - self.center[0]) / self.res,
                self.height() / 2 - (y - self.center[1]) / self.res)

    def to_map(self, sx, sy) -> Tuple[float, float]:
        return (self.center[0] + (sx - self.width() / 2) * self.res,
                self.center[1] - (sy - self.height() / 2) * self.res)

    def _on_model_changed(self):
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.btn_fit.move(self.width() - self.btn_fit.sizeHint().width() - 6, 6)
        if not self._fitted:
            self.fit()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._fitted:
            self.fit()

    # ---- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#E9EDF2"))
        note = self._paint_tiles(p)
        self._paint_ortho(p)
        self._paint_selection(p)
        self._paint_flight(p)
        self._paint_footprints(p)
        self._paint_texts(p, note)
        self._paint_hover_thumb(p)
        p.end()

    def _paint_tiles(self, p) -> str:
        source = self.model.source
        if source == F.NO_BACKGROUND or source not in F.TILE_SOURCES:
            return ""
        cache = tile_cache()
        if cache.offline(source):
            return "Background map unavailable (offline?)"
        src = F.TILE_SOURCES[source]
        z = int(round(math.log2(F.WORLD / (256 * self.res))))
        z = max(1, min(src.max_zoom, z))
        x0, y1 = self.to_map(0, 0)
        x1, y0 = self.to_map(self.width(), self.height())
        c0, r0 = F.tile_of(x0, y1, z)
        c1, r1 = F.tile_of(x1, y0, z)
        if (c1 - c0 + 1) * (r1 - r0 + 1) > 120:        # far zoomed out: not worth it
            return ""
        for col in range(c0, c1 + 1):
            for row in range(r0, r1 + 1):
                pix = cache.get((source, z, col, row))
                if pix is None:
                    continue
                bx0, by_top, bx1, by_bottom = F.tile_bounds(col, row, z)
                sx0, sy0 = self.to_screen(bx0, by_top)
                sx1, sy1 = self.to_screen(bx1, by_bottom)
                p.drawPixmap(QRectF(sx0, sy0, sx1 - sx0 + 0.5, sy1 - sy0 + 0.5), pix, QRectF(pix.rect()))
        return ""

    def _paint_ortho(self, p):
        img = self.model.ortho_images.get(self.model.ortho_mode)
        if img is None or not self.model.ortho_corners:
            return
        (tlx, tly), (trx, try_), (blx, bly) = [self.to_screen(*c) for c in self.model.ortho_corners]
        w, h = img.width(), img.height()
        t = QTransform((trx - tlx) / w, (try_ - tly) / w, (blx - tlx) / h, (bly - tly) / h, tlx, tly)
        p.save()
        p.setTransform(t)
        p.drawImage(0, 0, img)
        p.restore()

    def _paint_flight(self, p):
        xy = self.model.xy
        if not xy:
            return
        pts = [QPointF(*self.to_screen(x, y)) for x, y in xy]
        line = [QPointF(*self.to_screen(x, y)) for x, y in self.model.path_xy] if self.model.path_xy else pts
        shown = self.model.visible()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.model.sparse:
            # the whole flight, faint; the trajectory of the mapping on top
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.2, Qt.PenStyle.DashLine))
            p.drawPath(self._polyline(line))
            line_main = [pts[i] for i in self.model.mapped] or [pts[i] for i in shown]
        else:
            line_main = line
        path = self._polyline(line_main)
        p.setPen(QPen(QColor(255, 255, 255, 200), 4 if not self.compact else 3))
        p.drawPath(path)
        p.setPen(QPen(QColor("#17365D"), 1.6 if not self.compact else 1.2))
        p.drawPath(path)
        r = 3.2 if not self.compact else 2.2
        if self.model.sparse:
            r += 0.8
        flagged = set(self.model.flagged)
        # secondary points: small at the scale of the flight, full size once zoomed in (< 6 cm per pixel)
        r_minor = max(1.2, r * min(1.0, max(0.4, 0.06 / max(self.res, 1e-6))))
        for i in shown:
            q = pts[i]
            if self.model.minor is not None and self.model.minor(i) and not self.model.is_selected(i):
                p.setPen(Qt.PenStyle.NoPen if r_minor < r else QPen(QColor("white"), 1))
                p.setBrush(self.model.color_of(i) if self.model.color_of else QColor("#A0AAB4"))
                p.drawEllipse(q, r_minor, r_minor)
                continue
            if i in flagged:                     # left out of the map: a red dot (footprint on hover)
                p.setPen(QPen(QColor("white"), 1))
                p.setBrush(FLAGGED_COLOR)
                p.drawEllipse(q, r, r)
                continue
            color = self.model.color_of(i) if self.model.color_of else QColor("#17365D")
            if self.model.is_selected(i):
                p.setPen(QPen(QColor("#17365D"), 1.4))
                p.setBrush(color)
                p.drawEllipse(q, r + 2, r + 2)
                continue
            p.setPen(QPen(QColor("white"), 1))
            p.setBrush(color)
            p.drawEllipse(q, r, r)
        # take-off
        p.setPen(QPen(QColor("white"), 1.5))
        p.setBrush(QColor("#17365D"))
        p.drawRect(QRectF(line[0].x() - 4, line[0].y() - 4, 8, 8))

    @staticmethod
    def _polyline(points) -> QPainterPath:
        path = QPainterPath(points[0])
        for q in points[1:]:
            path.lineTo(q)
        return path

    def _paint_selection(self, p):
        """Footprints of the images kept for the map: their overlap shows."""
        kept = self.model.footprints_kept()
        if not kept:
            return
        if self.model.progress is not None:
            self._paint_progress(p, kept)
            return
        quads = [q for q in (self._quad(i) for i in kept) if q is not None]
        fill = QColor(Look.SURVEY)
        fill.setAlpha(30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        for q in quads:
            p.drawPolygon(q)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # a white halo under the green outline: visible on aerial photos and on plain maps
        for pen in (QPen(QColor(255, 255, 255, 170), 2.8), QPen(Look.SURVEY, 1.3)):
            p.setPen(pen)
            for q in quads:
                p.drawPolygon(q)

    def _paint_progress(self, p, indices):
        """Footprints still to do (dashed), done (green) and in progress
        (orange): the computation advances along the flight."""
        done, running = self.model.progress
        todo = [q for i in indices if i not in done and i not in running and (q := self._quad(i)) is not None]
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pen in (QPen(QColor(255, 255, 255, 160), 2.4), QPen(QColor("#17365D"), 1.0, Qt.PenStyle.DashLine)):
            p.setPen(pen)
            for q in todo:
                p.drawPolygon(q)
        fill = QColor(Look.SURVEY)
        fill.setAlpha(80)
        quads = [q for i in indices if i in done and (q := self._quad(i)) is not None]
        p.setBrush(fill)
        for pen in (QPen(QColor(255, 255, 255, 170), 2.6), QPen(Look.SURVEY, 1.3)):
            p.setPen(pen)
            for q in quads:
                p.drawPolygon(q)
        fill = QColor(Look.CURSOR)
        fill.setAlpha(30)
        p.setBrush(fill)
        for pen in (QPen(QColor("white"), 4.0), QPen(Look.CURSOR, 2.2)):
            p.setPen(pen)
            for i in indices:
                q = self._quad(i) if i in running else None
                if q is not None:
                    p.drawPolygon(q)

    def _quad(self, index) -> Optional[QPolygonF]:
        fp = self.model.footprint(index)
        if not fp:
            return None
        return QPolygonF([QPointF(*self.to_screen(x, y)) for x, y in fp])

    def _paint_footprints(self, p):
        if self.model.hover is not None and self.model.hover != self.model.current:
            q = self._quad(self.model.hover)
            if q is not None and self.model.hover in self.model.flagged:
                fill = QColor(FLAGGED_COLOR)        # flagged: the hole it leaves in the map
                fill.setAlpha(25)
                p.setBrush(fill)
                for pen in (QPen(QColor(255, 255, 255, 200), 3.0), QPen(FLAGGED_COLOR, 1.6, Qt.PenStyle.DashLine)):
                    p.setPen(pen)
                    p.drawPolygon(q)
            elif q is not None:
                p.setPen(QPen(QColor(255, 255, 255, 230), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawPolygon(q)
        cur = self.model.current
        if cur is None or not (0 <= cur < len(self.model.xy)):
            return
        q = self._quad(cur)
        pix = self.model.image(cur) if (self.model.show_image and not self.compact) else None
        if q is not None and pix is not None:
            src = QPolygonF([QPointF(0, 0), QPointF(pix.width(), 0), QPointF(pix.width(), pix.height()),
                             QPointF(0, pix.height())])
            t = QTransform()
            if QTransform.quadToQuad(src, q, t):
                p.save()
                p.setTransform(t)
                p.setOpacity(0.92)
                p.drawPixmap(0, 0, pix)
                p.restore()
        color = QColor(Look.CURSOR)
        if self.model.cursor_in_point_color and self.model.color_of is not None:
            color = QColor(self.model.color_of(cur))
        if q is not None:
            fill = QColor(color)
            fill.setAlpha(55)
            p.setPen(QPen(QColor(255, 255, 255, 170), 4.0))   # halo: readable on any background
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(q)
            p.setPen(QPen(color, 2.2))
            # no tint over the aligned image: its colours are what is checked
            p.setBrush(Qt.BrushStyle.NoBrush if pix is not None else fill)
            p.drawPolygon(q)
            p.setPen(QPen(QColor("white"), 3.5))          # top of the image
            p.drawLine(q[0], q[1])
            p.setPen(QPen(color, 2.2))
            p.drawLine(q[0], q[1])
        x, y = self.to_screen(*self.model.xy[cur])
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(color)
        p.drawEllipse(QPointF(x, y), 5.5, 5.5)

    def _paint_hover_thumb(self, p):
        i = self.model.hover
        if self.compact or i is None or i == self.model.current or not (0 <= i < len(self.model.xy)):
            return
        pix = self.model.image(i)
        sx, sy = self.to_screen(*self.model.xy[i])
        w = 200
        h = int(w * pix.height() / max(pix.width(), 1)) if pix is not None else 0
        x = sx + 14 if sx + 14 + w < self.width() else sx - 14 - w
        y = min(max(sy - h / 2 - 10, 4), max(self.height() - h - 26, 4))
        stem = self.model.points[i].stem
        box = QRectF(x - 3, y - 3, w + 6, h + 24)
        p.setPen(QPen(QColor("#C5CFDA"), 1))
        p.setBrush(QColor("white"))
        p.drawRoundedRect(box, 5, 5)
        if pix is not None:
            p.drawPixmap(QRectF(x, y, w, h), pix, QRectF(pix.rect()))
        p.setPen(QColor("#17365D"))
        p.drawText(QRectF(x, y + h, w, 20), Qt.AlignmentFlag.AlignCenter, stem)

    def selection_summary(self) -> List[str]:
        """Texts of the bottom right about the images of the map drawn."""
        bits: List[str] = []
        if not self.model.sparse:
            return bits
        n = len(self.model.mapped)
        built = self.model.built
        numbers = {self.model.numbers[i] for i in self.model.mapped}
        if self.model.mapped_by == "next mapping" and built:
            bits.append(f"{n} images of the map" if numbers == built else
                        f"{n} images for the next map (Step 5 again: the map built has {len(built)})")
        else:
            bits.append(f"{n} images Step 5 will map" if self.model.mapped_by == "next mapping"
                        else f"{n} images kept by the best mapping" if self.model.planned
                        else f"{n} images of the mapping")
        if self.model.flagged:
            # flagged after Step 5: they are in the map built, not in the next one
            again = {self.model.numbers[i] for i in self.model.flagged} & (
                built or ({self.model.numbers[i] for i in self.model.mapped}
                          if self.model.mapped_by == "mapping" else set()))
            bits.append(f"⚑ {len(self.model.flagged)} flagged, left out"
                        + (" when Step 5 runs again" if again else ""))
        return bits

    def _paint_texts(self, p, note):
        src = F.TILE_SOURCES.get(self.model.source)
        bits = []
        if src is not None and not tile_cache().offline(self.model.source):
            bits.append(src.attribution)
        if self.model.ortho_images and self.model.ortho_mode != "hidden":
            bits.append("orthophoto IRDrone")
        if self.model.progress is not None and self.model.selection:
            bits.append(f"{len(self.model.progress[0])} of {len(self.model.selection)} done")
        bits += self.selection_summary()
        font = p.font()
        font.setPointSizeF(7.5 if self.compact else 8.0)
        p.setFont(font)
        if bits:
            text = " · ".join(bits)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 8
            r = QRectF(self.width() - w, self.height() - fm.height() - 2, w, fm.height() + 2)
            p.fillRect(r, QColor(255, 255, 255, 190))
            p.setPen(QColor("#3E4C59"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        if note and not self.compact:
            fm = p.fontMetrics()
            r = QRectF(6, self.height() - fm.height() - 8, fm.horizontalAdvance(note) + 12, fm.height() + 4)
            p.fillRect(r, QColor(255, 244, 224, 230))
            p.setPen(QColor("#7A4B00"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, note)
        if not self.compact:
            # scale bar (mercator metres -> ground metres)
            lat = self.model.points[0].lat if self.model.points else 0.0
            ground = self.res * math.cos(math.radians(lat))       # ground metres per pixel
            target = ground * 110
            nice = 10 ** math.floor(math.log10(max(target, 1e-3)))
            for m in (5, 2, 1):
                if m * nice <= target:
                    nice *= m
                    break
            px = nice / ground
            x0, y0 = 12, self.height() - 34
            p.setPen(QPen(QColor("white"), 4))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
            p.setPen(QPen(QColor("#1F2933"), 2))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
            label = f"{nice:g} m" if nice >= 1 else f"{nice * 100:g} cm"
            fm = p.fontMetrics()
            r = QRectF(x0 + px + 4, y0 - fm.height() / 2 - 1, fm.horizontalAdvance(label) + 8, fm.height() + 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor("#1F2933"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

    # ---- mouse
    def nearest(self, sx, sy, radius=12) -> Optional[int]:
        best, best_d = None, radius * radius
        for i in self.model.visible():
            x, y = self.model.xy[i]
            px, py = self.to_screen(x, y)
            d = (px - sx) ** 2 + (py - sy) ** 2
            if d <= best_d:
                best, best_d = i, d
        return best

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        pos = e.position()
        mx, my = self.to_map(pos.x(), pos.y())
        self.res = min(max(self.res * (0.8 ** steps), 0.02), 2000.0)
        self.center = (mx - (pos.x() - self.width() / 2) * self.res,
                       my + (pos.y() - self.height() / 2) * self.res)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = (e.position(), self.center)
            self._dragged = False

    def mouseMoveEvent(self, e):
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            start, center = self._press
            d = e.position() - start
            if abs(d.x()) + abs(d.y()) > 3:
                self._dragged = True
            if self._dragged:
                self.center = (center[0] - d.x() * self.res, center[1] + d.y() * self.res)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
            return
        i = self.nearest(e.position().x(), e.position().y())
        self.setCursor(Qt.CursorShape.PointingHandCursor if i is not None else Qt.CursorShape.ArrowCursor)
        if i is not None:
            self.setToolTip(self.model.points[i].stem)
        self.hovered.emit(i)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        self._press = None
        self.unsetCursor()
        if self._dragged:
            return
        i = self.nearest(e.position().x(), e.position().y())
        if i is not None:
            self.picked.emit(i)
        else:
            self.clicked_empty.emit()

    def leaveEvent(self, e):
        self.hovered.emit(None)
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.fit()


class _OrthoSignals(QObject):
    loaded = pyqtSignal(object)
    ground = pyqtSignal(str)


class _OrthoJob(QRunnable):
    def __init__(self, mission, points=None, ortho=True):
        super().__init__()
        self.mission, self.points, self.ortho = mission, points, ortho
        self.signals = _OrthoSignals()

    def run(self):
        try:
            if self.points:
                source = F.find_ground(self.mission, self.points)
                self.signals.ground.emit(source)
            if self.ortho:
                self.signals.loaded.emit(F.load_orthophoto(self.mission))
        except RuntimeError:      # closing
            pass


PHASE_COLORS = {"sync": Look.SYNC, "survey": Look.SURVEY}


def phase_colors(mission: Path):
    """color_of(number) after the phases of Step 2 (grey outside them)."""
    ph = F.phases(mission)
    other = QColor("#A0AAB4")
    return lambda number: PHASE_COLORS.get(ph.get(number), other)


def map_model_for(mission: Path, color_of=None, with_ortho: bool = True, shoot_points_only: bool = False,
                  sparse_mapping: bool = False, parent=None) -> Optional[MapModel]:
    """Model of a mission's flight (None without positions): the shoot
    points (every visible image before Step 3) on the whole flight. The
    orthophoto and the ground are read in the background. `color_of(number)`
    gives the colour of a point (default: phases of Step 2). With
    `sparse_mapping`, only the shoot points of the map are drawn: the ones
    of the mapping done, else the ones the next run of Step 5 will map, else
    the ones kept by the best mapping; the flagged ones in red."""
    track = F.mission_track(mission, shoot_points_only=shoot_points_only)
    if not track:
        return None
    if color_of is None:
        color_of = phase_colors(mission)
    path = F.image_track(mission)
    mapped, mapped_by, flagged, built = None, "mapping", None, None
    if sparse_mapping:
        # the images of the map: once Step 4 is done, the ones the next run of
        # Step 5 will map (its own selection, with the settings of its last run,
        # over the images aligned now: realigned ones in, flagged ones out and
        # drawn in red), even when a map is built; else the ones of the map
        # built; else the best mapping planned (Steps 2 and 4)
        _kept, flagged = F.aligned_selection(mission)
        built = F.mapped_numbers(mission) if F.orthophoto_path(mission).is_file() else set()
        import IRD_Interactive_ODM as ODM
        mapped, mapped_by = ODM.planned_mapping_numbers(mission), "next mapping"
        if not mapped:
            mapped, mapped_by = built, "mapping"
        if not mapped:
            import best_mapping as BM
            mapped, mapped_by = BM.planned_numbers(mission), "best mapping"
    model = MapModel(track, fov=F.field_of_view(F.camera_model(mission)), parent=parent,
                     path=path if len(path) > len(track) else None,
                     mapped=mapped, mapped_by=mapped_by, flagged=flagged, built=built,
                     color_of=lambda i: color_of(track[i].number))
    # in the background: ground under the drone (footprint size), orthophoto
    job = _OrthoJob(Path(mission), track, with_ortho and F.orthophoto_path(mission).is_file())
    model._job = job                      # keeps the signals alive
    job.signals.loaded.connect(model.set_ortho)
    job.signals.ground.connect(model.grounds_found)
    QThreadPool.globalInstance().start(job)
    return model
