# -*- coding: utf-8 -*-
import config
import cv2
import numpy as np
import irdrone.utils as ut
import irdrone.process as pr
from synchronization.aruco_helper import aruco_detection
import os
from datetime import timedelta
from irdrone import imagepipe
import copy
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from irdrone.utils import Style
import argparse

osp = os.path


def continuify_angles_vectorized(angle_list_, forced_offset=0.):
    """Aggregate an array of absolute angles between [-180 , 180]
    into a continuous serie
    """
    angle_list = np.mod(angle_list_.copy() + forced_offset + 180., 360.) - 180.
    modulo = 360 * (np.abs(angle_list[1:] - angle_list[:-1]) > 180.) * (-np.sign(angle_list[1:] - angle_list[:-1]))
    angle_list_continuous = angle_list.copy()
    angle_list_continuous[1:] += np.cumsum(modulo)
    return angle_list_continuous



def prepare_synchronization_data(
        folder,
        out_dir=None,
        camera_definition=[("*.RAW", config.NIR_CAMERA), ("*.DNG", config.VIS_CAMERA)],
):
    """Caches temporary results into a _synchro_check folder
    In case you didn't use the right regexp for input images, you can remove  _synchro_check/rotations_analyzis.npy
    """
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
            rot_list = []
            candidates = ut.imagepath(imgname=extension, dirname=folder)
            assert candidates is not None and len(candidates)>5, \
                "Cannot find enough images in {}/{}".format(folder, extension)
            for index, img_pth in enumerate(candidates):
                date = pr.Image(img_pth).date
                img_name = ("_%04d_" % (index)) + osp.basename(img_pth)[:-4]
                out_file = osp.join(out_dir, img_name + ".jpg")
                # if not osp.isfile(out_file):
                #     img = pr.Image(img_pth)
                #     img.save(out_file)
                #     img_thmb = cv2.resize(img.data, (640, 480))
                #     pr.Image(img_thmb).save(osp.join(out_dir, "_thumb_" + img_name + ".jpg"))
                # else:
                #     img = pr.Image(out_file)
                img = pr.Image(img_pth)
                detection_file = osp.join(out_dir, "_detection" + img_name + ".npy")
                if osp.isfile(detection_file):
                    results = np.load(detection_file, allow_pickle=True).item()
                    angle = results["angle"]
                else:
                    out = aruco_detection(
                        img.data,
                        show=False,
                        debug_fig=osp.join(out_dir, "_detection" + img_name + ".jpg"),
                        title="{} {}  ".format(cam, date)
                    )
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
    return sync_dict


def synchronization_aruco_rotation(
    sync_dict,
    delta=0.,
    optionSolver='linear',
    manual=False,
    camera_definition=[("*.RAW", config.NIR_CAMERA), ("*.DNG", config.VIS_CAMERA)],
):
    delay = None
    forced_offset = None
    if manual:
        sig_list = []
        for indx, (cam, _delta, roll_offset) in enumerate(
                [(camera_definition[0][1], timedelta(seconds=delta), 0.), (camera_definition[1][1], timedelta(seconds=0.), 0.)]):
            cam_dat = np.array([[el["date"], el["angle"]] for el in sync_dict[cam]])
            if forced_offset is None:
                forced_offset = -cam_dat[0, 1]
            continuous_angles = continuify_angles_vectorized(cam_dat[:, 1], forced_offset=forced_offset) + roll_offset
            sig_list.append(imagepipe.Signal(cam_dat[:, 0] + _delta, continuous_angles, label="{}".format(cam),
                                             color=["k--.", "c-o"][indx]))
        delta_init = amplitude_Slider_DeltaTime(sync_dict)
        delay = signalplotshift(sig_list, init_delta=delta_init)
    cost_dict = buildCostDico(sync_dict, optionSolver, init_Delta=delay)
    return cost_dict

def amplitude_Slider_DeltaTime(sync_dict):
    estim_delta = (sync_dict['M20_RAW'][0]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds +\
                  np.sign((sync_dict['M20_RAW'][0]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds) *\
                  max(((sync_dict['M20_RAW'][-1]['date'] - sync_dict['M20_RAW'][0]['date']).seconds),
                      ((sync_dict['DJI_RAW'][-1]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds))
    return estim_delta

def signalplotshift(siglist, init_delta=0.):
    class Shift(imagepipe.ProcessBlock):
        def apply(self, sig, shift, **kwargs):
            out = copy.deepcopy(sig)
            out.x = sig.x + timedelta(seconds=shift)
            out.color = "orange"
            out.label = sig.label + " delay: {:.1f}s".format(shift)
            return out

    delay_block = Shift(
        "Delay",
        vrange=[
            (min(0, init_delta), max(0, init_delta), 0.),
        ],
        mode=[imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    )

    ip = imagepipe.ImagePipe(
        siglist,
        sliders=[delay_block, ])
    ip.gui()

    delay = ip.sliders[0].values[0]

    return delay


def buildCostDico(sync_dict, optionSolver, init_Delta=None):
    if init_Delta == None or init_Delta == 0.0:
        # estimate time shift  B to A.
        estimDelta= (sync_dict['M20_RAW'][0]['date'] - sync_dict['DJI_RAW'][0]['date']).seconds
    else:
        # use manual estimate time shift  B to A.
        estimDelta = init_Delta

    dataVIS = np.array([[el["date"], el["angle"]] for el in sync_dict['DJI_RAW']])
    dataNIR = np.array([[el["date"], el["angle"]] for el in sync_dict['M20_RAW']])
    # f_A(t_A)    f_B(t_B)
    t_A = np.float_([(dataVIS[k, 0] - sync_dict['DJI_RAW'][0]['date']).seconds for k in range(len(dataVIS[:, 0]))])
    t_B = np.float_([(dataNIR[k, 0] - sync_dict['DJI_RAW'][0]['date']).seconds - estimDelta for k in range(len(dataNIR[:, 0]))])
    # continuity for angle
    forced_offset = -dataVIS[0, 1]
    f_A = continuify_angles_vectorized(dataVIS[:, 1], forced_offset=forced_offset)
    f_B = continuify_angles_vectorized(dataNIR[:, 1], forced_offset=forced_offset)

    cost_dict = {'t_A': t_A, 'f_A': f_A, 't_B': t_B, 'f_B': f_B, 'solverOption': optionSolver, 'timeShift': estimDelta}

    return cost_dict


def continuify_angles(angle):
    # quadrants:  1 = [0,90°], 2 = [90°, 180°], 3 = [180°,270°], 4 = [270°,360°]
    angle = np.array(angle)
    w = [angle[0]] * len(angle)
    z = [angle[0]] * len(angle)
    for i in range(len(w)):
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
    f_A = interpol_func(cost_dic['t_A'], cost_dic['f_A'], option=cost_dic['solverOption'])
    f_B = interpol_func(cost_dic['t_B'], cost_dic['f_B'], option=cost_dic['solverOption'])
    nb_pt = 1000
    # finds common support for both functions f_A and f_B.
    x_Ashift = np.array(cost_dic['t_A']).copy() + shift_x
    x_C = np.linspace(max(min(x_Ashift), min(cost_dic['t_B'])),
                      min(max(x_Ashift), max(cost_dic['t_B'])), num=nb_pt)
    x_A = np.round(x_C.copy() - shift_x, 2)
    cost = np.sqrt(np.sum((f_A(x_A) - f_B(x_C)) ** 2)) / nb_pt
    # print('Time shift = ', shift_x, '  cost   = ', cost)
    return cost


def cost_function_1(shift_x, cost_dic):
    # construct interpolator of f_A and f_B
    f_A = interpol_func(cost_dic['t_A'], cost_dic['f_A'], option=cost_dic['solverOption'])
    f_B = interpol_func(cost_dic['t_B'], cost_dic['f_B'], option=cost_dic['solverOption'])
    cost = 0.
    for i in range(len(cost_dic['t_A'])):
        if cost_dic['x_B'][0] <= cost_dic['t_A'][i] + shift_x <= cost_dic['x_B'][-1]:
            cost = cost + (f_A(cost_dic['t_A'][i]) - f_B(cost_dic['t_A'][i] + shift_x)) ** 2
        elif cost_dic['x_B'][0] > cost_dic['t_A'][i] + shift_x:
            cost = cost + (f_A(cost_dic['t_A'][i]) - f_B(cost_dic['t_B'][0])) ** 2
        else:
            cost = cost + (f_A(cost_dic['t_A'][i]) - f_B(cost_dic['t_B'][-1])) ** 2
    cost = np.sqrt(cost) / len(cost_dic['t_A'])
    return cost


def fitPlot(data, res, camera_definition):
    # construction des interpolateurs
    x_fit = [data['t_B'][i] - res.x for i in range(1, len(data['t_B']))]
    f_A = interpol_func(data['t_A'], data['f_A'], option=data['solverOption'])
    f_B = interpol_func(data['t_B'], data['f_B'], option=data['solverOption'])
    camera_A = camera_definition[0][1]
    camera_B = camera_definition[1][1]
    camera_Fit = camera_definition[1][1] + ' fit'
    shift_graph = 100.  # Timle shift for graphic representation. Not true time
    plt.plot(data['t_A'], data['f_A'],
             color='black', linestyle='-', linewidth=1.4,
             marker='o', markersize=4, alpha=0.6)
    plt.plot(np.array(data['t_B']).copy() + shift_graph, data['f_B'],
             color='cyan', linestyle='-', linewidth=1.4,
             marker='o', markersize=4, alpha=0.6)
    plt.plot(x_fit, f_B([data['t_B'][i] for i in range(1, len(data['t_B']))]),
             color='orange', linestyle='-', linewidth=1.4,
             marker='*', markersize=8, alpha=0.4)
    x_B_interp = domaine_interpol(data['t_B'][0:])
    plt.plot(x_B_interp + shift_graph, f_B(x_B_interp),
             color='blue', linestyle='--', linewidth=0.4)
    plt.legend([camera_A, camera_B, camera_Fit], loc='best')
    plt.grid()
    plt.title(' Time shift  = %.2f  s' % (res.x + data['timeShift']))
    plt.show()


if __name__ == "__main__":
    # python.exe synchro_by_aruco.py --folder "C:\Air-Mission\FLY-20220118-Blassac-Synchro\Synchro Horloges" --vis "*.DNG" --nir "20*.RAW" --manual

    parser = argparse.ArgumentParser(description='Synchronize IR and Visible cameras based on Aruco')
    parser.add_argument('--folder', help='list of images', required=True)
    parser.add_argument('--vis', default="DJI*.JPG",  help='regexp for visible images, works for DNG & JPG')
    parser.add_argument('--nir', default="20*.JPG",  help='regexp for infrared images, works for RAW & JPG')
    parser.add_argument('--manual',  action="store_true",  help='manual delay initialization')
    parser.add_argument('--delay',  default=0, type=float,  help='delay in second \
                                                      3600 means 1hour which can come from winter or summer times')

    args = parser.parse_args()
    initDelta = args.delay
    optionSolver = 'linear'  # 'linear', 'quadratic', 'cubic'  ...
    TryAgain = True
    iterations = 0
    camera_definition=[(args.vis, config.VIS_CAMERA), (args.nir, config.NIR_CAMERA)]
    sync_dict = prepare_synchronization_data(
        args.folder,
        camera_definition=camera_definition,
    )
    while TryAgain and iterations < 5:
        iterations += 1
        try:
            cost_dict = synchronization_aruco_rotation(
                sync_dict,
                camera_definition=camera_definition,
                optionSolver=optionSolver,
                delta=initDelta,
                manual=args.manual
            )

            #shift_0 = float(cost_dict['t_B'][np.argmax(cost_dict['f_A'])] - cost_dict['t_A'][np.argmax(cost_dict['f_B'])])
            shift_0 = 0
        #    ------- optimisation avec une méthode sans gradient
            res = minimize(cost_function, shift_0, (cost_dict), method='Nelder-Mead', options={'xatol': 10 ** -8, 'disp': False})

            if cost_function(float(res.x), cost_dict) > 1.:
                print(Style.RED + 'Please be more precise when synchronizing manually ...' + Style.RESET)
                ReDo = True
            else:
                print('optimum initial      Time shift  = %.5f s.  cost = %.5f °\n'
                      'optimum final        Time shift  = %.5f s.  cost = %.5f °'
                      % (shift_0 + cost_dict['timeShift'], cost_function(float(shift_0), cost_dict),
                         res.x + cost_dict['timeShift'], cost_function(float(res.x), cost_dict)))

                ReDo = False
            # -------   Visualisation des résultats de l'optimisation automatique
            fitPlot(cost_dict, res, camera_definition)
            TryAgain = ReDo
        except Exception as exc:
            print(exc)
            print(Style.RED + 'Please be more precise !'+Style.RESET)
            TryAgain = True



