# -*- coding: utf-8 -*-
from matplotlib.colors import hsv_to_rgb
import glob
import itertools
import numpy as np
import os.path as osp
import json
opj = osp.join


class Style:
    """
    Use for nice console line colors
    """
    BLACK = '\033[30m '
    RED = '\033[31m '
    GREEN = '\033[32m '
    YELLOW = '\033[33m '
    BLUE = '\033[34m '
    MAGENTA = '\033[35m '
    CYAN = '\033[36m '
    WHITE = '\033[37m '
    UNDERLINE = '\033[4m '
    RESET = '\033[0m '


def testimage(xsize=300, ysize=100, sat=1.):
    """
    Return a color RGB images with a color wheel
    :param xsize: image width (horizontal dimension used for hue)
    :param ysize: image height (vertical dimension used for luminance)
    :param sat: color saturation
    :return: RGB numpy array [ysize, xsize, 3]
    """
    V, H = np.mgrid[0:1:ysize*1j, 0:1:xsize*1j]
    S = sat*np.ones_like(V)
    HSV = np.dstack((H,S,V))
    RGB = (255.*hsv_to_rgb(HSV)).clip(0,255).astype(np.uint8)
    return RGB


def imagepath(imgname="2020_1225_091929_004FullSpectrum.JPG", dirname=opj(osp.dirname(__file__), "..", "samples")):
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
            assert osp.exists(imgpth)
            imgpthList.append(imgpth)
    imgpthList = list(map(lambda x:osp.abspath(x), imgpthList))
    return imgpthList


def cameracalibration(camera="sjcam", checkerboardsize=(10,7), imgname="*.JPG"):
    """
    Load camera calibration from pre-stored models given the camera name
    Re-compute if not avaiable
    :param camera: camera name, indicates the folder where you store calibration images in "calibration" folder
    :param checkerboardsize: size (X, Y) - remember to count corners, not the number of rectangles.
    :param imgname: matchable image expression "*.jpg", "*.JPG", "*.png" to be more flexible
    :return: dictionary
    """
    calibfile = osp.join("calibration", camera, "calibration.json")
    if not osp.exists(calibfile):
        import cameracalibration
        dic = cameracalibration.calibrate(
            imlist= imagepath(imgname=imgname,  dirname=osp.join("calibration",camera))[-60:],
            resize=None,
            checkerboardsize=checkerboardsize
        )
        dic["mtx"] = dic["mtx"].tolist()
        dic["dist"] = dic["dist"].tolist()[0]
        with open(calibfile, "w") as fi:
            print(Style.CYAN + "SAVING %s CALIBRATION RESULTS %s"%(camera,calibfile))
            json.dump(dic, fi)
    if osp.exists(calibfile):
        with open(calibfile, "r") as fi:
            dic = json.load(fi)
            dic["mtx"] = np.array(dic["mtx"])
            dic["dist"] = np.array(dic["dist"])
            print(Style.GREEN + "CALIBRATION %s SUCCESSFULLY LOADED"%camera)
            print(Style.RESET)
    else:
        raise  NameError("Calibration %s cannot be loaded %s"%(camera, calibfile))
    return dic

def conversionGPSdms2dd(coord):
    """
        Conversion from dd° mm' ss.sssss"   en dd.dddddddd
    """
    if coord[0]=="W" or coord[0]=="S":
        signe=-1.
    else:
        signe=1.
    coordDD = signe*(coord[0] + (coord[1] / 60) + (coord[2] / 3600))
    return coordDD