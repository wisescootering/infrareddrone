# -*- coding: utf-8 -*-
"""
image processing utilities
"""
from genericpath import isfile
import shutil
import cv2
import sys
import matplotlib.pyplot as plt
import numpy as np
import os
import os.path as osp
import PIL.Image
import PIL.ExifTags
import piexif
import exifread
import datetime
import logging
from os import mkdir
sys.path.append(osp.join(osp.dirname(__file__), ".."))
from irdrone.utils import Style, conversionGPSdms2dd, get_polar_shading_map, contrast_stretching
import subprocess
from pathlib import Path
import json

if os.name == 'nt':
    RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
    assert osp.exists(RAWTHERAPEEPATH), "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
    EXIFTOOLPATH = osp.join(osp.dirname(__file__), "..", "exiftool", "exiftool.exe")
    assert osp.exists(EXIFTOOLPATH), "Requires exif tool at {} from https://exiftool.org/".format(EXIFTOOLPATH)

else:
    RAWTHERAPEEPATH = "rawtherapee-cli"
    EXIFTOOLPATH = "exiftool"

shading_correction_DJI = None
shading_correction_M20 = None
SJCAM_M20_PROFILE_CONTROL_POINTS = {
    "R" :[(-2013.186139572626, 1.0285597058816314), (196.1657528923779, 1.0138095996814964), (672.4623430384404, 0.9758875264857452), (1240.4111479507396, 1.0150339670490343), (1686.281583682889, 1.068122341155305), (2056.884896435969, 1.204810909017386), (2396.436069270902, 1.2303145442390813), (3045.416916737508, 0.7854837645467905), (3357.444414697938, 0.3475093200941026)],
    "G": [(-1818.1593058299723, 0.9593926491976511), (184.6507089333645, 1.016621860616801), (672.4623430384404, 0.9758875264857452), (1240.4111479507396, 1.0150339670490343), (1672.6256359791887, 1.0733830394880173), (2022.0053655849624, 1.2150426799356917), (2363.4446467906046, 1.245596720032249), (2994.7102946010355, 0.7414550584390546), (3256.7450918053655, 0.32619787712675397)],
    "B":[(-1872.1109909763832, 0.9448023256039491), (174.521941381101, 1.016191567620653), (650.7576814104391, 0.9787972027547605), (1241.1325657443285, 1.0204409272645043), (1668.6554117791238, 1.0786695019553694), (2008.6199153783855, 1.2239852542049876), (2347.1015157298157, 1.2613796190708801), (2895.4546895993954, 0.7369495461155825), (3357.444414697938, 0.3475093200941026)]
}


def load_tif(in_file):
    flags = cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR
    flags |= cv2.IMREAD_IGNORE_ORIENTATION
    return cv2.cvtColor(cv2.imread(in_file, flags=flags), cv2.COLOR_BGR2RGB)/(2.**16-1)

def cached_tif(path):
    return path[:-4]+"_RawTherapee.tif"

def load_dng(path, template="DJI_neutral.pp3"):
    out_file = cached_tif(path)
    cmd = [
        RAWTHERAPEEPATH,
        "-t", "-o", out_file,
        "-p", osp.join(osp.dirname(__file__), template),
        "-c", path
    ]
    if not osp.isfile(out_file):
        subprocess.call(cmd)
    else:
        logging.info("DNG already processed by RAW THERAPEE {}".format(path))
    return load_tif(out_file), out_file


def get_gimbal_info(pth: Path):
    exif_file = pth.with_suffix(".exif")
    if exif_file.exists():
        with open(exif_file, "r") as fi:
            dic = json.load(fi)
    else:
        cmd = [EXIFTOOLPATH, pth]
        p = subprocess.run(cmd,  capture_output=True, text=True)
        output_text = p.stdout
        lines = output_text.split("\n")
        selection = [li for li in lines if "Degree" in li]
        dic = dict()
        for li in selection:
            key = li.split(" Degree")[0]
            val = float(li.split(": ")[1])
            dic[key] = val
        with open(exif_file, "w") as fi:
            json.dump(dic, fi)
    return dic


class Image:
    """
    Fast image class
    image[0] = numpy array , only loaded when accessing , otherwise the path is simply kept
    image[1] = image name
    """
    def __init__(self, dat, name=None, shading_correction=True):
        self.proxy = None
        if isinstance(dat, str):
            if not osp.isfile(dat):
                raise NameError("File %s does not exist"%dat)
            self.path = dat
            self.name = osp.basename(dat)
            self._data = None
            self._lineardata = None
            self.shading_correction = shading_correction
            self.conv_dir = osp.join(osp.dirname(self.path), "_conversion_sjcam")
            # This piece of code is a dirty, the proxies are RGB temporary conversions of raw files
            # The list self.proxy is used to later clear (methode clean_proxy)
            dng_file = osp.join(self.conv_dir, osp.basename(self.path).replace(".RAW", ".dng"))
            proxypth = cached_tif(self.path)
            proxypth_from_dng = cached_tif(dng_file)
            self.proxy = [dng_file, proxypth, proxypth_from_dng]
        else:
            self.path = None
            self._data = dat
            self._lineardata = None
            self.name = name
        if name is not None: self.name = name
        self.date = None
        self.gps = None
        self.camera = None
        self.altitude = None
        self.altitude_ref = None
        self.flight_info = None
        self.loadMetata()

    def save(self, path, gps=None, exif=None):
        if gps is not None:
            self.gps = gps
        if self._data is None:
            self.data
        if path.lower().endswith("jpg"):
            if self.gps is not None:
                gps_exif = dict()
                gps_exif[0] = (2, 3, 0, 0)
                gps_exif[1] = self.gps["latitude"][0]
                gps_exif[2] = ((int(self.gps["latitude"][1]), 1), \
                               (int(self.gps["latitude"][2]), 1), \
                               (int(self.gps["latitude"][3]*10000), 10000))

                gps_exif[3] = self.gps["longitude"][0]
                gps_exif[4] = ((int(self.gps["longitude"][1]), 1), \
                               (int(self.gps["longitude"][2]), 1), \
                               (int(self.gps["longitude"][3]*10000), 10000))
                gps_exif[5] = 0
                gps_exif[6] = ((int(self.gps["altitude"]*1000), 1000))
                exif_dict = dict(GPS=gps_exif)
                if exif is not None:
                    exif_dict = {**exif_dict, **exif}
                # print(exif_dict)
                exif_bytes = piexif.dump(exif_dict)
                PIL.Image.fromarray(self._data).save(path, "jpeg", exif=exif_bytes)
            else:
                cv2.imwrite(path, cv2.cvtColor(self._data, cv2.COLOR_RGB2BGR))
        elif path.lower().endswith("tif"):
            cv2.imwrite(path, cv2.cvtColor(
                ((2**16-1)*(self._data.clip(0, 1))).astype(np.uint16),
                cv2.COLOR_RGB2BGR)
            )
        return

    def loadMetata(self):
        if self.path is not None:
            prefix = ""
            try:
                if self.path.lower().endswith("dng") or self.path.lower().endswith("raw"):
                    with open(self.path, 'rb') as f:
                        exifTag = exifread.process_file(f)
                    if self.path.lower().endswith("dng"):
                        fligh_info = get_gimbal_info(Path(self.path))
                        self.flight_info = fligh_info
                    prefix = "EXIF "
                else:
                    pimg = PIL.Image.open(self.path)
                    exifTag = {
                        PIL.ExifTags.TAGS[k]: v
                        for k, v in pimg._getexif().items()
                        if k in PIL.ExifTags.TAGS
                    }
            except:
                print(Style.YELLOW + "CANNOT ACCESS EXIF %s"%self.path + Style.RESET)
                return
            try:
                maker = str(exifTag['Image Make'])
                model = str(exifTag['Image Model'])
                serial_number = str(exifTag[prefix+'BodySerialNumber'])
                timelapse = 0
                deltatime = 0
                self.camera = {
                    "maker": maker,
                    "model": model,
                    "serial number": serial_number,
                    "timelapse": timelapse,
                    "deltatime": deltatime
                }
            except:
                print(Style.YELLOW + "NO CAMERA IN %s"%self.path + Style.RESET)
                self.camera = None
            try:
                if self.path.endswith(".RAW"):

                    year, month_date, hours , _ = osp.basename(self.path).split("_")
                    converted_date = datetime.datetime(year=int(year), month=int(month_date[:2]), day=int(month_date[2:]),
                                               hour=int(hours[:2]), minute=int(hours[2:4]),  second=int(hours[4:]))
                    self.date = converted_date
                    logging.info("DATE FROM FILE NAME .RAW  {}".format(self.date))
                else:
                    dateTimeOriginal = str(exifTag[prefix+'DateTimeOriginal'])
                    imgYear = int (dateTimeOriginal[0:4])
                    imgMonth = int (dateTimeOriginal[5:7])
                    imgDay = int (dateTimeOriginal[8:11])
                    imgHour = int (dateTimeOriginal[11:13])
                    imgMin = int (dateTimeOriginal[14:16])
                    imgSecond = int (dateTimeOriginal[17:19])
                    self.date = datetime.datetime(imgYear, imgMonth, imgDay, imgHour, imgMin, imgSecond)
            except:
                print(Style.YELLOW + "NO DATE FOUND IN %s"%self.path + Style.RESET)
                self.date = None

            try:
                dateTime = str(exifTag.get(prefix+'DateTime'))
                self.dateFile = dateTime
            except:
                self.dateFile = None

            try:
                if self.path.lower().endswith("dng"):
                    gpsHemisphere = str(exifTag["GPS GPSLatitudeRef"])
                    gpsLat_str = str(exifTag['GPS GPSLatitude'])[1:-1].split(", ")
                    gpsLat = [
                        int(gpsLat_str[0]),
                        int(gpsLat_str[1]),
                        int(gpsLat_str[2].split("/")[0])/ int(gpsLat_str[2].split("/")[1])
                    ]
                    gpsMeridien = str(exifTag["GPS GPSLongitudeRef"])
                    gpsLong_str = str(exifTag['GPS GPSLongitude'])[1:-1].split(", ")
                    gpsLong = [
                        int(gpsLong_str[0]),
                        int(gpsLong_str[1]),
                        int(gpsLong_str[2].split("/")[0])/ int(gpsLong_str[2].split("/")[1])
                    ]
                    _altitude = str(exifTag["GPS GPSAltitude"]).split("/")
                    if len(_altitude)==1:
                        self.altitude = int(_altitude[0])
                    else:
                        self.altitude = int(_altitude[0])/int(_altitude[1])
                    _altitude_ref = str(exifTag["GPS GPSAltitudeRef"])
                    if _altitude_ref != "0":
                        _altitude_ref = _altitude_ref.split("/")
                        self.altitude_ref = int(_altitude_ref[0])/int(_altitude_ref[1])
                else:
                    gpsHemisphere= exifTag.get(prefix+'GPSInfo').__getitem__(1)
                    gpsLat = [chiffre / (1. * precision) for chiffre, precision in exifTag.get('GPSInfo').__getitem__(2)]
                    gpsMeridien = exifTag.get(prefix+'GPSInfo').__getitem__(3)
                    gpsLong = [chiffre / (1. * precision) for chiffre, precision in exifTag.get('GPSInfo').__getitem__(4)]
                signeLat=-1.  if gpsHemisphere == 'S' else 1.
                signeLong = -1. if gpsMeridien == 'W' else 1.
                gpsLatDD = conversionGPSdms2dd(gpsLat)
                gpsLatitude=[gpsHemisphere, signeLat*gpsLat[0] ,gpsLat[1],gpsLat[2], gpsLatDD]
                gpsLongDD = conversionGPSdms2dd(gpsLong)
                gpsLongitude = [gpsMeridien, signeLong* gpsLong[0], gpsLong[1], gpsLong[2], gpsLongDD]
                self.latitude = gpsLatitude
                self.longitude = gpsLongitude
                self.gps = {"latitude": gpsLatitude, "longitude": gpsLongitude, "altitude": self.altitude}
            except:
                logging.info(Style.YELLOW + "NO GPS DATA FOUND IN %s"%self.path + Style.RESET)
                self.gps = None

    def get_lineardata(self):
        self.get_data()
        return self._lineardata
    lineardata = property(get_lineardata)

    def get_data(self):
        gamma = 2.2 #1./2.2
        if self._data is None:
            assert osp.exists(self.path), "%s not an image"%self.path
# ---------------------------------------------------------------------------------------------------- DJI Mavic Air RAW
            if str.lower(osp.basename(self.path)).endswith("dng"):
                rawimg, proxypth = load_dng(self.path, template="DJI_neutral.pp3") # COLOR MATRIX IS APPLIED, LINEAR
                self.proxy = [proxypth]
                # lens shading correction for DJI
                if self.shading_correction:
                    global shading_correction_DJI
                    if shading_correction_DJI is None:
                        shading_correction_DJI = np.load(
                            osp.abspath(osp.join(osp.dirname(__file__), "..", "calibration", "DJI_RAW",
                                                 "shading_calibration.npy"))
                        )
                        shading_correction_DJI = cv2.resize(shading_correction_DJI, (rawimg.shape[1], rawimg.shape[0]))
                    rawimg = (shading_correction_DJI*rawimg).clip(0., 1.)
                # self._data = ((rawimg**(gamma)).clip(0., 1.)*255).astype(np.uint8)
                self._data = (contrast_stretching(rawimg.clip(0., 1.))[0]*255).astype(np.uint8)
                self._lineardata = rawimg
# -------------------------------------------------------------------------------------------------------- SJCAM M20 RAW
            elif str.lower(osp.basename(self.path)).endswith("raw"):
                if os.name == "nt":
                    sjcam_converter = osp.join(osp.dirname(osp.abspath(__file__)), "..", "sjcam_raw2dng", "sjcam_raw2dng.exe")
                    sjconverter_link = "https://github.com/yanburman/sjcam_raw2dng/releases/tag/v1.2.0"
                    assert osp.isfile(sjcam_converter), "{} does not exist - please download from {}".format(
                        sjcam_converter,
                        sjconverter_link
                    )
                else:
                    sjcam_converter = osp.join(osp.dirname(osp.abspath(__file__)), "..", "sjcam_raw2dng_linux", "sjcam_raw2dng")
                conv_dir = self.conv_dir
                if not osp.isdir(conv_dir):
                    mkdir(conv_dir)
                dng_file = osp.join(conv_dir, osp.basename(self.path).replace(".RAW", ".dng"))
                if not osp.isfile(dng_file):
                    subprocess.call([sjcam_converter, "-o", conv_dir, self.path])
                rawimg, proxypth = load_dng(dng_file, template="SJCAM.pp3")
                self.proxy = [dng_file, proxypth]
                bp_sjcam = 0.255
                rawimg = rawimg - bp_sjcam
                if self.shading_correction:
                    global shading_correction_M20
                    if shading_correction_M20 is None:
                        shading_correction_M20 = get_polar_shading_map(
                            img_shape=rawimg.shape,
                            calib=SJCAM_M20_PROFILE_CONTROL_POINTS
                        )
                        # print("LOADING SHADING CALIB")
                    rawimg = (rawimg * shading_correction_M20)
                # self._data = ((rawimg.clip(0., 1.)**(gamma)).clip(0., 1.)*255).astype(np.uint8)
                self._data = (contrast_stretching(rawimg.clip(0., 1.))[0]*255).astype(np.uint8)
                self._lineardata = rawimg.clip(0., 1.)
            elif str.lower(osp.basename(self.path)).endswith("tif") or str.lower(osp.basename(self.path)).endswith("tiff"):
                linear_data = load_tif(self.path)
                self._lineardata = linear_data
                self._data = (contrast_stretching(linear_data.clip(0., 1.))[0]*255).astype(np.uint8)
                # self._data = ((linear_data**(gamma)).clip(0., 1.)*255).astype(np.uint8)
            else:
                self._data = cv2.cvtColor(cv2.imread(self.path), cv2.COLOR_BGR2RGB)  #LOAD AS A RGB CLASSIC ARRAY
                self._lineardata = self._data  # simply fake linear data...
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

    def clean_proxy(self):
        if self.proxy is None:
            return
        for img_pth in self.proxy:
            if os.path.isfile(img_pth):
                logging.info(f"CLEANING {img_pth}")
                os.remove(img_pth)


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


def show(img, title=None, compare=True, block=True, suptitle=None, figsize=None, save=None):
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

    :param img: RGB image / list of RGB images / lisst of list in a 2D array fashion
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
                if implt is not None:
                    if isinstance(implt, Image):
                        plt.imshow(implt.data)
                        if titl is None: titl=implt.name
                    else: plt.imshow(implt)
                if titl is not None: plt.title(titl)
                plt.axis('off')
                if not compare: plt.show(block=block)
        else: #1 row comparison
            # assert len(im.shape)==3
            titl = title[idy]
            if compare: plt.subplot(1, len(img), idy+1)
            else: plt.figure(num=("" if suptitle is None else suptitle) +(" %d"%idy if titl is None else (" " + titl)))
            if im is not None:
                if isinstance(im, Image):
                    plt.imshow(im.data)
                    if titl is None: titl=im.name
                else: plt.imshow(im)
            if titl is not None: plt.title(titl)
            plt.axis('off')
            if not compare: plt.show(block=block)
    if suptitle is not None: plt.suptitle(suptitle)
    if save is not None: plt.savefig(save); plt.close();return
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
