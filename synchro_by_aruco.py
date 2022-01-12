import cv2
import numpy as np
import irdrone.utils as ut
import irdrone.process as pr
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
        out_dir=None,
        camera_definition=[("*.RAW", "M20_RAW"), ("*.DNG", "DJI_RAW")],
        delta=0.,
        optionSolver='linear',
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
                img_name = ("_%04d_" % (index)) + osp.basename(img_pth)[:-4]
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
                        "angle": angle,
                        "corners": corners,
                    }
                    np.save(detection_file[:-4], results, allow_pickle=True)
                if angle is not None:
                    rot_list.append({"date": date, "path": img_pth, "angle": angle})
            sync_dict[cam] = rot_list
        np.save(synch_dict_path[:-4], sync_dict, allow_pickle=True)

    if manual:
        sig_list = []
        for indx, (cam, _delta, roll_offset) in enumerate(
                [("DJI_RAW", timedelta(seconds=delta), 0.), ("M20_RAW", timedelta(seconds=0.), 1.)]):
            cam_dat = np.array([[el["date"], el["angle"]] for el in sync_dict[cam]])
            angle_list = cam_dat[:, 1]

            modulo = 360 * (np.abs(angle_list[1:] - angle_list[:-1]) > 180.) * (
                -np.sign(angle_list[1:] - angle_list[:-1]))
            angle_list[1:] += np.cumsum(modulo) + roll_offset
            sig_list.append(imagepipe.Signal(cam_dat[:, 0] + _delta, angle_list, label="{}".format(cam),
                                             color=["k--.", "c-o"][indx]))

        signalplotshift(sig_list, init_delta=delta)

    cost_dict = buildCostDico(sync_dict, optionSolver)

    return cost_dict


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

            principal_axis_ = (topLeft - bottomLeft) + (topRight - bottomRight)
            principal_axis = principal_axis_ / np.sqrt(np.sum(principal_axis_ ** 2))
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

                cv2.line(image, (cX, cY), (int(cX + principal_axis_[0]), int(cY + principal_axis_[1])), (0, 255, 0), 2)
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


def aruco_chart_generator(arucoDict=ARUCO_SELECT, out=None):  # "ARCUO.png"
    tag_size = 1000
    tag = np.zeros((tag_size, tag_size, 1), dtype="uint8")
    cv2.aruco.drawMarker(arucoDict, 0, tag_size, tag, 1)
    if out is not None:
        cv2.imwrite(out, tag)
    return tag


def aruco_test_image():
    aruco_tag = aruco_chart_generator()
    img_size = (2000, 2000)
    image = 255 * np.ones((img_size[0], img_size[1], 3))

    # image = 255*np.ones((1000, 1000, 3))
    x_start, y_start = 600, 500
    image[y_start:y_start + aruco_tag.shape[0], x_start:x_start + aruco_tag.shape[1], :] = aruco_tag[::-1, ::-1]

    theta = np.deg2rad(30.)
    ho = np.array([
        [np.cos(theta), -np.sin(theta), 0.],
        [np.sin(theta), np.cos(theta), 0.],
        [0., 0., 1.],
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
            out.color = "orange"
            out.label = sig.label + " delay: {:.1f}s".format(shift + init_delta)
            return out

    AMPLI = Shift(
        "Amplification",
        vrange=[
            (-0., 280., 0.),
        ],
        mode=[imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    )

    ip = imagepipe.ImagePipe(
        sigList,
        sliders=[AMPLI, ])
    ip.gui()


def buildCostDico(sync_dict, optionSolver):
    # estimate time shift  B to A.
    estimDelta = (sync_dict['M20_RAW'][0]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds
    dataDJI = np.array([[el["date"], el["angle"]] for el in sync_dict['DJI_RAW']])
    dataM20 = np.array([[el["date"], el["angle"]] for el in sync_dict['M20_RAW']])
    # f_A(x_A)    f_B(x_B)
    x_A = [float((dataDJI[k, 0] - sync_dict['DJI_RAW'][0]['date']).seconds) for k in range(len(dataDJI[:, 0]))]
    x_B = [float((dataM20[k, 0] - sync_dict['DJI_RAW'][0]['date']).seconds - estimDelta) for k in range(len(dataM20[:, 0]))]
    # continuity for angle
    f_A = angle_0_360(dataDJI[:, 1])
    f_B = angle_0_360(dataM20[:, 1])

    cost_dict = {'x_A': x_A, 'f_A': f_A, 'x_B': x_B, 'f_B': f_B, 'solverOption': optionSolver, 'timeShift': estimDelta}

    return cost_dict


def angle_0_360(angle):
    # quadrants:  1 = [0,90°], 2 = [90°, 180°], 3 = [180°,270°], 4 = [270°,360°]
    angle = np.array(angle)
    w = [angle[0]] * len(angle)
    z = [angle[0]] * len(angle)
    for i in range(1, len(w)):
        if angle[i] >= 0:
            w[i] = angle[i]
        else:
            w[i] = 360 + angle[i]
    for i in range(1, len(w)):
        if w[i - 1] > 270 and w[i] < 90:  # changement de quadrant 4 > 1 (sens anti horaire)
            z[i] = z[i - 1] + 360 + w[i] - w[i - 1]
        elif w[i - 1] < 90 and w[i] > 270:  # changement de quadrant 1 > 4 (sens horaire)
            z[i] = z[i - 1] - (360 - (w[i] - w[i - 1]))
        else:
            z[i] = z[i - 1] + w[i] - w[i - 1]
    return list(z)


def domaine_interpol(x):
    x_interpol = np.linspace(min(x), max(x), num=9 * len(x), endpoint=True)
    return x_interpol


def interpol_func(x, y, option='linear'):
    f = interp1d(x, y, kind=option)
    return f


def cost_function(shift_x, cost_dic):
    # construct interpolator of f_A and f_B
    f_A = interpol_func(cost_dic['x_A'], cost_dic['f_A'], option=cost_dic['solverOption'])
    f_B = interpol_func(cost_dic['x_B'], cost_dic['f_B'], option=cost_dic['solverOption'])
    nb_pt = 1000
    # finds common support for both functions f_A and f_B.
    x_Ashift = np.array(cost_dic['x_A']).copy() + shift_x
    x_C = np.linspace(max(min(x_Ashift), min(cost_dic['x_B'])),
                      min(max(x_Ashift), max(cost_dic['x_B'])), num=nb_pt)
    x_A = np.round(x_C.copy() - shift_x, 2)
    cost = np.sqrt(np.sum((f_A(x_A) - f_B(x_C)) ** 2)) / nb_pt
    # print('Time shift = ', shift_x, '  cost   = ', cost)
    return cost


def cost_function_1(shift_x, cost_dic):
    # construct interpolator of f_A and f_B
    f_A = interpol_func(cost_dic['x_A'], cost_dic['f_A'], option=cost_dic['solverOption'])
    f_B = interpol_func(cost_dic['x_B'], cost_dic['f_B'], option=cost_dic['solverOption'])
    cost = 0.
    for i in range(len(cost_dic['x_A'])):
        if cost_dic['x_B'][0] <= cost_dic['x_A'][i] + shift_x <= cost_dic['x_B'][-1]:
            cost = cost + (f_A(cost_dic['x_A'][i]) - f_B(cost_dic['x_A'][i] + shift_x)) ** 2
        elif cost_dic['x_B'][0] > cost_dic['x_A'][i] + shift_x:
            cost = cost + (f_A(cost_dic['x_A'][i]) - f_B(cost_dic['x_B'][0])) ** 2
        else:
            cost = cost + (f_A(cost_dic['x_A'][i]) - f_B(cost_dic['x_B'][-1])) ** 2
    cost = np.sqrt(cost) / len(cost_dic['x_A'])
    return cost


def fitPlot(data, res):
    # construction des interpolateurs
    x_fit = [data['x_B'][i] - res.x for i in range(1, len(data['x_B']))]
    f_A = interpol_func(data['x_A'], data['f_A'], option=data['solverOption'])
    f_B = interpol_func(data['x_B'], data['f_B'], option=data['solverOption'])
    shift_graph = 100.  # Timle shift for graphic representation. Not true time
    plt.plot(data['x_A'], data['f_A'],
             color='black', linestyle='-', linewidth=1.4,
             marker='o', markersize=4, alpha=0.6)
    plt.plot(np.array(data['x_B']).copy() + shift_graph, data['f_B'],
             color='cyan', linestyle='-', linewidth=1.4,
             marker='o', markersize=4, alpha=0.6)
    plt.plot(x_fit, f_B([data['x_B'][i] for i in range(1, len(data['x_B']))]),
             color='orange', linestyle='-', linewidth=1.4,
             marker='o', markersize=2, alpha=0.6)
    x_B_interp = domaine_interpol(data['x_B'][0:])
    plt.plot(x_B_interp + shift_graph, f_B(x_B_interp),
             color='blue', linestyle='--', linewidth=0.4)
    plt.legend(['data_A', 'data_B', ' B fit'], loc='best')
    plt.grid()
    plt.title(' Time shift  = %.2f  s' % (res.x + data['timeShift']))
    plt.show()


if __name__ == "__main__":
    initDelta = 3600  # ordre de gandeur timeShift si connu
    optionSolver = 'linear'  # 'linear', 'quadratic', 'cubic'  ...
    cost_dict = synchronization_aruco_rotation(
                folder=r"C:\Air-Mission\FLY-20211109-Blassac-1ms\Synchro Horloges",
                camera_definition=[("DJI*.JPG", "DJI_RAW"), ("2021*.JPG", "M20_RAW")],
                optionSolver=optionSolver,
                delta=initDelta,
                manual=False
                )
    # --calcul du shift initial (basé sur la distance des pics des deux courbes)
    # Attention ici la courbe B a déjà été décalée de la pré estimation cost_dict['timeShift']
    # On est déjà près de la solution.
    # Il est parfaitement possible à ce stade de choisir   shift_0 = 0 !
    shift_0 = float(cost_dict['x_B'][np.argmax(cost_dict['f_A'])] - cost_dict['x_A'][np.argmax(cost_dict['f_B'])])
    # ------- optimisation avec une méthode sans gradient
    res = minimize(cost_function, shift_0, (cost_dict), method='Nelder-Mead', options={'xatol': 10 ** -8, 'disp': True})

    print('optimum initial      Time shift  = %.5f s.  cost = %.5f °\n'
          'optimum final        Time shift  = %.5f s.  cost = %.5f °'
          % (shift_0 + cost_dict['timeShift'], cost_function(float(shift_0), cost_dict),
             res.x + cost_dict['timeShift'], cost_function(float(res.x), cost_dict)))

    # -------   Visualisation des résultats de l'optimisation automatique
    fitPlot(cost_dict, res)

