"""Register georeferenced GeoTIFFs against IGN orthophoto imagery."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_bounds
from rasterio.warp import transform, transform_bounds


LOGGER = logging.getLogger("ign_registration")
DEFAULT_WMS_URL = "https://data.geopf.fr/wms-r"
DEFAULT_LAYER = "HR.ORTHOIMAGERY.ORTHOPHOTOS"


@dataclass
class RegistrationConfig:
    """Configuration for an IGN orthophoto registration run."""

    matcher: str = "auto"
    device: str = "auto"
    wms_url: str = DEFAULT_WMS_URL
    layer: str = DEFAULT_LAYER
    search_margin_m: float = 40.0
    reference_resolution_m: float = 0.15
    max_reference_dimension: int = 2048
    max_feature_dimension: int = 1200
    max_keypoints: int = 4096
    ransac_threshold_px: float = 4.0
    min_inliers: int = 20
    min_inlier_ratio: float = 0.20
    min_coverage: float = 0.20
    min_occupied_quadrants: int = 3
    max_rmse_px: float = 3.0
    timeout_s: float = 45.0

    def __post_init__(self) -> None:
        if self.matcher not in {"auto", "lightglue", "sift"}:
            raise ValueError("matcher must be 'auto', 'lightglue', or 'sift'")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be 'auto', 'cpu', or 'cuda'")
        if self.search_margin_m < 0 or self.reference_resolution_m <= 0:
            raise ValueError("Search margin must be non-negative and resolution positive")
        if self.max_reference_dimension < 256 or self.max_feature_dimension < 256:
            raise ValueError("Image dimensions must be at least 256 pixels")
        if self.max_keypoints < 100 or self.min_inliers < 3:
            raise ValueError("At least 100 keypoints and 3 inliers must be allowed")
        if not 0 < self.min_inlier_ratio <= 1:
            raise ValueError("min_inlier_ratio must be in (0, 1]")
        if not 0 < self.min_coverage <= 1:
            raise ValueError("min_coverage must be in (0, 1]")
        if not 1 <= self.min_occupied_quadrants <= 4:
            raise ValueError("min_occupied_quadrants must be between 1 and 4")


@dataclass
class RegistrationResult:
    """Per-image registration summary."""

    source: str
    accepted: bool
    message: str
    matcher: Optional[str] = None
    output: Optional[str] = None
    preview: Optional[str] = None
    report: Optional[str] = None
    metrics: Optional[Dict[str, object]] = None


def _image_rgb(dataset: rasterio.io.DatasetReader, max_dimension: int) -> Tuple[np.ndarray, np.ndarray]:
    """Read a bounded-size RGB representation and a mask of valid pixels."""
    if dataset.count >= 3:
        color_indices = {
            color: index + 1
            for index, color in enumerate(dataset.colorinterp)
            if color in {ColorInterp.red, ColorInterp.green, ColorInterp.blue}
        }
        if all(color in color_indices for color in (ColorInterp.red, ColorInterp.green, ColorInterp.blue)):
            indexes = [color_indices[ColorInterp.red], color_indices[ColorInterp.green], color_indices[ColorInterp.blue]]
        else:
            indexes = [1, 2, 3]
    else:
        indexes = [1]

    scale = min(1.0, max_dimension / max(dataset.width, dataset.height))
    width = max(1, round(dataset.width * scale))
    height = max(1, round(dataset.height * scale))
    bands = dataset.read(
        indexes,
        out_shape=(len(indexes), height, width),
        resampling=Resampling.bilinear,
    )
    if bands.shape[0] == 1:
        bands = np.repeat(bands, 3, axis=0)

    rgb = np.empty((height, width, 3), dtype=np.uint8)
    for index, band in enumerate(bands[:3]):
        if band.dtype == np.uint8:
            rgb[..., index] = band
            continue
        finite = np.isfinite(band)
        if not finite.any():
            rgb[..., index] = 0
            continue
        low, high = np.percentile(band[finite], (2, 98))
        if high <= low:
            rgb[..., index] = 0
            continue
        scaled = (np.nan_to_num(band, nan=low) - low) * (255.0 / (high - low))
        rgb[..., index] = np.clip(scaled, 0, 255).astype(np.uint8)

    valid_mask = np.any(rgb > 0, axis=2).astype(np.uint8) * 255
    return rgb, valid_mask


def _gray(rgb: np.ndarray, max_dimension: int) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float]]:
    """Convert RGB to a bounded-size grayscale image and binary mask."""
    height, width = rgb.shape[:2]
    scale = min(1.0, max_dimension / max(width, height))
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    if (resized_width, resized_height) != (width, height):
        resized = cv2.resize(rgb, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    else:
        resized = rgb
    gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    mask = (np.max(resized, axis=2) > 0).astype(np.uint8) * 255
    return gray, mask, (resized_width / width, resized_height / height)


def _sift_matches(
    source_gray: np.ndarray,
    source_mask: np.ndarray,
    reference_gray: np.ndarray,
    reference_mask: np.ndarray,
    max_keypoints: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Find mutually consistent SIFT correspondences."""
    detector = cv2.SIFT_create(nfeatures=max_keypoints)
    source_keypoints, source_descriptors = detector.detectAndCompute(source_gray, source_mask)
    reference_keypoints, reference_descriptors = detector.detectAndCompute(reference_gray, reference_mask)
    if source_descriptors is None or reference_descriptors is None:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32)

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward = matcher.knnMatch(source_descriptors, reference_descriptors, k=2)
    reverse = matcher.knnMatch(reference_descriptors, source_descriptors, k=2)
    reverse_pairs = set()
    for pair in reverse:
        if len(pair) == 2 and pair[0].distance < 0.78 * pair[1].distance:
            reverse_pairs.add((pair[0].trainIdx, pair[0].queryIdx))

    source_points: List[Tuple[float, float]] = []
    reference_points: List[Tuple[float, float]] = []
    for pair in forward:
        if len(pair) != 2 or pair[0].distance >= 0.78 * pair[1].distance:
            continue
        match = pair[0]
        if (match.queryIdx, match.trainIdx) not in reverse_pairs:
            continue
        source_points.append(source_keypoints[match.queryIdx].pt)
        reference_points.append(reference_keypoints[match.trainIdx].pt)
    return np.asarray(source_points, np.float32).reshape(-1, 2), np.asarray(reference_points, np.float32).reshape(-1, 2)


def _lightglue_matches(
    source_gray: np.ndarray,
    reference_gray: np.ndarray,
    max_keypoints: int,
    device: str = "auto",
) -> Tuple[np.ndarray, np.ndarray]:
    """Find independent learned correspondences outside OpenCV's OpenMP process."""
    worker = """
import sys
import torch

torch.set_num_threads(1)
import numpy as np
from lightglue import ALIKED, LightGlue, SuperPoint
from kornia.feature import LoFTR

source_path, reference_path, output_path, device, keypoint_limit = sys.argv[1:]
source_image = np.load(source_path)["image"]
reference_image = np.load(reference_path)["image"]
if device == "auto":
    device = "cuda" if torch.cuda.is_available() else "cpu"
source_tensor = torch.from_numpy(source_image).float()[None, None].to(device) / 255.0
reference_tensor = torch.from_numpy(reference_image).float()[None, None].to(device) / 255.0

def lightglue_matches(extractor_class, feature_name):
    extractor = extractor_class(max_num_keypoints=int(keypoint_limit)).eval().to(device)
    matcher = LightGlue(features=feature_name).eval().to(device)
    with torch.inference_mode():
        features0 = extractor.extract(source_tensor)
        features1 = extractor.extract(reference_tensor)
        result = matcher({"image0": features0, "image1": features1})
    indices = result["matches"][0].detach().cpu().numpy()
    if not len(indices):
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2), dtype=np.float32)
    points0 = features0["keypoints"][0].detach().cpu().numpy()[indices[:, 0]]
    points1 = features1["keypoints"][0].detach().cpu().numpy()[indices[:, 1]]
    return points0.astype(np.float32), points1.astype(np.float32)

superpoint = lightglue_matches(SuperPoint, "superpoint")
aliked = lightglue_matches(ALIKED, "aliked")
loftr = LoFTR(pretrained="outdoor").eval().to(device)
with torch.inference_mode():
    loftr_result = loftr({"image0": source_tensor, "image1": reference_tensor})
loftr_source = loftr_result["keypoints0"].detach().cpu().numpy().astype(np.float32)
loftr_reference = loftr_result["keypoints1"].detach().cpu().numpy().astype(np.float32)
np.savez(
    output_path,
    sp_source=superpoint[0],
    sp_reference=superpoint[1],
    aliked_source=aliked[0],
    aliked_reference=aliked[1],
    loftr_source=loftr_source,
    loftr_reference=loftr_reference,
)
"""
    with tempfile.TemporaryDirectory(prefix="irdrone_lightglue_") as temporary_directory:
        temporary = Path(temporary_directory)
        source_path = temporary / "source.npz"
        reference_path = temporary / "reference.npz"
        output_path = temporary / "matches.npz"
        np.savez_compressed(source_path, image=source_gray)
        np.savez_compressed(reference_path, image=reference_gray)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    worker,
                    str(source_path),
                    str(reference_path),
                    str(output_path),
                    device,
                    str(max_keypoints),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
            raise RuntimeError(f"LightGlue worker failed: {detail[-2000:]}") from error
        if not output_path.is_file():
            raise RuntimeError(f"LightGlue worker returned no matches file: {completed.stderr[-2000:]}")
        with np.load(output_path) as matches:
            source_points = np.concatenate(
                (matches["sp_source"], matches["aliked_source"], matches["loftr_source"]),
                axis=0,
            ).astype(np.float32)
            reference_points = np.concatenate(
                (matches["sp_reference"], matches["aliked_reference"], matches["loftr_reference"]),
                axis=0,
            ).astype(np.float32)
            return source_points, reference_points


def _match_images(
    source_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    config: RegistrationConfig,
) -> Tuple[np.ndarray, np.ndarray, str, Tuple[float, float], Tuple[float, float]]:
    """Extract correspondences and return coordinates in full-resolution pixel units."""
    source_gray, source_mask, source_scale = _gray(source_rgb, config.max_feature_dimension)
    reference_gray, reference_mask, reference_scale = _gray(reference_rgb, config.max_feature_dimension)
    method = config.matcher

    if method in {"auto", "lightglue"}:
        try:
            source_points, reference_points = _lightglue_matches(
                source_gray,
                reference_gray,
                config.max_keypoints,
                config.device,
            )
            method = "SuperPoint/ALIKED-LightGlue + LoFTR consensus"
        except RuntimeError as error:
            if method == "lightglue":
                raise
            LOGGER.warning("LightGlue failed; falling back to SIFT (%s).", error)
            method = "sift"
    if method == "sift":
        source_points, reference_points = _sift_matches(
            source_gray,
            source_mask,
            reference_gray,
            reference_mask,
            config.max_keypoints,
        )
        method = "SIFT"

    source_points /= np.asarray(source_scale, dtype=np.float32)
    reference_points /= np.asarray(reference_scale, dtype=np.float32)
    return source_points, reference_points, method, source_scale, reference_scale


def _assess_similarity_fit(
    source_points: np.ndarray,
    reference_points: np.ndarray,
    source_width: int,
    source_height: int,
    config: RegistrationConfig,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, object], List[str]]:
    """Estimate a similarity transform and reject weak or spatially clustered matches."""
    if len(source_points) < config.min_inliers:
        raise ValueError(f"Only {len(source_points)} matches; need at least {config.min_inliers}.")
    cv2.setRNGSeed(42)
    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        source_points,
        reference_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=config.ransac_threshold_px,
        maxIters=100000,
        confidence=0.999,
        refineIters=100,
    )
    if matrix is None or inlier_mask is None:
        raise ValueError("RANSAC could not estimate a stable similarity transform.")

    inliers = inlier_mask.ravel().astype(bool)
    predicted = source_points @ matrix[:, :2].T + matrix[:, 2]
    residuals = np.linalg.norm(predicted - reference_points, axis=1)[inliers]
    support = source_points[inliers]
    coverage = np.ptp(support, axis=0) / np.asarray([source_width, source_height])
    quadrant_ids = (support[:, 0] >= source_width / 2).astype(int) + 2 * (
        support[:, 1] >= source_height / 2
    ).astype(int)
    occupied_quadrants = int(len(np.unique(quadrant_ids)))
    rmse = float(np.sqrt(np.mean(residuals**2))) if len(residuals) else math.inf
    metrics: Dict[str, object] = {
        "match_count": int(len(source_points)),
        "inlier_count": int(inliers.sum()),
        "inlier_ratio": float(inliers.mean()),
        "inlier_rmse_reference_px": rmse,
        "inlier_median_reference_px": float(np.median(residuals)) if len(residuals) else math.inf,
        "inlier_p90_reference_px": float(np.percentile(residuals, 90)) if len(residuals) else math.inf,
        "coverage_width": float(coverage[0]),
        "coverage_height": float(coverage[1]),
        "occupied_source_quadrants": occupied_quadrants,
        "rotation_degrees": float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))),
        "scale": float(math.hypot(matrix[0, 0], matrix[1, 0])),
        "source_to_reference_affine": matrix.tolist(),
    }
    reasons: List[str] = []
    if int(inliers.sum()) < config.min_inliers:
        reasons.append(f"Only {int(inliers.sum())} RANSAC inliers; need {config.min_inliers}.")
    if float(inliers.mean()) < config.min_inlier_ratio:
        reasons.append(f"Inlier ratio {inliers.mean():.3f} is below {config.min_inlier_ratio:.3f}.")
    if float(coverage[0]) < config.min_coverage or float(coverage[1]) < config.min_coverage:
        reasons.append(
            f"Spatial coverage {coverage[0]:.3f} x {coverage[1]:.3f} is below "
            f"{config.min_coverage:.3f} in at least one image dimension."
        )
    if occupied_quadrants < config.min_occupied_quadrants:
        reasons.append(
            f"Inliers cover {occupied_quadrants} source-image quadrants; "
            f"need {config.min_occupied_quadrants}."
        )
    if rmse > config.max_rmse_px:
        reasons.append(f"Inlier RMSE {rmse:.3f} px exceeds {config.max_rmse_px:.3f} px.")
    return matrix, inliers, metrics, reasons


def _registered_transform(
    source_points: np.ndarray,
    matrix: np.ndarray,
    inliers: np.ndarray,
    reference_transform: Affine,
    reference_crs: rasterio.crs.CRS,
    source_crs: rasterio.crs.CRS,
) -> Affine:
    """Fit a source-image affine geotransform from the inlier control points."""
    fitted_reference = source_points[inliers] @ matrix[:, :2].T + matrix[:, 2]
    reference_centers = fitted_reference + 0.5
    reference_x = (
        reference_transform.a * reference_centers[:, 0]
        + reference_transform.b * reference_centers[:, 1]
        + reference_transform.c
    )
    reference_y = (
        reference_transform.d * reference_centers[:, 0]
        + reference_transform.e * reference_centers[:, 1]
        + reference_transform.f
    )
    source_x, source_y = transform(
        reference_crs,
        source_crs,
        reference_x.tolist(),
        reference_y.tolist(),
    )
    source_centers = source_points[inliers] + 0.5
    design = np.column_stack((source_centers, np.ones(len(source_centers))))
    coefficients_x, _, rank_x, _ = np.linalg.lstsq(design, np.asarray(source_x), rcond=None)
    coefficients_y, _, rank_y, _ = np.linalg.lstsq(design, np.asarray(source_y), rcond=None)
    if rank_x < 3 or rank_y < 3:
        raise ValueError("Inlier controls do not span a two-dimensional affine transform.")
    return Affine(
        coefficients_x[0],
        coefficients_x[1],
        coefficients_x[2],
        coefficients_y[0],
        coefficients_y[1],
        coefficients_y[2],
    )


def _request_reference(
    source_crs: rasterio.crs.CRS,
    source_bounds: rasterio.coords.BoundingBox,
    config: RegistrationConfig,
) -> Tuple[np.ndarray, Affine, rasterio.crs.CRS, Dict[str, object]]:
    """Request a padded IGN orthophoto, retrying in Web Mercator when needed."""
    candidates: List[rasterio.crs.CRS] = []
    if source_crs.is_projected:
        candidates.append(source_crs)
    web_mercator = rasterio.crs.CRS.from_epsg(3857)
    if web_mercator not in candidates:
        candidates.append(web_mercator)

    errors: List[str] = []
    for reference_crs in candidates:
        try:
            if reference_crs == source_crs:
                bounds = tuple(source_bounds)
                unit_factor = reference_crs.linear_units_factor[1]
                margin = config.search_margin_m / unit_factor
                resolution = config.reference_resolution_m / unit_factor
            else:
                bounds = transform_bounds(
                    source_crs,
                    reference_crs,
                    *tuple(source_bounds),
                    densify_pts=21,
                )
                margin = config.search_margin_m
                resolution = config.reference_resolution_m
            left, bottom, right, top = bounds
            left -= margin
            bottom -= margin
            right += margin
            top += margin
            if not all(math.isfinite(value) for value in (left, bottom, right, top)) or right <= left or top <= bottom:
                raise ValueError(f"Invalid WMS bounds: {bounds}")

            width = max(64, round((right - left) / resolution))
            height = max(64, round((top - bottom) / resolution))
            resize = min(1.0, config.max_reference_dimension / max(width, height))
            width = max(64, round(width * resize))
            height = max(64, round(height * resize))
            params = {
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetMap",
                "LAYERS": config.layer,
                "STYLES": "",
                "CRS": reference_crs.to_string(),
                "BBOX": f"{left},{bottom},{right},{top}",
                "WIDTH": width,
                "HEIGHT": height,
                "FORMAT": "image/jpeg",
                "TRANSPARENT": "FALSE",
            }
            response = requests.get(config.wms_url, params=params, timeout=config.timeout_s)
            response.raise_for_status()
            image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"IGN returned a non-image response: {response.text[:300]}")
            reference_transform = from_bounds(left, bottom, right, top, width, height)
            details = {
                "url": response.url,
                "layer": config.layer,
                "crs": reference_crs.to_string(),
                "bounds": [left, bottom, right, top],
                "width": width,
                "height": height,
            }
            return cv2.cvtColor(image, cv2.COLOR_BGR2RGB), reference_transform, reference_crs, details
        except (requests.RequestException, ValueError, rasterio.errors.RasterioError) as error:
            errors.append(f"{reference_crs}: {error}")
    raise RuntimeError("IGN WMS request failed for all candidate CRSs: " + " | ".join(errors))


def _write_registered_copy(
    source_path: Path,
    output_path: Path,
    new_transform: Affine,
    metrics: Dict[str, object],
    method: str,
) -> None:
    """Write an unchanged pixel copy with updated georeferencing and provenance tags."""
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(source_path) as source:
                profile = source.profile.copy()
                profile.update(transform=new_transform)
                with tempfile.NamedTemporaryFile(
                    prefix=output_path.stem + "_",
                    suffix=".tif",
                    dir=output_path.parent,
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                with rasterio.open(temporary_path, "w", **profile) as destination:
                    for _, window in source.block_windows(1):
                        destination.write(source.read(window=window), window=window)
                        destination.write_mask(source.dataset_mask(window=window), window=window)
                    destination.update_tags(**source.tags())
                    destination.update_tags(
                        IGN_REGISTRATION_STATUS="Experimental IGN alignment; inspect before use",
                        IGN_REGISTRATION_METHOD=method,
                        IGN_REGISTRATION_INLIERS=str(metrics["inlier_count"]),
                        IGN_REGISTRATION_RMSE_REFERENCE_PIXELS=f"{metrics['inlier_rmse_reference_px']:.4f}",
                        IGN_REGISTRATION_COVERAGE=(
                            f"{metrics['coverage_width']:.3f} width x "
                            f"{metrics['coverage_height']:.3f} height"
                        ),
                    )
                    for band_index in range(1, source.count + 1):
                        tags = source.tags(band_index)
                        if tags:
                            destination.update_tags(band_index, **tags)
                        description = source.descriptions[band_index - 1]
                        if description:
                            destination.set_band_description(band_index, description)
                    destination.colorinterp = source.colorinterp
        os.link(temporary_path, output_path)
        temporary_path.unlink()
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _write_overlay(
    source_rgb: np.ndarray,
    reference_rgb: np.ndarray,
    matrix: np.ndarray,
    source_width: int,
    source_height: int,
    output_path: Path,
) -> None:
    """Save a half-opacity source/IGN overlay for visual quality control."""
    source_scale = np.array(
        [
            [source_width / source_rgb.shape[1], 0, 0],
            [0, source_height / source_rgb.shape[0], 0],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )
    preview_matrix = matrix @ source_scale
    height, width = reference_rgb.shape[:2]
    warped = cv2.warpAffine(
        source_rgb[..., ::-1],
        preview_matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    valid = np.max(warped, axis=2) > 0
    reference_bgr = reference_rgb[..., ::-1].copy()
    reference_bgr[valid] = cv2.addWeighted(reference_bgr[valid], 0.5, warped[valid], 0.5, 0)
    cv2.putText(
        reference_bgr,
        "IGN orthophoto + registered GeoTIFF (50% overlay)",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        reference_bgr,
        "Source image is unchanged; alignment is experimental",
        (12, height - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", reference_bgr)
    if not success:
        raise OSError(f"Could not write overlay: {output_path}")
    with output_path.open("xb") as output_file:
        output_file.write(encoded.tobytes())


def register_geotiff(
    source_path: Path,
    output_dir: Path,
    config: Optional[RegistrationConfig] = None,
) -> RegistrationResult:
    """Register one georeferenced GeoTIFF and save QC artifacts in a separate directory."""
    config = config or RegistrationConfig()
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_path = output_dir / f"{source_path.stem}_ign_aligned.tif"
    preview_path = output_dir / f"{source_path.stem}_ign_overlay.png"
    report_path = output_dir / f"{source_path.stem}_ign_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = RegistrationResult(
        source=str(source_path),
        accepted=False,
        message="Registration did not complete.",
        output=str(output_path),
        preview=str(preview_path),
        report=str(report_path),
    )
    report: Dict[str, object] = {
        "source": str(source_path),
        "config": asdict(config),
        "accepted": False,
        "limitations": [
            "An affine fit cannot model terrain relief, roof-height displacement, or temporal changes.",
            "Review the overlay and independent ground controls before using the result for measurement.",
        ],
    }
    if output_path.exists() or preview_path.exists() or report_path.exists():
        result.message = f"Refusing to overwrite existing registration artifacts in {output_dir}."
        result.report = None
        LOGGER.error("%s: %s", source_path, result.message)
        return result
    try:
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with rasterio.open(source_path) as source:
            if source.crs is None:
                raise ValueError("Input GeoTIFF has no CRS; registration requires an existing georeference.")
            if not source.crs.is_projected:
                LOGGER.info("%s uses a geographic CRS; the IGN request will use EPSG:3857.", source_path.name)
            source_rgb, _ = _image_rgb(source, config.max_feature_dimension)
            source_width, source_height = source.width, source.height
            source_crs = source.crs
            source_bounds = source.bounds
        report["input_crs"] = source_crs.to_string()

        reference_rgb, reference_transform, reference_crs, wms_details = _request_reference(
            source_crs,
            source_bounds,
            config,
        )
        report["wms"] = wms_details
        source_points, reference_points, method, _, _ = _match_images(source_rgb, reference_rgb, config)
        result.matcher = method
        report["matcher"] = method
        report["candidate_match_count"] = int(len(source_points))
        matrix, inliers, metrics, rejection_reasons = _assess_similarity_fit(
            source_points,
            reference_points,
            source_width,
            source_height,
            config,
        )
        metrics["wms"] = wms_details
        new_transform = _registered_transform(
            source_points,
            matrix,
            inliers,
            reference_transform,
            reference_crs,
            source_crs,
        )
        result.metrics = metrics
        _write_overlay(
            source_rgb,
            reference_rgb,
            matrix,
            source_width,
            source_height,
            preview_path,
        )
        if rejection_reasons:
            result.message = "Rejected: " + " ".join(rejection_reasons)
        else:
            _write_registered_copy(source_path, output_path, new_transform, metrics, method)
            result.accepted = True
            result.message = "Accepted for visual review; the original file was not modified."
            report["registered_transform"] = list(new_transform)[:6]
        report.update(
            {
                "accepted": result.accepted,
                "message": result.message,
                "matcher": method,
                "metrics": metrics,
                "preview": str(preview_path),
                "output": str(output_path) if result.accepted else None,
            }
        )
    except Exception as error:
        result.message = f"{type(error).__name__}: {error}"
        report["message"] = result.message
        LOGGER.error("%s: %s", source_path, result.message)
    with report_path.open("x", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)
    return result


def discover_geotiffs(input_path: Path, pattern: str = "*_georef.tif") -> List[Path]:
    """Find georeferenced TIFFs without including generated registration outputs."""
    input_path = Path(input_path)
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(input_path)
    candidates = sorted(
        path
        for path in input_path.rglob(pattern)
        if path.suffix.lower() in {".tif", ".tiff"}
        and not path.stem.endswith(("_ign_aligned", "_IGN_affine"))
    )
    return candidates


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run registration for a GeoTIFF or a directory tree."""
    parser = argparse.ArgumentParser(
        description="Align georeferenced GeoTIFFs to the IGN orthophoto WMS."
    )
    parser.add_argument("input", type=Path, help="GeoTIFF path or directory to scan recursively.")
    parser.add_argument("--output-dir", type=Path, help="Separate directory for aligned rasters and QC files.")
    parser.add_argument("--pattern", default="*_georef.tif", help="TIFF glob used when input is a directory.")
    parser.add_argument("--matcher", choices=("auto", "lightglue", "sift"), default="auto")
    parser.add_argument("--margin-m", type=float, default=40.0, help="WMS search margin around the source footprint.")
    parser.add_argument("--reference-resolution-m", type=float, default=0.15)
    parser.add_argument("--max-feature-dimension", type=int, default=1200)
    parser.add_argument("--min-coverage", type=float, default=0.20)
    parser.add_argument("--min-inliers", type=int, default=20)
    parser.add_argument("--max-rmse-px", type=float, default=3.0)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        paths = discover_geotiffs(args.input, args.pattern)
    except (FileNotFoundError, OSError, ValueError) as error:
        parser.error(str(error))
    if not paths:
        LOGGER.error("No GeoTIFFs matched %r under %s.", args.pattern, args.input)
        return 1

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = (args.input if args.input.is_dir() else args.input.parent) / "ign_registration"
    config = RegistrationConfig(
        matcher=args.matcher,
        device=args.device,
        search_margin_m=args.margin_m,
        reference_resolution_m=args.reference_resolution_m,
        max_feature_dimension=args.max_feature_dimension,
        min_coverage=args.min_coverage,
        min_inliers=args.min_inliers,
        max_rmse_px=args.max_rmse_px,
    )
    results = []
    for path in paths:
        result = register_geotiff(path, output_dir, config)
        results.append(result)
        status = "OK" if result.accepted else "NOT ACCEPTED"
        print(f"{status}: {path.name} - {result.message}")
    accepted = sum(result.accepted for result in results)
    print(f"Completed {len(results)} image(s): {accepted} accepted for review, {len(results) - accepted} rejected.")
    return 0 if accepted == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
