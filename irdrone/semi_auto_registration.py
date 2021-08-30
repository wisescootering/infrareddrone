from skimage.registration import phase_cross_correlation
from itertools import product
import matplotlib.pyplot as plt
import numpy as np
import cv2
import irdrone.utils as ut
import irdrone.process as pr
from application import warp
import irdrone.imagepipe as ipipe
from skimage.transform import warp_polar
from skimage import filters



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
    # mov_u = pr.Image(
    #     mov_u,
    #     "Yaw {}° Pitch {}°".format(yaw_main, pitch_main)
    # )
    return mov_u


def estimate_translation(ref, mov_warped, refcalib, geometricscale=None):
    # ----------------------------------------------------------------------------------------
    shifts, error, phase_diff = phase_cross_correlation(
        ut.c2g(ref.astype(np.uint8)),
        ut.c2g(mov_warped.astype(np.uint8)),
    )
    translation = shifts[::-1]
    focal = refcalib["mtx"][0, 0].copy() # we estimate the displacement in the "reference" camera space (in the visible space)
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
    polar_mov = warp_polar(movi, radius=radius, multichannel=True, scaling=scaling)
    polar_ref = warp_polar(refi, radius=radius, multichannel=True, scaling=scaling)

    def special_convert(_img):
        img = ut.c2g(_img.astype(np.float32))
        img = filters.sobel(img)
        img = img*(0.5/np.average(img))
        img = (255.*img).clip(0, 255).astype(np.uint8)
        return img
    polar_mov_g = special_convert(polar_mov)
    polar_ref_g = special_convert(polar_ref)
    return polar_ref, polar_mov, polar_ref_g, polar_mov_g


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
        debug=True
        mov_warped = manual_warp(
            ref, mov,
            yaw, pitch, roll,
            refcalib=self.refcalib, movingcalib=self.movingcalib,
            geometric_scale=geometricscale
        )
        mov_warped_refined = mov_warped
        if auto > 0.25:
            # ----------------------------------------------------------------------------------------
            # REFINE TRANSLATION (PITCH & YAW)
            # ----------------------------------------------------------------------------------------
            yaw_refine, pitch_refine, homog_trans = estimate_translation(
                ref, mov_warped, self.refcalib,
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
        if auto >= 0.5:
            # ----------------------------------------------------------------------------------------
            # REFINE ROLL
            # ----------------------------------------------------------------------------------------
            mov_warped = mov_warped_refined
            polar_ref, polar_mov, polar_ref_g, polar_mov_g = mellin_transform(ref, mov_warped)
            roll_refine, roll_homog = estimate_rotation(polar_ref_g, polar_mov_g, ref)
            mov_warped_refined_rot = manual_warp(
                ref, mov,
                yaw+yaw_refine, pitch+pitch_refine, roll,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
                refinement_homography=roll_homog
            )
            mov_warped_refined = mov_warped_refined_rot
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
            yaw_refine_last, pitch_refine_last, _homog_trans_last = estimate_translation(
                ref, mov_warped_refined_rot, self.refcalib,
                geometricscale=geometricscale
            )
            mov_warped_refined_final = manual_warp(
                ref, mov,
                yaw+yaw_refine+yaw_refine_last, pitch+pitch_refine+pitch_refine_last, roll+roll_refine,
                refcalib=self.refcalib, movingcalib=self.movingcalib,
                geometric_scale=geometricscale,
            )
            mov_warped_refined = mov_warped_refined_final
        if auto >1.:
            compare = np.zeros((2*polar_ref.shape[0], polar_ref.shape[1]*2, polar_ref.shape[2]))
            compare[compare.shape[0]//2:, :compare.shape[1]//2, :] = ut.g2c(polar_ref_g) # polar_ref
            compare[compare.shape[0]//2:, compare.shape[1]//2:, :] = ut.g2c(polar_mov_g) # polar_mov
            compare[:compare.shape[0]//2, :compare.shape[1]//2, :] = polar_ref
            compare[:compare.shape[0]//2:, compare.shape[1]//2:, :] = polar_mov
            mov_warped_refined = np.zeros_like(mov_warped_refined)
            mov_warped_refined[:compare.shape[0], :compare.shape[1], :] = compare
        return [mov_warped_refined]


def real_images_pairs(number=[505, 230]):
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
        params = {"Rotate":[-15.76, 16.92, 0.0, 1.]}
    else:
        params = None
    return visref, irmoving, {"refcalib": viscalib, "movingcalib": ircalib}, params


class Transparency(ipipe.ProcessBlock):
    def apply(self, im1, im2, alpha, **kwargs):
        if im1.shape[0] != im2.shape[0] or im1.shape[1] != im2.shape[1]:
            return im1 if alpha > 0.5 else im2
        if alpha<=0:
            return ((1-np.abs(alpha))*im1 + 2.*np.abs(alpha)*np.abs(im1-im2)).clip(0, 255)
        else:
            return (alpha * im1) + (1-alpha)*im2


def demo(number=230):
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
    alpha = Transparency("Alpha", inputs=[0, 1], vrange=(-1., 1., 1.))
    rotate3d.set_movingcalib(cals["movingcalib"])
    rotate3d.set_refcalib(cals["refcalib"])
    ipi = ipipe.ImagePipe(
        [ref.data, mov.data],
        rescale=None,
        sliders=[
            rotate3d,
            alpha
        ]
    )
    if params is not None:
        ipi.set(
            **params
        )
    ipi.gui()

if __name__ == "__main__":
    demo(number=230)
    demo(number=505)

