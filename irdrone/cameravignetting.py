"""
Calibrate camera vignetting from single "white chart" image

WARNING: This script has been written pretty quickly.
Calibrating shading maps is a science which takes a lot of time ...
The proper way to calibrate is to use multiple shoots of the same tiny white chart / integrating sphere / screen
under constant illumination , multiple pictures allow to cover the whole field of view ...
This method was NOT used here, just some quick shortcuts!

White sheets in front of the sun for NIR, white wall for visible


------------------------------------------------------------------------------------------------------------------------
1/ DJI calibration : image out of Raw therapee / image out of DxO Photolab 4 with vignetting correction enabled
provides a map that we downscale and store in a pickle file...
-
while loading a new DJI DNG file in pr.Image
we'll load that thumbnail numpy pickle file, upsample it to full resolution
and simply perform a multiplication with raw buffer
------------------------------------------------------------------------------------------------------------------------
2/ SJCAM M20 calibration: image of a white sheet is supposed to be uniform. We use a rotation invariant model
shading curve is extracted from the polar representation on the diagonals.
by modifying the code you can modify the control points of the cubic curve to adjust the shading profile.
This is how the curves were fitted. (search CHANGE THE CUBIC HERE!!!!!!),
you'll need to do this 3 times for each color channel.
Press I to view the control points when the interactive curve shows up
Then update the calibration dict (take example on SJCAM_M20_PROFILE_CONTROL_POINT = {R : [(x, y) ... ], G: .., B :..}
(note : we fit a curve for R & G & B ... usually, a fisheye tends to have blue vignetting in the visible colors)
-
while loading a new SJCAM RAW file in pr.Image,
we'll sample the profile from the parametric control points,
then create a shading correction map by revolution (polar 2 cartesian)
then simply perform a multiplication with the raw buffers

NOTE: the bump in the middle of the frame is probably due to reflections of the sensor onto the lens
(coating was removed, cheap lens) .
@TODO: fit a blob in the middle

"""
import os.path as osp
import irdrone.process as pr
import matplotlib.pyplot as plt
from skimage import filters, transform
from scipy.ndimage import gaussian_filter1d
from irdrone.utils import get_shading_profile, get_polar_shading_map
from skimage import exposure
import numpy as np
import cv2


DEFAULT_SHADING_PROFILE = [
    (-2013.186139572626, 1.0285597058816314),
    (196.1657528923779, 1.0138095996814964),
    (672.4623430384404, 0.9758875264857452),
    (1240.4111479507396, 1.0150339670490343),
    (1686.281583682889, 1.068122341155305),
    (2056.884896435969, 1.204810909017386),
    (2396.436069270902, 1.2303145442390813),
    (3045.416916737508, 0.7854837645467905),
    (3357.444414697938, 0.3475093200941026)
]

SJCAM_M20_PROFILE_CONTROL_POINTS = {
    "R" :[(-2013.186139572626, 1.0285597058816314), (196.1657528923779, 1.0138095996814964), (672.4623430384404, 0.9758875264857452), (1240.4111479507396, 1.0150339670490343), (1686.281583682889, 1.068122341155305), (2056.884896435969, 1.204810909017386), (2396.436069270902, 1.2303145442390813), (3045.416916737508, 0.7854837645467905), (3357.444414697938, 0.3475093200941026)],
    "G": [(-1818.1593058299723, 0.9593926491976511), (184.6507089333645, 1.016621860616801), (672.4623430384404, 0.9758875264857452), (1240.4111479507396, 1.0150339670490343), (1672.6256359791887, 1.0733830394880173), (2022.0053655849624, 1.2150426799356917), (2363.4446467906046, 1.245596720032249), (2994.7102946010355, 0.7414550584390546), (3256.7450918053655, 0.32619787712675397)],
    "B":[(-1872.1109909763832, 0.9448023256039491), (174.521941381101, 1.016191567620653), (650.7576814104391, 0.9787972027547605), (1241.1325657443285, 1.0204409272645043), (1668.6554117791238, 1.0786695019553694), (2008.6199153783855, 1.2239852542049876), (2347.1015157298157, 1.2613796190708801), (2895.4546895993954, 0.7369495461155825), (3357.444414697938, 0.3475093200941026)]
}

def load_white_charts(camera_name="M20_RAW"):
    ref_, ref = None, None
    if camera_name == "DJI_RAW":
        radial_shading_calibration = None
        vig_folder = osp.join(osp.dirname(__file__), "..", "camera_calibration", "DJI_RAW_lens_shading")
        vig_ = osp.join(vig_folder, "DJI_Nappe Blanche_0936_RAW_Therapee.tif")
        ref_ = osp.join(vig_folder, "DJI_Nappe Blanche_0936PL_Neutral_Vig.tif")
    elif camera_name == "M20_RAW":
        radial_shading_calibration = SJCAM_M20_PROFILE_CONTROL_POINTS
        vig_folder = osp.join(osp.dirname(__file__), "..", "camera_calibration", "M20_RAW_lens_shading")
        vig_ = osp.join(vig_folder, "nappe Blanhe_037.RAW")
    vig = pr.Image(vig_, shading_correction=False).lineardata
    if ref_ is not None:
        ref = pr.Image(ref_, shading_correction=False).lineardata
    return vig, ref, radial_shading_calibration


def plot_channels(cartesian_image):
    img_shape = cartesian_image.shape
    center = [cartesian_image.shape[0]/2, cartesian_image.shape[1]/2]
    im = transform.warp_polar(cartesian_image, center=center, multichannel=True)
    fig, axs = plt.subplots(2, 3)
    for ch in range(im.shape[2]):
        axs[0, ch].imshow(im[:, :, ch])
        axs[0, ch].set_title("RGB"[ch])
        diag_angle = np.rad2deg(np.arctan((img_shape[0])/(img_shape[1])))
        diag_angle = int(diag_angle)
        im[:, :, ch] = filters.gaussian(im[:, :, ch], sigma=1)
        for angle in [0, 90, 180, 270]:
            axs[1, ch].plot(im[angle, :, ch], "--b", alpha=0.25, label="{}°".format(angle))
        diaglist = []
        for angle in [diag_angle, 180-diag_angle, 180+diag_angle, 360-diag_angle]:
            axs[1, ch].plot(im[angle, :, ch], "--", alpha=0.5, label="{}°".format(angle))
            diaglist.append(im[angle, :, ch])
        avg_radial_profile = np.average(np.array(diaglist), axis=0)
        axs[1, ch].plot(avg_radial_profile, "k-", label="AVERAGE".format(angle))
        # axs[1, ch].set_legend(True)
        axs[1, ch].legend()
    plt.show()


def interactive_cubic_profile(avg_radial_profile, verts=None, black_circle=2550):
    from path_editor import PathInteractor, interpolate, ax
    from matplotlib.lines import Line2D
    ax.plot(avg_radial_profile, "r--")
    if verts is None:
        verts = [(ra, avg_radial_profile[ra]) for ra in [0, 500, 1568, 2173, black_circle-1]]
        verts = verts + [(3000, 1)]
    x, y = interpolate(*zip(*verts))
    spline = Line2D(x, y)
    ax.add_line(spline)
    interactor = PathInteractor(spline, verts)
    ax.set_title('refine vertices to match shading correction, press I to print')
    plt.show()
    return interactor.verts


def polar_profiles(cartesian_image, black_circle=2550, verts_colors=SJCAM_M20_PROFILE_CONTROL_POINTS):
    """

    :param cartesian_image: shading correction ratios (x,y cartesian coordinates system, not polar!)
    :param black_circle: radius of a black circle
    :param verts_colors: control points of a cubic curve. None will allow you to fit a curve interactively
    :return:
    """
    img_shape = cartesian_image.shape
    center = [cartesian_image.shape[0]/2, cartesian_image.shape[1]/2]
    im = transform.warp_polar(cartesian_image, center=center, multichannel=True)
    for ch in range(im.shape[2]):
        diag_angle = np.rad2deg(np.arctan((img_shape[0])/(img_shape[1])))
        diag_angle = int(diag_angle)
        im[:, :, ch] = filters.gaussian(im[:, :, ch], sigma=2)
        diaglist = []
        for angle in [diag_angle, 180-diag_angle, 180+diag_angle, 360-diag_angle]:
            diaglist.append(im[angle, :, ch])
        avg_radial_profile_noisy = np.average(np.array(diaglist), axis=0)
        avg_radial_profile = avg_radial_profile_noisy.copy()
        if black_circle is not None:
            avg_radial_profile[black_circle:] = avg_radial_profile[black_circle]
        avg_radial_profile = gaussian_filter1d(avg_radial_profile, sigma=50)
        if black_circle is not None:
            avg_radial_profile[black_circle:] = 1.
        avg_radial_profile = 1.*(avg_radial_profile < 0.5)+ avg_radial_profile*(avg_radial_profile >= 0.5)
        x_lin = np.array(range(len(avg_radial_profile)))
        if verts_colors is not None:
            try: # CHANGE THE CUBIC HERE!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                verts = verts_colors["RGB"[ch]]
                # if ch ==0: # VERY MANUAL, FIT FOR EACH COLOR
                #     verts = interactive_cubic_profile(avg_radial_profile, verts=verts, black_circle=black_circle)
            except:
                verts = interactive_cubic_profile(avg_radial_profile, verts=DEFAULT_SHADING_PROFILE, black_circle=black_circle)
                print("COPY PASTE YOUR SHADING PROFILE NOW \n {}".format(verts))
            parametric_profile = get_shading_profile(verts, x_lin)
        fi, axd = plt.subplots(3,1)
        axd[0].plot(x_lin, parametric_profile, "--b", label="parametric shading profile")
        axd[0].plot(avg_radial_profile, "--r", label="shading profile")
        axd[0].set_title("Lens shading correction profile %s"%("RGB"[ch]))
        radial_map = np.zeros_like(im[:, :, ch])
        radial_map = np.repeat(np.array([parametric_profile]), radial_map.shape[0], axis=0)
        axd[1].imshow(radial_map)
        axd[2].set_title("Lens shading polar map")
        unpolar = cv2.warpPolar(
            1./radial_map[:,:],
            (img_shape[1], img_shape[0]),
            center=center[::-1],
            maxRadius=radial_map.shape[1],
            flags=cv2.WARP_INVERSE_MAP
        )
        axd[2].imshow(unpolar)
        axd[2].set_title("Lens shading parametric map")
        plt.show()


def lens_shading_calibration(vig, ref=None, shading_control_point=None, calib_path=None):
    if ref is None:
        roi_size = 400
        center_grey = np.average(vig[vig.shape[0]//2-roi_size: vig.shape[0]//2+roi_size, vig.shape[1]//2-roi_size:vig.shape[1]//2+roi_size, :], axis=(0,1))
        ratios = np.ones_like(vig)
        for ch in range(vig.shape[2]):
            ratios[:, :, ch] = center_grey[ch]/vig[:, :, ch]
        plot_channels(ratios)
        polar_profiles(ratios, verts_colors=shading_control_point)
    else:
        # sigma = 21.
        sigma = 4.
        if sigma > 0:
            ratios = filters.gaussian(ref, sigma, multichannel=False)/filters.gaussian(vig, sigma, multichannel=False)
        else:
            ratios = ref/vig
        # roi_size = 400
        # center_grey = np.average(
        #     ratios[
        #         ratios.shape[0]//2-roi_size: ratios.shape[0]//2+roi_size,
        #         ratios.shape[1]//2-roi_size:ratios.shape[1]//2+roi_size,
        #         :
        #     ], axis=(0,1)
        # )
        # for ch in range(3):
        #     ratios[:, :, ch] = ratios[:, :, ch] / center_grey[ch]
        scaling = 10
        ratios_thumb = cv2.resize(ratios, (ratios.shape[1]//scaling, ratios.shape[0]//scaling), interpolation=cv2.INTER_AREA)
        # import json
        # with open(osp.join(osp.dirname(__file__), "..", "calibration", camera_name, "shading_calibration.json"), 'w') as outfile:
        #     json.dump(dict(vignetting_map=ratios_thumb.tolist(), scaling=10), outfile)
        np.save(
            calib_path,
            ratios_thumb
        )
        ratios_up = cv2.resize(ratios_thumb, (ratios.shape[1], ratios.shape[0]), interpolation=cv2.INTER_LINEAR)
        plt.imshow(ratios_thumb[:,:, 2]/ratios_thumb[:,:, 1])
        plt.show()
        plt.imshow(ratios_thumb[:,:, 0]/ratios_thumb[:,:, 1])
        plt.show()
        plt.imshow(ratios_up[:,:, 0])
        plt.show()
    fig, axs = plt.subplots(1, 4)
    axs[0].imshow(2.*(1./ratios[:, :, :]-1.) + 0.5)
    axs[1].imshow(1./ratios[:, :, 0])
    axs[2].imshow(1./ratios[:, :, 1])
    axs[3].imshow(1./ratios[:, :, 2])
    plt.show()


def calibrate(camera_name="DJI_RAW"):
    vig, ref, radial_shading_calibration = load_white_charts(camera_name=camera_name)
    lens_shading_calibration(
        vig,
        ref=ref,
        shading_control_point=radial_shading_calibration,
        calib_path=osp.join(osp.dirname(__file__), "..", "calibration", camera_name, "shading_calibration")
    )


def test_calibration_DJI():
    camera_name = "DJI_RAW"
    shading_correction = np.load(
        osp.abspath(osp.join(osp.dirname(__file__), "..", "calibration", camera_name, "shading_calibration.npy"))
    )
    img_path = osp.join(osp.dirname(__file__), "..", "Hyperlapse 06_09_2021-2021_sync", "20210906122928.DNG")
    img_ = pr.Image(img_path, shading_correction=False)
    img_done = pr.Image(img_path)
    pr.show([img_.lineardata, img_done.lineardata])
    img = img_.lineardata


    shading_map = cv2.resize(shading_correction, (img.shape[1], img.shape[0]))
    img_shading = shading_map*img

    pr.Image(img).save(img_path[:-3]+"_VIG_CORRECTION_OFF.tif")
    pr.Image(img_shading).save(img_path[:-3]+"_VIG_CORRECTION_ON.tif")
    pr.show([img, img_shading])
    plt.imshow(img/img_shading)
    plt.show()



def contrast_stretching(img, percentiles=None):
    crop_black_circle = 450
    if percentiles is not None:
        p2, p98 = percentiles[0], percentiles[1]
        print("percentiles", p2, p98)
    else:
        p2, p98 = np.percentile(img[:, crop_black_circle:-crop_black_circle, 1], (2, 98))
    img_rescale = exposure.rescale_intensity(img, in_range=(p2, p98))
    return img_rescale, [p2, p98]

def test_calibration_M20():
    camera_name = "M20_RAW"
    img_shape = (3448, 4600, 3)
    vig_map = get_polar_shading_map(img_shape=img_shape, calib=SJCAM_M20_PROFILE_CONTROL_POINTS)
    img_path = osp.join(osp.dirname(__file__), "..", "Hyperlapse 06_09_2021-2021_sync", "20210906122928.RAW")
    img_ = pr.Image(img_path, shading_correction=False)
    img_done = pr.Image(img_path)
    img_adapteq_vig, perc = contrast_stretching(img_done.lineardata)
    img_adapteq, _ = contrast_stretching(img_.lineardata, percentiles=perc)
    pr.show([img_adapteq.data, img_adapteq_vig.data], ["original", "corrected_load"])

    plt.imshow(img_done.lineardata[:,:,1]/img_.lineardata[:,:,1])
    plt.show()
    pr.show([img_.data, img_done.data], ["original", "corrected_load"])

    pr.Image(img_.lineardata).save(img_path[:-3]+"_VIG_CORRECTION_OFF.tif")
    pr.Image(img_done.lineardata).save(img_path[:-3]+"_VIG_CORRECTION_ON.tif")

    img = img_.lineardata
    img_corr = (img*vig_map).clip(0.,1.)
    pr.show([img, img_corr])
    plt.imshow(vig_map[:,:, 1])
    plt.show()
    plt.imshow(img_corr-img)
    plt.show()


if __name__ == "__main__":
    calibrate(camera_name="M20_RAW")
    calibrate(camera_name="DJI_RAW")
    test_calibration_DJI()
    test_calibration_M20()