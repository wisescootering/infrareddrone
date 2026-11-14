"""The OpenCV filters of the alignment give the values of the scikit-image ones they replace."""
import numpy as np
import pytest
from skimage import filters, transform

from registration.constants import LAPLACIAN_ENERGIES
from registration.cost import multispectral_representation
from registration.pyramid_wrapper import pyramid_gaussian, pyramid_reduce
from registration.rigid import compute_pyramid


@pytest.fixture
def image():
    return np.random.default_rng(0).random((151, 203, 4), dtype=np.float32)


@pytest.mark.parametrize("downscale", [2, 4, 32])
def test_pyramid_reduce_as_scikit_image(image, downscale):
    expected = transform.pyramid_reduce(image, downscale=downscale, channel_axis=-1)
    reduced = pyramid_reduce(image, downscale)
    assert reduced.dtype == np.float32 and reduced.shape == expected.shape
    np.testing.assert_allclose(reduced, expected, atol=1e-5)


def test_pyramid_reduce_keeps_a_single_channel_axis(image):
    assert pyramid_reduce(image[:, :, :1], 2).shape == (76, 102, 1)


def test_pyramid_gaussian_as_scikit_image(image):
    expected = list(transform.pyramid_gaussian(image, downscale=2, channel_axis=-1))
    levels = pyramid_gaussian(image, downscale=2)
    assert [level.shape for level in levels] == [level.shape for level in expected]
    for level, reference in zip(levels, expected):
        np.testing.assert_allclose(level, reference, atol=1e-5)
    assert len(pyramid_gaussian(image, downscale=2, max_layer=3)) == 4


def test_pyramid_of_an_8_bit_image_is_scaled_to_one():
    image = np.random.default_rng(1).integers(0, 256, (64, 80, 3), dtype=np.uint8)
    expected = list(transform.pyramid_gaussian(image, downscale=2, channel_axis=-1))
    for level, reference in zip(pyramid_gaussian(image, downscale=2), expected):
        np.testing.assert_allclose(level, reference, atol=1e-5)


def test_compute_pyramid_keeps_the_asked_scales(image):
    pyramid = compute_pyramid(image, [16, 4])
    assert sorted(pyramid) == [4, 16]
    assert pyramid[4].shape == (38, 51, 4) and pyramid[16].shape == (10, 13, 4)


@pytest.mark.parametrize("sigma", [None, 1., 3., 5.])
def test_laplacian_energies_as_scikit_image(sigma):
    image = (255 * np.random.default_rng(2).random((120, 160, 3))).astype(np.uint8)
    import cv2
    gray = cv2.cvtColor(image.astype(np.float32), cv2.COLOR_RGB2GRAY)
    if sigma is not None:
        gray = filters.gaussian(gray, sigma)
    expected = np.stack([
        filters.scharr_h(gray), filters.scharr_v(gray),
        filters.edges.roberts_pos_diag(gray), filters.edges.roberts_neg_diag(gray),
    ], axis=-1) ** 2
    energies = multispectral_representation(image, sigma_gaussian=sigma, mode=LAPLACIAN_ENERGIES)
    assert energies.dtype == np.float32 and energies.shape == (120, 160, 4)
    np.testing.assert_allclose(energies, expected, rtol=1e-3, atol=1e-3 * expected.max())


def test_hessian_determinant_as_the_quadric_fit_of_each_position():
    from registration.newton import quadric_approximation
    from registration.rigid import hessian_determinant, minimum_cost_max_hessian
    rng = np.random.default_rng(3)
    cost = rng.random((15, 17, 4))
    determinant = hessian_determinant(cost[:, :, -1])
    expected = np.zeros((15, 17))
    for y in range(2, 13):
        for x in range(2, 15):
            hessian, _, _ = quadric_approximation(cost[y-1:y+2, x-1:x+2])
            expected[y, x] = np.linalg.det(hessian[-1])
    np.testing.assert_allclose(determinant, expected, atol=1e-12)
    # a cost with one clear minimum: found with its sub-pixel position
    yy, xx = np.mgrid[-10:11, -12:13]
    bowl = 1. - np.exp(-((xx - 3.3)**2 + (yy + 2.6)**2) / 8.)
    displacement = minimum_cost_max_hessian(np.repeat(bowl[:, :, np.newaxis], 4, axis=-1))
    np.testing.assert_allclose(displacement, [3.3, -2.6], atol=0.15)


@pytest.mark.parametrize("blocks, padding", [(5, (39, 29)), (4, None), (2, None), (7, (3, 5))])
def test_vector_field_maps_as_the_spline_evaluated_everywhere(blocks, padding):
    """The remap of a sparse vector field is the bisplrep / bisplev surface it always was."""
    import warnings
    from scipy.interpolate import bisplev, bisplrep
    from registration.warp_flow import warp_from_sparse_vector_field
    height, width = 359, 479
    field = np.random.default_rng(4).normal(0, 3, (blocks, blocks, 2))
    map_x, map_y = warp_from_sparse_vector_field(np.empty((height, width)), field, get_remap=True, padding=padding)
    assert map_x.dtype == np.float32 and map_x.shape == (height, width) == map_y.shape
    pad_x, pad_y = padding or (0, 0)
    size_x, size_y = (width - 2*pad_x) // blocks, (height - 2*pad_y) // blocks
    centers_x = [pad_x + (x + 0.5)*size_x for _ in range(blocks) for x in range(blocks)]
    centers_y = [pad_y + (y + 0.5)*size_y for y in range(blocks) for _ in range(blocks)]
    x, y = np.linspace(0, width, width), np.linspace(0, height, height)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected_x = x[np.newaxis, :] + bisplev(x, y, bisplrep(centers_x, centers_y, -field[:, :, 0].ravel(), kx=1, ky=1, s=0.)).T
        expected_y = y[:, np.newaxis] + bisplev(x, y, bisplrep(centers_x, centers_y, -field[:, :, 1].ravel(), kx=1, ky=1, s=0.)).T
    np.testing.assert_allclose(map_x, expected_x, atol=2e-4)
    np.testing.assert_allclose(map_y, expected_y, atol=2e-4)


@pytest.mark.parametrize("with_field", [True, False])
def test_warp_of_a_crop_is_the_crop_of_the_warp(with_field):
    from registration.warp_flow import warp
    rng = np.random.default_rng(5)
    image = rng.random((120, 160, 3), dtype=np.float32)
    calibration = {"mtx": np.array([[150., 0., 80.], [0., 150., 60.], [0., 0., 1.]]),
                   "dist": np.array([-0.1, 0.02, 0., 0., 0.])}
    homography = np.array([[1.01, 0.01, 20.], [-0.01, 0.99, 15.], [1e-5, 0., 1.]])
    field = rng.normal(0, 2, (5, 5, 2)) if with_field else None
    padding = (20, 15) if with_field else None
    whole = warp(image, calibration, homography, outsize=(200, 150), vector_field=field, padding=padding)
    part = warp(image, calibration, homography, outsize=(200, 150), vector_field=field, padding=padding,
                crop=(20, 15, 160, 120))
    assert part.shape == (120, 160, 3)
    np.testing.assert_array_equal(part, whole[15:135, 20:180])
