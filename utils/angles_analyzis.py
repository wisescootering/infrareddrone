# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
version 1.3 2022-09-27 19:37:00
@authors: balthazar/alain
"""

import sys
import os
import os.path as osp
import argparse
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
sys.path.append(osp.join(osp.dirname(__file__), ".."))
import utils.utils_IRdrone as IRd
from irdrone.utils import Style



def analyzis_motion_camera(dirMission, shootingPts, planVol, showAnglPlot=False, showDisperPlot=False):
    timeLine, yawIR2VI, pitchIR2VI, rollIR2VI = [], [], [], []
    timeLinePostProcess, yawCoarse, pitchCoarse, rollCoarse = [], [], [], []

    # List of motion models of IRdrone images.  Ext .py
    result_dir = Path(dirMission) / "ImgIRdrone"
    ImgPostProcess = sorted(result_dir.glob("*.npy"))

    # -------------------------------------------------------
    k = 0
    for shootPt in shootingPts:
        timeLine.append(shootPt.timeLine)
        yawIR2VI.append(shootPt.yawIR2VI)
        pitchIR2VI.append(shootPt.pitchIR2VI)
        rollIR2VI.append(shootPt.rollIR2VI)
        if shootPt.alignment == 1:
            timeLinePostProcess.append(shootPt.timeLine)
            try:
                assert ImgPostProcess[k].is_file()
                #  yaw & pitch .  Coarse  registration angle of near infrared images.
                mouvement = np.load(ImgPostProcess[k], allow_pickle=True).item()
                yawCoarse.append(mouvement["yaw"])
                pitchCoarse.append(mouvement["pitch"])
                rollCoarse.append(mouvement["roll"])
                shootingPts[shootPt.num - 1].yawCoarseAlign = mouvement["yaw"]
                shootingPts[shootPt.num - 1].pitchCoarseAlign = mouvement["pitch"]
                shootingPts[shootPt.num - 1].rollCoarseAlign = mouvement["roll"]
                k += 1
            except Exception as exc:
                print(Style.RED + "erreur lors de la lectures des angles process \nError = {}"%exc + Style.RESET)

    # -----------------------------------------------------------------------------------
    plotAnglesAlignment(timeLine, yawIR2VI, pitchIR2VI, rollIR2VI,
                        timeLinePostProcess, yawCoarse, pitchCoarse, rollCoarse, dirMission=dirMission, showPlot=showAnglPlot)
    plotDisperPitchYaw(yawIR2VI, pitchIR2VI, rollIR2VI,
                       yawCoarse, pitchCoarse, rollCoarse, planVol, dirMission=dirMission, showPlot=showDisperPlot)
    return


def plotDisperPitchYaw(yawIR2VI, pitchIR2VI, rollIR2VI, yawCoarse, pitchCoarse, rollCoarse, planVol, dirMission=None, showPlot=False):
    # --------   Courbe de dispersion des angles   pitch(yaw)
    _, (ax1, ax2) = plt.subplots(nrows=1, ncols=2)
    myTitleX = '. Offset = ' + str(np.round(planVol["offset_angles"][0], 2)) + '°'
    myTitleY = '. Offset =' + str(np.round(planVol["offset_angles"][1], 2)) + '°'
    missionTitle = dirMission.split("/")[-1]
    min, max = disperLimit(yawIR2VI, pitchIR2VI, yawCoarse, pitchCoarse)
    disperPitchYaw_plot(ax1, pitchIR2VI, yawIR2VI, min, max, missionTitle, myTitleX, myTitleY, 'Theoretical alignment', color='darkorange')
    disperPitchYaw_plot(ax2, pitchCoarse, yawCoarse, min, max, missionTitle, "", "", 'Coarse alignment', color='darkgoldenrod')
    # ---------- save plot in dirMission/Flight Analytics/Angles analysis ----------------
    savePlot(dirMission, 'Angles analysis dispersion')
    if showPlot:
        plt.show()
    else:
        print(Style.YELLOW + 'Look at the Dispersion Angles alignment analysis  >>>>' + Style.RESET)
    plt.close()
    return


def disperLimit(yawIR2VI, pitchIR2VI, yawCoarse, pitchCoarse):
    minTheori = np.min([np.min(np.array(yawIR2VI)), np.min(np.array(yawCoarse))])
    maxTheori = np.min([np.max(np.array(yawIR2VI)), np.max(np.array(yawCoarse))])
    minCoarse = np.min([np.min(np.array(pitchIR2VI)), np.min(np.array(pitchCoarse))])
    maxCoarse = np.min([np.max(np.array(pitchIR2VI)), np.max(np.array(pitchCoarse))])
    min = np.min([minTheori, minCoarse])
    max = np.max([maxTheori, maxCoarse])
    return min, max


def savePlot(dirMission, fileName):
    pathFolder = Path(dirMission) / 'Flight Analytics'
    filepath = pathFolder / fileName
    if pathFolder is None:
        pass
    else:
        plt.savefig(filepath, dpi=600, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.CYAN + '------ Save Angles analysis in %s' % filepath + Style.RESET)
    return


def disperPitchYaw_plot(ax, fx, fy, mini, maxi, missionTitle, myTitleX, myTitleY, spectralType, color='yellow'):
    avg = (np.average(fx, axis=0), np.average(fy, axis=0))
    std = (np.std(fx, axis=0), np.std(fy, axis=0))
    ax.plot(fx, fy, marker="o", markersize=6, alpha=0.4, mec=color, mfc=color, linestyle='')
    ax.set_xlim(mini - 2., maxi + 2.)
    ax.set_ylim(mini - 2., maxi + 2.)
    ax.plot(0., 0., "k+")
    ax.plot(avg[0], avg[1], "r+")
    myTitle = str(
        missionTitle + "\n" + spectralType + "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"
        .format(avg[0], std[0], avg[1], std[1]))
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel("YAW   %s" % myTitleX, fontsize=8)
    ax.set_ylabel("PITCH  %s" % myTitleY, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)
    return


def plotAnglesAlignment(timeLine, yawIR2VI, pitchIR2VI, rollIR2VI,
                        timeLinePostProcess, yawCoarse, pitchCoarse, rollCoarse,
                        dirMission=None, showPlot=False):
    if dirMission is None:
        return

    missionTitle = dirMission.split("/")[-1]
    _, (ax1, ax2) = plt.subplots(nrows=2, ncols=1)
    plotAnglesAlignment_2curves(ax1, timeLine, yawIR2VI, timeLinePostProcess, yawCoarse,
                                label1="Yaw theoretical.              average = {:.2f}°".format(np.average(yawIR2VI, axis=0)), color1='green',marksize1=1,
                                label2="Yaw coarse alignment.   average = {:.2f}°".format(np.average(yawCoarse, axis=0)), color2='yellowgreen', marksize2=8, Title=missionTitle)
    plotAnglesAlignment_2curves(ax2, timeLine, pitchIR2VI, timeLinePostProcess, pitchCoarse,
                                label1="Yaw theoretical.              average = {:.2f}°".format(np.average(yawIR2VI, axis=0)), color1='purple', marksize1=1,
                                label2="Yaw coarse alignment.   average = {:.2f}°".format(np.average(yawCoarse, axis=0)), color2='blueviolet', marksize2=8)

    # ---------- save plot in dirMission/Flight Analytics/Angles analysis ----------------
    savePlot(dirMission, 'Angles analysis')
    if showPlot:
        plt.show()
    else:
        print(Style.YELLOW + 'Look at the Angles alignment analysis  >>>>' + Style.RESET)
    plt.close()
    return

def plotAnglesAlignment_2curves(ax, x1, y1, x2, y2, label1="theoretical. ", label2="coarse alignment", color1='green', color2='yellowgreen',marksize1=1, marksize2=8, Title=" "):
    ax.plot(x1, y1, color=color1, linestyle='-', linewidth=1, marker='o', markersize=marksize1, alpha=1, label=label1)
    ax.plot(x2, y2, color=color2, linestyle='--', linewidth=1, marker='o', markersize=marksize2, alpha=0.5, label=label2)
    ax.set_title(Title, fontsize=8)
    ax.set_xlabel('Time line  [s]', fontsize=8)
    ax.set_ylabel('Angle [°]', fontsize=8)
    ax.grid()
    ax.legend()
    ax.set_xlim(0, np.max(x1))
    return



def interactifChoice():
    """Command line interface or manual file browser interface"""
    parser = argparse.ArgumentParser(description='Process flight summary - visualize angles')
    parser.add_argument('--summary', type=str, help='path to the flight summary data')
    parser.add_argument('--cache', help='cache', action="store_true")

    args = parser.parse_args()
    dirMission = args.summary
    if dirMission is None or not os.path.isfile(dirMission):
        print(Style.CYAN + "File browser")
        dirMission = os.path.dirname(IRd.loadFileGUI(mute=True))
        print(Style.CYAN + dirMission + Style.RESET)

        print(Style.YELLOW + 'Do you want to use cached data?' + Style.RESET)
        utilise_cache = IRd.answerYesNo('Yes (1) |  No (0):')
    else:
        dirMission = os.path.dirname(dirMission)
        utilise_cache = args.cache
    return dirMission, utilise_cache


def flightProfil_plot(d_list, elev_Drone, elev_Ground, title="IRdrone", dirSaveFig=None, mute=True):
    # PLOT ELEVATION PROFILE
    base_fill = min(elev_Ground) - 10
    up_fill = max(elev_Drone) + 10
    plt.figure(figsize=(10, 4))
    plt.plot(d_list, elev_Drone, '.r', label='Drone: ', linewidth=1, linestyle='dashed', markersize=0)
    plt.plot(d_list, elev_Ground, color='saddlebrown', label='Ground ')
    plt.fill_between(d_list, elev_Ground, base_fill, color='darkgoldenrod', alpha=0.1)
    plt.fill_between(d_list,  up_fill, elev_Ground, color='lightcyan', alpha=0.3)
    plt.text(d_list[0], elev_Drone[0], "Start")
    plt.text(d_list[-1], elev_Drone[-1], "End")
    plt.xlabel("Distance (m)")
    plt.ylabel("Altitude (m)")
    plt.grid()
    plt.legend(fontsize='small')
    plt.title(title, fontsize=8)
    filepath = osp.join(dirSaveFig, 'Flight profil IRdrone')
    if dirSaveFig is None:
        pass
    else:
        plt.savefig(filepath, dpi=600, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.CYAN + '------ Save flight profil in %s' % filepath + Style.RESET)
    if not mute:
        print(Style.YELLOW + 'Look your Drone Flight profil >>>>' + Style.RESET)
        plt.show()
    plt.close()
