import irdrone.utils as ut
import irdrone.process as pr
from application import warp
import numpy as np
import logging
import os.path as osp
import registration.rigid as rigid
from irdrone.semi_auto_registration import manual_warp
from skimage import transform
import os
osp = os.path
from synchronization import synchronize_data
import time
from datetime import datetime, timedelta
from customApplication import colorMapNDVI
import irdrone.imagepipe as ipipe
import shutil

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
        [vis_img.data, nir_img.data],
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


def align_raw(vis_path, nir_path, cals, debug_dir=None, extension=1.4):
    """
    :param vis_path: Path to visible DJI DNG image
    :param nir_path: Path to NIR SJCAM M20 RAW image
    :param cals: Geometric calibration dictionary.
    :param debug_dir: traces folder
    :param extension: extend the FOV of the NIR camera compared to the DJI camera 1.4 by default, 1.75 is ~maximum
    :return:
    """
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
    ts_end_load = time.perf_counter()
    logging.warning("{:.2f}s elapsed in loading full resolution RAW".format(ts_end_load - ts_start))

    # @TODO: inverse downscale and MSR
    ts_start_coarse_search = time.perf_counter()
    ds = 32
    ref = transform.pyramid_reduce(ref_full, downscale=ds, multichannel=True).astype(np.float32)
    # ref = cv2.resize(ref_full, (ref_full.shape[1]//ds, ref_full.shape[0]//ds))
    mov_full = nir.data
    mov = transform.pyramid_reduce(mov_full, downscale=ds, multichannel=True).astype(np.float32)
    # mov = cv2.resize(mov_full, (mov_full.shape[1]//ds, mov_full.shape[0]//ds))
    debug_dir = debug_dir
    if not os.path.isdir(debug_dir):
        os.mkdir(debug_dir)
    pr.Image(rigid.viz_msr(ref, "" )).save(osp.join(debug_dir, "REF.jpg"))
    yaw_main, pitch_main, roll_main = 0., 0., 0.
    mov_w = manual_warp(
        ref, mov,
        yaw_main, pitch_main, roll_main,
        refcalib=cals_ref, movingcalib=cals["movingcalib"],
        geometric_scale=1/ds, refinement_homography=None,
        bigger_size_factor=extension,

    )

    pad_y = (mov_w.shape[0]-ref.shape[0])//2
    pad_x = (mov_w.shape[1]-ref.shape[1])//2
    align_config = rigid.AlignmentConfig(num_patches=1, search_size=pad_x, mode=rigid.LAPLACIAN_ENERGIES)
    msr_ref = rigid.multispectral_representation(ref, mode=align_config.mode).astype(np.float32)
    msr_mov = rigid.multispectral_representation(mov_w, mode=align_config.mode).astype(np.float32)
    padded_ref = np.zeros_like(msr_mov)
    padded_ref[pad_y:pad_y+ref.shape[0], pad_x:pad_x+ref.shape[1], :] = msr_ref
    pr.Image(rigid.viz_msr(mov_w, None)).save(osp.join(debug_dir, "_LOWRES_MOV_INIT.jpg"))
    pr.Image(rigid.viz_msr(msr_mov, align_config.mode)).save(osp.join(debug_dir, "_LOWRES_MOV_MSR.jpg"))
    pr.Image(rigid.viz_msr(padded_ref, align_config.mode)).save(osp.join(debug_dir, "_LOWRES_MSR_PADDED_REF.jpg"))
    cost_dict = rigid.compute_cost_surfaces_with_traces(
        msr_mov, padded_ref,
        debug=True, debug_dir=debug_dir,
        prefix="Full Search", suffix="",
        align_config=align_config,
        forced_debug_dir=debug_dir,
    )



    focal = cals_ref["mtx"][0, 0].copy()
    # translation = -np.argmin(cost_dict["costs"][0,0, :, :, :])[::-1] * ds
    translation = -ds*rigid.minimum_cost(cost_dict["costs"][0,0, :, :, :])
    yaw_refine = np.rad2deg(np.arctan(translation[0]/focal))
    pitch_refine = np.rad2deg(np.arctan(translation[1]/focal))
    print("2D translation {}".format(translation, yaw_refine, pitch_refine))
    mov_wr = manual_warp(
        ref, mov,
        yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
        refcalib=cals_ref, movingcalib=cals["movingcalib"],
        geometric_scale=1/ds, refinement_homography=None,
    )

    pr.Image(rigid.viz_msr(mov_wr, None)).save(osp.join(debug_dir, "_LOWRES_REGISTERED.jpg"))


    mov_wr_fullres = manual_warp(
        ref_full, mov_full,
        yaw_main + yaw_refine, pitch_main + pitch_refine, roll_main,
        refcalib=cals_ref, movingcalib=cals["movingcalib"],
        geometric_scale=None, refinement_homography=None,
    )
    ts_end_coarse_search = time.perf_counter()
    logging.warning("{:.2f}s elapsed in coarse search".format(ts_end_coarse_search - ts_start_coarse_search))
    pr.Image(ref_full).save(osp.join(debug_dir, "REF_FULLRES.jpg"))
    pr.Image(mov_wr_fullres).save(osp.join(debug_dir, "FULLRES_REGISTERED_COARSE.jpg"))
    mov_w_final = rigid.pyramidal_search(
        ref_full, mov_wr_fullres,
        iterative_scheme=[(16, 2, 4), (16, 2, 5), (4, 3, 5)],
        mode=rigid.LAPLACIAN_ENERGIES, dist=rigid.NTG,
        debug=False, debug_dir=debug_dir,
        affinity=False,
        sigma_ref=5.,
        sigma_mov=3.
    )
    pr.Image(mov_w_final).save(osp.join(debug_dir, "FULLRES_REGISTERED_REFINED.jpg"))
    # pr.show([ref, mov, mov_w], suptitle="{}".format(mov.shape))
    ts_end = time.perf_counter()
    logging.warning("{:.2f}s elapsed in total alignment".format(ts_end - ts_start))



def demo_raw(folder=osp.join(osp.dirname(__file__), r"Hyperlapse 06_09_2021_sync")):
    """
    Scan the folder for pairs of raw with the same name.
    Assume that RAW from SJCAM M20 and DNG from DJI have the same file name
    """
    data_link = "https://drive.google.com/drive/folders/1IrF55tDYV6YwHm0gUTRc7T3WTnbwbPxk?usp=sharing"
    assert osp.isdir(folder), "please download {} and put all images in {}".format(data_link, folder)
    cals = dict(
        refcalib=ut.cameracalibration(camera="DJI_RAW"),
        movingcalib=ut.cameracalibration(camera="M20_RAW")
    )
    out_dir = osp.join(folder, "debug")
    if not osp.isdir(out_dir):
        import os
        os.mkdir(out_dir)
    import glob
    for vis_pth in sorted(glob.glob(osp.join(folder, "*DNG"))):
        nir_pth = vis_pth.replace("DNG", "RAW")
        # @TODO: FIX WHEN DJI GEOMETRIC CALIBRATION IS FIXED
        vis_pth_undist = vis_pth.replace(".DNG", "_PL4_DIST.tif")
        if osp.exists(vis_pth_undist):
            vis_pth = vis_pth_undist
        align_raw(vis_pth, nir_pth, cals, debug_dir=osp.basename(vis_pth)[:-4])


def process_raw_folder(folder, delta=timedelta(seconds=171)):
    """Synchronize image pairs"""
    sync_pairs = synchronize_data(folder, replace_dji=(".DNG", "_PL4_DIST.tif"), delta=delta)
    cals = dict(refcalib=ut.cameracalibration(camera="DJI_RAW"), movingcalib=ut.cameracalibration(camera="M20_RAW"))
    out_dir = osp.join(folder, "_RESULTS")
    if not osp.exists(out_dir):
        os.mkdir(out_dir)
    # for vis_pth, nir_pth in sync_pairs[::-1][:2]:
    for vis_pth, nir_pth in sync_pairs[::40]:
        logging.warning("processing {} {}".format(osp.basename(vis_pth), osp.basename(nir_pth)))
        debug_dir = osp.join(folder, osp.basename(vis_pth)[:-4]+"_align_debuggin")
        align_raw(vis_pth, nir_pth, cals, debug_dir=debug_dir)
        if osp.isdir(debug_dir):
            ref_pth = osp.join(debug_dir, "REF_FULLRES.jpg")
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
            ndvi(
                pr.Image(ref_pth),
                pr.Image(aligned_pth),
                out_path=osp.join(out_dir, "_NDVI_" + osp.basename(vis_pth[:-4])+".jpg")
            )

def demo_raw_real_application(folder_database=osp.join(osp.dirname(__file__), "FlightDatabase")):
    data_link = "https://drive.google.com/drive/folders/1UJGvq8gWpkkgtAd6cRbNiQIRyabcjPIf?usp=sharing"
    assert osp.isdir(folder_database), "please download {} and put all images in {}".format(data_link, folder_database)
    cals = dict(
        refcalib=ut.cameracalibration(camera="DJI_RAW"),
        movingcalib=ut.cameracalibration(camera="M20_RAW")
    )
    # -------------------------------------------------------------------------------------------------------- Visargent

    img_pairs = [
        ["DJI_0612.DNG", "2021_0505_083056_111.RAW"],
        ["DJI_0613.DNG", "2021_0505_083132_135.RAW"],
        ["DJI_0615.DNG", "2021_0505_083217_165.RAW"]
    ]
    folder = osp.join(folder_database, "FLY-20210505_Visargent", "AerialPhotography")
    pairs_paths = [[osp.join(folder, vis.replace(".RAW", "_PL4_DIST.tif")), osp.join(folder, nir)]
                   for vis, nir in img_pairs]
    batch_raw_alignment(folder, pairs_paths, cals)

    # ----------------------------------------------------------------------------------------------------------- Vivans
    img_pairs = [
        ["DJI_0618.DNG", "2021_0505_130901_067.RAW"],  # NOT WORKING IN AUTO! -> NEEDS MANUAL
        # ["DJI_0623.DNG", "2021_0505_131131_167.RAW"],
        # ["DJI_0624.DNG", "2021_0505_131155_183.RAW"]
        # ["DJI_0624.DNG", "2021_0505_131131_167.RAW"]
    ]
    folder = osp.join(folder_database, "FLY-20210505_Vivans", "AerialPhotography")
    pairs_paths = [[osp.join(folder, vis.replace(".RAW", "_PL4_DIST.tif")), osp.join(folder, nir)]
                   for vis, nir in img_pairs]
    batch_raw_alignment(folder, pairs_paths, cals, manual=True)


def batch_raw_alignment(folder, pairs_paths, cals, manual=False):
    """allows manual alignment for the first part
    """
    out_dir = osp.join(folder, "debug")
    if not osp.isdir(out_dir):
        os.mkdir(out_dir)
    for vis_pth, nir_pth in pairs_paths:
        dbg_dir = osp.join(out_dir, osp.basename(vis_pth)[:-4])
        if not osp.isdir(dbg_dir):
            os.mkdir(dbg_dir)
        if manual:
            from irdrone.semi_auto_registration import align_raw as align_raw_manual
            out_lin, out_non_lin, ref_full = align_raw_manual(vis_pth, nir_pth, cals, out_dir=dbg_dir+"_manual")
            mov_w_final = rigid.pyramidal_search(
                ref_full, out_non_lin,
                iterative_scheme=[(16, 2, 4), (16, 2, 5), (4, 3, 5)],
                mode=rigid.LAPLACIAN_ENERGIES, dist=rigid.NTG,
                debug=False, debug_dir=dbg_dir,
                affinity=False,
                sigma_ref=5.,
                sigma_mov=3.
            )
            pr.Image(mov_w_final).save(osp.join(dbg_dir, "FULLRES_REGISTERED_REFINED.jpg"))
        else:
            align_raw(vis_pth, nir_pth, cals, debug_dir=dbg_dir, extension=1.4)


if __name__ == "__main__":
    # demo_raw()
    process_raw_folder(folder = r"D:\FLY-20210906-Blassac-05ms\AerialPhotography")
    # demo_raw_real_application()