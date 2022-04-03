# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
version 1.05 2021-12-01
version 1.06 2021-12-31 16:41:05.   Theoritical Yaw,Pitch,Roll for NIR images
version 1.07 2022-02-17 21:58:00    Class ShootPoint. Save Summary Flight in binary file  (pickle)
@authors: balthazar/alain
"""

import utils_IRdrone as IRd
from irdrone.utils import Style
import datetime
import time
import os
import argparse
import os.path as osp
import automatic_registration
import AnalysePitchYawRoll as analys

if __name__ == "__main__":
    # --------------------------------------------------------------------------------------------------------------
    #                    Initialisation de la mesure du temps de calcul.
    # --------------------------------------------------------------------------------------------------------------
    versionIRdrone = '1.07'  # 15 fevrier 2022
    timeDebut = datetime.datetime.now()
    startTime = time.process_time()
    print(Style.CYAN + 'Start IRdrone-v%s  at  %s ' % (versionIRdrone, timeDebut.time()) + Style.RESET)

    # ------------------------------------------------------------------------------------------------------------
    # 0 > Choix interactif de la mission
    # ------------------------------------------------------------------------------------------------------------
    parser = argparse.ArgumentParser(description='Process Flight Path excel')
    parser.add_argument('--excel', metavar='excel', type=str, help='path to the flight path xlsx')
    args = parser.parse_args()
    dirPlanVol = args.excel
    if dirPlanVol is None or not os.path.isfile(dirPlanVol):
        print(Style.CYAN + "File browser")
        dirPlanVol = IRd.loadFileGUI(mute=False)

    dirMission = os.path.dirname(dirPlanVol)


    # --------------------------------------------------------------------------
    #                    options pour les tests rapides
    # --------------------------------------------------------------------------
    seaLevel = True        # Calculer l'altitude du sol  ... API internet (peut échouer si serveur indisponible)
    saveGpsTrack = False   # Sauvegarder la trajectoire du drone dans un fichier gps au format Garmin@
    saveExcel = True       # Sauvegarder la liste des paires, les coordonnées GPS, les angles ... dans un fichier Excel
    savePickle = True      # Sauvegarder les données de la mission (plan vol, listPts) dans un fichier binaire.
    createMappingList = True  # Create a list of best synchronous images for mapping with ODM
    #  options des courbes pour l'analyse
    coarseProcess = False
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
    # -------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Matching images VIS & NIR' + Style.RESET)
    listImgMatch, DtImgMatch, listdateMatch, listPts = \
        IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR, deltaTimeIR, timeLapseIR,
                                  planVol['mission']['date'], mute=True)
    IRd.summaryFlight(listPts, listImgMatch, planVol, dirPlanVol,
                      seaLevel=seaLevel,
                      dirSaveFig=osp.dirname(dirPlanVol),
                      saveGpsTrack=saveGpsTrack,
                      saveExcel=saveExcel,
                      savePickle=savePickle,
                      createMappingList=createMappingList,
                      mute=True)
    # -------------------------------------------------------------------------------------------------------------
    # 3 > Traitement des images.
    #     Recalage des paires d'images Vi et IR.
    #     Construction des images ViR  et NDVI.
    # -------------------------------------------------------------------------------------------------------------
    print(Style.YELLOW + 'The processing of these %i images will take %.2f h.  Do you want to continue?'
          % (len(listPts), 1.36 * len(listPts) / 60.) + Style.RESET)
    autoRegistration = IRd.answerYesNo('Yes (1) |  No (0):')
    # listImgMatch = [(vis.replace(".DNG", "_PL4_DIST.tif"), nir) for vis, nir in listImgMatch]
    if autoRegistration:
        print(Style.CYAN + '------ automatic_registration.process_raw_pairs' + Style.RESET)
        automatic_registration.process_raw_pairs(listImgMatch[::1], out_dir=dirNameIRdrone)
    else:
        print(
            Style.YELLOW + 'Warning :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)

    # -------------------------------------------------------------------------------------------------------------
    # 4 > Analyse
    #   Trace les angles Roll, Pitch et Yaw  (roulis, tangage & lacet)
    #     pour le drone, le gimbal et l'image NIR (coarse process et théorique)
    # -------------------------------------------------------------------------------------------------------------

    # Correction angles de visée.
    corrige_defaut_axe_visee = True
    if corrige_defaut_axe_visee:
        offsetPitch = 1.30    # défaut d'alignement (pitch) de l'axe de visée de la caméra NIR  en °
        offsetYaw = 1.02      # défaut d'alignement (yaw) de l'axe de visée de la caméra NIR    en °
    else:
        offsetPitch = 0
        offsetYaw = 0

    # Pitch --- Yaw ----------------------------------- Mission -----------------------------------------------------
    # 2.03 °   0.83 °   06 septembre 2021   U = 0,5 m/s  hyperlapse auto | vent faible (très légères rafales)
    # 1.33 °   0.90 °   06 septembre 2021   U = 1,0 m/s  hyperlapse auto | vent faible
    # 0.50 °   0.90 °   08 septembre 2021   U = 1,0 m/s  hyperlapse auto | beaucoup de rafales de vent !
    # 1.30 °   0.90 °   OK 09 novembre  2021   U = 1,0 m/s  hyperlapse auto | vent très faible | longue séquence :-)
    # 1.63 °   0.25 °   OK 18 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | test synchro
    # 1.92 °   0.41 °   OK 25 janvier   2022   U = 1,5 m/s  hyperlapse libre| vent nul | Support du cas TEST pour GitHub
    # 1.30 °   1.02 °   OK Peyrelevade-P 2 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # 1.30 °   1.02 °   OK Peyrelevade-P 1 (hyperlapse libre U=1,5m/s)  très peu de vent (quelques petites rafales)
    # 2.57 °   0.20 °   0K 25 janvier   2022   phase de Synchro  hyperlapse libre| vent nul |

    if autoRegistration:
        print(Style.CYAN + 'Construction of drone attitude data.' + Style.RESET)
        utilise_cache = False
    else:
        print(Style.MAGENTA + 'Do you want to use cached data?' + Style.RESET)
        utilise_cache = IRd.answerYesNo('Yes (1) |  No (0):')

    analys.plotYawPitchRollDroneAndCameraDJI(dirMission,
                                      utilise_cache=utilise_cache,
                                      offsetPitch=offsetPitch,
                                      offsetYaw=offsetYaw,
                                      showAngleCoarseProcess=coarseProcess,
                                      showTheoreticalAngle=theoreticalAngle,
                                      showGap=gap,
                                      showSpectralAnalysis=spectralAnalysis,
                                      showDispersion=dispersion,
                                      showRefined=refined
                                      )

    # -------------------------------------------------------------------------------------------------------------
    #        Fin  de la mesure du temps de calcul.
    # -------------------------------------------------------------------------------------------------------------
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    print(
        Style.CYAN + 'End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
