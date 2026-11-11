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

    def test_overlay_colours(self):
        """An edge only in the visible / only in the infrared, in each scheme."""
        from shoot_review import OVERLAY_COLOURS, overlay
        vis = np.zeros((40, 40, 3), np.uint8)
        vis[:, :10] = (40, 200, 120)                    # visible only (BGR, greenish)
        vir = np.zeros((40, 40, 3), np.uint8)
        vir[:, 30:, 2] = 255                            # infrared only
        expected = {  # (visible only, infrared only), BGR
            "colour_grey": ((20, 100, 60), (127, 127, 127)),
            "green_grey": ((0, 127, 0), (127, 127, 127)),
            "blue_red": ((255, 0, 0), (0, 0, 255)),
            "cyan_red": ((255, 255, 0), (0, 0, 255)),
        }
        self.assertEqual(set(expected), set(OVERLAY_COLOURS))
        for key, (only_vis, only_nir) in expected.items():
            out = overlay(vis, vir, key)
            np.testing.assert_allclose(out[20, 5], only_vis, atol=1, err_msg=key)
            np.testing.assert_allclose(out[20, 35], only_nir, atol=1, err_msg=key)
        self.assertIn(M.DEFAULT_OVERLAY_COLOURS, OVERLAY_COLOURS)

    def test_overlay_colours_kept_in_the_settings(self):
        from PyQt6.QtCore import QSettings
        with mock.patch.object(M, "SETTINGS", ("IRdrone-test", "manual-align-test")):
            QSettings(*M.SETTINGS).clear()
            try:
                self.assertEqual(M.load_overlay_colours(), "colour_grey")
                M.save_overlay_colours("blue_red")
                self.assertEqual(M.load_overlay_colours(), "blue_red")
                QSettings(*M.SETTINGS).setValue(M.OVERLAY_COLOURS_KEY, "purple")   # unknown: default
                self.assertEqual(M.load_overlay_colours(), "colour_grey")
            finally:
                QSettings(*M.SETTINGS).clear()

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
        for name, value in (("load_preview", mock.Mock(return_value=self.preview)),
                            ("load_overlay_colours", mock.Mock(return_value=M.DEFAULT_OVERLAY_COLOURS)),
                            ("save_overlay_colours", mock.Mock())):   # not the user's settings
            patcher = mock.patch.object(M, name, value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        d = M.ManualAlignDialog(items, "Mission")
        deadline = time.time() + 20
        while any(i.preview is None for i in items) and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return d, items

    def test_the_images_are_shown_in_every_mode(self):
        """Not black: the view is given images it can paint, in each mode."""
        d, items = self.window()
        self.assertTrue(d.view.has_images())
        self.assertEqual(d.view.message, "")
        for key in ("vis", "vir", "nir", "ana"):
            pix = d.view.image(key)
            self.assertIsNotNone(pix, key)
            self.assertFalse(pix.isNull(), key)
            self.assertGreater(pix.toImage().pixelColor(pix.width() // 2, pix.height() // 2).value(), 0, key)
        d.nudge(1, 0)                                  # moved: new images, shown too
        self.assertIsNotNone(d.view.image("ana"))
        d.done(0)

    def test_overlay_colours_chosen_and_kept(self):
        """Default: the visible in colour, the infrared in grey; a choice in the
        Colours menu is drawn at once, saved, and shows the overlay."""
        d, items = self.window(1)
        self.assertEqual(d.overlay_colours, "colour_grey")
        self.assertIn("Visible colour · infrared grey", d.view.overlay_tag)
        checked = [a.data() for a in d.colour_actions.actions() if a.isChecked()]
        self.assertEqual(checked, ["colour_grey"])
        d.set_mode("swipe")
        action = next(a for a in d.colour_actions.actions() if a.data() == "green_grey")
        action.trigger()
        self.assertEqual(d.overlay_colours, "green_grey")
        self.save_overlay_colours.assert_called_once_with("green_grey")
        self.assertEqual(d.view.mode, "overlay")
        self.assertIn("Visible green · infrared grey", d.view.overlay_tag)
        self.assertIsNotNone(d.view.image("ana"))
        d.done(0)

    def test_the_edges_in_colour_are_drawn_in_green(self):
        d, items = self.window(1)
        d.edges_box.setChecked(True)
        self.assertIn("Visible green", d.view.overlay_tag)
        d.edges_box.setChecked(False)
        self.assertIn("Visible colour", d.view.overlay_tag)
        d.done(0)

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

    def test_right_dragging_in_the_image_moves_the_infrared(self):
        """With the mouse, through the view (an error in a mouse handler ends the program)."""
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        d, items = self.window()
        d.resize(1300, 850)
        d.show()
        self.app.processEvents()
        before = items[0].angles
        centre = d.view.rect().center()
        for button, modifier in ((Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier),
                                 (Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)):
            QTest.mousePress(d.view, button, modifier, centre)
            QTest.mouseMove(d.view, centre + QPoint(40, 0))
            QTest.mouseRelease(d.view, button, modifier, centre + QPoint(40, 0))
            self.app.processEvents()
        self.assertNotEqual(items[0].angles, before)
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
