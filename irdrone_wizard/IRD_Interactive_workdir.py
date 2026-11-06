# -*- coding: utf-8 -*-
"""
Working folder of the wizard: the folder where the missions are stored.

* WorkingDirDialog: choose the folder. Shown at the first launch (nothing saved
  yet) and from the gear button at the bottom of the main window.
* WorkingDirBar: bottom bar of the main window, shows the folder + gear button.

The choice is saved in the user settings file (config.SETTINGS_FILE). The
environment variable IRDRONE_WORKING_DIR, when set, still wins at each launch.
"""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import config
from IRD_Interactive_styles import BUTTON_STYLE

GEAR_STYLE = BUTTON_STYLE + "QPushButton { font-size: 16px; padding: 2px; }"


class WorkingDirDialog(QDialog):
    """Choose the working folder. accepted -> config.set_working_dir() was applied."""

    def __init__(self, parent=None, first_run=False, problem=""):
        super().__init__(parent)
        self.first_run = first_run
        self.setWindowTitle("IRDrone – working folder")
        layout = QVBoxLayout(self)

        if first_run:
            text = ("<b>Welcome to IRDrone.</b><br>Choose the working folder where your "
                    "missions will be stored.<br>You can change it later with the ⚙ "
                    "button at the bottom of the main window.")
        else:
            text = "Folder where the missions are stored."
        intro = QLabel(text)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if problem:
            warning = QLabel(problem)
            warning.setWordWrap(True)
            warning.setStyleSheet("color: darkred;")
            layout.addWidget(warning)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(config.OUTPUT_FOLDER_NAME))
        self.path_edit.setMinimumWidth(440)  # sets the dialog width, labels wrap to it
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse...")
        browse.setStyleSheet(BUTTON_STYLE)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        if config.WORKING_DIR_SOURCE == "environment":
            note = QLabel(
                "The environment variable IRDRONE_WORKING_DIR is set: it takes priority at "
                "each launch. A folder chosen here is used for this session and saved for "
                "when the variable is not set.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8a5a00;")
            layout.addWidget(note)

        settings_note = QLabel(f"Saved in {config.SETTINGS_FILE}")
        settings_note.setWordWrap(True)
        settings_note.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(settings_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        if first_run:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Later")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Word-wrapped labels get a wrong height otherwise (text cut at the bottom).
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

    def _browse(self):
        start = Path(self.path_edit.text()).expanduser()
        while not start.exists() and start != start.parent:
            start = start.parent
        folder = QFileDialog.getExistingDirectory(self, "Working folder", str(start))
        if folder:
            self.path_edit.setText(folder)

    def _apply(self):
        text = self.path_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "IRDrone", "Choose a folder.")
            return
        try:
            config.set_working_dir(text)
        except OSError as error:
            QMessageBox.warning(self, "IRDrone", f"Cannot use this folder:\n{text}\n\n{error}")
            return
        self.accept()


def ensure_working_dir_at_startup(parent=None):
    """First launch: ask for the working folder. Later launches: check it is
    usable (e.g. an unplugged USB drive) and ask again if not.
    Returns the folder in use."""
    if config.WORKING_DIR_SOURCE == "default":
        dialog = WorkingDirDialog(parent, first_run=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            # "Later": default folder for this session, asked again next time.
            config.ensure_working_dir()
    elif not config.ensure_working_dir():
        dialog = WorkingDirDialog(
            parent, problem=f"The working folder {config.OUTPUT_FOLDER_NAME} is not reachable "
                            "(removed or unplugged drive?). Choose another one.")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            config.set_working_dir(config.DEFAULT_WORKING_DIR, remember=False)
    return config.OUTPUT_FOLDER_NAME


class WorkingDirBar(QWidget):
    """'Working folder: <path>' + gear button; emits changed(Path)."""

    changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setOpenExternalLinks(False)
        self.label.linkActivated.connect(self._open_folder)
        layout.addWidget(self.label)
        self.gear = QPushButton("⚙")
        self.gear.setFixedWidth(30)
        self.gear.setStyleSheet(GEAR_STYLE)
        self.gear.setToolTip("Options: change the working folder")
        self.gear.clicked.connect(self.open_options)
        layout.addWidget(self.gear)
        self.refresh()

    def refresh(self):
        folder = config.OUTPUT_FOLDER_NAME
        source = " (from IRDRONE_WORKING_DIR)" if config.WORKING_DIR_SOURCE == "environment" else ""
        self.label.setText(f'Working folder: <a href="open">{folder}</a>{source}')
        self.label.setToolTip("Click to open the folder")

    def _open_folder(self, _link=None):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.OUTPUT_FOLDER_NAME)))

    def open_options(self):
        before = config.OUTPUT_FOLDER_NAME
        if WorkingDirDialog(self.window()).exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            if config.OUTPUT_FOLDER_NAME != before:
                self.changed.emit(config.OUTPUT_FOLDER_NAME)
