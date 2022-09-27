# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
version 1.3 2022-09-27 19:37:00
@authors: balthazar/alain
"""

import sys
import os.path as osp

sys.path.append(osp.join(osp.dirname(__file__), ".."))
import utils.utils_IRdrone as IRd
import utils.utils_IRdrone_Plot as IRdplt
from version import __version__ as versionIRdrone
import numpy as np
from datetime import timedelta
from irdrone.utils import Style
import os
import os.path as osp
import cv2
import irdrone.utils as ut
import argparse
from pathlib import Path


def plotYawPitchRollDroneAndCameraDJI(dir_mission,
                                      utilise_cache=False,
                                      offsetYaw=0,
                                      offsetPitch=0,
                                      showAngleCoarseProcess=False,
                                      showTheoreticalAngle=False,
                                      showGap=False,
                                      showSpectralAnalysis=False,
                                      showDispersion=False,
                                      showRefined=False):
    # Estimation du défaut d'alignement de l'axe de visée caméra SJCam M20  après le 7 septembre 2021
    result_dir = osp.join(dir_mission, "ImgIRdrone")
    dirSaveFig = osp.join(dir_mission, "Flight Analytics")
    desync = timedelta(seconds=-0)
    txt = str('Delay  ' + str(desync) + "s")
    print(Style.YELLOW + txt + Style.RESET)
    missionTitle = dir_mission.split("/")[-1]
    motion_cache = osp.join(result_dir, "motion_summary_vs_drone_dates.npy")

    # Chargement des paramètres intrinsèques de la caméra NIR. On récupère en particulier la matrice K
    cal = ut.cameracalibration("DJI_Raw")

    if osp.exists(motion_cache) and utilise_cache:
        # utilisation des mouvements du drone et des angles de correction déjà sauvegardés
        print(Style.YELLOW + "Warning : utilisation du cache" + Style.RESET)
        m_cache = np.load(motion_cache, allow_pickle=True).item()
        motion_list, motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, normal_fin_b, \
        motion_list_drone, motion_list_cameraDJI, summaryFlight, yaw_Theorique, pitch_Theorique = \
            withMotionCache(m_cache)
    else:
        motion_list, motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, normal_fin_b, \
        motion_list_drone, motion_list_cameraDJI, summaryFlight, yaw_Theorique, pitch_Theorique = \
            noMotionCache(dir_mission, cal, showRefined)

    # infoMotion(motion_list_drone, motion_list_cameraDJI)

    # -------------------- Tracé des courbes   Yaw Pitch Roll ---------------------------------------------

    print(Style.YELLOW + 'Look at the yaw and pitch angles graph of NIR images  >>>>' + Style.RESET)
    plotAngles(motion_list, pitch_Theorique, yaw_Theorique, offsetYaw, offsetPitch,
               motion_list_drone, motion_list_cameraDJI, motion_list_fin_a, motion_list_fin_b, missionTitle,
               showAngleCoarseProcess, showTheoreticalAngle, showGap, showSpectralAnalysis, showDispersion, showRefined,
               dirSaveFig=dirSaveFig)


def plotAngles(motion_list, pitch_Theorique, yaw_Theorique, offsetYaw, offsetPitch,
               motion_list_drone, motion_list_cameraDJI, motion_list_fin_a, motion_list_fin_b, missionTitle,
               showAngleCoarseProcess, showTheoreticalAngle, showGap, showSpectralAnalysis, showDispersion, showRefined,
               dirSaveFig=None):
    motion_nul = []
    if showAngleCoarseProcess:
        IRdplt.YawPitchTeoriticalAndCoarse_plot(motion_list, pitch_Theorique, yaw_Theorique, offsetYaw, offsetPitch,
                                                missionTitle, dirSaveFig=dirSaveFig)

    if showTheoreticalAngle:
        IRdplt.Pitch_plot(motion_list, pitch_Theorique, offsetPitch, missionTitle, motion_list_fin_a, motion_list_fin_b,
                          traceFin_a=False, traceFin_b=False)
        IRdplt.Yaw_plot(motion_list, yaw_Theorique, offsetYaw, missionTitle, motion_list_fin_a, motion_list_fin_b,
                        traceFin_a=False, traceFin_b=False)

    if showGap:
        IRdplt.DeltaAngle_plot(motion_list, pitch_Theorique, offsetPitch, missionTitle, idx=2, nameAngle='Pitch')
        IRdplt.DeltaAngle_plot(motion_list, yaw_Theorique, offsetYaw, missionTitle, idx=1, nameAngle='Yaw unsynchro')
        IRdplt.DeltaYawSynchro_Unsynchro_plot(motion_list, motion_list_drone, motion_list_cameraDJI, yaw_Theorique,
                                              offsetYaw, missionTitle, nameAngle='Yaw synchro / unsynchro')

    if showSpectralAnalysis:
        IRdplt.Fourier_plot_2([motion_list[:, 2], pitch_Theorique[:, 1] + offsetPitch],
                              missionTitle,
                              titleSignal=['Pitch  Coarse process', 'Pitch  Theoretical'],
                              color=['black', 'magenta', 'orange'])
        IRdplt.Fourier_plot_2([motion_list[:, 1], yaw_Theorique[:, 1] - offsetYaw],
                              missionTitle,
                              titleSignal=['Yaw  Coarse process', 'Yaw  Theoretical'],
                              color=['black', 'magenta', 'orange'])

    # Etude de la dispersion  Pitch et Yaw des caméras (donc des images)
    if showDispersion:
        for i in range(len(motion_list)):
            motion_nul.append([0, 0, 0, 0])

        IRdplt.comparaisonPitchYaw_plot(motion_list,
                                        motion_list_drone,
                                        motion_list_cameraDJI,
                                        missionTitle,
                                        pitch_Theorique,
                                        offsetPitch,
                                        offsetYaw,
                                        process='Coarse ',
                                        motion_refined=np.array(motion_nul))
    if showDispersion and showRefined:
        IRdplt.comparaisonPitchYaw_plot(motion_list,
                                        motion_list_drone,
                                        motion_list_cameraDJI,
                                        missionTitle,
                                        pitch_Theorique,
                                        offsetPitch,
                                        offsetYaw,
                                        process='Refined ',
                                        motion_refined=motion_list_fin_b)


def noMotionCache(dirMission, cal, calculDecompositionHomographie):
    motion_list, motion_list_drone, motion_list_cameraDJI = [], [], []
    motion_list_fin_a, translat_fin_a, normal_fin_a = [], [], []
    motion_list_fin_b, translat_fin_b, normal_fin_b = [], [], []
    yaw_Theorique, pitch_Theorique, roll_Theorique = [], [], []

    pathMission = Path(dirMission)
    result_dir = pathMission/"ImgIRdrone"
    # List of original images in the AerialPhotography folder (visible spectrum) .  Ext .DNG
    summaryFlight = IRd.readFlightSummary(pathMission/'Flight Analytics', mute=True)
    # List of motion models of IRdrone images.  Ext .py
    ImgPostProcess = sorted(result_dir.glob("*.npy"))
    motion_cache = result_dir/"motion_summary_vs_drone_dates"
    count1 = 0
    count2 = 0

    for k in range(len(summaryFlight)):
        count1 += 1
        nameImgPostProcess = ImgPostProcess[k].name[: -17]
        nameImgPreProcess = summaryFlight[k][1][: -4]
        try:
            assert ImgPostProcess[k].is_file() and nameImgPostProcess == nameImgPreProcess
            date = summaryFlight[count1 - 1][6]  # date on time line
            # date , roll, pitch & yaw   drone      (NIR camera)
            mouvement_drone = [date, summaryFlight[count1 - 1][21], summaryFlight[count1 - 1][20], summaryFlight[count1 - 1][19]]
            motion_list_drone.append(mouvement_drone)
            # date , roll, pitch & yaw   gimbal     (VIS camera)
            mouvement_cameraDJI = [date, summaryFlight[count1 - 1][24], summaryFlight[count1 - 1][23], summaryFlight[count1 - 1][12]]
            motion_list_cameraDJI.append(mouvement_cameraDJI)
            #  yaw,  pitch & roll.  Theoretical registration angle of near infrared images.
            yaw_Theorique.append((date, summaryFlight[count1 - 1][28]))
            pitch_Theorique.append((date, summaryFlight[count1 - 1][29]))
            roll_Theorique.append((date, summaryFlight[count1 - 1][30]))
            #  yaw & pitch .  Coarse  registration angle of near infrared images.
            mouvement = np.load(ImgPostProcess[k], allow_pickle=True).item()
            motion_list.append([date, mouvement["yaw"], mouvement["pitch"],  mouvement["roll"]])

            if calculDecompositionHomographie:
                motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, normal_fin_b \
                    = decompositionHomography(mouvement, date, cal,
                                              motion_list_fin_a, translat_fin_a, normal_fin_a,
                                              motion_list_fin_b, translat_fin_b, normal_fin_b)
        except AssertionError:
            print(Style.RED + '[error in noMotionCache ] %s  != %s'%(nameImgPostProcess, nameImgPreProcess) + Style.RESET)

    motion_list = np.array(motion_list)
    motion_list_fin_a = np.array(motion_list_fin_a)
    translat_fin_a = np.array(translat_fin_a)
    normal_fin_a = np.array(normal_fin_a)
    motion_list_fin_b = np.array(motion_list_fin_b)
    translat_fin_b = np.array(translat_fin_b)
    normal_fin_b = np.array(normal_fin_b)
    motion_list_drone = np.array(motion_list_drone)
    motion_list_cameraDJI = np.array(motion_list_cameraDJI)
    summaryFlight = np.array(summaryFlight)
    yaw_Theorique = np.array(yaw_Theorique)
    pitch_Theorique = np.array(pitch_Theorique)

    # sauvegarde des mouvements du drone et des angles de correction
    np.save(motion_cache, {"motion_list": motion_list,
                                "motion_list_drone": motion_list_drone,
                                "motion_list_cameraDJI": motion_list_cameraDJI,
                                "summaryFlight": summaryFlight,
                                "pitch_Theorique": pitch_Theorique,
                                "yaw_Theorique": yaw_Theorique,
                                "motion_list_fin_a": motion_list_fin_a,
                                "translat_fin_a": translat_fin_a,
                                "normal_fin_a": normal_fin_a,
                                "motion_list_fin_b": motion_list_fin_b,
                                "translat_fin_b": translat_fin_b,
                                "normal_fin_b": normal_fin_b
                                })
    txt = 'The angles of ' + str(count1 - count2) + ' pairs of Visible-Infrared images were analyzed. \n' + \
          str(count2) + "   pairs have been eliminated :  "
    print(Style.GREEN + txt + Style.RESET)

    return motion_list, motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, \
           normal_fin_b, motion_list_drone, motion_list_cameraDJI, summaryFlight, yaw_Theorique, pitch_Theorique


def withMotionCache(m_cache):
    motion_list = m_cache["motion_list"]
    motion_list_drone = m_cache["motion_list_drone"]
    motion_list_cameraDJI = m_cache["motion_list_cameraDJI"]
    summaryFlight = m_cache["summaryFlight"]
    pitch_Theorique = m_cache["pitch_Theorique"]
    yaw_Theorique = m_cache["yaw_Theorique"]
    motion_list_fin_a = m_cache["motion_list_fin_a"]
    translat_fin_a = m_cache["translat_fin_a"]
    normal_fin_a = m_cache["normal_fin_a"]
    motion_list_fin_b = m_cache["motion_list_fin_b"]
    translat_fin_b = m_cache["translat_fin_b"]
    normal_fin_b = m_cache["normal_fin_b"]
    return motion_list, motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, \
           normal_fin_b, motion_list_drone, motion_list_cameraDJI, summaryFlight, yaw_Theorique, pitch_Theorique


def infoMotion(motion_list_drone, motion_list_cameraDJI):
    print('average  flight_Roll %.2f°  Gimbal_Roll %.2f°' %
          (np.average(motion_list_drone[:, 1]), np.average(motion_list_cameraDJI[:, 1])))
    print('average  flight_Yaw %.2f°  Gimbal_Yaw %.2f°' %
          (np.average(motion_list_drone[:, 3]), np.average(motion_list_cameraDJI[:, 3])))
    print('average  flight_Pitch %.2f°  Gimbal_Pitch %.2f°' %
          (np.average(motion_list_drone[:, 2]), np.average(motion_list_cameraDJI[:, 2])))
    print(' average delta Roll Drone/Gimbal  | |=%.2f' %
          np.average(abs(-motion_list_drone[:, 1] + motion_list_cameraDJI[:, 1])))
    print(' average delta Yaw Drone/Gimbal | |= %.2f' %
          np.average(abs(-motion_list_drone[:, 3] + motion_list_cameraDJI[:, 3])))


def decompositionHomography(mouvement, date, cal,
                            motion_list_fin_a, translat_fin_a, normal_fin_a,
                            motion_list_fin_b, translat_fin_b, normal_fin_b):
    solution = cv2.decomposeHomographyMat(mouvement["homography"], cal["mtx"])
    for idx in range(4):
        extra_pitch, extra_yaw, extra_roll = np.rad2deg(cv2.Rodrigues(solution[1][idx])[0].flatten())
        extra_tx, extra_ty, extra_tz = (solution[2][idx])
        extra_nx, extra_ny, extra_nz = (solution[3][idx])
        print('Solution N°', idx + 1, '\n',
              'pitch = %.4f°  yaw = %.4f°  roll = %.4f°  ' % (extra_pitch, extra_yaw, extra_roll))
        # print('  R', idx, '= ', solution[1][idx],'\n')
        print('  tx = %.4f  ty = %.4f  tz = %.4f  ' % (extra_tx, extra_ty, extra_tz))
        print('  nx = %.4f  ny = %.4f  nz = %.4f   ||n|| =%.4f'
              % (extra_nx, extra_ny, extra_nz, (extra_nx ** 2 + extra_ny ** 2 + extra_nz ** 2) ** 0.5))

        # break
    # WARNING! Choosing the first solution here, not sure it's the right one!!!
    extra_pitch, extra_yaw, extra_roll = np.rad2deg(cv2.Rodrigues(solution[1][0])[0].flatten())
    extra_tx, extra_ty, extra_tz = (solution[2][0])
    extra_nx, extra_ny, extra_nz = (solution[3][0])
    motion_list_fin_a.append([date, extra_yaw, extra_pitch, extra_roll])
    translat_fin_a.append([date, extra_tx, extra_ty, extra_tz])
    normal_fin_a.append([date, extra_nx, extra_ny, extra_nz])

    extra_pitch, extra_yaw, extra_roll = np.rad2deg(cv2.Rodrigues(solution[1][2])[0].flatten())
    extra_tx, extra_ty, extra_tz = (solution[2][2])
    extra_nx, extra_ny, extra_nz = (solution[3][2])
    motion_list_fin_b.append([date, extra_yaw, extra_pitch, extra_roll])
    translat_fin_b.append([date, extra_tx, extra_ty, extra_tz])
    normal_fin_b.append([date, extra_nx, extra_ny, extra_nz])

    return motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, normal_fin_b


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


if __name__ == "__main__":
    # ---------------------------- Options ---------------------------------------------------------------------------
    coarseProcess = True
    theoreticalAngle = False
    gap = False
    spectralAnalysis = False
    dispersion = True
    refined = False  # Attention extraction des homographies pour construire le cache ... long
    # Offset theoritical angles
    # [Yaw, Pitch,Roll]  -------------------------------- Mission ------------------------------------------------
    # [0.83,  2.03, 0.]  06 septembre 2021   U = 0,5 m/s  hyperlapse auto | vent faible (très légères rafales)
    # [0.90,  1.33, 0.]  06 septembre 2021   U = 1,0 m/s  hyperlapse auto | vent faible
    # [0.90,  0.50, 0.]  08 septembre 2021   U = 1,0 m/s  hyperlapse auto | beaucoup de rafales de vent !
    # [0.90,  1.30, 0.]  OK 09 novembre  2021   U = 1,0 m/s  hyperlapse auto | vent très faible | longue séquence :-)
    # [0.25,  1.63, 0.]  OK 18 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | test synchro
    # [0.33,  1.81, 0.]  OK 25 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | Support cas TEST pour GitHub
    # [0.33,  1.81, 0.]  OK 25 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | cas TEST GitHub COMPLET
    # [0.86,  1.43, 0.]  OK Peyrelevade-P 2 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # [1.02,  1.30, 0.]  OK Peyrelevade-P 1 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # [0.20,  2.57, 0.]  0K 25 janvier   2022   phase de Synchro  hyperlapse libre| vent nul |
    # [0.86,  1.43, 0.]  -> default offset Yaw, Pitch, Roll for theoretical angles
    # -------------------------------------------------------------------------------------------------------------
    # Attebtion les angles sont déjà corrigés de l'offset lors du process image. Ne pas les ajouter ici
    #             [Yaw, Pitch, Roll]
    offsetAngle = [0,  0, 0.]

    # ----------------------------------------------------------------------------------------------------------------
    # 0 > Choix interactif de la mission
    #

    dirMission, utilise_cache = interactifChoice()

    # ---------------------------------------------------------------------------------------------------------------
    # 1 > Trace les angles Roll, Pitch et Yaw  (roulis, tangage & lacet)
    #     pour le drone, le gimbal et l'image NIR (coarse process et théorique)
    #

    plotYawPitchRollDroneAndCameraDJI(dirMission,
                                      utilise_cache=utilise_cache,
                                      offsetYaw=offsetAngle[0],
                                      offsetPitch=offsetAngle[1],
                                      showAngleCoarseProcess=coarseProcess,
                                      showTheoreticalAngle=theoreticalAngle,
                                      showGap=gap,
                                      showSpectralAnalysis=spectralAnalysis,
                                      showDispersion=dispersion,
                                      showRefined=refined
                                      )