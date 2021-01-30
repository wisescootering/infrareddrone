# -*- coding: utf-8 -*-
"""
image processing utilities
"""
import cv2
import matplotlib.pyplot as plt
import numpy as np
import os.path as osp
import PIL.Image
import PIL.ExifTags
import datetime
from irdrone.utils import Style, conversionGPSdms2dd

class Image:
    """
    Fast image class
    image[0] = numpy array , only loaded when accessing , otherwise the path is simply kept
    image[1] = image name
    """
    def __init__(self, dat, name=None):
        if isinstance(dat, str):
            self.path = dat
            self.name = osp.basename(dat)
            self._data = None
        else:
            self.path = None
            self._data = dat
            self.name = name
        if name is not None: self.name = name
        self.loadMetata()

    def loadMetata(self):
        if self.path is not None:
            pimg = PIL.Image.open(self.path)
            exifTag = {
                PIL.ExifTags.TAGS[k]: v
                for k, v in pimg._getexif().items()
                if k in PIL.ExifTags.TAGS
            }
            try:
                dateTimeOriginal= exifTag.get('DateTimeOriginal')
                imgYear   = int (dateTimeOriginal[0:4])
                imgMonth  = int (dateTimeOriginal[5:7])
                imgDay    = int (dateTimeOriginal[8:11])
                imgHour   = int (dateTimeOriginal[11:13])
                imgMin    = int (dateTimeOriginal[14:16])
                imgSecond = int (dateTimeOriginal[17:19])
                self.date = datetime.datetime(imgYear, imgMonth, imgDay, imgHour, imgMin, imgSecond)
            except:
                print(Style.YELLOW + "NO DATE FOUND IN %s"%self.path + Style.RESET)
                self.date = None

            try:
                dateTime = exifTag.get('DateTime')
                self.dateFile = dateTime
            except:
                self.dateFile = None

            try:
                gpsHemisphere= exifTag.get('GPSInfo').__getitem__(1)
                if gpsHemisphere == 'S' :
                    signeLat=-1.
                else:
                    signeLat = 1.
                gpsLat = [chiffre / (1. * precision) for chiffre, precision in exifTag.get('GPSInfo').__getitem__(2)]
                gpsLatDD = conversionGPSdms2dd(gpsLat)
                gpsLatitude=[gpsHemisphere,signeLat*gpsLat[0] ,gpsLat[1],gpsLat[2], gpsLatDD]

                gpsMeridien = exifTag.get('GPSInfo').__getitem__(3)
                if gpsMeridien == 'W' :
                    signeLong=-1.
                else:
                    signeLong = 1.
                gpsLong = [chiffre / (1. * precision) for chiffre, precision in exifTag.get('GPSInfo').__getitem__(4)]
                gpsLongDD = conversionGPSdms2dd(gpsLong)
                gpsLongitude = [gpsMeridien, signeLong* gpsLong[0], gpsLong[1], gpsLong[2], gpsLongDD]
                self.gps = {"latitude": gpsLatitude, "longitude": gpsLongitude}
            except:
                print(Style.YELLOW + "NO GPS DATA FOUND IN %s"%self.path + Style.RESET)
                self.gps = None

    def get_data(self):
        if self._data is None:
            # print("LOAD DATA %s"%self.path)
            assert osp.exists(self.path), "%s not an image"%self.path
            self._data = cv2.cvtColor(cv2.imread(self.path), cv2.COLOR_BGR2RGB)
            # print("data loaded", self._data.shape)
        else:
            pass
            # print("Reaccessing image %s"%self.path)
        return self._data

    def set_data(self, value):
        self._data = value
    data = property(get_data, set_data)

    def __getitem__(self, item):
        if item == 0:
            # print("ACESS IMAGE CONTENT!")
            return self.data
        if item == 1:
            return  self.name

    def __repr__(self):
        if self._data is None:
            return "Image %s not loaded"%self.path
        else:
            return "%s - Image %s loaded"%(self._data.shape, self.path)

    def clear(self):
        self._data = None

    def isempty(self):
        return self._data is None

    def __repr__(self):
        prettyName = ""
        if self.date is not None:
            prettyName+= "Shot on %s ."%(self.date)
        if self.gps is not None:
            latitude  = self.gps["latitude"]
            longitude = self.gps["longitude"]
            prettyName+= "%s %.5f ° | %s %.5f °" % (
                latitude[0], latitude[4], longitude[0], longitude[4]
            )
        return prettyName

    def show(self):
        show(self.data, self.name + "\n" + self.__repr__())

    def channelshow(self, channels = ["Red", "Green","Blue"]):
        """
               Visualize eache colors channel and its own histogram
               |    Red   | Green |   Blue  |
               |   histR  | histG |  histB  |

               Available color scales available in pyplot
                 autumn, bone, cool, copper, flag, gray, hot, hsv, jet, pink, prism, spring, summer, winter.
        :param channels: Naming of channels for custom naming vizualization
        :return:
        """
        fig = plt.figure(figsize=(18, 9))
        listColor = ['red', 'green', 'blue']
        histl = [cv2.calcHist([self.data], [ch], None, [256], [0, 256]) for ch, _cname in enumerate(channels)]
        for ch, cname in enumerate(channels):
            plt.subplot(2, 3, 1 + ch)
            plt.imshow(self.data[:,:,ch], cmap=plt.cm.gray)
            plt.colorbar()
            plt.subplot(2, 3, 4 + ch)
            plt.plot(histl[ch], color=listColor[ch%len(listColor)])
            plt.title(cname)
        plt.suptitle(self.name + "\n" + self.__repr__())
        plt.show()

    def resize(self, coefResize=None):
        if coefResize is not None and coefResize != 1.:
            self.data = cv2.resize(
                self.data,
                None,
                fx = coefResize,
                fy = coefResize,
                interpolation = cv2.INTER_CUBIC
            )

    def hsv(self):
        self.data = cv2.cvtColor(self.data, cv2.COLOR_RGB2HSV)


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