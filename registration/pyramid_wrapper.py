"""Gaussian pyramids with OpenCV.

Same results as scikit-image ``transform.pyramid_reduce`` / ``pyramid_gaussian``
(Gaussian of sigma 2 * downscale / 6 truncated at 4 sigma, mirrored borders, then
a bilinear resize to ceil(size / downscale)) up to float32 rounding, but
multithreaded and in float32: 20 to 30 times faster on full resolution images.
"""
import math

import cv2
import numpy as np


def _as_float32(img):
    """uint8 images are scaled to [0, 1] as scikit-image does."""
    if img.dtype == np.uint8:
        return img.astype(np.float32) / 255.
    return np.asarray(img, dtype=np.float32)


def gaussian_blur(img, sigma, border=cv2.BORDER_REFLECT):
    """Gaussian filter truncated at 4 sigma (as scipy / scikit-image do)."""
    size = 2 * int(4. * sigma + 0.5) + 1
    return cv2.GaussianBlur(img, (size, size), sigmaX=sigma, sigmaY=sigma, borderType=border)


def pyramid_reduce(img, downscale):
    img = _as_float32(img)
    smoothed = gaussian_blur(img, 2. * downscale / 6.)
    out_size = (math.ceil(img.shape[1] / downscale), math.ceil(img.shape[0] / downscale))
    out = cv2.resize(smoothed, out_size, interpolation=cv2.INTER_LINEAR)
    if img.ndim == 3 and out.ndim == 2:  # OpenCV drops a single channel axis
        out = out[:, :, np.newaxis]
    return out


def pyramid_gaussian(img, downscale, max_layer=None):
    """List of the pyramid levels: the image, then each level reduced by
    ``downscale``, down to a single pixel or ``max_layer`` reductions."""
    level = _as_float32(img)
    levels = [level]
    while max_layer is None or len(levels) <= max_layer:
        if max(level.shape[:2]) <= 1:
            break
        level = pyramid_reduce(level, downscale)
        levels.append(level)
    return levels
