import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import IRD_Interactive_ArUco as Aru


class AngleMismatchTests(unittest.TestCase):
    def setUp(self):
        self.t_vis = np.arange(0.0, 30.0, 2.0)
        self.t_nir = np.arange(0.3, 30.0, 1.0)
        self.curve = lambda t: 12 * t + 20 * np.sin(t / 3)

    def test_gap_is_smallest_at_the_true_shift(self):
        # NIR(t) = VIS(t + 0.7): moving NIR to t + 0.7 lays it on VIS.
        a_vis = self.curve(self.t_vis)
        a_nir = self.curve(self.t_nir + 0.7)
        shifts = np.round(np.arange(-1.0, 3.0, 0.01), 2)
        gaps = [Aru.angle_mismatch_rms(self.t_vis, a_vis, self.t_nir, a_nir, s)[0] for s in shifts]
        self.assertAlmostEqual(float(shifts[int(np.argmin(gaps))]), 0.7, places=2)
        rms, count = Aru.angle_mismatch_rms(self.t_vis, a_vis, self.t_nir, a_nir, 0.7)
        self.assertLess(rms, 0.5)
        self.assertGreater(count, 10)

    def test_no_overlap_or_too_few_samples(self):
        self.assertEqual(Aru.angle_mismatch_rms([0, 1], [0, 1], [0, 1], [0, 1], 100.0), (None, 0))
        self.assertEqual(Aru.angle_mismatch_rms([0], [0], [0], [0], 0.0), (None, 0))
        self.assertEqual(Aru.angle_mismatch_rms([], [], [0, 1], [0, 1], 0.0), (None, 0))

    def test_unsorted_nir_times(self):
        rms, count = Aru.angle_mismatch_rms([1.5], [15.0], [2.0, 1.0], [20.0, 10.0], 0.0)
        self.assertAlmostEqual(rms, 0.0)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
