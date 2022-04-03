import numpy as np
import matplotlib.pyplot as plt
import matplotlib.transforms as mtrans
import scipy.fft
from irdrone.utils import Style


def flightProfil_plot(d_list, elev_Drone, elev_Ground, dirSaveFig=None, mute=True):
    # BASIC STAT INFORMATION
    min_elev = min(elev_Ground)

    # PLOT ELEVATION PROFILE
    base_reg = min_elev - 10
    plt.figure(figsize=(10, 4))
    plt.plot(d_list, elev_Drone, '.r', label='Drone: ', linewidth=1, linestyle='dashed', markersize=0)
    plt.plot(d_list, elev_Ground, 'tab:brown', label='Ground ')
    plt.fill_between(d_list, elev_Ground, base_reg, color='tab:brown', alpha=0.1)
    plt.text(d_list[0], elev_Drone[0], "Start Pt")
    plt.text(d_list[-1], elev_Drone[-1], "End Pt")
    plt.xlabel("Distance (m)")
    plt.ylabel("Altitude (m)")
    plt.grid()
    plt.legend(fontsize='small')
    filepath = dirSaveFig + '\\Topo' + '\\Flight profil IRdrone'
    if dirSaveFig is None:
        pass
    else:
        plt.savefig(filepath, dpi=75, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.CYAN + '----- Save flight profil in %s' % filepath + Style.RESET)
    if not mute:
        print(Style.YELLOW + 'Look your Drone Flight profil >>>>' + Style.RESET)
        plt.show()
    plt.close()


def Fourier_plot_2(signal, missionTitle, titleSignal='', color='p'):
    Fourier, x_f, fondamentale, N, nombre_image = [], [], [], [], []
    x_min = 9  # limite dans les basses fréquences. 0 No limit !
    timeLapse_Img = 2.018  # Timelapse de la caméra VIS du drone DJI.   en s

    fig, ax = plt.subplots()
    for i in range(len(signal)):
        # ------------------------------ Normalisation du signal-------------------------------------------------------
        signal[i] = signal[i] - np.average(signal[i])  # soustration de la moyenne  (elimination du terme constant)
        signal[i] = signal[i] / np.max(signal[i])  # normalisation du signal entre -1 et +1
        nombre_image.append(signal[i].size)  #
        N.append(nombre_image[i] // 2)  # echantillonnage du signal pour la fft

        # ----------------------- Calcul et trace la transformée de Fourier du signal----------------------------------

        fftSignal = scipy.fft.fft(signal[i], norm='ortho')
        Fourier.append(fftSignal)
        freq = (1 / timeLapse_Img) * (np.argmax(np.abs(Fourier[i][x_min:N[i]])) + x_min) / nombre_image[i]
        fondamentale.append(freq)
        maxFourier = 2 / N[i] * np.max(np.abs(Fourier[i][x_min:N[i]]))
        Fourier[i] = Fourier[i] / maxFourier  # normalisation  [0,1]
        print('%s  Fundamental frequency  f1 =  %.3f Hz    Fundamental period  T1 = %.2f s'
              % (titleSignal[i], fondamentale[i], 1 / fondamentale[i]))
        axe_frequence = np.linspace(0.0, 1 / 2 * 1 / timeLapse_Img, N[i], endpoint=False)  # axe des fréquences
        x_f.append(axe_frequence)
        ax.plot(x_f[i], (2 / N[i] * np.abs(Fourier[i][: N[i]])),
                color=color[i], linestyle='-', linewidth=0.75, label=titleSignal[i])
        # ------------------------- Etiquette de la fréquence fondamentale --------------------------------------------
        plt.plot(fondamentale[i], timeLapse_Img / N[i] * np.max(np.abs(Fourier[i][x_min:N[i]])),
                 marker="o", markersize=6, alpha=0.5, mec=color[1], mfc=color[i], linestyle='', linewidth=0.6)
        trans_offset = mtrans.offset_copy(ax.transData, fig=fig, x=0.08, y=-0.10, units='inches')
        plt.text(fondamentale[i], timeLapse_Img / N[i] * np.max(np.abs(Fourier[i][x_min:N[i]])),
                 '%.3f Hz' % (fondamentale[i]), transform=trans_offset)
    # ---------------------------------------- Legendes ---------------------------------------------------------------
    ax.set_title(missionTitle, fontsize=8)
    ax.set_xlabel('Frequency  [Hz]', fontsize=8)
    ax.legend()
    # -------------------------------Mise en forme particulière si une seule courbe -----------------------------------
    if len(signal) == 1:
        plt.fill_between(x_f[0], [0.] * len(x_f[0]), 2 / N[0] * np.abs(Fourier[0][:N[0]]),
                         alpha=0.2, color='gray')
    # ----------------------------- Limitation des axes --------------------------------------------------------------
    ax.grid(color='gray', linestyle='-', linewidth=0.5)
    plt.xlim(0.03, np.max(x_f))
    plt.ylim(0.0, 1.1)
    plt.show()


def YawPitchTeoriticalAndCoarse_plot(motion_list,
                                     pitch_Theorique,
                                     yaw_Theorique,
                                     offsetPitch,
                                     offsetYaw,
                                     missionTitle):
    fig, ax = plt.subplots()
    plt.plot(motion_list[:, 0], motion_list[:, 1], "b--",
             label="Yaw  Coarse process.      average = {:.2f}°".format(
                 np.average(motion_list[:, 1], axis=0)))

    plt.plot(motion_list[:, 0], yaw_Theorique[:, 1] + offsetYaw, "c-",
             label="Yaw  Theoretical.             average = {:.2f}°"
             .format(np.average(yaw_Theorique[:, 1] + offsetYaw, axis=0)))

    plt.plot(motion_list[:, 0], motion_list[:, 2], color='black', linestyle='-', linewidth=0.8,
             label="Pitch   Coarse process.    average = {:.2f}°"
             .format(np.average(motion_list[:, 2], axis=0)))
    plt.plot(motion_list[:, 0], pitch_Theorique[:, 1] + offsetPitch, "m-",
             label="Pitch  Theoretical.           average = {:.2f}°"
             .format(np.average(pitch_Theorique[:, 1] + offsetPitch, axis=0)))
    if False:
        plt.plot(motion_list[:, 0], motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], "g-",
                 label="Roll  Theoretical (Yaw Drone - Yaw Gimball)    average = {:.2f}°"
                 .format(np.abs(np.average(motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], axis=0))))
    plt.grid()
    plt.xlim(0, np.max(motion_list[:, 0]))
    # ---------------------------------------- Legendes ---------------------------------------------------------------
    ax.set_title(missionTitle, fontsize=8)
    ax.set_xlabel('Time line  [s]', fontsize=8)
    ax.set_ylabel('Angle [°]', fontsize=8)
    ax.legend()
    plt.show()


def Yaw_plot(motion_list,
             yaw_Theorique,
             offsetYaw,
             missionTitle,
             motion_list_fin_a, motion_list_fin_b,
             traceFin_a=False, traceFin_b=False):
    fig, ax = plt.subplots()
    plt.plot(motion_list[:, 0], motion_list[:, 1],
             color='black', linestyle='-', linewidth=1, marker='o', markersize=1, alpha=1,
             label="Yaw  Coarse process.       average = {:.2f}°"
             .format(np.average(motion_list[:, 1], axis=0)))

    plt.plot(motion_list[:, 0], yaw_Theorique[:, 1] + offsetYaw,
             color='magenta', linestyle='-', linewidth=1, marker='o', markersize=1, alpha=1,
             label="Yaw  Theoretical.              average = {:.2f}°"
             .format(np.average(yaw_Theorique[:, 1] + offsetYaw, axis=0)))

    if traceFin_a:
        plt.plot(motion_list[:, 0], motion_list[:, 1] - motion_list_fin_a[:, 1],
                 color='cyan', linestyle='-', linewidth=0.6,
                 label="Yaw  Refined process a.   average = {:.2f}°"
                 .format(np.abs(np.average(motion_list[:, 1] - motion_list_fin_a[:, 1], axis=0))))
    if traceFin_b:
        plt.plot(motion_list[:, 0], motion_list[:, 1] - motion_list_fin_b[:, 1],
                 color='blue', linestyle='-', linewidth=0.6,
                 label="Yaw  Refined process b.   average = {:.2f}°"
                 .format(np.average(motion_list[:, 1] - motion_list_fin_b[:, 1], axis=0)))
    plt.grid()
    plt.xlim(0, np.max(motion_list[:, 0]))
    ax.set_title(missionTitle, fontsize=8)
    ax.set_xlabel('Time line  [s]', fontsize=8)
    ax.set_ylabel('Angle [°]', fontsize=8)
    plt.legend()
    plt.show()


def Pitch_plot(motion_list,
               pitch_Theorique,
               offsetPitch,
               missionTitle,
               motion_list_fin_a, motion_list_fin_b,
               traceFin_a=False, traceFin_b=False):
    fig, ax = plt.subplots()
    plt.plot(motion_list[:, 0], motion_list[:, 2],
             color='black', linestyle='-', linewidth=1, marker='o', markersize=1, alpha=1,
             label="Pitch  Coarse process.       average = {:.2f}°"
             .format(np.average(motion_list[:, 2], axis=0)))

    plt.plot(motion_list[:, 0], pitch_Theorique[:, 1] + offsetPitch,
             color='magenta', linestyle='-', linewidth=1, marker='o', markersize=1, alpha=1,
             label="Pitch  Theoretical.             average = {:.2f}°"
             .format(np.average(pitch_Theorique[:, 1] + offsetPitch, axis=0)))

    if traceFin_a:
        plt.plot(motion_list[:, 0], motion_list[:, 2] - motion_list_fin_a[:, 2],
                 color='cyan', linestyle='-', linewidth=0.6,
                 label="Pitch  Refined process a.   average = {:.2f}°"
                 .format(np.average(motion_list[:, 2] - motion_list_fin_a[:, 2], axis=0)))
    if traceFin_b:
        plt.plot(motion_list[:, 0], motion_list[:, 2] - motion_list_fin_b[:, 2],
                 color='blue', linestyle='-', linewidth=0.6,
                 label="Pitch  Refined process b.   average = {:.2f}°"
                 .format(np.average(motion_list[:, 2] - motion_list_fin_b[:, 2], axis=0)))
    plt.grid()
    plt.xlim(0, np.max(motion_list[:, 0]))
    ax.set_title(missionTitle, fontsize=8)
    ax.set_xlabel('Time line  [s]', fontsize=8)
    ax.set_ylabel('Angle [°]', fontsize=8)
    plt.legend()
    plt.show()


def DeltaYawSynchro_Unsynchro_plot(motion_list, motion_list_drone, motion_list_cameraDJI, yaw_Theorique,
                                   offsetYaw, missionTitle, nameAngle='Yaw', ):
    plt.title(missionTitle + '  ' + nameAngle)
    plt.plot(motion_list[:, 0], motion_list[:, 1] - (motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1]),
             color='orange', linestyle=':', linewidth=1,
             label="delta imgNIR synchro   average |Delta|= {:.5f}°"
             .format(np.abs(np.average(
                 abs(motion_list[:, 1] - (motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1])),
                 axis=0))))
    plt.plot(motion_list[:, 0], motion_list[:, 1] - (yaw_Theorique[:, 1] + offsetYaw),
             color='blue', linestyle='-', linewidth=0.8,
             label="delta imgNIR  coarse - theoretical unsynchro  average |Delta|= {:.5f}°"
             .format(np.average(abs(motion_list[:, 1] - (yaw_Theorique[:, 1] + offsetYaw)), axis=0)))
    plt.grid()
    plt.legend()
    plt.show()


def DeltaAngle_plot(motion_list, angle_Theorique, offset, missionTitle, idx=1, nameAngle=''):
    plt.title(missionTitle + '  ' + nameAngle)
    plt.plot(motion_list[:, 0], motion_list[:, idx] - (angle_Theorique[:, 1] - offset),
             color='blue', linestyle='-', linewidth=0.8,
             label="delta imgNIR  coarse - theoretical  average |Delta|= {:.2f}°"
             .format(np.average(abs(motion_list[:, idx] - (angle_Theorique[:, 1] - offset)), axis=0)))
    plt.grid()
    plt.legend()
    plt.show()


def decomposeHomographyRefined_Plot(motion_list_fin_a, motion_list_fin_b,
                                    translat_fin_a, translat_fin_b,
                                    normal_fin_a, normal_fin_b,
                                    missionTitle):
    # Courbe d'evolution des angles fin solution a et b)
    print('Average refined yaw solution a = ', np.average(motion_list_fin_a[:, 1]),
          ' solution b = ', np.average(motion_list_fin_b[:, 1]))
    print('Average refined pitch solution a = ', np.average(motion_list_fin_a[:, 2]),
          ' solution b = ', np.average(motion_list_fin_b[:, 2]))
    print('Average refined roll solution a = ', np.average(motion_list_fin_a[:, 3]),
          ' solution b = ', np.average(motion_list_fin_b[:, 3]))
    plt.title(missionTitle)
    plt.plot(motion_list_fin_a[:, 1], "m-", label="pitch_a")
    plt.plot(motion_list_fin_b[:, 1], "m-.", label="pitch_b")
    plt.plot(motion_list_fin_a[:, 2], "r-", label="yaw_a")
    plt.plot(motion_list_fin_b[:, 2], "r-.", label="yaw_b")
    plt.plot(motion_list_fin_a[:, 3], "b-", label="roll_a")
    plt.plot(motion_list_fin_b[:, 3], "b-.", label="roll_b")
    plt.legend()
    plt.grid()
    plt.show()

    # Courbe d'evolution des translation fine solution a et b)
    plt.title(missionTitle)
    plt.plot(translat_fin_a[:, 1], "m-", label="tx_a")
    # plt.plot(translat_fin_b[:, 1], "m-.", label="tx_b")
    plt.plot(translat_fin_a[:, 2], "r-", label="ty_a")
    # plt.plot(translat_fin_b[:, 2], "r-.",label="ty_b")
    plt.plot(translat_fin_a[:, 3], "b-", label="tz_a")
    # plt.plot(translat_fin_b[:, 3], "b-.",label="tz_b")
    plt.legend()
    plt.grid()
    plt.show()

    # Courbe d'evolution des normale fine solution a et b)
    normal_fin_a = np.array(normal_fin_a)
    normal_fin_b = np.array(normal_fin_b)
    plt.title(missionTitle)
    plt.plot(normal_fin_a[:, 1], "m-", label="nx_a")
    # plt.plot(normal_fin_b[:, 1], "m-.", label="nx_b")
    plt.plot(normal_fin_a[:, 2], "r-", label="ny_a")
    # plt.plot(normal_fin_b[:, 2], "r-.", label="ny_b")
    plt.plot(abs(normal_fin_a[:, 3]), "b-", label="| nz_a |")
    # plt.plot(normal_fin_b[:, 3], "b-.", label="nz_b")
    plt.legend()
    plt.grid()
    plt.show()


def comparaisonPitchYaw_plot(motion_list,
                             motion_list_drone,
                             motion_list_cameraDJI,
                             missionTitle,
                             pitch_Theorique,
                             offsetPitch,
                             offsetYaw,
                             process='',
                             motion_refined=None):
    maxiIRrefined = (np.max(((motion_list[:, 1] + offsetYaw
                              - motion_refined[:, 1]),
                             -motion_list_drone[:, 1])),
                     np.max(((motion_list[:, 2]
                              - motion_refined[:, 2]),
                             (pitch_Theorique[:, 1] + offsetPitch))))
    miniIRrefined = (np.min(((motion_list[:, 1] + offsetYaw - motion_refined[:, 1]), -motion_list_drone[:, 1])),
                     np.min(((motion_list[:, 2] - motion_refined[:, 2]), (pitch_Theorique[:, 1] + offsetPitch))))

    _, (ax1, ax2) = plt.subplots(nrows=1, ncols=2)
    # Courbe de dispersion des angles   pitch(yaw)
    myTitleX = '. Offset : Yaw = ' + str(np.round(offsetYaw, 2)) + '°'
    myTitleY = '. Offset : Pitch =' + str(np.round(offsetPitch, 2)) + '°'
    disperPitchYaw_plot(ax1, offsetYaw - motion_list_drone[:, 1],
                        (pitch_Theorique[:, 1] + offsetPitch),
                        miniIRrefined, maxiIRrefined,
                        missionTitle, myTitleX, myTitleY, 'Theoretical', color='green')
    # Courbe de dispersion des angles de reclage de l'mage NIR sur l'image VIS  (pitch et yaw "refined")
    # ATTENTION: pour redresser l'image NIR on applique une rotation avec un pitch_NIR (resp yaw_NIR)
    # de signe opposé à celui du pitch (resp yaw) de la M20.
    disperPitchYaw_plot(ax2, motion_list[:, 1] - motion_refined[:, 1], motion_list[:, 2] - motion_refined[:, 2],
                        miniIRrefined, maxiIRrefined,
                        missionTitle, '', '', process, color='orange')

    plt.tight_layout()
    plt.show()


def disperPitchYaw_plot(ax, fx, fy, mini, maxi, missionTitle, myTitleX, myTitleY, spectralType, color='yellow'):
    avg = (np.average(fx, axis=0), np.average(fy, axis=0))
    std = (np.std(fx, axis=0), np.std(fy, axis=0))
    ax.plot(fx, fy,
            marker="o", markersize=6, alpha=0.4, mec=color, mfc=color, linestyle='')
    ax.set_xlim(mini[0] - 2., maxi[0] + 2.)
    ax.set_ylim(mini[1] - 2., maxi[1] + 2.)
    ax.plot(0., 0., "k+")
    ax.plot(avg[0], avg[1], "r+")
    myTitle = str(
        missionTitle + "\n" + spectralType + "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"
        .format(avg[0], std[0], avg[1], std[1]))
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel("YAW   %s" % myTitleX, fontsize=8)
    ax.set_ylabel("PITCH  %s" % myTitleY, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)


def DeltaYawPitchTeoriticalAndCoarse_plot(motion_list,
                                          motion_list_cameraDJI,
                                          motion_list_drone,
                                          pitch_Theorique,
                                          yaw_Theorique,
                                          offsetPitch,
                                          offsetYaw,
                                          missionTitle):
    plt.title(missionTitle)

    plt.plot(motion_list[:, 0], motion_list[:, 1] - (offsetYaw - yaw_Theorique[:, 1]), "b--",
             label="delta yaw_imgNIR      average = {:.2f}°"
             .format(np.average(motion_list[:, 1] - (offsetYaw - yaw_Theorique[:, 1]), axis=0)))
    plt.plot(motion_list[:, 0],
             motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], "g-",
             label="delta Roll_imgNIR     average = {:.2f}°"
             .format(np.abs(np.average(motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], axis=0))))
    plt.plot(motion_list[:, 0], motion_list[:, 2] - (pitch_Theorique[:, 1] + offsetPitch), "m--",
             label="delta pitch_imgNIR    average = {:.2f}°"
             .format(np.average(motion_list[:, 2] - (pitch_Theorique[:, 1] + offsetPitch), axis=0)))

    plt.grid()
    plt.legend()
    plt.show()
