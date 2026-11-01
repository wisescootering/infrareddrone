import unittest
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from irdrone.ign_registration import (
    RegistrationConfig,
    _assess_similarity_fit,
    _registered_transform,
    _write_registered_copy,
    discover_geotiffs,
    register_geotiff,
)


class RegistrationFitTests(unittest.TestCase):
    def test_similarity_fit_requires_broad_spatial_support(self):
        x, y = np.meshgrid(np.linspace(100, 900, 8), np.linspace(100, 900, 8))
        source_points = np.column_stack((x.ravel(), y.ravel())).astype(np.float32)
        angle = np.deg2rad(12)
        scale = 0.95
        matrix = np.array(
            [
                [scale * np.cos(angle), -scale * np.sin(angle), 80],
                [scale * np.sin(angle), scale * np.cos(angle), -30],
            ],
            dtype=np.float32,
        )
        reference_points = source_points @ matrix[:, :2].T + matrix[:, 2]

        fitted, inliers, metrics, reasons = _assess_similarity_fit(
            source_points,
            reference_points,
            1000,
            1000,
            RegistrationConfig(matcher="sift"),
        )

        self.assertTrue(inliers.all())
        self.assertEqual(reasons, [])
        self.assertAlmostEqual(metrics["rotation_degrees"], 12.0, places=2)
        np.testing.assert_allclose(fitted, matrix, atol=1e-4)

    def test_clustered_matches_are_rejected(self):
        x, y = np.meshgrid(np.linspace(100, 900, 8), np.linspace(50, 190, 4))
        source_points = np.column_stack((x.ravel(), y.ravel())).astype(np.float32)
        reference_points = source_points + np.array([20, 30], dtype=np.float32)

        _, inliers, metrics, reasons = _assess_similarity_fit(
            source_points,
            reference_points,
            1000,
            1000,
            RegistrationConfig(matcher="sift"),
        )

        self.assertTrue(inliers.all())
        self.assertLess(metrics["coverage_height"], 0.20)
        self.assertGreaterEqual(len(reasons), 1)

    def test_registered_transform_maps_pixel_centers(self):
        source_points = np.array(
            [[100, 100], [800, 100], [100, 800], [800, 800], [500, 400]],
            dtype=np.float32,
        )
        matrix = np.array([[1, 0, 20], [0, 1, 30]], dtype=np.float32)
        inliers = np.ones(len(source_points), dtype=bool)
        reference_transform = Affine(0.2, 0, 1000, 0, -0.2, 2000)

        result = _registered_transform(
            source_points,
            matrix,
            inliers,
            reference_transform,
            rasterio.crs.CRS.from_epsg(32631),
            rasterio.crs.CRS.from_epsg(32631),
        )

        source_corner = (source_points[0, 0] + 0.5, source_points[0, 1] + 0.5)
        reference_center = matrix[:, :2] @ source_points[0] + matrix[:, 2] + 0.5
        expected = reference_transform * tuple(reference_center)
        actual = result * tuple(source_corner)
        np.testing.assert_allclose(actual, expected, atol=1e-6)


class DiscoveryTests(unittest.TestCase):
    def test_discovery_uses_configured_geotiff_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VIS_0001_georef.tif").touch()
            (root / "VIS_0001_ign_aligned.tif").touch()
            (root / "VIS_0002.tiff").touch()
            matches = discover_geotiffs(root)
            self.assertEqual([path.name for path in matches], ["VIS_0001_georef.tif"])

    def test_existing_report_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            output_dir.mkdir()
            report_path = output_dir / "source_ign_report.json"
            report_path.write_text("preserve this report", encoding="utf-8")

            result = register_geotiff(root / "source.tif", output_dir)

            self.assertFalse(result.accepted)
            self.assertIsNone(result.report)
            self.assertEqual(report_path.read_text(encoding="utf-8"), "preserve this report")

    def test_registered_copy_preserves_pixels_and_updates_transform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.tif"
            output_path = root / "registered.tif"
            original_pixels = np.arange(3 * 8 * 9, dtype=np.uint8).reshape(3, 8, 9)
            original_transform = Affine(0.1, 0, 500000, 0, -0.1, 5000000)
            new_transform = Affine(0.09, 0.01, 500001, -0.01, -0.09, 5000002)
            with rasterio.open(
                source_path,
                "w",
                driver="GTiff",
                width=9,
                height=8,
                count=3,
                dtype="uint8",
                crs="EPSG:32631",
                transform=original_transform,
            ) as source:
                source.write(original_pixels)

            _write_registered_copy(
                source_path,
                output_path,
                new_transform,
                {
                    "inlier_count": 30,
                    "inlier_rmse_reference_px": 1.2,
                    "coverage_width": 0.7,
                    "coverage_height": 0.6,
                },
                "test matcher",
            )

            with rasterio.open(output_path) as registered:
                np.testing.assert_array_equal(registered.read(), original_pixels)
                self.assertEqual(registered.crs.to_epsg(), 32631)
                self.assertEqual(registered.transform, new_transform)
                self.assertEqual(registered.tags()["IGN_REGISTRATION_METHOD"], "test matcher")
            self.assertEqual({path.name for path in root.iterdir()}, {"source.tif", "registered.tif"})


if __name__ == "__main__":
    unittest.main()
