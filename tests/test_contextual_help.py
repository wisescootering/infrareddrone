"""Contextual help: every button of the windows has a tool tip, and every
manual label used by the code (right-click "Help on this button", "?" buttons)
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
