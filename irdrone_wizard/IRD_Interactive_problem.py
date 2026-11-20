# -*- coding: utf-8 -*-
"""When a step fails: what happened, in plain words, and how to fix it.

``from_error`` turns the message of an error into a ``Problem`` (the errors
IRDrone raises itself carry their fix after "How to fix:"; the common system
errors — tool missing, disk full, access denied, memory — are recognised);
``offset_not_measured`` explains why Step 3 could not measure the clock offset
from what happened to each synchronisation image. ``show_problem`` shows it
(and prints it in the console, so in the session log) with the buttons that
help: check the installation, open the images of the target, create a
diagnostic report of the mission.
"""
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

import IRD_Interactive_look as Look

CHECK = ("Click \"Check the installation\" (first page of the wizard, or below): it tries every tool on sample "
         "images and says how to fix what fails.")
REPORT = ("If it still fails, click \"Create a diagnostic report…\" below and send the zip to the IRDrone "
          "developers.")
TOOLS = {"RAWTHERAPEEPATH": "RawTherapee", "EXIFTOOLPATH": "ExifTool", "SJCONVERTERPATH": "the SJCam RAW converter"}


@dataclass
class Problem:
    title: str
    what: str
    fixes: List[str] = field(default_factory=list)
    details: str = ""

    def text(self) -> str:
        lines = [f"*** {self.title} ***", self.what, "How to fix:"]
        lines += [f"  {k}. {fix}" for k, fix in enumerate(self.fixes, 1)]
        if self.details:
            lines += ["Details:", self.details]
        return "\n".join(lines)


def from_error(message: str, stage: str = "") -> Problem:
    """A Problem from the message of an error raised during ``stage``."""
    message = str(message or "").strip()
    low = message.lower()
    title = f"{stage} failed" if stage else "The step failed"

    # Errors of IRDrone that carry their fix
    if "how to fix:" in low:
        index = low.index("how to fix:")
        what = message[:index].strip()
        fixes = [line.strip() for line in message[index + len("how to fix:"):].splitlines() if line.strip()]
        return Problem(title, what, fixes, details=message)

    # External tool missing (config.require_tool)
    for variable, name in TOOLS.items():
        if variable in message and "not found" in low:
            hint = re.search(r"Install it from (.+?), or set", message)
            return Problem(
                title, f"{name[0].upper() + name[1:]} is not installed, or not where IRDrone looks for it.",
                [f"Install {name}" + (f" from {hint.group(1)}" if hint else "") + ".",
                 f"If it is installed elsewhere, set the environment variable {variable} to the full path of the "
                 "program (Windows: System > Advanced system settings > Environment variables), then restart "
                 "the wizard.", CHECK], details=message)

    if "rawtherapee could not develop" in low:
        return Problem(
            title, "RawTherapee did not develop the images of the mission.",
            [CHECK, "If the installation check passes, the DNG images of the mission may be damaged: run Step 1 "
             "again (it copies the images from the SD cards).", REPORT], details=message)

    if "errno 28" in low or "no space left" in low or "diskfullerror" in low:
        return Problem(title, "The disk is full.",
                       ["Free some space on the disk of the working folder (or delete the working files of "
                        "finished missions: Step 7), then run the step again.",
                        "Or choose a working folder on another disk (⚙ options on the first page)."],
                       details=message)

    if "permission denied" in low or "errno 13" in low or "winerror 32" in low or "access is denied" in low:
        return Problem(title, "A file of the mission cannot be written: it is open in another program, or the "
                       "folder is read-only.",
                       ["Close the programs that may use the images (image viewer, Explorer preview, Excel, "
                        "an older IRDrone window), then run the step again.",
                        "If the mission is in a synchronised folder (OneDrive, Dropbox, Google Drive), pause the "
                        "synchronisation or move the working folder (⚙ options).",
                        "Check that the working folder is not read-only."], details=message)

    if "memoryerror" in low or "out of memory" in low or "unable to allocate" in low:
        return Problem(title, "The computer ran out of memory.",
                       ["Close the other programs, then run the step again.",
                        "IRDrone needs a 64 bits Python and 8 GB of memory or more: " + CHECK], details=message)

    if ".exif" in low and ("no such file" in low or "filenotfounderror" in low or "errno 2" in low):
        return Problem(title, "The metadata (EXIF) of some images of the mission are missing.",
                       ["Run Step 1 again for this mission (it reads the metadata of every image), then Steps 2 "
                        "and 3.", CHECK], details=message)

    if "at least two nir points" in low or "at least one vis point" in low:
        return Problem(title, "Too few images of the ArUco target were found to measure the clock offset.",
                       ["Open Step 2 and check that the synchronisation window is on the images where the "
                        "target is filmed turning (before take-off).", CHECK], details=message)

    if "no such file" in low or "errno 2" in low or "filenotfounderror" in low:
        return Problem(title, "A file of the mission is missing.",
                       ["Run the previous steps again (Step 1 copies the images, Step 2 chooses the windows).",
                        "Do not move or rename the files inside the mission folder.", REPORT], details=message)

    return Problem(title, f"Unexpected error{' during ' + stage.lower() if stage else ''}: {message}",
                   [CHECK, REPORT], details=message)


def offset_not_measured(stats: dict, found_vis: int, found_nir: int) -> Problem:
    """Step 3: too few images of the turning target to measure the offset.
    ``stats``: {band: ArucoWorker.stats}."""
    import IRD_Interactive_ArUco as Aru
    what = (f"The clock offset between the two cameras could not be measured: the rotating ArUco target was "
            f"found on {found_vis} visible and {found_nir} infrared images (at least 1 visible and 2 infrared "
            "images are needed).")
    fixes = []
    bands = [stats[b] for b in ("VIS", "NIR") if b in stats]
    if any(s["not_developed"] or s["missing"] for s in bands):
        fixes.append("Some images could not be developed or are missing (details below). " + CHECK)
    if any(s["no_time"] for s in bands):
        fixes.append("Some images are not in the time line of the mission: run Step 1 again, then Steps 2 and 3.")
    if any(s["no_marker"] for s in bands) or not fixes:
        fixes.append("Look at the developed images (\"Open the images of the target\" below, folders VIS and "
                     "NIR): if the target is not on them, or is blurred, the synchronisation window of Step 2 is "
                     "on the wrong images. Open Step 2, move the window onto the images where the target is "
                     "filmed turning (before take-off), then run Step 3 again.")
    fixes.append("If the target was not filmed during this flight, enter the clock offset by hand (button "
                 "below).")
    fixes.append(REPORT)
    details = "\n".join(Aru.sync_stats_text(s) for s in bands)
    return Problem("The clock offset could not be measured", what, fixes, details)


# ---------------------------------------------------------------------------
#  Window
# ---------------------------------------------------------------------------
def show_problem(parent, problem: Problem, mission=None, extra: Optional[str] = None) -> bool:
    """Show the problem (modal) and print it; True if ``extra`` was clicked."""
    print(problem.text(), flush=True)
    dialog = ProblemDialog(problem, mission, extra, parent)
    dialog.exec()
    return dialog.extra_clicked


class ProblemDialog(QDialog):
    def __init__(self, problem, mission=None, extra=None, parent=None):
        super().__init__(parent)
        self.problem, self.mission = problem, Path(mission) if mission else None
        self.extra_clicked = False
        self.setWindowTitle(problem.title)
        self.setStyleSheet(Look.DIALOG_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        title = QLabel(f"✗  {html.escape(problem.title)}")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #B03A2E;")
        lay.addWidget(title)
        what = QLabel(html.escape(problem.what).replace("\n", "<br>"))
        what.setTextFormat(Qt.TextFormat.RichText)
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        what.setStyleSheet("font-size: 11pt;")
        lay.addWidget(what)
        if problem.fixes:
            items = "".join(f"<li style='margin-bottom:4px'>{html.escape(f)}</li>" for f in problem.fixes)
            fixes = QLabel(f"<b style='color:#17365D'>How to fix</b><ol style='margin-left:-20px'>{items}</ol>")
            fixes.setTextFormat(Qt.TextFormat.RichText)
            fixes.setWordWrap(True)
            fixes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            fixes.setObjectName("fixes")
            fixes.setStyleSheet("#fixes { background: white; border: 1px solid #DDE3EA; border-radius: 6px;"
                                " padding: 8px 10px; }")
            lay.addWidget(fixes)
        self.details = QPlainTextEdit(problem.details)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.hide()
        helpers = QHBoxLayout()
        buttons = QHBoxLayout()
        self.btn_details = QPushButton("Details ▾")
        self.btn_details.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_details.setCheckable(True)
        self.btn_details.toggled.connect(self.details.setVisible)
        self.btn_details.setVisible(bool(problem.details))
        buttons.addWidget(self.btn_details)
        buttons.addStretch(1)
        self.btn_check = QPushButton("Check the installation")
        self.btn_check.setToolTip("Try every tool on sample images (about 20 s).")
        self.btn_check.clicked.connect(self._check)
        self.btn_images = QPushButton("Open the images of the target")
        self.btn_images.setToolTip("The synchronisation images as developed for the detection (Synchro/VIS, "
                                   "Synchro/NIR) and the detections drawn (Synchro/Check_ARUCO).")
        synchro = self.mission / "Synchro" if self.mission else None
        self.btn_images.setVisible(bool(synchro and synchro.is_dir()))
        self.btn_images.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(synchro))))
        self.btn_report = QPushButton("Create a diagnostic report…")
        self.btn_report.setToolTip("A zip describing the installation and this mission, to send to the IRDrone "
                                   "developers (the mission is not modified).")
        self.btn_report.clicked.connect(self._report)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setToolTip("Copy this message as text.")
        self.btn_copy.clicked.connect(self._copy)
        for button in (self.btn_check, self.btn_images, self.btn_report, self.btn_copy):
            button.setStyleSheet(Look.SECONDARY_STYLE)
            helpers.addWidget(button)
        helpers.addStretch(1)
        if extra:
            self.btn_extra = QPushButton(extra)
            self.btn_extra.setStyleSheet(Look.SECONDARY_STYLE.replace("color: #17365D;", "color: #17365D; "
                                                                      "font-weight: bold;", 1))
            self.btn_extra.clicked.connect(self._extra)
            buttons.addWidget(self.btn_extra)
        close = QPushButton("Close")
        close.setStyleSheet(Look.PRIMARY_STYLE)
        close.setDefault(True)
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        lay.addWidget(self.details)
        lay.addLayout(helpers)
        lay.addLayout(buttons)
        self.setMinimumWidth(min(900, max(640, self.sizeHint().width())))

    def _extra(self):
        self.extra_clicked = True
        self.accept()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.problem.text())
        self.btn_copy.setText("Copied ✓")

    def _check(self):
        import IRD_Interactive_diagnostic as Diagnostic
        self._check_dialog = Diagnostic.check_installation(self)

    def _report(self):
        import IRD_Interactive_diagnostic as Diagnostic
        self._report_thread = Diagnostic.create_diagnostic_report(self, mission=self.mission,
                                                                  ask=self.mission is None)
