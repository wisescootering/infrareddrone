import process as pr
import utils as ut
from joblib import Memory
import cv2
import itertools
import numpy as np
from tqdm import tqdm
import os.path as osp
opj = osp.join


def getcorners(img, checkerboardsize =(10,7), resize=None, show=False):
    """
    Corners detection on images
    @TODO: implement subpix corners refinement
    :param img: image numpy array or path to image
    :param checkerboardsize:  checkerboard size X, Y (count corners, not the number of squares)
    :param resize: speed up computation by processing smaller images
    :param show: computes an overlay on the image showing checkerboards, allow debugging
    :return: ret (boolean flag), corners, image with corners overlay, imsize
    """
    if isinstance(img, str): img = cv2.imread(img)
    grayorig = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    gray = grayorig if (resize is None or resize is False) else cv2.resize(grayorig, resize)
    ret, corners = cv2.findChessboardCorners(gray, checkerboardsize,None)
    img = None if not show else cv2.drawChessboardCorners(gray, checkerboardsize, corners,ret)
    return ret, corners, img, gray.shape[::-1]


def zhangcalibration(imgpoints, imsize, checkerboardsize=(10,7)):
    """
    Zhang camera calibration from checkerboard points
    :param imgpoints: List of list of 2D points
    :param imsize: (xsize,ysize) tuple size
    :param checkerboardsize: checkerboard size X, Y (count corners, not the number of squares)
    :return:
    """
    objp = np.zeros((checkerboardsize[1]*checkerboardsize[0],3), np.float32)
    objp[:,:2] = np.mgrid[0:checkerboardsize[0],0:checkerboardsize[1]].T.reshape(-1,2)
    objpoints = [] # 3d point in real world space
    for idx in range(len(imgpoints)):
        objpoints.append(objp)
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, imsize,None,None)
    return ret, mtx, dist, rvecs, tvecs


location = '_cachedir'
memory = Memory(location, verbose=0)
getcornerscached = memory.cache(getcorners)
zhangcalibcached = memory.cache(zhangcalibration)


def calibrate(
    imlist=[],
    resize=None,
    checkerboardsize=(10,7),
    show=True
):
    """
    Calibrate a camera based on a list of checkerboard images shot from various angles (30 images is a good number)
    Uses joblib cache mechanism to avoid multiple re-computations.
    Use a quick thumbnail corner detection to make sure detection works fine

    :param imlist: list of images
    :param resize: force resizing (usefull for testing)
    :param checkerboard size X, Y (count corners, not the number of squares)
    :param show: show debug detection images and distorted vs distortion free images
    :return: calibration dictionary {"mtx": 3x3 intrinsic matrix, "dist": distorsion polynoms, "size":imsize}
    """

    xshape = 8
    yshape = int(np.ceil(1.*len(imlist)/(1.*xshape)))
    outlist = np.empty((yshape,xshape)).tolist()
    cornerlist = []
    for id, (idy, idx) in enumerate(tqdm(
            itertools.product(range(yshape), range(xshape)),
            desc="corners detection",
            total=xshape*yshape)
    ):
        if id>=len(imlist): ret, out = False, None
        else:
            im = imlist[id]
            _ret, _corners, _out, _imsize = getcornerscached(im, resize=(800,600), show=True,  checkerboardsize=checkerboardsize) #START WITH A THUMBNAIL
            if _ret:
                ret, corners, out, imsize = getcornerscached(im, resize=resize, show=True,  checkerboardsize=checkerboardsize)
            else: ret, out= False,  None
            if ret: cornerlist.append(corners)
        outlist[idy][idx] = out if ret else None

    if show: #SHOW DETECTED IMAGES
        pr.show(outlist, figsize=(3*xshape, 3*yshape), suptitle="success : %d / %d"%(len(cornerlist), len(imlist)))
        pass

    # ZHANG CAMERA CALIBRATION FITTING
    ret, mtx, dist, rvecs, tvecs = zhangcalibcached(cornerlist, imsize, checkerboardsize=checkerboardsize)

    if show: #SHOW DISTORTED VS DISTORSION-FREE IMAGES
        undist = np.empty((2*yshape,xshape)).tolist()
        for id, (idy, idx) in enumerate(itertools.product(range(yshape), range(xshape))):
            img = outlist[idy][idx]
            if img is not None:
                newcameramtx = mtx
                dst = cv2.undistort(img, mtx, dist, None, newcameramtx)
            else:dst=None
            undist[2*idy][idx]   = (img, "original %d"%id)
            undist[2*idy+1][idx] = (dst, "undist %d"%id)
        pr.show(undist)
    print(ut.Style.GREEN + "success : %d / %d"%(len(cornerlist), len(imlist)))
    return {"mtx": mtx, "dist": dist, "size": imsize}



if __name__ == "__main__":
    #  cameraName="dji"          |   nbImage=48
    #  cameraName="SJ4000WIFI"   |   nbImage=53
    #  cameraName="M20"          |   nbImage=43
    #

    cameraName="SJ4000WIFI"
    nbImage = 53

    fullResolution=True
    if not fullResolution :
        # calibration avec des images en basse résolution pour tester si cela fonctionne
        calibrate(
            imlist=ut.imagepath(imgname="*.JPG",  dirname=opj(osp.dirname(__file__), "..", "calibration", cameraName))[-nbImage:],
            resize=(800,600)
        )
    elif fullResolution :
        finecalibration = calibrate(
            imlist=ut.imagepath(
                imgname="*.JPG",
                dirname=opj(osp.dirname(__file__), "..", "calibration", cameraName)
            )[-nbImage:],
            checkerboardsize=(10, 7),
            show=False
        )
        print(finecalibration)
        import json

        finecalibration["mtx"] = finecalibration["mtx"].tolist()
        finecalibration["dist"] = finecalibration["dist"].tolist()
        print(finecalibration)
        with open("calibration.json", 'w') as outfile:
            json.dump(finecalibration, outfile)
    else :
        pass
