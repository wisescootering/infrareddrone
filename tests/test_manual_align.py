"""Alignment by hand in the wizard (Qt window of the Step 4 review): the infrared
moved by yaw / pitch, the offset measured between the edges, "Fit", and the
window flow (place, skip, compute). Offscreen, synthetic images."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import IRD_Interactive_manual_align as M  # noqa: E402
from test_review_step import shifted, textured  # noqa: E402

SCALE = 0.2          # the full images are 5 times larger than the previews
TRUE_ANGLES = (1.2, 2.9, 0.0)


def synthetic_preview():
    """An infrared image and the visible one it shows once rotated by TRUE_ANGLES."""
    nir_gray = textured(690, 920, seed=3)
    nir = cv2.cvtColor(nir_gray, cv2.COLOR_GRAY2RGB)
    blank = np.zeros((598, 798, 3), np.uint8)
    vis = M.warp_preview(M.Preview(blank, nir, SCALE), TRUE_ANGLES)
    vis = np.ascontiguousarray(255 - vis)          # other contrast than the infrared
    return M.Preview(vis, nir, SCALE)


class OffsetTests(unittest.TestCase):
    def test_signed_tile_offsets(self):
        gray = textured()
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        dx, dy = M.measure_offset(vis, shifted(gray, 8, -6))
        self.assertAlmostEqual(dx, 8, delta=1)
        self.assertAlmostEqual(dy, -6, delta=1)

    def test_yaw_moves_right_pitch_down(self):
        p = synthetic_preview()

        def offset(angles):
            arrays = M.display_arrays(p.vis, M.warp_preview(p, angles))
            return M.measure_offset(arrays["vis"], arrays["vir"][:, :, 2])
        self.assertLess(np.hypot(*offset(TRUE_ANGLES)), 1.0)
        dx, dy = offset(M.move_angles(TRUE_ANGLES, 12, -7, p.focal))
        self.assertAlmostEqual(dx, 12, delta=1.5)
        self.assertAlmostEqual(dy, -7, delta=1.5)

    def test_redo_command_without_angles(self):
        items = M.items_from_queue([(5, "VIS_0005", ["--images", "/a/VIS_0005.dng", "/a/NIR_0001.dng"]),
                                    (6, "VIS_0006", ["--outdir", "x"])])        # unreadable: left out
        self.assertEqual([(i.number, i.initial) for i in items], [(5, (0.0, 0.0, 0.0))])

    def test_describe(self):
        self.assertIn("well placed", M.describe_offset((3.0, -2.0)))
        self.assertIn("40 px right, 25 px up", M.describe_offset((40.0, -25.0)))
        self.assertIn("not measurable", M.describe_offset(None))


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.preview = synthetic_preview()

    def window(self, n=3):
        start = (TRUE_ANGLES[0] + 0.6, TRUE_ANGLES[1] - 0.4, 0.0)
        items = [M.AlignItem(k, f"VIS_{k:04d}", ["--images", f"/a/VIS_{k:04d}.dng", f"/a/NIR_{k:04d}.dng"],
                             Path(f"/a/VIS_{k:04d}.dng"), Path(f"/a/NIR_{k:04d}.dng"), start, start)
                 for k in range(1, n + 1)]
        patcher = mock.patch.object(M, "load_preview", return_value=self.preview)
        patcher.start()
        self.addCleanup(patcher.stop)
        d = M.ManualAlignDialog(items, "Mission")
        deadline = time.time() + 20
        while any(i.preview is None for i in items) and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return d, items

    def test_keys_move_the_infrared_and_place_the_point(self):
        d, items = self.window()
        self.assertEqual(items[0].state, M.TODO)
        self.assertIn("Compute 0", d.btn_compute.text())
        d.nudge(1, 0)
        d.nudge(0, -10)
        d.rotate(-1)
        yaw, pitch, roll = items[0].angles
        self.assertAlmostEqual(yaw - items[0].initial[0], M.STEP)
        self.assertAlmostEqual(pitch - items[0].initial[1], -10 * M.STEP)
        self.assertAlmostEqual(roll, -M.STEP)
        self.assertEqual(items[0].state, M.PLACED)
        self.assertAlmostEqual(d.spins["yaw"].value(), round(yaw, 2))
        self.assertTrue(d.btn_compute.isEnabled())
        d.reset()
        self.assertEqual(items[0].angles, items[0].initial)
        d.done(0)

    def test_sliders_move_the_infrared_and_follow_the_keys(self):
        d, items = self.window(1)
        d.sliders["yaw"].setValue(round(3.0 * M.SLIDER_UNITS))
        self.assertAlmostEqual(items[0].angles[0], 3.0)
        self.assertEqual(items[0].state, M.PLACED)
        d.nudge(0, 1)
        self.assertEqual(d.sliders["pitch"].value(), round(items[0].angles[1] * M.SLIDER_UNITS))
        self.assertAlmostEqual(d.spins["yaw"].value(), 3.0)
        d.done(0)

    def test_arrow_keys_in_a_value_box_move_the_infrared(self):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import Qt
        d, items = self.window(1)
        pitch = items[0].angles[1]
        QApplication.sendEvent(d.spins["pitch"], QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up,
                                                            Qt.KeyboardModifier.NoModifier))
        self.assertAlmostEqual(items[0].angles[1], pitch - M.STEP)    # up, as everywhere
        d.done(0)

    def test_dragging_moves_by_the_pixels_dragged(self):
        d, items = self.window(1)
        d._on_drag_start()
        d._on_drag(20.0, 0.0)
        d._on_drag(10.0, -5.0)                     # relative to the drag start, not cumulative
        expected = M.move_angles(items[0].initial, 10.0, -5.0, self.preview.focal)
        np.testing.assert_allclose(items[0].angles, expected)
        d.done(0)

    def test_fit_finds_the_true_angles(self):
        d, items = self.window(1)
        d._measure()
        self.assertGreater(np.hypot(*items[0].offset), 3 * M.CLOSE_ENOUGH)
        d.fit()
        self.assertAlmostEqual(items[0].angles[0], TRUE_ANGLES[0], delta=0.05)
        self.assertAlmostEqual(items[0].angles[1], TRUE_ANGLES[1], delta=0.05)
        self.assertLess(np.hypot(*items[0].offset), M.CLOSE_ENOUGH)
        self.assertIn("well placed", d.offset_label.text())
        d.done(0)

    def test_place_skip_and_compute(self):
        d, items = self.window()
        d.place_and_next()
        self.assertIs(d.current(), items[1])
        d.skip()
        self.assertIs(d.current(), items[2])
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Ok) as ask:
            d.compute()                            # the third is not placed: asked, left out
            ask.assert_called_once()
        self.assertEqual(d.result(), 1)
        self.assertEqual([i.number for i in d.placed()], [1])
        self.assertEqual([i.state for i in items], [M.PLACED, M.SKIPPED, M.TODO])

    def test_placed_points_compute_while_the_next_is_placed(self):
        sent = []
        d, items = self.window()
        d.send_now = sent.append
        d.nudge(1, 0)
        d.place_and_next()
        self.assertEqual(sent, [items[0]])
        self.assertEqual(items[0].state, M.SENT)
        self.assertIs(d.current(), items[1])
        self.assertEqual(d.placed(), [])                 # sent already: not sent again
        self.assertIn("Compute 0", d.btn_compute.text())
        self.assertEqual(d.btn_cancel.text(), "Close")
        d.select(0)                                      # locked while it computes
        angles = items[0].angles
        d.nudge(5, 5)
        d.skip()
        self.assertEqual((items[0].angles, items[0].state), (angles, M.SENT))
        self.assertFalse(d.sliders["yaw"].isEnabled())
        d.compute()                                      # nothing left to send: closes
        self.assertEqual(d.result(), 1)

    def test_cancel_asks_before_forgetting_the_placed_points(self):
        d, _items = self.window(2)
        d.place_and_next()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            d.reject()
        self.assertTrue(d.isVisible() or d.result() == 0)
        self.assertNotEqual(d.result(), 1)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            d.reject()
        self.assertEqual(d.result(), 0)

    def test_unreadable_images_are_skipped(self):
        with mock.patch.object(M, "load_preview", side_effect=OSError("broken RAW")):
            items = [M.AlignItem(1, "VIS_0001", [], Path("a"), Path("b"))]
            d = M.ManualAlignDialog(items)
            deadline = time.time() + 10
            while not items[0].error and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
        self.assertEqual(items[0].state, M.SKIPPED)
        self.assertIn("broken RAW", items[0].error)
        d.place_and_next()                         # nothing to place
        self.assertEqual(items[0].state, M.SKIPPED)
        d.done(0)


if __name__ == "__main__":
    unittest.main()
