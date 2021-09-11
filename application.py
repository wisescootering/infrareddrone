# -*- coding: utf-8 -*-
import irdrone.process as pr
import irdrone.utils as ut
import irdrone.imagepipe as ipipe
import irdrone.registration as rg
import numpy as np
import cv2
from joblib import Memory


def loadDatabase(dirname="flight0001", viscam = "DJI", ircam = "sjcam", imageRange=range(6), numpyMode=True):
    """
    Load database for visible & ir image and camera calibrations loaded in a flight folder
    This function template shall be matched to adapt to any pair of images naming.
    Here, pairing lies in the inner images naming using wpt001,0002 prefixes and a camera suffix
    TODO: support visible camera calibration

    :param dirname: images are stored in the flight folder (dji)
    :param viscam: visible camera name (sjcam)
    :param ircam:  ir camera name
    :param imageRange: used to select a specific list of paired images
    :param numpyMode:
    :return: viImages, calibviscam, irImages, calibircam
    (visible images, calibration of visible camera , IR images, calibration of infrared camera)
    """
    # VISIBLE IMAGES
    viImages = [
        pr.Image(
            ut.imagepath(
                imgname="*%02d*%s*JPG"%(idx, viscam),
                dirname=dirname
            )[0],
            name="visible %d"%idx
        )
        for idx in imageRange
    ]
    calibviscam = None  #ut.cameracalibration(camera=viscam)


    # INFRARED CAMERA IMAGES
    irImages = [
        pr.Image(
            ut.imagepath(
                imgname="*%02d_20*JPG"%(idx) if ircam == "M20" else "*%02d*%s*JPG"%(idx,ircam),
                dirname=dirname
            )[0],
            name="IR %d"%idx
        )
        for idx in imageRange
    ]
    calibircam = ut.cameracalibration(camera=ircam)
    return viImages, calibviscam, irImages, calibircam


def registration(vilist, irlist, ircalib=None, resize=(800,600), debug=False):
    """
    Computes distorsion free thumbnails in order to estimate a matching between feature points
    and therefore deduce an homography

    :param vilist: (visible image, visible image title)
    :param irlist: (infrared image, infrared image title)
    :param calib: infrared camera calibration
    :param resize: use thumbnails to perform image registration. This is not optional.
    :param debug: show debug
    :return:
    """
    alignedList = []
    visimg, irimg = vilist[0].copy(), irlist[0].copy()
    if ircalib is None: #BETTER AVOID THIS !
        cropx, cropy = 300, 300
        irimg = cv2.resize(
            irimg[cropy:-cropy, cropx:-cropx, :],
            (visimg.shape[1], visimg.shape[0])
        )
    else:
        mtx, dist = ircalib["mtx"], ircalib["dist"]
        mtxout = mtx.copy()
        irimgu = cv2.undistort(irimg, mtx, dist, np.zeros_like(visimg), mtxout)
        if debug:
            ipipe.ImagePipe(
                [
                    irimg,
                    irimgu
                ],
                sliders=[ipipe.ALPHA,],
                winname="DISTORSION CORRECTION ON IR IMAGE  (THUMBNAILS)"
            ).gui()

        irimg = irimgu.copy()
        if resize is not None:
            fx, fy = irimg.shape[1] / resize[0], irimg.shape[0] / resize[1]
            irimg  = cv2.resize(irimg , resize, fx=fx, fy=fy)
            visimg = cv2.resize(visimg, (int(visimg.shape[1] / fx), int(visimg.shape[0]  / fy)), fx=fx, fy=fy)
        if debug:
            ipipe.ImagePipe(
                [
                    irimg[:visimg.shape[0], :visimg.shape[1]],
                    visimg
                ],
                sliders=[ipipe.ALPHA,],
                winname="VISIBLE VS UNDISTORTED UNREGRISTERED IR IMAGE (THUMBNAILS)"
            ).gui()
        equ = ipipe.Equalizer("")
        irimg[..., 1] = irimg[..., 2] #REMOVE GREEN CHANNEL, REPLACE IT BY RED
        irimg = equ.apply(irimg.astype(np.float)).astype(np.uint8)
        irimg = unsharp_mask(irimg)
        visimg = equ.apply(visimg.astype(np.float)).astype(np.uint8)
        aligned, homog, debug_img = rg.estimateFeaturePoints(irimg, visimg, debug=debug)
        if debug:
            ipipe.ImagePipe(
                [
                    visimg,
                    aligned
                ],
                sliders=[ipipe.ALPHA,],
                winname="REGISTRATION RESULT ON VISIBLE VS IR THUMBNAILS"
            ).gui()

        visimgFullRes = vilist[0]

        rescale = np.diag([fx, fy, 1.])
        homog   = np.dot(rescale, np.dot(homog, np.linalg.inv(rescale)))

        alignedFullRes = None
        if debug:
            alignedFullRes = cv2.warpPerspective(irimgu, homog, (visimgFullRes.shape[1], visimgFullRes.shape[0]))
            ipipe.ImagePipe(
                [
                    visimgFullRes,
                    alignedFullRes
                ],
                sliders=[ipipe.ALPHA,],
                winname="FULL RESOLUTION IR vs VISIBLE REGISTRATION"
            ).gui()
    visimgSize = (visimgFullRes.shape[1], visimgFullRes.shape[0])
    return homog, visimgSize, [alignedFullRes, "registered IR image"]



location = '_cachedir'
memory = Memory(location, verbose=0)
registrationCached = memory.cache(registration)

def unsharp_mask(image, kernel_size=(5, 5), sigma=1.0, amount=1.0, threshold=0):
    """Return a sharpened version of the image, using an unsharp mask."""
    blurred = cv2.GaussianBlur(image, kernel_size, sigma)
    sharpened = float(amount + 1) * image - float(amount) * blurred
    sharpened = np.maximum(sharpened, np.zeros(sharpened.shape))
    sharpened = np.minimum(sharpened, 255 * np.ones(sharpened.shape))
    sharpened = sharpened.round().astype(np.uint8)
    if threshold > 0:
        low_contrast_mask = np.absolute(image - blurred) < threshold
        np.copyto(sharpened, image, where=low_contrast_mask)
    return sharpened

def warp(im: pr.Image, cal, homog, outsize=None):
    if not isinstance(im, pr.Image):
        im = pr.Image(im, "warped")
    mtx, dist = cal["mtx"], cal["dist"]
    if outsize is None:
        outsize = (im.data.shape[1], im.data.shape[0])
    map1x, map1y = cv2.initUndistortRectifyMap(
        mtx,
        dist,
        np.eye(3,3),
        np.dot(homog, mtx),
        outsize, cv2.CV_32FC1
    )

    out = cv2.remap(
        im if not isinstance(im, pr.Image) else im.data, map1x, map1y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0)
    )
    return out

def applicationDjiDroneSJCamIR(imageRange=[4,6], outimage="fused", debug=False, ircamera="sjcam", dirname="flight0001"):
    """
    Visible camera: DJI Mavic Air 2 drone
    IR camera: sjcam400
    Load database (images and camera calibration)
    @TODO: Fusion viewer can be built here
    @TODO: Batch saving
    @TODO: Copy Exif data on output images
    :param imageRange: to select images , you have 4 & 6 available in the GIT repository
    :return:
    """
    viImages, _viscal, irImages, ircal = loadDatabase(
        dirname= dirname,
        imageRange=imageRange,
        ircam=ircamera
    )
    for idx in range(len(viImages)):
        # ONLY PERFORM IMAGE REGISTRATION WHEN NOT CACHED
        homog, visimgSize, _aligned = registrationCached(
            viImages[idx],
            irImages[idx],
            ircalib = ircal,
            debug=debug
        )
        aligned = pr.Image(
            warp(irImages[idx], ircal,homog, visimgSize),
            name="REGISTERED IMAGE"
        )
        aligned.save("%03d_registered.jpg"%imageRange[idx])
        BnWIR = ipipe.BnW("MonochromeIR", inputs=[2], outputs=[2], slidersName=[])
        brIR = ipipe.Brightness("BrightnessIR", inputs=[2], outputs=[2])
        gamIR = ipipe.Gamma("GammaIR", inputs=[2], outputs=[2])

        forcedParams = {
            "MonochromeIR": [],
            "BrightnessIR": [-0.440000],
            "GammaIR": [0.180000],
            "Mix IR and Visible": [0.820000, 1.186000, 1.222000],
            "ALPHA": [0.870000],
        }
        ip= ipipe.ImagePipe(
            [
                viImages[idx][0],
                aligned[0]
            ],
            sliders=[BnWIR, brIR, gamIR, #ipipe.TRANSLATION,
                     mix, ipipe.ALPHA],
            backendcv=False,
            winname = ("%d -- "%idx  + "VISIBLE:  %s"%viImages[idx]  + "---   FUSED WITH   --- IR : %s"%irImages[idx]).replace(u"°", " "),
            **forcedParams
        )
        ip.save(name= outimage+"%04d.jpg"%idx)
        ip.gui()

class MixIR(ipipe.ProcessBlock):
    def apply(self, vis, ir, coeffr, coeffg, coeffb,  **kwargs):
        out = vis.copy()
        out[:,:,0] = coeffr*ir[:,:,0]
        out[:,:,1] = coeffg*vis[:,:,0]
        out[:,:,2] = coeffb*vis[:,:,1]
        return out

mix = MixIR("Mix IR and Visible", inputs=[0,2], slidersName=["r", "g", "b"], vrange=(0.7, 1.3, 1.))

if __name__ == "__main__":
    applicationDjiDroneSJCamIR(
        imageRange=[4, 6],
        debug=False,
        ircamera="sjcam",
        dirname="flight0001",
    )
    applicationDjiDroneSJCamIR(
        imageRange=[2, 3, 5],
        debug=False,
        ircamera="M20",
        dirname="flight0002",
    )
