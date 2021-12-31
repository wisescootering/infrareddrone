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
    filepath = dirSaveFig  +'\\Topo'+ '\\Flight profil IRdrone'
    if dirSaveFig == None:
        pass
    else:
        plt.savefig(filepath, dpi=75, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.GREEN + 'Save flight profil in %s' % filepath + Style.RESET)
    if not mute:
        print(Style.YELLOW + 'Look your Drone Flight profil >>>>' + Style.RESET)
        plt.show()
    plt.close()


def Yaw_plot(motion_list,
               motion_list_cameraDJI,
               motion_list_drone,
               yaw_Theorique,
               offsetYaw,
               missionTitle,
               motion_list_fin_a, motion_list_fin_b,
               traceFin_a=False, traceFin_b=False):

    plt.title(missionTitle )
    plt.plot(motion_list[:, 0], motion_list[:, 1],
             color='black', linestyle='-', linewidth=1,
             label="yaw_imgNIR       (coarse process)    average = {:.2f}°"
             .format(np.average(motion_list[:, 1], axis=0)))

    plt.plot(motion_list[:, 0], motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1] ,
             color='orange', linestyle=':', linewidth=1,
             label="Theoretical yaw_imgNIR synchro   average = {:.2f}°"
             .format(np.abs(-np.average(motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1] , axis=0))))

    plt.plot(motion_list[:, 0], yaw_Theorique[:, 1] + offsetYaw,
             color='magenta', linestyle='-', linewidth=1,
             label="Theoretical yaw_imgNIR  unsynchro  average = {:.2f}°"
             .format(np.abs(np.average(yaw_Theorique[:, 1] + offsetYaw, axis=0))))

    if traceFin_a:
        plt.plot(motion_list[:, 0], motion_list[:, 1] - motion_list_fin_a[:, 1],
                 color='cyan', linestyle='-', linewidth=0.6,
                 label="yaw_imgNIR       (refined process a)   average = {:.2f}°"
                 .format(np.abs(np.average(motion_list[:, 1] - motion_list_fin_a[:, 1], axis=0))))
    if traceFin_b:
        plt.plot(motion_list[:, 0], motion_list[:, 1] - motion_list_fin_b[:, 1],
                 color='blue', linestyle='-', linewidth=0.6,
                 label="yaw_imgNIR       (refined process b)   average = {:.2f}°"
                 .format(np.abs(np.average(motion_list[:, 1] - motion_list_fin_b[:, 1], axis=0))))
    plt.grid()
    plt.legend()
    plt.show()



def Pitch_plot(motion_list,
               motion_list_cameraDJI,
               motion_list_drone,
               pitch_Theorique,
               offsetPitch,
               missionTitle,
               motion_list_fin_a, motion_list_fin_b,
               traceFin_a=False, traceFin_b=False):

    plt.title(missionTitle )
    plt.plot(motion_list[:, 0], motion_list[:, 2],
             color='black', linestyle=' ', linewidth=1, marker='o', markersize=4, alpha=0.4,
             label="pitch_imgNIR       (coarse process)    average = {:.2f}°"
             .format(np.average(motion_list[:, 2], axis=0)))

    plt.plot(motion_list[:, 0], motion_list_cameraDJI[:, 2] + 90. - motion_list_drone[:, 2] - offsetPitch,
             color='orange', linestyle=':', linewidth=1, marker='o', markersize=6, alpha=0.4,
             label="Theoretical pitch_imgNIR synchro   average = {:.2f}°"
             .format(np.abs(-np.average(motion_list_cameraDJI[:, 2] + 90.
                                        - motion_list_drone[:, 2]
                                        - offsetPitch, axis=0))))

    plt.plot(motion_list[:, 0], pitch_Theorique[:, 1] - offsetPitch,
             color='magenta', linestyle='-', linewidth=1, marker='o', markersize=3, alpha=0.4,
             label="Theoretical pitch_imgNIR  unsynchro  average = {:.2f}°"
             .format(np.abs(np.average(pitch_Theorique[:, 1] - offsetPitch, axis=0))))

    if traceFin_a:
        plt.plot(motion_list[:, 0], motion_list[:, 2] - motion_list_fin_a[:, 2],
                 color='cyan', linestyle='-', linewidth=0.6,
                 label="pitch_imgNIR       (refined process a)   average = {:.2f}°"
                 .format(np.abs(np.average(motion_list[:, 2] - motion_list_fin_a[:, 2], axis=0))))
    if traceFin_b:
        plt.plot(motion_list[:, 0], motion_list[:, 2] - motion_list_fin_b[:, 2],
                 color='blue', linestyle='-', linewidth=0.6,
                 label="pitch_imgNIR       (refined process b)   average = {:.2f}°"
                 .format(np.abs(np.average(motion_list[:, 2] - motion_list_fin_b[:, 2], axis=0))))
    plt.grid()
    plt.legend()
    plt.show()


def YawPitchTeoriticalAndCoarse_plot(motion_list,
                                     motion_list_cameraDJI,
                                     motion_list_drone,
                                     pitch_Theorique,
                                     yaw_Theorique,
                                     offsetPitch,
                                     offsetYaw,
                                     missionTitle):
    plt.title(missionTitle)
    plt.plot(motion_list[:, 0], motion_list[:, 1], "b--",
             label="yaw_imgNIR       (coarse process)    average = {:.2f}°".format(
                 np.average(motion_list[:, 1], axis=0)))
    plt.plot(motion_list[:, 0], motion_list_cameraDJI[:, 1] + (offsetYaw + yaw_Theorique[:, 1]), "c-",
             label="Theoretical yaw_imgNIR unsynchro  average = {:.2f}°"
             .format(np.abs(np.average(motion_list_cameraDJI[:, 1] + (offsetYaw + yaw_Theorique[:, 1]), axis=0))))
    plt.plot(motion_list[:, 0], motion_list[:, 2], color='black', linestyle='-', linewidth=0.8,
             label="pitch_imgNIR       (coarse process)    average = {:.2f}°"
             .format(np.average(motion_list[:, 2], axis=0)))
    plt.plot(motion_list[:, 0], pitch_Theorique[:, 1] - offsetPitch, "m-",
             label="Theoretical pitch_imgNIR  unsynchro  average = {:.2f}°"
             .format(np.abs(np.average(pitch_Theorique[:, 1] - offsetPitch, axis=0))))
    plt.plot(motion_list[:, 0], motion_list_drone[:, 3] - motion_list_cameraDJI[:, 3], "g-",
             label="Theoritical Roll_imgNIR   (Yaw Drone - Yaw Gimball)    average = {:.2f}°"
             .format(np.abs(np.average( motion_list_drone[:, 3]-motion_list_cameraDJI[:, 3], axis=0))))
    plt.grid()
    plt.legend()
    plt.show()



def DeltaYawSynchro_Unsynchro_plot(motion_list, motion_list_drone, motion_list_cameraDJI, yaw_Theorique,
                                   offsetYaw, missionTitle, nameAngle='Yaw', ):
    plt.title(missionTitle + '  ' + nameAngle)
    plt.plot(motion_list[:, 0], motion_list[:, 1]-(motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1]),
             color='orange', linestyle=':', linewidth=1,
             label="delta imgNIR synchro   average |Delta|= {:.5f}°"
             .format(np.abs(np.average(abs(motion_list[:, 1]-(motion_list_cameraDJI[:, 1] + offsetYaw - motion_list_drone[:, 1])), axis=0))))
    plt.plot(motion_list[:, 0], motion_list[:, 1] - (yaw_Theorique[:, 1] + offsetYaw),
             color='blue', linestyle='-', linewidth=0.8,
             label="delta imgNIR  coarse - theoritical unsynchro  average |Delta|= {:.5f}°"
             .format(np.average(abs(motion_list[:, 1] - (yaw_Theorique[:, 1] + offsetYaw)), axis=0)))
    plt.grid()
    plt.legend()
    plt.show()

def DeltaAngle_plot(motion_list, angle_Theorique, offset,  missionTitle,  idx=1, nameAngle=''):
    plt.title(missionTitle +'  ' + nameAngle)
    plt.plot(motion_list[:, 0], motion_list[:, idx] - (angle_Theorique[:, 1] - offset),
             color='blue', linestyle='-', linewidth=0.8,
             label="delta imgNIR  coarse - theoritical  average |Delta|= {:.2f}°"
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
                                    pitch_Theorique,
                                    offsetPitch,
                                    offsetYaw,
                                    process='',
                                    motion_refined=None):
    maxiIRrefined = (np.max(((motion_list[:, 1] + offsetYaw - motion_refined[:, 1]), -motion_list_drone[:, 1])),
                     np.max(((motion_list[:, 2] - motion_refined[:, 2]), (pitch_Theorique[:, 1] - offsetPitch))))
    miniIRrefined = (np.min(((motion_list[:, 1] + offsetYaw - motion_refined[:, 1]), -motion_list_drone[:, 1])),
                     np.min(((motion_list[:, 2] - motion_refined[:, 2]), (pitch_Theorique[:, 1] - offsetPitch))))

    _, (ax1, ax2) = plt.subplots(nrows=1, ncols=2)
    # Courbe de dispersion des angles   pitch(yaw)
    myTitleX= '. Offset : Yaw = ' + str(np.round(offsetYaw,2)) + '°'
    myTitleY = '. Offset : Pitch =' + str( np.round(offsetPitch, 2)) + '°'
    disperPitchYaw_plot(ax1, offsetYaw - motion_list_drone[:, 1],
                        (pitch_Theorique[:, 1] - offsetPitch),
                        miniIRrefined, maxiIRrefined,
                        missionTitle, myTitleX, myTitleY, 'Theoritical unsynchro', color='green')
    # Courbe de dispersion des angles de reclage de l'mage NIR sur l'image VIS  (pitch et yaw "refined")
    # ATTENTION: pour redresser l'image NIR on applique une rotation avec un pitch_NIR (resp yaw_NIR)
    # de signe opposé à celui du pitch (resp yaw) de la M20.
    disperPitchYaw_plot(ax2, motion_list[:, 1] - motion_refined[:, 1], motion_list[:, 2] - motion_refined[:, 2],
                        miniIRrefined, maxiIRrefined,
                        missionTitle, '', '', process, color='orange')

    plt.tight_layout()
    plt.show()


def disperPitchYaw_plot(ax, fx, fy,  mini, maxi, missionTitle, myTitleX, myTitleY, spectralType, color='yellow'):
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
    ax.set_xlabel("YAW   %s" % myTitleX, fontsize=8)
    ax.set_ylabel("PITCH  %s" % myTitleY, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)


def Fourier_plot(signal, title1='', title2='', color='p', montreSignal=False):
    signal = signal - np.average(signal)           # soustration de la moyenne  (elimination du terme constant)
    signal = signal / np.max(signal)               # normalisation du signal entre -1 et +1
    nombre_image = len(signal)  #
    N = nombre_image // 2             # echantillonnage du signal pour la fft
    timeLapse_Img = 2                 # Timelapse de la caméra VIS du drone DJI.   en s
    t = np.linspace(0.0, timeLapse_Img * nombre_image, nombre_image, endpoint=False)  # axe du temps

    # Représentation graphique du signal
    if montreSignal:
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
    x_f = np.linspace(0.0, 1 / 2 * 1 / timeLapse_Img, N, endpoint=False)        # axe des fréquences

    # Représentation graphique de la transformée (discrète) du signal
    fig, ax = plt.subplots()
    myTitle = 'Analyse spectrale du ' + title1
    ax.set_title(myTitle, fontsize=8)
    ax.set_xlabel('Fréquence  [Hz]', fontsize=8)
    myYlabel = 'FFT(' + title1 + ')  '
    ax.set_ylabel(myYlabel, fontsize=8)
    ax.grid(color='gray', linestyle='-', linewidth=0.5)
    plt.plot(x_f, 2 / N * np.abs(Fourier[: N]), color=color, linestyle='-',  linewidth=0.5)
    plt.fill_between(x_f, [0.]*len(x_f), 2 / N * np.abs(Fourier[: N]), alpha=0.2, color='gray')
    plt.plot((1 / timeLapse_Img) * np.argmax(np.abs(Fourier[:])) / (nombre_image),
             timeLapse_Img / N * np.max(np.abs(Fourier[:])),
             marker="o", markersize=6, alpha=0.5, mec=color, mfc=color, linestyle='', linewidth=0.6)
    trans_offset = mtrans.offset_copy(ax.transData, fig=fig,
                                      x=0.08, y=-0.10, units='inches')
    plt.text((1 / timeLapse_Img) * np.argmax(np.abs(Fourier[:])) / (nombre_image),
             timeLapse_Img / N * np.max(np.abs(Fourier[:])),
             '%.3f Hz' % (fondamentale), transform=trans_offset)
    plt.show()






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
        plt.plot(motion_list[:, 0], motion_list[:, 2] - (pitch_Theorique[:, 1] - offsetPitch), "m--",
                 label="delta pitch_imgNIR    average = {:.2f}°"
                 .format(np.average(motion_list[:, 2] - (pitch_Theorique[:, 1] - offsetPitch), axis=0)))

        plt.grid()
        plt.legend()
        plt.show()