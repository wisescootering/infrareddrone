import numpy as np
import glob
import matplotlib.pyplot as plt
import matplotlib.transforms as mtrans
import utils_IRdrone as IRd
import irdrone.process as pr
from datetime import timedelta
from irdrone.utils import Style
import os
import os.path as osp
import cv2
import irdrone.utils as ut
import datetime
import scipy.fft
import random


def plotYawPitchRollDroneAndCameraDJI(dir_mission, utilise_cache=False):
    #
    # Le 7 septembre 2021 la SJCam M20 a été équipée d'une cale de +3,1°  (+ <=> vision "vers l'avant")
    date_cale = datetime.date(2021,9,7)
    angle_wedge = 3.1  #angle of the wedge  in degre
    #



    motion_list, motion_list_drone, motion_list_cameraDJI = [], [], []
    motion_list_fin_a, translat_fin_a, normal_fin_a = [], [], []
    motion_list_fin_b, translat_fin_b, normal_fin_b = [], [], []
    motion_nul = []
    image_dir = osp.join(dir_mission, "AerialPhotography")
    result_dir = osp.join(dir_mission, "ImgIRdrone")
    desync = timedelta(seconds=-0)
    txt = str('Delay  ' + str(desync) + "s")
    print(Style.YELLOW + txt + Style.RESET)
    missionTitle= dir_mission.split("/")[-1]

    motion_cache = osp.join(result_dir, "motion_summary_vs_drone_dates.npy")
    count1 = 0
    count2 = 0
    # Chargement des paramètres intrinsèques de la caméra NIR. On récupère en particulier la matrice K
    cal = ut.cameracalibration("DJI_Raw")

    if not osp.exists(motion_cache) or not utilise_cache :
        for ipath in glob.glob(osp.join(image_dir, "*.DNG")):
            try:
                count1 += 1
                mpath = glob.glob(osp.join(result_dir, osp.basename(ipath)[:-4]) + "*.npy")[0]
                img = pr.Image(ipath)
                print(Style.CYAN + img.name + Style.RESET)
                finfo = img.flight_info
                date = img.date
                # roll, pitch & yaw   drone    (NIR camera)
                mouvement_drone = [date, finfo["Flight Roll"], finfo["Flight Pitch"], finfo["Flight Yaw"]]
                motion_list_drone.append(mouvement_drone)
                # roll, pitch & yaw   gimbal  (VIS camera)
                mouvement_cameraDJI = [date, finfo["Gimbal Roll"], finfo["Gimbal Pitch"], finfo["Gimbal Yaw"]]
                motion_list_cameraDJI.append(mouvement_cameraDJI)
                #  yaw & pitch  image NIR recalage grossier
                mouvement = np.load(mpath, allow_pickle=True).item()
                motion_list.append([date, mouvement["yaw"], mouvement["pitch"]])

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
                          %(extra_nx, extra_ny, extra_nz, (extra_nx**2+ extra_ny**2+extra_nz**2)**0.5))


                    #break
                # WARNING! Choosing the first solution here, not sure it's the right one!!!
                extra_pitch, extra_yaw, extra_roll = np.rad2deg(cv2.Rodrigues(solution[1][0])[0].flatten())
                extra_tx, extra_ty, extra_tz = (solution[2][0])
                extra_nx, extra_ny, extra_nz = (solution[3][0])
                motion_list_fin_a.append([date, extra_yaw, extra_pitch, extra_roll])
                translat_fin_a.append([date,extra_tx, extra_ty, extra_tz])
                normal_fin_a .append([date,extra_nx, extra_ny, extra_nz])

                extra_pitch, extra_yaw, extra_roll = np.rad2deg(cv2.Rodrigues(solution[1][2])[0].flatten())
                extra_tx, extra_ty, extra_tz = (solution[2][2])
                extra_nx, extra_ny, extra_nz = (solution[3][2])
                motion_list_fin_b.append([date, extra_yaw, extra_pitch, extra_roll])
                translat_fin_b.append([date,extra_tx, extra_ty, extra_tz])
                normal_fin_b .append([date,extra_nx, extra_ny, extra_nz])

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
        np.save(motion_cache[:-4], {"motion_list": motion_list,
                                    "motion_list_drone": motion_list_drone,
                                    "motion_list_cameraDJI": motion_list_cameraDJI,
                                    "motion_list_fin_a": motion_list_fin_a,
                                    "translat_fin_a": translat_fin_a,
                                    "normal_fin_a": normal_fin_a,
                                    "motion_list_fin_b": motion_list_fin_b,
                                    "translat_fin_b": translat_fin_b,
                                    "normal_fin_b": normal_fin_b
                                    })
        txt = "images retenues" + str(count1 - count2) + "   images rejettées  " + str(count2)
        print(Style.CYAN + txt + Style.RESET)

    else:
        print(Style.YELLOW + "Warning : utilisation du cache" + Style.RESET)
        m_cache = np.load(motion_cache, allow_pickle=True).item()
        motion_list = m_cache["motion_list"]
        motion_list_drone = m_cache["motion_list_drone"]
        motion_list_cameraDJI = m_cache["motion_list_cameraDJI"]
        motion_list_fin_a = m_cache["motion_list_fin_a"]
        translat_fin_a = m_cache["translat_fin_a"]
        normal_fin_a = m_cache["normal_fin_a"]
        motion_list_fin_b = m_cache["motion_list_fin_b"]
        translat_fin_b = m_cache["translat_fin_b"]
        normal_fin_b = m_cache["normal_fin_b"]

    dates = motion_list[:, 0]
    # détermination de l'offset théorique de l'image NIR
    date_mission=datetime.date(dates[0].year,dates[0].month,dates[0].day)

    if date_mission > date_cale:
        print(Style.YELLOW + "présence d'une cale de 3,1° sous la SJCam M20" + Style.RESET)
        calePitchM20 = angle_wedge
    else :
        calePitchM20 = 0
    print('average  flight_Roll %.2f°  Gimbal_Roll %.2f°' %
              (np.average(motion_list_drone[:, 1]), np.average(motion_list_cameraDJI[:, 1])))
    print('average  flight_Yaw %.2f°  Gimbal_Yaw %.2f°' %
          (np.average(motion_list_drone[:, 3]), np.average(motion_list_cameraDJI[:, 3])))
    print('average  flight_Pitch %.2f°  Gimbal_Pitch %.2f°'%
          (np.average(motion_list_drone[:,2]),np.average( motion_list_cameraDJI[:,2])))
    print(' average delta Roll Drone/Gimbal  %.2f'%
          np.average((-motion_list_drone[:,1]+motion_list_cameraDJI[:,1])))
    print(' average delta Yaw Drone/Gimbal  %.2f' %
          np.average((-motion_list_drone[:, 3] + motion_list_cameraDJI[:, 3])))

    #  Tracé des courbes
    #
    #    Yaw Pitch Roll

    YawPitchTeoriticalAndCoarse_plot(motion_list,
                                     motion_list_cameraDJI,
                                     motion_list_drone,
                                     0*calePitchM20,
                                     missionTitle,
                                     desync)

    DeltaYawPitchTeoriticalAndCoarse_plot(motion_list,
                                     motion_list_cameraDJI,
                                     motion_list_drone,
                                     0 * calePitchM20,
                                     missionTitle,
                                     desync)

    # Analyse de Fourier du Pitch
    '''
    signal = motion_list[:, 2]
    Fourier_plot(signal, title1='Pitch Image NIR  ', title2='', color='orange')
    signal = (- (motion_list_cameraDJI[:, 2] + 90.))
    Fourier_plot(signal, title1='Pitch_Camera DJI  ', title2='', color='r')
    signal = motion_list_drone[:, 2]
    Fourier_plot(signal, title1='Pitch_Camera NIR  ', title2='', color='g')
    '''
    signal =  (motion_list_cameraDJI[:, 2] + 90. - motion_list_drone[:, 2])
    Fourier_plot(signal, title1='Theoritical Pitch  ', title2='', color='c')

    signal = motion_list[:, 2] - (motion_list_cameraDJI[:, 2] + 90.- motion_list_drone[:, 2])
    Fourier_plot(signal, title1='NIR Pitch - Theoritical Pitch  ', title2='',color='m')

    # Etude de la dispersion  Pitch et Yaw des caméras (donc des images)
    for i in range(len(motion_list)):
        motion_nul.append([0,0,0,0])

    comparaisonPitchYaw_plot(motion_list,
                                    motion_list_drone,
                                    motion_list_cameraDJI,
                                    missionTitle,
                                    0*calePitchM20,
                                    process='Coarse ',
                                    motion_refined= np.array(motion_nul))

    comparaisonPitchYaw_plot(motion_list,
                                    motion_list_drone,
                                    motion_list_cameraDJI,
                                    missionTitle,
                                    0*calePitchM20,
                                    process='Refined ',
                                    motion_refined =motion_list_fin_b)


def YawPitchTeoriticalAndCoarse_plot(motion_list,
                                     motion_list_cameraDJI,
                                     motion_list_drone,
                                     calePitchM20,
                                     missionTitle,
                                     desync):
    plt.title(missionTitle + "    Delay {}".format(float(desync.total_seconds())))
    plt.plot(motion_list[:, 0], motion_list[:, 1], "b--",
             label="yaw_imgNIR       (coarse process)    average = {:.2f}°".format(
                 np.average(motion_list[:, 1], axis=0)))
    plt.plot(motion_list[:, 0] + desync, -motion_list_drone[:, 1], "c-",
             label="Theoretical yaw_imgNIR (roll_drone)  average = {:.2f}°"
             .format(np.abs(np.average(-motion_list_drone[:, 1], axis=0))))
    plt.plot(motion_list[:, 0], motion_list[:, 2], "r--",
             label="pitch_imgNIR       (coarse process)    average = {:.2f}°"
             .format(np.average(motion_list[:, 2], axis=0)))
    plt.plot(motion_list[:, 0] + desync,
             motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2], "m-",
             label="Theoretical pitch_imgNIR  (90+pitch gimbal-pitch drone)  average = {:.2f}°"
             .format(np.abs(-np.average(motion_list_cameraDJI[:, 2] + 90.
                                        - calePitchM20 - motion_list_drone[:, 2], axis=0))))
    plt.plot(motion_list[:, 0] + desync,
              motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], "g-",
             label="Yaw Drone - Yaw Gimball           average = {:.2f}°"
             .format(np.abs(np.average( motion_list_drone[:, 3]-motion_list_cameraDJI[:, 3], axis=0))))
    plt.grid()
    plt.legend()
    plt.show()


def DeltaYawPitchTeoriticalAndCoarse_plot(motion_list,
                                     motion_list_cameraDJI,
                                     motion_list_drone,
                                     calePitchM20,
                                     missionTitle,
                                     desync):
    plt.title(missionTitle + "    Delay {}".format(float(desync.total_seconds())))
    plt.plot(motion_list[:, 0], motion_list[:, 1]-(-motion_list_drone[:, 1]), "b--",
             label="delta yaw_imgNIR      average = {:.2f}°".format(
                 np.average(motion_list[:, 1]-(-motion_list_drone[:, 1]), axis=0)))
    plt.plot(motion_list[:, 0], motion_list[:, 2] -
             (motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2]), "r--",
             label="delta pitch_imgNIR    average = {:.2f}°"
             .format(np.average(motion_list[:, 2] -
             (motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2]), axis=0)))
    plt.plot(motion_list[:, 0] + desync,
              motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], "g-",
             label="delta Roll_imgNIR     average = {:.2f}°"
             .format(np.abs(np.average( motion_list_drone[:, 3]-motion_list_cameraDJI[:, 3], axis=0))))
    plt.grid()
    plt.legend()
    plt.show()

def decomposeHomographyRefined_Plot(motion_list_fin_a, motion_list_fin_b,
                                    translat_fin_a, translat_fin_b,
                                    normal_fin_a, normal_fin_b,
                                    missionTitle):
    # Courbe d'evolution des angles fin solution a et b)
        print('Average refined yaw solution a = ', np.average(motion_list_fin_a[:, 1]),
              ' solution b = ',np.average(motion_list_fin_b[:, 1]))
        print('Average refined pitch solution a = ', np.average(motion_list_fin_a[:, 2]),
              ' solution b = ', np.average(motion_list_fin_b[:, 2]))
        print('Average refined roll solution a = ', np.average(motion_list_fin_a[:, 3]),
              ' solution b = ', np.average(motion_list_fin_b[:, 3]))
        plt.title(missionTitle)
        plt.plot(motion_list_fin_a[:, 1], "m-", label="pitch_a")
        plt.plot(motion_list_fin_b[:, 1], "m-.", label="pitch_b")
        plt.plot(motion_list_fin_a[:, 2], "r-", label="yaw_a")
        plt.plot(motion_list_fin_b[:, 2], "r-.",label="yaw_b")
        plt.plot(motion_list_fin_a[:, 3], "b-", label="roll_a")
        plt.plot(motion_list_fin_b[:, 3], "b-.",label="roll_b")
        plt.legend()
        plt.grid()
        plt.show()

    # Courbe d'evolution des translation fine solution a et b)
        plt.title(missionTitle)
        plt.plot(translat_fin_a[:, 1], "m-", label="tx_a")
        #plt.plot(translat_fin_b[:, 1], "m-.", label="tx_b")
        plt.plot(translat_fin_a[:, 2], "r-", label="ty_a")
        #plt.plot(translat_fin_b[:, 2], "r-.",label="ty_b")
        plt.plot(translat_fin_a[:, 3], "b-", label="tz_a")
        #plt.plot(translat_fin_b[:, 3], "b-.",label="tz_b")
        plt.legend()
        plt.grid()
        plt.show()

        # Courbe d'evolution des normale fine solution a et b)
        normal_fin_a = np.array(normal_fin_a)
        normal_fin_b = np.array(normal_fin_b)
        plt.title(missionTitle)
        plt.plot(normal_fin_a[:, 1], "m-", label="nx_a")
        #plt.plot(normal_fin_b[:, 1], "m-.", label="nx_b")
        plt.plot(normal_fin_a[:, 2], "r-", label="ny_a")
        #plt.plot(normal_fin_b[:, 2], "r-.", label="ny_b")
        plt.plot(abs(normal_fin_a[:, 3]), "b-", label="| nz_a |")
        #plt.plot(normal_fin_b[:, 3], "b-.", label="nz_b")
        plt.legend()
        plt.grid()
        plt.show()

def comparaisonPitchYaw_plot(motion_list,
                                    motion_list_drone,
                                    motion_list_cameraDJI,
                                    missionTitle,
                                    calePitchM20,
                                    process='',
                                    motion_refined=None):
    maxiIRrefined = (np.max(((motion_list[:, 1] - motion_refined[:, 1]), -motion_list_drone[:, 1])),
                     np.max(((motion_list[:, 2] - motion_refined[:, 2]),
                             motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2])))
    miniIRrefined = (np.min(((motion_list[:, 1] - motion_refined[:, 1]), -motion_list_drone[:, 1])),
                     np.min(((motion_list[:, 2] - motion_refined[:, 2]),
                             motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2])))

    _, (ax1, ax2) = plt.subplots(nrows=1, ncols=2)
    # Courbe de dispersion des angles de la caméra VIS DJI Mavic Air.2   pitch(yaw)
    disperPitchYaw_plot(ax1, -motion_list_drone[:, 1],
                        motion_list_cameraDJI[:, 2] + 90. - calePitchM20 - motion_list_drone[:, 2],
                        miniIRrefined, maxiIRrefined,
                        missionTitle, 'Theoritical ', color='green')
    # Courbe de dispersion des angles de reclage de l'mage NIR sur l'image VIS  (pitch et yaw "refined")
    # ATTENTION: pour redresser l'image NIR on applique une rotation avec un pitch_NIR (resp yaw_NIR)
    # de signe opposé à celui du pitch (resp yaw) de la M20.
    disperPitchYaw_plot(ax2, motion_list[:, 1] - motion_refined[:, 1], motion_list[:, 2] - motion_refined[:, 2],
                        miniIRrefined, maxiIRrefined,
                        missionTitle, process, color='orange')

    plt.tight_layout()
    plt.show()


def disperPitchYaw_plot(ax, fx, fy,  mini, maxi, missionTitle, spectralType, color='yellow'):
    avg = (np.average(fx, axis=0), np.average(fy, axis=0))
    std = (np.std(fx, axis=0), np.std(fy, axis=0))
    ax.plot(fx, fy,
             marker="o", markersize=6, alpha=0.4,  mec=color, mfc=color, linestyle='')
    ax.set_xlim(mini[0]-2., maxi[0]+2.)
    ax.set_ylim(mini[1]-2., maxi[1]+2.)
    ax.plot(0., 0., "k+")
    ax.plot(avg[0], avg[1], "r+")
    myTitle = str(missionTitle + "\n" + spectralType +\
              "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"\
                  .format(avg[0], std[0], avg[1], std[1]))
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel("%s yaw"% spectralType, fontsize=8)
    ax.set_ylabel("%s pitch"%spectralType, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)


def Fourier_plot(signal, title1='', title2='', color='p'):
    signal_fin = signal[0]
    signal = np.append(signal, signal_fin)
    signal = signal - np.average(signal)
    nombre_image = len(signal)  #
    print('nombre d\'images ', nombre_image)
    N = nombre_image // 2
    timeLapse_Img = 2  # s
    t = np.linspace(0.0, timeLapse_Img * nombre_image, nombre_image, endpoint=False)

    # Représentation graphique du signal
    fig, ax = plt.subplots()
    myTitle = 'Evolution du ' + title1 + ' en fonction du temps'
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel('Temps  [s]', fontsize=8)
    myYlabel = title1 + '[°] '
    ax.set_ylabel(myYlabel, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)
    ax.plot(t, signal, color=color,  linewidth=0.2)
    plt.plot(t, signal, marker="o", markersize=3, alpha=0.6, mec='black', mfc=color, linestyle='')
    plt.show()

    # Calcul de la transformée de Fourier du signal
    Fourier = scipy.fft.fft(signal, norm='ortho')
    fondamentale = (1 / timeLapse_Img) * np.argmax(np.abs(Fourier[:])) / (nombre_image)
    print('%s  Féquence fondamentale f1 =  %.3f Hz    Période fondamentale  T1 = %.2f s'
          % (title1, fondamentale, 1 / fondamentale))
    x_f = np.linspace(0.0, 1 / 2 * 1 / timeLapse_Img, N, endpoint=False)

    # Représentation graphique de la transformée (discrète) du signal
    fig, ax = plt.subplots()
    myTitle = 'Analyse spectrale du ' + title1
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel('Fréquence  [Hz]', fontsize=8)
    myYlabel = 'FFT(' + title1 + ')  '
    ax.set_ylabel(myYlabel, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)
    plt.plot(x_f, 2 / N * np.abs(Fourier[: N]), color=color, linestyle='-',  linewidth=0.5)
    plt.fill_between(x_f, [0.]*len(x_f) ,2 / N * np.abs(Fourier[: N]), alpha=0.2, color='gray')
    plt.plot((1 / timeLapse_Img) * np.argmax(np.abs(Fourier[:])) / (nombre_image),
             timeLapse_Img / N * np.max(np.abs(Fourier[:])),
             marker="o", markersize=6, alpha=0.5, mec=color, mfc=color, linestyle='', linewidth=0.6)
    trans_offset = mtrans.offset_copy(ax.transData, fig=fig,
                                      x=0.08, y=-0.10, units='inches')
    plt.text((1 / timeLapse_Img) * np.argmax(np.abs(Fourier[:])) / (nombre_image),
             timeLapse_Img / N * np.max(np.abs(Fourier[:])),
             '%.3f Hz' % (fondamentale), transform=trans_offset)
    plt.show()



if __name__ == "__main__":
    versionIRdrone = '1.05'  # 26 october 2021
    # ----------------------------------------------------
    # 0 > Choix interactif de la mission
    #
    print(Style.CYAN + "File browser")
    dirMission = os.path.dirname(IRd.loadFileGUI(mute=True))
    print(Style.CYAN + dirMission + Style.RESET)

    print(Style.MAGENTA + 'Voulez vous utiliser les données en cache  ?' + Style.RESET)
    utilise_cache = IRd.answerYesNo('Oui (1) |  Non (0):')

    # ----------------------------------------------------
    # 1 > Trace les angles Roll, Pitch et Yaw  (roulis, tangage & lacet)
    #     pour le drone, le gimbal et l'image NIR
    #

    plotYawPitchRollDroneAndCameraDJI(dirMission, utilise_cache=utilise_cache)
