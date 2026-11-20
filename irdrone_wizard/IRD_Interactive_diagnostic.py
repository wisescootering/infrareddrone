# -*- coding: utf-8 -*-
"""Diagnostic report from the wizard (⚙ options, "Create a diagnostic report…").

The user chooses a mission (or the installation only); diagnostic.create_report
runs in a thread behind a progress window, then the zip is shown in the file
explorer, ready to be sent.
"""
from pathlib import Path

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

import config
import diagnostic


class DiagnosticThread(QThread):
    step = pyqtSignal(str)
    done = pyqtSignal(object)      # Path of the zip
    failed = pyqtSignal(str)

    def __init__(self, mission, output, parent=None):
        super().__init__(parent)
        self.mission, self.output = mission, output

    def run(self):
        try:
            self.done.emit(diagnostic.create_report(self.mission, self.output, progress=self.step.emit))
        except Exception as error:      # reported to the user, never a crash
            self.failed.emit(f"{type(error).__name__}: {error}")


def choose_mission(parent=None):
    """(go, mission folder or None)."""
    box = QMessageBox(parent)
    box.setWindowTitle("Diagnostic report")
    box.setText("The report describes the installation (Python, packages, external tools) and runs a few "
                "self-tests.\n\nWith a mission, the synchronisation images are also developed again and "
                "checked (about a minute; the mission is not modified).")
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


def create_diagnostic_report(parent=None, mission=None, ask=True):
    """Ask for the mission, run the report, show where the zip is. Returns the
    thread (kept alive by its parent)."""
    if ask:
        go, mission = choose_mission(parent)
        if not go:
            return None
    output = Path(config.OUTPUT_FOLDER_NAME)
    progress = QProgressDialog("Diagnostic report…", None, 0, 0, parent)
    progress.setWindowTitle("Diagnostic report")
    progress.setMinimumWidth(420)
    progress.setMinimumDuration(0)
    thread = DiagnosticThread(mission, output, parent)
    thread.step.connect(lambda text: progress.setLabelText(f"Diagnostic report…\n{text}"))

    def finished(zip_path):
        progress.close()
        answer = QMessageBox.information(
            parent, "Diagnostic report",
            f"Report written:\n{zip_path}\n\nSend this zip file to the IRDrone developers.",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close)
        if answer == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(zip_path).parent)))

    def failed(message):
        progress.close()
        QMessageBox.warning(parent, "Diagnostic report", f"The report could not be written:\n{message}")

    thread.done.connect(finished)
    thread.failed.connect(failed)
    progress.show()
    thread.start()
    return thread
