from matplotlib.colors import hsv_to_rgb
import glob
import itertools
import numpy as np
import os
opj = os.path.join


def testimage(xsize=300, ysize=100, sat=1.):
    V, H = np.mgrid[0:1:ysize*1j, 0:1:xsize*1j]
    S = sat*np.ones_like(V)
    HSV = np.dstack((H,S,V))
    RGB = (255.*hsv_to_rgb(HSV)).clip(0,255).astype(np.uint8)
    return RGB

def imagepath(imgname="2020_1225_091929_004FullSpectrum.JPG", dirname=opj(os.path.dirname(__file__), "..", "samples")):
    """
    Get a default sample image, many images and support * character

    :param imgname: jpeg file name or list of images
    :param dirname: directory path  or list of directories
    :return: list of images
    """
    if not isinstance(imgname, list): imgname = [imgname,]
    if not isinstance(dirname, list): dirname = [dirname,]
    imgpthList = []
    for di, img in itertools.product(dirname, imgname):
        imgpth = opj(di, img)
        if "*" in imgpth:
            imgpthList += glob.glob(imgpth)
        else:
            assert os.path.exists(imgpth)
            imgpthList.append(imgpth)
    imgpthList = list(map(lambda x:os.path.abspath(x), imgpthList))
    return imgpthList