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

import argparse
import datetime
import logging
import os
import os.path as osp
import sys
import time
import traceback
from copy import deepcopy
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy as np

import automatic_registration
import utils.angles_analyzis as analys
import utils.utils_IRdrone as IRd
from config import CROP
from irdrone.utils import Style
from utils.utils_IRdrone import legacy_best_mapping_selection
from utils.utils_IRdrone_Class import ShootPoint
from utils.utils_odm import create_odm_folder, odm_mapping_optim
from version import __version__ as versionIRdrone


def extract_flight_data(config_file: Union[str, Path]) -> dict:
    """
    1 > Extraction of flight data
    --------------------------------------------------------------------------------------------------------------
    Date, time, image file, clock sync, drone and IR camera type ...
    Construction of the list of images taken during the flight (Drone and IR)
    Aggregates all information from the configuration file in particular:
    - it reads all exifs from visible & nir images.
    - it retrieves the delay from the synchronization pre-phase
    --------------------------------------------------------------------------------------------------------------
    Args:
        config_file (Union[str, Path]): path to json (or xlsx) configuration file.

    Returns:
        dict:
        flight_data_dict contains aggregated information such as:
        * `images_path_list_vis`, `images_path_list_ir`: list of paths to the input images 
        * `timelapse_vis_interval`,  `timelapse_ir_interval`: timelapse intervals for the visible drone images & nir camera
        * `delta_time_vis`, `delta_time_ir`: temporal mis-synchronization (epressed in seconds)
        * `out_images_folder`: folder to save VIS, NIR jpg images
    """
    print(Style.CYAN + 'INFO : ------ Read flight plan' + Style.RESET)
    flight_data_dict = IRd.extractFlightPlan(config_file, mute=True)
    print(Style.GREEN + "Time shift between original VIS and NIR images :  %s s   "
    "First image shooting at  %s" %(round(flight_data_dict["delta_time_ir"],2), flight_data_dict["mission"]["date"]) + Style.RESET)

    return flight_data_dict



def find_all_matching_pairs(flight_data_dict: dict) -> List[ShootPoint]:
    """
    2 > Find all matching pairs of images from both cameras
    --------------------------------------------------------------------------------------------------------------
    Pair images from both cameras
    We are looking for the pairs of Vi and IR images taken at the "same moment".
    --------------------------------------------------------------------------------------------------------------
    Args:
        flight_data_dict (dict): dictionary containing all valuable information
    Raises:
        NameError: No synchronization provided

    Returns:
        List[ShootPoint]: list of all ShootPoint points with metadata.
    
    ```matched_images_paths_list = list(map(lambda pt: (pt.Vis, pt.Nir), shooting_pts_list))```

    Notes:
    ------
    It is possible to view pairs of IR and Vi images.
    These images are saved in the configuration["out_images_folder"] folder
    that was specified in the flight plan  (FlightPlan_*.xlxs)

    > Type A images are those:
      - with the smallest timelapse or  ...
      - no time lapse at all (timelapse_A < 0 value set in Excel file FlightPlan.xlsx)
    > Type B images have:
      - the largest timelapse  (timelapse_B > timelapse_A ).
    In order for an A_j image to be considered synchronized with a B_k image, the closest (nearest) time criterion is used:
    Selected from the {B_k} images that have the minimum date difference (deltaTime) with the A_j image
    """

    
    print(Style.CYAN + 'INFO : ------ Pair images VIS & NIR' + Style.RESET)
    synchro_date = flight_data_dict['mission']['date']
    if synchro_date is None:
        raise NameError(Style.RED + "Synchro start date needs to be provided!" + Style.RESET)
    shooting_pts_list = None # process_raw_pairs shall work with None shootingPts

    #  Find matching pairs of images from both cameras
    shooting_pts_list = IRd.matchImagesFlightPath(
        flight_data_dict["images_path_list_vis"],
        flight_data_dict["delta_time_vis"],
        flight_data_dict["timelapse_vis_interval"] , 
        flight_data_dict["images_path_list_ir"],
        flight_data_dict["delta_time_ir"],
        flight_data_dict["timelapse_ir_interval"],
        synchro_date, 
        mute=True
    )
    return shooting_pts_list


def gather_metadata(flight_data_dict: dict, shooting_pts_list: List[ShootPoint], configuration: dict):
    """
    3 > Retrieve altitudes and fill shooting points from exif metadata
    """
    offsetAngle = flight_data_dict["offset_angles"]
    print(Style.GREEN  + f"Initial offset angles {offsetAngle}" + Style.RESET)
    matched_images_paths_list = list(map(lambda pt: (pt.Vis, pt.Nir), shooting_pts_list))
    shooting_pts_list = IRd.summaryFlight(
        shooting_pts_list, matched_images_paths_list, flight_data_dict, configuration["config_file"],
        offsetTheoreticalAngle=offsetAngle,
        seaLevel=configuration['seaLevel'],
        dirSavePlanVol=osp.dirname(configuration["config_file"]),
        saveGpsTrack=configuration['saveGpsTrack'],
        saveExcel=configuration['saveExcel'],
        savePickle=configuration['savePickle'],
        mute=True,
        altitude_api_disabled=configuration["disable_altitude_api"]
    )

def auto_angles_offset_pre_computation(flight_data_dict: dict, shooting_pts_list: List[ShootPoint], configuration: Optional[dict]={}):
    """
    4 > Pre-compute angles offset from a sub-selection of frames (with minimum delay)
    --------------------------------------------------------------------------------------------------------------
    """
    try:
        offset_estimation_folder = Path(configuration["working_directory"]) / "offset_pre_estimation"
        shooting_pts_offset_selection = IRd.select_pairs(
            deepcopy(shooting_pts_list), flight_data_dict, optionAlignment='best-offset',
            folder_save=os.path.join(offset_estimation_folder, 'Mapping selection for offset')
        )
        #  Offset angles estimation
        # images will be processed in a new offset directory
        offsetYaw, offsetPitch, offsetRoll = estim_offsets_from_subselection(
            shooting_pts_offset_selection,
            flight_data_dict,
            configuration["config_file"],
            Path(configuration["working_directory"]) / "offset_pre_estimation"
        )
        offsetAngle = [offsetYaw, offsetPitch, offsetRoll]
        flight_data_dict["estimated_offset_angles"] = offsetAngle
        flight_data_dict["offset_angles"] = list(np.array(offsetAngle) +  np.array(flight_data_dict["offset_angles"]))
        # phase_test = False
        # if phase_test:
        #     analys.analyzis_motion_camera(
        #         configuration["working_directory"],
        #         shooting_pts_list,
        #         [offsetYaw, offsetPitch, offsetRoll],
        #         showAnglPlot=True,
        #         showDisperPlot=True
        #     )
    except Exception as exc:
        logging.error(Style.RED + "Cannot pre-compute flight offset\nError = {}".format(exc)+ Style.RESET)
        traceback.print_exc()
    return offsetAngle, shooting_pts_offset_selection


def estim_offsets_from_subselection(shooting_pts_offset_selection, flight_data_dict, dirPlanVol, dirMission):
    offsetYaw, offsetPitch, offsetRoll = 0., 0., 0.
    traces = ["vir", "vis"] #, "nir", "vir", "ndvi"]
    nbImgProcess = len(shooting_pts_offset_selection)
    print(Style.YELLOW + 'WARNING : The processing of these %i images will take %.2f h.' % (nbImgProcess, 1.5 * nbImgProcess / 60.) + Style.RESET)
    dirNameOffset = os.path.join(dirMission, 'ImgOffset')
    IRd.reformatDirectory(dirNameOffset, rootdir=dirPlanVol, makeOutdir=True)
    print(Style.CYAN + 'INFO : ------ Automatic_registration.process_raw_pairs \n' + Style.RESET)
    matched_images_paths_offset_selection = list(map(lambda pt: (pt.Vis, pt.Nir), shooting_pts_offset_selection))
    automatic_registration.process_raw_pairs(matched_images_paths_offset_selection,
                                             out_dir=dirNameOffset,
                                             crop=CROP,
                                             listPts=shooting_pts_offset_selection,
                                             option_alti='sealevel',
                                             clean_proxy=True,
                                             multispectral_folder=None,
                                             skip=True,
                                             traces=traces)
    try:
        IRd.SaveSummaryInExcelFormat(dirMission, True, shooting_pts_offset_selection, matched_images_paths_offset_selection, mute=True)
        IRd.SaveSummaryInNpyFormat(dirMission, True, flight_data_dict, shooting_pts_offset_selection)
    except Exception as exc:
        logging.error(Style.YELLOW + "WARNING : Offset angle analytics cannot be saved to excel.\nError = {}".format(exc) + Style.RESET)
        traceback.print_exc()
    offsetYaw, offsetPitch, offsetRoll = IRd.estimOffset(shooting_pts_offset_selection)
    print(Style.GREEN + 'Extra NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.3f° | %.3f° | %.3f° ].   ' % (offsetYaw, offsetPitch, offsetRoll) + Style.RESET)

    return offsetYaw, offsetPitch, offsetRoll


def select_matching_pairs(flight_data_dict: dict, shooting_pts_list: List[ShootPoint], configuration: Optional[dict]={}, selection_option: str='all') -> Tuple[List[Tuple[Path, Path]], List[ShootPoint], List[ShootPoint]]:
    """
    5 > Select matching pairs of images from both cameras
    --------------------------------------------------------------------------------------------------------------
    
      - Find pairs of images with a timing deviation of less than ~ 0,05 s.
      - Construction of the GPS trace between the image pairs. (file format .gpx)
      - Write data in Excel and Binary files.
      - Plot of the drone flight profile and the image mapping diagram (file format .png)
    
    --------------------------------------------------------------------------------------------------------------
    """
    try:
        # Image selection for VIS NIR pair alignment process based on option-alignment value
        # > 'all'  or None   Selects all available pairs of images in AerialPhotography
        # > 'best-synchro'   Selects only images with timing deviation less than TimeLapseDJI*0.25
        # > 'best-mapping'   Selects in well-synchronized images those with appropriate mapping overlap.
        # Note: If the shooting mode is not HYPERLAPSE the registration option is forced to "all".
        if flight_data_dict["timelapse_vis_interval"] > 0:
            print(Style.GREEN + 'Option for images alignment is %s ' % selection_option + Style.RESET)
        else:
            selection_option = 'all'
            configuration["traces"] = ["vis", "nir", "vir"]
            configuration["createMappingList"] = False
            print(
                Style.YELLOW + 'The shots of this mission were not taken in hyperlapse mode.\n All pairs will be aligned.\n No mapping.\n Option for images alignment is %s ' % selection_option + Style.RESET)


        # Fixed the alignment defect [yaw,pitch,roll] of the NIR camera aiming axis in °
        print(Style.GREEN + 'NIR camera offset angles : [Yaw, Pitch, Roll]= [ %.2f° | %.2f° | %.2f° ].   '%(
            flight_data_dict["offset_angles"][0], flight_data_dict["offset_angles"][1], flight_data_dict["offset_angles"][2]) + Style.RESET)
        shooting_pts_selection = IRd.select_pairs(
            shooting_pts_list, flight_data_dict, optionAlignment=selection_option,
            folder_save=configuration["working_directory"]
        )
    except Exception as exc:
        logging.error(Style.RED + "Cannot compute flight analytics - you can still process your images but you won't get altitude profiles and gpx\nError = {}".format(exc)+ Style.RESET)
        traceback.print_exc()
    return shooting_pts_selection

def image_processing_engine(ImgMatchProcess: List[Tuple[Path, Path]], ptsProcess: List[ShootPoint], odm_multispectral: bool=True, traces: Optional[List[str]]=None, configuration: dict={}, skip=False):
    """
    6 > Image processing.
    -------------------------------------------------------------------------------------------------------------
        Automatic_registration of Vi and IR image pairs.
        Build multispectal images ( Red/Green/Blue/NIR   .tif) and  vis, nir images (.jpg). 
        vir & ndvi images are optional.
    -------------------------------------------------------------------------------------------------------------

    Args:
        ImgMatchProcess (List[Tuple[Path, Path]]): List of tuples (visible , nir) images paths
        ptsProcess (List[ShootPoint]): Metadata of all points
        odm_multispectral (bool, optional): Flag to decide whether or not to output 4 channels tifs. Defaults to True.
        traces (Optional[List[str]], optional): List of string containing the jpg modalities to be saved (like vis, nir, vir, ndvi). Defaults to None.
        configuration (dict, optional): dictionary containing all configurations parameters. Defaults to {}.
    """
    
    odm_image_directory = None
    if odm_multispectral:
        if traces is None:
            traces = [automatic_registration.VIR]
        odm_image_directory = create_odm_folder(configuration["working_directory"], multispectral_modality="MULTI", extra_options=["--skip-band-alignment"])
    else:
        if traces is None:
            traces = automatic_registration.TRACES
    nbImgProcess = len(ptsProcess)
    print(Style.YELLOW + 'WARNING : The processing of these %i images will take %.2f h.  Do you want to continue?'
          % (nbImgProcess, 1.5 * nbImgProcess / 60.) + Style.RESET)
    autoRegistration = IRd.answerYesNo('Yes (y/1) |  No (n/0):')
    if autoRegistration:
        print(Style.CYAN + 'INFO : ------ Automatic_registration.process_raw_pairs \n' + Style.RESET)
        automatic_registration.process_raw_pairs(
                ImgMatchProcess, out_dir=configuration["out_images_folder"], crop=CROP, listPts=ptsProcess,
                option_alti=configuration['option_alti'], clean_proxy=configuration.get("clean_proxy", False), multispectral_folder=odm_image_directory,
                traces=traces,
                skip=skip
            )
    else:
        print(
            Style.YELLOW + 'WARNING :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)


def legacy_prepare_odm_postprocessing(shooting_pts_list: List[ShootPoint], configuration: dict={}):
    """
    7 > Open Drone Map post processing [OPTIONAL]
    -------------------------------------------------------------------------------------------------------------
    [OPTIONAL IN MULTISPECTRAL MODE]
    Prepare ODM folders (with .bat, images and camera calibrations)

    -------------------------------------------------------------------------------------------------------------

    Args:
        shooting_pts_list List[ShootPoint]: all points with metadata
        configuration (dict, optional): Defaults to {}.
    """
    if not configuration["createMappingList"]:
        return
    shooting_pts_selection_best_mapping = legacy_best_mapping_selection(shooting_pts_list)
    dirMission = configuration["working_directory"]
    if not configuration["odm_multispectral"] and configuration["timelapse_vis_interval"] > 0:
        for ext in ["VIS", "NIR_local", "NDVI__local", "VIR__local"]:
            for trace in configuration["traces"]:
                if trace in ext.lower():
                    _odm_image_directory = odm_mapping_optim(
                        dirMission,
                        configuration["out_images_folder"], multispectral_modality=ext, mappingList=shooting_pts_selection_best_mapping)
                    break
    # @TODO: potentially could directly run the ODM post processing straight away, without the need for any user intervention


def analyzis(flight_data_dict: dict, shootingPts: List[ShootPoint], configuration: dict={}):
    """
    8 > Analysis
    -------------------------------------------------------------------------------------------------------------
    - Draws roll, pitch and Yaw angles (roll, pitch & yaw)
    for the drone, the gimbal and the NIR image (coarse process and theoretical)
    - Saves excel & npy angles summaries
    -------------------------------------------------------------------------------------------------------------

    Args:
        flight_data_dict (dict): contains calibrated offset angles
        shootingPts (List[ShootPoint]): list of pairs of images including all metadata
        configuration (dict, optional): options including plotting flags. Defaults to {}.
    """
    listImgMatch = list(map(lambda pt: (pt.Vis, pt.Nir), shootingPts))
    dirMission = configuration["working_directory"]

    if not configuration['analysisAlignment']:
        return
    try:
        analys.analyzis_motion_camera(
            dirMission, shootingPts, flight_data_dict["offset_angles"],
            showAnglPlot=configuration['showAnglPlot'], showDisperPlot=configuration['showDisperPlot']
        )
        IRd.SaveSummaryInExcelFormat(dirMission, configuration['saveExcel'], shootingPts, listImgMatch, mute=True)
        IRd.SaveSummaryInNpyFormat(dirMission, configuration['savePickle'], flight_data_dict, shootingPts)
    except Exception as exc:
        logging.error(
            Style.YELLOW + "WARNING : Flight analytics cannot plot.\nError = {}".format(
                exc) + Style.RESET)
        traceback.print_exc()


def configure(args: argparse.Namespace) -> dict:
    """
    0 > Prepare configuration / options dictionary
    ------------------------------------------------------------------------------------------------------------

    Args:
        args (argparse.Namespace): parsed arguments

    Returns:
        dict: _description_
    """
    if args.odm_multispectral:
        if args.traces is None:
            args.traces = [automatic_registration.VIR] # default VIR jpg trace to at least be able to visualize something
    else:
        if args.traces is None:
            args.traces = automatic_registration.TRACES
    options = dict(
        config_file=args.config,                        # config file (json or excel)
        working_directory=os.path.dirname(args.config), # mission directory
        clean_proxy = args.clean_proxy,                 # flag to clean temporary data
        odm_multispectral=args.odm_multispectral,       # flag to save 4 multispectral tifs per pair & enable ODM multispectral mode, True by default
        disable_altitude_api=args.disable_altitude_api, # disable calls to IGN API (not recommended), False by default
        traces=args.traces,                             # list of traces
        offset=args.offset,                             # ["manual", "auto"] default manual
        selection=args.selection                        # pairs sub-selection, by default all. best-mapping is recommended for the right c
    )
    # --------------------------------------------------------------------------
    #                    options       (for rapid tests and analysis)
    # --------------------------------------------------------------------------
    debug_options = dict(
        seaLevel = True,           # Calculate the altitude of the ground via the IGN API. If the server is unavailable makes three attempts.
        saveGpsTrack = True,       # Save the drone’s trajectory in a GPS file in Garmin format (.gpx)
        saveExcel = True,          # Save the list of pairs, GPS coordinates, angles ... in an Excel file
        savePickle = True,         # Save mission data (flight plan, shootingPts) in a binary file.
        option_alti = 'sealevel',  # Altitude GPS  for Exif data. Options: ['takeoff', 'sealevel', 'ground', 'geo']
        analysisAlignment = True,  # Analysis of "theoretical" and "coarse" alignment angles
        showAnglPlot = True,       # Display of the chart at the end of the process. The chart is automatically saved in the "Flight Analytics" folder.
        showDisperPlot = False,    # Show 2D angles dispersion plot
        createMappingList = False, # LEGACY: Create a list of best synchronous images for mapping with ODM
    )
    return {**options, **debug_options}




def parse_arguments(argv) -> argparse.Namespace:
    """
    0 > Parse command line
    ------------------------------------------------------------------------------------------------------------
    
    - Interactive choice of mission throug folder selection popup
    ------------------------------------------------------------------------------------------------------------

    Returns:
        argparse.Namespace: parsed arguments
    """
    
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
    parser.add_argument('--offset', type=str, default="manual", choices=["manual", "auto"],  help='offset angles choice - auto allows pre-computing offsets')
    args = parser.parse_args(argv)

    if args.config is None or not os.path.isfile(args.config):
        print(Style.GREEN + "File browser")
        args.config = IRd.loadFileGUI(mute=False)
    return args

def main_process(args: argparse.Namespace):
    """
    Main IRDrone processing 
    -----------------------
    - configuration based on json or xlsx + command line arguments (requires pre-synchronization phase)
    - analyze all exifs metadata and finds image pairs, selects the best matches
    - estimated alignment between visible NIR & Visible images, warp and save multispectral tifs


    Args:
        args (argparse.Namespace): 
            parsed arguments
            (potentially allows being called directly from python or a jupyter notebook aswell without command line)
    """
    # 0 > Parse arguments, prepare configuration dictionary
    conf = configure(args)
    
    # 1 > Extraction of flight data
    # --------------------------------------------------------------------------------------------------------------
    flight_data_dict = extract_flight_data(conf["config_file"])
    conf["out_images_folder"] = flight_data_dict["out_images_folder"]
    conf["timelapse_vis_interval"] = flight_data_dict["timelapse_vis_interval"]
    if conf["timelapse_vis_interval"] <= 0:
        conf["selection"] = "all"
    
    # 2 > Find all matching pairs of images from both cameras
    # 3 > Then retrieve metadata from exifs & altitudes
    #[4]> Pre-compute angles offset and add
    # --------------------------------------------------------------------------------------------------------------
    shooting_pts_list = find_all_matching_pairs(flight_data_dict)
    gather_metadata(flight_data_dict, shooting_pts_list, conf)
    if conf["offset"] == "auto":
        offset_angles, _ = auto_angles_offset_pre_computation(flight_data_dict, shooting_pts_list, configuration=conf)
        IRd.add_offset_theoretical_angles(shooting_pts_list, offset=offset_angles)
    
    # 5 > Selection of frames
    # --------------------------------------------------------------------------------------------------------------
    shooting_pts_selection = select_matching_pairs(flight_data_dict, shooting_pts_list, configuration=conf, selection_option=conf.get("selection", "all"))
    
    # 6 > Image processing.
    # --------------------------------------------------------------------------------------------------------------
    matched_images_paths_selection = list(map(lambda pt: (pt.Vis, pt.Nir), shooting_pts_selection))
    image_processing_engine(matched_images_paths_selection, shooting_pts_selection, odm_multispectral=conf["odm_multispectral"], traces=conf["traces"], configuration=conf)
    
    # 7 > Open Drone Map - [NOT REQUIRED WHEN ODM MULTISPECTRAL MODE]
    # --------------------------------------------------------------------------------------------------------------
    if conf["createMappingList"]:
        legacy_prepare_odm_postprocessing(shooting_pts_selection, configuration=conf)
    
    # 8 > Analysis
    # --------------------------------------------------------------------------------------------------------------
    analyzis(flight_data_dict, shooting_pts_list, configuration=conf)


if __name__ == "__main__":
    # --------------------------------------------------------------------------------------------------------------
    #       Start of calculation time measurement.
    # --------------------------------------------------------------------------------------------------------------
    timeDebut = datetime.datetime.now()
    startTime = time.process_time()
    print(Style.CYAN + 'INFO : ------ Start IRdrone-v%s  at  %s ' % (versionIRdrone, timeDebut.time()) + Style.RESET)
    args = parse_arguments(sys.argv[1:])
    main_process(args)
    # -------------------------------------------------------------------------------------------------------------
    #        End of calculation time measurement.
    # -------------------------------------------------------------------------------------------------------------
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    # -------------------------------------------------------------------------------------------------------------
    #        Logo
    # -------------------------------------------------------------------------------------------------------------
    IRd.logoIRDrone(num=4)
    print(
        Style.CYAN + '\n INFO : End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
