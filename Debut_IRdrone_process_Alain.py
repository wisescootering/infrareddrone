# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
"""
Created on 2021-10-05 19:17:16

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

    # ----------------------------------------------------
    # 0 > Choix interactif de la mission
    #
    parser = argparse.ArgumentParser(description='Process Flight Path excel')
    parser.add_argument('--excel', metavar='excel', type=str, help='path to the flight path xlsx')
    args = parser.parse_args()
    dirPlanVol = args.excel
    if dirPlanVol is None or not os.path.isfile(dirPlanVol):
        print(Style.CYAN + "File browser")
        dirPlanVol = IRd.loadFileGUI()
    versionIRdrone = '1.04'  # 11 october 2021
    # ------------ options test rapide -----------------
    seaLevel = True  # pour calculer l'altitude du sol  ... API internet (peut échouer si serveur indispo)
    saveGpsTrack = True  # pour sauvegarder la trajectoire du drone dans un fichier gps au format Garmin@
    saveSummary = True  # pour sauvegarder la liste des paires ainsi que les coordonnées GPS dans un fichier Excel
    seeDualImages = False  # pour vérifier visuellement les appariements sur l'écran (en phase de test)
    autoRegistration = True  # pour lancer effectivement le traitement

    # ----------------------------------------------------
    #        Début du programme
    timeDebut = datetime.datetime.now()
    startTime = time.process_time()
    print(Style.CYAN + 'Start IRdrone-v%s  at  %s ' % (versionIRdrone, timeDebut.time()) + Style.RESET)

    # ----------------------------------------------------
    # 1 > Extraction des données du vol
    #     Date, heure, dossier d'images, synchro des horloges, type du drone et de la caméra IR ...
    #     Construction de la liste des images prises lors du vol (Drone et IR)

    planVol, imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR, deltaTimeIR, timeLapseIR, dirNameIRdrone = \
        IRd.extractFlightPlan(dirPlanVol, mute=True)

    # ----------------------------------------------------
    # 2 > Appariement des images des deux caméras
    #     On cherche les paires d'images Vi et IR prises au même instant.
    #     On peut éventuellement visualiser les paires d'images  IR et Vi.
    #     Ces images sont  sauvegardées dans le dossier  dirNameIRdrone
    #     qui a été spécifié dans le plan de vol  (.xlxs)
    #
    #
    #   - Construction de  la trace GPS qui relie les points où ont été prises les paires d'images. (file format .gpx)
    #         (l'altitude est celle du drone / au pt de décollage)
    #   - Ecriture dans la feuille Summary du fichier Excel Plan de Vol
    #   - Tracé du profil de vol du drone dans une figure (file format .png)
    #
    # Note:   les images de type A sont celles qui ont le plus petit time lapse ou pas de time Lapse  (fixé < 0 )
    #         les images de type B sont celles qui ont le plus grand tim lapse
    #         pour qu'une image A soient considérées comme synchronisées avec une image B on test deux critères :

    #   > Choix parmis les images B de celle qui à la différence de date (deltaTime) minimum avec l'image A
    #   > ET on retient la paire {A,B} si deltaTime < timeDeviation
    #
    #    la tolérance  (timeDeviation) est calculée par la formule :  timeDeviation = timeDeviationFactor * timeLapseA
    #           Rappelons que timeLapseA est le timeLapse minimum.
    #           Si pas de time lapse (photos DJI prises à la volée)
    #           on fixe arbitrairement timeDeviation = timeDeviationFactor * 2.1
    #           (2s est le delai mini d'enregistrement du  DJI ).
    #

    listImgMatch, DtImgMatch= IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone, imgListIR,
                                             deltaTimeIR, timeLapseIR, planVol['mission']['date'],
                                             timeDeviationFactor=0.48, mute=True)
    # ------ Calcule de la trajectoire du drone et du profil du vol
    #        Génère la trajectoire au format Garmin gpx

    print(Style.CYAN + '------ Calculation of drone trajectory and flight profile' + Style.RESET)
    flightPlanSynthesis = IRd.summaryFlight(listImgMatch, DtImgMatch, planVol, seaLevel=seaLevel,
                                            dirSaveFig=osp.dirname(dirPlanVol), mute=True)
    IRd.writeSummaryFlight(flightPlanSynthesis, dirPlanVol, saveExcel=saveSummary)
    if saveGpsTrack:
        uGPS.writeGPX(listImgMatch, dirNameIRdrone, planVol['mission']['date'], mute=True)  # save GPS Track

    # -----------------------------------------------------
    #  3 > Traitement des images
    #     Recalage des paires d'images Vi et IR
    #     Construction des images RiV  et NDVI
    # ------------------------------------------------%----
    print(Style.WHITE,'Voulez vous traiter ces %i images ?'%len(listImgMatch))
    autoRegistration = int(input(  'Oui (1) |  Non (0):'))
    # listImgMatch = [(vis.replace(".DNG", "_PL4_DIST.tif"), nir) for vis, nir in listImgMatch]
    if autoRegistration:
        print(Style.CYAN + '------ automatic_registration.process_raw_pairs' + Style.RESET)
        automatic_registration.process_raw_pairs(listImgMatch[::1], out_dir=dirNameIRdrone)
    else:
        print(
            Style.YELLOW + 'Warning :  automatic_registration.process_raw_pairs ... Process neutralized.' + Style.RESET)

    # -----------------------------------------------------
    # 4 > Résumé du traitement
    # ----------------------------------------------------
    #        Fin du programme
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    print(
        Style.CYAN + 'End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
