import irdrone.utils as ut
import irdrone.process as pr
from application import warp
import numpy as np
import logging
import os.path as osp
import registration.rigid as rigid
from irdrone.semi_auto_registration import manual_warp, ManualAlignment, Transparency, Absgrad
from skimage import transform
import os
osp = os.path
from synchronization import synchronize_data
import time
from datetime import datetime, timedelta
from customApplication import colorMapNDVI
import irdrone.imagepipe as ipipe
import shutil
import cv2
import argparse
from copy import deepcopy


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


def ndvi(vis_img, nir_img, out_path=None):
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
        ipi.save(out_path)


def vir(vis_img, nir_img, out_path=None):
    vir = vis_img.copy()
    vir[:, :, 0] = np.mean(nir_img, axis=-1)
    vir[:, :, 0] *= 0.5/np.mean(vir[:, :, 0]) # @TODO: correctly expose the NIR channel
    vir[:, :, 1] = vis_img[:, :, 0]
    vir[:, :, 2] = vis_img[:, :, 1]
    if out_path is None:
        pr.Image(vir).show()
    else:
        if out_path.lower().endswith("tif"):
            pr.Image(vir).save(out_path)
        else:
            recontrasted_image = (ut.contrast_stretching(vir.clip(0., 1.))[0]*255).astype(np.uint8)
            pr.Image(recontrasted_image).save(out_path)
            # pr.Image((vir*255).clip(0, 255).astype(np.uint8)).save(out_path)


def user_assisted_manual_alignment(ref, mov, cals):
    ROTATE = "Rotate"
    rotate3d = ManualAlignment(
        ROTATE,
        slidersName=["YAW [Horizontal]", "PITCH [Vertical]", "ROLL"],
        inputs=[1, 2],
        outputs=[0],
        vrange=[
            (-30., 30, 0.), (-30., 30, 0.), (-5., 5, 0.)
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
    msr_ref = transform.pyramid_reduce(msr_ref_full, downscale=ds, multichannel=True).astype(np.float32)
    msr_mov = transform.pyramid_reduce(msr_mov_full, downscale=ds, multichannel=True).astype(np.float32)
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
        translation = -ds*rigid.minimum_cost(cost_dict["costs"][0, 0, :, :, :])
    yaw_refine = np.rad2deg(np.arctan(translation[0]/focal))
    pitch_refine = np.rad2deg(np.arctan(translation[1]/focal))
    print("2D translation {}".format(translation, yaw_refine, pitch_refine))
    ts_end_coarse_search = time.perf_counter()
    logging.warning("{:.2f}s elapsed in coarse search".format(ts_end_coarse_search - ts_start_coarse_search))
    ts_start_warp = time.perf_counter()
    if debug_dir is not None and debug:
        mov_wr = manual_warp(
            msr_ref, cv2.resize(mov_full, (mov_full.shape[1]//ds, mov_full.shape[0]//ds)),
            yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
            refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
            geometric_scale=1/ds, refinement_homography=None,
            )
        pr.Image(rigid.viz_msr(mov_wr, None)).save(osp.join(debug_dir, "_LOWRES_REGISTERED.jpg"))
        pr.Image(rigid.viz_msr(cv2.resize(ref_full, (ref_full.shape[1]//ds, ref_full.shape[0]//ds)), None)).save(
            osp.join(debug_dir, "_LOWRES_REF.jpg"))
    mov_wr_fullres = manual_warp(
        ref_full, mov_full,
        yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
        refcalib=cals["refcalib"], movingcalib=cals["movingcalib"],
        geometric_scale=None, refinement_homography=None,
    )
    ts_end_warp = time.perf_counter()
    logging.warning("{:.2f}s elapsed in warping from coarse search".format(ts_end_warp - ts_start_warp))
    if debug_dir is not None:
        pr.Image(ref_full).save(osp.join(debug_dir, "FULLRES_REF.jpg"))
        pr.Image(mov_wr_fullres).save(osp.join(debug_dir, "FULLRES_REGISTERED_COARSE.jpg"))
    return mov_wr_fullres, dict(yaw=yaw_main + yaw_refine, pitch=pitch_main + pitch_refine, roll=roll_main)


def align_raw(vis_path, nir_path, cals_dict, debug_dir=None, debug=False, extension=1.4, manual=True):
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
    motion_model_file = None
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
            alignment_params = user_assisted_manual_alignment(ref_full, mov_full, cals)
            yaw_main, pitch_main, roll_main = alignment_params["yaw"], alignment_params["pitch"], alignment_params["roll"]
        else:
            yaw_main, pitch_main, roll_main = 0., 0., 0.
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
    return vis_undist_lin, mov_w_linear_local, mov_w_linear_global, full_motion_model
    # return ref_full, mov_w_final_yowo_full


def process_raw_folder(folder, delta=timedelta(seconds=166.5), manual=False, debug=False,
                       extension_vis="*.DNG", extension_nir="*.RAW", extension=1.4,
                       ):
    """NIR/VIS image alignment and fusion
    - using a simple synchronization mechanism based on exif and camera deltas
    - camera time delta
    """
    sync_pairs = synchronize_data(folder, replace_dji=None, delta=delta,
                                  extension_vis=extension_vis, extension_nir=extension_nir, debug=debug)
    # replace_dji=(".DNG", "_PL4_DIST.tif")
    cals = dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW"))
    out_dir = osp.join(folder, "_RESULTS_delta={:.1f}s".format(delta.seconds+delta.microseconds/(1.E6)))
    process_raw_pairs(sync_pairs, cals, debug_folder=None, out_dir=out_dir, manual=manual, debug=debug, extension=extension)


def process_raw_pairs(
        sync_pairs,
        cals=dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW")),
        extension=1.4,
        debug_folder=None, out_dir=None, manual=False, debug=False
    ):
    # if debug_folder is None:
    #     debug_folder = osp.dirname(sync_pairs[0][0])
    if out_dir is None:
        out_dir = osp.join(osp.dirname(sync_pairs[0][0]), "_RESULTS")
    if not osp.exists(out_dir):
        os.mkdir(out_dir)
    for index_pair, (vis_pth, nir_pth) in enumerate(sync_pairs):
        logging.warning("processing {} {}".format(osp.basename(vis_pth), osp.basename(nir_pth)))
        if debug_folder is not None:
            debug_dir = osp.join(debug_folder, osp.basename(vis_pth)[:-4]+"_align_traces" + ("_manual" if manual else ""))
        else:
            debug_dir = None
        offset_async = [offset for offset in [0, -1, +1, -2, +2]
                        if (index_pair+offset >=0 and index_pair+offset<len(sync_pairs))]
        nir_pth_async = [sync_pairs[index_pair+offset][1] for offset in offset_async]
        write_manual_bat_redo(vis_pth, nir_pth_async,
                              osp.join(out_dir, osp.basename(vis_pth[:-4])+"_REDO_ASYNC.bat"),
                              async_suffix=offset_async,
                              debug=False)
        write_manual_bat_redo(vis_pth, [nir_pth], osp.join(out_dir, osp.basename(vis_pth[:-4])+"_REDO.bat"), debug=False)
        write_manual_bat_redo(vis_pth, [nir_pth], osp.join(out_dir, osp.basename(vis_pth[:-4])+"_DEBUG.bat"), debug=True)
        # continue
        ref_full, aligned_full, align_full_global, motion_model = align_raw(
            vis_pth, nir_pth, cals,
            debug_dir=debug_dir, debug=debug,
            manual=manual,
            extension=extension
        )
        # AGGREGATED RESULTS!
        if debug:  # SCIENTIFIC LINEAR OUTPUTS
            pr.Image(aligned_full).save(osp.join(out_dir, "_RAW_" + osp.basename(vis_pth[:-4])+"_NIR.tif"), gps=ref_full.gps)
            pr.Image(align_full_global).save(osp.join(out_dir, "_RAW_" + osp.basename(vis_pth[:-4])+"_NIR.tif"), gps=ref_full.gps)
            pr.Image(ref_full).save(osp.join(out_dir, "_RAW_"+ osp.basename(vis_pth[:-4])+"_VIS.tif"), gps=ref_full.gps)
        # Systematically write motion model!
        if motion_model is not None:
            motion_model_file = osp.join(out_dir, osp.basename(vis_pth[:-4])+"_motion_model")
            np.save(motion_model_file, motion_model, allow_pickle=True)
        pr.Image((ut.contrast_stretching(ref_full)[0]*255).astype(np.uint8)).save(osp.join(out_dir, osp.basename(vis_pth[:-4])+"_VIS.jpg"))
        for ali, almode in [(aligned_full, "_local_"), (align_full_global, "_global_")]:
            ndvi(ref_full, ali, out_path=osp.join(out_dir, "_NDVI_" + almode + osp.basename(vis_pth[:-4])+".jpg"))
            vir(ref_full, ali, out_path=osp.join(out_dir, "_VIR_" + almode + osp.basename(vis_pth[:-4])+".jpg"))
            pr.Image((ut.contrast_stretching(ali)[0]*255).astype(np.uint8)).save(
                osp.join(out_dir, osp.basename(vis_pth[:-4])+"_NIR{}.jpg".format(almode)))


def write_manual_bat_redo(vis_pth, nir_pth_list, debug_bat_pth, out_dir=None, debug=False, async_suffix=None):
    if out_dir is None:
        out_dir = osp.abspath(debug_bat_pth.replace(".bat", ""))
    with open(debug_bat_pth, "w") as fi:
        fi.write("call activate {}\n".format(os.environ['CONDA_DEFAULT_ENV']))
        for id_sync, nir_pth in enumerate(nir_pth_list):
            out_dir_current = out_dir
            if async_suffix is not None:
                out_dir_current = out_dir_current + "_async_{}".format(async_suffix[id_sync])
            fi.write(
                ("REM " if id_sync>0 else "")+
                "python {} --images {} {} --manual --outdir {} {}\n".format(
                "\""+osp.abspath(__file__)+"\"",
                "\""+vis_pth+"\"", "\""+nir_pth+"\"",
                "\""+out_dir_current+"\"",
                "--debug" if debug else "")
            )
        fi.write("call deactivate\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Align images')
    parser.add_argument('--images', nargs='+', help='list of images')
    parser.add_argument('--manual', action="store_true", help='manual alignement')
    parser.add_argument('--outdir', help='output directory')
    parser.add_argument('--debug', action="store_true", help='full debug traces')
    parser.add_argument('--folder', help='folder containing images for visible and NIR')
    parser.add_argument('--delay', help='synchronization (in seconds)', default=0.)

    args = parser.parse_args()
    extension = 1.6
    if args.images is None:
        if args.folder is None:
            logging.error("Please provide image pair through --images  or a full folder to process through --folder")
        if args.delay == 0.:
            logging.warning("WARNING: assuming synchronized data, " +
                            "please make sure you have no delay between image pairs")
            delta = None
        else:
            delta=timedelta(seconds=float(args.delay))
        process_raw_folder(folder=args.folder, manual=args.manual, debug=args.debug, delta=delta, extension=extension)
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
            extension=extension
        )

