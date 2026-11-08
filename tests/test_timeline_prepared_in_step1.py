"""Step 2 prepared during Step 1: the scan of a band lands in the cache, so
the analysis of Step 2 does not read the images again; stopping it early
leaves a partial cache that Step 2 completes."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import flight_timeline as FT  # noqa: E402


def make_mission(n_vis=12, n_nir=10):
    m = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
    for band, n in (("VIS", n_vis), ("NIR", n_nir)):
        folder = m / "AerialPhotography" / band
        folder.mkdir(parents=True)
        for k in range(1, n + 1):
            (folder / f"{band}_{k:04d}.dng").write_bytes(b"dng")
            alt = 2.0 if k <= 6 else 80.0          # low hover, then the survey
            (folder / f"{band}_{k:04d}.exif").write_text(json.dumps(
                {"RelativeTimeLine": 2.0 * k, "DroneAltitudeTakeOff": alt}))
    return m


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.reads = []
        img = np.zeros((60, 80, 3), np.uint8)
        p1 = mock.patch.object(FT, "read_preview", side_effect=lambda p, *a, **k: self.reads.append(p) or img)
        p2 = mock.patch.object(FT, "detect_mobile_marker", return_value=(10.0, 5.0))
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_step2_reads_nothing_after_step1_prepared_both_bands(self):
        m = make_mission()
        FT.prepare_band(m, "VIS")
        FT.prepare_band(m, "NIR")
        self.assertTrue(self.reads)
        self.reads.clear()
        vis, nir, _ = FT.analyse_mission(m)
        self.assertEqual(self.reads, [])                     # all from the cache
        self.assertTrue(all(f.scanned for f in vis.frames[:6]))

    def test_stopped_early_step2_goes_on_from_the_cache(self):
        m = make_mission()
        with self.assertRaises(InterruptedError):
            FT.prepare_band(m, "VIS", cancelled=lambda: len(self.reads) >= 4)
        first = len(self.reads)
        self.reads.clear()
        FT.analyse_mission(m)
        vis_reads = [p for p in self.reads if "VIS" in Path(p).name]
        self.assertEqual(len(vis_reads), 12 - first)          # only the frames not done yet


class Step1DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_prep_thread_runs_and_reports(self):
        import IRD_Interactive_new_mission as NM
        m = make_mission()
        seen = []
        img = np.zeros((60, 80, 3), np.uint8)
        with mock.patch.object(FT, "read_preview", return_value=img), \
                mock.patch.object(FT, "detect_mobile_marker", return_value=(None, None)):
            t = NM.TimelinePrep(m, "VIS")
            t.progress.connect(lambda b, d, n: seen.append((b, d, n)))
            t.start()
            end = time.time() + 10
            while t.isRunning() and time.time() < end:
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()
        self.assertEqual(seen[-1], ("VIS", 12, 12))
        self.assertTrue((m / "Synchro").exists())


if __name__ == "__main__":
    unittest.main()
