# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
from pathlib import Path
import shutil
import os.path as osp
import matplotlib
import numpy as np
import utils.utils_IRdrone as IRd
from irdrone.utils import Style
matplotlib.use('TkAgg')
from matplotlib import pyplot as plt
from matplotlib.patches import Polygon
columnNbr = 5
colorNames = list(matplotlib.colors.cnames.keys())


def odm_mapping_optim(dirMission, dirNameIRdrone, multispectral_modality="VIR", mappingList=None):
    mapping_folder = "mapping_{}".format(multispectral_modality)
    path_database = Path(dirMission) / mapping_folder
    odm_camera_conf = Path(__file__).parent / ".." / "odm_data" / "dji_fc3170.json"
    camera_conf_dir = path_database / "camera"
    camera_conf_dir.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(odm_camera_conf, camera_conf_dir / "camera_IRdrone.json")
    image_database = path_database / "images"
    image_database.mkdir(exist_ok=True, parents=True)
    cmd = "docker run -ti --rm -v {}:/datasets opendronemap/odm".format(dirMission)
    cmd += " --project-path /datasets {}".format(mapping_folder)
    cmd += " --cameras /datasets/{}/camera/camera_IRdrone.json".format(mapping_folder)
    cmd += " --orthophoto-resolution 1. --ignore-gsd --fast-orthophoto --orthophoto-png"
    cmd += " --force-gps --use-exif"

    with open(path_database / "odm_mapping.bat", "w") as fi:
        fi.write(cmd)

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


def buildMappingList(listPts, planVol, dirSaveFig=None, mute=True):
    print(Style.CYAN + '------ Creating the list of images for mapping  ' + Style.GREEN)
    mappingList = []
    DTmin = planVol['drone']['timelapse'] / 4
    # TODO  recuperer les dimensions du capteur et la focale du fichier camera
    lPix = 1.6 * 10 ** -6  # pixel size for camera VIS           en m
    lCapt_x = 4000         # image size VIS  axe e_1             en pixels
    lCapt_y = 3000         # image size VIS  axe e_2             en pixels
    f = 2898.5             # focal length camera VIS             en pixels
    f_m = f * lPix         # focal length camera VIS             en m
    overlap_x = 0.30       # percentage of overlap between two images  axe e_1
    overlap_y = 0.68       # percentage of overlap between two images  axe e_2   50% à 75%

    # ------------------------------------------------------------------------------------------
    d = 0
    firstImg = False
    for pointImage in listPts:
        d_y = pointImage.altGround * (1 - overlap_y) * lCapt_y / f
        if -DTmin <= pointImage.timeDeviation <= DTmin:
            if d == 0 and firstImg is False:  # premier point de la série
                mappingList.append(pointImage)
                firstImg = True
                if not mute:
                    print("%s     sync %.2f s    alt. %.2f m  Yaw %.1f °  ech. 1/%i "
                      % (pointImage.Vis, pointImage.timeDeviation, pointImage.altGround, pointImage.yawDrone,
                         pointImage.altGround // f_m))
            elif d >= d_y:  # trouvé le point suivant de la série du mapping
                mappingList.append(pointImage)
                d = 0       # raz odometre
                if not mute:
                    print("%s     sync %.2f s    alt. %.2f m  Yaw %.1f °  ech. 1/%i "
                      % (pointImage.Vis, pointImage.timeDeviation, pointImage.altGround , pointImage.yawDrone,
                         pointImage.altGround // f_m))

        if firstImg:              # incrémentation de l'odomètre
            d = d + (pointImage.x_1 ** 2 + pointImage.x_2 ** 2) ** 0.5

    visu_mapping(mappingList, listPts, dirSaveFig=dirSaveFig)

    return mappingList


def visu_mapping(mappingList, listPts, dirSaveFig=None):

    focal_DJI = 2830  # in pixels
    figure = plt.figure(figsize=(6, 6))
    ax = figure.add_subplot(111)
    order = len(mappingList)
    # --------------  Plot trajectory of the drone in the geographical referential X: W->E   Y: S->N
    #  Use UTM coordinates
    listDrone_X, listDrone_Y , listMapping_X, listMapping_Y = [], [], [], []
    offsetMappingArea = (3892/1.5) * IRd.avAltitude(listPts) / focal_DJI   # in meter

    for pt in mappingList:
        listMapping_X.append(pt.gpsUTM_X)
        listMapping_Y.append(pt.gpsUTM_Y)
    for pt in listPts:
        listDrone_X.append(pt.gpsUTM_X)
        listDrone_Y.append(pt.gpsUTM_Y)
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
    ax.plot(listDrone_X, listDrone_Y, linestyle='None',
            marker='o', markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.3,  markersize=2, zorder=order,
            label='Shooting point.')
    for i in range(len(listMapping_X)):
        ax.plot(listMapping_X[i], listMapping_Y[i], linestyle='None',
            marker='o', markerfacecolor=colorNames[20 + i], markeredgecolor='black', markeredgewidth=0.5,markersize=6, zorder=order)
    ax.plot(listMapping_X[0], listMapping_Y[0], linestyle='None',
            marker='o', markerfacecolor=colorNames[20], markeredgecolor='black', markeredgewidth=0.5, markersize=6, zorder=order, label='Image for mapping.')

    # -------------- Plot area scanned by images for mapping ----------------------------------------------------------
    pix_X = 3892
    pix_Y = 2892

    for i in range(len(listMapping_X)):
        Yaw = np.deg2rad(360 + mappingList[i].yawDrone)
        zoomX = mappingList[i].altGround / focal_DJI
        zoomY = mappingList[i].altGround / focal_DJI
        coord_Img = rectImg(pix_X,pix_Y)
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
    ax.set_facecolor('mediumseagreen')
    plt.legend(loc='best', fontsize=6)
    plt.gcf().subplots_adjust(left=0., bottom=0., right=1., top=1., wspace=0., hspace=0.)

    # -------------- Save Mapping scheme -------------------------------------------------------------------------------
    filepath = osp.join(dirSaveFig, 'Mapping scheme')
    if dirSaveFig is None:
        pass
    else:
        plt.savefig(filepath, dpi=300, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.CYAN + '----- Save Mapping scheme in %s' % filepath + Style.RESET)

    print(Style.YELLOW + 'Look at the mapping scheme  >>>>' + Style.RESET)
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

