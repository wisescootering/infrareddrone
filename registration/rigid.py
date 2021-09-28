import os.path as osp
import numpy as np
from registration.newton import newton_iter, quadric_approximation
from irdrone.registration import geometric_rigid_transform_estimation
import logging
from registration.cost import align
from registration.constants import LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED, SSD, NTG
import irdrone.process as pr
import cv2
from skimage import transform
from os import mkdir

def minimum_cost(cost):
    """Find the argmin in a single cost area (multichannel) and refine with quadratic form subpixel search
    :param cost:
    :return:
    """
    amin_index = np.unravel_index(np.argmin(cost.sum(axis=-1)), (cost.shape[0], cost.shape[1]))
    init_position = np.array([amin_index[1]-cost.shape[1]//2, amin_index[0]-cost.shape[0]//2])
    neighborhood_size = 1
    if amin_index[0] < neighborhood_size or amin_index[0] > cost.shape[0]-1-neighborhood_size or amin_index[1] < neighborhood_size or amin_index[1] > cost.shape[1]-1-neighborhood_size:
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
    :param costs:
    :param centers:
    :param downscale:
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
        self.model = geometric_rigid_transform_estimation(vector_pos, vector_field, debug=debug, affinity=affinity)
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
        """Downscale shall be dealt with here"""
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
        self.model_history = self.model_history.prepend(new_model.model)
    def estimate(self, *args, **kwargs):
        """
        Estimate motion model from data such as
            - a vector field
            - cost function using optimization algorithm

        self.model = model_estimation(*args)
        """
        pass


def dummy_cost_func(_img_ref, _img_mov, **kwargs):
    cost_file = osp.join(osp.dirname(__file__), "..", "samples" , "cost.npy")
    cost_dict = np.load(cost_file, allow_pickle=True).item()
    return cost_dict


def pyramidal_search(
        img_ref, img_mov, debug_dir=None, dummy_mode=False, debug=True,
        iterative_scheme=[(32, 12), (16, 2), (8, 1),],
        mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][-1],
        dist=[SSD, NTG][0],
    ):
    """
    """
    forced_debug_dir = debug_dir
    if not debug:
        debug_dir = None # disable most traces if debug is set to False
    def debug_trace(img, ds=1, iter="", suffix="", prefix="", debug_flag=None):
        """debug_flag allows to force debugging trace if set to True"""
        if debug_flag is None:
            debug_flag = debug
        if debug_flag and forced_debug_dir is not None:
            img_save = img if img.dtype == np.uint8 else ((img*255).clip(0, 255)).astype(np.uint8)
            pr.Image(img_save).save(osp.join(forced_debug_dir, "{}it{:02d}_ds{:02d}_{}.jpg".format(prefix, iter, ds, suffix)))
    motion_model = MotionModelHomography()
    if dummy_mode:
        compute_cost, alignment_params = dummy_cost_func, dict()
    else:
        compute_cost = align
        alignment_params = dict(
            downscale=1, debug_dir=debug_dir,
            mode=mode,
            dist_mode=dist,
            sigma_ref=None, # @TODO: remove the sigmas
            sigma_mov=None,
            debug=debug
        )
    # @TODO: move spectral reperesentation here! downscale, warp and estimate on spectral representations images...
    downscale_func = lambda img, ds: transform.pyramid_reduce(img, downscale=ds, multichannel=True)
    iter = 0
    for ds, n_iter in iterative_scheme:
        ds_img_ref = downscale_func(img_ref, ds)
        ds_img_mov = downscale_func(img_mov, ds)
        ds_img_mov_init = ds_img_mov.copy()
        ds_img_mov = motion_model.warp(ds_img_mov_init, downscale=ds)
        debug_trace(ds_img_mov_init, ds, 0, suffix="_original")
        debug_trace(ds_img_ref, ds, 0, suffix="_ref")
        debug_trace(ds_img_mov, ds, 0, suffix="_start")
        iter_list = range(1, n_iter+1)
        for iter_current in iter_list:
            iter +=1
            cost_dict = compute_cost(ds_img_ref, ds_img_mov, prefix="ds{:02d}_".format(ds), suffix="_it{:02d}".format(iter), **alignment_params)
            vpos, vector_field = brute_force_vector_field_search(costs=cost_dict["costs"], centers=cost_dict["centers"], downscale=ds)
            motion_model_residual = MotionModelHomography(model=None, vector_pos=vpos, vector_field=vector_field, affinity=True) #, debug=debug)
            print(iter, motion_model_residual)
            motion_model.compose(motion_model_residual)
            ds_img_mov = motion_model.warp(ds_img_mov_init, downscale=ds)
            debug_trace(ds_img_mov, ds, iter, suffix="alignment")
            out_img = motion_model.warp(img_mov, downscale=1)
            debug_trace(out_img, ds, iter, prefix="ALIGN_", debug_flag=True)  # FORCE DEBUGGING (minimal trace)
    out_img = motion_model.warp(img_mov, downscale=1)
    return out_img


def align_data(img_ref, img_mov, debug_dir):
    cost_file = osp.join(debug_dir, "ds_32_blocks_y5x5_colored_SSD__cost_search.npy")
    if not osp.isfile(cost_file):
        cost_dict = align(
            img_ref, img_mov,
            downscale=32,
            # debug=False, debug_dir= None,
            debug_dir=debug_dir,
            mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][-1],
            dist_mode=[SSD, NTG][0]
        )
        # cost_file = np.array(costs)
    else:
        cost_dict = np.load(cost_file, allow_pickle=True).item()
    vpos, vector_field = brute_force_vector_field_search(**cost_dict)
    homog_estim = MotionModelHomography(model=None, vector_pos=vpos, vector_field=vector_field, debug=True, affinity=True)
    print(homog_estim)
    return homog_estim


def generate_test_data(t_x=2., t_y=-5., theta=-0.5, suffix=""):
    # t_x, t_y, theta = -2. ,2., -0.5
    # t_x, t_y, theta = -20. ,2., 1.
    # t_x, t_y, theta = -20., 2.8, 4.
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


def test_alignment_system():
    vis_img, vis_img_moved, debug_dir, homog = generate_test_data(t_x=-20, t_y=135.4, theta = -7., suffix="_multi_scale")
    out_img = pyramidal_search(
        vis_img.data, vis_img_moved.data,
        # debug_dir=None, debug=True,  # -> SHOW TRACES, NOT SAVING ANYTHING TO DISK
        # debug_dir=None, debug=False,  # -> NO TRACES AT ALL, NOT SAVING ANYTHING TO DISK
        # debug_dir=debug_dir, debug=False, # -> FORCE ONLY MANDATORY TRACES
        # debug_dir=debug_dir, debug=True, # -> FORCE ALL TRACES TO DISK
        debug_dir=debug_dir, debug=True,
        mode=COLORED,
        dist=SSD
    )
    # homog_estim = align_data(vis_img.data, vis_img_moved.data, debug_dir)
    # img_mov_corrected = homog_estim.warp(vis_img_moved)
    pr.Image(out_img.astype(np.uint8)).save(osp.join(debug_dir, "ALIGNED_PYR.jpg"))


def test_alignment_system_single_scale():
    vis_img, vis_img_moved, debug_dir, homog = generate_test_data(suffix="_single_scale")
    homog_estim = align_data(vis_img.data, vis_img_moved.data, debug_dir)
    img_mov_corrected = homog_estim.warp(vis_img_moved)
    pr.Image(img_mov_corrected).save(osp.join(debug_dir, "ALIGNED_NEW.jpg"))


def test_alignement_real():
    path = osp.join(osp.dirname(__file__), "..", "samples")
    vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
    nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
    mode = LAPLACIAN_ENERGIES
    dist = NTG
    iterative_scheme = [(32, 4), (32, 2), (16, 2), (8, 1),]
    debug_dir = "_iterative_multiscale_multispectral_alignment_{}_{}_{}".format(mode, dist, iterative_scheme)
    if not osp.isdir(debug_dir):
        mkdir(debug_dir)
    out_img = pyramidal_search(
        vis_img.data, nir_img.data,
        # debug_dir=None, debug=True,  # -> SHOW TRACES, NOT SAVING ANYTHING TO DISK
        # debug_dir=None, debug=False,  # -> NO TRACES AT ALL, NOT SAVING ANYTHING TO DISK
        # debug_dir=debug_dir, debug=False, # -> FORCE ONLY MANDATORY TRACES
        # debug_dir=debug_dir, debug=True, # -> FORCE ALL TRACES TO DISK
        debug_dir=debug_dir, debug=True,
        iterative_scheme = iterative_scheme,
        mode=mode,
        dist=dist
    )
    # homog_estim = align_data(vis_img.data, vis_img_moved.data, debug_dir)
    # img_mov_corrected = homog_estim.warp(vis_img_moved)
    pr.Image(out_img.astype(np.uint8)).save(osp.join(debug_dir, "ALIGNED_PYR.jpg"))


if __name__ == "__main__":
    log = logging.getLogger()
    log.setLevel(logging.INFO)
    test_alignment_system_single_scale()
    test_alignment_system()
    test_alignement_real()
