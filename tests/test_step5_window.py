"""Step 5 window: same frame as Step 3 (stages, one main action), the map built
earlier is shown when the window opens, and the image selection starts the map
without a second confirmation."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_5 as S5  # noqa: E402
import IRD_Interactive_look as Look  # noqa: E402


class Step5WindowTest(unittest.TestCase):
    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        self.mission.mkdir()

    def dialog(self):
        d = S5.DialogGeoRef({"File path mission": str(self.mission)})
        self.addCleanup(d.done, 0)
        return d

    def test_header_and_main_action(self):
        d = self.dialog()
        self.assertIn("Step 5", d.windowTitle())
        self.assertIn(self.mission.name, d.windowTitle())
        self.assertIn("Build the map", d.btn_run_Mapping.text())
        self.assertIn(Look.PRIMARY_STYLE, d.btn_run_Mapping.styleSheet())
        self.assertIn(Look.SECONDARY_STYLE, d.btn_run_GeoRef.styleSheet())

    def test_without_a_map_the_terrain_model_waits(self):
        d = self.dialog()
        self.assertFalse(d.btn_run_DTM.isEnabled())
        self.assertEqual(d.stages.states, [Look.STAGE_PENDING] * 3)

    def test_map_built_earlier_is_shown(self):
        result = self.mission / "mapping_MULTI" / "mapping_result"
        result.mkdir(parents=True)
        (result / "odm_orthophoto.tif").write_bytes(b"")
        (result / "ortho_dtm.tif").write_bytes(b"")
        with mock.patch.object(S5.DialogGeoRef, "_start_ODM_preview") as preview:
            d = self.dialog()
        preview.assert_called_once_with(result / "odm_orthophoto.tif")
        self.assertTrue(d.btn_run_DTM.isEnabled())
        self.assertEqual(d.stages.states, [Look.STAGE_DONE] * 3)

    def test_the_selection_starts_the_map_without_a_second_question(self):
        d = self.dialog()
        with mock.patch.object(S5.ODMSelectionDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                mock.patch.object(S5.QMessageBox, "question") as question, \
                mock.patch.object(d, "_start_ODM_worker") as start:
            d.on_run_ODM()
        question.assert_not_called()
        start.assert_called_once()
        self.assertEqual(d.stages.states[0], Look.STAGE_DONE)

    def test_cancel_starts_nothing(self):
        d = self.dialog()
        with mock.patch.object(S5.ODMSelectionDialog, "exec", return_value=QDialog.DialogCode.Rejected), \
                mock.patch.object(d, "_start_ODM_worker") as start:
            d.on_run_ODM()
        start.assert_not_called()
        self.assertEqual(d.stages.states[0], Look.STAGE_PENDING)


if __name__ == "__main__":
    unittest.main()
