# -*- coding: utf-8 -*-
"""
Common look of the modern wizard windows (flight timeline, new mission,
review, home page): colours, button styles, chips and window sizing.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

INK = QColor("#1F2933")
MUTED = QColor("#6B7785")
GRID = QColor("#E4E8EE")
PANEL = QColor("#F5F7FA")
BLUE = QColor("#17365D")
SYNC = QColor("#7B3FA0")
SURVEY = QColor("#2E7D32")
NIR_ACCENT = QColor("#B03A2E")
CURSOR = QColor("#E8A33D")
WARNING = QColor("#C26A00")

BACKGROUND = "#FAFBFC"
DIALOG_STYLE = f"QDialog {{ background: {BACKGROUND}; }} QLabel {{ color: #1F2933; }}"

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
QPushButton:checked { background-color: #17365D; color: white; border-color: #17365D; }
QPushButton:disabled { color: #A0AAB4; }
"""
DANGER_STYLE = """
QPushButton { background-color: white; color: #B03A2E; padding: 8px 14px; font-weight: bold;
              border: 1px solid #E3B4AE; border-radius: 6px; }
QPushButton:hover { background-color: #FBEDEB; }
QPushButton:checked { background-color: #B03A2E; color: white; border-color: #B03A2E; }
QPushButton:disabled { color: #A0AAB4; border-color: #E4E8EE; }
"""
NUDGE_STYLE = """
QToolButton { background: white; color: #17365D; border: 1px solid #C5CFDA; border-radius: 4px;
              min-width: 22px; min-height: 20px; font-weight: bold; }
QToolButton:hover { background: #EEF3F8; }
QToolButton:disabled { color: #C5CFDA; border-color: #E4E8EE; }
"""
CARD_STYLE = "#card { background: white; border: 1px solid #DDE3EA; border-radius: 8px; }"
TITLE_STYLE = "font-size: 14pt; font-weight: bold; color: #17365D;"
SUBTITLE_STYLE = "color: #6B7785;"
MESSAGE_STYLE = "background: #FFF4E0; color: #7A4B00; border-radius: 6px; padding: 3px 10px;"
PROGRESS_STYLE = ("QProgressBar { background: #E4E8EE; border: none; border-radius: 2px; }"
                  "QProgressBar::chunk { background: #17365D; border-radius: 2px; }")


def chip(color, text: str = "", tip: str = "") -> QLabel:
    """Small rounded label tinted with `color` (hidden while empty)."""
    lab = QLabel()
    c = QColor(color)
    lab.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},28);"
                      f"color: {c.name()}; border-radius: 9px; padding: 2px 9px; font-weight: bold;")
    set_chip(lab, text, tip)
    return lab


def set_chip(lab: QLabel, text: str, tip: str = "") -> None:
    lab.setText(text)
    lab.setToolTip(tip)
    lab.setVisible(bool(text))


def bgr_to_pixmap(img) -> QPixmap:
    return QPixmap.fromImage(bgr_to_qimage(img))


def bgr_to_qimage(img) -> QImage:
    """QImage (own copy) of a BGR or grey numpy image; safe in a worker thread."""
    import numpy as np
    if img.ndim == 2:
        img = np.ascontiguousarray(img)
        h, w = img.shape
        return QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    img = np.ascontiguousarray(img[:, :, ::-1])   # BGR -> RGB
    h, w = img.shape[:2]
    return QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def fit_to_screen(dialog, parent=None, max_w=1500, max_h=1000, ratio=0.95):
    """Centre `dialog` on the screen of `parent`, as large as the screen allows
    (title bar and taskbar margin kept). Returns (width, height)."""
    screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
    g = screen.availableGeometry()
    w, h = min(max_w, int(g.width() * ratio)), min(max_h, g.height() - 48)
    dialog.setGeometry(g.x() + (g.width() - w) // 2, g.y() + (g.height() - h) // 2, w, h)
    return w, h


def fmt_time(t: float) -> str:
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------------------
#  Stage tracker: the chained stages of a step, left to right
# ---------------------------------------------------------------------------
STAGE_PENDING, STAGE_RUNNING, STAGE_DONE, STAGE_FAILED, STAGE_SKIPPED = \
    "pending", "running", "done", "failed", "skipped"
_STAGE_LOOK = {   # icon, icon colour, title colour
    STAGE_PENDING: ("○", "#A0AAB4", "#6B7785"),
    STAGE_RUNNING: ("●", "#E8A33D", "#1F2933"),
    STAGE_DONE: ("✓", "#2E7D32", "#1F2933"),
    STAGE_FAILED: ("✗", "#B03A2E", "#B03A2E"),
    STAGE_SKIPPED: ("–", "#A0AAB4", "#A0AAB4"),
}


class StageTracker:
    """Row of stages ("✓ Target detected  —  ● Pairing images  —  ○ ...") with a
    detail line under each. Build with `widget()`; update with `set()`."""

    def __init__(self, titles):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
        self.titles = list(titles)
        self.states = [STAGE_PENDING] * len(self.titles)
        self._widget = QFrame()
        self._widget.setObjectName("stages")
        self._widget.setStyleSheet("#stages { background: white; border: 1px solid #DDE3EA; border-radius: 8px; }")
        row = QHBoxLayout(self._widget)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self._icons, self._names, self._details = [], [], []
        for k, title in enumerate(self.titles):
            if k:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color: #DDE3EA;")
                line.setMinimumWidth(16)
                row.addWidget(line, 1)
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            icon = QLabel()
            icon.setFixedWidth(18)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(title)
            bold = name.font()
            bold.setBold(True)
            from PyQt6.QtGui import QFontMetrics
            name.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(title) + 2)   # no jump when bold
            detail = QLabel()
            detail.setStyleSheet("color: #6B7785; font-size: 8.5pt;")
            text.addWidget(name)
            text.addWidget(detail)
            lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            lay.addLayout(text)
            row.addWidget(cell)
            self._icons.append(icon)
            self._names.append(name)
            self._details.append(detail)
            self._paint(k)

    def widget(self):
        return self._widget

    def set(self, index: int, state: str, detail: str = None):
        self.states[index] = state
        if detail is not None:
            self._details[index].setText(detail)
        self._paint(index)

    def detail(self, index: int, text: str):
        self._details[index].setText(text)

    def _paint(self, k):
        icon, icolor, tcolor = _STAGE_LOOK[self.states[k]]
        self._icons[k].setText(icon)
        self._icons[k].setStyleSheet(f"color: {icolor}; font-size: 11pt; font-weight: bold;")
        weight = "bold" if self.states[k] == STAGE_RUNNING else "normal"
        self._names[k].setStyleSheet(f"color: {tcolor}; font-weight: {weight};")
