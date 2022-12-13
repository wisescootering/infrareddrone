import irdrone.utils as ut
import irdrone.process as pr
from registration.warp_flow import warp
import numpy as np
import logging
import os.path as osp
import registration.rigid as rigid
from irdrone.semi_auto_registration import manual_warp, ManualAlignment, Transparency, Absgrad, mellin_transform
from skimage import transform
import os
osp = os.path
import time
from datetime import datetime, timedelta
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.pyplot as plt
import interactive.imagepipe as ipipe
import cv2
import argparse
from pathlib import Path
from copy import deepcopy
import traceback
from config import CROP

try:
    conda_env_name = os.environ['CONDA_DEFAULT_ENV']
except:
    conda_env_name = None
    logging.warning("cannot retrieve conda env")
exif_dict_minimal = np.load(osp.join(osp.dirname(__file__), "utils", "minimum_exif_dji.npy"), allow_pickle=True).item()
TRACES = ["vis", "nir", "vir", "ndvi"]
VIS, NIR, VIR, NDVI = TRACES

def colorMapNDVI():
    #  définition de la palette des couleurs pour l'indice NDVI à partir de couleurs prédéfinies
    #  voir les couleurs par exemple ici   http://xymaths.free.fr/Informatique-Programmation/Couleurs/Liste.php
    colors = ["black",
              "dimgray",
              "lightgray",
              "burlywood",
              "lawngreen",
              "lightseagreen",
              "forestgreen",
              "lightgray"
              ]
    #   répartition des plages de couleurs  (entre 0 et 1)
    nodes = [0.0,
             35. / 100,
             45. / 100,
             51. / 100,
             60. / 100,
             65. / 100,
             75. / 100,
             1.0
             ]
    myColorMap = LinearSegmentedColormap.from_list("mapNDVI", list(zip(nodes, colors)))

    # Autre possibilité: egale répartition entre les couleurs
    # myColorMap = LinearSegmentedColormap.from_list("mapNDVI", colors)  #

    return myColorMap


class VegetationIndex(ipipe.ProcessBlock):
    """
    """
    def apply(self, vis, nir, alpha, **kwargs):
        red = vis[:, :, 0]
        nir_mono = np.mean(nir, axis=-1)
        nir_mono *= 0.5/np.mean(nir_mono)  # @TODO: correctly expose the NIR channel
        nir_mono = (1+alpha)*nir_mono*0.5/np.average(nir_mono)
        red = red*0.5/np.average(red)
        ndvi = ((nir_mono - red)/(nir_mono + red)) # @TODO: enhance final constrast here
        return ndvi


def ndvi(vis_img, nir_img, out_path=None, exif=None, gps=None, image_in=None):
    ndvi = VegetationIndex("NDVI", vrange=[(-1., 1., 0)], inputs=[1, 2], outputs=[0,], )
    ipi = ipipe.ImagePipe(
        [vis_img, nir_img],
        sliders=[ndvi],
        floatpipe=True
    )
    ipi.floatColorBar(maxColorBar=1., minColorBar=-1, colorBar=colorMapNDVI())
    if out_path is None:
        ipi.gui()
    else:
        ipi.set(
            **{
                "NDVI":[-0.1],
            }
        )
        # ipi.gui()
        # try:
            # todo: fix missing exif datas in ndvi file.  La ligne en dessous ne marche pas !!!
        out_img = ipi.save(out_path)
        if image_in is not None:
            pr.copy_metadata(image_in, out_path)




def vir(vis_img, nir_img, out_path=None, exif=None, gps=None, image_in=None):
    vir = vis_img.copy()
    vir[:, :, 0] = np.mean(nir_img, axis=-1)
    vir[:, :, 0] *= 0.5/np.mean(vir[:, :, 0]) # @TODO: correctly expose the NIR channel
    vir[:, :, 1] = vis_img[:, :, 0]
    vir[:, :, 2] = vis_img[:, :, 1]
    if out_path is None:
        pr.Image(vir).show()
    else:
        if out_path.lower().endswith("tif"):
            pr.Image(vir).save(out_path, exif=exif, gps=gps)
        else:
            recontrasted_image = (ut.contrast_stretching(vir.clip(0., 1.))[0]*255).astype(np.uint8)
            im = pr.Image(recontrasted_image)
            im.path = image_in
            im.save(out_path, exif=exif, gps=gps)
            # pr.Image((vir*255).clip(0, 255).astype(np.uint8)).save(out_path)


def user_assisted_manual_alignment(ref, mov, cals, yaw=0, pitch=0, roll=0):
    ROTATE = "Rotate"
    rotate3d = ManualAlignment(
        ROTATE,
        slidersName=["YAW [Horizontal]", "PITCH [Vertical]", "ROLL"],
        inputs=[1, 2],
        outputs=[0],
        vrange=[
            (-30., 30, yaw), (-30., 30, pitch), (-5., 5, roll)
        ]
    )
    rotate3d.set_movingcalib(cals["movingcalib"])
    rotate3d.set_refcalib(cals["refcalib"])
    alpha = Transparency("Alpha", inputs=[0, 1], vrange=(-1., 1., -0.45))
    absgrad_viz = Absgrad("Absgrad visualize", inputs=[0, 1], outputs=[0, 1], vrange=(0, 1, 1))
    ipi = ipipe.ImagePipe(
        [ref, mov],
        rescale=None,
        sliders=[
            rotate3d,
            absgrad_viz,
            alpha
        ]
    )
    ipi.gui()
    return rotate3d.alignment_parameters

def build_x_poly_values(_x):
    x = np.array([_x]).T
    a_mat = np.concatenate([x**2, x, np.ones_like(x)], axis=1)
    return a_mat

def poly_fit_1d(profile, amin, neighborhood = 1):
    '''
    [x1², x1 , 1]  * [ a ] = [y1]
    [x2², x2 , 1]    [ b ]   [y2]
        ...          [ c ]    ...
    '''
    if neighborhood==1:
        y = profile[amin-1:amin+1+1]
        x = np.array([-1, 0, 1])
    if neighborhood==2:
        y = profile[amin-2:amin+2+1]
        x = np.array([-2, -1, 0, 1, 2])
    a_mat = build_x_poly_values(x)
    a_mat_pinv = np.linalg.pinv(a_mat) #.shape, y.shape
    return np.dot(a_mat_pinv, y)

def coarse_roll_estimation(msr_ref, msr_mov, alignment_config, roll_search_window=10, debug=False, debug_dir=None):
    if roll_search_window==0:
        return 0.
    try:
        align_config_polar = deepcopy(alignment_config)
        align_config_polar.search_x = 0
        align_config_polar.search_y = roll_search_window
        vis_rep_polar, niru_rep_polar = mellin_transform(msr_ref, msr_mov)
        cost_dict_polar = rigid.compute_cost_surfaces_with_traces(
            vis_rep_polar, niru_rep_polar,
            debug=debug,
            suffix="Polar search",
            prefix="",
            align_config=align_config_polar,
            debug_dir=debug_dir
        )
        profile = cost_dict_polar["costs"][0, 0, :, 0, :].sum(axis=-1)
        amin, min_cost = np.argmin(profile), np.min(profile)
        coarse_roll_angle = amin - len(profile)//2
        plot = debug or debug_dir is not None
        if plot:
            plt.figure(figsize=(10, 10))
            plt.plot(np.arange(len(profile)) - len(profile)//2, profile, "r--", label="cost function")
            plt.plot(amin- len(profile)//2, min_cost, "go")
        
        neighborhood_refine = 1
        if amin > neighborhood_refine and amin < len(profile)-neighborhood_refine-1:
            poly_coeffs = poly_fit_1d(profile, amin, neighborhood = neighborhood_refine)
            coarse_roll_angle = amin - poly_coeffs[1]/(2*poly_coeffs[0]) - len(profile)//2
            refined_argmin = - poly_coeffs[1] /(2 * poly_coeffs[0])
            refined_min = poly_coeffs[0]*refined_argmin**2 + poly_coeffs[1]*refined_argmin+poly_coeffs[2]
            x_fit = build_x_poly_values(np.linspace(-2, 2, num=100))
            y_fit = np.dot(x_fit, poly_coeffs)
            plt.plot(x_fit[:, 1]+amin - len(profile)//2, y_fit, "b-", label="Parabola fitting")
            plt.plot(amin+refined_argmin - len(profile)//2, refined_min, "mo", label=f"REFINED {coarse_roll_angle}")
        
        if plot:
            plt.title("Polar matching cost")
            plt.xlabel("Polar Angle")
            plt.ylabel("Matching cost")
            plt.legend()
            plt.grid()
            if debug and debug_dir is None:
                plt.show()
            elif debug_dir is not None:
                debug_fig_main = osp.join(debug_dir, "polar_matching profile")
                plt.savefig(debug_fig_main)
            plt.close()
       
    except:
        coarse_roll_angle = 0.
        logging.warning("Cannot find refined roll!")
        traceback.print_exc()
    return coarse_roll_angle

def coarse_alignment(ref_full, mov_full, cals, yaw_main, pitch_main, roll_main, extension=1.4,
                     debug_dir=None, debug=False):
    ts_start_coarse_search = time.perf_counter()
    ds = 32
    # -------------------------------------------------------------- Full res : Undistort NIR fisheye with a larger FOV
    mov_w_full = manual_warp(
        ref_full, mov_full,
        yaw_main, pitch_main, roll_main,
        refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
        refinement_homography=None,
        bigger_size_factor=extension,
    )
    # ------------------------------------------------------------------------------------ Multi-spectral representation
    # @TODO : REFACTOR! This is exactly the same kind of data preparation for pyramidal search
    msr_mode = rigid.LAPLACIAN_ENERGIES
    # @TODO : Fix Gaussian
    msr_ref_full = rigid.multispectral_representation(ref_full, mode=msr_mode, sigma_gaussian=3.).astype(np.float32)
    # @TODO: re-use MSR of full res!
    msr_mov_full = rigid.multispectral_representation(mov_w_full, mode=msr_mode, sigma_gaussian=1.).astype(np.float32)
    msr_ref = transform.pyramid_reduce(msr_ref_full, downscale=ds, channel_axis=-1).astype(np.float32)
    msr_mov = transform.pyramid_reduce(msr_mov_full, downscale=ds, channel_axis=-1).astype(np.float32)
    pad_y = (msr_mov.shape[0]-msr_ref.shape[0])//2
    pad_x = (msr_mov.shape[1]-msr_ref.shape[1])//2
    align_config = rigid.AlignmentConfig(num_patches=1, search_size=pad_x, mode=msr_mode)
    padded_ref = np.zeros_like(msr_mov)
    padded_ref[pad_y:pad_y+msr_ref.shape[0], pad_x:pad_x+msr_ref.shape[1], :] = msr_ref
    # pr.Image(rigid.viz_msr(mov_w, None)).save(osp.join(debug_dir, "_LOWRES_MOV_INIT.jpg"))
    if debug_dir is not None:
        pr.Image(rigid.viz_msr(msr_mov, align_config.mode)).save(osp.join(debug_dir, "_PADDED_LOWRES_MOV_MSR.jpg"))
        pr.Image(rigid.viz_msr(padded_ref, align_config.mode)).save(osp.join(debug_dir, "_PADDED_LOWRES_MSR_REF.jpg"))
    cost_dict = rigid.compute_cost_surfaces_with_traces(
        msr_mov, padded_ref,
        debug=debug, debug_dir=debug_dir,
        prefix="Full Search", suffix="",
        align_config=align_config,
        forced_debug_dir=debug_dir,
    )
    focal = cals["refcalib"]["mtx"][0, 0].copy()
    try:
        translation = -ds*rigid.minimum_cost_max_hessian(cost_dict["costs"][0,0, :, :, :], debug=debug)
    except:
        logging.warning("Max of Hessian failed!")  # @ TODO: handle the case of argmax close to the edge!
        trans, _, _ = rigid.minimum_cost(cost_dict["costs"][0, 0, :, :, :])
        translation = -ds*trans
    yaw_refine = np.rad2deg(np.arctan(translation[0]/focal))
    pitch_refine = np.rad2deg(np.arctan(translation[1]/focal))
    print("2D translation {}".format(translation, yaw_refine, pitch_refine))
    roll_refine = 0.
    # roll_refine = coarse_roll_estimation(msr_ref, msr_mov, alignment_config=align_config, roll_search_window=10)
    roll_refine = coarse_roll_estimation(msr_ref_full, msr_mov_full, alignment_config=align_config, roll_search_window=5, debug=debug, debug_dir=debug_dir)
    print(f"Roll {roll_refine}°")
    ts_end_coarse_search = time.perf_counter()
    logging.warning("{:.2f}s elapsed in coarse search".format(ts_end_coarse_search - ts_start_coarse_search))
    ts_start_warp = time.perf_counter()
    if debug_dir is not None and debug:
        mov_wr = manual_warp(
            msr_ref, cv2.resize(mov_full, (mov_full.shape[1]//ds, mov_full.shape[0]//ds)),
            yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main + roll_refine,
            refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
            geometric_scale=1/ds, refinement_homography=None,
            )
        pr.Image(rigid.viz_msr(mov_wr, None)).save(osp.join(debug_dir, "_LOWRES_REGISTERED.jpg"))
        pr.Image(rigid.viz_msr(cv2.resize(ref_full, (ref_full.shape[1]//ds, ref_full.shape[0]//ds)), None)).save(
            osp.join(debug_dir, "_LOWRES_REF.jpg"))
    mov_wr_fullres = manual_warp(
        ref_full, mov_full,
        yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main + roll_refine,
        refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
        geometric_scale=None, refinement_homography=None,
    )
    ts_end_warp = time.perf_counter()
    logging.warning("{:.2f}s elapsed in warping from coarse search".format(ts_end_warp - ts_start_warp))
    if debug_dir is not None:
        pr.Image(ref_full).save(osp.join(debug_dir, "FULLRES_REF.jpg"))
        pr.Image(mov_wr_fullres).save(osp.join(debug_dir, "FULLRES_REGISTERED_COARSE.jpg"))
    return mov_wr_fullres, dict(yaw=yaw_main + yaw_refine, pitch=pitch_main + pitch_refine, roll=roll_main+roll_refine)


def align_raw(vis_path, nir_path, cals_dict, debug_dir=None, debug=False, extension=1.4, manual=True, init_angles=[0., 0., 0.], motion_model_file = None):
    """
    :param vis_path: Path to visible DJI DNG image
    :param nir_path: Path to NIR SJCAM M20 RAW image
    :param cals_dict: Geometric calibration dictionary.
    :param debug_dir: traces folder
    :param extension: extend the FOV of the NIR camera compared to the DJI camera 1.4 by default, 1.75 is ~maximum
    :return:
    """
    cals = deepcopy(cals_dict)
    if debug_dir is not None and not osp.isdir(debug_dir):
        os.mkdir(debug_dir)
    if debug_dir is not None:
        motion_model_file = osp.join(debug_dir, "motion_model")
    ts_start = time.perf_counter()
    vis = pr.Image(vis_path)
    nir = pr.Image(nir_path)
    vis_undist = warp(vis.data, cals["refcalib"], np.eye(3))
    vis_undist = pr.Image(vis_undist)
    vis_undist_lin = warp(vis.lineardata, cals["refcalib"], np.eye(3))
    # distorsion has been compensated on the reference.
    cals_ref = cals["refcalib"]
    cals_ref["dist"] *= 0.
    cals["refcalib"] = cals_ref
    ref_full = vis_undist.data
    mov_full = nir.data
    ts_end_load = time.perf_counter()
    logging.warning("{:.2f}s elapsed in loading full resolution RAW".format(ts_end_load - ts_start))
    if motion_model_file is None or not osp.isfile(motion_model_file+".npy"):
        if manual:
            alignment_params = user_assisted_manual_alignment(ref_full, mov_full, cals, init_angles[0], init_angles[1], init_angles[2])
            yaw_main, pitch_main, roll_main = alignment_params["yaw"], alignment_params["pitch"], alignment_params["roll"]
        else:
            yaw_main, pitch_main, roll_main = init_angles
        mov_wr_fullres, coarse_rotation_estimation = coarse_alignment(
            ref_full, mov_full, cals,
            yaw_main, pitch_main, roll_main,
            extension=extension,  # FOV extension
            debug_dir=debug_dir, debug=debug
        )
        motion_model = rigid.pyramidal_search(
            ref_full, mov_wr_fullres,
            iterative_scheme=[(16, 2, 4, 8), (16, 2, 5), (4, 3, 5)],
            mode=rigid.LAPLACIAN_ENERGIES, dist=rigid.NTG,
            debug=debug, debug_dir=debug_dir,
            affinity=False,
            sigma_ref=5.,
            sigma_mov=3.
        )
        homog = motion_model.rescale(downscale=1.)
        full_motion_model = coarse_rotation_estimation.copy()
        full_motion_model["homography"] = homog
        full_motion_model["vector_field"] = motion_model.vector_field
        full_motion_model["previous_homography"] = motion_model.previous_model
        if motion_model_file is not None:
            np.save(motion_model_file, full_motion_model, allow_pickle=True)
    else:
        logging.warning("Loading motion model!")
        full_motion_model = np.load(motion_model_file+".npy", allow_pickle=True).item()

    if debug_dir is not None:
        mov_w_final_yowo_full = manual_warp(
            ref_full, mov_full,
            full_motion_model["yaw"], full_motion_model["pitch"], full_motion_model["roll"],
            refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
            geometric_scale=None, refinement_homography=full_motion_model["previous_homography"],
            vector_field=full_motion_model["vector_field"]
        )  # you only warp once!
        pr.Image(mov_w_final_yowo_full).save(osp.join(debug_dir, "FULLRES_REGISTERED_REFINED_WARPED_ONCE_ONLY.jpg"))
    ts_start_yowo = time.perf_counter()
    mov_w_linear_local = manual_warp(
        ref_full, nir.lineardata,
        full_motion_model["yaw"], full_motion_model["pitch"], full_motion_model["roll"],
        refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
        geometric_scale=None,
        refinement_homography=full_motion_model["previous_homography"],
        vector_field=full_motion_model["vector_field"]
    )  # you only warp once!

    mov_w_linear_global = manual_warp(
        ref_full, nir.lineardata,
        full_motion_model["yaw"], full_motion_model["pitch"], full_motion_model["roll"],
        refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
        geometric_scale=None,
        refinement_homography=full_motion_model["homography"],
    )  # global warp!
    ts_end = time.perf_counter()
    logging.warning("{:.2f}s elapsed in global and local unique warp".format(ts_end - ts_start_yowo))
    logging.warning("{:.2f}s elapsed in total alignment".format(ts_end - ts_start))
    full_motion_model["initialization_angles"] = init_angles
    full_motion_model["initialization"] = {"yaw": init_angles[0], "pitch": init_angles[1], "roll": init_angles[2]}
    return vis_undist_lin, mov_w_linear_local, mov_w_linear_global, full_motion_model
    # return ref_full, mov_w_final_yowo_full



def write_manual_bat_redo(vis_pth, nir_pth_list, debug_bat_pth, out_dir=None, debug=False, async_suffix=None, multispectral_folder=None, angles=None):
    if out_dir is None:
        out_dir = osp.abspath(debug_bat_pth.replace(".bat", ""))
    with open(debug_bat_pth, "w") as fi:
        if conda_env_name is not None:
            fi.write("call activate {}\n".format(conda_env_name))
        for id_sync, nir_pth in enumerate(nir_pth_list):
            out_dir_current = out_dir
            if async_suffix is not None:
                out_dir_current = out_dir_current + "_async_{}".format(async_suffix[id_sync])
            cmd = "REM " if id_sync>0 else ""
            cmd+= "python {} --images {} {} --manual --outdir {} {}".format(
                "\""+osp.abspath(__file__)+"\"",
                "\""+vis_pth+"\"", "\""+nir_pth+"\"",
                "\""+out_dir_current+"\"",
                "--debug" if debug else ""
            )
            if multispectral_folder is not None:
                cmd+= "--multispectral-folder "+ "\""+osp.abspath(multispectral_folder)+"\""
            if angles is not None:
                cmd += f" --angles {angles[0]:.3f} {angles[1]:.3f} {angles[2]:.3f}"
            cmd+="\n"
            fi.write(cmd)
        fi.write("call deactivate\n")

def process_raw_pairs(
        sync_pairs,
        cals=dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW")),
        extension=1.4,
        debug_folder=None, out_dir=None, manual=False, debug=False,
        crop=None, listPts=None, option_alti='takeoff',
        clean_proxy=False,
        multispectral_folder=None,
        traces=[VIS, NIR, VIR, NDVI],
        angles=None,
        skip=False
    ):
    """
    listPts [optional]: contains all metadata & theoretical angles
    """
    # if debug_folder is None:
    #     debug_folder = osp.dirname(sync_pairs[0][0])
    if out_dir is None:
        out_dir = osp.join(osp.dirname(sync_pairs[0][0]), "_RESULTS")
    if not osp.exists(out_dir):
        os.mkdir(out_dir)
    motion_model_list = []
    for index_pair, (vis_pth, nir_pth) in enumerate(sync_pairs):
        if angles is None:
            yaw_init, pitch_init, roll_init = 0., 0., 0.
        else:
            assert len(angles) == 3
            yaw_init, pitch_init, roll_init = angles
        if listPts is not None:
            yaw_init = listPts[index_pair].yawIR2VI
            pitch_init = listPts[index_pair].pitchIR2VI
            roll_init = listPts[index_pair].rollIR2VI
            logging.info(f"INIT ANGLES FROM EXIF: yaw {yaw_init}, pitch {pitch_init}, roll {roll_init}")
        angles = [yaw_init, pitch_init, roll_init]
        # RELOAD PREVIOUSLY COMPUTED MOTION FILE
        motion_model_file = osp.join(out_dir, osp.basename(vis_pth[:-4])+"_motion_model")
        if not osp.exists(motion_model_file + ".npy"):
            motion_model_file = None
        else:
            logging.info(f"Using cached motion file {motion_model_file}")
            if skip:
                if listPts is not None:
                    motion_model = np.load(motion_model_file+".npy", allow_pickle=True).item()
                    listPts[index_pair].yawCoarseAlign = motion_model["yaw"]
                    listPts[index_pair].pitchCoarseAlign = motion_model["pitch"]
                    listPts[index_pair].rollCoarseAlign = motion_model["roll"]
                    listPts[index_pair].motion_model = motion_model
                logging.info(f"SKIP IMAGE PROCESSING - loaded motion from {motion_model_file}")
                continue
        logging.warning("processing {} {}".format(osp.basename(vis_pth), osp.basename(nir_pth)))
        
        # DEBUG FOLDER
        if debug_folder is not None:
            debug_dir = osp.join(debug_folder, osp.basename(vis_pth)[:-4]+"_align_traces" + ("_manual" if manual else ""))
        else:
            debug_dir = None

        # REDO.bat
        if os.name == "nt":
            offset_async = [offset for offset in [0, -1, +1, -2, +2]
                        if (index_pair+offset >=0 and index_pair+offset<len(sync_pairs))]
            nir_pth_async = [sync_pairs[index_pair+offset][1] for offset in offset_async]
            write_manual_bat_redo(vis_pth, nir_pth_async,
                              osp.join(out_dir, osp.basename(vis_pth[:-4])+"_REDO_ASYNC.bat"),
                              async_suffix=offset_async,
                              debug=False,
                              multispectral_folder=multispectral_folder,
                              angles=angles)
            write_manual_bat_redo(vis_pth, [nir_pth], osp.join(out_dir, osp.basename(vis_pth[:-4])+"_REDO.bat"), debug=False, multispectral_folder=multispectral_folder, angles=angles)
            write_manual_bat_redo(vis_pth, [nir_pth], osp.join(out_dir, osp.basename(vis_pth[:-4])+"_DEBUG.bat"), debug=True, multispectral_folder=multispectral_folder, angles=angles)


        gps_vis = pr.Image(vis_pth).gps
        date_vis = pr.Image(vis_pth).date   # todo fix error  date Exif (Date/Time Original and Create Date
        try:
            #option_alti = 'sealevel'  #   geo, ground, sealevel, takeoff

            if option_alti == 'geo':
                # Substitutes of drone altitude to the takeoff by altitude of ground to sea level
                gps_vis['altitude'] = listPts[index_pair].altGeo
                logging.info(f"Use altitude of ground to sea level : {gps_vis['altitude']} m")
            if option_alti == 'ground':
                #Substitutes of drone altitude to the takeoff by drone altitude to ground.
                gps_vis['altitude'] = listPts[index_pair].altGround
                logging.info(f"Use altitude of drone to ground  : {gps_vis['altitude']} m")
            if option_alti == 'sealevel':
                #Substitutes of drone altitude to the takeoff by drone altitude to ground.
                gps_vis['altitude'] = listPts[index_pair].altGeo + listPts[index_pair].altGround
                logging.info(f"Use altitude of drone to sea level  : {gps_vis['altitude']} m")
            if option_alti == 'takeoff':
                # altitude of droe to the takeoff.
                logging.info(f"Use altitude of drone to takeoff  : {gps_vis['altitude']} m")
                gps_vis['altitude'] = listPts[index_pair].altTakeOff
        except Exception as exc:
            logging.warning(f"{exc} use altitude drone to takeoff instead: {gps_vis['altitude']} m")

        ref_full, aligned_full, align_full_global, motion_model = align_raw(
            vis_pth, nir_pth, cals,
            debug_dir=debug_dir, debug=debug,
            manual=manual,
            extension=extension,
            init_angles=[yaw_init, pitch_init, roll_init],
            motion_model_file=motion_model_file
        )
        
        # AGGREGATED RESULTS!
        if crop is not None:
            aligned_full = aligned_full[crop:-crop, crop:-crop, :]
            align_full_global = align_full_global[crop:-crop, crop:-crop, :]
            ref_full = ref_full[crop:-crop, crop:-crop, :]
        # Systematically write motion model!
        if motion_model is not None:
            if motion_model_file is None:
                motion_model_file = osp.join(out_dir, osp.basename(vis_pth[:-4])+"_motion_model")
            np.save(motion_model_file, motion_model, allow_pickle=True)
        if listPts is not None:
            listPts[index_pair].yawCoarseAlign = motion_model["yaw"]
            listPts[index_pair].pitchCoarseAlign = motion_model["pitch"]
            listPts[index_pair].rollCoarseAlign = motion_model["roll"]
            listPts[index_pair].motion_model = motion_model
        if multispectral_folder is not None:
            #----------------------------------------------------------------------------------------------- MULTISPECTRAL EXPORT
            img = pr.Image(vis_pth)
            ms_img = np.zeros((ref_full.shape[0], ref_full.shape[1], 4))
            ms_img[:, :, :3] = ref_full
            ms_img[:, :, 3] = np.average(aligned_full, axis=-1)
            img._data = ms_img
            # out_name = f"{(index_pair+1):04d}"
            out_name = osp.basename(vis_pth[:-4])
            img.save_multispectral(Path(multispectral_folder)/out_name)
            #--------------------------------------------------------------------------------------------------------------------
        if VIS in traces:
            vis_img = pr.Image((ut.contrast_stretching(ref_full)[0]*255).astype(np.uint8))
            vis_img.path = vis_pth
            vis_img.save(
                osp.join(out_dir, osp.basename(vis_pth[:-4])+"_VIS.jpg"), gps=gps_vis, exif=exif_dict_minimal)
        
        for ali, almode in [(aligned_full, "_local_"), (align_full_global, "_global_")]:
            if NDVI in traces:
                ndvi(ref_full, ali, out_path=osp.join(out_dir, "_NDVI_" + almode + osp.basename(vis_pth[:-4])+".jpg"),
                    gps=gps_vis, exif=exif_dict_minimal, image_in=vis_pth)
            if VIR in traces:
                vir(ref_full, ali, out_path=osp.join(out_dir, "_VIR_" + almode + osp.basename(vis_pth[:-4])+".jpg"),
                    gps=gps_vis, exif=exif_dict_minimal, image_in=vis_pth)
            if NIR in traces:
                nir_out = pr.Image((ut.contrast_stretching(ali)[0]*255).astype(np.uint8))
                nir_out.path = vis_pth
                nir_out.save(
                    osp.join(out_dir, osp.basename(vis_pth[:-4])+"_NIR{}.jpg".format(almode)),
                    exif=exif_dict_minimal,
                    gps=gps_vis
                )
        if debug:  # SCIENTIFIC LINEAR OUTPUTS
            pr.Image(aligned_full).save(osp.join(out_dir, "_RAW_" + osp.basename(vis_pth[:-4])+"_NIR.tif"), gps=gps_vis, exif=exif_dict_minimal)
            pr.Image(align_full_global).save(osp.join(out_dir, "_RAW_" + osp.basename(vis_pth[:-4])+"_NIR_global.tif"), gps=gps_vis, exif=exif_dict_minimal)
            pr.Image(ref_full).save(osp.join(out_dir, "_RAW_"+ osp.basename(vis_pth[:-4])+"_VIS.tif"), gps=gps_vis, exif=exif_dict_minimal)
            
        motion_model_list.append(motion_model)
        if clean_proxy:
            pr.Image(vis_pth).clean_proxy()
            pr.Image(nir_pth).clean_proxy()
    return motion_model_list


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Align images')
    parser.add_argument('--images', nargs='+', help='list of images')
    parser.add_argument('--manual', action="store_true", help='manual alignement')
    parser.add_argument('--outdir', help='output directory')
    parser.add_argument('--debug', action="store_true", help='full debug traces')
    parser.add_argument('--delay', help='synchronization (in seconds)', default=0.)
    parser.add_argument('--multispectral-folder', help='multispectral TIF folder for ODM', default=None)
    parser.add_argument("--angles", nargs='+', type=float, help="yaw,pitch,roll")
    args = parser.parse_args()
    extension = 1.6
    if args.images is None:
        import utils.utils_IRdrone as IRd
        im_pair = []
        im_pair.append(IRd.loadFileGUI(mute=False, title="Open DRONE VISIBLE file (.dng)"))
        im_pair.append(IRd.loadFileGUI(mute=False, title="Open INFRARED NIR file (.raw)"))
        if args.outdir is None:
            args.outdir = IRd.loadFolderGUI(mute=False, title="Where do you want to save the images?")
    else:
        im_pair = args.images
    if im_pair[0].lower().endswith(".raw"):
        im_pair = im_pair[::-1]
    assert im_pair[0].lower().endswith(".tif") or im_pair[0].lower().endswith(".dng"), "Drone image first, SJcam image second"
    im_pairs = [im_pair]
    if args.outdir is not None:
        out_dir = args.outdir
    else:
        out_dir = osp.dirname(im_pairs[0][0])
    process_raw_pairs(
        im_pairs,
        debug_folder=out_dir,
        out_dir=out_dir,
        manual=args.manual,
        debug=args.debug,
        extension=extension,
        crop=CROP,
        multispectral_folder=args.multispectral_folder,
        angles=args.angles
    )

