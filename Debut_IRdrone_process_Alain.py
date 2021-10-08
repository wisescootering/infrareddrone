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
from tkinter import Tk
from tkinter.filedialog import askopenfilename
import argparse
import sys
import os.path as osp
import automatic_registration


# ----------------------      ------------------------------------


def loadFileGUI():
    Tk().withdraw()  # we don't want a full GUI, so keep the root window from appearing
    filename = askopenfilename()  # show an "Open" dialog box and return the path to the selected file
    print(filename)
    return filename


if __name__ == "__main__":

    # ----------------------------------------------------
    # 0 > Choix interactif du vol
    #
    parser = argparse.ArgumentParser(description='Process Flight Path excel')
    parser.add_argument('--excel', metavar='excel', type=str, help='path to the flight path xlsx')
    args = parser.parse_args()
    dirPlanVol = args.excel
    if dirPlanVol is None or not os.path.isfile(dirPlanVol):
        print(Style.CYAN + "File browser")
        dirPlanVol = loadFileGUI()
    versionIRdrone = '1.03'  # 02 october 2021
    # ------------ pour test rapide -----------------
    seaLevel = True  # True   pour calculer l'altitude du sol  ... API internet (peut échouer si serveur indispo)
    seeDualImages = False  # True pour vérifier visuellement les appariements sur l'écran (en phase de test)

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
    dateMission = planVol['mission']['date']

    # ----------------------------------------------------
    # 2 > Appariement des images des deux caméras
    #     On cherche les paires d'images Vi et IR prises au même instant.
    #     On peut éventuellement visualiser les paires d'images  IR et Vi.
    #     Ces images sont  sauvegardées dans le dossier  dirNameIRdrone
    #     qui a été spécifié dans le plan de vol  (.xlxs)
    #
    #   - Construction de  la trace GPS qui relie les points où ont été prises les paires d'images. (file format .gpx)
    #         (l'altitude est celle du drone / au pt de décollage)
    #   - Ecriture dans la feuille Summary du fichier Excel Plan de Vol
    #   - Tracé du profil de vol du drone dans une figure (file format .png)

    listImgMatch = IRd.matchImagesFlightPath(imgListDrone, deltaTimeDrone, timeLapseDrone,
                                             imgListIR, deltaTimeIR, timeLapseIR, dateMission, mute=True)

    if len(listImgMatch) == 0:
        print('0 couples d\'images Visible-InfraRouge ont été détectés pour ce vol')
        sys.exit(2)
    # ------ Calcule de la trajectoire du drone et du profil du vol
    #        Génère la trajectoire au format Garmin gpx

    print(Style.CYAN + '------ Calcule de la trajectoire du drone et du profil du vol' + Style.RESET)
    flightPlanSynthesis = IRd.summaryFlight(listImgMatch, planVol, seaLevel=True,
                                            dirSaveFig=osp.dirname(dirPlanVol), mute=True)
    IRd.writeSummaryFlight(flightPlanSynthesis, dirPlanVol)
    uGPS.writeGPX(listImgMatch, dirNameIRdrone, dateMission, mute=True)  # écriture  du tracé GPS au format gpx Garmin

    # -----------------------------------------------------
    #  3 > Traitement des images
    #     Recalage des paires d'images Vi et IR
    #     Construction des images RiV  et NDVI
    # ----------------------------------------------------

    automatic_registration.process_raw_pairs(listImgMatch, out_dir=dirNameIRdrone)
    # -----------------------------------------------------
    # 4 > Résumé du traitement
    # ----------------------------------------------------
    #        Fin du programme
    timeFin = datetime.datetime.now()
    stopTime = time.process_time()
    tempsExe = stopTime - startTime
    print(
        Style.CYAN + 'End IRdrone-v%s  at %s   CPU : %3.f s' % (versionIRdrone, timeFin.time(), tempsExe) + Style.RESET)
