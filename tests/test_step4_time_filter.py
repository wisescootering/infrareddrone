import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_after_preprocessing import (
    filter_shoot_points_by_image_number,
    filter_shoot_points_by_time_difference,
)


class ShootPointTimeFilterTests(unittest.TestCase):
    def test_image_number_range_is_inclusive_and_independent_of_list_indexes(self):
        points = [
            {"VIS": {"FileName": f"VIS_{number:04d}.dng"}}
            for number in (49, 50, 51, 54, 55)
        ]

        filtered = filter_shoot_points_by_image_number(points, 50, 54)

        self.assertEqual(
            [point["VIS"]["FileName"] for point in filtered],
            ["VIS_0050.dng", "VIS_0051.dng", "VIS_0054.dng"],
        )

    def test_keeps_only_rank_one_pairs_strictly_inside_threshold(self):
        points = [
            {
                "VIS": {"FileName": "VIS_0001.dng"},
                "NIR": [{"rank": 1, "dt": -0.49}],
            },
            {
                "VIS": {"FileName": "VIS_0002.dng"},
                "NIR": [{"rank": 1, "dt": 0.5}],
            },
            {
                "VIS": {"FileName": "VIS_0003.dng"},
                "NIR": [
                    {"rank": 2, "dt": 0.01},
                    {"rank": 1, "dt": -0.3},
                ],
            },
            {
                "VIS": {"FileName": "VIS_0004.dng"},
                "NIR": [{"rank": 2, "dt": 0.1}],
            },
        ]

        filtered = filter_shoot_points_by_time_difference(points, 0.5)

        self.assertEqual(
            [point["VIS"]["FileName"] for point in filtered],
            ["VIS_0001.dng", "VIS_0003.dng"],
        )

    def test_rejects_invalid_time_threshold(self):
        with self.assertRaisesRegex(ValueError, "between 0.1 and 6.0"):
            filter_shoot_points_by_time_difference([], 6.1)

    def test_reports_missing_rank_one_time_difference(self):
        points = [
            {
                "VIS": {"FileName": "VIS_0001.dng"},
                "NIR": [{"rank": 1}],
            }
        ]

        with self.assertRaisesRegex(ValueError, "VIS_0001.dng"):
            filter_shoot_points_by_time_difference(points, 0.5)


if __name__ == "__main__":
    unittest.main()
