# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-12 19:02:16
v 1.05
@authors: balthazar/alain
"""

import utils_IRdrone as IRd
import utils_GPS as uGPS
from irdrone.utils import Style
import datetime
import time
import os
import argparse
import os.path as osp
import automatic_registration

if __name__ == "__main__":
    # --------------------------------------------------------------------------------------------------------------
    #                    Initialisation de la mesure du temps de calcul.
    # --------------------------------------------------------------------------------------------------------------
    versionIRdrone = '1.06'  # 31 december 2021
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

    # --------------------------------------------------------------------------
    #                    options pour les tests rapides
    # --------------------------------------------------------------------------
    seaLevel = True            # Calculer l'altitude du sol  ... API internet (peut échouer si serveur indisponible)
    saveGpsTrack = True        # Sauvegarder la trajectoire du drone dans un fichier gps au format Garmin@
    saveSummary = True         # Sauvegarder la liste des paires ainsi que les coordonnées GPS dans un fichier Excel
    seeDualImages = False      # Vvérifier visuellement les appariements sur l'écran (en phase de test)

    # --------------------------------------------------------------------------------------------------------------
    # 1 > Extraction des données du vol
    #     Date, heure, dossier d'images, synchro des horloges, type du drone et de la caméra IR ...
    #     Construction de la liste des images prises lors du vol (Drone et IR)
    # --------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Read flight plan' + Style.RESET)
    planVol, imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR, deltaTimeIR, timeLapseIR, dirNameIRdrone = \
        IRd.extractFlightPlan(dirPlanVol, mute=True)

    # --------------------------------------------------------------------------------------------------------------
    # 2 > Appariement des images des deux caméras
    #     On cherche les paires d'images Vi et IR prises au "même instant".
    #     On peut éventuellement visualiser les paires d'images  IR et Vi.
    #     Ces images sont  sauvegardées dans le dossier  dirNameIRdrone
    #     qui a été spécifié dans le plan de vol  (.xlxs)
    #
    # Note:   > les images de type A sont celles qui ont le plus petit timelapse ou  ...
    #         pas de time Lapse du tout (timelapse_A < 0  valeur fixée  dans le fichier Excel FlightPlan.xlsx)
    #         > les images de type B sont celles qui ont le plus grand timelapse  (timelapse_B > timelapse_A ).
    #   Pour qu'une image A_j soient considérées comme synchronisées avec une image B_k on teste deux critères :
    #
    #   > Au plus proche (nearest)
    #     Choisi parmi les images {B_k} celle qui à la différence de date (deltaTime) minimum avec l'image A_j
    #     ET
    #   > Retient la paire {A_j,B_k} si deltaTime < timeDeviation
    #
    #    la tolérance  (timeDeviation) est calculée par la formule :  timeDeviation = timeDeviationFactor * timeLapseA
    #           Rappelons que timeLapse_A est le timeLapse minimum.
    #           Si il n'y a pas de time lapse (photos DJI prises à la volée)
    #           on fixe arbitrairement timeDeviation = timeDeviationFactor * 2.1
    #           (2s est le delai mini d'enregistrement du  DJI).
    #
    #    Remarque: en réalité quelque soit l'image A_j on a  (sauf peut-être pour la première image ?)
    #                          - timelapse_B / 2 <=   min(deltaTime)   <= + timelapse_B / 2
    #
    #   - Construction de  la trace GPS qui relie les points où ont été prises les paires d'images. (file format .gpx)
    #         (l'altitude est celle du drone / au pt de décollage)
    #   - Ecriture dans la feuille Summary du fichier Excel Plan de Vol
    #   - Tracé du profil de vol du drone dans une figure (file format .png)
    # -------------------------------------------------------------------------------------------------------------
    print(Style.CYAN + '------ Matching images VIS & NIR' + Style.RESET)
    listImgMatch, DtImgMatch, listdateMatch = IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone,
                                                                        imgListIR,
                                                                        deltaTimeIR, timeLapseIR,
                                                                        planVol['mission']['date'],
                                                                        timeDeviationFactor=2., mute=True)
    # ------ Calcule  la trajectoire du drone et le profil du vol
    #        Calcule yaw et pitch  théorique de l'image NIR vers VIS.


    print(Style.CYAN + '------ Calculation of drone trajectory and flight profile' + Style.RESET)
    flightPlanSynthesis = IRd.summaryFlight(listImgMatch, DtImgMatch, listdateMatch, planVol, seaLevel=seaLevel,
                                            dirSaveFig=osp.dirname(dirPlanVol), mute=True)


    IRd.writeSummaryFlight(flightPlanSynthesis, dirPlanVol, saveExcel=saveSummary)
    if saveGpsTrack:      # save GPS Track in Garmin format (.gpx)
        uGPS.writeGPX(listImgMatch, os.path.dirname(dirPlanVol)+'\\Topo', planVol['mission']['date'], mute=True)
    # -------------------------------------------------------------------------------------------------------------
    # 3 > Traitement des images
    #     Recalage des paires d'images Vi et IR
    #     Construction des images RiV  et NDVI
    # -------------------------------------------------------------------------------------------------------------
    print(Style.YELLOW + 'The processing of these %i images will take %.2f h.  Do you want to continue?'
          % (len(listImgMatch), 1.36 * len(listImgMatch) / 60.) + Style.RESET)
    autoRegistration = IRd.answerYesNo('Yes (1) |  No (0):')
    # listImgMatch = [(vis.replace(".DNG", "_PL4_DIST.tif"), nir) for vis, nir in listImgMatch]
    if autoRegistration:
        print(Style.CYAN + '------ automatic_registration.process_raw_pairs' + Style.RESET)
        automatic_registration.process_raw_pairs(listImgMatch[::1], out_dir=dirNameIRdrone)
    else:
        print(
            Style.YELLOW + 'Warning :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)

    # -------------------------------------------------------------------------------------------------------------
    # 4 > Résumé du traitement
    # -------------------------------------------------------------------------------------------------------------




    # -------------------------------------------------------------------------------------------------------------
    #        Fin  de la mesure du temps de calcul.
    # -------------------------------------------------------------------------------------------------------------
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    print(
        Style.CYAN + 'End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
