# -*- coding: utf-8 -*-
"""
Details of a mission already created (Step 1 done): description, pilot,
cameras and filter, edited without going back to the SD cards. The folder,
the images, the date and the take-off position are kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

import IRD_Interactive_look as Look
import mission_setup as MS


class MissionDetailsDialog(QDialog):
    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.params = MS.read_mission_parameters(self.folder)
        self.changed = []
        self.setWindowTitle(f"Mission details – {self.folder.name}")
        self.setStyleSheet(Look.DIALOG_STYLE + " QLineEdit { padding: 4px; border: 1px solid #C5CFDA;"
                           " border-radius: 4px; background: white; }")
        self.setMinimumWidth(620)
        form = MS.details_form(self.params)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        title = QLabel(self.folder.name)
        title.setStyleSheet(Look.TITLE_STYLE)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(title)
        facts = []
        if self.params.get("Date"):
            y, m, d = (str(self.params["Date"]).replace("-", ":").split(":") + ["", "", ""])[:3]
            date = f"{d}/{m}/{y}" if d else str(self.params["Date"])
            facts.append(f"{date} {str(self.params.get('Time', ''))[:5]}".strip())
        if self.params.get("GPS lat") is not None and self.params.get("GPS lon") is not None:
            facts.append(f"{float(self.params['GPS lat']):.5f}, {float(self.params['GPS lon']):.5f}")
        if self.params.get("name image take-off"):
            facts.append(f"take-off {self.params['name image take-off']}")
        sub = QLabel(" · ".join(facts))
        sub.setStyleSheet(Look.SUBTITLE_STYLE)
        lay.addWidget(sub)
        note = QLabel("The images are already in the mission: only these details are changed. "
                      "The folder keeps its name.")
        note.setWordWrap(True)
        note.setStyleSheet(Look.MESSAGE_STYLE)
        lay.addWidget(note)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(Look.CARD_STYLE)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        fl = QFormLayout()
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        fl.setVerticalSpacing(8)
        self.f_location = QLineEdit(form["location"])
        self.f_description = QLineEdit(form["description"])
        self.f_description.setPlaceholderText("e.g. Vineyard survey, plot 12")
        self.f_pilot = QLineEdit(form["pilot"])
        self.f_pilot_id = QLineEdit(form["pilot_id"])
        for label, w in (("Location", self.f_location), ("Description", self.f_description),
                         ("Pilot", self.f_pilot), ("Pilot ID", self.f_pilot_id)):
            fl.addRow(label, w)
        cl.addLayout(fl)
        cams = QLabel("Cameras and filter")
        cams.setStyleSheet("font-weight: bold; color: #17365D; padding-top: 6px;")
        cl.addWidget(cams)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        vis = QLabel(f"{self.params.get('camera VIS maker', '')} {self.params.get('camera VIS ID', '')}".strip())
        self.f_vis_timelapse = _spin(form["vis_timelapse"], 1, 60, " s")
        self.f_vis_delta = _dspin(form["vis_deltatime"])
        self.f_nir_maker = QLineEdit(form["nir_maker"])
        self.f_nir_model = QLineEdit(form["nir_model"])
        self.f_nir_timelapse = _spin(form["nir_timelapse"], 1, 60, " s")
        self.f_nir_delta = _dspin(form["nir_deltatime"])
        self.f_filter_maker = QLineEdit(form["filter_maker"])
        self.f_filter_band = _spin(form["filter_band"], 300, 1200, " nm")
        rows = [("Visible camera", vis, None),
                ("Visible interval · clock delta", self.f_vis_timelapse, self.f_vis_delta),
                ("Infrared camera", self.f_nir_maker, self.f_nir_model),
                ("Infrared interval · clock delta", self.f_nir_timelapse, self.f_nir_delta),
                ("Filter maker · band", self.f_filter_maker, self.f_filter_band)]
        for r, (label, a, b) in enumerate(rows):
            lab = QLabel(label)
            lab.setStyleSheet("color: #6B7785;")
            grid.addWidget(lab, r, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(a, r, 1)
            if b is not None:
                grid.addWidget(b, r, 2)
        cl.addLayout(grid)
        lay.addWidget(card)

        buttons = QHBoxLayout()
        self.btn_help = QPushButton("?")
        self.btn_help.setStyleSheet(Look.SECONDARY_STYLE)
        self.btn_help.setFixedWidth(36)
        self.btn_help.clicked.connect(self._on_help)
        self.btn_reset = Look.reset_button("Put back the details as they were when the window opened.")
        self.btn_reset.clicked.connect(self.reset)
        buttons.addWidget(self.btn_help)
        buttons.addWidget(self.btn_reset)
        buttons.addStretch(1)
        self.btn_close = QPushButton(Look.close_text(False))
        self.btn_close.setStyleSheet(Look.PRIMARY_STYLE)
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.save)
        buttons.addWidget(self.btn_close)
        lay.addLayout(buttons)
        self._opened = self.form_values()      # what Reset puts back (as the widgets show it)
        for line in (self.f_location, self.f_description, self.f_pilot, self.f_pilot_id,
                     self.f_nir_maker, self.f_nir_model, self.f_filter_maker):
            line.textChanged.connect(self._update_close)
        for spin in (self.f_vis_timelapse, self.f_vis_delta, self.f_nir_timelapse, self.f_nir_delta,
                     self.f_filter_band):
            spin.valueChanged.connect(self._update_close)
        try:   # tool tips, F1: the manual
            import IRD_Interactive_help as Help
            for widget, tip in (
                (self.btn_help, "Open the manual at the mission details."),
                (self.btn_reset, self.btn_reset.toolTip()),
                (self.btn_close, "Close; once a detail is changed, save the details in mission_parameters.json "
                                 "(the previous file is kept as .bak). The mission folder keeps its name."),
            ):
                Help.attach_help(widget, "btn:step1_details", tip, parent=self)
        except Exception as e:  # the help is a convenience
            print(f"Help unavailable: {e}")

    def _on_help(self):
        try:
            import IRD_Interactive_help as Help
            Help.show_help("btn:step1_details", parent=self)
        except Exception as e:
            print(f"Help unavailable: {e}")

    def form_values(self) -> dict:
        return {
            "location": self.f_location.text(),
            "description": self.f_description.text(),
            "pilot": self.f_pilot.text(),
            "pilot_id": self.f_pilot_id.text(),
            "vis_timelapse": self.f_vis_timelapse.value(),
            "vis_deltatime": self.f_vis_delta.value(),
            "nir_maker": self.f_nir_maker.text(),
            "nir_model": self.f_nir_model.text(),
            "nir_timelapse": self.f_nir_timelapse.value(),
            "nir_deltatime": self.f_nir_delta.value(),
            "filter_maker": self.f_filter_maker.text(),
            "filter_band": self.f_filter_band.value(),
        }

    def edited(self) -> dict:
        """The fields changed since the window opened."""
        return {k: v for k, v in self.form_values().items() if v != self._opened.get(k)}

    def _update_close(self, *_):
        changed = bool(self.edited())
        self.btn_close.setText(Look.close_text(changed))
        self.btn_reset.setVisible(changed)

    def reset(self):
        """The details as they were when the window opened (nothing written)."""
        f = self._opened
        for widget, key in ((self.f_location, "location"), (self.f_description, "description"),
                            (self.f_pilot, "pilot"), (self.f_pilot_id, "pilot_id"),
                            (self.f_nir_maker, "nir_maker"), (self.f_nir_model, "nir_model"),
                            (self.f_filter_maker, "filter_maker")):
            widget.setText(f[key])
        for widget, key in ((self.f_vis_timelapse, "vis_timelapse"), (self.f_vis_delta, "vis_deltatime"),
                            (self.f_nir_timelapse, "nir_timelapse"), (self.f_nir_delta, "nir_deltatime"),
                            (self.f_filter_band, "filter_band")):
            widget.setValue(f[key])

    def reject(self):
        """Closing the window (title bar, Esc) saves, like Close."""
        self.save()

    def save(self):
        try:
            edited = self.edited()
            self.changed = MS.update_mission_details(self.folder, edited) if edited else []
        except (OSError, ValueError) as e:
            if QMessageBox.question(self, "Mission details", f"The details could not be saved:\n{e}\n\n"
                                    "Close without saving?") == QMessageBox.StandardButton.Yes:
                super().reject()
            return
        self.accept()


def _spin(value, lo, hi, suffix=""):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(int(value))
    s.setSuffix(suffix)
    return s


def _dspin(value):
    s = QDoubleSpinBox()
    s.setRange(-7200.0, 7200.0)
    s.setDecimals(2)
    s.setSuffix(" s")
    s.setValue(float(value))
    return s


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    d = MissionDetailsDialog(Path(sys.argv[1]))
    d.show()
    app.exec()


if __name__ == "__main__":
    main()
