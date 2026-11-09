"""Step 6 window: the dry run is implicit. When the window opens, the folder is
analysed (nothing deleted) and the window says how much archiving frees; the
archive button carries that size."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_6 as S6  # noqa: E402
import IRD_Interactive_archive as Archive  # noqa: E402
from test_step6_archive import make_mission  # noqa: E402


def settle():
    """Let the analysis worker finish and its signals reach the window."""
    for _ in range(5):
        APP.processEvents()
        QThreadPool.globalInstance().waitForDone(5000)
    APP.processEvents()


class Step6WindowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mission = make_mission(Path(self.tmp.name))

    def dialog(self):
        d = S6.DialogArchive({"File path mission": str(self.mission)})
        self.addCleanup(d.deleteLater)
        settle()
        return d

    def test_opening_tells_what_archiving_frees_and_deletes_nothing(self):
        before = sorted(p for p in self.mission.rglob("*"))
        d = self.dialog()
        plan = Archive.build_plan(self.mission)
        size = Archive.format_size(plan.total_bytes)
        self.assertEqual(d.summary_title.text(), f"{size} can be freed")
        self.assertIn(str(plan.total_files), d.summary_detail.text())
        self.assertEqual(d.btn_archive.text(), f"Archive and free {size}…")
        self.assertTrue(d.btn_archive.isEnabled())
        self.assertFalse(hasattr(d, "btn_simulate"))
        self.assertEqual(sorted(p for p in self.mission.rglob("*")), before)

    def test_missing_files_block_the_archiving(self):
        (self.mission / "AerialPhotography" / "shoot_points.json").unlink()
        d = self.dialog()
        self.assertEqual(d.summary_title.text(), "Archiving impossible")
        self.assertIn("shoot_points.json", d.summary_detail.text())
        self.assertFalse(d.btn_archive.isEnabled())

    def test_archived_mission_says_so(self):
        Archive.execute_archive(Archive.build_plan(self.mission))
        d = self.dialog()
        self.assertIn("already archived", d.summary_title.text())
        self.assertFalse(d.btn_archive.isEnabled())

    def test_wrong_name_deletes_nothing(self):
        d = self.dialog()
        with mock.patch.object(S6.QInputDialog, "getText", return_value=("wrong", True)):
            d.on_archive()
            settle()
        self.assertTrue((self.mission / "dev_leftover.txt").exists())
        self.assertTrue(d.btn_archive.isEnabled())

    def test_archiving_then_the_card_says_archived(self):
        d = self.dialog()
        with mock.patch.object(S6.QInputDialog, "getText", return_value=(self.mission.name, True)), \
                mock.patch.object(S6.QMessageBox, "information"):
            d.on_archive()
            settle()
            settle()
        self.assertFalse((self.mission / "dev_leftover.txt").exists())
        self.assertIn("already archived", d.summary_title.text())


if __name__ == "__main__":
    unittest.main()
