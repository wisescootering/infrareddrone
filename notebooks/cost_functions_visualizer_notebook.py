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
# mandatory to avoid plotting figures in separate windows
%matplotlib inline 

# %%
path = osp.join(osp.dirname(__file__), "registration", "..", "samples")
nir_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg"))
vis_img = pr.Image(osp.join(path, "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg"))
debug_dir = "_debug_cost_factorize"
if not osp.isdir(debug_dir):
    os.mkdir(debug_dir)
debug_dir = None
align_conf = AlignmentConfig(
    mode=[LAPLACIAN_ENERGIES, GRAY_SCALE, COLORED][0],
    dist_mode=[SSD, NTG][1],
    downscale=16,
    sigma_ref=5.,
    sigma_mov=3.,  # reducing blur for NIR image
    num_patches=6,
    search_size=5
)
run_multispectral_cost(vis_img, nir_img, align_config=align_conf, debug_dir=debug_dir)



