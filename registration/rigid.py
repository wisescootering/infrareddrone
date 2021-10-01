import os.path as osp
import numpy as np
from registration.newton import newton_iter, quadric_approximation
from irdrone.registration import geometric_rigid_transform_estimation
from registration.warp_flow import warp_from_sparse_vector_field
# from irdrone.utils import c2g, g2c
import matplotlib.pyplot as plt
import logging
from registration.cost import compute_cost_surfaces_with_traces, AlignmentConfig, run_multispectral_cost, multispectral_representation, viz_laplacian_energy
from registration.constants import LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED, SSD, NTG
import irdrone.process as pr
import cv2
from skimage import transform
from os import mkdir
import time


def minimum_cost(cost):
    """Find the argmin in a single cost area (multichannel) and refine with quadratic form subpixel search
    :param cost:
    :return:
    """
    amin_index = np.unravel_index(np.argmin(cost.sum(axis=-1)), (cost.shape[0], cost.shape[1]))
    init_position = np.array([amin_index[1]-cost.shape[1]//2, amin_index[0]-cost.shape[0]//2])
    neighborhood_size = 1
    if amin_index[0] < neighborhood_size or amin_index[0] > cost.shape[0]-1-neighborhood_size or \
            amin_index[1] < neighborhood_size or amin_index[1] > cost.shape[1]-1-neighborhood_size:
        return init_position
    extracted_patch = cost[
                      amin_index[0]-neighborhood_size:amin_index[0]+neighborhood_size+1,
                      amin_index[1]-neighborhood_size:amin_index[1]+neighborhood_size+1,
                      :
                      ]
    hessi, gradi, constants = quadric_approximation(extracted_patch)

    new_val = newton_iter(
        np.array([0., 0.]).T,
        gradi,
        hess_mat = hessi,
        max_step=None
    )
    return new_val+init_position


def brute_force_vector_field_search(costs=None, centers=None, downscale=None):
    """
    Returns vector field ready to be fit (at full scale if downscale is provided)
    :param costs: displacement cost
    :param centers: center positions of each path
    :param downscale: downscale factor
    :return:
    """
    center_y, center_x = costs.shape[2]//2, costs.shape[3]//2
    extraction_area = 5
    vector_field = np.empty((costs.shape[0], costs.shape[1], 2))
    vpos = np.empty((costs.shape[0], costs.shape[1], 2))
    for i in range(costs.shape[0]):
        for j in range(costs.shape[1]):
            logging.info("patch {} {}".format(i, j))
            single_cost = costs[
                          i, j,
                          center_y-extraction_area:center_y+extraction_area+1,
                          center_x-extraction_area:center_x+extraction_area+1,
                          :
                          ]
            vector_field[i, j, :] = minimum_cost(single_cost) * (1. if downscale is None else downscale)
            vpos[i, j, :] = centers[i, j] * (1. if downscale is None else downscale)
    return vpos, vector_field


class MotionModelHomography:
    def __init__(self, model=np.eye(3), **kwargs):
        if model is None:
            self.estimate(**kwargs)
        else:
            self.model = model
            self.model_history = [self.model]

    def estimate(self, vector_pos=None, vector_field=None, debug=False, affinity=False, **kwargs):
        self.model = geometric_rigid_transform_estimation(vector_pos, vector_field, debug=debug, affinity=affinity, **kwargs)
        self.model_history = [self.model]

    def compose(self, new_model):
        self.model = np.dot(new_model.model, self.model)
        self.model_history = [new_model.model] + self.model_history

    def rescale(self, downscale=1.) -> np.ndarray:
        """Rescale homography - model is defined at full resolution"""
        if downscale !=1:
            zoom_mat = np.eye(3)
            zoom_mat[0, 0] = zoom_mat[1, 1] = 1./downscale
            return np.dot(np.dot(zoom_mat, self.model), np.linalg.inv(zoom_mat))
        else:
            return self.model

    def warp(self, img, downscale=1.):
        """Downscale is handled here"""
        img_array = img.data if isinstance(img, pr.Image) else img
        homog_at_scale = self.rescale(downscale=downscale)
        img_aligned = cv2.warpPerspective(img_array, homog_at_scale, img_array.shape[:2][::-1])
        return img_aligned

    def __repr__(self):
        return str(self.model)


class MotionModel:
    def __init__(self, model=None):
        self.model = model
        self.model_history = [self.model]

    def compose(self, new_model):
        """
        compose
        :param new_model:
        :return:
        """
        self.model = new_model.model # combine models
        self.model_history = [new_model.model] + self.model_history

    def estimate(self, *args, **kwargs):
        """
        Estimate motion model from data such as
            - a vector field
            - cost function using optimization algorithm

        self.model = model_estimation(*args)
        """
        pass

    def warp(self, img, downscale=1.):
        pass

    def __repr__(self):
        return str(self.model)


def compute_pyramid(img, scales_list):
    """Returns pyramid dictionary"""
    img_pyr = {}

    for (ids, resized) in enumerate(transform.pyramid_gaussian(img, downscale=2, multichannel=True)):
        if 2**ids in scales_list:
            img_pyr[2**ids] = resized.astype(np.float32)
            logging.info("Storing pyramid level {}".format(2**ids, resized.shape))
        if 2**ids >= max(scales_list):#iterative_scheme[0][0]:
            break
    return img_pyr


def viz_msr(img, msr_mode):
    if msr_mode == LAPLACIAN_ENERGIES:
        img_save = viz_laplacian_energy(img)
    else:
        img_save = img if img.dtype == np.uint8 else ((img*255).clip(0, 255)).astype(np.uint8)
    return img_save


def pyramidal_search(
    img_ref, img_mov, debug_dir=None, debug=True,
    iterative_scheme=[(32, 12), (16, 2), (8, 1),],
    mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][-1],
    dist=[SSD, NTG][0],
    sigma_ref=5,
    sigma_mov=3,
    affinity=True,
    default_patch_number=5
):
    """
        iterative_scheme = [ (downsample, iteration, num_patches)]
        - debug_dir=None, debug=True,  # -> SHOW TRACES, NOT SAVING ANYTHING TO DISK
        - debug_dir=None, debug=False,  # -> NO TRACES AT ALL, NOT SAVING ANYTHING TO DISK
        - debug_dir=debug_dir, debug=False, # -> FORCE ONLY MANDATORY TRACES (see debug_flag in debug_trace function)
        - debug_dir=debug_dir, debug=True, # -> FORCE ALL TRACES TO DISK
    """
    ts_start = time.perf_counter()
    forced_debug_dir = debug_dir
    if not debug:
        debug_dir = None # disable most traces if debug is set to False

    def debug_trace(img, ds=1, iter="", suffix="", prefix="", debug_flag=None, msr_mode=None):
        """debug_flag allows to force debugging trace if set to True"""
        if debug_flag is None:
            debug_flag = debug
        if debug_flag and forced_debug_dir is not None:
            name = "{}it{:02d}_ds{:02d}_{}.jpg".format(prefix, iter, ds, suffix)
            if isinstance(img, np.ndarray) or isinstance(img, pr.Image):
                img_save = viz_msr(img, msr_mode=msr_mode)
                pr.Image(img_save).save(osp.join(forced_debug_dir, name))
            elif isinstance(img, plt.Axes):
                plt.savefig(osp.join(forced_debug_dir, name))
    # ------------------------------------------------------------------------------------------------------------------
    motion_model = MotionModelHomography()
    compute_cost = compute_cost_surfaces_with_traces
    # ------------------------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------  Multispectral representation
    ts_msr_start = time.perf_counter()
    msr_ref = multispectral_representation(
        img_ref if isinstance(img_ref, np.ndarray) else img_ref.data,
        sigma_gaussian=sigma_ref, mode=mode
    ).astype(np.float32)
    msr_mov = multispectral_representation(
        img_mov if isinstance(img_mov, np.ndarray) else img_mov.data,
        sigma_gaussian=sigma_mov, mode=mode
    ).astype(np.float32)
    ts_msr_end = time.perf_counter()
    logging.warning("{:.2f}s elapsed in MSR {} computation".format(ts_msr_end - ts_msr_start, mode))
    # ------------------------------------------------------------------------------------------------------------------
    iter = 0
    ts_ds_start = time.perf_counter()
    scales_list = [el[0] for el in iterative_scheme]
    msr_ref_pyr = compute_pyramid(msr_ref, scales_list)
    msr_mov_pyr = compute_pyramid(msr_mov, scales_list)
    if debug:
        img_ref_pyr = compute_pyramid(img_ref, scales_list)
        img_mov_pyr = compute_pyramid(img_mov, scales_list)
    ts_ds_end = time.perf_counter()

    logging.warning("{:.2f}s elapsed in pyramid dowscale up to {}".format(ts_ds_end - ts_ds_start, iterative_scheme[0][0]))

    # ---------------------------------------------------    PYRAMID   -------------------------------------------------
    # -------------------------------------------------------------------------------------------------- Multiscale loop
    for iter_conf in iterative_scheme:
        if len(iter_conf) >= 2:
            ds, n_iter = iter_conf[:2]
            num_patches = default_patch_number
        if len(iter_conf) >= 3:
            num_patches = iter_conf[2]
        ts_scale_start = time.perf_counter()
        alignment_params = dict(
            debug=debug,
            debug_dir=debug_dir,
            forced_debug_dir=forced_debug_dir, # for cost overview
            align_config = AlignmentConfig(
                downscale=ds,
                mode=mode,
                dist_mode=dist,
                sigma_ref=None,
                sigma_mov=None,
                num_patches=num_patches
            )
        )
        # --------------------------------------------------------------------------------------------------------------
        # ------------------------------------------------------------------------------------------------- Debug images
        if debug:
            ds_img_mov_init = img_mov_pyr[ds]
            ds_img_mov = motion_model.warp(ds_img_mov_init, downscale=ds)  # register thumbnail based on previous model
            # debug_trace(ds_img_mov_init, ds, 999, prefix="_image_", suffix= "_mov_original")
            debug_trace(ds_img_mov, ds, iter, prefix="_image_" , suffix="mov_start")

        # --------------------------------------------------------------------------------------------------------------
        # --------------------------------------------------------------------- Downsample multispectral representation
        ts_ds_start = time.perf_counter()
        ds_msr_ref = msr_ref_pyr[ds]
        ds_msr_mov_init = msr_mov_pyr[ds]
        ts_ds_end = time.perf_counter()
        logging.warning("{:.2f}s elapsed in dowscale {}".format(ts_ds_end - ts_ds_start, ds))
        ts_warp_start = time.perf_counter()
        ds_msr_mov = motion_model.warp(ds_msr_mov_init, downscale=ds)  # register thumbnail based on previous model
        ts_warp_end = time.perf_counter()
        logging.warning("{:.2f}s elapsed in warping at scale {}".format(ts_warp_end - ts_warp_start, ds))
        debug_trace(ds_msr_mov, ds, iter, prefix="_msr_", suffix="__start", msr_mode=mode)

        # --------------------------------------------------------------------------------------------------------------
        # ----------------------------------------------------------------------------------------------- Iteration loop
        iter_list = range(1, n_iter+1)
        for _iter_current in iter_list:
            iter += 1
            ts_iter_start = time.perf_counter()
            # --------------------------------------------    COST SEARCH   --------------------------------------------
            # ---------------------------------------------------------------------- Cost + Vector field + Model fitting
            cost_dict = compute_cost(
                ds_msr_ref, ds_msr_mov,
                suffix="_it{:02d}".format(iter),
                prefix="ds{}_{}".format(ds, mode),

                **alignment_params
            )
            vpos, vector_field = brute_force_vector_field_search(
                costs=cost_dict["costs"],
                centers=cost_dict["centers"],
                downscale=ds
            )

            # --------------------------------------------------------------------------------------- Debug Vector field
            ax_vector_field = None
            img_mov_reg = None
            if debug:
                img_mov_reg = motion_model.warp(img_mov, downscale=1)
                # debug_trace(img_mov_reg, ds, iter, prefix="FLOW_", suffix="ALIGNED_GLOBALLY", debug_flag=True)
                displaced_image = warp_from_sparse_vector_field(img_mov_reg, vector_field)
                # np.save(osp.join(forced_debug_dir, "local_displacement"), {"img":img_mov_reg, "vector_field":vector_field})
                debug_trace(displaced_image, ds, iter, prefix="FLOW_", suffix="WARP_LOCAL", debug_flag=True)
                fig = plt.figure(figsize=(img_mov.shape[:2][::-1]), dpi=1)
                ax_vector_field = fig.add_subplot(111)

            motion_model_residual = MotionModelHomography(
                model=None, vector_pos=vpos, vector_field=vector_field,
                affinity=affinity,
                ax=ax_vector_field,
                # img= g2c(c2g(
                #     (255.*transform.resize(viz_msr(ds_msr_mov, msr_mode=mode), img_mov.shape, anti_aliasing=False)).astype(np.uint8)
                # )),
                img = img_mov_reg
                # debug=debug
            )
            if debug:
                debug_trace(
                    ax_vector_field, ds, iter,
                    prefix="FLOW_", suffix="VECTOR_FIELD_GLOBAL_ALIGNED", debug_flag=True
                )
            logging.info("iteration {} - {}".format(iter, motion_model_residual))
            motion_model.compose(motion_model_residual)

            # ----------------------------------------------    WARP   -------------------------------------------------
            # ----------------------------------------------------------------------------------------------- MSR images
            ds_msr_mov = motion_model.warp(ds_msr_mov_init, downscale=ds)
            debug_trace(ds_msr_mov, ds, iter, prefix="_msr_", suffix="_alignment", msr_mode=mode, debug_flag=True)
            # @TODO: every once in a while, we could warp the full res image...

            # --------------------------------------------------------------------------------------------- Debug images
            if debug:
                ds_img_mov = motion_model.warp(ds_img_mov_init, downscale=ds)
                debug_trace(ds_img_mov, ds, iter, prefix="_image_", suffix="alignment")
                out_img = motion_model.warp(img_mov, downscale=1)
                debug_trace(out_img, ds, iter, prefix="FULL_RES_ALIGN_", debug_flag=True)
            ts_iter_end = time.perf_counter()
            logging.warning("{:.2f}s elapsed at scale {} - iter {}".format(ts_iter_end - ts_iter_start, ds, iter))
        debug_trace(ds_msr_ref, ds, iter, prefix="_msr_", suffix="_ref", msr_mode=mode, debug_flag=True)
        if debug:
            ds_img_ref = img_ref_pyr[ds]
            debug_trace(ds_img_ref, ds, iter, prefix="_image_", suffix= "ref")
        ts_scale_end = time.perf_counter()
        logging.warning("{:.2f}s elapsed at scale {}".format(ts_scale_end - ts_scale_start, ds))
        iter +=1
    ts_end = time.perf_counter()
    logging.warning("\tTOTAL {:.2f}s elapsed for iterative scheme {}".format(ts_end - ts_start, iterative_scheme))
    out_img = motion_model.warp(img_mov, downscale=1)

    return out_img


# ------------------------------------------------------- Tests --------------------------------------------------------
# ----------------------------------------------- Vanilla alignment ----------------------------------------------------
def generate_test_data(t_x=2., t_y=-5., theta=-0.5, suffix=""):
    path = osp.join(osp.dirname(__file__), "..", "samples")
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    debug_dir = "_test_images_tx%d_ty%d_%ddeg%s"%(t_x, t_y, theta, suffix)
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    vis_img_moved_path = osp.join(debug_dir, "MOVED.jpg")
    vis_img_path = osp.join(debug_dir, "REF.jpg")
    thetar = np.deg2rad(theta)
    homog = np.eye(3)
    homog[:2, :2] = np.array([
        [np.cos(thetar), np.sin(thetar)],
        [-np.sin(thetar), np.cos(thetar)]]
    )
    homog[0, -1] = t_x
    homog[1, -1] = t_y

    if osp.isfile(vis_img_moved_path):
        return pr.Image(vis_img_path), pr.Image(vis_img_moved_path), debug_dir, homog
        # return pr.Image(np.zeros((5,5,3))), pr.Image(vis_img_moved_path), debug_dir, homog
    else:
        vis_img_moved = cv2.warpPerspective(vis_img.data, homog, vis_img.data.shape[:2][::-1])
        vis_img.save(vis_img_path)
        vis_img_moved = pr.Image(vis_img_moved)
        vis_img_moved.save(vis_img_moved_path)
    return vis_img, vis_img_moved, debug_dir, homog


# -------------------------------------- single scale cost + search + warp  --------------------------------------------
def alignment_system_single_scale_single_iter(
        img_ref, img_mov, debug_dir,
        align_config=AlignmentConfig(mode=COLORED, dist_mode=SSD, downscale=32)
):
    """
    Single scale - compute cost, search, warp
    """
    cost_file = osp.join(debug_dir, "ds32_colored_blocks_y5x5_search_y6x6_SSD__cost_search_.npy")
    if not osp.isfile(cost_file):
        cost_dict = run_multispectral_cost(
            img_ref, img_mov,
            debug_dir=debug_dir,
            align_config=align_config
        )
    else:
        cost_dict = np.load(cost_file, allow_pickle=True).item()
    vpos, vector_field = brute_force_vector_field_search(**cost_dict)
    homog_estim = MotionModelHomography(model=None, vector_pos=vpos, vector_field=vector_field, debug=True, affinity=True)
    return homog_estim


def test_alignment_system_single_scale_single_iter():
    """
    """
    vis_img, vis_img_moved, debug_dir, homog = generate_test_data(suffix="_single_scale")
    homog_estim = alignment_system_single_scale_single_iter(vis_img.data, vis_img_moved.data, debug_dir)
    img_mov_corrected = homog_estim.warp(vis_img_moved)
    pr.Image(img_mov_corrected).save(osp.join(debug_dir, "ALIGNED_NEW.jpg"))


def test_alignment_system_multi_scale_multi_iter():
    """
    """
    iterative_scheme = [(32, 12, 5), (16, 2, 5), (8, 1, 5), (4, 1, 5)]
    vis_img, vis_img_moved, debug_dir, homog = generate_test_data(
        t_x=20., t_y=120.4, theta =-15.,
        suffix="_Multi_scale_MSR_{}".format(iterative_scheme)
    )
    out_img = pyramidal_search(
        vis_img.data, vis_img_moved.data,
        debug_dir=debug_dir, debug=False,
        mode=LAPLACIAN_ENERGIES,
        dist=SSD,
        iterative_scheme=iterative_scheme,
        sigma_mov=5,
        sigma_ref=5,
        affinity=True
    )
    pr.Image(out_img.astype(np.uint8)).save(osp.join(debug_dir, "REGISTERED_PYR.jpg"))


# ----------------------------------------- Run on images using pyramid ------------------------------------------------
def align_images(
        vis_img=None, nir_img=None,
        debug_dir="", debug=False, affinity=True,
        iterative_scheme = [(4, 1, 5), (4, 1, 15), (2, 1, 15)]
    ):
    mode = LAPLACIAN_ENERGIES
    dist = NTG
    debug_dir = debug_dir+"_{}_{}_{}".format(mode, dist, iterative_scheme)
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    out_img_path = osp.join(debug_dir, "REGISTERED_PYR.jpg")
    if not osp.isfile(out_img_path):
        vis_img.save(osp.join(debug_dir, "REF.jpg"))
        nir_img.save(osp.join(debug_dir, "MOVED.jpg"))

        out_img = pyramidal_search(
            vis_img.data, nir_img.data,
            debug_dir=None, debug=debug,
            iterative_scheme = iterative_scheme,
            mode=mode,
            dist=dist,
            affinity=affinity

        )
        pr.Image(out_img.astype(np.uint8)).save(out_img_path)
    else:
        out_img = pr.Image(out_img_path).data


def run_alignment_disparity():
    path = osp.join(osp.dirname(__file__), "..", "Image_424")
    vis_img = pr.Image(osp.join(path, "HYPERLAPSE_0422_PL4_DIST.tif"))
    nir_img = pr.Image(osp.join(path, "HYPERLAPSE_0429_PL4_DIST.tif"))
    align_images(vis_img, nir_img,
                 debug_dir="img_424_disparity",
                 iterative_scheme = [(16, 6, 5), (8, 1, 15), (4, 1, 15), (4, 1, 30)])


def run_alignment_multispectral():
    path = osp.join(osp.dirname(__file__), "..", "samples")
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
    align_images(
        vis_img, nir_img,
        debug_dir="PWC_MSR",
        debug=False,
        affinity=False,
        iterative_scheme = [(32, 3, 4), (16, 2, 5), (8, 2, 5), (4, 1, 5), (4, 1, 10), (4, 1, 15)]
    )


if __name__ == "__main__":
    log = logging.getLogger()
    # log.setLevel(logging.INFO)
    log.setLevel(logging.WARNING)
    # test_alignment_system_single_scale_single_iter()
    # test_alignment_system_multi_scale_multi_iter()

    # run_alignment_disparity()
    run_alignment_multispectral()

