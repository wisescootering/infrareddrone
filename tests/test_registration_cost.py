"""The fast cost surfaces give the same values as the direct formulas."""
import numpy as np
import pytest

from registration.constants import NTG, SSD
from registration.cost import compute_cost_surfaces, cost_surface_NTG, cost_surface_SSD


def reference_ntg(patch_ref, patch_mov_search, search_y, search_x):
    """Sobel of the difference at each shift (the former implementation)."""
    h, w, c_s = patch_mov_search.shape
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for v in range(2*search_y+1):
        for u in range(2*search_x+1):
            for ch in range(c_s):
                diff = (patch_mov_search[:, :, ch] - patch_ref[v:v+h, u:u+w, ch]).astype(np.float64)
                sobel_ = diff[:, 2:] - diff[:, :-2]
                sobel_v = sobel_[:-2] + sobel_[2:] + 2*sobel_[1:-1]
                sobel_ = diff[2:, :] - diff[:-2, :]
                sobel_h = sobel_[:, :-2] + sobel_[:, 2:] + 2*sobel_[:, 1:-1]
                cost[v, u, ch] = np.abs(sobel_v).sum() + np.abs(sobel_h).sum()
    return cost


def reference_ssd(patch_ref, patch_mov_search, search_y, search_x):
    h, w, c_s = patch_mov_search.shape
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for v in range(2*search_y+1):
        for u in range(2*search_x+1):
            diff = (patch_mov_search - patch_ref[v:v+h, u:u+w]).astype(np.float64)
            cost[v, u] = (diff**2).sum(axis=(0, 1))
    return cost


@pytest.fixture
def patches():
    rng = np.random.default_rng(0)
    search_y, search_x = 3, 5
    ref = rng.random((40, 52, 4), dtype=np.float32)
    mov = rng.random((40, 52, 4), dtype=np.float32)
    return ref, mov, search_y, search_x


def test_ntg_cost_surface_matches_the_direct_formula(patches):
    ref, mov, search_y, search_x = patches
    mov_search = mov[search_y:-search_y, search_x:-search_x]
    cost = cost_surface_NTG(ref, np.ascontiguousarray(mov_search), search_y, search_x)
    assert cost.shape == (2*search_y+1, 2*search_x+1, 4)
    np.testing.assert_allclose(cost, reference_ntg(ref, mov_search, search_y, search_x), rtol=1e-5)


def test_ssd_cost_surface_matches_the_direct_formula(patches):
    ref, mov, search_y, search_x = patches
    mov_search = mov[search_y:-search_y, search_x:-search_x]
    cost = cost_surface_SSD(ref, np.ascontiguousarray(mov_search), search_y, search_x)
    np.testing.assert_allclose(cost, reference_ssd(ref, mov_search, search_y, search_x), rtol=1e-5)


@pytest.mark.parametrize("dist_mode", [NTG, SSD])
def test_cost_surfaces_find_a_known_shift(dist_mode):
    """The moving image is the reference moved by (dx, dy) = (2, -1): each
    patch has its lowest cost at that shift."""
    rng = np.random.default_rng(1)
    ref = rng.random((90, 120, 2)).astype(np.float32)
    dx, dy = 2, -1
    mov = np.roll(ref, (-dy, -dx), axis=(0, 1))
    search = 4
    costs, centers, coords = compute_cost_surfaces(
        ref, mov, y_n=2, x_n=3, search_y=search, search_x=search, dist_mode=dist_mode)
    assert costs.shape == (2, 3, 2*search+1, 2*search+1, 2)
    assert centers.shape == (2, 3, 2) and coords.shape == (2, 3, 4)
    for y_id in range(2):
        for x_id in range(3):
            total = costs[y_id, x_id].sum(axis=-1)
            v, u = np.unravel_index(np.argmin(total), total.shape)
            assert (u - search, v - search) == (dx, dy)
