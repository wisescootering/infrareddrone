# -*- coding: utf-8 -*-
"""
Home page of the main window.

    welcome   no mission loaded: New mission / Open a mission, and the recent
              missions of the working folder with their progress
    mission   the current mission: what is done, what comes next ("Continue"),
              a few figures (images, pairs, aligned, flagged) and the review
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget,
                             QVBoxLayout, QWidget)

import IRD_Interactive_look as Look
import IRD_Interactive_progress as Progress

STEP_TITLES = {
    1: ("Mission", "Copy the images from the SD cards"),
    2: ("Flight timeline", "Check the synchronisation and survey phases"),
    3: ("Synchronise", "Measure the clock offset and pair the images"),
    4: ("Align", "Align the infrared on the visible images, then review them"),
    5: ("Map", "Georeference, orthophoto and terrain model"),
    6: ("Archive", "Keep the results, clean the mission folder"),
}
WHAT_NEXT = {
    1: "Insert the SD cards: the images are found and copied.",
    2: "The phases are detected automatically: check them, then the synchronisation, the pairing and "
       "the alignment run on their own.",
    3: "Detection of the rotating target, clock alignment and pairing run on their own, then the alignment.",
    4: "Align the image pairs of the survey, then review the result.",
    5: "Build the orthophoto and the terrain model with OpenDroneMap.",
    6: "Archive the mission to free disk space.",
}
STEP_TIPS = {
    1: "Create a new mission: find the images on the SD cards and copy them.",
    2: "Check the automatically detected flight phases (synchronisation, survey).",
    3: "Synchronise the visible and infrared cameras and pair the images.",
    4: "Align the infrared on the visible images, then review them.",
    5: "Georeference, orthophoto and terrain model (OpenDroneMap).",
    6: "Archive the mission (cleans the mission folder).",
}


# ---------------------------------------------------------------------------
#  Missions on disk (no Qt widgets)
# ---------------------------------------------------------------------------
@dataclass
class MissionInfo:
    folder: Path
    params: dict
    done: Dict[int, str]

    @property
    def name(self) -> str:
        return self.folder.name

    def next_step(self) -> Optional[int]:
        """First step not done (Step 6, archiving, is optional: None once 1-5 are done)."""
        return next((s for s in range(1, 6) if s not in self.done), None)

    def subtitle(self) -> str:
        bits = []
        date, time_ = self.params.get("Date"), self.params.get("Time")
        if date:
            try:
                y, m, d = str(date).replace("-", ":").split(":")
                bits.append(f"{d}/{m}/{y}" + (f" {str(time_)[:5]}" if time_ else ""))
            except ValueError:
                bits.append(str(date))
        for key in ("Location", "Pilot", "Description"):
            if self.params.get(key):
                bits.append(str(self.params[key]))
        return " · ".join(bits)


def read_mission(folder: Path) -> Optional[MissionInfo]:
    folder = Path(folder)
    path = folder / "FlightAnalytics" / "mission_parameters.json"
    try:
        with open(path, encoding="utf-8") as f:
            params = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(params, dict):
        return None
    return MissionInfo(folder=folder, params=params, done=Progress.done_steps(folder))


def recent_missions(working_dir: Path, limit: int = 6) -> List[MissionInfo]:
    """FLY-* missions of the working folder, most recently changed first."""
    try:
        folders = [p for p in Path(working_dir).iterdir() if p.is_dir() and p.name.startswith("FLY-")]
    except OSError:
        return []

    def changed(p):
        times = []
        for name in ("FlightAnalytics/wizard_progress.json", "FlightAnalytics/mission_parameters.json"):
            try:
                times.append((p / name).stat().st_mtime)
            except OSError:
                pass
        return max(times) if times else 0.0
    folders.sort(key=changed, reverse=True)
    out = []
    for p in folders:
        info = read_mission(p)
        if info is not None:
            out.append(info)
        if len(out) >= limit:
            break
    return out


def mission_figures(folder: Path) -> List[tuple]:
    """(text, colour) facts about the mission, read from its files."""
    folder = Path(folder)
    out = []
    counts = []
    for band in ("VIS", "NIR"):
        try:
            n = sum(1 for p in (folder / "AerialPhotography" / band).iterdir() if p.suffix.lower() == ".dng")
        except OSError:
            n = 0
        counts.append(n)
    if any(counts):
        out.append((f"{counts[0]} visible · {counts[1]} infrared images", Look.BLUE))
    pairs = _points(folder / "AerialPhotography" / "shoot_points.json")
    if pairs is not None:
        out.append((f"{len(pairs)} pairs", Look.SYNC))
    aligned = _points(folder / "ImgIRdrone" / "shoot_points.json")
    if aligned is not None:
        flagged = sum(1 for p in aligned if isinstance(p, dict) and p.get("failed"))
        out.append((f"{len(aligned)} aligned", Look.SURVEY))
        if flagged:
            out.append((f"⚑ {flagged} flagged", Look.NIR_ACCENT))
    if (folder / "mapping_MULTI" / "mapping_result" / "odm_orthophoto.tif").is_file():
        out.append(("Orthophoto ready", Look.SURVEY))
    return out


def _points(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pts = data.get("shoot_points")
        return pts if isinstance(pts, list) else None
    except (OSError, ValueError, AttributeError):
        return None


def mission_picture(folder: Path) -> Optional[Path]:
    """An aligned image (false colours) if there is one, else the vertical profile."""
    out = Path(folder) / "ImgIRdrone"
    try:
        vir = sorted(out.glob("VIR_*_local.jpg")) or sorted(out.glob("VIR_*.jpg"))
    except OSError:
        vir = []
    if vir:
        return vir[len(vir) // 2]
    return None


# ---------------------------------------------------------------------------
#  Widgets
# ---------------------------------------------------------------------------
class ActionCard(QPushButton):
    """Large clickable card: icon, title and a line of explanation."""

    def __init__(self, icon, title, text, primary=False, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bg, fg, sub, border, hover = (("#17365D", "white", "#C9D6E6", "#17365D", "#244A73") if primary else
                                      ("white", "#17365D", "#6B7785", "#DDE3EA", "#EEF3F8"))
        self.setStyleSheet(f"QPushButton {{ background: {bg}; border: 1px solid {border}; border-radius: 10px;"
                           f" text-align: left; padding: 0; }} QPushButton:hover {{ background: {hover}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(14)
        ic = QLabel(icon)
        ic.setStyleSheet(f"color: {fg}; font-size: 22pt; background: transparent;")
        ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"color: {fg}; font-size: 13pt; font-weight: bold; background: transparent;")
        s = QLabel(text)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {sub}; background: transparent;")
        for w in (t, s):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            col.addWidget(w)
        lay.addWidget(ic)
        lay.addLayout(col, 1)
        self.setMinimumHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class RecentRow(QPushButton):
    def __init__(self, info: MissionInfo, parent=None):
        super().__init__(parent)
        self.info = info
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: white; border: 1px solid #E4E8EE; border-radius: 6px;"
                           " text-align: left; } QPushButton:hover { background: #EEF3F8; border-color: #C5CFDA; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(info.name)
        name.setStyleSheet("font-weight: bold; color: #17365D; background: transparent;")
        sub = QLabel(info.subtitle())
        sub.setStyleSheet("color: #6B7785; background: transparent;")
        col.addWidget(name)
        col.addWidget(sub)
        dots = QLabel(progress_dots(info.done))
        dots.setTextFormat(Qt.TextFormat.RichText)
        dots.setToolTip(", ".join(f"Step {s} done" for s in sorted(info.done)) or "Nothing done yet")
        for w in (name, sub, dots):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addLayout(col, 1)
        lay.addWidget(dots)
        self.setMinimumHeight(48)
        self.setToolTip(f"Open this mission\n{info.folder}")


def progress_dots(done) -> str:
    return "".join(f"<span style='color:{'#2E7D32' if s in done else '#C5CFDA'}; font-size: 12pt'>●</span>"
                   for s in range(1, 7)) + "&nbsp;<span style='color:#6B7785'>" + \
        (f"{len([s for s in done if s <= 6])}/6" if done else "new") + "</span>"


TILE_DONE, TILE_NEXT, TILE_TODO = "done", "next", "todo"
# Step 1 creates the mission: once done, its tile edits the mission details
# (the SD cards are not read again)
_TILE_LOOK = {   # background, border, badge background, badge text, title, detail, hover
    TILE_DONE: ("white", "#CFE3D0", "#2E7D32", "white", "#1F2933", "#2E7D32", "#F1F8F1"),
    TILE_NEXT: ("#EEF3F8", "#17365D", "#17365D", "white", "#17365D", "#17365D", "#E1EAF3"),
    TILE_TODO: ("white", "#E4E8EE", "#E4E8EE", "#6B7785", "#6B7785", "#A0AAB4", "#F5F7FA"),
}


class StepTile(QPushButton):
    """One step of the rail: badge (number or ✓), name and state. Click: run the step."""

    def __init__(self, step: int, parent=None):
        super().__init__(parent)
        self.step = step
        self.state = TILE_TODO
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        self.badge = QLabel()
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = QLabel(STEP_TITLES[step][0])
        self.detail = QLabel()
        col.addWidget(self.name)
        col.addWidget(self.detail)
        for w in (self.badge, self.name, self.detail):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.badge)
        lay.addLayout(col, 1)
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_state(TILE_TODO)

    def set_state(self, state: str, detail: str = ""):
        self.state = state
        bg, border, badge_bg, badge_fg, title, sub, hover = _TILE_LOOK[state]
        width = 2 if state == TILE_NEXT else 1
        pad = 0 if state == TILE_NEXT else 1          # same outer size whatever the border
        self.setStyleSheet(f"StepTile {{ background: {bg}; border: {width}px solid {border}; border-radius: 8px;"
                           f" margin: {pad}px; }} StepTile:hover {{ background: {hover}; }}")
        self.badge.setText("✓" if state == TILE_DONE else str(self.step))
        self.badge.setStyleSheet(f"background: {badge_bg}; color: {badge_fg}; border-radius: 13px;"
                                 " font-weight: bold;")
        self.name.setStyleSheet(f"color: {title}; font-weight: bold; background: transparent;")
        self.detail.setStyleSheet(f"color: {sub}; font-size: 8.5pt; background: transparent;")
        self.detail.setText(detail)
        what = STEP_TIPS[self.step]
        action = {TILE_DONE: "Done. Click to run it again.", TILE_NEXT: "Next step: click to start it.",
                  TILE_TODO: "Click to open it."}[state]
        if state == TILE_DONE and self.step == 1:
            what = "Mission created."
            action = ("Click to edit its details (description, pilot, cameras): the SD cards are not read again.\n"
                      "A new mission is started from \"‹ All missions\".")
        self.setToolTip(f"Step {self.step} · {what}\n{action}\n(F1: help on this step)")


class StepRail(QWidget):
    """The six steps of a mission, left to right; a click on a step emits clicked(step)."""
    clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.tiles: Dict[int, StepTile] = {}
        for s in range(1, 7):
            if s > 1:
                arrow = QLabel("›")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(16)
                arrow.setStyleSheet("color: #A0AAB4; font-size: 14pt; background: transparent;")
                row.addWidget(arrow)
            tile = StepTile(s)
            tile.clicked.connect(lambda _=False, step=s: self.clicked.emit(step))
            row.addWidget(tile, 1)
            self.tiles[s] = tile

    def show_progress(self, done: Dict[int, str], nxt: Optional[int]):
        for s, tile in self.tiles.items():
            if s in done:
                tile.set_state(TILE_DONE, "Done " + _short_date(done[s]) + (" · edit" if s == 1 else ""))
            elif s == nxt:
                tile.set_state(TILE_NEXT, "Next")
            else:
                tile.set_state(TILE_TODO, "")


def _short_date(stamp: str) -> str:
    """'2026-11-08T10:12:00' -> '08/11/2026'."""
    try:
        y, m, d = str(stamp)[:10].split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return str(stamp)[:10]


class ScaledPicture(QLabel):
    """Image scaled to the label (kept whole), re-scaled when the label is resized."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_picture(self, pix: Optional[QPixmap]):
        self._pix = pix if pix is not None and not pix.isNull() else None
        self._render()

    def _render(self):
        if self._pix is None:
            self.setPixmap(QPixmap())
        elif self.width() > 10 and self.height() > 10:
            self.setPixmap(self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render()


class HomePage(QStackedWidget):
    """Welcome page (no mission) or the current mission."""
    new_mission = pyqtSignal()
    open_mission = pyqtSignal()
    open_recent = pyqtSignal(object)      # Path
    run_step = pyqtSignal(int)          # "Continue": the next step, chained
    step_clicked = pyqtSignal(int)      # a step of the rail
    review = pyqtSignal()

    def __init__(self, hero_image: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.hero_image = hero_image
        self.setStyleSheet(f"HomePage, #page {{ background: {Look.BACKGROUND}; }} "
                           "QLabel { background: transparent; }")
        self.addWidget(self._welcome())
        self.addWidget(self._mission_page())
        self.info: Optional[MissionInfo] = None
        self._next = 1

    # ---- welcome
    def _welcome(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(28)
        self.hero = ScaledPicture()
        self.hero.set_picture(QPixmap(str(self.hero_image)) if self.hero_image and Path(self.hero_image).is_file()
                              else None)
        lay.addWidget(self.hero, 5)
        col = QVBoxLayout()
        col.setSpacing(12)
        title = QLabel("IRDrone")
        title.setStyleSheet("font-size: 22pt; font-weight: bold; color: #17365D;")
        tag = QLabel("Visible and near-infrared drone surveys: from the SD cards to the vegetation map.")
        tag.setWordWrap(True)
        tag.setStyleSheet("color: #6B7785; font-size: 11pt;")
        col.addWidget(title)
        col.addWidget(tag)
        col.addSpacing(8)
        self.card_new = ActionCard("✚", "New mission", "Insert the SD cards of the drone and of the infrared "
                                   "camera: the images are found and copied.", primary=True)
        self.card_new.clicked.connect(self.new_mission.emit)
        self.card_open = ActionCard("📂", "Open a mission", "Continue a mission already created "
                                    "(folder FLY-YYYYMMDD-hhmm-place).")
        self.card_open.clicked.connect(self.open_mission.emit)
        col.addWidget(self.card_new)
        col.addWidget(self.card_open)
        col.addSpacing(10)
        self.recent_title = QLabel("Recent missions")
        self.recent_title.setStyleSheet("font-weight: bold; color: #3E4C59;")
        col.addWidget(self.recent_title)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(6)
        col.addLayout(self.recent_box)
        col.addStretch(1)
        lay.addLayout(col, 4)
        return page

    def set_recent(self, missions: List[MissionInfo]):
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.recent_title.setVisible(bool(missions))
        for info in missions:
            row = RecentRow(info)
            row.clicked.connect(lambda _=False, p=info.folder: self.open_recent.emit(p))
            self.recent_box.addWidget(row)

    # ---- mission
    def _mission_page(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self.m_title = QLabel()
        self.m_title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #17365D;")
        self.m_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.m_title.setToolTip("Click to open the mission folder")
        self.m_title.mousePressEvent = lambda _e: self._open_folder()
        self.m_sub = QLabel()
        self.m_sub.setStyleSheet("color: #6B7785; font-size: 11pt;")
        col.addWidget(self.m_title)
        col.addWidget(self.m_sub)
        head.addLayout(col, 1)
        self.btn_all = QPushButton("‹ All missions")
        self.btn_all.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_all.setToolTip("New mission, open another mission, recent missions")
        self.btn_all.clicked.connect(lambda: self.setCurrentIndex(0))
        head.addWidget(self.btn_all, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.rail = StepRail()
        self.rail.clicked.connect(self.step_clicked.emit)
        lay.addWidget(self.rail)

        body = QHBoxLayout()
        body.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.next_card = QFrame()
        self.next_card.setObjectName("card")
        self.next_card.setStyleSheet(Look.CARD_STYLE)
        nl = QVBoxLayout(self.next_card)
        nl.setContentsMargins(18, 14, 18, 14)
        self.next_title = QLabel()
        self.next_title.setStyleSheet("font-size: 13pt; font-weight: bold; color: #1F2933;")
        self.next_text = QLabel()
        self.next_text.setWordWrap(True)
        self.next_text.setStyleSheet("color: #3E4C59;")
        self.btn_continue = QPushButton()
        self.btn_continue.setStyleSheet(Look.PRIMARY_STYLE)
        self.btn_continue.setMinimumHeight(42)
        self.btn_continue.clicked.connect(self._continue)
        self.btn_continue.setToolTip("Open the next step of the mission.")
        nl.addWidget(self.next_title)
        nl.addWidget(self.next_text)
        nl.addSpacing(6)
        nl.addWidget(self.btn_continue, 0, Qt.AlignmentFlag.AlignLeft)
        left.addWidget(self.next_card)
        self.btn_review = ActionCard("🔍", "Review the aligned images",
                                     "Check every survey image on a time line, flag the misaligned ones and "
                                     "realign them by hand.")
        self.btn_review.clicked.connect(self.review.emit)
        left.addWidget(self.btn_review)
        self.figures = QHBoxLayout()
        self.figures.setSpacing(8)
        left.addLayout(self.figures)
        left.addStretch(1)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(6)
        switch = QHBoxLayout()
        switch.setSpacing(4)
        switch.addStretch(1)
        self.btn_show_map = QPushButton("Map")
        self.btn_show_image = QPushButton("Image")
        for b in (self.btn_show_map, self.btn_show_image):
            b.setCheckable(True)
            b.setStyleSheet(Look.SECONDARY_STYLE)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            switch.addWidget(b)
        self.btn_show_map.setToolTip("The flight on the map: phases of Step 2, orthophoto of Step 5, aerial photos "
                                     "(online). Click a point to see the ground covered by its image.")
        self.btn_show_image.setToolTip("Show an aligned image of the mission instead of the map.")
        self.btn_show_map.clicked.connect(lambda: self._show_right("map"))
        self.btn_show_image.clicked.connect(lambda: self._show_right("image"))
        right.addLayout(switch)
        self.right_stack = QStackedWidget()
        self.picture = ScaledPicture()
        self.map_holder = QWidget()
        self.map_holder_lay = QVBoxLayout(self.map_holder)
        self.map_holder_lay.setContentsMargins(0, 0, 0, 0)
        self.right_stack.addWidget(self.picture)
        self.right_stack.addWidget(self.map_holder)
        right.addWidget(self.right_stack, 1)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)
        self.map_view = None
        self._map_key = None
        self._right = "map"
        return page

    def _show_right(self, which):
        if which == "map" and self.map_view is None:
            which = "image"
        else:
            self._right = which
        self.right_stack.setCurrentWidget(self.map_holder if which == "map" else self.picture)
        self.btn_show_map.setChecked(which == "map")
        self.btn_show_image.setChecked(which == "image")

    def _update_map(self, folder: Path):
        """Flight map of the mission (built again only when its files changed)."""
        import flight_map as F

        def stamp(path):
            try:
                return path.stat().st_mtime
            except OSError:
                return None
        ortho = stamp(F.orthophoto_path(folder))
        key = (str(folder), stamp(folder / "AerialPhotography" / "shoot_points.json"),
               ortho, stamp(folder / "FlightAnalytics" / "flight_timeline.json"),
               stamp(folder / "AerialPhotography" / "VIS"),
               stamp(folder / "FlightAnalytics" / "best_mapping.json"),
               stamp(folder / "mapping_MULTI" / "img_best_mappping.json"),
               stamp(folder / "mapping_MULTI" / "mapping_result" / "ortho_dtm.tif"))
        if key == self._map_key:
            return
        # the map of Step 5 has just been built (or built again): show it
        new_map = (ortho is not None and self._map_key is not None
                   and self._map_key[0] == key[0] and self._map_key[2] != ortho)
        self._map_key = key
        if self.map_view is not None:
            self.map_view.setParent(None)
            self.map_view.deleteLater()
            self.map_view = None
        try:
            import IRD_Interactive_map as MapV
            model = MapV.map_model_for(folder, sparse_mapping=True, parent=self)
        except Exception as e:  # the map is a help, never a blocker
            print(f"Map unavailable: {e}")
            model = None
        if model is not None:
            self.map_view = MapV.FlightMapView(model)
            self.map_view.picked.connect(model.set_current)
            self.map_view.hovered.connect(model.set_hover)
            self.map_holder_lay.addWidget(self.map_view)
            if new_map:
                self._right = "map"
                if model.ortho_mode == "hidden":
                    model.set_ortho_mode("natural")
        self.btn_show_map.setEnabled(self.map_view is not None)

    def show_mission(self, folder: Optional[Path]):
        """Mission page of `folder` (None: welcome page)."""
        info = read_mission(folder) if folder else None
        if info is None and folder:
            info = MissionInfo(folder=Path(folder), params={}, done=Progress.done_steps(folder))
        self.info = info
        if info is None:
            self.setCurrentIndex(0)
            return
        self.m_title.setText(info.name)
        self.m_sub.setText(info.subtitle())
        nxt = info.next_step()
        self.rail.show_progress(info.done, nxt)
        if nxt is None:
            self.next_title.setText("✓ Mission processed")
            self.next_text.setText("The orthophoto and the terrain model are in mapping_MULTI. "
                                   "Archive the mission to free disk space, or click a step above to run it again.")
            self.btn_continue.setText("Archive the mission  ▶")
            self.btn_continue.setToolTip("Open Step 6: delete the working files, keep what is needed to "
                                         "process the mission again.\n(F1: help on this button)")
            self._next = 6
        else:
            name, what = STEP_TITLES[nxt]
            self.next_title.setText(f"Next: Step {nxt} · {what}")
            self.next_text.setText(WHAT_NEXT[nxt])
            self.btn_continue.setText(f"Continue with Step {nxt}  ▶")
            self.btn_continue.setToolTip(f"Open Step {nxt}: {what}."
                                         "\n(F1: help on this button)")
            self._next = nxt
        has_review = (info.folder / "ImgIRdrone" / "shoot_points.json").is_file()
        self.btn_review.setVisible(has_review)
        while self.figures.count():
            w = self.figures.takeAt(0).widget()
            if w is not None:
                w.hide()          # gone at once, even before Qt deletes it
                w.deleteLater()
        for text, color in mission_figures(info.folder):
            self.figures.addWidget(Look.chip(color, text))
        self.figures.addStretch(1)
        pic = mission_picture(info.folder)
        self.picture.set_picture(QPixmap(str(pic)) if pic is not None else (
            QPixmap(str(self.hero_image)) if self.hero_image and Path(self.hero_image).is_file() else None))
        self.picture.setToolTip(pic.name if pic is not None else "")
        self._update_map(info.folder)
        self._show_right(self._right)
        self.setCurrentIndex(1)

    def _open_folder(self):
        if self.info is not None:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.info.folder)))

    def _continue(self):
        self.run_step.emit(self._next)
