# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 6
#   Mission archiving.  User interface
# ---------------------------------------------------------------------------------
"""Step 6 dialog: archiving (cleaning) of the mission folder.

``DialogArchive`` offers two commands:

* **Simulate**: analyses the mission folder and lists what would be deleted,
  without touching the disk;
* **Archive and clean**: same analysis, then a strong confirmation (the user
  types the name of the mission folder) and the irreversible deletion.

The rules of what is kept or deleted, the consistency checks and the deletion
itself are in ``IRD_Interactive_archive`` (no Qt). The analysis and the deletion
run in a ``QRunnable`` worker that reports to the dialog through Qt signals.
The window cannot be closed while a worker runs.
"""

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

import IRD_Interactive_help as Help
import IRD_Interactive_archive as Archive
from IRD_Interactive_styles import BUTTON_STYLE


class _WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(object, object)  # byte counts can exceed the 32-bit range of int
    done = pyqtSignal(object)
    error = pyqtSignal(str)


class _Worker(QRunnable):
    """Run ``fn(signals)`` outside the GUI thread."""

    def __init__(self, fn: Callable[[_WorkerSignals], object]):
        super().__init__()
        self.fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals)
        except Exception as exc:  # reported to the user, never silent
            self.signals.error.emit(str(exc))
            return
        self.signals.done.emit(result)


class DialogArchive(QDialog):
    """Dialog of step 6: archiving of the mission."""

    data_signal_to_main = pyqtSignal(bool)

    def __init__(self, mission_parameters: dict, parent=None):
        super().__init__(parent)
        self.mission_parameters = mission_parameters
        folder = (mission_parameters.get("folderMissionPath")
                  or mission_parameters.get("File path mission"))
        if folder is None:
            raise ValueError("The mission folder is not defined.")
        self.folderMissionPath = Path(folder)
        self._busy = False
        self._worker = None

        self.setWindowTitle("Step 6 – Archive the mission")
        self.setMinimumSize(700, 400)
        self.resize(900, 600)
        self._init_gui()
        self._log(f"Mission folder: {self.folderMissionPath}")
        self._log("Use <b>Simulate</b> to list what would be deleted, without changing anything.")

    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel("<b>Mission archiving</b>"))
        warning = QLabel(
            "Archiving deletes the technical files of the mission folder. "
            "<b>This operation is irreversible.</b> Copy anything you want to keep elsewhere first."
        )
        warning.setWordWrap(True)
        main_layout.addWidget(warning)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, stretch=1)

        btn_layout = QHBoxLayout()
        self.btn_simulate = QPushButton("Simulate (dry run)")
        self.btn_simulate.setFixedWidth(200)
        self.btn_simulate.setStyleSheet(BUTTON_STYLE)
        self.btn_simulate.clicked.connect(self.on_simulate)
        btn_layout.addWidget(self.btn_simulate)
        self.btn_archive = QPushButton("Archive and clean…")
        self.btn_archive.setFixedWidth(200)
        self.btn_archive.setStyleSheet(BUTTON_STYLE)
        self.btn_archive.clicked.connect(self.on_archive)
        btn_layout.addWidget(self.btn_archive)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(BUTTON_STYLE)
        self.btn_close.clicked.connect(self.on_close)
        bottom_layout.addWidget(self.btn_close)
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(30)
        self.btn_help.setStyleSheet(BUTTON_STYLE)
        self.btn_help.clicked.connect(lambda: Help.show_help("ch:step6", parent=self))
        bottom_layout.addWidget(self.btn_help)
        main_layout.addLayout(bottom_layout)

        for widget, label, tip in (
            (self.btn_simulate, "btn:step6_simulate", "List what would be deleted, without changing anything."),
            (self.btn_archive, "btn:step6_archive", "Delete the technical files of the mission (irreversible)."),
            (self.btn_close, "btn:step6_close", "Close this window."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(self, message: str) -> None:
        self.log_text.append(message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (self.btn_simulate, self.btn_archive, self.btn_close):
            button.setEnabled(not busy)

    def _start(self, fn, on_done) -> None:
        self._set_busy(True)
        self.progress_bar.setRange(0, 0)  # indeterminate until the first progress report
        worker = _Worker(fn)
        worker.signals.log.connect(self._log)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.done.connect(on_done)
        worker.signals.error.connect(self._on_error)
        self._worker = worker  # keeps the signals alive
        QThreadPool.globalInstance().start(worker)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(100 * done / max(total, 1)))

    def _on_error(self, message: str) -> None:
        self._end()
        self.progress_bar.setValue(0)
        self._log(f"<span style='color:red'>ERROR: {message}</span>")
        QMessageBox.critical(self, "Archiving error", message)

    def _end(self) -> None:
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)

    def _show_plan(self, plan: Archive.ArchivePlan) -> bool:
        """Display the analysis; return False if the archiving is not possible."""
        if not plan.blockers:
            for line in plan.summary_lines():
                self._log(line)
        for warning in plan.warnings:
            self._log(f"<span style='color:#C87800'>Warning: {warning}</span>")
        for blocker in plan.blockers:
            self._log(f"<span style='color:red'>{blocker}</span>")
        return not plan.blockers

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def on_simulate(self) -> None:
        self._log("<b>--- Simulation ---</b>")
        self._start(lambda sig: Archive.build_plan(self.folderMissionPath), self._simulation_done)

    def _simulation_done(self, plan: Archive.ArchivePlan) -> None:
        self._end()
        if self._show_plan(plan):
            self._log("Simulation only: nothing was deleted.")

    def on_archive(self) -> None:
        self._log("<b>--- Archiving ---</b>")
        self._start(lambda sig: Archive.build_plan(self.folderMissionPath), self._archive_plan_ready)

    def _archive_plan_ready(self, plan: Archive.ArchivePlan) -> None:
        self._end()
        if not self._show_plan(plan):
            QMessageBox.warning(self, "Archiving impossible", "\n".join(plan.blockers))
            return
        if not plan.delete_items:
            self._log("Nothing to delete.")
            return
        expected = self.folderMissionPath.name
        text, ok = QInputDialog.getText(
            self,
            "Confirm archiving",
            f"{plan.total_files} file(s) ({Archive.format_size(plan.total_bytes)}) will be "
            f"permanently deleted.\nThis cannot be undone.\n\n"
            f"Type the name of the mission folder to confirm:\n{expected}",
        )
        if not ok or text.strip() != expected:
            self._log("Archiving cancelled." if not ok else "Archiving cancelled: the name does not match.")
            return
        self._start(
            lambda sig: Archive.execute_archive(plan, log=sig.log.emit, progress=sig.progress.emit),
            self._archive_done,
        )

    def _archive_done(self, manifest: dict) -> None:
        self._end()
        self.progress_bar.setValue(100)
        n_errors = len(manifest["errors"])
        if n_errors:
            self._log(f"<span style='color:red'>{n_errors} item(s) could not be deleted "
                      f"(file in use?). Close the programs using them and run the archiving again.</span>")
            QMessageBox.warning(self, "Archiving finished with errors",
                                f"{n_errors} item(s) could not be deleted. See the log.")
        else:
            self._log("<span style='color:green'>Archiving completed.</span>")
            QMessageBox.information(self, "Archiving completed",
                                    f"{Archive.format_size(manifest['deleted_bytes'])} freed.")

    def on_close(self) -> None:
        """Close the dialog (refused while an operation runs)."""
        if self._busy:
            return
        self.data_signal_to_main.emit(True)
        self.close()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self) -> None:
        if not self._busy:
            super().reject()
