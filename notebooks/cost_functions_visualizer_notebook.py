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
plt.style.use('dark_background')
calibrations = dict(refcalib=utils.cameracalibration(camera="DJI_RAW"), movingcalib=utils.cameracalibration(camera="M20_RAW"))
# mandatory to avoid plotting figures in separate windows
%matplotlib inline 

# %% [markdown]
# # Loading images
# |Image             | Loading time   | Resolution          |
# |------------------|----------------|---------------------|
# | visible DJI DNG  | 7.6s           | 12Mpix (2992x3992)  |
# | nir sjcam RAW    | 27.2s          | 16Mpix (3448x4600)  |
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
nir_rep = multispectral_representation(
        nir_img,
        sigma_gaussian=align_config.sigma_mov, mode=align_config.mode
)
pr.show(representation_visualization(nir_rep)[0], figsize=(15, 3), suptitle="NIR")
pr.show(representation_visualization(vis_rep)[0], figsize=(15, 3), suptitle="VIS")
# representation_visualization_pairs(vis_rep, nir_rep, ref_orig=vis_img, mov_orig=nir_img, figsize=(10, 3))

# %% [markdown]
# ## Alignment process
# * The NIR image comes from a fisheye camera. It is affected by serious distorsion but this is not a problem as geometric calibration has been performed previously. Having a much wider field of view (FOV) is what actually allows an overlap with the visible DJI camera. 
# * When the drone is flying, you may think it is super steady as the visible images do not seem to be affected by any shake... but in reality, the drone is hihgly shaking. The visible camera is stabilized mechanically by a gimbal so you get the impression that the visible images are very steady.
#     * Roll of the drone leads to camera yaw, Pitch of the drone leads to camera pitch. Camera roll misalignment is usually zero because of the gimbal lock when the camera points towards the ground. 
#     * Hopefully, the fisheye has a much wider field of view than the DJI visible camera, therefore we're able to align the NIR image onto the visible image.
# * Let's manually align the NIR image onto the visible image using 3 degrees of freedom: virtual camera yaw, pitch and roll. You are virtually rotating the NIR camera and projecting into the visible camera (you get a much narrower field of view than the fisheye... equivalent to the DJI camera *this is all possible thanks to the initial camera calibrations*)
# 

# %%
from automatic_registration import user_assisted_manual_alignment
alignment_params = user_assisted_manual_alignment(vis_img.data, nir_img.data, calibrations)


