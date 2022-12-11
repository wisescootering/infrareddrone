# %%
%load_ext autoreload
%autoreload 2
import os.path as osp
import sys
import os
os.path.abspath('')
from os import mkdir
__file__ = os.path.abspath('')
sys.path.append(osp.join(__file__, ".."))
import irdrone.process as pr
from registration.cost import *
import matplotlib.pyplot as plt
import irdrone.process as process
import irdrone.utils as utils
from irdrone.semi_auto_registration import mellin_transform
from automatic_registration import user_assisted_manual_alignment
from irdrone.semi_auto_registration import manual_warp
from registration.cost import compute_cost_surfaces_with_traces
import matplotlib.pyplot as plt
plt.style.use('dark_background')
calibrations = dict(refcalib=utils.cameracalibration(camera="DJI_RAW"), movingcalib=utils.cameracalibration(camera="M20_RAW"))
# mandatory to avoid plotting figures in separate windows
%matplotlib inline 

# %% [markdown]
# # Loading images
# |Image             | Loading time   | Resolution          | Loading time (cached  tif) |
# |------------------|----------------|---------------------|----------------------------|
# | visible DJI DNG  | 7.6s           | 12Mpix (2992x3992)  |     3.3s                   |
# | nir sjcam RAW    | 27.2s          | 16Mpix (3448x4600)  |     4.6s                   |
# 

# %%
# %%timeit -n 1 -r 1
vis_img = pr.Image(osp.join(__file__, "..", "samples", "_visible.DNG"))
_vis_data = vis_img.get_data()
print(_vis_data.shape)

# %%
# %%timeit  -n 1 -r 1
nir_img = pr.Image(osp.join(__file__, "..", "samples", "_nir.RAW"))
_nir_data = nir_img.get_data()
print(_nir_data.shape)

# %%
process.show([nir_img, vis_img])

# %% [markdown]
# # Alignment of multispectral images
# ## Multispectral representation
# Back in 1998, Irani & Anandan explained very clearly that *Laplacian energies* would lead to a better suited multispectral images representation for alignment.
# 
# [Robust MultiSensor Image Alignment](http://www.weizmann.ac.il/math/irani/sites/math.irani/files/publications/multisensoralignment.pdf)
# > 2.The Image Representation
# 
# > The underlying assumption of multiple resolution alignment is that the corresponding signals 
# at all resolution levels contain enough correlated structure to allow stable matching. 
# This assumption is generally true when an image pair is obtained by the same sensor,
# or by two different cameras of same modality. However, in multi-sensor image pairs (ie image
# pairs taken by sensors of dierent modalities) the signals are correlated primarily in high
# resolution levels, while correlation between the signals tends to degrade substantially with
# the reduction in spatial resolution. This is because high resolution images capture high
# spatial frequency information, which corresponds to physical structure of the scene that is
# common to the two images. Low resolution images, on the other hand, depend heavily on
# illumination and on the photometric and physical imaging properties of the sensors which
# are characterized by low frequency information and these are substantially different in two
# multi-modality images
# 
# > The directional derivative is applied to the raw image in four directions horizontal, vertical and the two diagonals. Then each of the four generated derivative images is squared. Since the squaring operation doubles the frequency band, the raw image is filtered with a Gaussian prior to the derivative filtering to avoid aliasing effects)
# 
# Let's see the 4 directional components of the Laplacian energy representation

# %%
align_config = AlignmentConfig(
    mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
    dist_mode=[SSD, NTG][1],
    downscale=16,
    sigma_ref=5.,
    sigma_mov=3.,  # reducing blur for NIR image
    num_patches=6,
    search_size=5
)

vis_rep = multispectral_representation(
        vis_img,
        sigma_gaussian=align_config.sigma_ref, mode=align_config.mode
)

pr.show(representation_visualization(vis_rep)[0], figsize=(15, 3), suptitle="VIS")

nir_rep = multispectral_representation(
        nir_img,
        sigma_gaussian=align_config.sigma_mov, mode=align_config.mode
)


pr.show(representation_visualization(nir_rep)[0], figsize=(15, 3), suptitle="NIR distorted")
# representation_visualization_pairs(vis_rep, nir_rep, ref_orig=vis_img, mov_orig=nir_img, figsize=(10, 3))

# %% [markdown]
# ## Alignment process
# * The NIR image comes from a fisheye camera. It is affected by serious distorsion but this is not a problem as geometric calibration has been performed previously. Having a much wider field of view (FOV) is what actually allows an overlap with the visible DJI camera. 
# * When the drone is flying, you may think it is super steady as the visible images do not seem to be affected by any shake... but in reality, the drone is hihgly shaking. The visible camera is stabilized mechanically by a gimbal so you get the impression that the visible images are very steady.
#     * Roll of the drone leads to camera yaw, Pitch of the drone leads to camera pitch. Camera roll misalignment is usually zero because of the gimbal lock when the camera points towards the ground. 
#     * Hopefully, the fisheye has a much wider field of view than the DJI visible camera, therefore we're able to align the NIR image onto the visible image.
# * Let's manually align the NIR image onto the visible image using 3 degrees of freedom: virtual camera yaw, pitch and roll. You are virtually rotating the NIR camera and projecting into the visible camera (you get a much narrower field of view than the fisheye... equivalent to the DJI camera *this is all possible thanks to the initial camera calibrations*)
# * But first, let's get a coarse estimation of the camera misalignment from the EXIF data. Please beware that the exact computation is much more complex than this naïve computation and requires the estimated altitude
# 

# %%
pitch = (vis_img.flight_info["Gimbal Pitch"] + 90.)
yaw = -(vis_img.flight_info["Flight Roll"])
# roll = -3.
roll = 0. #cannot be estimated from metadata , shall be zero due to gimbal lock when camera points to the ground
yaw, pitch, roll
# 5.210 -2.523 -2.399


# %%
_alignment_params = user_assisted_manual_alignment(vis_img.data, nir_img.data, calibrations, yaw=yaw, pitch=pitch, roll=roll)

# %% [markdown]
# # Estimating the roll angle
# * It is possible to efficiently estimate the optimal roll by transforming the images into an efficient space using polar warp.
# In the polar representation (radius=x-axis, angle=y-axis), you simply have to perform a vertical search to get the equivalent roll.
# * First, we need to prepare the NIR data:
#     - with an undistorted NIR fisheye image. Precisely, this image has some distorsions (the one from the visible image, we simply reproject into that camera space).
#     - with a coarse pre-alignment in terms of yaw & pitch (allows the center to be correctly located)
# * Next we'll compute the MSR (laplacian energy)
# * Finally,
#     * we'll tranform into polar representation
#     * perform a "translation search" in the vertical direction (equivalent to polar application of a roll)

# %%
#NIR undistorted
niru = manual_warp(
    vis_img.data, nir_img.data,
    yaw, pitch, roll,
    refcalib=calibrations["refcalib"], movingcalib=calibrations["movingcalib"],
    refinement_homography=None,
    bigger_size_factor=1.,
)
pr.show(niru, suptitle=f"NIR undistorted Y={yaw:.1f}° P={pitch:.1f}° R={roll:.1f}°")
niru_rep = multispectral_representation(
        niru,
        sigma_gaussian=align_config.sigma_mov, mode=align_config.mode
)
pr.show(representation_visualization(niru_rep)[0], figsize=(15, 3), suptitle="NIR undistorted MSR")

# %% [markdown]
# Taking polar(MSR(NIR)) & polar(MSR(VIS))

# %%
vis_rep_polar, niru_rep_polar = mellin_transform(vis_rep, niru_rep)
pr.show([(vis_rep_polar, 'Polar - visible'), (niru_rep_polar, "Polar - NIR")], figsize=(5, 5))
pr.show([representation_visualization(vis_rep_polar)], figsize=(10, 2), suptitle='Polar - visible')
pr.show([representation_visualization(niru_rep_polar)], figsize=(10, 2), suptitle='Polar - NIR undistorted')

# %%
align_config = AlignmentConfig(
    mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
    dist_mode=[SSD, NTG][1],
    downscale=16,
    sigma_ref=5.,
    sigma_mov=3.,  # reducing blur for NIR image
    num_patches=1,
    search_size=5
)
align_config.search_x = 0
align_config.search_y = 10 

cost_dict = compute_cost_surfaces_with_traces(
    vis_rep_polar[:, :, :], niru_rep_polar[:, :, :],
    debug=True,
    suffix="",
    prefix="",
    align_config=align_config
)

# %%
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

# %%
profile = cost_dict["costs"][0, 0, :, 0, :].sum(axis=-1)
amin, min_cost = np.argmin(profile), np.min(profile)
poly_coeffs = poly_fit_1d(profile, amin, neighborhood = 1)
coarse_roll_angle = amin - poly_coeffs[1]/(2*poly_coeffs[0]) - len(profile)//2
plot=True
if plot:
    refined_argmin = - poly_coeffs[1] /(2 * poly_coeffs[0])
    refined_min = poly_coeffs[0]*refined_argmin**2 + poly_coeffs[1]*refined_argmin+poly_coeffs[2]
    x_fit = build_x_poly_values(np.linspace(-2, 2, num=100))
    y_fit = np.dot(x_fit, poly_coeffs)
    plt.figure(figsize=(10, 10))
    plt.plot(np.arange(len(profile)) - len(profile)//2, profile, "r--", label="cost function")
    plt.plot(amin- len(profile)//2, min_cost, "go")
    plt.plot(x_fit[:, 1]+amin - len(profile)//2, y_fit, "b-", label="Parabola fitting")
    plt.plot(amin+refined_argmin - len(profile)//2, refined_min, "mo", label=f"REFINED {coarse_roll_angle}")
    plt.title("Polar matching cost")
    plt.xlabel("Polar Angle")
    plt.ylabel("Matching cost")
    plt.legend()
    plt.grid()