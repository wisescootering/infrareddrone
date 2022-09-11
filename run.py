# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
version 1.05 2021-12-01
version 1.06 2021-12-31 16:41:05.   Theoritical Yaw,Pitch,Roll for NIR images
version 1.07 2022-02-17 21:58:00    Class ShootPoint. Save Summary Flight in binary file  (pickle)
@authors: balthazar/alain
"""

import logging
import utils.angles_analyzis as analys
import utils.utils_IRdrone as IRd
from utils.utils_odm import odm_mapping_optim
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
    parser = argparse.ArgumentParser(description='Process Flight Path excel')
    parser.add_argument('--config', type=str, help='path to the flight configuration')
    parser.add_argument('--clean-proxy', action="store_true", help='clean proxy tif files to save storage')
    parser.add_argument('--disable-altitude-api', action="store_true", help='force not using altitude from IGN API')
    args = parser.parse_args()
    clean_proxy = args.clean_proxy
    dirPlanVol = args.config
    if dirPlanVol is None or not os.path.isfile(dirPlanVol):
        print(Style.CYAN + "File browser")
        dirPlanVol = IRd.loadFileGUI(mute=False)

    dirMission = os.path.dirname(dirPlanVol)


    # --------------------------------------------------------------------------
    #                    options       (for rapid tests and analysis)
    # --------------------------------------------------------------------------
    seaLevel = True        # Calculer l'altitude du sol  ... API internet (peut échouer si serveur indisponible)
    saveGpsTrack = True    # Sauvegarder la trajectoire du drone dans un fichier gps au format Garmin@
    saveExcel = True       # Sauvegarder la liste des paires, les coordonnées GPS, les angles ... dans un fichier Excel
    savePickle = True      # Sauvegarder les données de la mission (plan vol, listPts) dans un fichier binaire.
    createMappingList = True  # Create a list of best synchronous images for mapping with ODM
    option_alti = 'sealevel'  # Altitude GPS  for Exif data. Options: ['takeoff', 'sealevel', 'ground', 'geo']
    #  options des courbes pour l'analyse
    corrige_defaut_axe_visee = True
    coarseProcess = True
    theoreticalAngle = False
    gap = False
    spectralAnalysis = False
    dispersion = False
    refined = False  # Attention extraction des homographies pour construire le cache ... long

    # --------------------------------------------------------------------------------------------------------------
    # 1 > Extraction des données du vol
    #     Date, heure, dossier d'images, synchro des horloges, type du drone et de la caméra IR ...
    #     Construction de la liste des images prises lors du vol (Drone et IR)
    # --------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Read flight plan' + Style.RESET)
    planVol, \
    imgListDrone, deltaTimeDrone, timeLapseDrone, \
    imgListIR, deltaTimeIR, timeLapseIR, dirNameIRdrone = \
        IRd.extractFlightPlan(dirPlanVol, mute=True)

    print("deltaTimeIR    ", deltaTimeIR, "  First image shooting at  ", planVol["mission"]["date"])
    
    # --------------------------------------------------------------------------------------------------------------
    # 2 > Appariement des images des deux caméras
    #     On cherche les paires d'images Vi et IR prises au "même instant".
    #     On peut éventuellement visualiser les paires d'images  IR et Vi.
    #     Ces images sont  sauvegardées dans le dossier  dirNameIRdrone
    #     qui a été spécifié dans le plan de vol  (FlightPlan_*.xlxs)
    #
    # Note:   > les images de type A sont celles qui ont le plus petit timelapse ou  ...
    #         pas de time Lapse du tout (timelapse_A < 0  valeur fixée  dans le fichier Excel FlightPlan.xlsx)
    #         > les images de type B sont celles qui ont le plus grand timelapse  (timelapse_B > timelapse_A ).
    #   Pour qu'une image A_j soient considérées comme synchronisées avec une image B_k on utilise le critère
    #   au plus proche (nearest):
    #   Choisi parmi les images {B_k} celle qui à la différence de date (deltaTime) minimum avec l'image A_j
    #
    #   - Construction de la trace GPS entre les paires d'images. (file format .gpx)
    #   - Ecriture des données dans des fichiers Excel et Binaires.
    #   - Tracé du profil de vol du drone  (file format .png)
    #
    # Offset theoritical angles
    # [Yaw, Pitch,Roll]  -------------------------------- Mission ------------------------------------------------
    # [0.83,  2.03, 0.]  06 septembre 2021   U = 0,5 m/s  hyperlapse auto | vent faible (très légères rafales)
    # [0.90,  1.33, 0.]  06 septembre 2021   U = 1,0 m/s  hyperlapse auto | vent faible
    # [0.90,  0.50, 0.]  08 septembre 2021   U = 1,0 m/s  hyperlapse auto | beaucoup de rafales de vent !
    # [0.90,  1.30, 0.]  OK 09 novembre  2021   U = 1,0 m/s  hyperlapse auto | vent très faible | longue séquence :-)
    # [0.25,  1.63, 0.]  OK 18 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | test synchro
    # [0.33,  1.81, 0.]  OK 25 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | Support cas TEST pour GitHub
    # [0.86,  1.43, 0.]  OK Peyrelevade-P 2 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # [1.02,  1.30, 0.]  OK Peyrelevade-P 1 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # [0.20,  2.57, 0.]  0K 25 janvier   2022   phase de Synchro  hyperlapse libre| vent nul |
    # -------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Matching images VIS & NIR' + Style.RESET)
    synchro_date = planVol['mission']['date']
    if synchro_date is None:
        raise NameError(Style.RED + "Synchro start date needs to be provided!" + Style.RESET)
    listPts = None # process_raw_pairs shall work with None listPts
    listImgMatch, DtImgMatch, listdateMatch, listPts = \
        IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR, deltaTimeIR, timeLapseIR,
                                  synchro_date, mute=True)
    try:
        # Fixed the alignment defect [yaw,pitch,roll] of the NIR camera aiming axis in °
        offsetTheoretical = [0., 0., 0.]          # default set
        if corrige_defaut_axe_visee:
            offsetTheoretical = [0.86,  1.43, 0.]   # offset Yaw, Pitch, Roll for theoretical angles

        mappingList = IRd.summaryFlight(listPts, listImgMatch, planVol, dirPlanVol,
                        offsetTheoreticalAngle=offsetTheoretical,
                        seaLevel=seaLevel,
                        dirSaveFig=osp.dirname(dirPlanVol),
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

    print(Style.YELLOW + 'The processing of these %i images will take %.2f h.  Do you want to continue?'
          % (len(listPts), 1.36 * len(listPts) / 60.) + Style.RESET)
    autoRegistration = IRd.answerYesNo('Yes (y/1) |  No (n/0):')
    
    if autoRegistration:
        print(Style.CYAN + '------ automatic_registration.process_raw_pairs' + Style.RESET)
        automatic_registration.process_raw_pairs(listImgMatch[::1], out_dir=dirNameIRdrone, crop=CROP, listPts=listPts, option_alti=option_alti, clean_proxy=clean_proxy)
    else:
        print(
            Style.YELLOW + 'Warning :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)

    # -------------------------------------------------------------------------------------------------------------
    # 4 > Open Drone Map
    #      Prepare ODM folders (with .bat, images and camera calibrations)
    # -------------------------------------------------------------------------------------------------------------

    for ext in ["VIS", "NIR_local", "NDVI__local", "VIR__local"]:
        odm_image_directory = odm_mapping_optim(dirMission, dirNameIRdrone, multispectral_modality=ext, mappingList=mappingList)

    # -------------------------------------------------------------------------------------------------------------
    # 5 > Analysis
    #     Draws roll, pitch and Yaw angles (roll, pitch & yaw)
    #     for the drone, the gimbal and the NIR image (coarse process and theoretical)
    # -------------------------------------------------------------------------------------------------------------

    if autoRegistration:
        print(Style.CYAN + 'Construction of drone attitude data.' + Style.RESET)
        utilise_cache = False
    else:
        print(Style.YELLOW + 'Do you want to use cached data?' + Style.RESET)
        utilise_cache = IRd.answerYesNo('Yes (y/1) |  No (n/0):')

    analys.plotYawPitchRollDroneAndCameraDJI(dirMission,
                                      utilise_cache=utilise_cache,
                                      showAngleCoarseProcess=coarseProcess,
                                      showTheoreticalAngle=theoreticalAngle,
                                      showGap=gap,
                                      showSpectralAnalysis=spectralAnalysis,
                                      showDispersion=dispersion,
                                      showRefined=refined
                                      )

    # -------------------------------------------------------------------------------------------------------------
    #        End of calculation time measurement.
    # -------------------------------------------------------------------------------------------------------------
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    print(
        Style.CYAN + 'End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
