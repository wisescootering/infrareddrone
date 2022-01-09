import cv2
import numpy as np
import irdrone.utils as ut
import irdrone.process as pr
import matplotlib.pyplot as plt
import os
from datetime import datetime, timedelta
from synchronization import date_from_path_sjcam
from irdrone import imagepipe
import copy
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from scipy.optimize import minimize
osp = os.path


ARUCO_DICT = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
    "DICT_7X7_100": cv2.aruco.DICT_7X7_100,
    "DICT_7X7_250": cv2.aruco.DICT_7X7_250,
    "DICT_7X7_1000": cv2.aruco.DICT_7X7_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
    "DICT_APRILTAG_16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "DICT_APRILTAG_25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "DICT_APRILTAG_36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "DICT_APRILTAG_36h11": cv2.aruco.DICT_APRILTAG_36h11
}
ARUCO_SELECT = cv2.aruco.Dictionary_get(ARUCO_DICT["DICT_4X4_50"])


def synchronization_aruco_rotation(
        folder="D:\Synchro_data",
        out_dir  = None,
        camera_definition=[("*.RAW", "M20_RAW") , ("*.DNG", "DJI_RAW")],
        delta=0.,
        manual=False
    ):
    if out_dir is None:
        out_dir = osp.join(folder, "_synchro_check")
    if not osp.isdir(out_dir):
        os.mkdir(out_dir)
    synch_dict_path = osp.join(out_dir, "rotations_analyzis.npy")
    if osp.isfile(synch_dict_path):
        sync_dict = np.load(synch_dict_path, allow_pickle=True).item()
    else:
        sync_dict = dict()
        for extension, cam in camera_definition:
            cal = ut.cameracalibration(camera=cam)
            rot_list = []
            for index, img_pth in enumerate(ut.imagepath(imgname=extension, dirname=folder)):
                date = pr.Image(img_pth).date
                img_name = ("_%04d_"%(index)) + osp.basename(img_pth)[:-4]
                out_file = osp.join(out_dir, img_name + ".jpg")
                if not osp.isfile(out_file):
                    img = pr.Image(img_pth)
                    img.save(out_file)
                    img_thmb = cv2.resize(img.data, (640, 480))
                    pr.Image(img_thmb).save(osp.join(out_dir, "_thumb_" + img_name + ".jpg"))
                else:
                    img = pr.Image(out_file)
                detection_file = osp.join(out_dir, "_detection" + img_name + ".npy")
                if osp.isfile(detection_file):
                    results = np.load(detection_file, allow_pickle=True).item()
                    angle = results["angle"]
                else:
                    out = aruco_detection(
                        img.data,
                        calibration=cal, show=False,
                        debug_fig=osp.join(out_dir, "_detection" + img_name + ".jpg"),
                        title="{} {}  ".format(cam, date)
                    )
                    print(out)
                    angle, corners = out
                    if angle is None:
                        continue
                    results = {
                        "angle" : angle,
                        "corners": corners,
                    }
                    np.save(detection_file[:-4], results, allow_pickle=True)
                if angle is not None:
                    rot_list.append({"date": date, "path": img_pth, "angle": angle})
            sync_dict[cam] = rot_list
        np.save(synch_dict_path[:-4], sync_dict, allow_pickle=True)

    # ===================================================================================================
    #
    #   PARTIE AJOUTEE POUR RECUPERER LES TEMPS ET ANGLES DANS MON FORMAT
    #

    #print("synch_dict_path   \n", synch_dict_path,"\n","synch_dict   \n", sync_dict)
    x_A,y_A,x_B,y_B = [],[],[],[]
    #print(sync_dict['DJI_RAW'][0]['date'])
    for cle,valeur in sync_dict.items():
        for k in range(len(valeur)):
            print(cle, " Date : ", valeur[k]['date'], "   Angle : ", valeur[k]['angle'])
            dt = (valeur[k]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds
            if cle =="DJI_RAW":
                x_A.append(dt)
                y_A.append(valeur[k]['angle'])
            else:
                x_B.append(dt)
                y_B.append(valeur[k]['angle'])

    # ========================================================================================================

    # for cam, delta in  [("DJI_RAW" , timedelta(seconds=0.)), ("M20_RAW", timedelta(seconds=196.5))]:
    sig_list = []
    for indx, (cam, _delta, roll_offset) in enumerate([("DJI_RAW", timedelta(seconds=delta), 0.), ("M20_RAW", timedelta(seconds=0.), 1.)]):
        cam_dat = np.array([[el["date"],  el["angle"]] for el in sync_dict[cam]])
        angle_list = cam_dat[:, 1]

        #  JE NE COMPRENDS PAS LE 270°   ????
        #  A VUE DE NEZ ON A [0°, 180°] <=> [0°, 180°] ET [-180°, 0°] <=>> [180°, 360°]

        modulo = 360*(np.abs(angle_list[1:]-angle_list[:-1])>270.) * (-np.sign(angle_list[1:]-angle_list[:-1]))
        angle_list[1:] += np.cumsum(modulo)+roll_offset
        # plt.plot(cam_dat[:, 0]+delta, angle_list, "-o", label="{} - delta {}".format(cam, float(delta.seconds + delta.microseconds/1E6)))
        sig_list.append(imagepipe.Signal(cam_dat[:, 0]+_delta, angle_list, label="{}".format(cam), color=["k--.", "c-o"][indx]))

    if manual:
        signalplotshift(sig_list, init_delta=delta)

    return x_A, y_A, x_B, y_B


def aruco_detection(image, arucoDict=ARUCO_SELECT, calibration=None, show=False, debug_fig=None, title=""):
    arucoParams = cv2.aruco.DetectorParameters_create()
    (corners, ids, rejected) = cv2.aruco.detectMarkers(image, arucoDict,
                                                       parameters=arucoParams)
    if len(corners) > 0:
        # flatten the ArUco IDs list
        ids = ids.flatten()
        # rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 0.1, cal_dji["mtx"], None)
        rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(corners, 1., calibration["mtx"], None)
        rvec = np.array(rvecs[0])
        print(np.rad2deg(rvec))

        # print(rvecs[0])
        # loop over the detected ArUCo corners
        for (markerCorner, markerID) in zip(corners, ids):

            # extract the marker corners (which are always returned in
            # top-left, top-right, bottom-right, and bottom-left order)
            corners = markerCorner.reshape((4, 2))
            (topLeft, topRight, bottomRight, bottomLeft) = corners

            principal_axis_ = (topLeft - bottomLeft)+(topRight-bottomRight)
            principal_axis = principal_axis_/np.sqrt(np.sum(principal_axis_**2))
            angle = np.rad2deg(np.arctan2(principal_axis[1], principal_axis[0]))
            print("angle", angle, "principal axis", principal_axis)
            if show or debug_fig is not None:
                # convert each of the (x, y)-coordinate pairs to integers
                topRight = (int(topRight[0]), int(topRight[1]))
                bottomRight = (int(bottomRight[0]), int(bottomRight[1]))
                bottomLeft = (int(bottomLeft[0]), int(bottomLeft[1]))
                topLeft = (int(topLeft[0]), int(topLeft[1]))

                # draw the bounding box of the ArUCo detection
                cv2.line(image, topLeft, topRight, (0, 255, 0), 2)
                cv2.line(image, topRight, bottomRight, (0, 255, 0), 2)
                cv2.line(image, bottomRight, bottomLeft, (0, 255, 0), 2)
                cv2.line(image, bottomLeft, topLeft, (0, 255, 0), 2)




                # compute and draw the center (x, y)-coordinates of the ArUco
                # marker
                cX = int((topLeft[0] + bottomRight[0]) / 2.0)
                cY = int((topLeft[1] + bottomRight[1]) / 2.0)


                cv2.line(image, (cX, cY), (int(cX+principal_axis_[0]), int(cY+principal_axis_[1])), (0, 255, 0), 2)
                cv2.circle(image, (cX, cY), 4, (0, 0, 255), -1)
                # draw the ArUco marker ID on the image
                cv2.putText(image, str(markerID),
                            (topLeft[0], topLeft[1] - 15), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 0), 2)
                # print("[INFO] ArUco marker ID: {}".format(markerID))
                plt.imshow(image)
                plt.title(title + ("angle {}".format(angle)))
                if debug_fig is not None:
                    plt.savefig(debug_fig)
                else:
                    plt.show()
                plt.close()
                return angle, corners
            else:
                return angle, corners
        print("detection failed")
    return None, None


def aruco_chart_generator(arucoDict=ARUCO_SELECT, out=None): #"ARCUO.png"
    tag_size = 1000
    tag = np.zeros((tag_size, tag_size, 1), dtype="uint8")
    cv2.aruco.drawMarker(arucoDict, 0, tag_size, tag, 1)
    if out is not None:
        cv2.imwrite(out, tag)
    return tag


def aruco_test_image():
    aruco_tag  = aruco_chart_generator()
    img_size  = (2000, 2000)
    image = 255*np.ones((img_size[0], img_size[1], 3))

    # image = 255*np.ones((1000, 1000, 3))
    x_start, y_start = 600, 500
    image[y_start:y_start+aruco_tag.shape[0], x_start:x_start+aruco_tag.shape[1], :] = aruco_tag[::-1, ::-1]

    theta = np.deg2rad(30.)
    ho = np.array([
        [np.cos(theta), -np.sin(theta), 0.],
        [np.sin(theta), np.cos(theta), 0.],
        [0. ,0., 1.],
    ])
    tr = np.eye(3)
    tr[0, 2] = x_start
    tr[1, 2] = y_start
    ho = np.dot(np.dot(tr, ho), np.linalg.inv(tr))
    image = image.astype(np.uint8)

    # plt.imshow(image)
    # plt.show()
    image = cv2.warpPerspective(image, ho, (image.shape[1], image.shape[0]))
    # plt.imshow(image)
    # plt.show()
    # cv2.imshow("ArUCo Tag", image)
    # cv2.waitKey(0)
    return image


def signalplotshift(sigList, init_delta=0.):
    class Shift(imagepipe.ProcessBlock):
        def apply(self, sig, shift, **kwargs):
            out = copy.deepcopy(sig)
            out.x = sig.x + timedelta(seconds=shift)
            out.color ="orange"
            out.label = sig.label + " delay: {:.1f}s".format(shift+init_delta)
            return out

    AMPLI = Shift(
        "Amplification",
        vrange=[
            (-0.,280., 0.),
        ],
        mode = [imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    )

    ip = imagepipe.ImagePipe(
        sigList,
        sliders=[AMPLI, ])
    ip.gui()


def domaine_interpol(x):
    x_interpol = np.linspace(min(x), max(x), num=9*len(x), endpoint=True)
    return x_interpol


def interpol_func(x, y, option='linear'):
    f = interp1d(x, y, kind=option)
    return f


def cost_function(shift_x):
    # récupération des deux courbes à supperposer
    # JE NE SAIS PAS PRENDRE x_A, y_A, x_B, y_B  COMME ARGUMENT CAR ...
    # LORS DE L'APPEL DE minimize
    x_A, y_A, x_B, y_B = \
        synchronization_aruco_rotation \
                (
                folder=r"C:\Air-Mission\FLY-20211109-Blassac-1ms\Synchro Horloges",
                camera_definition=[("DJI*.JPG", "DJI_RAW"), ("2021*.JPG", "M20_RAW")],
                delta=3600.  # ordre de grandeur de l'écart initial (si connu)
            )
    # construct interpolator of f_A and f_B
    f_A = interpol_func(x_A, y_A, option='linear')
    f_B = interpol_func(x_B, y_B, option='linear')
    cost_function = 0.
    for i in range(len(x_A)):
        if x_B[0] <= x_A[i] + shift_x <= x_B[-1]:
            cost_function = cost_function + (f_A(x_A[i]) - f_B(x_A[i] + shift_x)) ** 2
        elif x_B[0] > x_A[i] + shift_x:
            cost_function = cost_function + (f_A(x_A[i]) - f_B(x_B[0])) ** 2  # assume f_B equal zero before x_B[O]
        else:   # x_B[-1] < x_A[i] + shift_x
            cost_function = cost_function + (f_A(x_A[i]) - f_B(x_B[-1])) ** 2
    #cost_function = np.sqrt(cost_function/np.average(x_A)**2)/len(x_A)
    cost_function = np.sqrt(cost_function) / len(x_A)
    return cost_function


def fitPlot(x_A, y_A, x_B, y_B, res):
    # construction des interpolateurs
    x_fit = [x_B[i] - res.x for i in range(1, len(x_B))]
    f_A = interpol_func(x_A, y_A, option='linear')
    f_B = interpol_func(x_B, y_B, option='linear')
    plt.plot(x_A, y_A, 'o:', x_B, y_B, 'o:', x_fit, f_B([x_B[i] for i in range(1, len(x_B))]), 'o-')
    x_B_interp = domaine_interpol(x_B[0:])
    plt.plot(x_B_interp, f_B(x_B_interp), '--')
    plt.legend(['data_A', 'data_B', ' B fit'], loc='best')
    plt.grid()
    plt.title(' Time shift  = %.5f  s' % (res.x))
    plt.show()


if __name__ == "__main__":
    x_A, y_A, x_B, y_B = \
        synchronization_aruco_rotation\
        (
        folder=r"C:\Air-Mission\FLY-20211109-Blassac-1ms\Synchro Horloges",
        camera_definition=[("DJI*.JPG", "DJI_RAW"), ("2021*.JPG", "M20_RAW")],
        delta=3600.,  # ordre de grandeur de l'écart initial (si connu)
        manual = False
        )
    # --calcul du shift initial (basé sur la distance des pics des deux courbes)
    n_A = np.argmax(y_A)
    n_B = np.argmax(y_B)
    shift_0 = x_B[n_B] - x_A[n_A]    # NE MARCHE PAS BIEN  CAR TROP DE MAX !
    shift_0 = 3824                   # ON  AIDE UN PEU ...
    # ------- optimisation
    #
    # JE NE SAIS PAS COMMENT ENVOYER x_A, y_A, x_B, y_B   A cost_function  QUI NE PRENDS QUE
    # L'ARGUMENT A MODIFIER POUR MINIMISER LE COUT  ?????
    # D'OU L'APPEL A synchronization_aruco_rotation AUSSI DANS cost_function   ...
    # CE QUI EST VRAIMENT CRADO !!!
    #
    res = minimize(cost_function, shift_0, method='Nelder-Mead', options={'xatol': 10 ** -8, 'disp': True})

    print('Optimum initial   Time shift  = %.5f s.  Coût %.5f \n'
          'Optimum final     Time shift  = %.5f s.  Coût %.5f '
          % (shift_0, cost_function(shift_0), res.x, cost_function(res.x)))

    # -------   Visualisation des résultats
    fitPlot(x_A, y_A, x_B, y_B, res)

    x_A, y_A, x_B, y_B = \
        synchronization_aruco_rotation \
                (
                folder=r"C:\Air-Mission\FLY-20211109-Blassac-1ms\Synchro Horloges",
                camera_definition=[("DJI*.JPG", "DJI_RAW"), ("2021*.JPG", "M20_RAW")],
                delta=3600.,  # ordre de grandeur de l'écart initial (si connu)
                manual = True
            )