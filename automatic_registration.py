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


class VegetationIndex(ipipe.ProcessBlock):
    """
    """
    def apply(self, vis, nir, alpha, **kwargs):
        red = vis[:, :, 0]
        nir_mono = np.average(nir, axis=2)
        nir_mono = (1+alpha)*nir_mono*0.5/np.average(nir_mono)
        red = red*0.5/np.average(red)
        ndvi = ((nir_mono - red)/(nir_mono + red))
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
                "NDVI":[-0.15],
            }
        )
        ipi.save(out_path)


def vir(vis_img, nir_img, out_path=None):
    vir = vis_img.copy()
    vir[:, :, 0] = np.mean(nir_img, axis=-1)
    vir[:, :, 1] = vis_img[:, :, 0]
    vir[:, :, 2] = vis_img[:, :, 1]
    if out_path is None:
        pr.Image(vir).show()
    else:
        pr.Image(vir).save(out_path)

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


def align_raw(vis_path, nir_path, cals, debug_dir=None, debug=False, extension=1.4, manual=True):
    """
    :param vis_path: Path to visible DJI DNG image
    :param nir_path: Path to NIR SJCAM M20 RAW image
    :param cals: Geometric calibration dictionary.
    :param debug_dir: traces folder
    :param extension: extend the FOV of the NIR camera compared to the DJI camera 1.4 by default, 1.75 is ~maximum
    :return:
    """
    if debug_dir is not None and not osp.isdir(debug_dir):
        os.mkdir(debug_dir)
    ts_start = time.perf_counter()
    vis = pr.Image(vis_path)
    nir = pr.Image(nir_path)
    if False:
        vis_undist = warp(vis.data, cals["refcalib"], np.eye(3)) # @TODO: Fix DJI calibration before using this
        vis_undist = pr.Image(vis_undist)
        vis_undist_lin = warp(vis.lineardata, cals["refcalib"], np.eye(3))
    else:
        vis_undist = vis
        vis_undist_lin = vis.lineardata
        cals_ref = cals["refcalib"]
        cals_ref["dist"] *= 0.

    ref_full = vis_undist.data
    mov_full = nir.data
    ts_end_load = time.perf_counter()
    logging.warning("{:.2f}s elapsed in loading full resolution RAW".format(ts_end_load - ts_start))
    if manual:
        alignment_params = user_assisted_manual_alignment(ref_full, mov_full, cals)
        yaw_main, pitch_main, roll_main = alignment_params["yaw"], alignment_params["pitch"], alignment_params["roll"]
    else:
        yaw_main, pitch_main, roll_main = 0., 0., 0.
    ts_start_coarse_search = time.perf_counter()
    ds = 32
    # -------------------------------------------------------------- Full res : Undistort NIR fisheye with a larger FOV
    mov_w_full = manual_warp(
        ref_full, mov_full,
        yaw_main, pitch_main, roll_main,
        refcalib=cals_ref, movingcalib=cals["movingcalib"],
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
    pr.Image(rigid.viz_msr(msr_mov, align_config.mode)).save(osp.join(debug_dir, "_PADDED_LOWRES_MOV_MSR.jpg"))
    pr.Image(rigid.viz_msr(padded_ref, align_config.mode)).save(osp.join(debug_dir, "_PADDED_LOWRES_MSR_REF.jpg"))
    cost_dict = rigid.compute_cost_surfaces_with_traces(
        msr_mov, padded_ref,
        debug=True, debug_dir=debug_dir,
        prefix="Full Search", suffix="",
        align_config=align_config,
        forced_debug_dir=debug_dir,
    )


    focal = cals_ref["mtx"][0, 0].copy()
    # translation = -ds*rigid.minimum_cost(cost_dict["costs"][0,0, :, :, :])
    try:
        translation = -ds*rigid.minimum_cost_max_hessian(cost_dict["costs"][0,0, :, :, :], debug=debug)
    except:
        translation = -ds*rigid.minimum_cost(cost_dict["costs"][0,0, :, :, :]) # @ TODO: handle the case of argmax close to the edge!
    yaw_refine = np.rad2deg(np.arctan(translation[0]/focal))
    pitch_refine = np.rad2deg(np.arctan(translation[1]/focal))
    print("2D translation {}".format(translation, yaw_refine, pitch_refine))
    ts_end_coarse_search = time.perf_counter()
    logging.warning("{:.2f}s elapsed in coarse search".format(ts_end_coarse_search - ts_start_coarse_search))
    ts_start_warp = time.perf_counter()
    if debug:
        mov_wr = manual_warp(
            msr_ref, cv2.resize(mov_full, (mov_full.shape[1]//ds, mov_full.shape[0]//ds)),
            yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
            refcalib=cals_ref, movingcalib=cals["movingcalib"],
            geometric_scale=1/ds, refinement_homography=None,
        )
        pr.Image(rigid.viz_msr(mov_wr, None)).save(osp.join(debug_dir, "_LOWRES_REGISTERED.jpg"))
        pr.Image(rigid.viz_msr(cv2.resize(ref_full, (ref_full.shape[1]//ds, ref_full.shape[0]//ds)), None)).save(osp.join(debug_dir, "_LOWRES_REF.jpg"))

    mov_wr_fullres = manual_warp(
        ref_full, mov_full,
        yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
        refcalib=cals_ref, movingcalib=cals["movingcalib"],
        geometric_scale=None, refinement_homography=None,
    )
    ts_end_warp = time.perf_counter()
    logging.warning("{:.2f}s elapsed in warping from coarse search".format(ts_end_warp - ts_start_warp))
    pr.Image(ref_full).save(osp.join(debug_dir, "FULLRES_REF.jpg"))
    pr.Image(mov_wr_fullres).save(osp.join(debug_dir, "FULLRES_REGISTERED_COARSE.jpg"))
    mov_w_final = rigid.pyramidal_search(
        ref_full, mov_wr_fullres,
        iterative_scheme=[(16, 2, 4, 8), (16, 2, 5), (4, 3, 5)],
        mode=rigid.LAPLACIAN_ENERGIES, dist=rigid.NTG,
        debug=debug, debug_dir=debug_dir,
        affinity=False,
        sigma_ref=5.,
        sigma_mov=3.
    )
    pr.Image(mov_w_final).save(osp.join(debug_dir, "FULLRES_REGISTERED_REFINED.jpg"))
    # pr.show([ref, mov, mov_w], suptitle="{}".format(mov.shape))
    ts_end = time.perf_counter()
    logging.warning("{:.2f}s elapsed in total alignment".format(ts_end - ts_start))
    return ref_full, mov_w_final


def process_raw_folder(folder, delta=timedelta(seconds=171), manual=False):
    """NIR/VIS image alignment and fusion
    - using a simple synchronization mechanism based on exif and camera deltas
    - camera time delta
    """
    sync_pairs = synchronize_data(folder, replace_dji=(".DNG", "_PL4_DIST.tif"), delta=delta)
    cals = dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW"))
    out_dir = osp.join(folder, "_RESULTS")
    process_raw_pairs(sync_pairs, cals, folder=folder, out_dir=out_dir, manual=manual)


def process_raw_pairs(
        sync_pairs,
        cals=dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW")),
        folder=None, out_dir=None, manual=False, debug=False
    ):
    if folder is None:
        folder = osp.dirname(sync_pairs[0][0])
    if out_dir is None:
        out_dir = osp.join(folder, "_RESULTS")
    if not osp.exists(out_dir):
        os.mkdir(out_dir)
    for vis_pth, nir_pth in sync_pairs[::-1]:  # [::-1]  [::-1][4:5]:  [3::40]: [410:415]:
        logging.warning("processing {} {}".format(osp.basename(vis_pth), osp.basename(nir_pth)))
        debug_dir = osp.join(folder, osp.basename(vis_pth)[:-4]+"_align_GLOBAL_MIN_FIXED" + ("_manual" if manual else ""))
        write_manual_bat_redo(vis_pth, nir_pth, osp.join(out_dir, osp.basename(vis_pth[:-4])+"_REDO.bat"), debug=False)
        write_manual_bat_redo(vis_pth, nir_pth, osp.join(out_dir, osp.basename(vis_pth[:-4])+"_DEBUG.bat"), debug=True)
        ref_full, aligned_full = None, None
        if not osp.isdir(debug_dir):
            ref_full, aligned_full = align_raw(vis_pth, nir_pth, cals, debug_dir=debug_dir, manual=manual, debug=debug)
        if osp.isdir(debug_dir):
            ref_pth = osp.join(debug_dir, "FULLRES_REF.jpg")
            aligned_pth = osp.join(debug_dir, "FLOW_it09_ds04_WARP_LOCAL.jpg")
            # ---------------------------------------------------------------------------------------------- copy traces
            if True:
                shutil.copy(ref_pth, osp.join(out_dir, osp.basename(vis_pth[:-4]+"_visible_ref.jpg")))
                shutil.copy(aligned_pth, osp.join(out_dir, osp.basename(vis_pth[:-4]+"_nir_aligned.jpg")))
            if False:
                shutil.copy(ref_pth, osp.join(out_dir, osp.basename(vis_pth[:-4])+"_visible_ref.jpg"))
                shutil.copy(aligned_pth, osp.join(out_dir, osp.basename(vis_pth[:-4])+"_nir_aligned.jpg"))
                cost_pth = osp.join(debug_dir, "Full Search_blocks_y1x1_search_y25x25_NTG_overview_cost_surfaces_.png")
                search_pth = osp.join(debug_dir, "Full Search_blocks_y1x1_search_y25x25_NTG_cost_surface_0_0_.png")
                shutil.copy(cost_pth, osp.join(out_dir, "_COSTS_" + osp.basename(vis_pth[:-4])+"_Global_cost.png"))
                shutil.copy(search_pth, osp.join(out_dir, "_GLOBAL_SEARCH_" + osp.basename(vis_pth[:-4])+"_Global_cost.png"))
                local_cost_pth = osp.join(debug_dir, "ds4_laplacian_energies_blocks_y5x5_search_y6x6_NTG_overview_cost_surfaces__it09.png")
                shutil.copy(local_cost_pth, osp.join(out_dir, "_LOCAL_COSTS_" + osp.basename(vis_pth[:-4])+"_Global_cost.png"))
            if ref_full is None :
                ref_full = pr.Image(ref_pth).data
            if aligned_full is None:
                aligned_full = pr.Image(aligned_pth).data
            ndvi(ref_full, aligned_full, out_path=osp.join(out_dir, "_NDVI_" + osp.basename(vis_pth[:-4])+".jpg"))
            vir(ref_full, aligned_full, out_path=osp.join(out_dir, "_VIR_" + osp.basename(vis_pth[:-4])+".jpg"))


def write_manual_bat_redo(vis_pth, nir_pth, debug_bat_pth, out_dir=None, debug=False):
    if out_dir is None:
        out_dir = osp.abspath(debug_bat_pth.replace(".bat", ""))
    with open(debug_bat_pth, "w") as fi:
        fi.write("call activate {}\n".format(os.environ['CONDA_DEFAULT_ENV']))
        fi.write("python {} --images {} {} --manual --outdir {} {}\n".format(
            osp.abspath(__file__),
            vis_pth, nir_pth,
            out_dir,
            "--debug" if debug else "")
        )
        fi.write("call deactivate\n")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Align images')
    parser.add_argument('--images', nargs='+', help='list of images')
    parser.add_argument('--manual', action="store_true", help='manual alignement')
    parser.add_argument('--outdir', help='output directory')
    parser.add_argument('--debug', action="store_true", help='full debug traces')
    args = parser.parse_args()
    print(args.manual)
    if args.images is None:
        process_raw_folder(folder = r"D:\FLY-20210906-Blassac-05ms\AerialPhotography", manual=args.manual)
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
            folder=out_dir,
            out_dir=out_dir,
            manual=args.manual,
            debug=args.debug,
        )

