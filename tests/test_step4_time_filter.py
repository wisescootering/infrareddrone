import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_after_preprocessing import (
    filter_shoot_points_best_mapping,
    filter_shoot_points_by_image_number,
    filter_shoot_points_by_time_difference,
)


def flying_point(number, north_m, dt):
    lat = 45.0 + north_m / 111195.0
    return {
        "VIS": {"FileName": f"VIS_{number:04d}.dng", "DroneLatitude": lat, "DroneLongitude": 3.0,
                "DroneAltitudeGround": 100.0, "GimbalYawDegree": 0.0},
        "NIR": [{"rank": 1, "dt": dt}],
    }


class ShootPointBestMappingTests(unittest.TestCase):
    def test_keeps_a_subset_of_the_synchronized_points_only(self):
        points = [flying_point(n, 3.0 * n, 0.1 if n % 4 else 0.8) for n in range(1, 81)]
        synchronized = filter_shoot_points_by_time_difference(points, 0.5)

        kept = filter_shoot_points_best_mapping(points, synchronized, 0.75)

        self.assertTrue(kept)
        self.assertLess(len(kept), len(synchronized) // 3)
        self.assertTrue(all(any(point is s for s in synchronized) for point in kept))
        self.assertIs(kept[0], synchronized[0])
        self.assertIs(kept[-1], synchronized[-1])

    def test_overlap_in_percent_is_accepted(self):
        points = [flying_point(n, 3.0 * n, 0.1) for n in range(1, 41)]
        self.assertEqual(
            filter_shoot_points_best_mapping(points, points, 80),
            filter_shoot_points_best_mapping(points, points, 0.8),
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
