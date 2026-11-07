"""Review of the aligned survey images (end of Step 4): loading the shoot
points, measuring the residual misalignment, flagging and the saved state."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import shoot_review as R  # noqa: E402


def textured(h=600, w=800, seed=0):
    """Fields and hedges: blobs of texture at several scales."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w), np.float32)
    for size in (5, 17, 41):
        noise = rng.random((h // size + 2, w // size + 2)).astype(np.float32)
        img += cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
    img = (img - img.min()) / (img.max() - img.min())
    return (img * 255).astype(np.uint8)


def shifted(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REFLECT)


class ResidualShiftTests(unittest.TestCase):
    def setUp(self):
        gray = textured()
        self.vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        # the infrared does not look like the visible: other contrast
        self.nir = (255 - gray // 2).astype(np.uint8)

    def test_aligned_images_read_about_zero(self):
        shift, worst = R.residual_shift(self.vis, self.nir)
        self.assertLess(shift, 1.0)
        self.assertLess(worst, 1.5)

    def test_a_shift_is_measured_in_full_image_pixels(self):
        shift, _ = R.residual_shift(self.vis, shifted(self.nir, 8, 6), width=400)
        self.assertAlmostEqual(shift, 10.0, delta=1.5)

    def test_no_texture_cannot_be_measured(self):
        flat = np.full((600, 800), 120, np.uint8)
        self.assertEqual(R.residual_shift(cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR), flat), (None, None))


class StatusTests(unittest.TestCase):
    def point(self, **kw):
        p = R.ReviewPoint(number=1, stem="VIS_0001", vis_image=Path("a"), vir_image=Path("b"))
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    def test_thresholds(self):
        self.assertEqual(self.point(shift=1.2).status, R.STATUS_OK)
        self.assertEqual(self.point(shift=4.0).status, R.STATUS_CHECK)
        self.assertEqual(self.point(shift=12.0).status, R.STATUS_SUSPICIOUS)
        self.assertEqual(self.point().status, R.STATUS_UNKNOWN)

    def test_flag_wins_then_missing_then_checked(self):
        self.assertEqual(self.point(shift=1.0, failed=True).status, R.STATUS_FLAGGED)
        self.assertEqual(self.point(vir_image=None).status, R.STATUS_MISSING)
        self.assertEqual(self.point(shift=12.0, checked=True).status, R.STATUS_CHECKED)


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        out = self.mission / "ImgIRdrone"
        out.mkdir(parents=True)
        (self.mission / "AerialPhotography").mkdir()
        gray = textured(300, 400)
        points, pairs = [], []
        for k, number in enumerate((137, 140, 143)):
            stem = f"VIS_{number:04d}"
            vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            nir = shifted(gray, 12 if number == 140 else 0, 0)
            vir = vis.copy()
            vir[:, :, 2] = nir
            cv2.imwrite(str(out / f"{stem}.jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 98])
            if number != 143:   # 143: alignment failed, no image
                cv2.imwrite(str(out / f"VIR_{number:04d}_local.jpg"), vir, [cv2.IMWRITE_JPEG_QUALITY, 98])
            (out / f"{stem}_REDO.sh").write_text("#!/bin/sh\n")
            points.append({"FileName": f"{stem}.dng", "dt": 0.1 * k, "failed": False})
            pairs.append({"VIS": {"FileName": f"{stem}.dng", "RelativeTimeLine": 270.0 + 6 * k,
                                  "DroneAltitudeGround": 115.0},
                          "NIR": [{"rank": 1, "FileName": f"NIR_{100 + k:04d}.dng", "dt": 0.1 * k}]})
        (out / "shoot_points.json").write_text(json.dumps({"time_shift": 1.0, "shoot_points": points}))
        (self.mission / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": pairs}))

    def test_load_reads_images_pairs_and_redo_scripts(self):
        review = R.load_review(self.mission)
        self.assertEqual([p.number for p in review.points], [137, 140, 143])
        p = review.points[0]
        self.assertEqual((p.time, p.altitude, p.nir_name), (270.0, 115.0, "NIR_0100.dng"))
        self.assertIsNotNone(p.redo_script)
        self.assertEqual(review.points[2].status, R.STATUS_MISSING)

    def test_no_step4_output_yet(self):
        with self.assertRaises(FileNotFoundError):
            R.load_review(self.mission.parent / "nothing")

    def test_measure_finds_the_misaligned_point_and_caches_it(self):
        review = R.load_review(self.mission)
        R.measure_all(review)
        statuses = {p.number: p.status for p in review.points}
        self.assertEqual(statuses[137], R.STATUS_OK)
        self.assertEqual(statuses[140], R.STATUS_SUSPICIOUS)
        R.save_state(review)
        again = R.load_review(self.mission)
        self.assertAlmostEqual(again.by_number(140).shift, review.by_number(140).shift)

    def test_cached_score_dropped_when_the_image_changes(self):
        review = R.load_review(self.mission)
        R.measure_all(review)
        R.save_state(review)
        vir = self.mission / "ImgIRdrone" / "VIR_0140_local.jpg"
        vir.write_bytes(vir.read_bytes() + b"\0" * 10)   # rewritten by a redo
        self.assertIsNone(R.load_review(self.mission).by_number(140).shift)

    def test_flag_and_unflag_write_the_inventory_and_summary(self):
        review = R.load_review(self.mission)
        R.set_failed(review, {140}, True)
        inv = json.loads((self.mission / "ImgIRdrone" / "shoot_points.json").read_text())
        self.assertEqual([p["failed"] for p in inv["shoot_points"]], [False, True, False])
        summary = json.loads((self.mission / "ImgIRdrone" / "shoot_points_failed_summary.json").read_text())
        self.assertEqual(summary["failed_true"], ["0140"])
        self.assertEqual(R.load_review(self.mission).by_number(140).status, R.STATUS_FLAGGED)
        R.set_failed(review, {140}, False)
        self.assertFalse(R.load_review(self.mission).by_number(140).failed)

    def test_checked_points_are_remembered(self):
        review = R.load_review(self.mission)
        review.by_number(137).checked = True
        R.save_state(review)
        self.assertTrue(R.load_review(self.mission).by_number(137).checked)


if __name__ == "__main__":
    unittest.main()
