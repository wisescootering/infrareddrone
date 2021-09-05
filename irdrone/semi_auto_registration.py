from skimage.registration import phase_cross_correlation
from skimage.transform import warp_polar
from skimage import filters
import numpy as np
import cv2
import irdrone.utils as ut
import irdrone.process as pr
from application import warp
import irdrone.imagepipe as ipipe
from irdrone.registration import register_by_blocks, estimateFeaturePoints


def manual_warp(ref: pr.Image, mov: pr.Image, yaw_main: float, pitch_main: float, roll_main: float = 0.,
                refcalib=None, movingcalib=None, geometric_scale=None, refinement_homography=None):
    rot_main, _ = cv2.Rodrigues(np.array([-np.deg2rad(pitch_main), np.deg2rad(yaw_main), np.deg2rad(roll_main)]))
    mov_calib = movingcalib.copy()
    if geometric_scale is None:
        h = np.dot(np.dot(refcalib["mtx"], rot_main), np.linalg.inv(movingcalib["mtx"]))
    else:
        zoom_mat_mov = np.eye(3)
        zoom_mat_mov[0, 0] = geometric_scale
        zoom_mat_mov[1, 1] = geometric_scale
        zoom_mat_ref = zoom_mat_mov.copy()
        ref_cal = refcalib["mtx"].copy()
        mov_cal = movingcalib["mtx"].copy()
        ref_cal = np.dot(zoom_mat_ref, ref_cal)
        mov_cal = np.dot(zoom_mat_mov, mov_cal)
        h = np.dot(np.dot(ref_cal, rot_main), np.linalg.inv(mov_cal))
        mov_calib["mtx"] = mov_cal
    if refinement_homography is not None:
        h = np.dot(refinement_homography, h)
    mov_u = warp(mov, mov_calib, h, outsize=(ref.data.shape[1], ref.data.shape[0]))
    return mov_u


def estimate_translation(ref, mov_warped, refcalib, geometricscale=None):
    # ----------------------------------------------------------------------------------------
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


def abs_grad_convert(_img):
    img = ut.c2g(_img.astype(np.float32))
    img = filters.sobel(img)
    img = img*(0.5/np.average(img))
    img = (255.*img).clip(0, 255).astype(np.uint8)
    return img


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
    refcalib = None
    movingcalib = None

    def set_refcalib(self, _refcalib):
        self.refcalib = _refcalib

    def set_movingcalib(self, _movingcalib):
        self.movingcalib = _movingcalib

    def apply(self, ref, mov, yaw, pitch, roll, auto, geometricscale=None, **kwargs):
        yaw_refine, yaw_refine_last, pitch_refine, pitch_refine_last, roll_refine = 0., 0., 0., 0., 0.
        debug=False
        abs_grad = True
        ref_g = abs_grad_convert(ref) if abs_grad else ref
        mov_warped = manual_warp(
            ref, mov,
            yaw, pitch, roll,
            refcalib=self.refcalib, movingcalib=self.movingcalib,
            geometric_scale=geometricscale
        ) # manual warp in colors
        out = mov_warped
        mov_warped_g = abs_grad_convert(mov_warped) if abs_grad else mov_warped
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
            mov_warped_refined_g = abs_grad_convert(mov_warped_refined) if abs_grad else mov_warped_refined
            out = mov_warped_refined
        if auto >= 0.5:
            # ----------------------------------------------------------------------------------------
            # REFINE ROLL
            # ----------------------------------------------------------------------------------------
            polar_ref_g, polar_mov_g = mellin_transform(ref_g, mov_warped_refined_g)
            polar_ref, polar_mov = mellin_transform(ref, mov_warped_refined) # colored for debugging
            roll_refine, roll_homog = estimate_rotation(polar_ref_g, polar_mov_g, ref)
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
            mov_warped_refined_rot_g = abs_grad_convert(mov_warped_refined_rot) if abs_grad else mov_warped_refined_rot
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
            compare[:compare.shape[0]//2, :compare.shape[1]//2, :] = polar_ref
            compare[:compare.shape[0]//2:, compare.shape[1]//2:, :] = polar_mov
            out = np.zeros_like(out)
            out[:compare.shape[0], :compare.shape[1], :] = compare
        self.yaw = yaw+yaw_refine+yaw_refine_last
        self.pitch = pitch+pitch_refine+pitch_refine_last
        self.roll = roll+roll_refine
        return [out]


class Absgrad(ipipe.ProcessBlock):
    def apply(self, im1, im2, col, **kwargs):
        if col > 0.5:
            # return [abs_grad_convert(im1), abs_grad_convert(im2)]
            im1_g, im2_g = abs_grad_convert(im1), abs_grad_convert(im2)
            im1_c = np.zeros((im1_g.shape[0], im1_g.shape[1], 3))
            im1_c[:, :, 2] = im1_g
            im2_c = np.zeros((im2_g.shape[0], im2_g.shape[1], 3))
            im2_c[:, :, 0] = im2_g
            return [im1_c, im2_c]
        else:
            return [im1, im2]


class Transparency(ipipe.ProcessBlock):
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
            alpha_crop = np.abs(alpha) - 0.5
            limits_y = [int(shp[0]*alpha_crop), int(shp[0]*(1-alpha_crop))]
            limits_x = [int(shp[1]*alpha_crop), int(shp[1]*(1-alpha_crop))]
            cmp[limits_y[0]:limits_y[1], limits_x[0]: limits_x[1]] = im1[limits_y[0]:limits_y[1], limits_x[0]: limits_x[1]]
            return cmp
        elif alpha<=0.:
            return ((1-np.abs(alpha))*im1 + 2.*np.abs(alpha)*np.abs(im1-im2)).clip(0, 255)
        else:
            return (alpha * im1) + (1-alpha)*im2


def pre_convert_for_features(_img, amplification=1., thresh=0.01):
    """
    Two-step Multi-spectral Registration Via Key-point Detector and Gradient Similarity:
    Application to Agronomic Scenes for Proxy-sensing

    :param _img:
    :param amplification:
    :param thresh:
    :return:
    """
    img = ut.c2g(_img.astype(np.float32))
    if thresh == 0.:
        return img.astype(np.uint8)
    img = filters.sobel(img)
    img = (img > thresh)*img
    img = img*(0.5/np.average(img))
    img = (255.*img).clip(0, 255).astype(np.uint8)
    return img

class BlockMatching(ipipe.ProcessBlock):
    def apply(self, ref, mov, flag, threshold, geometricscale=None, **kwargs):
        if flag <= 0.5:
            return mov
        else:
            ref_new = pre_convert_for_features(ref, thresh=threshold)
            mov_new = pre_convert_for_features(mov, amplification= 3., thresh=threshold)
            homog = register_by_blocks(ref_new, mov_new, debug=flag > 0.9, patch_size=120)
            return cv2.warpPerspective(mov, homog, mov.shape[:2][::-1])
        return mov


class SiftAlignment(ipipe.ProcessBlock):
    def apply(self, ref, mov, flag, threshold, geometricscale=None, **kwargs):
        if flag <= 0.5:
            return mov
        else:
            ref_new = pre_convert_for_features(ref, thresh=threshold)
            mov_new = pre_convert_for_features(mov, amplification=3., thresh=threshold)
            print(ref_new.shape, mov_new.shape)
            match_debug_flag = flag > 0.9
            reg, h, matchdebug = estimateFeaturePoints(ref_new, mov_new, debug=match_debug_flag)
            if match_debug_flag:
                return matchdebug
            else:
                return cv2.warpPerspective(mov, h, mov.shape[:2][::-1])


def real_images_pairs(number=[505, 230, 630][0]):
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
        params = {"Rotate":[-15.76, 16.92, 0.88, 1.]}
    elif number == 630:
        params = {"Rotate":[-2.200000,7.680000,-4.360000, 1.]}
    elif number == 230:
        params = {"Rotate":[1.76 ,5.88 , 0.0 , 1.]}
    else:
        params = None
    return visref, irmoving, {"refcalib": viscalib, "movingcalib": ircalib}, params


def demo(number=230, save_full_res=True):
    ref, mov, cals, params = real_images_pairs(number=number)
    angles_amplitude = (-20., 20, 0.)
    rotate3d = ManualAlignment(
        "Rotate",
        slidersName=["YAW", "PITCH", "ROLL", "AUTO"],
        inputs=[1, 2],
        outputs=[0,],
        vrange=[
            angles_amplitude, angles_amplitude,angles_amplitude, (0., 1.01, 1.)
        ]
    )
    auto_sift = SiftAlignment("SIFT", inputs=[1, 0], outputs=[0],
                         slidersName=["SIFT", "Threshold"], vrange=[(0., 1., 0.), (0., 1., 0.)])
    auto_bm = BlockMatching("BM", inputs=[1, 0], outputs=[0],
                            slidersName=["BLOCK MATCHING", "Threshold"], vrange=[(0., 1., 0.), (0., 1., 0.)]
                            )
    alpha = Transparency("Alpha", inputs=[0, 1], vrange=(-1., 1., 1.))
    absgrad = Absgrad("Absgrad", inputs=[0, 1], outputs=[0, 1], vrange=(0, 1))
    rotate3d.set_movingcalib(cals["movingcalib"])
    rotate3d.set_refcalib(cals["refcalib"])
    ipi = ipipe.ImagePipe(
        [ref.data, mov.data],
        rescale=None,
        sliders=[
            rotate3d,
            # auto_sift,
            # auto_bm,
            absgrad,
            alpha
        ]
    )
    if params is not None:
        ipi.set(
            **params
        )
    ipi.gui()
    mov_warped_fullres = manual_warp(
        ref, mov,
        rotate3d.yaw, rotate3d.pitch, rotate3d.roll,
        **cals,
    )
    if save_full_res:
        pr.Image(mov_warped_fullres, "IR registered").save("%d_IR_registered_semi_auto.jpg"%number)
        pr.Image(abs_grad_convert(ref.data), "REF absgrad").save("%d_REF_absgrad.jpg"%number)
        pr.Image(abs_grad_convert(mov_warped_fullres), "IR registered absgrad").save("%d_IR_registered_semi_auto_absgrad.jpg"%number)

if __name__ == "__main__":
    demo(number=630)
    demo(number=230)
    demo(number=505)

