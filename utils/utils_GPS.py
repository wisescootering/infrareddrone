# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703

"""
Created on 2021-10-05 19:17:16

@authors: balthazar/alain
"""

import numpy as np
import math
import re
import json
import requests
from irdrone.utils import Style
import irdrone.process as pr
import os


# ========================================
# =          Utilities for  GPS          =
# ========================================


def dstUTM(lat1, lon1, lat2, lon2):
    """
    param lat1: latitude  point P1  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon1: longitude point P1  dd.ddddddd   ( < 0 si W  > 0 si E )
    param lat2: latitude  point P2  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon2: longitude point P2  dd.ddddddd   ( < 0 si W  > 0 si E )

    return:  dstUTM  Euclidean distance between P1 and P2  in m

    x1: Point P1  UTM coordinate W-E
    y1: Point P1  UTM coordinate S-N
    x2: Point P2  UTM coordinate W-E
    y2: Point P2  UTM coordinate S-N

    Calculation of the distance between two points P1 and P2 on the earth surface.
    We assume that the earth is an ellipsoid  (WGS84).
    A compliant transverse Mercator projection is used. (UTM means Universal Transverse Mercator projection)
    Points are identified by their geocentric coordinates latitude,longitude (input).
    Geocentric coordinates are converted to UTM coordinates x,y.
    The transverse projection of Mercator is a conformal map.
    Conformal map is a function that locally preserves angles, but not necessarily lengths.
    In other words, it's therefore easy to determine the direction between two points
    relative to the geographic north.
    In the (x,y) plan we can use the Euclidean distance.
    The approximation is excellent in each UTM zone.
    """
    x1, y1, zoneUTM1 = geo2UTM(lat1, lon1)
    x2, y2, zoneUTM1 = geo2UTM(lat2, lon2)
    dstUtm = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
    return dstUtm


def capUTM(lat1, lon1, lat2, lon2):
    """
    param lat1: latitude  point P1  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon1: longitude point P1  dd.ddddddd   ( < 0 si W  > 0 si E )
    param lat2: latitude  point P2  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon2: longitude point P2  dd.ddddddd   ( < 0 si W  > 0 si E )

    return:    capUTM  heading between P1 and P2 from the geographic north

    x1: Point P1  UTM coordinate W-E
    y1: Point P1  UTM coordinate S-N
    x2: Point P2  UTM coordinate W-E
    y2: Point P2  UTM coordinate S-N
    """
    x1, y1, zoneUTM1 = geo2UTM(lat1, lon1)
    x2, y2, zoneUTM1 = geo2UTM(lat2, lon2)
    cap = 0.
    if y1 == y2:
        if x1 > x2:
            cap = 270.
        else:
            cap = 90.
    else:
        if (y2 - y1) > 0 and (x2 - x1) >= 0:  # cadran N°1  N / E
            cap = np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) < 0 <= (x2 - x1):  # cadran N°2  E / S
            cap = 180 - np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) < 0 and (x2 - x1) <= 0:  # cadran N°3  S / W
            cap = 180. + np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) > 0 >= (x2 - x1):  # cadran N°4  W / N
            cap = 360. - np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        else:
            pass
    return cap


def geo2UTMSimple(lat, lon):
    """
    param lat: latitude  point P  dd.ddddddd   (<0 si S  >0 si N )
    param lon: longitude point P  dd.ddddddd   (<0 si W  >0 si E )
    return: xUTM, yUTM  UTM coordinates in m

    Conversion of geocentric coordinates to UTM coordinates.
    https://fr.wikipedia.org/wiki/Transverse_universelle_de_Mercator

    Values for test
                lat = 5°50'51"     lon= 45°09'33"
                lat= 5.8475 °      lon= 45.1591667°
                fuseau 31  [0°, 6°]   lamb0=3°
                lamb-lamb0= 0.0496983 rad
                AA= 0.0350442107
                BB= 1.00169
                C= 0.0033510263
                T= 1.01117395
                S= 0.784340804
                xUTM= 723.80393 km  yUTM= 5004.57704 km
                xUTM= 723803.93 m   yUTM= 5004577.04 m
    """
    a = 6378137.000  # equatorial radius in m
    f = 1. / 298.257223563

    e2 = 2. * f - f ** 2  # if e  is eccentricity  e2 = e **2
    K0 = 0.9996
    zoneUTM = math.floor((lon + 180.) / 6.) + 1  # N° fuseau UTM

    phi = np.deg2rad(lat)  # convert Degrees to Radians
    lamb = np.deg2rad(lon)
    lamb0 = np.deg2rad((zoneUTM - 30) * 6. - 3.)  # longitude of the center of the UTM zone
    #
    BB = 1. / (1 - e2 * (np.sin(phi)) ** 2) ** 0.5
    AA = (lamb - lamb0) * np.cos(phi)
    S1 = (1. - e2 / 4. - 3. * (e2 ** 2) / 64. - 5. * (e2 ** 3) / 256.) * phi
    S2 = -(3. * e2 / 8. + 3. * (e2 ** 2) / 32. + 45. * (e2 ** 3) / 1024.) * np.sin(2. * phi)
    S3 = (15. * (e2 ** 2) / 256. + 45. * (e2 ** 3) / 1024.) * np.sin(4. * phi)
    S4 = -(35. * (e2 ** 3) / 3072.) * np.sin(6. * phi)
    S = S1 + S2 + S3 + S4
    T = (np.tan(phi)) ** 2
    C = (e2 / (1. - e2)) * (np.cos(phi)) ** 2

    if phi >= 0.:
        N0 = 0
    else:
        N0 = 10000000.

    xUTM = 500000. + K0 * a * BB * (AA + (1 - T + C) * (AA ** 3) / 6. + (5. - 18. * T + T ** 2) * (AA ** 5) / 120)
    yUTM = N0 + K0 * a * (S + BB * np.tan(phi) * (
            (AA ** 2) / 2. + (5 - T + 9 * C + 4 * C ** 2) * (AA ** 4) / 24. + (61. - 58. * T + T ** 2) *
            (AA ** 6) / 720.))

    return xUTM, yUTM, zoneUTM


def geo2UTM(lat, lon):
    """
    param lat: latitude  point P  dd.ddddddd   (<0 si S  >0 si N )
    param lon: longitude point P  dd.ddddddd   (<0 si W  >0 si E )
    return: xUTM, yUTM  UTM coordinates in m

    Conversion of geocentric coordinates to UTM coordinates.
    They are accurate to around a millimeter within 3000 km of the central meridian.
    https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system

    Values for test
                lat = 5°50'51"     lon= 45°09'33"
                lat= 5.8475 °      lon= 45.1591667°
                fuseau 31  [0°, 6°]   lamb0=3°
                lamb-lamb0= 0.0496983 rad
                AA= 0.0350442107
                BB= 1.00169
                C= 0.0033510263
                T= 1.01117395
                S= 0.784340804
                xUTM= 723.80393 km  yUTM= 5004.57704 km
                xUTM= 723803.93 m   yUTM= 5004577.04 m
    """
    a = 6378137.000  # equatorial radius in meter
    f = 1. / 298.257223563
    K0 = 0.9996

    zoneUTM = math.floor((lon + 180.) / 6.) + 1  # N° zone UTM
    phi = np.deg2rad(lat)  # convert Degrees to Radians
    if phi >= 0.:
        N0 = 0
    else:
        N0 = 10000000.

    lamb = np.deg2rad(lon)
    lamb0 = np.deg2rad((zoneUTM - 30) * 6. - 3.)  # longitude of the center of the UTM zone
    E0 = 500000  # in meter
    n = f / (2 - f)
    A = (a / (1. + n)) * (1. + 1. / 4 * n ** 2 + 1. / 64 * n ** 4)
    t = np.sinh(np.arctanh(np.sin(phi))
                - (2. * np.sqrt(n) / (1. + n)) * np.arctanh((2. * np.sqrt(n) / (1. + n)) * np.sin(phi))
                )
    zeta = np.arctan(t / np.cos(lamb - lamb0))
    eta = np.arctanh(np.sin(lamb - lamb0) / np.sqrt(1. + t ** 2))

    x0 = E0 + K0 * A * eta
    x1 = (1. / 2 * n - 2. / 3 * n ** 2 + 5. / 16 * n ** 3) * np.cos(2 * zeta) * np.sinh(2 * eta)
    x2 = (13. / 48 * n ** 2 - 3. / 5 * n ** 3) * np.cos(4 * zeta) * np.sinh(4 * eta)
    x3 = (61. / 240 * n ** 3) * np.cos(6 * zeta) * np.sinh(6 * eta)
    y0 = N0 + K0 * A * zeta
    y1 = (1. / 2 * n - 2. / 3 * n ** 2 + 5. / 16 * n ** 3) * np.sin(2 * zeta) * np.cosh(2 * eta)
    y2 = (13. / 48 * n ** 2 - 3. / 5 * n ** 3) * np.sin(4 * zeta) * np.cosh(4 * eta)
    y3 = (61. / 240 * n ** 3) * np.sin(6 * zeta) * np.cosh(6 * eta)

    xUTM = x0 + K0 * A * (x1 + x2 + x3)
    yUTM = y0 + K0 * A * (y1 + y2 + y3)

    return xUTM, yUTM, zoneUTM


def UTM2geo(xUTM, yUTM, zoneUTM):
    """
    param:  xUTM     in m
    param:  yUTM     in m
    param:  zoneUTM
    return:  lat    Latitude in DD.ddddd°
    return:  lon    Longitude in DD.ddddd°


    These formulae are truncated version of Transverse Mercator:
    flattening series, which were originally derived by Johann Heinrich Louis Krüger in 1912.
    They are accurate to around a millimeter within 3000 km of the central meridian.
    https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system

     phi <=>  long
     lamb <=> lat
    """
    a = 6378137.000  # equatorial radius in m
    f = 1. / 298.257223563
    K0 = 0.9996
    N0 = 0  #
    E0 = 500000  # in meter
    n = f / (2 - f)
    A = (a / (1. + n)) * (1. + 1. / 4 * n ** 2 + 1. / 64 * n ** 4 + 1. / 256 * n ** 6)
    #
    zeta0 = (yUTM - N0) / (K0 * A)
    eta0 = (xUTM - E0) / (K0 * A)

    zeta1 = (1. / 2 * n - 2. / 3 * n ** 2 + 37. / 96 * n ** 3) * np.sin(2 * zeta0) * np.cosh(2 * eta0)
    eta1 = (1. / 2 * n - 2. / 3 * n ** 2 + 37. / 96 * n ** 3) * np.cos(2 * zeta0) * np.sinh(2 * eta0)
    zeta2 = (1. / 48 * n ** 2 + 1. / 15 * n ** 3) * np.sin(4 * zeta0) * np.cosh(4 * eta0)
    eta2 = (1. / 48 * n ** 2 + 1. / 15 * n ** 3) * np.cos(4 * zeta0) * np.sinh(4 * eta0)
    zeta3 = (17. / 480 * n ** 3) * np.sin(6 * zeta0) * np.cosh(6 * eta0)
    eta3 = (17. / 480 * n ** 3) * np.cos(6 * zeta0) * np.sinh(6 * eta0)

    zeta = zeta0 - (zeta1 + zeta2 + zeta3)
    eta = eta0 - (eta1 + eta2 + eta3)

    phi0 = np.arcsin(np.sin(zeta) / np.cosh(eta))
    phi1 = (2. * n - 2. / 3 * n ** 2 - 2. * n ** 3) * np.sin(2 * phi0)
    phi2 = (7. / 3 * n ** 2 - 8. / 5 * n ** 3) * np.sin(4 * phi0)
    phi3 = (56. / 15 * n ** 3) * np.sin(6 * phi0)
    phi = phi0 + phi1 + phi2 + phi3

    lamb0 = np.deg2rad(zoneUTM * 6 - 183)
    lamb = lamb0 + np.arctan(np.sinh(eta) / np.cos(zeta))

    lat = np.rad2deg(phi)
    lon = np.rad2deg(lamb)
    return lat, lon


def GPSdms2GPSdd(coord):
    """
    :param coord:   (dd,mm,ss.ssss)

    :return: coordDD    dd.dddddddd           float

    Conversion from dd° mm' ss.sssss"   en dd.dddddddd
    """
    coordDD = coord[0] + coord[1] / 60 + coord[2] / 3600
    return coordDD


def segmentUTM(lat1, lon1, lat2, lon2):
    dstUtm = dstUTM(lat1, lon1, lat2, lon2)
    capUtm = capUTM(lat1, lon1, lat2, lon2)
    return dstUtm, capUtm


def calcul_distance(latLongZ):
    """
    :param  latLongZ:   liste de coordonnées GPS des point P0,P1,P2,P3    [...,(lat,long,z),...]

    :return: distP0P1  distance entre le point Pi et le point Pi+1   (en metres)
            capP0P1   cap entre le point Pi et le point Pi+1        (en degres)

    Calcule la distance et le cap entre le points GPS d'un chemin (trk).
    """
    distP0P1 = []
    capP0P1 = []
    nPt = len(latLongZ)
    for ind in range(nPt - 1):
        distP0P1.append(dstUTM(latLongZ[ind][0], latLongZ[ind][1], latLongZ[ind + 1][0], latLongZ[ind + 1][1]))
        capP0P1.append(capUTM(latLongZ[ind][0], latLongZ[ind][1], latLongZ[ind + 1][0], latLongZ[ind + 1][1]))
    distP0P1.append(0)  # pas de distance ni de cap au point suivant pour point d'atterrissage !
    capP0P1.append(0)  # on fixe la valeur arbitrairement à 0
    return distP0P1, capP0P1


def altitude_trk(coordGPS, interpolation=0):
    """
    param:  coord_GPS   liste de tuples contenant dans l'ordre (latitude, longitude) en degres.

    return: altitude z/sol      dans l'ordre des données recues ou interpoles.        List
    return: latLongZGPS  [...,(lat, long,z), ...]  dans l'ordre des données recues ou interpoles.        List

    interpol: nombre de wpt du chemi interpole.               Integer
                            Le chemin defini par la liste coord_GPS est interpole puis les altitudes
                            de tous les points sont renvoyees.

    Utilise l'API IGN https://wxs.ign.fr/essentiels/alti/rest/elevation.json?
    """
    if not isinstance(coordGPS, list):
        raise TypeError('Les données doivent être des listes de tuples'
                        ' latitude longitude exprimés en degrés'
                        f' et non {type(coordGPS)}')
    altitude = []
    latLongZGPS = []
    longitude_formate = ""
    latitude_formate = ""
    interpol = str(interpolation * len(coordGPS))

    for donnee in coordGPS:
        latitude_formate += str(donnee[0]) + '|'
        longitude_formate += str(donnee[1]) + '|'

    latitude_formate = re.sub(r'\|$', '', latitude_formate)
    longitude_formate = re.sub(r'\|$', '', longitude_formate)

    api_url = f"https://wxs.ign.fr/essentiels/alti/rest/elevationLine.json?" \
              f"sampling={interpol}&lon={longitude_formate}&lat={latitude_formate} &indent=false"
    print(f"https://wxs.ign.fr/essentiels/alti/rest/elevationLine.json?sampling={interpol}")
    dico = json.loads(requests.get(api_url).text)
    for retour in dico['elevations']:
        altitude.append(retour['z'])
        latlongZ = (retour['lon'], retour['lat'], retour['z'])
        latLongZGPS.append(latlongZ)

    return latLongZGPS


def altitude_IGN(coordGPS, mute=True, bypass=False):
    """
    param:  coord_GPS   liste de tuples contenant dans l'ordre latitude, longitude en degres.

    return: altitude z/sol      dans l'ordre des données recues ou interpoles.        List

    Utilise l'API IGN https://wxs.ign.fr/essentiels/alti/rest/elevation.json?
    """
    if bypass:
        altitude = sealLevel(coordGPS, 0.)
        return altitude
    if not isinstance(coordGPS, list):
        raise TypeError('Les données doivent être des listes de tuples'
                        ' (latitude  , longitude ) exprimés en degrés'
                        f' et non {type(coordGPS)}')
    altitude = []
    longitude_formate = ""
    latitude_formate = ""

    for donnee in coordGPS:
        latitude_formate += str(donnee[0]) + '|'
        longitude_formate += str(donnee[1]) + '|'

    latitude_formate = re.sub(r'\|$', '', latitude_formate)
    longitude_formate = re.sub(r'\|$', '', longitude_formate)

    tries = 2
    for i in range(tries):
        try:
            api_url = f"https://wxs.ign.fr/essentiels/alti/rest/elevation.json?" \
                      f"lon={longitude_formate}&lat={latitude_formate}&zonly=true"
            if not mute:
                print(f"https://wxs.ign.fr/essentiels/alti/rest/elevation.json?")

            dico = json.loads(requests.get(api_url).text)
            if not isinstance(dico, dict):
                altitude = sealLevel(coordGPS, 0.)
            elif list(dico.keys())[0] == 'error':
                altitude = sealLevel(coordGPS, 0.)
            else:
                for retour in dico['elevations']:
                    altitude.append(retour)
                if min(altitude) < 0:
                    altitude = sealLevel(coordGPS, 0.)
            return altitude
        except:
            if i < tries - 1:
                print(Style.YELLOW + 'Try again API IGN' + Style.RESET)
                continue
            else:
                print(Style.RED +
                      'No response from web server',
                      '\n Ground level set to zero.'
                      + Style.RESET)
                altitude = sealLevel(coordGPS, 0.)
                return altitude


def sealLevel(coordGPS, hlevel):
    altitude = []
    for i in range(len(coordGPS)):
        altitude.append(hlevel)
    return altitude


def cumul_Dist(coordLatLongZ):
    """
    param:  coordLatLongZ   liste de coordonnées GPS  [...,(lat, long,z), ...]

    return:  dst   liste des distances cumulées
    """
    cumulDist = []
    sumDist = 0
    distP0P1, capP0P1 = calcul_distance(coordLatLongZ)
    for i in range(len(coordLatLongZ)):
        cumulDist.append(sumDist)
        sumDist = sumDist + distP0P1[i]
    return cumulDist


def convertGPSExif_dms2GPSdd(repSign, coord):
    """
    :param repSign: {'E','W','S','N'}          str
    :param coord:   (dd,dd,ss.ssss)
    :return: coordDD    dd.dddddddd           float

         Conversion from dd° mm' ss.sssss"   en dd.dddddddd
    """
    if repSign == "W" or repSign == "S":
        signe = -1.
    else:
        signe = 1.
    coordDD = signe * (coord[0] + (coord[1] / 60) + (coord[2] / 3600))
    return coordDD


def printGPS(gpsLatitude, gpsLongitude, gpsAltitude):
    stringgpsLong = "%s %d° %d\' %.6f\" " % (gpsLongitude[0], gpsLongitude[1], gpsLongitude[2], gpsLongitude[3])
    stringgpsLat = "%s %d° %d\' %.6f\" " % (gpsLatitude[0], gpsLatitude[1], gpsLatitude[2], gpsLatitude[3])
    stringgpsAlt = "%.2f" % gpsAltitude
    print("  Longitude :", stringgpsLong, " |  Latitude :", stringgpsLat, " | Altitude : ", stringgpsAlt, " m")
    return


def writeGPX(listPts, dirNameVol, dateEtude, mute=True):
    """
    :param listImgMatch:
    :param dirNameVol:
    :param dateEtude:
    :param mute:
    :return:
        Construction d'un fichier gpx contenant le tracé du plan de vol
        Il y a au début une tres grosse étiquette !!
    """
    print(Style.CYAN + '------ Write Garmin .gpx file' + Style.RESET)
    #  mise en forme de la date pour le format gpx Garmin
    if dateEtude.month < 10:
        monthGpx = str('0' + str(dateEtude.month))
    else:
        monthGpx = str(dateEtude.month)
    if dateEtude.day < 10:
        dayGpx = str('0' + str(dateEtude.day))
    else:
        dayGpx = str(dateEtude.day)

    dateGpx = '%i-%s-%sT00:00:00Z' % (dateEtude.year, monthGpx, dayGpx)

    #     mise en forme des coordonnées GPS pour le format gpx
    #     Il faut aussi calculer la zone GPS  définie par le domaine [maxLat,minLat]x[maxLon,minLon]
    pointTrk, maxLat, minLat, maxLon, minLon = formatCoordGPSforGpx(listPts)

    # affectation du nom du fichier  et d'une description
    nameTrkGPS = "IRdrone-%s-%s-%i" % (dayGpx, monthGpx, dateEtude.year)
    descriptionTrkGPS = str('IRdrone v01.1   Trace GPS du vol %s-%s-%i' % (dayGpx, monthGpx, dateEtude.year))

    fichierGpx = "<?xml version=\"1.0\" encoding=\"utf-8\"?>" \
                 "<gpx creator=\"IRdrone v01.1\" " \
                 "version=\"1.1\" " \
                 "xsi:schemaLocation=\"http://www.topografix.com/GPX/1/1 \" "

    fichierGpx = "{0}xmlns=\"http://www.topografix.com/GPX/1/1\" xmlns:xsi=\"" \
                 "http://www.w3.org/2001/XMLSchema-instance\" xmlns:wptx1=\"" \
                 "http://www.garmin.com/xmlschemas/WaypointExtension/v1\" xmlns:gpxtrx=\"" \
                 "http://www.garmin.com/xmlschemas/GpxExtensions/v3\" xmlns:gpxtpx=\"" \
                 "http://www.garmin.com/xmlschemas/TrackPointExtension/v1\" xmlns:gpxx=\"" \
                 "http://www.garmin.com/xmlschemas/GpxExtensions/v3\" xmlns:trp=\"" \
                 "http://www.garmin.com/xmlschemas/TripExtensions/v1\" xmlns:adv=\"" \
                 "http://www.garmin.com/xmlschemas/AdventuresExtensions/v1\" xmlns:prs=\"" \
                 "http://www.garmin.com/xmlschemas/PressureExtension/v1\" xmlns:tmd=\"" \
                 "http://www.garmin.com/xmlschemas/TripMetaDataExtensions/v1\" xmlns:vptm=\"" \
                 "http://www.garmin.com/xmlschemas/ViaPointTransportationModeExtensions/v1\" xmlns:ctx=\"" \
                 "http://www.garmin.com/xmlschemas/CreationTimeExtension/v1\" xmlns:gpxacc=\"" \
                 "http://www.garmin.com/xmlschemas/AccelerationExtension/v1\" xmlns:gpxpx=\"" \
                 "http://www.garmin.com/xmlschemas/PowerExtension/v1\" xmlns:vidx1=\"" \
                 "http://www.garmin.com/xmlschemas/VideoExtension/v1\">".format(fichierGpx)

    """
        Couleur du trait :   Red,Green,Blue,Yellow,Gray, et DarkRed, DarkGreen etc

        Attention format des dates   2021-02-11T19:00:00Z
    """

    fichierGpx = fichierGpx + "\n<metadata>\n" \
                              "<link href=\"http://www.garmin.com\">\n" \
                              "<text>Garmin International</text>\n" \
                              "</link>\n" \
                              "<time>" + dateGpx + "</time>\n" \
                                                   "<bounds maxlat=\"" + str(maxLat) + "\" maxlon=\"" + str(
        minLat) + "\" minlat=\"" + str(maxLon) + "\" minlon=\"" + str(minLon) + "\" />\n" \
                                                                                "</metadata>\n" \
                                                                                "<trk>\n" \
                                                                                "<name>" + nameTrkGPS + "</name>\n" \
                                                                                                        "<desc>" + descriptionTrkGPS + "</desc>\n" \
                                                                                                                                       "<extensions>\n" \
                                                                                                                                       "<gpxx:TrackExtension>\n" \
                                                                                                                                       "<gpxx:DisplayColor>Red</gpxx:DisplayColor>\n" \
                                                                                                                                       "</gpxx:TrackExtension>\n" \
                                                                                                                                       "</extensions>\n" \
                                                                                                                                       "<trkseg>"

    for k in range(len(listPts)):
        fichierGpx = fichierGpx + pointTrk[k]

    fichierGpx = fichierGpx + "\n</trkseg>\n" \
                              "</trk>\n" \
                              "</gpx>"

    if not mute: print(fichierGpx)

    dirpath = '%s\\TrkGpx-%s-%s-%i.gpx' % (dirNameVol, dayGpx, monthGpx, dateEtude.year)

    if not mute: print('Ecriture du fichier gpx %s' % dirpath)
    if not os.path.isdir(dirNameVol):
        os.mkdir(dirNameVol)
    with open(dirpath, "w") as fichier:
        fichier.write(fichierGpx)

    return


def formatCoordGPSforGpx(listPts):
    """
    :param listImgMatch: list of images pairs
    :return: pointTrk  list of GPS coordinates (str)    (format gpx Garmin)
             sample      '<trkpt 45.05022 3.89567 >
                          <ele>110.5</ele>
                          </trkpt>'
            maxLat, minLat, maxLon, minLon
    """
    coordGPSgpxLat, coordGPSgpxLon, coordGPSgpxAlt, pointTrk  = [], [], [], []
    for k in range(len(listPts)):
        lat = listPts[k].gpsLat
        long = listPts[k].gpsLon
        alti = listPts[k].altGeo + listPts[k].altGround
        coordGPSgpxLat.append(lat)
        coordGPSgpxLon.append(long)
        coordGPSgpxAlt.append(alti)
        pointTrk.append("\n<trkpt lat=\"%s\" lon=\"%s\">\n<ele>%s</ele>\n</trkpt>" % (lat, long, alti))
    maxLat = max(coordGPSgpxLat)
    minLat = min(coordGPSgpxLat)
    maxLon = max(coordGPSgpxLon)
    minLon = min(coordGPSgpxLon)

    return pointTrk, maxLat, minLat, maxLon, minLon


def TakeOff(coordGPS_TakeOff, bypass=False):
    """

    :param coordGPS_TakeOff:               (N DD.dddddd  E DD.dddddd)
    :return: coordGPS, alti_TakeOff       (DD.ddddddd , DD.ddddddd) , float
    """

    takeOff = []
    takeOff.append((coordGPS_TakeOff.split()[1], coordGPS_TakeOff.split()[3]))
    alti_TakeOff = altitude_IGN(takeOff, mute=True, bypass=bypass)
    coordGPS = (coordGPS_TakeOff.split()[1], coordGPS_TakeOff.split()[3], alti_TakeOff[0])
    print(Style.CYAN, 'Take Off  : %s   %s m' % (coordGPS_TakeOff, alti_TakeOff[0]), Style.RESET)

    return coordGPS, alti_TakeOff[0]
