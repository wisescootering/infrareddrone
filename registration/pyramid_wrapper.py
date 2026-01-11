from skimage import transform
import numpy as np


# scikit-image version compatibility wrapper
# < 0.19	multichannel=True
# >= 0.19	channel_axis=-1
def pyramid_reduce(img, downscale):
    try:
        out = transform.pyramid_reduce(img, downscale=downscale, channel_axis=-1)
    except TypeError:
        out = transform.pyramid_reduce(img, downscale=downscale, multichannel=True)
    return out.astype(np.float32)


def pyramid_gaussian(img, downscale):
    try:
        out = transform.pyramid_gaussian(img, downscale=downscale, channel_axis=-1)
    except TypeError:
        out = transform.pyramid_gaussian(img, downscale=downscale, multichannel=True)

    # pyramid_gaussian returns a generator
    return [level.astype(np.float32) for level in out]
