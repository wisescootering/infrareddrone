from skimage import filters, transform
import numpy as np
from irdrone.utils import c2g, g2c
from numba import jit
import os.path as osp
import logging
import irdrone.process as pr
from registration.constants import LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED, SSD, NTG


def multispectral_representation(img, sigma_gaussian=5., mode=LAPLACIAN_ENERGIES):
    """Laplacian Energy
    """
    shp = img.shape
    if mode == LAPLACIAN_ENERGIES:
        ms_img = np.empty((shp[0], shp[1], 4))
        img_filt = c2g(img.astype(np.float32)) #float32 otherwise cv2 cannot convert RGB to GRAY
        if sigma_gaussian is not None:
            img_filt = filters.gaussian(img_filt, sigma_gaussian)
        ms_img[:, :, 0] = filters.scharr_h(img_filt)
        ms_img[:, :, 1] = filters.scharr_v(img_filt)
        ms_img[:, :, 2] = filters.edges.roberts_pos_diag(img_filt)
        ms_img[:, :, 3] = filters.edges.roberts_neg_diag(img_filt)
        ms_img = ms_img**2
    if mode == GRAY_SCALE:
        ms_img = np.empty((shp[0], shp[1], 1))
        ms_img[:, :, 0] = 0.299*img[:, :, 0] + 0.587*img[:, :, 1] + 0.114*img[:, :, 2]
    if mode == COLORED:
        ms_img = img
    return ms_img


def get_patch(ref, mov, crop):
    y_start, y_end, x_start, x_end = crop
    patch_ref = ref[y_start:y_end, x_start:x_end, :]
    patch_mov = mov[y_start:y_end, x_start:x_end, :]
    return patch_ref, patch_mov


@jit(nopython=True)
def cost_surface_SSD(patch_ref, patch_mov_search, search_y, search_x):
    """Sum of squared difference optimized by Numba
    """
    pm_s_y, pm_s_x, c_s = patch_mov_search.shape
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for v in range(0, 2*search_y+1):
        for u in range(0, 2*search_x+1):
            for ch in range(c_s):
                cost[v, u, ch] = np.sum((patch_mov_search[:, :, ch]-patch_ref[v:v+pm_s_y, u:u+pm_s_x, ch])**2)
    return cost


# @jit(nopython=True)
def cost_surface_NCC(patch_ref, patch_mov_search, search_y, search_x):
    """Normalized Correlation Coefficient - optimized by Numba
    """
    pm_s_y, pm_s_x, c_s = patch_mov_search.shape
    cost = np.zeros((2*search_y+1, 2*search_x+1, c_s))
    for v in range(0, 2*search_y+1):
        for u in range(0, 2*search_x+1):
            for ch in range(c_s):
                diff = (patch_mov_search[:, :, ch] - patch_ref[v:v+pm_s_y, u:u+pm_s_x, ch])
                sobel_ = diff[:, 2:] - diff[:, :-2]
                sobel_v = sobel_[:-2] + sobel_[2:] + 2*sobel_[1:-1]
                sobel_ = diff[2:, :] - diff[:-2, :]
                sobel_h = sobel_[:, :-2] + sobel_[:, 2:] + 2*sobel_[:, 1:-1]
                cost[v, u, ch] = np.abs(sobel_v).sum() + np.abs(sobel_h).sum()
    return cost


def g2ci(ms_img):
    avg = np.average(ms_img)
    return g2c((255*(ms_img*0.5/avg).clip(0, 1)).astype(np.uint8))


def viz_laplacian_energy(ms_img):
    avg = np.average(ms_img)
    out = (255*(ms_img[:, :, :3]*0.5/avg).clip(0, 1)).astype(np.uint8)
    return out


def compute_surfaces(ref, mov, debug=False, y_n=3, x_n=3, search_y=3, search_x=3, debug_fig=None, mode=LAPLACIAN_ENERGIES, dist_mode=SSD, suffix="", prefix=""):
    y_s, x_s, c_s = ref.shape
    p_size_x = int(np.floor(x_s / x_n))
    p_size_y = int(np.floor(y_s / y_n))
    costs = []
    costs_dbg = []
    centers = np.empty((p_size_y, p_size_x, 2))
    for y_id in range(y_n):
        costs.append([])
        costs_dbg.append([])
        for x_id in range(x_n):
            y_start, y_end = y_id*p_size_y, (y_id+1)*p_size_y
            x_start, x_end = x_id*p_size_x, (x_id+1)*p_size_x
            y_center, x_center = (y_start+y_end)/2., (x_start+x_end)/2.
            centers[y_id, x_id, :] = [x_center, y_center]
            patch_ref, patch_mov = get_patch(ref, mov, (y_start, y_end, x_start, x_end))
            patch_mov_search = patch_mov[search_y:-search_y, search_x:-search_x, :]
            if dist_mode == SSD:
                cost = cost_surface_SSD(patch_ref.astype(np.float32), patch_mov_search.astype(np.float32), search_y, search_x)
            else:
                cost = cost_surface_NCC(patch_ref.astype(np.float32), patch_mov_search.astype(np.float32), search_y, search_x)
            if debug or debug_fig is not None:
                debug_fig_current = None
                if debug_fig is not None:
                    debug_fig_current = debug_fig+"cost_surface_{}_{}_{}.png".format(y_id, x_id, suffix)

                if mode == LAPLACIAN_ENERGIES:
                    costs_plots = [
                        (cost[:, :, 0], "{} -".format(dist_mode)),
                        (cost[:, :, 1], "{} |".format(dist_mode)),
                        (cost[:, :, 2], "{} /".format(dist_mode)),
                        (cost[:, :, 3], "{} \\".format(dist_mode)),
                        (np.sum(cost, axis=2), "cost sum")
                    ]
                if mode == GRAY_SCALE:
                    costs_plots = [
                        (cost[:, :, 0], "{}".format(dist_mode)),
                    ]
                if mode == COLORED:
                    costs_plots = [
                        (cost[:, :, 0], "{} R".format(dist_mode)),
                        (cost[:, :, 1], "{} G".format(dist_mode)),
                        (cost[:, :, 2], "{} B".format(dist_mode)),
                    ]
                pr.show(
                    [
                        [
                            (viz_laplacian_energy(patch_ref), "VIS"),
                            (viz_laplacian_energy(patch_mov), "NIR"),
                            (viz_laplacian_energy(patch_mov_search), "NIR patch"),
                            (viz_laplacian_energy(cost), "colored cost {}".format(dist_mode)),
                        ],
                        costs_plots

                    ],
                    suptitle="PATCH Y={} X={} {} {} {}".format(y_id, x_id, dist_mode, prefix, suffix),
                    save=debug_fig_current
                )
            costs[y_id].append(cost)
            costs_dbg[y_id].append(np.sum(cost, axis=2))
    return costs, costs_dbg, centers


def debug_image_inputs(ref_orig, mov_orig, ref, mov, debug_fig=None, title="", mode=LAPLACIAN_ENERGIES):
    """
    - Laplacian Energies
    """
    debug_fig = None if debug_fig is None else (debug_fig + "inputs_"+mode+".png")
    if mode == LAPLACIAN_ENERGIES:
        pr.show(
            [
                [(ref_orig.data, "VIS"), (g2ci(ref[:, :, 0]), "-"), (g2ci(ref[:, :, 1]), "|"),
                 (g2ci(ref[:, :, 2]), "/"), (g2ci(ref[:, :, 3]), "\\"), (viz_laplacian_energy(ref), "Energies")
                 ],
                [(mov_orig.data, "NIR"), (g2ci(mov[:, :, 0]), "-"), (g2ci(mov[:, :, 1]), "|"),
                 (g2ci(mov[:, :, 2]), "/"), (g2ci(mov[:, :, 3]), "\\"), (viz_laplacian_energy(mov), "Energies")
                 ]
            ],
            suptitle=title+"Directional energies {}".format(mov.shape),
            save=debug_fig
        )
    if mode == GRAY_SCALE:
        pr.show(
            [
                [(ref_orig.data, "VIS"), (g2ci(ref[:, :, 0]), "Gray")],
                [(mov_orig.data, "NIR"), (g2ci(mov[:, :, 0]), "Gray")]
            ],
            suptitle=title+"Gray {}".format(mov.shape),
            save=debug_fig
        )
    if mode == COLORED:
        pr.show(
            [
                [(ref_orig.data, "VIS"), (mov_orig.data, "NIR")],
            ],
            suptitle=title+"Colored {}".format(mov.shape),
            save=debug_fig
        )


def align_single_scale(ref, mov, downscale=1, debug=False, debug_dir=None, prefix=None, suffix="", y_n=5, x_n=5, search_y=5, search_x=5, mode=LAPLACIAN_ENERGIES, dist_mode=SSD):
    if downscale >1:
        ref_pyr = transform.pyramid_reduce(ref, downscale=downscale, multichannel=True)
        mov_pyr = transform.pyramid_reduce(mov, downscale=downscale, multichannel=True)
        logging.info("Downscale from {} to {}".format(ref.shape, ref_pyr.shape))
        if prefix is None:
            prefix = "ds_{}".format(downscale)
    else:
        ref_pyr, mov_pyr = ref, mov
    if prefix is None:
        prefix = ""
    debug_fig_main = None if debug_dir is None else osp.join(debug_dir, "{}_blocks_y{}x{}_{}_{}_".format(prefix, y_n, x_n, mode, dist_mode))
    costs, _costs_dbg, centers = compute_surfaces(
        ref_pyr, mov_pyr, y_n=y_n, x_n=x_n, search_x=search_x, search_y=search_y,
        debug=debug,
        debug_fig=debug_fig_main, prefix=prefix, suffix=suffix,
        mode=mode,
        dist_mode=dist_mode,
    )
    debug_fig = None if debug_fig_main is None else debug_fig_main + "overview_cost_surfaces_{}.png".format(suffix)
    cost_dict = {
        "costs": np.array(costs),
        "centers": centers,
        "downscale": downscale
    }
    if debug or debug_dir is not None:
        pr.show(
            _costs_dbg, suptitle="cost {} surfaces {}, ds {} y{} x{} {} {}".format(dist_mode, mode, downscale, y_n, x_n, prefix, suffix),
            save=debug_fig
        )
        np.save(debug_fig_main+"_cost_search_{}".format(suffix), cost_dict)
    return cost_dict


def align(ref_orig, mov_orig, debug=False, debug_dir=None, mode=LAPLACIAN_ENERGIES, dist_mode=SSD, downscale=1, prefix=None, suffix="", sigma_ref=5., sigma_mov=3.):
    # @TODO: move spectral representation outside align!
    # @TODO: move downscale outside align!
    ref = multispectral_representation(ref_orig if isinstance(ref_orig, np.ndarray) else ref_orig.data, sigma_gaussian=sigma_ref, mode=mode)
    mov = multispectral_representation(mov_orig if isinstance(mov_orig, np.ndarray) else mov_orig.data, sigma_gaussian=sigma_mov, mode=mode) # reducing blur for NIR image
    if prefix is None:
        if downscale>1:
            prefix = "ds_{}".format(downscale)
        else:
            prefix = ""
    if debug or debug_dir is not None:
        debug_fig = None if debug_dir is None else osp.join(debug_dir, "{}_{}".format(prefix, suffix))
        debug_image_inputs(ref_orig, mov_orig, ref, mov, debug_fig=debug_fig, title="{} {}".format(prefix, suffix), mode=mode)
    num_patches = 5
    search_size = 6
    y_n = num_patches
    x_n = num_patches
    cost_dict = align_single_scale(
        ref, mov, debug=debug, debug_dir=debug_dir, prefix=prefix, suffix=suffix,
        downscale=downscale, y_n=y_n, x_n=x_n, search_y=search_size, search_x=search_size,
        mode=mode,
        dist_mode=dist_mode
    )
    return cost_dict


if __name__ == '__main__':
    import irdrone.process as pr
    from os import mkdir
    path = osp.join(osp.dirname(__file__), "..", "samples")
    nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    debug_dir="_debug_cost"
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    align(
        vis_img, nir_img, debug_dir=debug_dir,
        mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
        dist_mode=[SSD, NTG][1],
        downscale=16
    )