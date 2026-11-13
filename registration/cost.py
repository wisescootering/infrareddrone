import cv2
import numpy as np
import os.path as osp
import sys
sys.path.append(osp.join(osp.dirname(__file__), ".."))
from irdrone.utils import c2g, g2c
from numba import jit

import logging
import irdrone.process as pr
from registration.constants import LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED, SSD, NTG
from registration.pyramid_wrapper import pyramid_reduce, gaussian_blur

ROBERTS_POS_DIAG = np.array([[1, 0], [0, -1]], dtype=np.float32)
ROBERTS_NEG_DIAG = np.array([[0, 1], [-1, 0]], dtype=np.float32)

class AlignmentConfig:
    def __init__(self, mode=LAPLACIAN_ENERGIES, dist_mode=NTG, downscale=1, sigma_ref=None, sigma_mov=None, num_patches = 5, search_size=6):
        self.mode = mode
        self.dist_mode = dist_mode
        self.downscale = downscale
        self.sigma_ref = sigma_ref
        self.sigma_mov = sigma_mov
        self.search_size = search_size
        self.num_patches = num_patches
        self.y_n = num_patches
        self.x_n = num_patches
        self.search_x = search_size
        self.search_y = search_size

# --------------------------------------------------- Helpers ----------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------
def g2ci(ms_img):
    avg = np.average(ms_img)
    return g2c((255*(ms_img*0.5/avg).clip(0, 1)).astype(np.uint8))


def viz_laplacian_energy(ms_img):
    avg = np.average(ms_img)
    out = (255*(ms_img[:, :, :3]*0.5/avg).clip(0, 1)).astype(np.uint8)
    return out


def representation_visualization(rep):
    if rep.shape[-1] == 4:
        mode = LAPLACIAN_ENERGIES 
        ttl = "Directional energies"
        viz = [
            (g2ci(rep[:, :, 0]), "-"), (g2ci(rep[:, :, 1]), "|"),
            (g2ci(rep[:, :, 2]), "/"), (g2ci(rep[:, :, 3]), "\\")
        ]
        viz+= [(viz_laplacian_energy(rep), "Energies")]
    elif rep.shape[-1] == 1:
        mode = ttl = GRAY_SCALE
        viz =  [(g2ci(rep[:, :, 0]), ttl)]
    elif rep.shape[-1] == 3:
        mode = ttl = COLORED
        viz =  [(rep, "Colored")]
    ttl += f"{rep.shape}"
    return viz, mode, ttl


def representation_visualization_pairs(ref, mov, ref_orig=None, mov_orig=None, debug_fig=None, title="", **kwargs):
    """
    Support various modes of plotting the images depending on the representation mode
    """
    
    viz_ref, mode, ttl  = representation_visualization(ref)
    if ref_orig is not None:
        viz_ref+= [(ref_orig.data, "VIS")]
    viz_mov, _, _ = representation_visualization(mov)
    if ref_orig is not None:
        viz_mov+= [(mov_orig.data, "NIR")]
    viz = [viz_ref, viz_mov]
    debug_fig = None if debug_fig is None else (debug_fig + "inputs_"+mode+".png")
    pr.show(
        viz,
        suptitle=title+ttl,
        save=debug_fig,
        **kwargs
    )


# --------------------------------------------------- Representations --------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------
def multispectral_representation(_img, sigma_gaussian=None, mode=LAPLACIAN_ENERGIES):
    """Laplacian Energy , Gray scales, Colors
    """
    img = _img if isinstance(_img, np.ndarray) else _img.data
    shp = img.shape
    if mode == LAPLACIAN_ENERGIES:
        # OpenCV filters: same values as the scikit-image ones used before
        # (filters.gaussian, scharr_h, scharr_v, roberts_pos_diag, roberts_neg_diag)
        # up to float32 rounding, about 10 times faster and in float32.
        img_filt = c2g(img.astype(np.float32)) #float32 otherwise cv2 cannot convert RGB to GRAY
        if sigma_gaussian is not None:
            img_filt = gaussian_blur(img_filt, sigma_gaussian, border=cv2.BORDER_REPLICATE)
        ms_img = np.empty((shp[0], shp[1], 4), dtype=np.float32)
        border = cv2.BORDER_REFLECT
        ms_img[:, :, 0] = cv2.Scharr(img_filt, cv2.CV_32F, 0, 1, scale=1/16., borderType=border)
        ms_img[:, :, 1] = cv2.Scharr(img_filt, cv2.CV_32F, 1, 0, scale=1/16., borderType=border)
        ms_img[:, :, 2] = cv2.filter2D(img_filt, cv2.CV_32F, ROBERTS_POS_DIAG, anchor=(0, 0), borderType=border)
        ms_img[:, :, 3] = cv2.filter2D(img_filt, cv2.CV_32F, ROBERTS_NEG_DIAG, anchor=(0, 0), borderType=border)
        np.square(ms_img, out=ms_img)
    elif mode == GRAY_SCALE:
        ms_img = np.empty((shp[0], shp[1], 1))
        ms_img[:, :, 0] = 0.299*img[:, :, 0] + 0.587*img[:, :, 1] + 0.114*img[:, :, 2]
    elif mode == COLORED:
        ms_img = img
    else:
        raise NameError("Representation {} is not supported".format(mode))
    return ms_img

# ---------------------------------------------- Cost functions / distances --------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------



@jit(nopython=True, cache=True, fastmath=True)
def cost_surface_SSD(patch_ref, patch_mov_search, search_y, search_x):
    """Sum of squared difference optimized by Numba
    """
    pm_s_y, pm_s_x, c_s = patch_mov_search.shape
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for ch in range(c_s):
        mov = np.ascontiguousarray(patch_mov_search[:, :, ch])
        ref = np.ascontiguousarray(patch_ref[:, :, ch])
        for v in range(0, 2*search_y+1):
            for u in range(0, 2*search_x+1):
                total = 0.
                for y in range(pm_s_y):
                    for x in range(pm_s_x):
                        diff = mov[y, x] - ref[v+y, u+x]
                        total += diff*diff
                cost[v, u, ch] = total
    return cost


@jit(nopython=True, cache=True, fastmath=True)
def _sobel_valid(img):
    """Unnormalized 3x3 Sobel gradients of a 2D image, without the 1 pixel border:
    (derivative along x, derivative along y), each (H-2, W-2) float32."""
    y_s, x_s = img.shape
    grad_x = np.empty((y_s-2, x_s-2), dtype=np.float32)
    grad_y = np.empty((y_s-2, x_s-2), dtype=np.float32)
    for y in range(y_s-2):
        for x in range(x_s-2):
            grad_x[y, x] = (img[y, x+2] - img[y, x]) + 2*(img[y+1, x+2] - img[y+1, x]) + (img[y+2, x+2] - img[y+2, x])
            grad_y[y, x] = (img[y+2, x] - img[y, x]) + 2*(img[y+2, x+1] - img[y, x+1]) + (img[y+2, x+2] - img[y, x+2])
    return grad_x, grad_y


@jit(nopython=True, cache=True, fastmath=True)
def _sum_abs_diff_surface(mov, ref, cost, ch):
    """cost[v, u, ch] += sum |mov - ref[v:v+h, u:u+w]| for every offset (v, u)."""
    y_s, x_s = mov.shape
    for v in range(cost.shape[0]):
        for u in range(cost.shape[1]):
            total = 0.
            for y in range(y_s):
                for x in range(x_s):
                    total += abs(mov[y, x] - ref[v+y, u+x])
            cost[v, u, ch] += total


@jit(nopython=True, cache=True)
def cost_surface_NTG(patch_ref, patch_mov_search, search_y, search_x):
    """Normalized Total Gradient - optimized by Numba:
    sum of |Sobel(mov - shifted ref)| for every shift, both Sobel directions.

    The Sobel filter is linear: Sobel(mov - ref) = Sobel(mov) - Sobel(ref). The
    gradients of both patches are computed once, each shift is then a sum of
    absolute differences (same result as filtering the difference at each
    shift, about 15 times faster).
    """
    c_s = patch_mov_search.shape[2]
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for ch in range(c_s):
        mov_x, mov_y = _sobel_valid(np.ascontiguousarray(patch_mov_search[:, :, ch]))
        ref_x, ref_y = _sobel_valid(np.ascontiguousarray(patch_ref[:, :, ch]))
        _sum_abs_diff_surface(mov_x, ref_x, cost, ch)
        _sum_abs_diff_surface(mov_y, ref_y, cost, ch)
    return cost


# ---------------------------------------------- Full image cost function ----------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------
def get_patch(ref, mov, crop):
    y_start, y_end, x_start, x_end = crop
    patch_ref = ref[y_start:y_end, x_start:x_end, :]
    patch_mov = mov[y_start:y_end, x_start:x_end, :]
    return patch_ref, patch_mov


def compute_cost_surfaces(
        ref, mov,
        y_n=3, x_n=3, search_y=3, search_x=3,
        dist_mode=SSD
    ):
    y_s, x_s, c_s = ref.shape
    p_size_x = int(np.floor(x_s / x_n))
    p_size_y = int(np.floor(y_s / y_n))
    costs = np.empty((y_n, x_n, 2*search_y+1, 2*search_x+1, c_s))
    centers = np.empty((y_n, x_n, 2))
    patch_coords = np.empty((y_n, x_n, 4))
    if dist_mode == SSD:
        cost_surface = cost_surface_SSD
    elif dist_mode == NTG:
        cost_surface = cost_surface_NTG
    else:
        raise NameError("Distance {} is not supported".format(dist_mode))
    for y_id in range(y_n):
        for x_id in range(x_n):
            y_start, y_end = y_id*p_size_y, (y_id+1)*p_size_y
            x_start, x_end = x_id*p_size_x, (x_id+1)*p_size_x
            y_center, x_center = (y_start+y_end)/2., (x_start+x_end)/2.
            patch_coords[y_id, x_id, :] = [y_start, y_end, x_start, x_end]
            centers[y_id, x_id, :] = [x_center, y_center]
            patch_ref, patch_mov = get_patch(ref, mov, (y_start, y_end, x_start, x_end))
            patch_mov_search = patch_mov[search_y:-search_y, search_x:-search_x, :]
            costs[y_id, x_id] = cost_surface(
                np.ascontiguousarray(patch_ref, dtype=np.float32),
                np.ascontiguousarray(patch_mov_search, dtype=np.float32),
                search_y, search_x)
    return costs, centers, patch_coords


def plot_costs_overview(cost_dict, debug_fig=None, title=None, pickle_path=None):
    _costs_dbg = []
    for y_id in range(cost_dict["costs"].shape[0]):
        _costs_dbg.append([])
        for x_id in range(cost_dict["costs"].shape[1]):
            cost = cost_dict["costs"][y_id][x_id]
            _costs_dbg[y_id].append(cost.sum(axis=-1))
    pr.show(
        _costs_dbg,
        suptitle=title,
        save=debug_fig,
    )
    if pickle_path is not None:
        np.save(pickle_path, cost_dict)


def plot_single_cost_function(cost_dict, ref, mov, patch_coords, prefix="", suffix="", align_config=AlignmentConfig(),
                              debug=False, debug_fig=None):

    for y_id in range(align_config.y_n):
        for x_id in range(align_config.x_n):
            y_start, y_end, x_start, x_end = patch_coords[y_id, x_id, :].astype(int)
            patch_ref, patch_mov = get_patch(ref, mov, (y_start, y_end, x_start, x_end))
            cost = cost_dict["costs"][y_id][x_id]
            if debug or debug_fig is not None:
                debug_fig_current = None
                if debug_fig is not None:
                    debug_fig_current = debug_fig+"cost_surface_{}_{}_{}.png".format(y_id, x_id, suffix)

                if align_config.mode == LAPLACIAN_ENERGIES:
                    costs_plots = [
                        (cost[:, :, 0], "{} -".format(align_config.dist_mode)),
                        (cost[:, :, 1], "{} |".format(align_config.dist_mode)),
                        (cost[:, :, 2], "{} /".format(align_config.dist_mode)),
                        (cost[:, :, 3], "{} \\".format(align_config.dist_mode)),
                        (np.sum(cost, axis=2), "cost sum")
                    ]
                if align_config.mode == GRAY_SCALE:
                    costs_plots = [
                        (cost[:, :, 0], "{}".format(align_config.dist_mode)),
                    ]
                if align_config.mode == COLORED:
                    costs_plots = [
                        (cost[:, :, 0], "{} R".format(align_config.dist_mode)),
                        (cost[:, :, 1], "{} G".format(align_config.dist_mode)),
                        (cost[:, :, 2], "{} B".format(align_config.dist_mode)),
                    ]
                patch_mov_search = patch_mov[
                                   align_config.search_y:-align_config.search_y,
                                   align_config.search_x:-align_config.search_x,
                                   :
               ]
                pr.show(
                    [
                        [
                            (viz_laplacian_energy(patch_ref), "VIS"),
                            (viz_laplacian_energy(patch_mov), "NIR"),
                            (viz_laplacian_energy(patch_mov_search), "NIR patch"),
                            (viz_laplacian_energy(cost), "colored cost {}".format(align_config.dist_mode)),
                        ],
                        costs_plots
                    ],
                    suptitle="PATCH Y={} X={} {} {} {}".format(y_id, x_id, align_config.dist_mode, prefix, suffix),
                    save=debug_fig_current
                )

def compute_cost_surfaces_with_traces(
        ref, mov,
        debug=False, debug_dir=None, prefix=None, suffix="", align_config=AlignmentConfig(),
        forced_debug_dir=None
    ):
    """Wrapping for numba acclerated compute_cost_surfaces with extra debug traces
    """
    if prefix is None:
        prefix = ""
    debug_fig_main = None if debug_dir is None else osp.join(debug_dir, "{}_blocks_y{}x{}_search_y{}x{}_{}_".format(
        prefix, align_config.y_n, align_config.x_n, align_config.search_y, align_config.search_x, align_config.dist_mode))
    costs, centers, patch_coords = compute_cost_surfaces(
        ref, mov,
        y_n=align_config.y_n, x_n=align_config.x_n,
        search_x=align_config.search_x, search_y=align_config.search_y,
        dist_mode=align_config.dist_mode,
    )
    cost_dict = {
        "costs": costs,
        "centers": centers,
        "downscale": align_config.downscale
    }
    debug_fig = debug_fig_main
    # ------------------------------------------------------------------------------------------- Debug all single costs
    if debug or debug_dir is not None:
        plot_single_cost_function(
            cost_dict, ref, mov, patch_coords, prefix=prefix, suffix=suffix, align_config=align_config,
            debug=debug, debug_fig=debug_fig
        )
    # -------------------------------------------------------------------------------------- Debug overview of all costs
    if forced_debug_dir is not None:
        debug_fig_main = osp.join(
            forced_debug_dir, "{}_blocks_y{}x{}_search_y{}x{}_{}_".format(
                prefix, align_config.y_n, align_config.x_n,
                align_config.search_y, align_config.search_x, align_config.dist_mode
            )
        )
        debug_fig = None if debug_fig_main is None else debug_fig_main + "overview_cost_surfaces_{}.png".format(suffix)
        pickle_path = None if debug_fig_main is None else debug_fig_main+"_cost_search_{}".format(suffix)
        plot_costs_overview(
            cost_dict,
            debug_fig=debug_fig,
            title="cost {} surfaces y{} x{} {} {}".format(align_config.dist_mode, align_config.y_n, align_config.x_n, prefix, suffix),
            pickle_path=pickle_path
        )
    return cost_dict


def run_multispectral_cost(ref_orig, mov_orig, debug_dir=None, debug=True, suffix="", prefix="", align_config=AlignmentConfig()):
    """
    - Switch to a specific multi-spectral representation
    - Downscale
    - Compute costs
    """
    if debug_dir is not None and not osp.isdir(debug_dir):
        mkdir(debug_dir)
    ref = multispectral_representation(
        ref_orig if isinstance(ref_orig, np.ndarray) else ref_orig.data,
        sigma_gaussian=align_config.sigma_ref, mode=align_config.mode
    )
    mov = multispectral_representation(
        mov_orig if isinstance(mov_orig, np.ndarray) else mov_orig.data,
        sigma_gaussian=align_config.sigma_mov, mode=align_config.mode
    )
    prefix = prefix+"ds{}_{}".format(align_config.downscale, align_config.mode)
    if debug or debug_dir is not None:
        debug_fig = None if debug_dir is None else osp.join(debug_dir, "{}_{}".format(prefix, suffix))
        representation_visualization_pairs(ref, mov, ref_orig=ref_orig, mov_orig=mov_orig, debug_fig=debug_fig, title="{} {}".format(prefix, suffix))
    if align_config.downscale >1:
        ref_pyr = pyramid_reduce(ref, downscale=align_config.downscale)
        mov_pyr = pyramid_reduce(mov, downscale=align_config.downscale)
        logging.info("Downscale from {} to {}".format(ref.shape, ref_pyr.shape))
    else:
        ref_pyr, mov_pyr = ref, mov

    cost_dict = compute_cost_surfaces_with_traces(
        ref_pyr, mov_pyr, debug_dir=debug_dir,
        prefix=prefix,suffix=suffix,
        debug=debug,
        align_config=align_config

    )
    return cost_dict


if __name__ == '__main__':
    import irdrone.process as pr
    from os import mkdir
    path = osp.join(osp.dirname(__file__), "..", "samples")
    nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    debug_dir = "_debug_cost_factorize"
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    debug_dir = None
    align_conf = AlignmentConfig(
        mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
        dist_mode=[SSD, NTG][1],
        downscale=16,
        sigma_ref=5.,
        sigma_mov=3.,  # reducing blur for NIR image
        num_patches=6,
        search_size=5
    )
    run_multispectral_cost(vis_img, nir_img, align_config=align_conf, debug_dir=debug_dir)
