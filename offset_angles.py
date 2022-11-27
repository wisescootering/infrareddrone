# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703

"""
Created on 2022-11-23 19:12:00
version 1.3  2022-11-23 19:12:00
@authors: balthazar/alain
"""

import logging
import os
import os.path as osp
import sys

import utils.utils_IRdrone as IRd
from irdrone.utils import Style

sys.path.append(osp.join(osp.dirname(__file__), ".."))
import traceback

import automatic_registration
import config


def estimOffsetYawPitchRoll(shooting_pts_list, matched_images_paths_list, flight_data_dict, dirPlanVol, dirMission):
    offsetAngles_0 = flight_data_dict["offset_angles"]   # use offset angles  in FlightPlan (Excel ) or config.json (??)
    print(Style.GREEN + 'Current NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.3f° | %.3f° | %.3f° ].   ' % (flight_data_dict["offset_angles"][0], flight_data_dict["offset_angles"][1], flight_data_dict["offset_angles"][2]) + Style.RESET)
    try:
        shootingPts = IRd.summaryFlight(shooting_pts_list, matched_images_paths_list, flight_data_dict, dirPlanVol,
                                                                   offsetTheoreticalAngle=offsetAngles_0,
                                                                   seaLevel=True,
                                                                   dirSavePlanVol=osp.dirname(dirPlanVol),
                                                                   saveGpsTrack=False,
                                                                   saveExcel=True,
                                                                   savePickle=False,
                                                                   muteGraph=True,
                                                                   mute=True,
                                                                   altitude_api_disabled=False)
    except Exception as exc:
        logging.error(
            Style.RED + "Cannot compute flight analytics - you can still process your images but you won't get altitude profiles and gpx\nError = {}".format(
                exc) + Style.RESET)
        traceback.print_exc()
    matched_images_paths_offset_selection, shooting_pts_offset_selection = IRd.select_pairs(
        shooting_pts_list, matched_images_paths_list, flight_data_dict, optionAlignment='best-offset',
        folder_save=osp.dirname(dirPlanVol)
    )
    traces = ["vir", "vis"] #, "nir", "vir", "ndvi"]
    nbImgProcess = len(shooting_pts_offset_selection)
    print(Style.YELLOW + 'WARNING : The processing of these %i images will take %.2f h.' % (nbImgProcess, 1.5 * nbImgProcess / 60.) + Style.RESET)
    dirNameOffset = os.path.join(dirMission, 'ImgOffset')
    IRd.reformatDirectory(dirNameOffset, rootdir=dirPlanVol, makeOutdir=True)
    print(Style.CYAN + 'INFO : ------ Automatic_registration.process_raw_pairs \n' + Style.RESET)
    automatic_registration.process_raw_pairs(matched_images_paths_offset_selection,
                                             out_dir=dirNameOffset,
                                             crop=config.CROP,
                                             listPts=shooting_pts_offset_selection,
                                             option_alti='sealevel',
                                             clean_proxy=True,
                                             multispectral_folder=None,
                                             traces=traces)
    try:
        IRd.save_motion_camera(dirMission, shootingPts, flight_data_dict, matched_images_paths_offset_selection)
    except Exception as exc:
        logging.error(Style.YELLOW + "WARNING : Flight analytics cannot plot.\nError = {}".format(exc) + Style.RESET)
        traceback.print_exc()
    offsetYaw, offsetPitch, offsetRoll = IRd.estimOffset(shooting_pts_offset_selection)
    print(Style.GREEN + 'New NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.3f° | %.3f° | %.3f° ].   ' % (offsetYaw, offsetPitch, offsetRoll) + Style.RESET)



    return offsetYaw, offsetPitch, offsetRoll
