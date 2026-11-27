"""Spectral balance (Step 6): tone adjustments, automatic NIR, balanced bands
written beside the originals, and the map built from them."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import spectral_balance as SB  # noqa: E402
from image_io import imwrite  # noqa: E402


def make_quartets(mission: Path, numbers=(45, 46), shape=(60, 80), nir_scale=0.3):
    """Four 16 bit bands per image: visible gradients, a dark NIR."""
    folder = mission / SB.SOURCE_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    for n in numbers:
        base = np.linspace(0.1, 0.9, shape[1])[None, :] * np.ones(shape)
        noise = rng.uniform(-0.05, 0.05, shape)
        for k, gain in enumerate((1.0, 0.95, 0.85, nir_scale), start=1):
            band = np.clip((base + noise) * gain, 0, 1) * 65535
            imwrite(folder / f"IRD_{n:04d}_{k}.tif", band.astype(np.uint16), [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        (folder / f"IRD_{n:04d}_1.exif").write_text("{}", encoding="utf-8")
    return folder


class TransferTest(unittest.TestCase):
    def test_neutral_balance_changes_nothing(self):
        b = SB.Balance()
        self.assertTrue(b.is_identity())
        for band in SB.BANDS:
            np.testing.assert_array_equal(SB.lut16(b, band), np.arange(65536, dtype=np.uint16))

    def test_exposure_doubles_and_gamma_lifts_the_mid_tones(self):
        x = np.array([0.1, 0.25, 0.5])
        np.testing.assert_allclose(SB.transfer(SB.Adjust(exposure=1.0), x), [0.2, 0.5, 1.0])
        np.testing.assert_allclose(SB.transfer(SB.Adjust(gamma=2.0), np.array([0.25])), [0.5])

    def test_contrast_pivots_on_mid_grey_and_brightness_shifts(self):
        x = np.array([0.4, 0.5, 0.6])
        out = SB.transfer(SB.Adjust(contrast=1.0), x)
        self.assertAlmostEqual(out[1], 0.5)
        self.assertAlmostEqual(out[2] - out[0], 0.6, places=6)    # x3
        np.testing.assert_allclose(SB.transfer(SB.Adjust(brightness=0.2), x), x + 0.1)

    def test_curve_goes_through_its_handles_without_overshoot(self):
        curve = SB.clean_curve([(0, 0), (0.25, 0.15), (0.75, 0.85), (1, 1)])    # an S
        x = np.linspace(0, 1, 1001)
        y = SB.curve_eval(curve, x)
        for hx, hy in curve:
            self.assertAlmostEqual(float(SB.curve_eval(curve, np.array([hx]))[0]), hy, places=9)
        self.assertTrue(np.all(np.diff(y) >= -1e-12))     # monotone handles: monotone curve
        self.assertTrue(y.min() >= 0 and y.max() <= 1)

    def test_visible_bands_take_the_rgb_layer_then_their_own(self):
        b = SB.Balance()
        b.layer("rgb").exposure = 1.0
        b.layer("red").exposure = -1.0
        x = np.array([0.2])
        self.assertAlmostEqual(float(SB.band_transfer(b, "red", x)[0]), 0.2)
        self.assertAlmostEqual(float(SB.band_transfer(b, "green", x)[0]), 0.4)
        self.assertAlmostEqual(float(SB.band_transfer(b, "nir", x)[0]), 0.2)

    def test_the_all_layer_applies_to_the_four_bands_after_their_own(self):
        b = SB.Balance()
        b.layer("all").exposure = 1.0
        b.layer("nir").gamma = 2.0
        x = np.array([0.04])
        self.assertAlmostEqual(float(SB.band_transfer(b, "red", x)[0]), 0.08)
        self.assertAlmostEqual(float(SB.band_transfer(b, "nir", x)[0]), 0.4)      # 0.04^(1/2) = 0.2, x2
        self.assertFalse(b.is_identity())
        old = SB.Balance.from_json({"layers": {"nir": {"exposure": 1.0}}})       # saved before "all" existed
        self.assertTrue(old.layer("all").is_identity())

    def test_settings_survive_a_round_trip_and_bad_values_are_clamped(self):
        s = SB.Settings()
        s.mission.layer("nir").exposure = 1.5
        s.mission.layer("nir").curve = SB.clean_curve([(0, 0.1), (0.5, 0.6), (1, 1)])
        s.mission.nir_auto = True
        s.points[45] = SB.Balance()
        s.points[45].layer("red").gamma = 1.3
        back = SB.Settings.from_json(json.loads(json.dumps(s.to_json())))
        self.assertEqual(back.to_json(), s.to_json())
        self.assertEqual(SB.Adjust.from_json({"exposure": 99, "gamma": "x"}).exposure, SB.EXPOSURE_RANGE[1])
        self.assertEqual(SB.Adjust.from_json({"gamma": "x"}).gamma, 1.0)


class AutoNirTest(unittest.TestCase):
    def test_automatic_nir_takes_the_median_and_the_highlights_of_the_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            mission = Path(tmp)
            make_quartets(mission, numbers=(45,), nir_scale=0.3)
            bands = SB.read_bands(SB.source_paths(mission, 45))
        b = SB.Balance(nir_auto=True)
        small = SB.stats_copy(bands)
        applied = SB.effective(b, small)
        self.assertFalse(applied.nir_auto)
        self.assertGreater(applied.layer("nir").exposure, 1.0)        # dark NIR made brighter
        out = SB.apply(applied, bands).astype(np.float64) / 65535
        vis = out[..., :3].mean(axis=-1)
        for q in SB.AUTO_PERCENTILES:
            self.assertAlmostEqual(np.percentile(out[..., 3], q), np.percentile(vis, q), delta=0.02)
        # a common S curve on the four bands keeps the NIR matched
        b.layer("all").curve = SB.clean_curve([(0, 0), (0.3, 0.2), (0.7, 0.8), (1, 1)])
        out = SB.apply(SB.effective(b, small), bands).astype(np.float64) / 65535
        vis = out[..., :3].mean(axis=-1)
        for q in SB.AUTO_PERCENTILES:
            self.assertAlmostEqual(np.percentile(out[..., 3], q), np.percentile(vis, q), delta=0.03)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mission = Path(self.tmp.name)
        make_quartets(self.mission)
        self.settings = SB.Settings()
        self.settings.mission.layer("nir").exposure = 1.0

    def test_quartets_of_the_mission(self):
        (self.mission / SB.SOURCE_FOLDER / "IRD_0047_1.tif").write_bytes(b"")    # incomplete
        self.assertEqual(SB.quartet_numbers(self.mission), [45, 46])

    def test_written_bands_are_balanced_and_the_point_is_done_until_something_changes(self):
        self.assertEqual(SB.point_state(self.mission, 45, self.settings), SB.STATE_NONE)
        record = SB.write_point(self.mission, 45, self.settings, metadata=False)
        out = SB.read_bands(SB.balanced_paths(self.mission, 45))
        src = SB.read_bands(SB.source_paths(self.mission, 45))
        np.testing.assert_array_equal(out[..., :3], src[..., :3])
        expected = np.clip(src[..., 3].astype(np.float64) * 2, 0, 65535)
        self.assertLessEqual(np.abs(out[..., 3] - expected).max(), 1)
        self.assertTrue((self.mission / SB.BALANCE_FOLDER / "IRD_0045_1.exif").is_file())
        self.assertEqual(record["balance"], self.settings.mission.to_json())
        self.assertTrue(SB.record_path(self.mission, 45).is_file())
        self.assertEqual(SB.point_state(self.mission, 45, self.settings), SB.STATE_DONE)
        # the balance changes: out of date
        self.settings.mission.layer("nir").exposure = 0.5
        self.assertEqual(SB.point_state(self.mission, 45, self.settings), SB.STATE_STALE)
        self.settings.mission.layer("nir").exposure = 1.0
        # Step 4 writes the originals again: out of date
        time.sleep(0.01)
        src_path = SB.source_paths(self.mission, 45)[3]
        src_path.write_bytes(src_path.read_bytes())
        self.assertEqual(SB.point_state(self.mission, 45, self.settings), SB.STATE_STALE)

    def test_an_image_with_its_own_balance(self):
        own = self.settings.mission.copy()
        own.layer("nir").exposure = -1.0
        self.settings.points[46] = own
        SB.write_point(self.mission, 45, self.settings, metadata=False)
        record = SB.write_point(self.mission, 46, self.settings, metadata=False)
        self.assertTrue(record["own_balance"])
        a = SB.read_bands(SB.balanced_paths(self.mission, 45))[..., 3].mean()
        b = SB.read_bands(SB.balanced_paths(self.mission, 46))[..., 3].mean()
        self.assertGreater(a, 3 * b)

    @unittest.skipUnless(shutil.which("exiftool"), "ExifTool not installed")
    def test_metadata_of_the_originals_are_copied(self):
        import subprocess
        src = SB.source_paths(self.mission, 45)[3]
        conf = ROOT / "thirdparty" / "exiftool" / "xmp.config"
        subprocess.run(["exiftool", "-config", str(conf), "-XMP-camera:BandName=NIR", "-Make=irdrone",
                        "-overwrite_original", str(src)], check=True, capture_output=True)
        SB.write_point(self.mission, 45, self.settings)
        out = subprocess.run(["exiftool", "-config", str(conf), "-s3", "-XMP-camera:BandName", "-Make",
                              str(SB.balanced_paths(self.mission, 45)[3])],
                             check=True, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["NIR", "irdrone"])
        self.assertEqual(SB.point_state(self.mission, 45, self.settings), SB.STATE_DONE)

    def test_the_map_uses_the_balanced_bands_once_a_balance_is_set(self):
        def manifest():
            return {"image_quartets": [{"files": {b: str(p) for b, p in zip(
                SB.BANDS, SB.source_paths(self.mission, n))}} for n in (45, 46)]}
        m = manifest()
        self.assertIsNone(SB.apply_to_manifest(self.mission, m))          # no balance: the originals
        SB.save_settings(self.mission, SB.Settings())
        self.assertIsNone(SB.apply_to_manifest(self.mission, m))          # neutral balance: the originals
        self.assertIn("imgMultispectral", m["image_quartets"][0]["files"]["nir"])
        SB.save_settings(self.mission, self.settings)
        SB.write_point(self.mission, 45, self.settings, metadata=False)
        written = []
        orig = SB.write_point
        SB.write_point = lambda mission, n, s: (written.append(n), orig(mission, n, s, metadata=False))[1]
        try:
            summary = SB.apply_to_manifest(self.mission, m, log=lambda _: None)
        finally:
            SB.write_point = orig
        self.assertEqual(written, [46])                 # 45 up to date: not written again
        self.assertEqual((summary["written"], summary["up_to_date"]), (1, 1))
        for q in m["image_quartets"]:
            for band, path in q["files"].items():
                self.assertIn("img_Bal_Multispectral", path)
                self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
