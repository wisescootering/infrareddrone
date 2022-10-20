# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
version 1.05 2021-12-01
version 1.06 2021-12-31 16:41:05.   Theoritical Yaw,Pitch,Roll for NIR images
version 1.07 2022-02-17 21:58:00    Class ShootPoint. Save Summary Flight in binary file  (pickle)
version 1.3  2022-09-27             Mapping ODM, 4 band images Tif,  ...
@authors: balthazar/alain
"""

import logging
import utils.angles_analyzis as analys
import utils.utils_IRdrone as IRd
from utils.utils_odm import odm_mapping_optim, create_odm_folder
from irdrone.utils import Style
import datetime
import time
import os
import argparse
import os.path as osp
import automatic_registration
from version import __version__ as versionIRdrone
from config import CROP
from pathlib import Path

if __name__ == "__main__":
    # --------------------------------------------------------------------------------------------------------------
    #                    Start of calculation time measurement.
    # --------------------------------------------------------------------------------------------------------------
    timeDebut = datetime.datetime.now()
    startTime = time.process_time()
    print(Style.CYAN + 'Start IRdrone-v%s  at  %s ' % (versionIRdrone, timeDebut.time()) + Style.RESET)

    # ------------------------------------------------------------------------------------------------------------
    # 0 > Interactive choice of mission
    # ------------------------------------------------------------------------------------------------------------
    parser = argparse.ArgumentParser(description='Process pre-synchronized multispectral aerial data')
    parser.add_argument('--config', type=str, help='path to the flight configuration')
    parser.add_argument('--clean-proxy', action="store_true", help='clean proxy tif files to save storage')
    parser.add_argument('--disable-altitude-api', action="store_true", help='force not using altitude from IGN API')
    parser.add_argument('--odm-multispectral', default=True, action="store_true", help='ODM multispectral export')
    parser.add_argument('--traces', default=None, choices=automatic_registration.TRACES, nargs="+", 
        help= 'export specific spectral traces. when not provided: VIR by default if --odm-multispectral, otherwise all traces'
    )
    parser.add_argument('--selection', type=str, default="all", choices=["all", "best-synchro", "best-mapping"],
        help= 'best-synchro: only pick pairs of images with gap < 1/4th of the TimeLapseDJI interval ~ 0.5 seconds'
        + 'best-mapping: select best synchronized images + granting a decent overlap'
    )
    args = parser.parse_args()
    clean_proxy = args.clean_proxy
    dirPlanVol = args.config
    if dirPlanVol is None or not os.path.isfile(dirPlanVol):
        print(Style.CYAN + "File browser")
        dirPlanVol = IRd.loadFileGUI(mute=False)

    dirMission = os.path.dirname(dirPlanVol)
    odm_multispectral = args.odm_multispectral
    traces = args.traces

    # --------------------------------------------------------------------------
    #                    options       (for rapid tests and analysis)
    # --------------------------------------------------------------------------
    seaLevel = True        # Calculate the altitude of the ground via the IGN API. If the server is unavailable makes three attempts.
    saveGpsTrack = True    # Save the drone’s trajectory in a GPS file in Garmin format (.gpx)
    saveExcel = True       # Save the list of pairs, GPS coordinates, angles ... in an Excel file
    savePickle = True      # Save mission data (flight plan, shootingPts) in a binary file.
    createMappingList = True  # Create a list of best synchronous images for mapping with ODM
    option_alti = 'sealevel'  # Altitude GPS  for Exif data. Options: ['takeoff', 'sealevel', 'ground', 'geo']
    analysisAlignment = True   #  Analysis of "theoretical" and "coarse" alignment angles
    showAnglPlot = True     #Display of the chart at the end of the process. The chart is automatically saved in the "Flight Analytics" folder.
    showDisperPlot = False


    # --------------------------------------------------------------------------------------------------------------
    # 1 > Extraction of flight data
    #       Date, time, image file, clock sync, drone and IR camera type ...
    #       Construction of the list of images taken during the flight (Drone and IR)
    # --------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Read flight plan' + Style.RESET)
    planVol, \
    imgListDrone, deltaTimeDrone, timeLapseDrone, \
    imgListIR, deltaTimeIR, timeLapseIR, dirNameIRdrone = \
        IRd.extractFlightPlan(dirPlanVol, mute=True)

    print(Style.GREEN + "Time shift between original VIS and NIR images :  %s s   First image shooting at  %s" %(round(deltaTimeIR,2), planVol["mission"]["date"]) + Style.RESET)
    
    # --------------------------------------------------------------------------------------------------------------
    # 2 > Find matching pairs of images from both cameras
    #     Pair images from both cameras
    #     We are looking for the pairs of Vi and IR images taken at the "same moment".
    #     It is possible to view pairs of IR and Vi images.
    #     These images are saved in the dirNameIRdrone folder
    #     that was specified in the flight plan  (FlightPlan_*.xlxs)
    #
    # Note:   > Type A images are those with the smallest timelapse or  ...
    #           no time lapse at all (timelapse_A < 0 value set in Excel file FlightPlan.xlsx)
    #         > Type B images have the largest timelapse  (timelapse_B > timelapse_A ).
    #   In order for an A_j image to be considered synchronized with a B_k image, the closest (nearest) time criterion is used:
    #   Selected from the {B_k} images that have the minimum date difference (deltaTime) with the A_j image
    #
    #   - Construction of the GPS trace between the image pairs. (file format .gpx)
    #   - Write data in Excel and Binary files.
    #   - Plot of the drone flight profile and the image mapping diagram (file format .png)
    #
    # --------------------------------------------------------------------------------------------------------------

    print(Style.CYAN + '------ Pair images VIS & NIR' + Style.RESET)
    synchro_date = planVol['mission']['date']
    if synchro_date is None:
        raise NameError(Style.RED + "Synchro start date needs to be provided!" + Style.RESET)
    shootingPts = None # process_raw_pairs shall work with None shootingPts
    listImgMatch, DtImgMatch, listdateMatch, shootingPts = \
        IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR, deltaTimeIR, timeLapseIR,
                                  synchro_date, mute=True)

    # Image selection for VIS NIR pair alignment process based on option-alignment value
    # > 'all'  or None   Selects all available pairs of images in AerialPhotography
    # > 'best-synchro'   Selects only images with timing deviation less than TimeLapseDJI*0.25
    # > 'best-mapping'   Selects in well-synchronized images those with appropriate mapping overlap.
    # Note: If the shooting mode is not HYPERLAPSE the registration option is forced to "all".
    selection_option = args.selection
    if timeLapseDrone > 0:
        print(Style.GREEN + 'Option for images alignment is %s ' % selection_option + Style.RESET)
    else:
        selection_option = 'all'
        traces = ["vis", "nir", "vir"]
        createMappingList = False
        print(
            Style.YELLOW + 'The shots of this mission were not taken in hyperlapse mode.\n All pairs will be aligned.\n No mapping.\n Option for images alignment is %s ' % selection_option + Style.RESET)

    try:
        # Fixed the alignment defect [yaw,pitch,roll] of the NIR camera aiming axis in °
        mappingList, ImgMatchProcess, ptsProcess = IRd.summaryFlight(shootingPts, listImgMatch, planVol, dirPlanVol,
                        optionAlignment=selection_option,
                        offsetTheoreticalAngle=planVol["offset_angles"],
                        seaLevel=seaLevel,
                        dirSavePlanVol=osp.dirname(dirPlanVol),
                        saveGpsTrack=saveGpsTrack,
                        saveExcel=saveExcel,
                        savePickle=savePickle,
                        createMappingList=createMappingList,
                        mute=True,
                        altitude_api_disabled=args.disable_altitude_api)
    except Exception as exc:
        logging.error(Style.RED + "Cannot compute flight analytics - you can still process your images but you won't get altitude profiles and gpx\nError = {}".format(exc)+ Style.RESET)
        mappingList = None

    # -------------------------------------------------------------------------------------------------------------
    # 3 > Image processing.
    #     Automatic_registration of Vi and IR image pairs.
    #     Build ViR and NDVI images.
    # -------------------------------------------------------------------------------------------------------------
    odm_image_directory = None
    if odm_multispectral:
        if traces is None:
            traces = [automatic_registration.VIR]
        odm_image_directory = create_odm_folder(dirMission, multispectral_modality="MULTI", extra_options=["--skip-band-alignment"])
    else:
        if traces is None:
            traces = automatic_registration.TRACES
    nbImgProcess = len(ptsProcess)
    print(Style.YELLOW + 'The processing of these %i images will take %.2f h.  Do you want to continue?'
          % (nbImgProcess, 2.05 * nbImgProcess / 60.) + Style.RESET)
    autoRegistration = IRd.answerYesNo('Yes (y/1) |  No (n/0):')
    if autoRegistration:
        print(Style.CYAN + '------ Automatic_registration.process_raw_pairs' + Style.RESET)
        automatic_registration.process_raw_pairs(
                ImgMatchProcess[::1], out_dir=dirNameIRdrone, crop=CROP, listPts=shootingPts ,
                option_alti=option_alti, clean_proxy=clean_proxy, multispectral_folder=odm_image_directory,
                traces=traces
            )
    else:
        print(
            Style.YELLOW + 'Warning :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)

    # -------------------------------------------------------------------------------------------------------------
    # 4 > Open Drone Map
    #      Prepare ODM folders (with .bat, images and camera calibrations)
    # -------------------------------------------------------------------------------------------------------------
    if not odm_multispectral and timeLapseDrone > 0:
        for ext in ["VIS", "NIR_local", "NDVI__local", "VIR__local"]:
            odm_image_directory = odm_mapping_optim(dirMission, dirNameIRdrone, multispectral_modality=ext, mappingList=mappingList)

    # -------------------------------------------------------------------------------------------------------------
    # 5 > Analysis
    #     Draws roll, pitch and Yaw angles (roll, pitch & yaw)
    #     for the drone, the gimbal and the NIR image (coarse process and theoretical)
    # -------------------------------------------------------------------------------------------------------------

    if analysisAlignment:
        try:
            analys.analyzis_motion_camera(dirMission, shootingPts, planVol, showAnglPlot=showAnglPlot, showDisperPlot=showDisperPlot)
            IRd.SaveSummaryInExcelFormat(dirMission, saveExcel, shootingPts, listImgMatch, mute=True)
            IRd.SaveSummaryInNpyFormat(dirMission, savePickle, planVol, shootingPts)
        except Exception as exc:
            logging.error(
                Style.YELLOW + "Flight analytics cannot plot.\nError = {}".format(
                    exc) + Style.RESET)

    # -------------------------------------------------------------------------------------------------------------
    #        End of calculation time measurement.
    # -------------------------------------------------------------------------------------------------------------
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    IRd.logoIRDrone(num=4)
    print(
        Style.CYAN + '\n End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)

