"""
image processing utilities
"""
import cv2
import matplotlib.pyplot as plt
import numpy as np


def loadimage(imgpth, numpyMode=True):
    """
    @todo: enrich with an image class
    :param imgpth: list of paths to jpg images
    :return: list of RGB arrays (cv2 bgr to rgb conversion is performed)
    """
    if not isinstance(imgpth, list): imgpth = [imgpth,]
    if numpyMode:
        return [cv2.cvtColor(cv2.imread(img), cv2.COLOR_BGR2RGB) for img in imgpth]
    else:
        return [cv2.imread(img) for img in imgpth]


def show(img, title=None, compare=True, block=True, suptitle=None, figsize=None):
    """
    Display matplolib image or a 1D or 2D comparison between images

    Side by side image mode
    -----------------------
    [(image A, "title A") , (image B, "title B"), (image C, None), image D]

    Grid image mode
    -----------------------
    [(image top left   , "title A") , (image top    right, "title B")]
    [(image middle left, "title C") , (image middle right, "title D")]
    [(image bottom left, "title E") , (image bottom right, "title F")]

    :param img: RGB image / list of RGB images / list of list in a 2D array fashion
    :param title: [optional] not necessary if the tuple (image, title) is used
    :param compare: disable only to display each image sequentially rather than in a side by side comparison fashion
    :param block: True by default, if False, shows plot only at the end
    :param suptitle: main title of the plot / window
    """
    if not isinstance(img, list) : img = [img,]
    if title is None and any(map(lambda x:isinstance(x, tuple), img)): # Handle empty (None) images or empty titles
        title = [None if (im is None or not ((isinstance(im, tuple) or isinstance(im, list)) and len(im)>=2)) else im[1] for im in img]
        img   = [im if (im is None or not ((isinstance(im, tuple) or isinstance(im, list)) and len(im)>=1)) else im[0] for im in img]
    if not isinstance(title, list): title = len(img)*[title]
    assert len(title)==len(img)
    if compare: plt.figure(num=suptitle, figsize=figsize)
    for idy, im in enumerate(img):
        if isinstance(im, list): #2D comparison array:
            xlen = max(map(lambda x:len(x), img))
            for idx, ima in enumerate(im):
                if (isinstance(ima, list) or isinstance(ima, tuple)) and len(ima) == 2: implt = ima[0]; titl = ima[1]
                else: implt = ima; titl = None
                if compare: plt.subplot(len(img), xlen, xlen*idy+1 + idx)
                else: plt.figure(num=("" if suptitle is None else suptitle) +(" %d %d "%(idy, idx) if titl is None else (" " + titl)))
                if implt is not None:  plt.imshow(implt)
                if titl is not None: plt.title(titl)
                plt.axis('off')
                if not compare: plt.show(block=block)
        else: #1 row comparison
            # assert len(im.shape)==3
            titl = title[idy]
            if compare: plt.subplot(1, len(img), idy+1)
            else: plt.figure(num=("" if suptitle is None else suptitle) +(" %d"%idy if titl is None else (" " + titl)))
            if im is not None: plt.imshow(im)
            if titl is not None: plt.title(titl)
            plt.axis('off')
            if not compare: plt.show(block=block)
    if suptitle is not None: plt.suptitle(suptitle)
    if compare: plt.show(block=block)


def applycolormatrix(img, cm=np.eye(3)):
    """
    apply 3x3 color matrix on 8 bits RGB images

    [ rr  rg  rb]   | R |       [ rr * R + rg * g * rb * B ]
    [ gr  gg  gb] * | G |    =  [ gr * R + gg * g * gb * B ]
    [ br  bg  bb]   | B |       [ br * R + bg * g * bb * B ]

    - 3x3 identity will perform no color correction.
    - color permutation (switch Red and Blue)
    [0 0 1]
    [0 1 0]
    [1 0 0]
    :param img: NxMx3 RGB image
    :param cm: 3x3 matrix or list of 3 elements for white balance (diagonal) coefficients or single float to amplify
    :return:
    """
    if isinstance(cm, float): cm = cm*np.eye(3)
    if isinstance(cm, list): cm = np.array(cm)
    ndim =  len(cm.shape)
    if ndim==1:
        assert cm.shape[0] == 3, "cannot initialize diagonal matrix"
        cm = np.diag(cm)
    imgcm = np.dot(img, 1.*cm.T).clip(0,255).astype(np.uint8)
    return imgcm