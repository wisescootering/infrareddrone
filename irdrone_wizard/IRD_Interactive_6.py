# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 6
#   Mission archiving.  User interface
# ---------------------------------------------------------------------------------
"""Step 6 dialog: archiving (cleaning) of the mission folder.

When the window opens, the mission folder is analysed (nothing is changed)
and the window shows what archiving would free: the dry run is implicit.
**Archive and free …** analyses again, then asks for a strong confirmation
(the user types the name of the mission folder) before the irreversible deletion.

The rules of what is kept or deleted, the consistency checks and the deletion
itself are in ``IRD_Interactive_archive`` (no Qt). The analysis and the deletion
run in a ``QRunnable`` worker that reports to the dialog through Qt signals.
The window cannot be closed while a worker runs.
"""

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
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
from IRD_Interactive_progress import mark_step_done
import IRD_Interactive_archive as Archive
import IRD_Interactive_look as Look
from IRD_Interactive_look import DANGER_STYLE, DIALOG_STYLE, MESSAGE_STYLE, SECONDARY_STYLE

STEP_NAME = "Mission archiving"


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
        self.plan = None          # the last analysis (None while it runs)

        self.setWindowTitle(Look.step_window_title(6, STEP_NAME, self.folderMissionPath))
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumSize(600, 420)
        self.resize(820, 600)
        self._init_gui()
        self._log(f"Mission folder: {self.folderMissionPath}")
        QTimer.singleShot(0, self.analyse)       # the dry run: what archiving would free

    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(Look.step_header(6, STEP_NAME, self.folderMissionPath))
        warning = QLabel(
            "Archiving deletes the technical files of the mission folder. "
            "<b>This operation is irreversible.</b> Copy anything you want to keep elsewhere first."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(MESSAGE_STYLE)
        main_layout.addWidget(warning)

        # What archiving would free, computed when the window opens (nothing is changed)
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(Look.CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        self.summary_title = QLabel("Analysing the mission folder…")
        self.summary_title.setStyleSheet(Look.TITLE_STYLE)
        self.summary_detail = QLabel("Nothing is changed while the folder is analysed.")
        self.summary_detail.setWordWrap(True)
        self.summary_detail.setStyleSheet(Look.SUBTITLE_STYLE)
        card_layout.addWidget(self.summary_title)
        card_layout.addWidget(self.summary_detail)
        main_layout.addWidget(card)

        btn_layout = QHBoxLayout()
        self.btn_archive = QPushButton("Archive and free…")
        self.btn_archive.setStyleSheet(DANGER_STYLE)     # irreversible
        self.btn_archive.setEnabled(False)               # until the analysis says what it frees
        self.btn_archive.clicked.connect(self.on_archive)
        btn_layout.addWidget(self.btn_archive)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Details, folder by folder
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, stretch=1)

        # Footer: the manual (?) on the left, Close always at the bottom right
        bottom_layout = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(36)
        self.btn_help.setStyleSheet(SECONDARY_STYLE)
        self.btn_help.clicked.connect(lambda: Help.show_help("ch:step6", parent=self))
        bottom_layout.addWidget(self.btn_help)
        bottom_layout.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(120)
        self.btn_close.setStyleSheet(SECONDARY_STYLE)
        self.btn_close.clicked.connect(self.on_close)
        bottom_layout.addWidget(self.btn_close)
        main_layout.addLayout(bottom_layout)

        for widget, label, tip in (
            (self.btn_archive, "btn:step6_archive",
             "Delete the files listed below (irreversible): the folder is analysed again, then you "
             "confirm by typing the name of the mission folder."),
            (self.btn_close, "btn:step6_close", "Close this window."),
            (self.btn_help, "ch:step6", "Open the manual at Step 6."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(self, message: str) -> None:
        self.log_text.append(message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_close.setEnabled(not busy)
        self.btn_archive.setEnabled(not busy and self._can_archive())

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
        if self.plan is None:
            self.summary_title.setText("Analysis failed")
            self.summary_detail.setText(message)
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
    def _can_archive(self) -> bool:
        return self.plan is not None and not self.plan.blockers and bool(self.plan.delete_items)

    def analyse(self) -> None:
        """The dry run: what archiving would delete and free, without changing anything."""
        if self._busy:
            return
        self.plan = None
        self.summary_title.setText("Analysing the mission folder…")
        self._start(lambda sig: Archive.build_plan(self.folderMissionPath), self._analysis_done)

    def _analysis_done(self, plan: Archive.ArchivePlan) -> None:
        self.plan = plan
        self._log("<b>--- What archiving would delete (nothing is deleted yet) ---</b>")
        self._show_plan(plan)
        self._show_summary(plan)
        self._end()

    def _show_summary(self, plan: Archive.ArchivePlan) -> None:
        """The answer of the dry run, in the card: how much is freed, or why not."""
        title_style = Look.TITLE_STYLE
        if plan.already_archived:
            title, detail = "✓ Mission already archived", plan.blockers[0]
            title_style += " color: #2E7D32;"
        elif plan.blockers:
            title, detail = "Archiving impossible", " ".join(plan.blockers)
            title_style += " color: #B03A2E;"
        elif not plan.delete_items:
            title, detail = "Nothing to delete", "The mission folder holds only what archiving keeps."
        else:
            size = Archive.format_size(plan.total_bytes)
            title = f"{size} can be freed"
            detail = (f"{plan.total_files} file(s) will be deleted. The original images, the aligned "
                      f"images, the synchronisation result and the map are kept (details below).")
        self.summary_title.setText(title)
        self.summary_title.setStyleSheet(title_style)
        self.summary_detail.setText(detail)
        self.btn_archive.setText(f"Archive and free {Archive.format_size(plan.total_bytes)}…"
                                 if self._can_archive() else "Archive and free…")

    def on_archive(self) -> None:
        self._log("<b>--- Archiving ---</b>")
        self._start(lambda sig: Archive.build_plan(self.folderMissionPath), self._archive_plan_ready)

    def _archive_plan_ready(self, plan: Archive.ArchivePlan) -> None:
        self.plan = plan
        self._show_summary(plan)
        self._end()
        if plan.blockers:                      # listed in the card
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
        QTimer.singleShot(0, self.analyse)     # the card then says what is left (or archived)
        self.progress_bar.setValue(100)
        n_errors = len(manifest["errors"])
        if n_errors:
            self._log(f"<span style='color:red'>{n_errors} item(s) could not be deleted "
                      f"(file in use?). Close the programs using them and run the archiving again.</span>")
            QMessageBox.warning(self, "Archiving finished with errors",
                                f"{n_errors} item(s) could not be deleted. See the log.")
        else:
            self._log("<span style='color:green'>Archiving completed.</span>")
            mark_step_done(self.folderMissionPath, 6)
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
