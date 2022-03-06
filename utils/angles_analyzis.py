import sys
import os.path as osp
sys.path.append(osp.join(osp.dirname(__file__), ".."))
import utils_IRdrone as IRd
import utils_IRdrone_Plot as IRdplt
from version import __version__ as versionIRdrone
import numpy as np
import glob
import irdrone.process as pr
from datetime import timedelta
from irdrone.utils import Style
import os
import os.path as osp
import cv2
import irdrone.utils as ut
import datetime


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


def plotYawPitchRollDroneAndCameraDJI(dir_mission, utilise_cache=False, offsetPitch=0, offsetYaw=0):
    #
    # Le 7 septembre 2021 la SJCam M20 a été équipée d'une cale de +3,1°  (+ <=> vision "vers l'avant")
    date_cale = datetime.date(2021, 9, 7)
    angle_wedge = 3.1  # angle of the wedge  in degre

    # Estimation du défaut d'alignement de l'axe de visée caméra SJCam M20  après le 7 septembre 2021

    motion_list, motion_list_drone, motion_list_cameraDJI = [], [], []
    motion_list_fin_a, translat_fin_a, normal_fin_a = [], [], []
    motion_list_fin_b, translat_fin_b, normal_fin_b = [], [], []
    yaw_Theorique, pitch_Theorique, roll_Theorique = [], [], []
    motion_nul = []

    image_dir = osp.join(dir_mission, "AerialPhotography")
    result_dir = osp.join(dir_mission, "ImgIRdrone")
    desync = timedelta(seconds=-0)
    txt = str('Delay  ' + str(desync) + "s")
    print(Style.YELLOW + txt + Style.RESET)
    missionTitle = dir_mission.split("/")[-1]

    motion_cache = osp.join(result_dir, "motion_summary_vs_drone_dates.npy")
    count1 = 0
    count2 = 0
    # Chargement des paramètres intrinsèques de la caméra NIR. On récupère en particulier la matrice K
    cal = ut.cameracalibration("DJI_Raw")

    if not osp.exists(motion_cache) or not utilise_cache:

        listSummaryFlight = IRd.readFlightSummary(dirMission, mute=True)

        for ipath in glob.glob(osp.join(image_dir, "*.DNG")):

            try:
                count1 += 1
                mpath = glob.glob(osp.join(result_dir, osp.basename(ipath)[:-4]) + "*.npy")[0]
                img = pr.Image(ipath)
                print(Style.CYAN + img.name + Style.RESET)
                finfo = img.flight_info
                #  Todo securiser  cette partie   (si nb d'image DNG différent de celui dans flight summary)
                if img.name == listSummaryFlight[count1 - 1][1]:
                    pass  # print(Style.CYAN + img.name + Style.RESET)
                else:
                    txt = str(img.name) + ' != ' + listSummaryFlight[count1 - 1][1]
                    print(Style.RED + txt + Style.RESET)

                date = listSummaryFlight[count1 - 1][6]   # date on time line
                #date = IRd.dateExcelString2Py(date)
                # date = img.date
                # roll, pitch & yaw   drone    (NIR camera)
                mouvement_drone = [date, finfo["Flight Roll"], finfo["Flight Pitch"], finfo["Flight Yaw"]]
                motion_list_drone.append(mouvement_drone)
                # roll, pitch & yaw   gimbal  (VIS camera)
                mouvement_cameraDJI = [date, finfo["Gimbal Roll"], finfo["Gimbal Pitch"], finfo["Gimbal Yaw"]]
                motion_list_cameraDJI.append(mouvement_cameraDJI)
                #  yaw & pitch  process  image NIR recalage grossier
                mouvement = np.load(mpath, allow_pickle=True).item()
                motion_list.append([date, mouvement["yaw"], mouvement["pitch"]])
                #  yaw,  pitch & roll  théoriques
                data = date, listSummaryFlight[count1 - 1][28]
                yaw_Theorique.append(data)
                data = date, listSummaryFlight[count1 - 1][29]
                pitch_Theorique.append(data)
                data = date, listSummaryFlight[count1 - 1][30]
                roll_Theorique.append(data)

                calculDecompositionHomographie = False
                if calculDecompositionHomographie:
                    motion_list_fin_a, translat_fin_a, normal_fin_a, motion_list_fin_b, translat_fin_b, normal_fin_b \
                        = decompositionHomography(mouvement, date, cal,
                                                  motion_list_fin_a, translat_fin_a, normal_fin_a,
                                                  motion_list_fin_b, translat_fin_b, normal_fin_b)

            except:
                count2 += 1
                continue

        motion_list = np.array(motion_list)
        motion_list_fin_a = np.array(motion_list_fin_a)
        translat_fin_a = np.array(translat_fin_a)
        normal_fin_a = np.array(normal_fin_a)
        motion_list_fin_b = np.array(motion_list_fin_b)
        translat_fin_b = np.array(translat_fin_b)
        normal_fin_b = np.array(normal_fin_b)
        motion_list_drone = np.array(motion_list_drone)
        motion_list_cameraDJI = np.array(motion_list_cameraDJI)
        listSummaryFlight = np.array(listSummaryFlight)
        yaw_Theorique = np.array(yaw_Theorique)
        pitch_Theorique = np.array(pitch_Theorique)

        # sauvegarde des mouvements du drone et des angles de correction
        np.save(motion_cache[:-4], {"motion_list": motion_list,
                                    "motion_list_drone": motion_list_drone,
                                    "motion_list_cameraDJI": motion_list_cameraDJI,
                                    "listSummaryFlight": listSummaryFlight,
                                    "pitch_Theorique": pitch_Theorique,
                                    "yaw_Theorique": yaw_Theorique,
                                    "motion_list_fin_a": motion_list_fin_a,
                                    "translat_fin_a": translat_fin_a,
                                    "normal_fin_a": normal_fin_a,
                                    "motion_list_fin_b": motion_list_fin_b,
                                    "translat_fin_b": translat_fin_b,
                                    "normal_fin_b": normal_fin_b
                                    })
        txt = "images retenues" + str(count1 - count2) + "   images rejettées  " + str(count2)
        print(Style.CYAN + txt + Style.RESET)

    else:  # utilisation des mouvements du drone et des angles de correction déjà sauvegardés
        print(Style.YELLOW + "Warning : utilisation du cache" + Style.RESET)
        m_cache = np.load(motion_cache, allow_pickle=True).item()
        motion_list = m_cache["motion_list"]
        motion_list_drone = m_cache["motion_list_drone"]
        motion_list_cameraDJI = m_cache["motion_list_cameraDJI"]
        listSummaryFlight = m_cache["listSummaryFlight"]
        pitch_Theorique = m_cache["pitch_Theorique"]
        yaw_Theorique = m_cache["yaw_Theorique"]
        motion_list_fin_a = m_cache["motion_list_fin_a"]
        translat_fin_a = m_cache["translat_fin_a"]
        normal_fin_a = m_cache["normal_fin_a"]
        motion_list_fin_b = m_cache["motion_list_fin_b"]
        translat_fin_b = m_cache["translat_fin_b"]
        normal_fin_b = m_cache["normal_fin_b"]
    """
    dates = motion_list[:, 0]
    # détermination de l'offset théorique de l'image NIR
    date_mission = datetime.date(dates[0].year, dates[0].month, dates[0].day)

    if date_mission > date_cale:
        print(Style.YELLOW + "présence d'une cale de 3,1° sous la SJCam M20" + Style.RESET)
        calePitchM20 = angle_wedge
    else:
        calePitchM20 = 0
    """
    calePitchM20 = angle_wedge
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

# ----------------------------------------------------------------------------------------------------
#
#                 Tracé des courbes   Yaw Pitch Roll
#
# ----------------------------------------------------------------------------------------------------
    montreAngleCoarseProcess = True
    montreAngleTheorique = True
    montreEcart = False
    montreAnalyseFourier = False
    montreRefined = False

    if montreAngleCoarseProcess:
        IRdplt.YawPitchTeoriticalAndCoarse_plot(motion_list, motion_list_cameraDJI, motion_list_drone,
                                                pitch_Theorique, yaw_Theorique,offsetPitch, offsetYaw, missionTitle)

    if montreAngleTheorique:
        IRdplt.Pitch_plot(motion_list, motion_list_cameraDJI, motion_list_drone, pitch_Theorique, offsetPitch,
                          missionTitle, motion_list_fin_a, motion_list_fin_b, traceFin_a=False, traceFin_b=False)
        IRdplt.Yaw_plot(motion_list, motion_list_cameraDJI, motion_list_drone, yaw_Theorique, offsetYaw,
                        missionTitle, motion_list_fin_a, motion_list_fin_b, traceFin_a=False, traceFin_b=False)

    if montreEcart:
        IRdplt.DeltaAngle_plot(motion_list, pitch_Theorique, offsetPitch, missionTitle, idx=2, nameAngle='Pitch')
        IRdplt.DeltaAngle_plot(motion_list, yaw_Theorique, - offsetYaw, missionTitle, idx=1, nameAngle='Yaw unsynchro')
        IRdplt.DeltaYawSynchro_Unsynchro_plot(motion_list, motion_list_drone, motion_list_cameraDJI, yaw_Theorique,
                                              offsetYaw, missionTitle,  nameAngle='Yaw synchro / unsynchro')

    if montreAnalyseFourier:
        signal = motion_list[:, 2]
        IRdplt.Fourier_plot(signal, title1='NIR Pitch   (coarse process)', title2='', color='black', montreSignal=False)
        signal = (motion_list_cameraDJI[:, 2] + 90. - motion_list_drone[:, 2])
        IRdplt.Fourier_plot(signal, title1='Theoritical Pitch  synchro', title2='', color='orange', montreSignal=False)
        signal = pitch_Theorique[:, 1] - offsetPitch
        IRdplt.Fourier_plot(signal, title1='Theoritical Pitch  un-synchro', title2='', color='m', montreSignal=False)
        signal = motion_list[:, 1]
        IRdplt.Fourier_plot(signal, title1='NIR Yaw     (coarse process)', title2='', color='black', montreSignal=False)
        signal = yaw_Theorique[:, 1]
        IRdplt.Fourier_plot(signal, title1='Theoritical Yaw  un-synchro', title2='', color='m',montreSignal=False)

    # Etude de la dispersion  Pitch et Yaw des caméras (donc des images)
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
    if montreRefined:
        IRdplt.comparaisonPitchYaw_plot(motion_list,
                                        motion_list_drone,
                                        motion_list_cameraDJI,
                                        missionTitle,
                                        pitch_Theorique,
                                        offsetPitch,
                                        offsetYaw,
                                        process='Refined ',
                                        motion_refined=motion_list_fin_b)


if __name__ == "__main__":
    # ----------------------------------------------------
    # 0 > Choix interactif de la mission
    #
    print(Style.CYAN + "File browser")
    dirMission = os.path.dirname(IRd.loadFileGUI(mute=True))
    print(Style.CYAN + dirMission + Style.RESET)

    print(Style.MAGENTA + 'Voulez vous utiliser les données en cache  ?' + Style.RESET)
    utilise_cache = IRd.answerYesNo('Oui (1) |  Non (0):')

    corrige_defaut_axe_visee = True
    if corrige_defaut_axe_visee:
        # Pitch      Yaw
        # -2.03 °  0.83 °    06 septembre 2021   U = 0,5 m/s   vent faible (très légères rafales)
        # -1.29 °  0.79 °    06 septembre 2021   U = 1,0 m/s   vent faible
        # -0.50 °  0.90 °    08 septembre 2021   U = 1,0 m/s   beaucoup de rafales de vent !
        # -1.33 °  0.90 °    09 novembre  2021   U = 1,0 m/s   vent très faible
        # -1.90 °  0.50 °    18 janvier   2022   U = 1,5 m/s  (hyperlapse libre)  vent nul
        # -3.90 °  0.40 °    25 janvier   2022   U = 1,5 m/s  (hyperlapse libre)  vent nul
        # -2.00 °  0.90 ° Peyrelevade partie 2 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)

        offsetPitch = - 1.9   # défaut d'alignement (pitch) de l'axe de visée de la caméra NIR  en °
        offsetYaw = 0.9       # défaut d'alignement (yaw) de l'axe de visée de la caméra NIR    en °
    else:
        offsetPitch = 0
        offsetYaw = 0

    # ----------------------------------------------------
    # 1 > Trace les angles Roll, Pitch et Yaw  (roulis, tangage & lacet)
    #     pour le drone, le gimbal et l'image NIR (coarse process et théorique)
    #

    plotYawPitchRollDroneAndCameraDJI(dirMission,
                                      utilise_cache=utilise_cache,
                                      offsetPitch=offsetPitch,
                                      offsetYaw=offsetYaw
                                      )
