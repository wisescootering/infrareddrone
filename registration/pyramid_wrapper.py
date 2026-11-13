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


def _reduce_weights(size, out_size, sigma):
    """Weights (out_size, size) of a Gaussian filter (sigma, truncated at
    4 sigma, mirrored borders) followed by the bilinear resize from ``size``
    to ``out_size`` pixels, as (first source index of each output pixel,
    weights (out_size, taps)) once the mirrored indices are folded back."""
    radius = int(4. * sigma + 0.5)
    kernel = cv2.getGaussianKernel(2 * radius + 1, sigma, cv2.CV_64F).ravel()
    # Bilinear resize of OpenCV: output pixel i reads source position (i + 0.5) * scale - 0.5
    position = (np.arange(out_size) + 0.5) * (size / out_size) - 0.5
    first = np.floor(position).astype(np.int64)
    fraction = position - first
    fraction[first < 0] = 0.
    first = np.clip(first, 0, size - 1)
    second = np.clip(first + 1, 0, size - 1)
    weights = np.zeros((out_size, size))
    taps = np.arange(-radius, radius + 1)
    rows = np.arange(out_size)[:, np.newaxis]
    for center, share in ((first, 1. - fraction), (second, fraction)):
        index = center[:, np.newaxis] + taps[np.newaxis, :]
        # mirrored border (BORDER_REFLECT): -1 -> 0, -2 -> 1, size -> size - 1, ...
        index = np.where(index < 0, -index - 1, index)
        index = np.where(index >= size, 2 * size - 1 - index, index)
        np.add.at(weights, (rows, index), share[:, np.newaxis] * kernel[np.newaxis, :])
    start = np.clip(first - radius, 0, max(0, size - (2 * radius + 2)))
    width = min(size, 2 * radius + 2)
    window = start[:, np.newaxis] + np.arange(width)[np.newaxis, :]
    return start, np.take_along_axis(weights, window, axis=1).astype(np.float32)


def _reduce_sparse(img, downscale):
    """pyramid_reduce computed only where the reduced image is sampled: the
    Gaussian filter and the bilinear resize are both linear, they are merged
    into one small filter per output row and per output column. Same result as
    filtering the whole image, without filtering the pixels that the resize
    then drops (downscale 32: 1 filtered row out of 16)."""
    sigma = 2. * downscale / 6.
    height, width = img.shape[:2]
    out_height, out_width = math.ceil(height / downscale), math.ceil(width / downscale)
    flat = img.reshape(height, -1)
    start, weights = _reduce_weights(height, out_height, sigma)
    rows = np.empty((out_height, flat.shape[1]), dtype=np.float32)
    for index in range(out_height):
        np.dot(weights[index], flat[start[index]:start[index] + weights.shape[1]], out=rows[index])
    rows = rows.reshape((out_height, width) + img.shape[2:])
    start, weights = _reduce_weights(width, out_width, sigma)
    out = np.empty((out_height, out_width) + img.shape[2:], dtype=np.float32)
    for index in range(out_width):
        window = rows[:, start[index]:start[index] + weights.shape[1]]
        out[:, index] = np.tensordot(window, weights[index], axes=([1], [0]))
    return out


def pyramid_reduce(img, downscale):
    img = _as_float32(img)
    if downscale >= 8 and min(img.shape[:2]) > 16 * downscale:
        return _reduce_sparse(np.ascontiguousarray(img), downscale)
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
