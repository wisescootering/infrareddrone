# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
from pathlib import Path
import shutil
import os.path as osp
import matplotlib
import numpy as np
try:
    matplotlib.use('TkAgg')
except:
    pass
from matplotlib import pyplot as plt
from matplotlib.patches import Polygon
import sys
sys.path.append(osp.join(osp.dirname(__file__), ".."))
import utils.utils_IRdrone as IRd
from irdrone.utils import Style
import config as cf

columnNbr = 5
colorNames = list(matplotlib.colors.cnames.keys())


def create_odm_folder(dirMission, multispectral_modality="MS", extra_suggested_options=True, forced_camera_calibration=True, extra_options=[]):
    mapping_folder = "mapping_{}".format(multispectral_modality)
    path_database = Path(dirMission) / mapping_folder
    odm_camera_conf = Path(__file__).parent / ".." / "thirdparty" / "odm_data" / "irdrone_multispectral.json"
    camera_conf_dir = path_database / "camera"
    camera_conf_dir.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(odm_camera_conf, camera_conf_dir / "camera_IRdrone.json")
    image_database = path_database / "images"
    image_database.mkdir(exist_ok=True, parents=True)
    cmd = "docker run -ti --rm -v {}:/datasets opendronemap/odm".format(dirMission)
    cmd += " --project-path /datasets {}".format(mapping_folder)
    cmd += " --cameras /datasets/{}/camera/camera_IRdrone.json".format(mapping_folder)
    cmd += " --orthophoto-resolution 1. --ignore-gsd --fast-orthophoto --orthophoto-png"
    #cmd += " --orthophoto-kmz"
    cmd += " --force-gps --use-exif"
    cmd += " --build-overviews"
    cmd += " --skip-band-alignment"
    # see https://github.com/wisescootering/infrareddrone/issues/26
    if extra_suggested_options:
        cmd += " --smrf-threshold 0.3 --smrf-scalar 1.3 --smrf-slope 0.05 --smrf-window 24"
        # our goal is orthophoto, using parameters to increase the planarity attempt
        # illustrations in the odm missing guide -> pages 107/108/109
        cmd += " --texturing-skip-global-seam-leveling"
        # enable light adjustment
    if forced_camera_calibration:
        cmd += " --use-fixed-camera-params"
    for extra_option in extra_options:
        cmd += " " + extra_option
    with open(path_database / "odm_mapping.bat", "w") as fi:
        fi.write(cmd)
    return image_database


def odm_mapping_optim(dirMission, dirNameIRdrone, multispectral_modality="VIR", mappingList=None, extra_suggested_options=True, forced_camera_calibration=True):
    image_database = create_odm_folder(dirMission, multispectral_modality=multispectral_modality, extra_suggested_options=extra_suggested_options, forced_camera_calibration=forced_camera_calibration)
    newMappingList = []
    for i in range(len(mappingList)):
        if multispectral_modality == "VIS":
            new_name = mappingList[i].Vis[
                       mappingList[i].Vis.find("HYPERLAPSE_"):-4] + "_" + multispectral_modality + ".jpg"
        elif multispectral_modality == "NIR_local":
            new_name = mappingList[i].Vis[
                       mappingList[i].Vis.find("HYPERLAPSE_"):-4] + "_" + multispectral_modality + "_.jpg"
        else:
            new_name = "_" + multispectral_modality + "_" + mappingList[i].Vis[
                                                            mappingList[i].Vis.find("HYPERLAPSE_"):-4] + ".jpg"
        newMappingList.append(osp.join(Path(dirNameIRdrone), new_name))
    for img in newMappingList:
        shutil.copy(img, image_database)
    return image_database


def legacy_buildMappingList(listPts, overlap_x=0.33, overlap_y=0.80, dirSaveFig=None, mute=True):
    """
    focalPix            focal length camera VIS                pixels , m
    overlap_x = 0.30    percentage of overlap between two images  axe e_1
    overlap_y = 0.75    percentage of overlap between two images  axe e_2   [50% , 90%]
    lCapt_x             image size VIS  axe e_1                pixels
    lCapt_y             image size VIS  axe e_2  (axe drone)   pixels
    lPix                pixel size for camera VIS              m
    """
    print(Style.CYAN + 'INFO : ------ Creating the list of images for mapping  ' + Style.RESET)
    mappingList = []
    # TODO  prendre en compte la trajectoire exacte et pas seulement le mouvement  suivant e_2

    camera_make, camera_type, lCapt_x, lCapt_y, focal_factor, focalPix = IRd.lectureCameraIrdrone()
    lPix = cf.IRD_LPIX
    # ------------------------------------------------------------------------------------------
    d = 0     # reset odometre
    firstImg = False
    for pointImage in listPts:
        d_y = pointImage.altGround * (1 - overlap_y) * lCapt_y / focalPix
        if pointImage.bestSynchro == 1:
            if d == 0 and firstImg is False:   # The first point for mapping has been found.
                mappingList.append(pointImage)
                listPts[pointImage.num - 1].bestMapping = 1
                firstImg = True
                if not mute:
                    print("%s     sync %.2f s    alt. %.2f m  Yaw %.1f °  ech. 1/%i "
                      % (pointImage.Vis, pointImage.timeDeviation, pointImage.altGround, pointImage.yawDrone,
                         pointImage.altGround // (focalPix * lPix)))
            elif d >= d_y:  # The next point for mapping has been found.
                listPts[pointImage.num - 1].bestMapping = 1
                mappingList.append(pointImage)
                d = 0       # reset odometre
                if not mute:
                    print("%s     sync %.2f s    alt. %.2f m  Yaw %.1f °  ech. 1/%i "
                      % (pointImage.Vis, pointImage.timeDeviation, pointImage.altGround , pointImage.yawDrone,
                         pointImage.altGround // (focalPix * lPix)))

        if firstImg:              # Increment of the odometer.
            d = d + (pointImage.x_1 ** 2 + pointImage.x_2 ** 2) ** 0.5
    if 0 < len(mappingList) < 5:
        print(Style.YELLOW + '[warning]  The number of images selected for mapping is insufficient. It must be greater than 5.' + Style.RESET)
    elif len(mappingList) == 0:
        print(Style.RED + '[error]  No images selected for mapping.' + Style.RESET)
    visu_mapping(mappingList, listPts, focal_DJI=focalPix, lCapt_x=lCapt_x, lCapt_y=lCapt_y, dirSaveFig=dirSaveFig)

    return mappingList


def visu_mapping(mappingList, listPts, focal_DJI=cf.IRD_FOCAL_LENGTH_PIX, lCapt_x=cf.IRD_PIX_X, lCapt_y=cf.IRD_PIX_Y, dirSaveFig=None, name=None):
    figure = plt.figure(figsize=(6, 6))
    ax = figure.add_subplot(111)
    order = len(mappingList)
    # --------------  Plot trajectory of the drone in the geographical referential X: W->E   Y: S->N
    #  Use UTM coordinates
    listDrone_X, listDrone_Y , listBestMapping_X, listBestMapping_Y, listSynchro_X, listSynchro_Y = [], [], [], [], [], []
    offsetMappingArea = (lCapt_x/1.5) * IRd.avAltitude(listPts) / focal_DJI   # in meter
    for pt in listPts:
        if pt.bestMapping ==1:
            listBestMapping_X.append(pt.gpsUTM_X)
            listBestMapping_Y.append(pt.gpsUTM_Y)
        if pt.bestSynchro ==1:
            listSynchro_X.append(pt.gpsUTM_X)
            listSynchro_Y.append(pt.gpsUTM_Y)
        listDrone_X.append(pt.gpsUTM_X)
        listDrone_Y.append(pt.gpsUTM_Y)

    listMapping_X, listMapping_Y = [], []
    for pt in mappingList:
        listMapping_X.append(pt.gpsUTM_X)
        listMapping_Y.append(pt.gpsUTM_Y)

    # -------------   limits
    dx = np.max(listDrone_X) - np.min(listDrone_X) + 2 * offsetMappingArea
    xmiddle = np.min(listDrone_X) - offsetMappingArea + dx/2
    dy = (np.max(listDrone_Y) - np.min(listDrone_Y)) + 2 * offsetMappingArea
    ymiddle = np.min(listDrone_Y) - offsetMappingArea + dy / 2
    dl = np.max([dx,dy])
    ax.set_xlim(xmiddle - dl / 2, xmiddle + dl / 2)
    ax.set_ylim(ymiddle - dl / 2, ymiddle + dl / 2)
    ax.xaxis.set_visible(False)
    ax.yaxis.set_visible(False)

    # ----------- Plots shooting points-------------------------------------------------------------------------------

    ax.plot(listDrone_X, listDrone_Y, color='blue', linestyle='solid', linewidth=0.2, zorder=order,
            label='Drone trajectory.')
    # shoot point
    ax.plot(listDrone_X, listDrone_Y, linestyle='None',
            marker='o', markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.3,  markersize=2, zorder=order,
            label='Shooting point.')
    # best synchro images
    for i in range(len(listSynchro_X)):
        ax.plot(listSynchro_X[i], listSynchro_Y[i], linestyle='None',
            marker='o', markerfacecolor='orangered', markeredgecolor='darkred', markeredgewidth=0.5,markersize=2, zorder=order)
    ax.plot(listSynchro_X[0], listSynchro_Y[0], linestyle='None',
            marker='o', markerfacecolor='orangered', markeredgecolor='darkred', markeredgewidth=0.5, markersize=2,
            zorder=order,
            label='Shooting ~synchro.')
    # images for mapping
    for i in range(len(listBestMapping_X)):
        ax.plot(listBestMapping_X[i], listBestMapping_Y[i], linestyle='None',
            marker='o', markerfacecolor=colorNames[20 + i], markeredgecolor='black', markeredgewidth=0.5,markersize=8, zorder=order)
    if len(listBestMapping_X)>0:
        ax.plot(listBestMapping_X[0], listBestMapping_Y[0], linestyle='None',
            marker='o', markerfacecolor=colorNames[20], markeredgecolor='black', markeredgewidth=0.5, markersize=8, zorder=order, label='Best mapping ODM images')

    # selected images for processing  
    for i in range(len(listMapping_X)):
        ax.plot(listMapping_X[i], listMapping_Y[i], linestyle='None',
            marker='o', markerfacecolor=colorNames[20 + i], markeredgecolor='black', markeredgewidth=0.5,markersize=6, zorder=order)
    if len(listMapping_X)>0:
        ax.plot(listMapping_X[0], listMapping_Y[0], linestyle='None',
            marker='o', markerfacecolor=colorNames[20], markeredgecolor='black', markeredgewidth=0.5, markersize=6, zorder=order, label='Selected images ' + ("" if name is None else name))





    # -------------- Plot area scanned by images for mapping ----------------------------------------------------------

    for i in range(len(listMapping_X)):
        Yaw = np.deg2rad(360 + mappingList[i].yawDrone)
        zoomX = mappingList[i].altGround / focal_DJI
        zoomY = mappingList[i].altGround / focal_DJI
        coord_Img = rectImg(lCapt_x,lCapt_y)
        A = transAffine(Yaw, zoomX, zoomY, listMapping_X[i], listMapping_Y[i])
        ptGeo = coordRef2coordGeo(A, coord_Img)
        poly = Polygon(ptGeo, facecolor='whitesmoke', lw=0, hatch='', fill=True, zorder=order-1-i)
        ax.add_patch(poly)
        poly = Polygon(ptGeo, facecolor='None', edgecolor=colorNames[20 + i], lw=0.5, hatch='', fill=True, zorder=order)
        ax.add_patch(poly)

    # ------------ plot north arrow -----------------------------------------------------------------------------------
    northArrowVerts = northArrow(xmiddle, ymiddle, dl)
    arrow = Polygon(northArrowVerts, facecolor='black', edgecolor='black', lw=0.5, hatch='', fill=True, zorder=order+1)
    ax.add_patch(arrow)
    plt.text(xmiddle - 0.9 * dl / 2 - 4, ymiddle - 0.9 * dl / 2 + 16, "N")
    # -----------------------------------------------------------------------------------------------------------------
    ax.set_facecolor('silver')
    plt.legend(loc='best', fontsize=6)
    plt.gcf().subplots_adjust(left=0., bottom=0., right=1., top=1., wspace=0., hspace=0.)

    # -------------- Save Mapping scheme -------------------------------------------------------------------------------
    if dirSaveFig is None:
        pass
    else:
        filepath = osp.join(dirSaveFig, 'Mapping scheme')
        plt.savefig(filepath, dpi=300, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.CYAN + 'INFO : ------ Save Mapping scheme in %s' % filepath + Style.RESET)
        # plt.close()

    print(Style.YELLOW + 'WARNING : Look at the mapping scheme  >>>>' + Style.RESET)
    plt.show()
    plt.close()
    


def northArrow(x0,y0,d):
    coord = [[0, 8, 1], [2, 0, 1], [0, 2, 1], [-2, 0, 1], [0, 8, 1]]
    zoom=2
    Affine = np.array([[zoom, 0, x0-0.9*d/2], [0, zoom, y0-0.9*d/2], [0., 0., 1.]])
    listRectX = []
    listRectY = []
    for j in range(len(coord)):
        Coord_abs = np.dot(Affine, coord[j])
        listRectX.append(Coord_abs[0])
        listRectY.append(Coord_abs[1])
    verts = [(listRectX[k], listRectY[k]) for k in range(len(listRectX))]
    return verts


def rectImg(pix_X,pix_Y):
    coord_Img = [[-pix_X / 2, -pix_Y / 2, 1],
                 [+pix_X / 2, -pix_Y / 2, 1],
                 [+pix_X / 2, +pix_Y / 2, 1],
                 [-pix_X / 2, +pix_Y / 2, 1],
                 [-pix_X / 2, -pix_Y / 2, 1]]
    return coord_Img


def transAffine(Yaw, zoomX, zoomY, D_X, D_Y):
    A = np.array([[zoomX * np.cos(Yaw), zoomY * np.sin(Yaw), D_X],
                       [-zoomX * np.sin(Yaw), zoomY * np.cos(Yaw), D_Y],
                       [0., 0., 1.]
                       ])
    return A


def coordRef2coordGeo(A, coord_Img):
        listPtX, listPtY = [], []
        for j in range(len(coord_Img)):
            Coord_geo = np.dot(A, coord_Img[j])
            listPtX.append(Coord_geo[0])
            listPtY.append(Coord_geo[1])
        verts = [(listPtX[k], listPtY[k]) for k in range(len(listPtX))]
        return verts





