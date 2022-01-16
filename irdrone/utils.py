# -*- coding: utf-8 -*-
from matplotlib.colors import hsv_to_rgb
from scipy.interpolate import interp1d
from skimage import exposure
import glob
import itertools
import numpy as np
import os.path as osp
import json
import cv2
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
    calibfile = osp.join(osp.dirname(osp.abspath(__file__)), "..", "calibration", camera, "calibration.json")
    if not osp.exists(calibfile):
        print("NOT CALIBRATED %s"%calibfile)
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


def calculate_cdf(histogram):
    """
    This method calculates the cumulative distribution function
    :param array histogram: The values of the histogram
    :return: normalized_cdf: The normalized cumulative distribution function
    :rtype: array
    """
    # Get the cumulative sum of the elements
    cdf = histogram.cumsum()

    # Normalize the cdf
    normalized_cdf = cdf / float(cdf.max())

    return normalized_cdf


def calculate_lookup(src_cdf, ref_cdf):
    """
    This method creates the lookup table
    :param array src_cdf: The cdf for the source image
    :param array ref_cdf: The cdf for the reference image
    :return: lookup_table: The lookup table
    :rtype: array
    """
    lookup_table = np.zeros(256)
    lookup_val = 0
    for src_pixel_val in range(len(src_cdf)):
        lookup_val
        for ref_pixel_val in range(len(ref_cdf)):
            if ref_cdf[ref_pixel_val] >= src_cdf[src_pixel_val]:
                lookup_val = ref_pixel_val
                break
        lookup_table[src_pixel_val] = lookup_val
    return lookup_table


def match_histograms(src_image, ref_image):
    """
    This method matches the source image histogram to the
    reference signal
    :param image src_image: The original source image
    :param image  ref_image: The reference image
    :return: image_after_matching
    :rtype: image (array)
    """
    # Split the images into the different color channels
    # b means blue, g means green and r means red
    src_b, src_g, src_r = cv2.split(src_image)
    ref_b, ref_g, ref_r = cv2.split(ref_image)

    # Compute the b, g, and r histograms separately
    # The flatten() Numpy method returns a copy of the array c
    # collapsed into one dimension.
    src_hist_blue, bin_0 = np.histogram(src_b.flatten(), 256, [0,256])
    src_hist_green, bin_1 = np.histogram(src_g.flatten(), 256, [0,256])
    src_hist_red, bin_2 = np.histogram(src_r.flatten(), 256, [0,256])
    ref_hist_blue, bin_3 = np.histogram(ref_b.flatten(), 256, [0,256])
    ref_hist_green, bin_4 = np.histogram(ref_g.flatten(), 256, [0,256])
    ref_hist_red, bin_5 = np.histogram(ref_r.flatten(), 256, [0,256])

    # Compute the normalized cdf for the source and reference image
    src_cdf_blue = calculate_cdf(src_hist_blue)
    src_cdf_green = calculate_cdf(src_hist_green)
    src_cdf_red = calculate_cdf(src_hist_red)
    ref_cdf_blue = calculate_cdf(ref_hist_blue)
    ref_cdf_green = calculate_cdf(ref_hist_green)
    ref_cdf_red = calculate_cdf(ref_hist_red)

    # Make a separate lookup table for each color
    blue_lookup_table = calculate_lookup(src_cdf_blue, ref_cdf_blue)
    green_lookup_table = calculate_lookup(src_cdf_green, ref_cdf_green)
    red_lookup_table = calculate_lookup(src_cdf_red, ref_cdf_red)

    # Use the lookup function to transform the colors of the original
    # source image
    blue_after_transform = cv2.LUT(src_b, blue_lookup_table)
    green_after_transform = cv2.LUT(src_g, green_lookup_table)
    red_after_transform = cv2.LUT(src_r, red_lookup_table)

    # Put the image back together
    image_after_matching = cv2.merge([
        blue_after_transform, green_after_transform, red_after_transform])
    image_after_matching = cv2.convertScaleAbs(image_after_matching)

    return image_after_matching

def c2g(im):
    return cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)

def g2c(im):
    return cv2.cvtColor(im, cv2.COLOR_GRAY2RGB)

def get_polar_shading_map(img_shape=(3448, 4600, 3), calib=None):
    radius = int(np.sqrt((img_shape[0]/2)**2+(img_shape[1]/2) **2))
    x_lin = np.array(range(radius))
    vignetting_map = np.zeros(img_shape)
    for ch in range(3):
        parametric_profile = get_shading_profile(calib["RGB"[ch]], x_lin)
        radial_map = np.zeros((360, radius))
        radial_map = np.repeat(np.array([parametric_profile]), radial_map.shape[0], axis=0)
        vignetting_map[:, :, ch] = cv2.warpPolar(
            radial_map,
            (img_shape[1], img_shape[0]),
            center=(img_shape[1]/2, img_shape[0]/2),
            maxRadius=radius,
            flags=cv2.WARP_INVERSE_MAP
        )
    return vignetting_map


def get_shading_profile(verts, x_lin):
    x_vert, y_vert = zip(*verts)
    i_lin = np.arange(len(x_vert))
    interp_i = np.linspace(0, i_lin.max(), 100 * i_lin.max())
    xi = interp1d(i_lin, x_vert, kind='linear')(interp_i)
    yi = interp1d(i_lin, y_vert, kind='cubic')(interp_i)
    i_nonlin = interp1d(xi, interp_i)(x_lin)
    y_profile = interp1d(interp_i, yi)(i_nonlin)
    return y_profile


def contrast_stretching(img, percentiles=None, crop_black_circle = 450, p_val=(2, 98)):
    if percentiles is not None:
        p2, p98 = percentiles[0], percentiles[1]
    else:
        if crop_black_circle is not None:
            p2, p98 = np.percentile(img[:, crop_black_circle:-crop_black_circle, 1], p_val)
        else:
            p2, p98 = np.percentile(img, p_val)
    img_rescale = exposure.rescale_intensity(img, in_range=(p2, p98))
    return img_rescale, [p2, p98]
