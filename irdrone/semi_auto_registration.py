import sys
import os
osp = os.path
root = osp.join(osp.dirname(__file__), "..")
sys.path.append(root)
from skimage.registration import phase_cross_correlation
from skimage.transform import warp_polar
from skimage import filters
from skimage import exposure
import irdrone.utils as ut
import irdrone.process as pr
from registration.warp_flow import warp
import interactive.imagepipe as ipipe
from irdrone.register import register_by_blocks, estimateFeaturePoints
import numpy as np
import cv2
import logging

ROTATE = "Rotate"


# ---------------------------------------------- 3D ROTATION -----------------------------------------------------------
def get_zoom_mat(scale):
    zoom_mat = np.eye(3)
    zoom_mat[0, 0] = scale
    zoom_mat[1, 1] = scale
    return zoom_mat


def manual_warp(ref: pr.Image, mov: pr.Image, yaw_main: float, pitch_main: float, roll_main: float = 0.,
                refcalib=None, movingcalib=None, geometric_scale=None, refinement_homography=None,
                bigger_size_factor = None,
                vector_field=None
    ):
    rot_main, _ = cv2.Rodrigues(np.array([-np.deg2rad(pitch_main), np.deg2rad(yaw_main), np.deg2rad(roll_main)]))
    mov_calib = movingcalib.copy()
    if geometric_scale is None:
        h = np.dot(np.dot(refcalib["mtx"], rot_main), np.linalg.inv(movingcalib["mtx"]))
    else:
        zoom_mat_mov = get_zoom_mat(geometric_scale)
        zoom_mat_ref = zoom_mat_mov.copy()
        ref_cal = refcalib["mtx"].copy()
        mov_cal = movingcalib["mtx"].copy()
        ref_cal = np.dot(zoom_mat_ref, ref_cal)
        mov_cal = np.dot(zoom_mat_mov, mov_cal)
        h = np.dot(np.dot(ref_cal, rot_main), np.linalg.inv(mov_cal))
        mov_calib["mtx"] = mov_cal
    if refinement_homography is not None:
        h = np.dot(refinement_homography, h)
    if vector_field is not None:
        bigger_size_factor = 1.2
        print("PAD BECAUSE OF VECTOR FIELD")
    if bigger_size_factor is not None:
        outsize= [ref.data.shape[1], ref.data.shape[0]]
        new_out_size = [int(outsize[0]*bigger_size_factor), int(outsize[1]*bigger_size_factor)]
        translation_mat = np.eye(3)
        translation_mat[0, 2] = (new_out_size[0] - outsize[0])/2
        translation_mat[1, 2] = (new_out_size[1] - outsize[1])/2
        if vector_field is not None:
            padding = [int(translation_mat[0, 2]), int(translation_mat[1, 2])]
        else:
            padding = None
        h = np.dot(translation_mat, h)
        mov_u = warp(mov, mov_calib, h, outsize=(new_out_size[0], new_out_size[1]),
                     vector_field=vector_field, padding=padding)
        if vector_field is not None:
            mov_u = mov_u[
                    int(translation_mat[1, 2]): int(translation_mat[1, 2])+outsize[1],
                    int(translation_mat[0, 2]): int(translation_mat[0, 2])+outsize[0],
                    :
            ]
    else:
        mov_u = warp(mov, mov_calib, h, outsize=(ref.data.shape[1], ref.data.shape[0]), vector_field=vector_field)
    return mov_u


# ---------------------------------------------- SEMI-AUTO ALIGNMENT----------------------------------------------------
def estimate_translation(ref, mov_warped, refcalib, geometricscale=None):
    shifts, error, phase_diff = phase_cross_correlation(
        ref if len(ref.shape)==2 else ut.c2g(ref.astype(np.uint8)),
        mov_warped if len(mov_warped.shape) == 2 else ut.c2g(mov_warped.astype(np.uint8)),
        upsample_factor=8.
    )
    translation = shifts[::-1]
    focal = refcalib["mtx"][0, 0].copy()
    # we estimate the displacement in the "reference" camera space (in the visible space)
    if geometricscale is not None:
        focal = focal*geometricscale
    yaw_refine = np.rad2deg(np.arctan(translation[0]/focal))
    pitch_refine = np.rad2deg(np.arctan(translation[1]/focal))
    homog_trans = np.eye(3)
    homog_trans[:2, 2] = translation
    return yaw_refine, pitch_refine, homog_trans


def mellin_transform(refi, movi):
    radius = np.min(refi.shape[:2])/2.*0.75
    scaling= ["linear", "log"][0]
    polar_mov = warp_polar(movi, radius=radius, multichannel=len(movi.shape) == 3, scaling=scaling)
    polar_ref = warp_polar(refi, radius=radius, multichannel=len(refi.shape) == 3, scaling=scaling)
    return polar_ref, polar_mov


def estimate_rotation(polar_refi, polar_movi, ref):
    shifts, error, phase_diff = phase_cross_correlation(
        polar_refi,
        polar_movi,
        upsample_factor=8.
    )

    roll_refine = -shifts[0]
    rot_main, _ = cv2.Rodrigues(np.array([0., 0., np.deg2rad(roll_refine)]))
    out_intrinsic = np.eye(3)
    out_intrinsic[0, 2] = ref.data.shape[1]/2
    out_intrinsic[1, 2] = ref.data.shape[0]/2
    roll_homog = np.dot(np.dot(out_intrinsic, rot_main), np.linalg.inv(out_intrinsic))
    return roll_refine, roll_homog


class ManualAlignment(ipipe.ProcessBlock):
    """
    Manual 3D rotations
    Composed with semi automatic refinement
    """
    refcalib = None
    movingcalib = None
    alignment_parameters = dict(yaw=0, pitch=0, roll=0)

    def set_refcalib(self, _refcalib):
        self.refcalib = _refcalib

    def set_movingcalib(self, _movingcalib):
        self.movingcalib = _movingcalib

    def apply(self, ref, mov, yaw, pitch, roll, geometricscale=None, **kwargs):
        mov_warped = manual_warp(
            ref, mov,
            yaw, pitch, roll,
            refcalib=self.refcalib, movingcalib=self.movingcalib,
            geometric_scale=geometricscale
        )  # manual warp in colors
        self.alignment_parameters = dict(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
        )
        return mov_warped


class SemiAutoAlignment(ipipe.ProcessBlock):
    """
    Manual 3D rotations
    Composed with semi automatic refinement
    """
    refcalib = None
    movingcalib = None
    abstraction_offset_ref = 1.

    def set_refcalib(self, _refcalib):
        self.refcalib = _refcalib

    def set_movingcalib(self, _movingcalib):
        self.movingcalib = _movingcalib

    def set_abstraction_offset_ref(self, _abstraction_offset_ref):
        self.abstraction_offset_ref = _abstraction_offset_ref

    def apply(self, ref, mov, yaw, pitch, roll, auto, geometricscale=None, **kwargs):
        yaw_refine, yaw_refine_last, pitch_refine, pitch_refine_last, roll_refine = 0., 0., 0., 0., 0.
        debug=False
        mode = [None, "ABS_GRAD", "SCHARR"][2]
        mov_warped = manual_warp(
            ref, mov,
            yaw, pitch, roll,
            refcalib=self.refcalib, movingcalib=self.movingcalib,
            geometric_scale=geometricscale
        )  # manual warp in colors
        out = mov_warped
        #ABS GRAD VERSION
        if mode=="ABS_GRAD":
            ref_g = abs_grad_convert(ref)
            mov_warped_g = abs_grad_convert(mov_warped)
        elif mode == "SCHARR":
            ref_g, mov_warped_g = prepare_inputs_for_matching(ref, mov_warped, abstraction_offset_ref=self.abstraction_offset_ref)
        elif mode is None:
            ref_g, mov_warped_g = ut.c2g(ref), ut.c2g(mov_warped)


        mov_warped_refined = mov_warped  # stay in color
        if auto > 0.25:
            # ----------------------------------------------------------------------------------------
            # REFINE TRANSLATION (PITCH & YAW)
            # ----------------------------------------------------------------------------------------
            yaw_refine, pitch_refine, homog_trans = estimate_translation(
                ref_g, mov_warped_g, self.refcalib,
                geometricscale=geometricscale
            )
            print("YAW %.2f° PITCH %.2f°"%(yaw+yaw_refine, pitch+pitch_refine))
            if debug:
                yaw_refine, pitch_refine = 0.,  0.
            mov_warped_refined = manual_warp(
                ref, mov,
                yaw+yaw_refine, pitch+pitch_refine, roll,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
                refinement_homography=homog_trans if debug else None
            )
            if mode=="ABS_GRAD":
                mov_warped_refined_g = abs_grad_convert(mov_warped_refined)
            elif mode == "SCHARR":
                _, mov_warped_refined_g = prepare_inputs_for_matching(ref, mov_warped_refined, abstraction_offset_ref=self.abstraction_offset_ref)
            elif mode is None:
                mov_warped_refined_g = ut.c2g(mov_warped_refined)
            out = mov_warped_refined
        if auto >= 0.5:
            # ----------------------------------------------------------------------------------------
            # REFINE ROLL
            # ----------------------------------------------------------------------------------------
            polar_ref_g, polar_mov_g = mellin_transform(ref_g, mov_warped_refined_g)
            polar_ref, polar_mov = mellin_transform(ref, mov_warped_refined) # colored for debugging
            roll_refine, roll_homog = estimate_rotation(polar_ref_g, polar_mov_g, ref)
            roll_refine = -roll_refine
            roll_homog = np.linalg.inv(roll_homog)
            mov_warped_refined_rot = manual_warp(
                ref, mov,
                yaw+yaw_refine, pitch+pitch_refine, roll,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
                refinement_homography=roll_homog
            )
            out = mov_warped_refined_rot
        if auto >= 0.75:
            # ----------------------------------------------------------------------------------------
            # LAST REFINE TRANSLATION ON TOP OF REFINED { ROLL + PITCH + YAW }
            # ----------------------------------------------------------------------------------------
            mov_warped_refined_rot = manual_warp(
                ref, mov,
                yaw+yaw_refine, pitch+pitch_refine, roll+roll_refine,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
            )
            if mode=="ABS_GRAD":
                mov_warped_refined_rot_g = abs_grad_convert(mov_warped_refined_rot)
            elif mode == "SCHARR":
                _, mov_warped_refined_rot_g = prepare_inputs_for_matching(ref, mov_warped_refined_rot, abstraction_offset_ref=self.abstraction_offset_ref)
            elif mode is None:
                mov_warped_refined_rot_g = ut.c2g(mov_warped_refined_rot)
            yaw_refine_last, pitch_refine_last, _homog_trans_last = estimate_translation(
                ref_g, mov_warped_refined_rot_g, self.refcalib,
                geometricscale=geometricscale
            )
            mov_warped_refined_final = manual_warp(
                ref, mov,
                yaw+yaw_refine+yaw_refine_last, pitch+pitch_refine+pitch_refine_last, roll+roll_refine,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
            )
            out = mov_warped_refined_final
        if auto >1.:
            compare = np.zeros((2*polar_ref.shape[0], polar_ref.shape[1]*2, polar_ref.shape[2]))
            try:
                compare[compare.shape[0]//2:, :compare.shape[1]//2, :] = ut.g2c((255.*polar_ref_g).astype(np.uint8)) # polar_ref
                compare[compare.shape[0]//2:, compare.shape[1]//2:, :] = ut.g2c((255.*polar_mov_g).astype(np.uint8)) # polar_mov
            except:
                pass
            compare[:compare.shape[0]//2, :compare.shape[1]//2, :] = (255.*polar_ref).astype(np.uint8)
            compare[:compare.shape[0]//2:, compare.shape[1]//2:, :] = (255.*polar_mov).astype(np.uint8)
            out = np.zeros_like(out)
            out[:compare.shape[0], :compare.shape[1], :] = compare
        self.yaw = yaw+yaw_refine+yaw_refine_last
        self.pitch = pitch+pitch_refine+pitch_refine_last
        self.roll = roll+roll_refine
        return [out]


# ------------------------------ MULTISPECTRAL DEDICATED REPRESENTATION ------------------------------------------------
def pre_convert_for_features(_img, amplification=1., gaussian=9, debug=0):
    """
    Two-step Multi-spectral Registration Via Key-point Detector and Gradient Similarity:
    Application to Agronomic Scenes for Proxy-sensing

    To compute the gradient of the image with a minimal impact of the light distribution (shadow, reflectance, specular)
    each spectral band is normalized using Gaussian blur [Sage and Unser, 2003],
    the kernel size is defined by next_odd(image_width^0.4) (19 in our case)
    and the final normalized images are defined by I=I /(G + 1) * 255
    where I is the spectral band and G is the Gaussian blur of those spectral bands.
    This first step minimizes the impact of the noise on the gradient and smooth the signal in case of high reflectance.
    Using this normalized image, the gradient Igrad(x;y) is computed with the sum of absolute Sharr filter [Seitz, 2010]
    for horizontal Sx and vertical Sy derivative, noted $I_grad(x,y) = 1/2 |Sx| + 1/2 |Sy|$ .
    Finally, all gradients Igrad(x;y) are normalized using CLAHE [Zuiderveld, 1994] to locally improve their intensity
    and increase the number of keypoints detected.

    :param _img:
    :param amplification:
    :param thresh:
    :return:
    """
    img = ut.c2g(_img.astype(np.float32))/255.

    img = filters.gaussian(img, sigma=gaussian)
    # img = exposure.equalize_adapthist(img)
    img = img*amplification
    img = (img * 0.5/np.average(img))
    if debug > 0.75:
        logging.info("Smoothed images")
        return (255*img).astype(np.uint8)
    img_g = filters.gaussian(img, sigma=9.)
    img = img/(img_g+1.)
    if debug > 0.5:
        logging.info("Normalized by gradients")
        return (255*img).astype(np.uint8)
    scharr = 0.5* (np.abs(filters.scharr_h(img)) + np.abs(filters.scharr_v(img))) # /255.
    import matplotlib.pyplot as plt
    out = scharr.clip(-1, 1).astype(float)
    out = (out * 0.5/np.average(out))
    if debug > 0.25:
        logging.info("Sharr")
        plt.figure()
        plt.imshow(scharr)
        plt.show()
        return (255*out).clip(0, 255).astype(np.uint8)
    # out = out.clip(0.01, 1)
    out = out.clip(0., 1)
    out = exposure.equalize_adapthist(out)
    return (255*out).astype(np.uint8)


def prepare_inputs_for_matching(ref, mov, abstraction=0., abstraction_offset_ref=1., debug=0):
    """
    Prepare pairs of inputs
    assuming that visible image is always sharper than the NIR image so visible has to be blurred slightly more
    """
    ref_new = pre_convert_for_features(ref, gaussian=abstraction_offset_ref+(21*abstraction), debug=debug)
    mov_new = pre_convert_for_features(mov, gaussian=(21*abstraction), debug=debug)
    return ref_new, mov_new


def abs_grad_convert(_img):
    img = ut.c2g(_img.astype(np.float32))
    img = filters.sobel(img)
    img = img*(0.5/np.average(img))
    img = (255.*img).clip(0, 255).astype(np.uint8)
    return img


# ---------------------------------------------- UTILITIES FOR VISUALIZATION -------------------------------------------
class Absgrad(ipipe.ProcessBlock):
    """Visualize abs grad for simpler registration quality evaluation
    """
    def apply(self, im1, im2, col, **kwargs):
        if col > 0.5:
            im1_g, im2_g = abs_grad_convert(im1), abs_grad_convert(im2)
            im1_c = np.zeros((im1_g.shape[0], im1_g.shape[1], 3))
            im1_c[:, :, 2] = im1_g
            im2_c = np.zeros((im2_g.shape[0], im2_g.shape[1], 3))
            im2_c[:, :, 0] = im2_g
            return [im1_c, im2_c]
        else:
            return [im1, im2]


class Transparency(ipipe.ProcessBlock):
    """
    Alpha blend between two images (between 0 & 1)...
    Switch from one to another around 0...
    Difference (between -0.5 & 0)
    Rectangle overlap (between -1 & 0.5)
    """
    def apply(self, im1, im2, alpha, **kwargs):
        if len(im1.shape) == 2:
            im1 = ut.g2c(im1)
        if len(im2.shape) == 2:
            im2 = ut.g2c(im2)
        if im1.shape[0] != im2.shape[0] or im1.shape[1] != im2.shape[1]:
            return im1 if alpha > 0.5 else im2
        if alpha <= -0.5:
            cmp = np.zeros_like(im1)
            shp = cmp.shape
            cmp = im2.copy()
            alpha_crop = 1-np.abs(alpha)
            limits_y = [int(shp[0]*alpha_crop), int(shp[0]*(1-alpha_crop))]
            limits_x = [int(shp[1]*alpha_crop), int(shp[1]*(1-alpha_crop))]
            cmp[limits_y[0]:limits_y[1], limits_x[0]: limits_x[1]] = im1[limits_y[0]:limits_y[1], limits_x[0]: limits_x[1]]
            return cmp
        elif alpha<=0.:
            return ((1-np.abs(alpha))*im1 + 2.*np.abs(alpha)*np.abs(im1-im2)).clip(0, 255)
        else:
            return (alpha * im1) + (1-alpha)*im2


# ---------------------------------------------- AUTO ALIGNMENT  -------------------------------------------------------
class SiftAlignment(ipipe.ProcessBlock):
    """
    Feature based rigid transform
    """
    def apply(self, ref, mov, flag, abstraction, threshold, debug=0., geometricscale=None, **kwargs):
        self.homography = np.eye(3)
        if flag <= 0.5:
            return mov
        else:
            # visible image is always sharper than IR image
            ref_new, mov_new = prepare_inputs_for_matching(ref, mov, abstraction=abstraction, debug=debug)
            match_debug_flag = flag > 0.9
            reg, homog, matchdebug = estimateFeaturePoints(
                ref_new,
                mov_new,
                debug=match_debug_flag,
                thresh=threshold
            )
            homog = np.linalg.inv(homog)
            self.homography = homog if geometricscale is None else np.dot(
                np.dot(
                    get_zoom_mat(1./geometricscale),
                    homog
                ),
                np.linalg.inv(get_zoom_mat(1./geometricscale))
            )  # homograpghy at full resolution
            if match_debug_flag:
                return matchdebug
            else:
                return cv2.warpPerspective(mov, homog, mov.shape[:2][::-1])


class BlockMatching(ipipe.ProcessBlock):
    """
    Patch based motion estimation with rigid transform
    """
    def apply(self, ref, mov, flag, abstraction, debug=0, geometricscale=None, **kwargs):
        self.homography = np.eye(3)
        if flag <= 0.5:
            return mov
        else:
            ref_new, mov_new = prepare_inputs_for_matching(ref, mov, abstraction=abstraction, debug=debug)
            homog = register_by_blocks(ref_new, mov_new, debug=flag > 1., patch_size=120, affinity=False)
            self.homography = homog if geometricscale is None else np.dot(
                np.dot(
                    get_zoom_mat(1./geometricscale),
                    homog
                ),
                np.linalg.inv(get_zoom_mat(1./geometricscale))
            )  # homograpghy at full resolution
            return cv2.warpPerspective(mov, homog, mov.shape[:2][::-1])
        return mov


# ---------------------------------------------- INTERACTIVE DEMO  -----------------------------------------------------


def align_demo(ref, mov, cals, params={}, abstraction_offset_ref=1):
    angles_amplitude = (-20., 20, 0.)
    auto_align = None
    rotate3d = SemiAutoAlignment(
        ROTATE,
        slidersName=["YAW", "PITCH", "ROLL", "AUTO"],
        inputs=[1, 2],
        outputs=[0],
        vrange=[
            angles_amplitude, angles_amplitude, angles_amplitude, (0., 1.01, 0.)
        ]
    )
    rotate3d.set_abstraction_offset_ref(abstraction_offset_ref)
    # USE SIFT = 1 to trigger debug , use <0.9 to view the classical result
    auto_sift = SiftAlignment(
        "SIFT", inputs=[1, 0], outputs=[0],
        slidersName=["SIFT", "ABSTRACT", "SIFT Threshold", "DEBUG"],
        vrange=[(0., 1., 0.88), (0., 1., 0.), (0., 1., 0.), (0., 1., 0.)]
    )
    auto_sift.homography = np.eye(3)
    auto_bm = BlockMatching(
        "BM", inputs=[1, 0], outputs=[0],
        slidersName=["BLOCK MATCHING", "Abstraction"],
        vrange=[(0., 1.01, 1.), (0., 1., 0.)]
    )
    auto_bm.homography = np.eye(3)
# ---------------------------------------------- AUTO ALIGNMENT  -------------------------------------------------------
    auto_align = [None, auto_bm, auto_sift][1]
    # auto_bm: auto alignment based on patch local motion estimation using phase correlation + rigid transform
    # auto_sift = feature matching based rigid transform estimation
# ----------------------------------------------------------------------------------------------------------------------

    alpha = Transparency("Alpha", inputs=[0, 1], vrange=(-1., 1., 1.))
    absgrad_viz = Absgrad("Absgrad visualize", inputs=[0, 1], outputs=[0, 1], vrange=(0, 1))
    rotate3d.set_movingcalib(cals["movingcalib"])
    rotate3d.set_refcalib(cals["refcalib"])
    ipi = ipipe.ImagePipe(
        [ref.data, mov.data],
        rescale=None,
        sliders=[
            rotate3d,  # semi auto alignment
            auto_align, # auto alignment (block matching / feature matching based)
            absgrad_viz,  # simpler visualization of alignment quality
            alpha  # alpha blend
        ]
    )
    if params is not None:
        ipi.set(
            **params
        )
    ipi.gui()
    alignment_parameters = dict(
        yaw=rotate3d.yaw,
        pitch=rotate3d.pitch,
        roll=rotate3d.roll,
        homography=None if (auto_align is None or auto_align.homography is None) else auto_align.homography,
        calibrations=cals
    )
    return alignment_parameters


def post_warp(ref, mov, params, img_name="img", linear=False):
    extension = "tif" if linear else "jpg"
    mov_warped_fullres = manual_warp(
        ref, mov,
        params["yaw"], params["pitch"], params["roll"],
        **params["calibrations"],
    )
    if params["homography"] is not None:
        mov_warped_fullres_refined = manual_warp(
            ref, mov,
            params["yaw"], params["pitch"], params["roll"],
            refinement_homography=params["homography"],
            **params["calibrations"],
        )
        if img_name is not None:
            pr.Image(mov_warped_fullres_refined, "IR registered refined").save("{}_IR_registered_semi_auto_REFINED.{}".format(img_name, extension))
            logging.warning("SAVE WITH REFINING WITH {}".format(params["homography"]))
            if not isinstance(ref, pr.Image):
                ref = pr.Image(ref)
            ref.save("{}_REF.{}".format(img_name, extension))
            pr.Image(mov_warped_fullres, "IR registered").save("{}_IR_registered_semi_auto.{}".format(img_name, extension))
        # pr.Image(abs_grad_convert(ref.data), "REF absgrad").save("%d_REF_absgrad.jpg"%number)
        # pr.Image(abs_grad_convert(mov_warped_fullres), "IR registered absgrad").save("%d_IR_registered_semi_auto_absgrad.jpg"%number)
    return mov_warped_fullres

# ------------------------------------------------------ JPG DEMO  -----------------------------------------------------
def real_images_pairs(number=[505, 230, 630][0]):
    """Demo inputs"""
    visref = pr.Image(
        ut.imagepath(r"%d-DJI-VI.jpg"%number, dirname="../samples")[0],
        name="visible reference"

    )
    irmoving = pr.Image(
        ut.imagepath(r"%d-SJM20-IR.JPG"%number, dirname="../samples")[0],
        name="ir moving"
    )
    ircalib = ut.cameracalibration(camera="M20")
    viscalib = ut.cameracalibration(camera="DJI")
    if number == 505:
        params = {ROTATE:[-15.76, 16.92, 0.88, 1.]}
    elif number == 630:
        params = {ROTATE:[-2.200000, 7.680000, -4.360000, 1.]}
    elif number == 230:
        params = {ROTATE:[1.76, 5.88, 0.0, 1.]}
    else:
        params = None
    return visref, irmoving, {"refcalib": viscalib, "movingcalib": ircalib}, params


def demo_jpg(number=630):
    ref, mov, cals, params = real_images_pairs(number=number)
    alignment = align_demo(ref, mov, cals, params=params)
    post_warp(ref, mov, alignment, img_name="{}".format(number))


def check_alignement(number=630):
    """Test semi-auto alignment on visible pairs
    Use manual angles to create a fake misalignment
    """
    ref, mov, cals, params = real_images_pairs(number=number)
    mov = pr.Image(ref.data)
    cals["refcalib"]["dist"] = None
    cals["movingcalib"] = cals["refcalib"]
    params = {
        "Absgrad visualize":[1.],
        "Alpha": [-0.48],
        "SIFT": [0.85,0.276000,0.000000,0.000000],
    }
    align_demo(ref, mov, cals,  params=params, abstraction_offset_ref=0)


# ------------------------------------------------------ RAW DEMO  -----------------------------------------------------
def align_raw(vis_path, nir_path, cals, out_dir=None, params=None):
    """Estimate alignment on raw files through semi-automatic alignment GUI.
    Then apply to linear raw & save 16bits tif ... (ready for any kind of multi-spectral fusion)

    :param vis_path: Path to visible DJI DNG image
    :param nir_path: Path to NIR SJCAM M20 RAW image
    :param cals: Geometric calibration dictionary.
    :param out_dir: Path to save images
    :param params: Params to initiate the GUI
    :return: 
    """
    vis = pr.Image(vis_path)
    nir = pr.Image(nir_path)
    if False:
        vis_undist = warp(vis.data, cals["refcalib"], np.eye(3)) # @TODO: Fix DJI calibration before using this
        vis_undist = pr.Image(vis_undist)
        vis_undist_lin = warp(vis.lineardata, cals["refcalib"], np.eye(3))
    else:
        vis_undist = vis
        vis_undist_lin = vis.lineardata
    alignment = align_demo(vis_undist, nir, cals, params=params)
    if out_dir is not None:
        if not osp.isdir(out_dir):
            os.mkdir(out_dir)
        prefix = osp.basename(vis_path)[:-4]
    out_non_lin = post_warp(
        vis_undist.data,
        nir,
        alignment,
        img_name=None if out_dir is None else osp.join(out_dir, prefix + "_raw_NON_LINEAR")
    )
    out_lin = post_warp(
        vis_undist_lin,
        nir.lineardata,
        alignment,
        img_name=None if out_dir is None else osp.join(out_dir, prefix + "_raw_LINEAR"),
        linear=True
    )
    return out_lin, out_non_lin, vis


def demo_raw(folder=osp.join(osp.dirname(__file__), "..", r"Hyperlapse 06_09_2021_sync")):
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
    for vis_pth in sorted(glob.glob(osp.join(folder, "*.DNG"))):
        print(osp.basename((vis_pth)))
        params = None
        phase_correl_default_flag = 1.
        bname = osp.basename(vis_pth)
        params = dict()
        if "20210906122928" in bname: params = {ROTATE: [4.2, 7.52, 0.56, phase_correl_default_flag]}
        if "20210906123134" in bname: params = {ROTATE: [3.44, 8.16, 0.32, phase_correl_default_flag]}
        if "20210906123514" in bname: params = {ROTATE: [0.4, 7.72, 1.88, phase_correl_default_flag]}
        if "20210906123918" in bname: params = {ROTATE: [3.48, 5.64, 1.88, phase_correl_default_flag]}
        if "20210906124318" in bname: params = {ROTATE: [1.84, 6.6, 2.84, phase_correl_default_flag]}
        if "20210906124530" in bname: params = {ROTATE: [2.24, 7.04, 1.52, phase_correl_default_flag]}
        params["Absgrad visualize"] = [1.]
        params["Alpha"] = [-0.47]
        nir_pth = vis_pth.replace("DNG", "RAW")
        # @TODO: FIX WHEN DJI GEOMETRIC CALIBRATION IS FIXED
        vis_pth_undist = vis_pth.replace(".DNG", "_PL4_DIST.tif")
        if osp.exists(vis_pth_undist):
            vis_pth = vis_pth_undist
        align_raw(vis_pth, nir_pth, cals, out_dir=out_dir, params=params)


if __name__ == "__main__":
    # check_alignement(number=630)
    raw = True
    if raw:
        demo_raw()
    else:
        demo_jpg(number=630)
        demo_jpg(number=230)
        demo_jpg(number=505)
