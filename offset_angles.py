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
import config
import automatic_registration




def estimOffsetYawPitchRoll(shootingPts, listImgMatch, planVol, dirPlanVol, dirMission, dirNameIRdrone):
    offsetAngles_0 = planVol["offset_angles"]   # use offset angles  in FlightPlan (Excel ) or config.json (??)
    print(Style.GREEN + 'Current NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.3f° | %.3f° | %.3f° ].   ' % (planVol["offset_angles"][0], planVol["offset_angles"][1], planVol["offset_angles"][2]) + Style.RESET)
    try:
        mappingList, ImgMatchOffset, ptsOffset = IRd.summaryFlight(shootingPts, listImgMatch, planVol, dirPlanVol,
                                                                   optionAlignment='best-offset',
                                                                   offsetTheoreticalAngle=offsetAngles_0,
                                                                   seaLevel=True,
                                                                   dirSavePlanVol=osp.dirname(dirPlanVol),
                                                                   saveGpsTrack=False,
                                                                   saveExcel=True,
                                                                   savePickle=False,
                                                                   createMappingList=False,
                                                                   muteGraph=True,
                                                                   mute=True,
                                                                   altitude_api_disabled=False)
    except Exception as exc:
        logging.error(
            Style.RED + "Cannot compute flight analytics - you can still process your images but you won't get altitude profiles and gpx\nError = {}".format(
                exc) + Style.RESET)
        mappingList = None

    traces = ["vir"]  # ["vis", "nir", "vir", "ndvi"]
    nbImgProcess = len(ptsOffset)
    print(Style.YELLOW + 'WARNING : The processing of these %i images will take %.2f h.' % (nbImgProcess, 1.5 * nbImgProcess / 60.) + Style.RESET)
    dirNameOffset = os.path.join(dirMission, 'ImgOffset')
    IRd.reformatDirectory(dirNameOffset, rootdir=dirPlanVol, makeOutdir=True)
    print(Style.CYAN + 'INFO : ------ Automatic_registration.process_raw_pairs \n' + Style.RESET)
    automatic_registration.process_raw_pairs(ImgMatchOffset[::1],
                                             out_dir=dirNameOffset,
                                             crop=config.CROP,
                                             listPts=ptsOffset,
                                             option_alti='sealevel',
                                             clean_proxy=True,
                                             multispectral_folder=None,
                                             traces=traces)
    try:
        IRd.save_motion_camera(dirMission, shootingPts, planVol, listImgMatch)
    except Exception as exc:
        logging.error(Style.YELLOW + "WARNING : Flight analytics cannot plot.\nError = {}".format(exc) + Style.RESET)
    offsetYaw, offsetPitch, offsetRoll = IRd.estimOffset(ptsOffset)
    print(Style.GREEN + 'New NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.3f° | %.3f° | %.3f° ].   ' % (offsetYaw, offsetPitch, offsetRoll) + Style.RESET)



    return offsetYaw, offsetPitch, offsetRoll
