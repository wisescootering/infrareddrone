# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703

"""
Created on 2021-10-05 19:17:16

@authors: balthazar/alain
"""

import irdrone.process as pr
import irdrone.utils as ut
from irdrone.utils import Style
import utils_GPS as uGPS
import os
import sys
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from operator import itemgetter
import datetime
import matplotlib.pyplot as plt
import openpyxl
from openpyxl import Workbook


# -----   Convertisseurs de dates   Exif<->Python  Excel->Python    ------


def dateExif2Py(exifTag):
    """

    :param exifTag: données Exif d'une image
    :return: datePhotoPython     (datetime python)

       Extraction de la date  de la prise de photo à partir de ses données Exif
       La date est fournie par  l'horloge de la caméra.
       Format Exif  YYYY:MM:DD  hh:mm:ss  type string
       Puis conversion en datetime python en analysant la chaine de caractère Exif
       On récupère Year Month Day Hour Min et Second  de type string
       Il faut convertir les string en integer (via la fonction int()  )

       Attention la clé Exif à utiliser est 'DateTimeOriginal'
       La clé Exif 'DateTime' indique la date de création du fichier sur l'ordinateur!
       La valeur de la clé 'DateTimeOriginal' est une chaine de caractères (string) 'YYYY:MM:DD  hh:mm:ss'
       Il faut extraire de cette chaine les valeurs numériques (integer) DD,MM,YYYY,hh,mm,ss
       puis construire une date "python" datetime.datetime(YYYY,MM,DD,hh,mm,ss,micross). Sous cette
       forme on peut manipuler les dates. En particulier on peut connaître  la durée entre deux
       dates  (en seconde). Il est aussi possible de connaître le nom du jour et du mois.

    """

    dateTimeOriginal = exifTag.get('DateTimeOriginal')  # date exacte de la prise de vue
    imgYear = int(dateTimeOriginal[0:4])
    imgMonth = int(dateTimeOriginal[5:7])
    imgDay = int(dateTimeOriginal[8:11])
    imgHour = int(dateTimeOriginal[11:13])
    imgMin = int(dateTimeOriginal[14:16])
    imgSecond = int(dateTimeOriginal[17:19])
    imgMicroSecond = 0
    # construction de la date python
    #  Rem: Pour accéder aux éléments individuels de la date python
    #       datePhotoPython.year(.month | .day | .hour | .minute | .second | .microseconde)
    #
    datePy = datetime.datetime(imgYear, imgMonth, imgDay, imgHour, imgMin, imgSecond, imgMicroSecond)

    return datePy


def datePy2Exif(datePy):
    """

    :param datePy:    (Year, Month, Day, Hour, Minute, Second, Microsecond, timezone)
    :return: dateExif  str  format  YYYY:MM:DD hh:mm:ss
    """
    dateExif = str(datePy.year) + ':' + str(datePy.month) + ':' + str(datePy.day) + ' ' + \
               str(datePy.hour) + ':' + str(datePy.minute) + ':' + str(datePy.second)
    return dateExif


def dateExif2Excel(dateExif):
    """

    :param dateExif:   str format  YYYY:MM:DD hh:mm:ss
    :return: dateExcel str format  YYYY-MM-DD hh:mm:ss
    """
    date = dateExif.split(' ')[0].split(':')
    date.extend(dateExif.split(' ')[1].split(':'))
    dateExcel = str(date[0]) + '-' + str(date[1]) + '-' + str(date[2]) + ' ' + \
                str(date[3]) + ':' + str(date[4]) + ':' + str(date[5])

    return dateExcel


def dateExcel2Py(dateExcel):
    """

    :param dateExcel:    str    format  YYYY-MM-DD hh:mm:ss
    :return: datePy     (Year, Month, Day, Hour, Minute, Second, Microsecond, timezone)
    """
    imgYear = int(dateExcel[0:4])
    imgMonth = int(dateExcel[5:7])
    imgDay = int(dateExcel[8:11])
    imgHour = int(dateExcel[11:13])
    imgMin = int(dateExcel[14:16])
    imgSecond = int(dateExcel[17:19])
    imgMicroSecond = 0
    # construction de la date python
    #  Rem: Pour accéder aux éléments individuels de la date python
    #       datePhotoPython.year(.month | .day | .hour | .minute | .second | .microseconde)
    #
    datePy = datetime.datetime(imgYear, imgMonth, imgDay, imgHour, imgMin, imgSecond, imgMicroSecond)
    return datePy


# ------------------     Plan de Vol      ------------------------------


def readFlightPlan(pathPlanVolExcel, mute=None):
    """
        Read the Flight Plan  in Excel file.

    :param pathPlanVolExcel: chemin du fichier Excel qui contient le plan de vol  (string)
           mute : affiche des informatios si True  (utile en phase debug)
    :return: planVol  Dictionnaire contenant les données du plan de vol  (dic)
    """
    workbook = openpyxl.load_workbook(pathPlanVolExcel, read_only=True, data_only=True)

    sheet = workbook['Plan_de_Vol']

    nuetude = 2  # 2      numéro première ligen de données du fichier Excel
    nudrone = (nuetude + 8) + 1  # 2+8+1 =11
    nucameraIR = (nudrone + 7) + 1  # 11+7+1=19
    nuimages = (nucameraIR + 5) + 1  # 19+5+1=25
    numeteo = (nuimages + 11) + 1  # 25+11+1=37
    planVol = {'mission':
                   {'client': sheet.cell(nuetude + 1, 2).value,
                    'lieu': sheet.cell(nuetude + 2, 2).value,
                    'coord GPS Take Off': sheet.cell(nuetude + 3, 2).value,
                    'altitude Take 0ff': sheet.cell(nuetude + 4, 2).value,
                    'date': sheet.cell(nuetude + 5, 2).value,  # ' DD-MM-YYYY  hh:mm:ss
                    'heure_solaire': sheet.cell(nuetude + 6, 2).value,
                    'numero_du_vol': sheet.cell(nuetude + 7, 2).value,
                    'pilote': sheet.cell(nuetude + 8, 2).value
                    },
               'drone':
                   {'marque': sheet.cell(nudrone + 1, 2).value,
                    'type': sheet.cell(nudrone + 2, 2).value,
                    'timelapse': sheet.cell(nudrone + 3, 2).value,
                    'deltatime': sheet.cell(nudrone + 4, 2).value,
                    'imatriculation': sheet.cell(nudrone + 5, 2).value,
                    'altitude  de vol': sheet.cell(nudrone + 6, 2).value,
                    'synchro horloges': sheet.cell(nudrone + 7, 2).value  # libre
                    },
               'cameraIR':
                   {'marque': sheet.cell(nucameraIR + 1, 2).value,
                    'type': sheet.cell(nucameraIR + 2, 2).value,
                    'timelapse': sheet.cell(nucameraIR + 3, 2).value,
                    'deltatime': sheet.cell(nucameraIR + 4, 2).value,
                    'synchro horloges': sheet.cell(nucameraIR + 5, 2).value  # libre
                    },
               'images':
                   {'repertoireViR  (save)': sheet.cell(nuimages + 1, 2).value,
                    'repertoireDrone': sheet.cell(nuimages + 2, 2).value,
                    'extDrone': sheet.cell(nuimages + 3, 2).value,
                    'filtreDrone': sheet.cell(nuimages + 4, 2).value,
                    'libre_1': sheet.cell(nuimages + 5, 2).value,  # libre
                    'libre_2': sheet.cell(nuimages + 6, 2).value,  # libre
                    'repertoireIR': sheet.cell(nuimages + 7, 2).value,
                    'extIR': sheet.cell(nuimages + 8, 2).value,
                    'filtreIR': sheet.cell(nuimages + 9, 2).value,
                    'libre_3': sheet.cell(nuimages + 10, 2).value,  # libre
                    'libre_4': sheet.cell(nuimages + 11, 2).value  # libre
                    },
               'meteo':
                   {'ensoleillement': sheet.cell(numeteo + 1, 2).value,
                    'vent': sheet.cell(numeteo + 2, 2).value,
                    'temperature': sheet.cell(numeteo + 3, 2).value,
                    'humidite': sheet.cell(numeteo + 4, 2).value
                    }
               }
    workbook.close()

    if not mute:
        printPlanVol(planVol)

    return planVol


def extractFlightPlan(dirPlanVol, mute=True):
    """
    Extract the datas of Fligth Plan
    > Chemin des images Visible et IR, type de drone et de caméra, synchroniation horloges ...
    > Images list of Drone and IR cameras

    :param dirPlanVol:  path of Fligth Plan in  a Excel
               mute : affiche des informatios si True  (utile en phase debug)
    :return: (planVol,imgListDrone,deltaTimeDrone,timeLapseDrone,imgListIR,deltaTimeIR,timeLapseIR,
    dirNameIRdrone,coordGPS_TakeOff,altiTakeOff)   )
    """
    planVol = readFlightPlan(dirPlanVol, mute=mute)
    dirNameIRdrone = planVol['images']['repertoireViR  (save)']  # folder for save photography  VIR,  NDVI (output)
    dirNameDrone = planVol['images']['repertoireDrone']  # Drone photography folder   (input)
    dirNameIR = planVol['images']['repertoireIR']  # IR photography folder (input)
    dateMission = planVol['mission']['date']  # date of flight > format DD MM et YYYY
    typeDrone = planVol['drone']['type']  # type of drone (see in the Exif tag of the image of the drone)
    extDrone = planVol['images']['extDrone']  # file format Vi
    typeIR = planVol['cameraIR']['type']  # type of camera in use (see in the Exif tag of the image of the IR camera)
    timeLapseDrone = float(planVol['drone']['timelapse'])  # Time Lapse of Drone camera
    timeLapseIR = float(planVol['cameraIR']['timelapse'])  # Time Lapse of IR camera
    extIR = planVol['images']['extIR']  # file format  IR
    deltaTimeDrone = float(planVol['drone']['deltatime'])  # decalage horloge caméra du drone / horloge de référence
    deltaTimeIR = float(planVol['cameraIR']['deltatime'])  # decalage horloge caméra infrarouge /horloge de référence

    #    Liste des images de l'étude.
    #    Une liste pour les images du drone et une liste pour les images de la caméra infrarouge
    #    Chaque élément de la liste est un triplet (file name image , path name image, date image)
    print('Liste des images de l\'étude')
    dirNameDrone = reformatDirectory(dirNameDrone, xlpath=dirPlanVol)
    dirNameIR = reformatDirectory(dirNameIR, xlpath=dirPlanVol, makeOutdir=True)
    dirNameIRdrone = reformatDirectory(dirNameIRdrone, xlpath=dirPlanVol, makeOutdir=True)
    print('Liste des images VIS de l\'étude')
    imgListDrone = creatListImg(dirNameDrone, dateMission, typeDrone, '*', extDrone, planVol)
    print('Liste des images IR de l\'étude')
    imgListIR = creatListImgIR(dirNameIR, '*', extIR)
    if not mute:
        if len(imgListDrone) == 0:
            print('No visible images detected for this flight.')
            sys.exit(2)
        else:
            print('%i visible images detected for this flight.' % len(imgListDrone))
            print([(imgListDrone[i][0], imgListDrone[i][2]) for i in range(len(imgListDrone))])

        if len(imgListIR) == 0:
            print('No near infrared images detected for this flight.')
            sys.exit(2)
        else:
            print('%i near infrared images detected for this flight.' % len(imgListIR))
            print([(imgListIR[i][0], imgListIR[i][2]) for i in range(len(imgListIR))])

        if len(imgListDrone) == 0 and len(imgListIR) == 0:
            print('%i visible images (Vi) and %i near infrared images (NiR) for this flight.' %
                  (len(imgListDrone), len(imgListIR)))

    return planVol, imgListDrone, deltaTimeDrone, timeLapseDrone, \
           imgListIR, deltaTimeIR, timeLapseIR, dirNameIRdrone


def creatListImgIR(dirName, camera, typImg):
    """
    :return:  imgList   [(),...,(file name image , path name image, date image),...,()]
    """
    # Création de la liste des photos IR  (extension donnée  RAW) et contenues dans le répertoire dirName
    # Si camera="*' alors la liste comporte toutes les images avec l'extension typeImg (ici RAW)
    # Pour une  SJcam M20 on extrait la date du nom du fichier  ...
    # car les données Exif du fichier RAW de SJCam sont illisibles par exifread ou bien PIL.ExifTags ???
    #
    imlist = sorted(ut.imagepath(imgname="*%s*.%s" % (camera, typImg), dirname=dirName))
    imgList = []
    for i in range(len(imlist)):
        nameImg = imlist[i].split('\\')[len(imlist[i].split('\\')) - 1]
        imgYear = int(nameImg[0:4])
        imgMonth = int(nameImg[5:7])
        imgDay = int(nameImg[7:9])
        imgHour = int(nameImg[10:12])
        imgMin = int(nameImg[12:14])
        imgSecond = int(nameImg[14:16])
        imgMicroSecond = 0
        dateImg = datetime.datetime(imgYear, imgMonth, imgDay, imgHour, imgMin, imgSecond, imgMicroSecond)
        imgList.append((nameImg, imlist[i], dateImg))  # ajout à la liste des images

    imgList = sorted(imgList, key=itemgetter(2), reverse=False)  # tri par la date de prise de vue
    return imgList


def creatListImg(dirName, dateMission, cameraModel, camera, typImg, planVol, debug=False):
    """
    :param dirName:
    :param dateMission:
    :param cameraModel:
    :param camera:
    :param typImg:
    :param debug:
    :return:  imgList   [(), ...,(file name image , path name image, date image), ..., ()]
    """

    # Création de la liste des photos (extension donnée  ex: JPG, DNG) et contenues dans le répertoire dirName
    # Si camera="*' alors la liste comporte toutes les images avec l'extension typeImg
    # Si camera ='DJI'  la liste filtre les images prises par le drone
    # Pas possible de filtrer les images SJcam avec le non du fichier  (il faut regarder les données Exif de l'image)
    imlist = sorted(ut.imagepath(imgname="*%s*.%s" % (camera, typImg), dirname=dirName))

    imgList = []
    j = 0
    for i in range(len(imlist)):
        img = pr.Image(imlist[i])
        img.camera["timelapse"] = float(planVol['drone']['timelapse'])
        img.camera["deltatime"] = float(planVol['drone']['deltatime'])
        try:
            """
            extraction des données Exif de l'image
            si pas de données Exif image ignorée.
            """
            debug = True
            cameraModelImg = img.camera['model']

            if cameraModelImg == cameraModel:  # images prises par d'autres caméras. images ignorées
                dateImg = img.date
                print(img.name,'  dateImg  ',dateImg)
                if (dateImg.year, dateImg.month, dateImg.day) == (dateMission.year, dateMission.month, dateMission.day):
                    j += 1
                    nameImg = imlist[i].split('\\')[len(imlist[i].split('\\')) - 1]
                    imgList.append((nameImg, imlist[i], dateImg))  # ajout à la liste des images
                else:
                    if debug: print(Style.YELLOW,
                                    '%s a été prise le %i %i %i. Cette date est différente de celle de la mission %i %i %i'
                                    % (imlist[i], dateImg.day, dateImg.month, dateImg.year, dateMission.day,
                                       dateMission.month,
                                       dateMission.year), Style.RESET)
            else:
                if debug: print(Style.YELLOW,
                                '%s a été prise par un autre  appareil (Model %s) ' % (imlist[i], cameraModelImg),
                                Style.RESET)
        except:
            if debug: print("No Exif tags in %s" % imlist[i])

    imgList = sorted(imgList, key=itemgetter(2), reverse=False)  # tri par la date de prise de vue
    return imgList


def printPlanVol(planVol):
    print(' Vol à : %s  (%s)  du %s   '
          '\n Client : %s'
          '\n Pilote : %s sur drone %s'
          '\n Caméra Vi : %s'
          '\n Timelaps  : %s  s    DeltaTime %s  s'
          '\n Caméra IR: %s'
          '\n Timelaps  : %s  s    DeltaTime %s  s'
          '\n Filtre infrarouge  IR %i nm'
          '\n Météo : %s  Vent %.1f m/s  Température %.1f °C' %
          (planVol['mission']['lieu'],
           (planVol['mission']['coord GPS Take Off'] + '  ' + str(planVol['mission']['altitude Take 0ff']) + ' m'),
           planVol['mission']['date'],
           planVol['mission']['client'],
           planVol['mission']['pilote'],
           (planVol['drone']['marque'] + ' ' + planVol['drone']['type']),
           planVol['drone']['marque'],
           planVol['drone']['timelapse'], planVol['drone']['deltatime'],
           (planVol['cameraIR']['marque'] + '  ' + planVol['cameraIR']['type']),
           planVol['cameraIR']['timelapse'], planVol['cameraIR']['deltatime'],
           planVol['images']['filtreIR'],
           planVol['meteo']['ensoleillement'], float(planVol['meteo']['vent']), float(planVol['meteo']['temperature'])
           )
          )
    return

# ------------------     Appairement des images      ---------------------


def matchImagesFlightPath(imgListDrone,
                          deltaTimeDrone,
                          timeLapseDrone,
                          imgListIR,
                          deltaTimeIR,
                          timeLapseIR,
                          dateMission,
                          timeDeviationFactor=0.5,
                          mute=False):
    """
    :param imgListDrone:  [...,(file name, path name, date), ...]
    :param deltaTimeDrone:
    :param timeLapseDrone
    :param imgListIR:     [...,(file name, path name, date), ...]
    :param deltaTimeIR:
    :param timeLapseIR:
    :param dateMission:   date of flight
    :param timeDeviationFactor : as a percentage of the lowest time lapse
     Value 1/2 is a good choice for timing deviation |   1/4  is very selective.
    :param mute:
    :return:  listImgMatch   [..., (imgListDrone[i][1], imgListIR[k][1]), ...]
    """

    if timeLapseDrone <= 0:
        # if timeLapseDrone=0 or -1 the photos are taken in manual mode
        repB = 'IR'
        repA = 'drone'
        imgListB = imgListIR
        imgListA = imgListDrone
        deltaTimeB = deltaTimeIR
        deltaTimeA = deltaTimeDrone
        timeDeviation = timeDeviationFactor * 2.1  # 2s is the weakest time lapse of the drone DJI-Mavic-Air2 (jpeg+dng)

    elif timeLapseDrone > timeLapseIR:
        # unwise !
        repA = 'drone'
        repB = 'IR'
        imgListA = imgListDrone
        imgListB = imgListIR
        deltaTimeA = deltaTimeDrone
        deltaTimeB = deltaTimeIR
        timeDeviation = timeDeviationFactor * timeLapseIR

    else:
        # timeLapseDrone =< timeLapseIR    This is the best configuration  (2s DJI | 3s SJCam M20]
        repB = 'IR'
        repA = 'drone'
        imgListB = imgListIR
        imgListA = imgListDrone
        deltaTimeB = deltaTimeIR
        deltaTimeA = deltaTimeDrone
        timeDeviation = timeDeviationFactor * timeLapseDrone

    n = 0
    nRejet = 0
    listImgMatch = []
    DtImgMatch =[]
    dateA = [imgListA[i][2] for i in range(len(imgListA))]
    dateB = [imgListB[k][2] for k in range(len(imgListB))]
    deltaTime = [[datetime.timedelta.total_seconds(dateB[k] - dateA[i]) + deltaTimeA - deltaTimeB
                  for k in range(len(imgListB))] for i in range(len(imgListA))]
    DTime =[[abs(deltaTime[i][k]) for k in range(len(imgListB))] for i in range(len(imgListA))]

    for i in range(len(imgListA)):
        kBmatch=0
        for k in range(len(imgListB)):
            if abs(deltaTime[i][k])== min(DTime[i][:]) and abs(deltaTime[i][k])< timeDeviation:
                kBmatch = k
                n += 1
                DtImgMatch.append(deltaTime[i][k])

        if kBmatch == 0:
            # No match for type B image
            nRejet += 1
            if not mute: print(Style.YELLOW + 'INFO:  Image ', repA, ' ', imgListA[i][0],
                                   ' does not match any image ', repB,
                                   '.  Minimum time deviation = ',
                               round(min(DTime[i][:]), 2), 's' + Style.RESET)
            pass
        else:
            #  construction of the image pair IR & Vi
            if timeLapseDrone >= timeLapseIR:
                listImgMatch.append((imgListB[kBmatch][1], imgListA[i][1]))
            else:
                listImgMatch.append((imgListA[i][1], imgListB[kBmatch][1]))



            if not mute:
                    print(Style.GREEN + 'N°', n, ' DT ', round(min(DTime[i][:]), 2), 's   ',
                          imgListA[i][0], ' | ', imgListB[kBmatch][0] + Style.RESET)

    if timeLapseDrone >= timeLapseIR:
        print(Style.GREEN + '%i pairs of Visible-Infrared images were detected for the flight on  %s' % (
            len(listImgMatch), dateMission), '\n',
              '%i images  %s  have been eliminated :' % (nRejet, repA) + Style.RESET)
    else:
        print(Style.GREEN + '%i pairs of Visible-Infrared images were detected for the flight on  %s' % (
            len(listImgMatch), dateMission), '\n',
              '%i  images Vi (%s) have been eliminated :' % (nRejet, repA) + Style.RESET)

    if len(listImgMatch) == 0:
        print(Style.RED, 'No pair of Visible-Infrared images were detected for this flight.', Style.RESET)
        sys.exit(2)

    return listImgMatch, DtImgMatch


# -----------   Synthèse de informations sur la mission      --------------


def summaryFlight(listImg, DtImgMatch, planVol, seaLevel=False, dirSaveFig=None, mute=True):
    """
    :param listImg:      list of image pairs VI/IR matched at the same point
    :param mute:
    :return: summary  [... (imgNameVi,imgNameIRoriginal,imgNameIR,imgNameViR, dateVi,
                          imgLat, imgLon, imgAltGround , imgAltSeaLevel ,imgAltRef,
                          distToLastPt,capToLastPt   ) ...]                   list
        imgNameVi---------------------- file name of visible RGB color image at point P
        imgNameIRoriginal-------------- file name of original infrared image  at point P
        imgNameIR---------------------- file name of infrared image  (match with visible image at point P)
        imgNameViR -------------------- file name of multispectral image at point P
        dateVi ------------------------ date the visible image was shot             [YY-MM-DD hh:mm:ss]
        imgLat, imgLon, imgAltGround    GPS coordinates of point P                  [°],[°],[m]
        imgAltSeaLevel ---------------  altitude of the drone in relation to the sealevel [m]
        imgAltRef---------------------- altitude of the drone relative to take-off point  (DJI ref)  [m]
        distToLastPt------------------- distance to next point                                       [m]
        capToLastPt-------------------- direction to the next point relative to the geographic north [°]

        lists the essential elements of flight after treatment by IRdrone.
        This data will be saved in the Excel file of the flight plan  (sheet "Summary")

    For all points of the list, the altitudes of the ground relative to the sea level are determined..
    For France the code uses the API of the IGN (national geographical institute)
    Warning : this API limits the number of points that can be sent in the request
    An attempt is made. If the ground elevation relative to sea level fails, it is set at zero.
    https://geoservices.ign.fr/documentation/services/api-et-services-ogc/calcul-altimetrique-rest
    For each request the IGN API accepts in theory 5000 pts. In practice 189 works but 199 fails!

    """
    print(Style.CYAN + 'Request to  https://wxs.ign.fr/essentiels/alti/rest/elevation')
    summary = []
    listPtGPS = []
    listCoordGPS = []
    distP0P1 = []
    capP0P1 = []
    altGeo = []
    altDroneSol = []
    altDroneSealLevel = []
    altGround = []
    distFlight = []
    dateVi = []

    maxPas = 99
    if len(listImg) < maxPas:
        pas = len(listImg) - 1
    else:
        pas = maxPas

    for i in range(len(listImg)):
        img = pr.Image(listImg[i][0])
        listPtGPS.append((img.gps['latitude'][4], img.gps['longitude'][4]))
        listCoordGPS.append((img.gps['latitude'][4], img.gps['longitude'][4], img.gps['altitude']))
        dateVi.append(img.date)
    if seaLevel:
        # take-off point altitude relative to sea level
        coordGPSTakeOff, altiTakeOff = uGPS.TakeOff(planVol['mission']['coord GPS Take Off'])
        if altiTakeOff < 0:
            altiTakeOff = 0
        #  Splitting the list of points into multiple segments because the number of points in the IGN API is limited.
        for k in range(0, int(round(len(listImg), 0) / pas) + 1):
            list = listPtGPS[k * pas:(k + 1) * pas]
            altGeo += uGPS.altitude_IGN(list)
            print(Style.CYAN, '%i / %.0f ' % (k, len(listImg) / pas), Style.RESET)

    else:
        altGeo = [0.0] * len(listPtGPS)
        altiTakeOff = 0.

    #  Calculates the distance and heading between point P0 and the next point P1
    for i in range(len(listImg) - 1):
        imgDist, imgCap = uGPS.segmentUTM(listPtGPS[i][0], listPtGPS[i][1], listPtGPS[i + 1][0], listPtGPS[i + 1][1])
        distP0P1.append(imgDist)
        capP0P1.append(imgCap)
    distP0P1.append(0)  # no distance or heading to the next point for landing point!
    capP0P1.append(0)  # arbitrarily set the value to 0

    for i in range(len(listImg)):
        if not mute:
            print('altitudes : drone / takeOff %f m | sol/ sea level %f m |  drone /sol %f m'
                  % (listCoordGPS[i][2], altGeo[i], round(listCoordGPS[i][2] + altiTakeOff - altGeo[i], 5)))
        # drone altitude relative to ground and sea level
        altDroneSol.append(round(listCoordGPS[i][2] + altiTakeOff - altGeo[i], 5))
        altGround.append(altGeo[i])  # ground elevation relative to sea level
        altDroneSealLevel.append(altGeo[i] + altDroneSol[i])
        distToLastPt = round(distP0P1[i], 2)  # distance to next point   (accuracy to cm!)
        if i == 0:
            distFlight.append(0.)
        else:
            distFlight.append(distFlight[i - 1] + distToLastPt)

        capToLastPt = round(capP0P1[i], 3)
        # Vi images
        imgNameViOriginal = listImg[i][0].split('\\')[len(listImg[i][0].split('\\')) - 1]
        str =imgNameViOriginal.split('_')[1]
        numeroRef = str.split('.')[0]
        imgViExt = str.split('.')[1]
        recordType = imgNameViOriginal.split('_')[0]  # DJI (single shoot), TIMELAPSE, HYPERLASE, PANORAMIC  etc
        imgNameVIS ='%s_%s_VIS.jpg' % (recordType,numeroRef)
        # IR images
        imgNameIRoriginal = listImg[i][1].split('\\')[len(listImg[i][1].split('\\')) - 1]
        imgNameNIR = '%s_%s_NIR_local_.jpg' % (recordType,numeroRef)
        imgNameViR = '_VIR_local_%s_%s.jpg ' % (recordType,numeroRef)

        summary.append(
            (imgNameViOriginal, imgNameIRoriginal, round(DtImgMatch[i],2), imgNameVIS, imgNameNIR, imgNameViR,
             dateVi[i],
             round(listCoordGPS[i][0], 5), round(listCoordGPS[i][1], 5),
             altDroneSol[i], round(altGeo[i], 3), round(listCoordGPS[i][2], 3),
             distToLastPt, capToLastPt, round(distFlight[i], 2)
             )
        )

    showFlightProfil(distFlight, altDroneSealLevel, altGround, dirSaveFig=dirSaveFig, mute=False)

    if not mute:
        txtSummary = 'List of images of the flight:'
        for i in range(len(listImg)):
            txtSummary = txtSummary + '\n' + str(summary[i])
        print(Style.GREEN + txtSummary + Style.RESET)

    return summary


def writeSummaryFlight(flightPlanSynthesis, pathName, saveExcel=False):
    """

     Write the Flight Plan Summary in Excel file
    If the file not exist the file FlightSummary.xlsx  is create withe one sheet (sheetname = Summary)

    :param flightPlanSynthesis:
    :param pathName:
    :param saveExcel: save data in Excel file if True
    :return:


    """
    pathName=os.path.join(os.path.join(os.path.dirname(pathName)), 'FlightSummary.xlsx')
    if os.path.isfile(pathName):
        pass
    else:
        print(Style.YELLOW + ' Create file FlightSummary.xlsx'+ Style.RESET)
        wb = Workbook()
        ws=wb.active
        ws.title = "Summary"
        wb.save(pathName)

    if saveExcel:
        workbook = openpyxl.load_workbook(pathName)
        listSheets = workbook.sheetnames
        if listSheets[0] != 'Summary':
            print(Style.YELLOW + ' Create sheet Summary' + Style.RESET)
            ws_sum = workbook.create_sheet("Summary", 0)
            ws_sum.title = "Summary"
            ws_sum.protection.sheet = False
        else:
            pass

        sheet = workbook['Summary']
        sheet.protection.sheet = False
        sheet.delete_rows(2,1000)
        listHeadCol = ['Point',
                       'Image                    Visible             (original)',
                       'Image                    Infrared            (original)',
                       'Time deviation              [s]',
                       'Image                    Visible aligned',
                       'Image                    Infrared aligned',
                       'Image                    Multi-Spectral ViR',
                       'Date of shooting.',
                       'Latitude                dd°dddddd',
                       'Longitude               dd°dddddd',
                       'Drone Altitude     / ground         [m]',
                       'Ground Elevation   / sea level      [m]',
                       'Drone Altitude     / Take off       [m]',
                       'Distance point suivant  [°]',
                       'Cap point suivant',
                       'Distance / Start Pt      [m]'
                       ]
        for k in range(len(listHeadCol)):
            sheet.cell(1, k + 1).value = listHeadCol[k]
        for i in range(len(flightPlanSynthesis)):
            sheet.cell(i + 2, 1).value = i+1
            for k in range(len(flightPlanSynthesis[i])):
                sheet.cell(i + 2, k + 2).value = flightPlanSynthesis[i][k]
        sheet.protection.sheet = False
        workbook.save(pathName)
        workbook.close()
        print(Style.GREEN + 'Ecriture du résumé du vol dans %s  terminée.' % pathName + Style.RESET)


def showFlightProfil(d_list, elev_Drone, elev_Ground, dirSaveFig=None, mute=True):
    # BASIC STAT INFORMATION
    min_elev = min(elev_Ground)

    # PLOT ELEVATION PROFILE
    base_reg = min_elev - 10
    plt.figure(figsize=(10, 4))
    plt.plot(d_list, elev_Drone, '.r', label='Drone: ', linewidth=1, linestyle='dashed', markersize=0)
    plt.plot(d_list, elev_Ground, 'tab:brown', label='Ground ')
    plt.fill_between(d_list, elev_Ground, base_reg, color='tab:brown', alpha=0.1)
    plt.text(d_list[0], elev_Drone[0], "Start Pt")
    plt.text(d_list[-1], elev_Drone[-1], "End Pt")
    plt.xlabel("Distance (m)")
    plt.ylabel("Altitude (m)")
    plt.grid()
    plt.legend(fontsize='small')
    filepath = dirSaveFig + '\\Flight profil IRdrone'
    if dirSaveFig == None:
        pass
    else:
        plt.savefig(filepath, dpi=75, facecolor='w', edgecolor='w', orientation='portrait',
                    format=None, transparent=False,
                    bbox_inches='tight', pad_inches=0.1, metadata=None)
        print(Style.GREEN + 'Save flight profil in %s' % filepath + Style.RESET)
    if not mute:
        print(Style.YELLOW + 'Look your Drone Flight profil >>>>' + Style.RESET)
        plt.show()
    plt.close()

# ------------------     Gestion des fichiers      ---------------------


def reformatDirectory(di, xlpath=None, makeOutdir=False):
    if os.path.exists(di):
        return di
    else:
        if xlpath is not None:
            newdi = os.path.join(os.path.dirname(xlpath), di)
            return reformatDirectory(newdi, xlpath=None, makeOutdir=makeOutdir)
        if makeOutdir:
            os.mkdir(di)
            print("creating output dir: %s" % di)
            return di

    raise NameError("Cannot find directory %s" % di)


def loadFileGUI(mute=True):
    Tk().withdraw()  # we don't want a full GUI, so keep the root window from appearing
    filename = askopenfilename()  # show an "Open" dialog box and return the path to the selected file
    if not mute: print(filename)
    return filename


def answerYesNo(txt):
    ans = input(txt)
    tryAgain=True
    countTry =0
    while tryAgain:
        try:
            ans = int(ans)
            if ans !=1 and ans != 0:
                raise ValueError
            else:
                ans = bool(int(ans))

            return ans

        except ValueError:
            try:
                if countTry < 2 :
                    print('You need to type 0 or 1' )
                    ans = input(txt)
                else:
                    return
            except:
                return ans
            else:
                countTry += 1
                tryAgain = True



