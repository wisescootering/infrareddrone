import config
import process as pr
import utils as ut
from joblib import Memory
import cv2
import itertools
import numpy as np
from tqdm import tqdm
import os.path as osp
from os import mkdir
import logging
opj = osp.join


def getcorners(img_in, checkerboardsize =(10,7), resize=None, show=False):
    """
    Corners detection on images with subpix corners refinement
    :param img: image numpy array or path to image
    :param checkerboardsize:  checkerboard size X, Y (count corners, not the number of squares)
    :param resize: speed up computation by processing smaller images
    :param show: computes an overlay on the image showing checkerboards, allow debugging
    :return: ret (boolean flag), corners, image with corners overlay, imsize
    """
    if isinstance(img_in, str): img = pr.Image(img_in).data
    elif isinstance(img_in, pr.Image): img = img_in.data
    else: img = img_in
    grayorig = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    gray = grayorig if (resize is None or resize is False) else cv2.resize(grayorig, resize)
    ret, corners = cv2.findChessboardCorners(gray, checkerboardsize, None)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.1)
    if ret:
        corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)
    img = None if not show else cv2.drawChessboardCorners(img, checkerboardsize, corners, ret)
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
    return ret, mtx, dist, rvecs, tvecs, objpoints


location = '_cachedir'
memory = Memory(location, verbose=0)
getcornerscached = memory.cache(getcorners)
zhangcalibcached = memory.cache(zhangcalibration)


def reprojection_error(objpoints, imgpoints, rvecs, tvecs, mtx, dist, imsize=None):
    import matplotlib.pyplot as plt
    mean_error = 0
    fig = plt.figure()
    ax = fig.add_subplot(111)
    logging.warning("{} checkerboards detected in total!".format(len(objpoints)))
    for idx in range(len(objpoints)):
        imgpoints_reproj, _ = cv2.projectPoints(objpoints[idx], rvecs[idx], tvecs[idx], mtx, dist)
        error = cv2.norm(imgpoints[idx], imgpoints_reproj, cv2.NORM_L2)/len(imgpoints_reproj)
        ax.plot(imgpoints[idx][:, 0, 0], imgpoints[idx][:, 0, 1], "b+", alpha=0.5)
        ax.plot(imgpoints_reproj[:, 0, 0], imgpoints_reproj[:, 0, 1], "r+")
        mean_error += error
    plt.title("Total reprojection error {:.4f} pixels - image size {}".format(mean_error/len(objpoints), imsize))
    if imsize is not None:
        ax.set_xlim(0., imsize[0])
        ax.set_ylim(0., imsize[1])
    ax.set_aspect('equal', adjustable='box')
    plt.gca().invert_yaxis()
    plt.show()


def get_corners_from_crop(im, _corners, resize_thumb, resize=None, debug=False, debug_img=None):
    im_load = pr.Image(im).lineardata
    imsize_full = (im_load.shape[1], im_load.shape[0])
    bbox_min = np.min(_corners, axis=(0,1))
    bbox_max = np.max(_corners, axis=(0,1))
    x_start= int(bbox_min[0]*im_load.shape[1]/resize_thumb[0])
    x_end = int(bbox_max[0]*im_load.shape[1]/resize_thumb[0])
    y_start = int(bbox_min[1]*im_load.shape[0]/resize_thumb[1])
    y_end = int(bbox_max[1]*im_load.shape[0]/resize_thumb[1])
    extension_x, extension_y = int((x_end - x_start) * 0.2), int((y_end - y_start)*0.2)
    x_start= max(x_start-extension_x, 0)
    x_end = min(x_end+extension_x, im_load.shape[1])
    y_start = max(y_start-extension_y, 0)
    y_end = min(y_end+extension_y, im_load.shape[0])
    if False:
        im_crop = np.ones_like(im_load)*0
        im_crop[y_start:y_end, x_start:x_end, :] = im_load[y_start:y_end, x_start:x_end, :]
    else:
        im_crop = im_load[y_start:y_end, x_start:x_end, :]
    im_crop = (im_crop*255).astype(np.uint8)
    ret, corners, out, _imsize = getcornerscached(im_crop, resize=resize, checkerboardsize=checkerboardsize,
                                                 show=debug)
    if ret:
        corners[:, :, 0] = corners[:, :, 0]+float(x_start)
        corners[:, :, 1] = corners[:, :, 1]+float(y_start)
    if debug and debug_img is not None:
        pr.Image(im_crop).save(osp.join(debug_img+"detection_{}.jpg".format("ok" if ret else "failed")))
        pr.Image(out).save(osp.join(debug_img+"_corners_detection_{}.jpg".format(0, "ok" if ret else "failed")))
    return ret, corners, out, imsize_full


get_corners_from_crop_cached = memory.cache(get_corners_from_crop)


def calibrate(
        imlist=[],
        resize=None,
        checkerboardsize=(10,7),
        show=True,
        debug_folder=None
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
    if debug_folder is not None and not osp.isdir(debug_folder):
        mkdir(debug_folder)
    yshape = int(np.ceil(1.*len(imlist)/(1.*xshape)))
    outlist = np.empty((yshape, xshape)).tolist()
    cornerlist = []
    imsize_full = None
    for id, (idy, idx) in enumerate(tqdm(
            itertools.product(range(yshape), range(xshape)),
            desc="corners detection",
            total=xshape*yshape)
    ):
        if id>=len(imlist):
            ret, out = False, None
        else:
            im = imlist[id]
            resize_thumb = (800, 600)
            _ret, _corners, _out, _imsize = getcornerscached(im, resize=resize_thumb, checkerboardsize=checkerboardsize,
                                                             show=True) # START WITH A THUMBNAIL
            if _ret:
                # move on to full resolution detection on the crop computed from thumbnail
                debug_img = None
                if debug_folder is not None:
                    debug_img = osp.join(debug_folder, "{:04d}_".format(id))
                ret, corners, out, imsize = get_corners_from_crop_cached(im, _corners, resize_thumb, debug=True, debug_img=debug_img)
                if imsize is not None and imsize_full is None:
                    imsize_full = imsize
            else:
                logging.warning("Could not detect checkerboard in small resolution ")
                ret, out = False,  None
            if ret:
                cornerlist.append(corners)
            if _ret and not ret:
                    logging.warning("Could not detect checkerboard in full resolution {}".format(id))
        outlist[idy][idx] = out if ret else None

    if show: #SHOW DETECTED IMAGES
        pr.show(outlist, figsize=(3*xshape, 3*yshape), suptitle="success : %d / %d"%(len(cornerlist), len(imlist)))
        pass

    # ZHANG CAMERA CALIBRATION FITTING
    ret, mtx, dist, rvecs, tvecs, objpoints = zhangcalibcached(cornerlist, imsize, checkerboardsize=checkerboardsize)
    reprojection_error(objpoints, cornerlist, rvecs, tvecs, mtx, dist, imsize=imsize_full)


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


def get_config(cam):
    #  cameraName="dji"          |   nbImage=48
    #  cameraName="SJ4000WIFI"   |   nbImage=53
    #  cameraName="M20"          |   nbImage=43
    #  cameraName="dji"          |   nbImage=? checkerboardsize=(7, 5)
    confs = {
        "SJ4000WIFI": dict(checkerboardsize=(10, 7), nbImage=53, suffix="*.JPG"),
        "M20": dict(checkerboardsize=(10, 7), nbImage=43, suffix="*.JPG"),
        "DJI_RAW": dict(checkerboardsize=(15, 8), nbImage=None, suffix="*.DNG"),
        "M20_RAW": dict(checkerboardsize=(10, 7), nbImage=30, suffix="*.RAW"),
        "DJI": dict(checkerboardsize=(7, 5), nbImage=29, suffix="*.JPG")
    }
    return confs[cam]


if __name__ == "__main__":
    cameraName= "DJI_RAW"
    conf = get_config(cameraName)
    suffix = conf["suffix"]
    nbImage = conf["nbImage"]
    checkerboardsize = conf["checkerboardsize"]
    fullResolution = True
    calibration_folder = opj(osp.dirname(__file__), "..", "calibration", cameraName)
    # calibration_folder = r"D:\Calib-20211010\Calib"
    # img_list = img_list[137:137+30] + img_list[-30:] + img_list[:30] # for DJI 200+ images calibration !!

    img_list = ut.imagepath(imgname=suffix,  dirname=calibration_folder)
    logging.info("{} available calibration images".format(len(img_list)))
    if nbImage is not None:
        img_list = img_list[:nbImage]

    if not fullResolution :
        # calibration avec des images en basse résolution pour tester si cela fonctionne
        calibrate(
            imlist=img_list,
            checkerboardsize=checkerboardsize,
            resize=(800, 600)
        )
    elif fullResolution:
        finecalibration = calibrate(
            imlist=img_list,
            checkerboardsize=checkerboardsize,
            show=False,
            debug_folder=osp.join(calibration_folder, "_detection_new")
        )
        import json
        finecalibration["camera"] = cameraName
        finecalibration["mtx"] = finecalibration["mtx"].tolist()
        finecalibration["dist"] = finecalibration["dist"].tolist()
        print(finecalibration)
        with open(opj(calibration_folder, "calibration.json"), 'w') as outfile:
            json.dump(finecalibration, outfile)
    else :
        pass
