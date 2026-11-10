"""Contextual help: every button of the windows has a tool tip, and every
manual label used by the code (F1 on a button, "?" buttons)
exists in help/irdrone_help.tex."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IRDRONE_CACHE", tempfile.mkdtemp())

from PyQt6.QtWidgets import QAbstractButton, QApplication, QDialogButtonBox  # noqa: E402

APP = QApplication.instance() or QApplication([])
TEX = ROOT / "help" / "irdrone_help.tex"


def manual_labels():
    text = TEX.read_text(encoding="utf-8")
    return set(re.findall(r"\\label\{([^}#]+)\}", text))


def labels_used_by_the_code():
    used = {}
    for path in (ROOT / "irdrone_wizard").glob("*.py"):
        for label in re.findall(r"[\"']((?:btn|ch|sec):[A-Za-z0-9_]+)[\"']", path.read_text(encoding="utf-8")):
            used.setdefault(label, path.name)
    return used


def buttons_without_tool_tip(widget):
    """Buttons of `widget` (shown or not yet) without a tool tip; standard OK / Cancel boxes aside."""
    missing = []
    for b in widget.findChildren(QAbstractButton):
        if isinstance(b.parent(), QDialogButtonBox) or type(b).__name__ == "QToolButton" and not b.text():
            continue
        if not b.toolTip().strip():
            missing.append(b.text() or b.objectName() or type(b).__name__)
    return missing


class ManualLabelsTest(unittest.TestCase):
    def test_every_label_used_by_the_code_is_in_the_manual(self):
        labels = manual_labels()
        missing = {label: f for label, f in labels_used_by_the_code().items() if label not in labels}
        self.assertEqual(missing, {})

    def test_english_manual_has_the_same_labels(self):
        """The web help is the English manual: the software links to the same labels."""
        english = TEX.with_name("irdrone_help_en.tex").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"\\label\{([^}#]+)\}", english))), sorted(manual_labels()))

    def test_figures_exist_with_the_exact_case(self):
        """Linux (GitHub Actions, the web site) is case sensitive: Step4_x.jpg is not step4_x.jpg."""
        images = {p.name for p in (TEX.parent / "images").iterdir()}
        stems = {p.stem for p in (TEX.parent / "images").iterdir()}
        for tex in (TEX, TEX.with_name("irdrone_help_en.tex")):
            text = re.sub(r"(?<!\\)%.*", "", tex.read_text(encoding="utf-8"))
            text = text[text.index("\\begin{document}"):]
            names = re.findall(r"\\figureIRD(?:\[[^\]]*\])?\{([^}]+)\}", text)
            names += re.findall(r"\{([^{}\s]+\.(?:png|jpe?g|pdf))\}", text)      # pairs of figures
            wrong = [n for n in names if n not in images and n not in stems
                     and n.lower() in {x.lower() for x in images | stems}]
            self.assertEqual(wrong, [], tex.name)

    def test_no_label_twice(self):
        text = TEX.read_text(encoding="utf-8")
        found = re.findall(r"\\label\{([^}#]+)\}", text)
        self.assertEqual(sorted({x for x in found if found.count(x) > 1}), [])


class ToolTipsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def mission(self):
        from test_home_page import make_mission
        m = make_mission(self.root, "FLY-20220125-1159-Blassac", done=(1, 2, 3, 4))
        vis = m / "AerialPhotography" / "VIS"
        vis.mkdir(parents=True)
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(
            {"shoot_points": [{"VIS": {"FileName": "VIS_0137.dng"}, "NIR": []}]}))
        (vis / "transfer_info_VIS_dng.json").write_text(json.dumps({"fly": {"listCopiedImages": ["VIS_0137.dng"]}}))
        return m

    def check(self, widget):
        self.assertEqual(buttons_without_tool_tip(widget), [], type(widget).__name__)

    def test_main_window(self):
        import IRD_Interactive_Main as Main
        window = Main.Main_Window()
        self.check(window)                       # list of the missions
        window.load_mission(self.mission())
        self.check(window)                       # the mission and its steps
        window.close()

    def test_step1_windows(self):
        import IRD_Interactive_new_mission as NM
        import IRD_Interactive_mission_details as MD
        d = NM.NewMissionDialog(self.root, scan=False)
        self.check(d)
        d.done(0)
        self.check(MD.MissionDetailsDialog(self.mission()))

    def test_steps_3_to_6(self):
        import IRD_Interactive_3 as S3
        import IRD_Interactive_4 as S4
        import IRD_Interactive_5 as S5
        import IRD_Interactive_6 as S6
        m = self.mission()
        params = {"File path mission": str(m), "folderMissionPath": str(m)}
        for dialog in (S3.DialogSynchroAruco(params), S4.DialogImageProcessing(params),
                       S4.Step4SettingsDialog(0), S5.DialogGeoRef(params), S5.ODMSelectionDialog(),
                       S6.DialogArchive(params)):
            self.check(dialog)
            dialog.done(0)

    def test_closed_step5_no_longer_receives_the_georef_log(self):
        import IRD_Interactive_5 as S5
        import IRD_Interactive_GeoRef as GeoRef
        m = self.mission()
        d = S5.DialogGeoRef({"File path mission": str(m)})
        self.assertIsNotNone(GeoRef.logger.log_callback)
        d.done(0)
        self.assertIsNone(GeoRef.logger.log_callback)
        GeoRef.logger.info("after the window was closed")       # console only, no crash

    def test_review_window(self):
        import test_review_step
        import IRD_Interactive_review as RV
        fixture = test_review_step.MissionTests("setUp")
        fixture.setUp()
        d = RV.ReviewDialog(fixture.mission)
        d.scan.wait(10000)
        self.check(d)
        d.done(0)


if __name__ == "__main__":
    unittest.main()


class F1HelpTest(unittest.TestCase):
    """F1 opens the manual at the button (under the mouse or with the focus), else at the window."""

    def setUp(self):
        import IRD_Interactive_help as Help
        self.Help = Help
        self.opened = []
        self._show_help, Help.show_help = Help.show_help, lambda label, parent=None: self.opened.append(label)

    def tearDown(self):
        self.Help.show_help = self._show_help

    def press_f1(self, widget):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        QTest.keyClick(widget, Qt.Key.Key_F1)

    def test_f1_on_the_focused_button(self):
        from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout
        dialog = QDialog()
        button = QPushButton("Run", dialog)
        QVBoxLayout(dialog).addWidget(button)
        self.Help.attach_help(button, "btn:step4_run_alignment", "Run.")
        self.assertIn("F1", button.toolTip())
        dialog.show()
        dialog.activateWindow()
        button.setFocus()
        APP.processEvents()
        self.press_f1(button)
        self.assertEqual(self.opened, ["btn:step4_run_alignment"])

    def test_f1_elsewhere_clicks_the_question_mark_of_the_window(self):
        from PyQt6.QtWidgets import QDialog, QLineEdit, QPushButton, QVBoxLayout
        dialog = QDialog()
        edit = QLineEdit(dialog)
        dialog.btn_help = QPushButton("?", dialog)
        clicked = []
        dialog.btn_help.clicked.connect(lambda: clicked.append(True))
        lay = QVBoxLayout(dialog)
        lay.addWidget(edit)
        lay.addWidget(dialog.btn_help)
        self.Help.install_f1_help()
        dialog.show()
        dialog.activateWindow()
        edit.setFocus()
        APP.processEvents()
        self.press_f1(edit)
        self.assertEqual(clicked, [True])
