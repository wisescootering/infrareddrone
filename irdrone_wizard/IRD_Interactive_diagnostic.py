# -*- coding: utf-8 -*-
"""Is something wrong with this installation? From the wizard.

* "Check the installation" (first page, and ⚙ options): selftests.py runs
  every link of the processing chain on the bundled samples, each one shown
  as it ends, with what is wrong and how to fix it (SelfTestDialog);
* "Create a diagnostic report…": the user chooses a mission (or the
  installation only); diagnostic.create_report runs in a thread behind a
  progress window, then the text of the report is shown (to read, copy or
  take a screenshot of) and printed in the console, and the zip is ready to be
  sent (ReportTextDialog).
"""
import html
from pathlib import Path

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                             QProgressBar, QProgressDialog, QPushButton, QScrollArea, QVBoxLayout, QWidget)

import config
import diagnostic
import IRD_Interactive_look as Look
import selftests

STATUS_COLORS = {selftests.OK: "#2E7D32", selftests.WARNING: "#C26A00", selftests.FAILED: "#B03A2E",
                 selftests.SKIPPED: "#8A96A3", "pending": "#B8C2CC", "running": "#17365D"}
# Plain glyphs: the emoji font of ✔ / ✖ ignores the colour
GLYPHS = {selftests.OK: "✓", selftests.WARNING: "!", selftests.FAILED: "✗", selftests.SKIPPED: "–",
          "pending": "○", "running": "…"}
VERDICT_STYLES = {selftests.OK: "background: #E8F5E9; color: #1B5E20;",
                  selftests.WARNING: "background: #FFF4E0; color: #7A4B00;",
                  selftests.FAILED: "background: #FBEDEB; color: #8E2A20;"}


def _monospace():
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


# ---------------------------------------------------------------------------
#  Check the installation
# ---------------------------------------------------------------------------
class SelfTestThread(QThread):
    log = pyqtSignal(str)
    started_check = pyqtSignal(str)
    result = pyqtSignal(object)        # one result dict, as each check ends
    done = pyqtSignal(object)          # {name: result}

    def __init__(self, names=None, parent=None):
        super().__init__(parent)
        self.names = names
        self.stop = False

    def run(self):
        def log(text):
            self.log.emit(text)
            if text.startswith("[") and text.endswith("]"):
                self.started_check.emit(text[1:-1])
        results = selftests.run_checks(self.names, log=log, on_result=self.result.emit,
                                       should_stop=lambda: self.stop)
        self.done.emit(results)


class CheckRow(QFrame):
    """One check: status icon, title, detail and, when it is not ok, how to fix it."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedWidth(22)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.text, 1)
        self.title = title
        self.set_state("pending")

    def set_state(self, state, detail="", fix="", seconds=None):
        color = STATUS_COLORS[state]
        stripe = color if state in (selftests.FAILED, selftests.WARNING, "running") else "#E4E8EE"
        self.setStyleSheet(f"#row {{ background: white; border: 1px solid #E4E8EE; border-left: 4px solid {stripe};"
                           " border-radius: 6px; }")
        self.icon.setText(f"<span style='color:{color}; font-size:14pt; font-weight:bold'>{GLYPHS[state]}</span>")
        title = html.escape(self.title)
        time = f" <span style='color:#8A96A3'>({seconds:.1f} s)</span>" if seconds is not None else ""
        body = f"<b style='color:#17365D'>{title}</b>{time}"
        if state == "running":
            body += "<br><span style='color:#6B7785'>running…</span>"
        if detail:
            body += f"<br><span style='color:{'#1F2933' if state != selftests.SKIPPED else '#8A96A3'}'>" \
                    f"{html.escape(detail).replace(chr(10), '<br>')}</span>"
        if fix:
            body += f"<br><b style='color:{color}'>How to fix:</b> {html.escape(fix)}"
        self.text.setText(body)


class SelfTestDialog(QDialog):
    """Runs the self-tests as soon as it opens; one row per check."""

    def __init__(self, parent=None, names=None):
        super().__init__(parent)
        self.setWindowTitle("Check the installation")
        self.setStyleSheet(Look.DIALOG_STYLE)
        self.names = names
        self.results = {}
        self.thread = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        title = QLabel("Check the installation")
        title.setStyleSheet(Look.TITLE_STYLE)
        lay.addWidget(title)
        sub = QLabel("Each link of the processing chain is tried on sample images shipped with IRDrone "
                     "(DJI DNG, SJCam RAW, ArUco target, visible / infrared pair), the way the steps do it. "
                     "About 20 seconds; your missions are not touched.")
        sub.setWordWrap(True)
        sub.setStyleSheet(Look.SUBTITLE_STYLE)
        lay.addWidget(sub)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.hide()
        lay.addWidget(self.verdict)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(Look.PROGRESS_STYLE)
        lay.addWidget(self.progress)

        rows = QWidget()
        rows_lay = QVBoxLayout(rows)
        rows_lay.setContentsMargins(0, 0, 4, 0)
        rows_lay.setSpacing(5)
        self.rows = {}
        self.order = [(name, t) for name, t, _ in selftests.CHECKS if names is None or name in names]
        for name, check_title in self.order:
            self.rows[name] = CheckRow(check_title)
            rows_lay.addWidget(self.rows[name])
        rows_lay.addStretch(1)
        self.scroll = scroll = QScrollArea()
        scroll.setWidget(rows)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(scroll, 3)

        self.btn_log = QPushButton("Show the details ▾")
        self.btn_log.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_log.setCheckable(True)
        self.btn_log.setToolTip("Everything the checks print (commands, outputs, errors).")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(_monospace())
        self.log_view.hide()
        self.btn_log.toggled.connect(self._toggle_log)
        lay.addWidget(self.log_view, 2)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_log)
        buttons.addStretch(1)
        self.btn_again = QPushButton("Run again")
        self.btn_again.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_again.clicked.connect(self.start)
        self.btn_copy = QPushButton("Copy the results")
        self.btn_copy.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_copy.setToolTip("Copy the results as text, to paste in an e-mail.")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_report = QPushButton("Create a diagnostic report…")
        self.btn_report.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_report.setToolTip("A zip with these results, the installation, the logs and, for a mission, "
                                   "its synchronisation images checked: to send to the IRDrone developers.")
        self.btn_report.clicked.connect(self._report)
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(Look.PRIMARY_STYLE)
        self.btn_close.clicked.connect(self.close)
        for button in (self.btn_again, self.btn_copy, self.btn_report, self.btn_close):
            buttons.addWidget(button)
        lay.addLayout(buttons)
        Look.fit_to_screen(self, parent, max_w=900, max_h=860, ratio=0.85)

    # ---- run
    def start(self):
        if self.thread is not None and self.thread.isRunning():
            return
        self.results = {}
        for name, row in self.rows.items():
            row.set_state("pending")
        self.verdict.hide()
        self.log_view.clear()
        self.progress.setRange(0, len(self.order))
        self.progress.setValue(0)
        for button in (self.btn_again, self.btn_copy):
            button.setEnabled(False)
        print("Check the installation: running the self-tests…")
        self.thread = SelfTestThread(self.names, self)
        self.thread.log.connect(self.log_view.appendPlainText)
        self.thread.started_check.connect(self._running)
        self.thread.result.connect(self._result)
        self.thread.done.connect(self._done)
        self.thread.start()

    def _running(self, check_title):
        for name, title in self.order:
            if title == check_title:
                self.rows[name].set_state("running")

    def _result(self, result):
        self.results[result["name"]] = result
        self.rows[result["name"]].set_state(result["status"], result["detail"], result["fix"], result["seconds"])
        self.progress.setValue(len(self.results))

    def _done(self, results):
        self.results = results
        verdict, counts = selftests.summary(results)
        state = selftests.FAILED if counts[selftests.FAILED] else (
            selftests.WARNING if counts[selftests.WARNING] else selftests.OK)
        self.verdict.setText(f"{GLYPHS[state]}  {verdict}")
        self.verdict.setStyleSheet(VERDICT_STYLES[state] + " border-radius: 6px; padding: 8px 12px; "
                                                            "font-weight: bold; font-size: 11pt;")
        self.verdict.show()
        for button in (self.btn_again, self.btn_copy):
            button.setEnabled(True)
        # In the console too (and so in the session log)
        print(selftests.text(results), flush=True)
        problems = [name for name, r in results.items() if r["status"] in (selftests.FAILED, selftests.WARNING)]
        problems.sort(key=lambda name: results[name]["status"] != selftests.FAILED)
        if problems:        # the first thing to fix in view
            self.scroll.ensureWidgetVisible(self.rows[problems[0]], 0, 40)

    def _toggle_log(self, shown):
        self.log_view.setVisible(shown)
        self.btn_log.setText("Hide the details ▴" if shown else "Show the details ▾")

    def text(self):
        return selftests.text(self.results)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.text())
        self.btn_copy.setText("Copied ✔")

    def _report(self):
        done = self.thread is None or not self.thread.isRunning()
        checks = self.results if done and self.results else None
        self._report_thread = create_diagnostic_report(self, checks=checks)

    def showEvent(self, event):
        super().showEvent(event)
        if self.thread is None:
            self.start()

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop = True        # after the running check
            self.thread.wait(120000)
        super().closeEvent(event)


def check_installation(parent=None, names=None):
    """Open "Check the installation" (modeless): the checks start at once."""
    dialog = SelfTestDialog(parent, names)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog


# ---------------------------------------------------------------------------
#  Diagnostic report
# ---------------------------------------------------------------------------
class DiagnosticThread(QThread):
    step = pyqtSignal(str)
    done = pyqtSignal(object)      # Path of the zip
    failed = pyqtSignal(str)

    def __init__(self, mission, output, parent=None, checks=None):
        super().__init__(parent)
        self.mission, self.output, self.checks = mission, output, checks

    def run(self):
        try:
            self.done.emit(diagnostic.create_report(self.mission, self.output, progress=self.step.emit,
                                                    checks=self.checks))
        except Exception as error:      # reported to the user, never a crash
            self.failed.emit(f"{type(error).__name__}: {error}")


class ReportTextDialog(QDialog):
    """The text of the report (report.txt), to read, copy or screenshot."""

    def __init__(self, zip_path, text, parent=None):
        super().__init__(parent)
        self.zip_path = Path(zip_path)
        self.setWindowTitle("Diagnostic report")
        self.setStyleSheet(Look.DIALOG_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        head = QLabel(f"<b>Report written:</b> {html.escape(str(self.zip_path))}<br>"
                      "Send this zip file to the IRDrone developers. Its text is below "
                      "(also printed in the console).")
        head.setWordWrap(True)
        head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(head)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setFont(_monospace())
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_copy = QPushButton("Copy the text")
        self.btn_copy.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_folder = QPushButton("Open the folder of the zip")
        self.btn_folder.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.zip_path.parent))))
        close = QPushButton("Close")
        close.setStyleSheet(Look.PRIMARY_STYLE)
        close.clicked.connect(self.accept)
        for button in (self.btn_copy, self.btn_folder, close):
            buttons.addWidget(button)
        lay.addLayout(buttons)
        Look.fit_to_screen(self, parent, max_w=1100, max_h=900, ratio=0.85)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.view.toPlainText())
        self.btn_copy.setText("Copied ✔")


def report_text(zip_path) -> str:
    import zipfile
    with zipfile.ZipFile(zip_path) as archive:
        return archive.read("report.txt").decode("utf-8")


def choose_mission(parent=None):
    """(go, mission folder or None)."""
    box = QMessageBox(parent)
    box.setWindowTitle("Diagnostic report")
    box.setText("The report describes the installation (Python, packages, external tools) and runs the "
                "installation self-tests.\n\nWith a mission, the synchronisation images are also developed again "
                "and checked (about a minute; the mission is not modified).")
    mission_button = box.addButton("Choose a mission…", QMessageBox.ButtonRole.AcceptRole)
    install_button = box.addButton("Installation only", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is install_button:
        return True, None
    if clicked is not mission_button:
        return False, None
    folder = QFileDialog.getExistingDirectory(parent, "Mission folder (FLY-...)", str(config.OUTPUT_FOLDER_NAME))
    return (True, Path(folder)) if folder else (False, None)


def create_diagnostic_report(parent=None, mission=None, ask=True, checks=None):
    """Ask for the mission, run the report, show its text. Returns the
    thread (kept alive by its parent). ``checks``: self-tests already run."""
    if ask:
        go, mission = choose_mission(parent)
        if not go:
            return None
    output = Path(config.OUTPUT_FOLDER_NAME)
    progress = QProgressDialog("Diagnostic report…", None, 0, 0, parent)
    progress.setWindowTitle("Diagnostic report")
    progress.setMinimumWidth(460)
    progress.setMinimumDuration(0)
    thread = DiagnosticThread(mission, output, parent, checks=checks)

    def step(text):
        progress.setLabelText(f"Diagnostic report…\n{text}")
        print(f"  {text}", flush=True)

    def finished(zip_path):
        progress.close()
        try:
            text = report_text(zip_path)
        except Exception as error:
            text = f"(report.txt could not be read: {error})"
        print(text, flush=True)
        print(f"Diagnostic report written: {zip_path}\nSend this zip file to the IRDrone developers.", flush=True)
        dialog = ReportTextDialog(zip_path, text, parent)
        dialog.exec()

    def failed(message):
        progress.close()
        print(f"The diagnostic report could not be written: {message}", flush=True)
        QMessageBox.warning(parent, "Diagnostic report", f"The report could not be written:\n{message}")

    thread.step.connect(step)
    thread.done.connect(finished)
    thread.failed.connect(failed)
    print("Diagnostic report…", flush=True)
    progress.show()
    thread.start()
    return thread
