from skimage import filters, transform
import numpy as np
from irdrone.utils import c2g, g2c
from numba import jit
import os.path as osp
import logging
from registration.constants import LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED, SSD, NTG


def multispectral_representation(img, sigma_gaussian=5., mode=LAPLACIAN_ENERGIES):
    """Laplacian Energy
    """
    shp = img.shape
    if mode == LAPLACIAN_ENERGIES:
        ms_img = np.empty((shp[0], shp[1], 4))
        img_filt = filters.gaussian(c2g(img), sigma_gaussian)
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


def compute_surfaces(ref, mov, debug=False, y_n=3, x_n=3, search_y=3, search_x=3, debug_fig=None, mode=LAPLACIAN_ENERGIES, dist_mode=SSD):
    y_s, x_s, c_s = ref.shape
    p_size_x = int(np.floor(x_s / x_n))
    p_size_y = int(np.floor(y_s / y_n))
    costs = []
    costs_dbg = []
    for y_id in range(y_n):
        costs.append([])
        costs_dbg.append([])
        for x_id in range(x_n):
            y_start, y_end = y_id*p_size_y, (y_id+1)*p_size_y
            x_start, x_end = x_id*p_size_x, (x_id+1)*p_size_x
            patch_ref, patch_mov = get_patch(ref, mov, (y_start, y_end, x_start, x_end))
            patch_mov_search = patch_mov[search_y:-search_y, search_x:-search_x, :]
            if dist_mode == SSD:
                cost = cost_surface_SSD(patch_ref.astype(np.float32), patch_mov_search.astype(np.float32), search_y, search_x)
            else:
                cost = cost_surface_NCC(patch_ref.astype(np.float32), patch_mov_search.astype(np.float32), search_y, search_x)
            if debug or debug_fig is not None:
                debug_fig_current = None
                if debug_fig is not None:
                    debug_fig_current = debug_fig+"cost_surface_{}_{}.png".format(y_id, x_id)

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
                    suptitle="PATCH Y={} X={} {}".format(y_id, x_id, dist_mode),
                    save=debug_fig_current
                )
            costs[y_id].append(cost)
            costs_dbg[y_id].append(np.sum(cost, axis=2))
    return costs, costs_dbg


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


def align_single_scale(ref, mov, downscale=1, debug=False, debug_dir=None, y_n=5, x_n=5, mode=LAPLACIAN_ENERGIES, dist_mode=SSD):
    ref_pyr = transform.pyramid_reduce(ref, downscale=downscale, multichannel=True)
    mov_pyr = transform.pyramid_reduce(mov, downscale=downscale, multichannel=True)
    logging.info("Downscale from {} to {}".format(ref.shape, ref_pyr.shape))
    debug_fig_main = None if debug_dir is None else osp.join(debug_dir, "ds_{}_blocks_y{}x{}_{}_{}_".format(downscale, y_n, x_n, mode, dist_mode))
    costs, _costs_dbg = compute_surfaces(
        ref_pyr, mov_pyr, y_n=y_n, x_n=x_n, search_x=5, search_y=5,
        debug=True,
        debug_fig=debug_fig_main,
        mode=mode,
        dist_mode=dist_mode
    )
    debug_fig = None if debug_fig_main is None else debug_fig_main + "overview_cost_surfaces.png"
    if debug or debug_dir is not None:
        pr.show(_costs_dbg, suptitle="cost {} surfaces {}, ds {} y{} x{}".format(dist_mode, mode, downscale, y_n, x_n), save=debug_fig)
        np.save(debug_fig+"_cost", np.array(costs))
    return costs


def align(ref_orig, mov_orig, debug=False, debug_dir=None, mode=LAPLACIAN_ENERGIES, dist_mode=SSD):
    ref = multispectral_representation(ref_orig.data, sigma_gaussian=5., mode=mode)
    mov = multispectral_representation(mov_orig.data, sigma_gaussian=3., mode=mode) # reducing blur for NIR image
    if debug or debug_dir is not None:
        debug_fig = None if debug_dir is None else osp.join(debug_dir, "ds_{}_".format(1))
        debug_image_inputs(ref_orig, mov_orig, ref, mov, debug_fig=debug_fig, title="DS={} ".format(1), mode=mode)

    downscale = 16
    num_patches = 5
    y_n = num_patches
    x_n = num_patches
    costs = align_single_scale(
        ref, mov, debug=debug, debug_dir=debug_dir,
        downscale=downscale, y_n=y_n, x_n=x_n,
        mode=mode,
        dist_mode=dist_mode
    )
    return costs


if __name__ == '__main__':
    import irdrone.process as pr
    from os import mkdir

    path = osp.join(osp.dirname(__file__), "..", "Hyperlapse 06_09_2021_sync" , "debug")
    nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    debug_dir="_debug_laplacian_energies"
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    align(
        vis_img, nir_img, debug_dir=debug_dir,
        mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
        dist_mode=[SSD, NTG][1]
    )