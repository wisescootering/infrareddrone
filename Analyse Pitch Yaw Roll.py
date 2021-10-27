import numpy as np
import glob
import matplotlib.pyplot as plt
import utils_IRdrone as IRd
import irdrone.process as pr
from datetime import timedelta
from irdrone.utils import Style
import os
import os.path as osp




def plotYawPitchRollDroneAndCameraDJI(dir_mission, offsetPitchM20=0., offsetYawM20=0., offsetCapGeo=0.):
    motion_list, motion_list_drone, motion_list_cameraDJI = [], [], []
    image_dir = osp.join(dir_mission, "AerialPhotography")
    result_dir = osp.join(dir_mission, "ImgIRdrone")
    desync = timedelta(seconds=-1)
    missionTitle= dir_mission.split("/")[-1]

    motion_cache = osp.join(result_dir, "motion_summary_vs_drone_dates.npy")
    count1 = 0
    count2 = 0

    if not osp.exists(motion_cache):
        for ipath in glob.glob(osp.join(image_dir, "*.DNG")):
            try:
                count1 += 1
                mpath = glob.glob(osp.join(result_dir, osp.basename(ipath)[:-4]) + "*.npy")[0]
                img = pr.Image(ipath)
                finfo = img.flight_info
                date = img.date
                # roll, pitch & yaw   drone    (NIR camera)
                mouvement_drone = [date, finfo["Flight Roll"], finfo["Flight Pitch"], finfo["Flight Yaw"]]
                motion_list_drone.append(mouvement_drone)
                # roll, pitch & yaw   gimbal  (VIS camera)
                mouvement_cameraDJI = [date, finfo["Gimbal Roll"], finfo["Gimbal Pitch"], finfo["Gimbal Yaw"]]
                motion_list_cameraDJI.append(mouvement_cameraDJI)
                #  yaw & pitch  image NIR
                mouvement = np.load(mpath, allow_pickle=True).item()
                motion_list.append([date, mouvement["yaw"], mouvement["pitch"]])

                print(Style.CYAN + img.name + Style.RESET)

            except:
                count2 += 1
                continue

        motion_list = np.array(motion_list)
        motion_list_drone = np.array(motion_list_drone)
        motion_list_cameraDJI = np.array(motion_list_cameraDJI)
        np.save(motion_cache[:-4], {"motion_list": motion_list,
                                    "motion_list_drone": motion_list_drone,
                                    "motion_list_cameraDJI": motion_list_cameraDJI
                                    })
        txt = "images retenues" + str(count1 - count2) + "   images rejettées  " + str(count2)
        print(Style.CYAN + txt + Style.RESET)

    else:
        print(Style.YELLOW + "Warning : utilisation du cache" + Style.RESET)
        m_cache = np.load(motion_cache, allow_pickle=True).item()
        motion_list = m_cache["motion_list"]
        motion_list_drone = m_cache["motion_list_drone"]
        motion_list_cameraDJI = m_cache["motion_list_cameraDJI"]

    avgNIR = (np.average(motion_list[:, 1], axis=0), np.average(motion_list[:, 2], axis=0))
    stdNIR = (np.std(motion_list[:, 1], axis=0), np.std(motion_list[:, 2], axis=0))
    avgM20 = (np.average(motion_list_drone[:, 1], axis=0), np.average(motion_list_drone[:, 2], axis=0))
    stdM20 = (np.std(motion_list_drone[:, 1], axis=0), np.std(motion_list_drone[:, 2], axis=0))
    avgDJI = (np.average(motion_list_cameraDJI[:, 1], axis=0), np.average(motion_list_cameraDJI[:, 2]+ 90., axis=0))
    stdDJI = (np.std(motion_list_cameraDJI[:, 1], axis=0), np.std(motion_list_cameraDJI[:, 2]+ 90., axis=0))
    offsetYawM20=np.abs(avgNIR[0]+avgM20[0])
    offsetPitchM20=np.abs(avgNIR[1]+avgM20[1])
    print('offsetPitchM20 = %.3f °   offsetYawM20 = %.3f ° '%(offsetPitchM20, offsetYawM20))

    dates = motion_list[:, 0]

    plt.title(missionTitle + "    Delay {}".format(float(desync.total_seconds())))

    plt.plot(dates, motion_list[:, 1], "b--", label="yaw_imgNIR")
    plt.plot(dates, motion_list[:, 2], "r--", label="pitch_imgNIR")

    plt.plot(dates + desync, -motion_list_drone[:, 1] + offsetYawM20, "c-",
             label="yaw_M20   (roll_drone)  offset = {:.2f}°".format(offsetYawM20))
    plt.plot(dates + desync, -motion_list_drone[:, 2] + offsetPitchM20, "m-",
             label="pitch_M20 (pitch_drone) offset = {:.2f}°".format(offsetPitchM20))
    plt.plot(dates + desync, - motion_list_drone[:, 3] + offsetCapGeo, "g-",
             label="roll_M20  (yaw_drone)")

    plt.plot(dates + desync, motion_list_cameraDJI[:, 1], "m-.",
             label="yaw_DJIcamera   (roll_gimbal)")
    plt.plot(dates + desync,  motion_list_cameraDJI[:, 2]+ 90., "c-.",
             label="pitch_DJIcamera (pitch_gimbal)")
    plt.plot(dates + desync, - motion_list_cameraDJI[:, 3] + offsetCapGeo, "g-.",
             label="roll_DJIcamera     (yaw_gimbal)")



    plt.grid()
    plt.legend()
    plt.show()
    if False:
        # Courbe d'evolution des angles de reclage de l'mage NIR sur l'image VIS  (pitch et yaw "grossier")
        motion_list = np.array(motion_list)
        plt.title(missionTitle)
        plt.plot(motion_list[:, 1], label="image NIR yaw")
        plt.plot(motion_list[:, 2], label="image NIR pitch")
        plt.legend()
        plt.show()

    if True:
        # Courbe de dispersion des angles de reclage de l'mage NIR sur l'image VIS  (pitch et yaw "grossier")
        # ATTENTION: si le pitch (resp yaw) de la M20 est négatif, alors pour redresser l'image NIR
        # on applique une rotation avec un pitch_NIR (resp yaw_NIR)  positif.
        plt.plot(motion_list[:, 1], motion_list[:, 2], marker="o", markersize=6, alpha=0.4, mfc='orange', linestyle='')
        plt.xlim(-20, 20)
        plt.ylim(-20, 20)
        plt.plot(0., 0., "k+")
        plt.plot(avgNIR[0], avgNIR[1], "r+")
        plt.title(missionTitle+"\n images NIR "
                               "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"
                  .format(avgNIR[0], stdNIR[0], avgNIR[1], stdNIR[1])
                  )
        plt.xlabel("NIR yaw")
        plt.ylabel("NIR pitch")
        plt.grid(True)
        plt.show()
        plt.close()

    if True:
        # Courbe de dispersion des angles de la caméra NIR SJCam M20   pitch(yaw)
        plt.plot(motion_list_drone[:, 1], motion_list_drone[:, 2],
                 marker="o", markersize=6, alpha=0.4, mfc='green', linestyle='')
        plt.xlim(-20, 20)
        plt.ylim(-20, 20)
        plt.plot(0., 0., "k+")
        plt.plot(avgM20[0], avgM20[1], "r+")
        plt.title(missionTitle+"\n Camera NIR "
                               "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"
                  .format(avgM20[0], stdM20[0], avgM20[1], stdM20[1])
                  )
        plt.xlabel("Camera NIR yaw")
        plt.ylabel("Camera NIR pitch")
        plt.grid(True)
        plt.show()
        plt.close()


    if True:
        # Courbe de dispersion des angles de la caméra VIS DJI Mavic Air.2   pitch(yaw)
        plt.plot(motion_list_cameraDJI[:, 1], motion_list_cameraDJI[:, 2]+ 90.,
                 marker="o", markersize=6, alpha=0.4, mfc='cyan', linestyle='')
        plt.xlim(-20, 20)
        plt.ylim(-20, 20)
        plt.plot(0., 0., "k+")
        plt.plot(avgDJI[0], avgDJI[1], "r+")
        plt.title(missionTitle+"\n Camera VIS "
                               "\n Average yaw {:.2f}° +/- {:.2f}°    | pitch {:.2f}°  +/-{:.2f}°"
                  .format(avgDJI[0], stdDJI[0], avgDJI[1], stdDJI[1])
                  )
        plt.xlabel("Camera VIS yaw")
        plt.ylabel("Camera VIS pitch")
        plt.grid(True)
        plt.show()
        plt.close()




if __name__ == "__main__":
    versionIRdrone = '1.05'  # 26 october 2021
    # ----------------------------------------------------
    # 0 > Choix interactif de la mission
    #
    print(Style.CYAN + "File browser")
    dirMission = os.path.dirname(IRd.loadFileGUI(mute=True))
    print(Style.CYAN + dirMission + Style.RESET)
    # ----------------------------------------------------
    # 1 > Trace les angles Roll, Pitch et Yaw  (roulis, tangage & lacet)
    #     pour le drone, le gimbal et l'image NIR
    #

    plotYawPitchRollDroneAndCameraDJI(dirMission, offsetPitchM20=7.70, offsetYawM20=1., offsetCapGeo=170.)
