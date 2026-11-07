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


def progress_dots(done) -> str:
    return "".join(f"<span style='color:{'#2E7D32' if s in done else '#C5CFDA'}; font-size: 12pt'>●</span>"
                   for s in range(1, 7)) + "&nbsp;<span style='color:#6B7785'>" + \
        (f"{len([s for s in done if s <= 6])}/6" if done else "new") + "</span>"


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
    run_step = pyqtSignal(int)
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
        self.m_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.m_sub = QLabel()
        self.m_sub.setStyleSheet("color: #6B7785; font-size: 11pt;")
        col.addWidget(self.m_title)
        col.addWidget(self.m_sub)
        head.addLayout(col, 1)
        self.btn_all = QPushButton("All missions")
        self.btn_all.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_all.clicked.connect(lambda: self.setCurrentIndex(0))
        head.addWidget(self.btn_all, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.tracker = Look.StageTracker([f"{s} {STEP_TITLES[s][0]}" for s in range(1, 7)])
        lay.addWidget(self.tracker.widget())

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
        self.picture = ScaledPicture()
        body.addWidget(self.picture, 1)
        lay.addLayout(body, 1)
        return page

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
        for s in range(1, 7):
            if s in info.done:
                self.tracker.set(s - 1, Look.STAGE_DONE, info.done[s][:10])
            elif s == nxt:
                self.tracker.set(s - 1, Look.STAGE_RUNNING, "next")
            else:
                self.tracker.set(s - 1, Look.STAGE_PENDING, "")
        if nxt is None:
            self.next_title.setText("✓ Mission processed")
            self.next_text.setText("The orthophoto and the terrain model are in mapping_MULTI. "
                                   "Archive the mission to free disk space, or run a step again from the bar above.")
            self.btn_continue.setText("Archive the mission  ▶")
            self._next = 6
        else:
            name, what = STEP_TITLES[nxt]
            self.next_title.setText(f"Next: Step {nxt} · {what}")
            self.next_text.setText(WHAT_NEXT[nxt])
            self.btn_continue.setText(f"Continue with Step {nxt}  ▶")
            self._next = nxt
        has_review = (info.folder / "ImgIRdrone" / "shoot_points.json").is_file()
        self.btn_review.setVisible(has_review)
        while self.figures.count():
            w = self.figures.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for text, color in mission_figures(info.folder):
            self.figures.addWidget(Look.chip(color, text))
        self.figures.addStretch(1)
        pic = mission_picture(info.folder)
        self.picture.set_picture(QPixmap(str(pic)) if pic is not None else (
            QPixmap(str(self.hero_image)) if self.hero_image and Path(self.hero_image).is_file() else None))
        self.picture.setToolTip(pic.name if pic is not None else "")
        self.setCurrentIndex(1)

    def _continue(self):
        self.run_step.emit(self._next)
