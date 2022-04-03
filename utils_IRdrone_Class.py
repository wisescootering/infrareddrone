from datetime import datetime
from datetime import timedelta
import json
import pandas as pd
import pickle
import copy


# ====================================================================================================
#                      Definition de  Class ShootPoint
# ====================================================================================================


class ShootPoint:

    def __init__(self,
                 numero=0,
                 nameVis="EIFFEL_TOWER_0000.DNG",
                 nameNir="2022_0101_130000_000.RAW",
                 visDate='2022-01-01 12:00:00',
                 nirDate='2022-01-01 12:00:00',
                 timeLine=0,
                 timeDeviation=0):
        self.num = numero
        self.Vis = nameVis
        self.Nir = nameNir
        self.dateVis = datetime.fromisoformat(visDate)
        self.dateNir = datetime.fromisoformat(nirDate)
        self.timeLine = timeLine
        self.timeDeviation = timeDeviation
        self.altGround = 324.
        self.altGeo = 357.
        self.altTakeOff = 324.
        self.gpsSN = "N"
        self.gpsWE = "E"
        self.gpsLat = 48.858370
        self.gpsLon = 2.294481
        self.gpsDist = 0
        self.gpsCap = 0
        self.gpsDistTot = 0
        self.gpsUTM_X = 448253
        self.gpsUTM_Y = 5411938
        self.gpsUTM_Zone = 31
        self.yawDrone = 0
        self.pitchDrone = 0
        self.rollDrone = 0
        self.yawGimbal = 0
        self.pitchGimbal = 0
        self.rollGimbal = 0
        self.x_1 = 0  # axis e_1          x axis
        self.x_2 = 0  # axis e_2          y axis  (drone axis)   e_3 ^ e_1 = e_2
        self.x_3 = 0  # axis e_3          z axis  bottom up
        self.yawIR2VI = 0
        self.pitchIR2VI = 0
        self.rollIR2VI = 0
        self.distStarPt = 0
        self.capLastPt = 0
        self.distLastPt = 0
        self.dic = ShootPoint.loadPoint2DicPoint(self)

    def __str__(self):
        return "___________________________________________________________________________________________________\n" \
               "Point {0} .....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDron..... \n" \
               "___________________________________________________________________________________________________\n" \
               "Visible image        :  {1}    |  Date of shooting: {3}                                            \n" \
               "Near Infrared image :   {2}    |  Date of shooting: {4}                                            \n" \
               "Time line: {5} s                                                                                   \n" \
               "Time deviation Nir to Vis: {6} s                                                                   \n" \
               "________________________Coordinate_________________________________________________________________\n" \
               "Geo: {7} {8}°  {9} {10}°                                                                           \n" \
               "UTM: x {11} m    y {12} m   zone {13}                                                              \n" \
               "Altitude: | Drone/ground {14} m | Ground/sealevel {15} m | Drone/takeoff {16} m |                  \n" \
               "To next point : Dist {29} m  | Cape {30} °  |             total distance {31} m |                  \n" \
               "______________________Displacement____________drone axis___________________________________________\n" \
               "x:  {26} m  y: {27} m  z: {28} m        Speed: |   Horizontal {32} m/s |   Ascent speed: {33} m/s |\n" \
               "________________________Attitude___________________________________________________________________\n" \
               " Drone    | yaw: {17}°  | pitch: {18}° | roll: {19}° |                                             \n" \
               " Gimbal   | yaw: {20}°  | pitch: {21}° | roll: {22}° |                                             \n" \
               " Ir to Vi | yaw: {23}°  | pitch: {24}° | roll: {25}° |                                             \n" \
            .format(self.num, self.Vis, self.Nir, self.dateVis, self.dateNir,
                    round(self.timeLine, 4), round(self.timeDeviation, 3),
                    self.gpsSN, round(self.gpsLat, 6), self.gpsWE, round(self.gpsLon, 6),
                    round(self.gpsUTM_X, 2), round(self.gpsUTM_Y,2), self.gpsUTM_Zone,
                    self.altGround, self.altGeo, self.altTakeOff,
                    self.yawDrone, self.pitchDrone, self.rollDrone,
                    self.yawGimbal, self.pitchGimbal, self.rollGimbal,
                    round(self.yawIR2VI, 5), round(self.pitchIR2VI, 5), round(self.rollIR2VI, 5),
                    round(self.x_1, 3), round(self.x_2, 3), round(self.x_3, 3),
                    round(self.gpsDist, 3), round(self.gpsCap, 3), round(self.gpsDistTot,3),
                    round((self.x_1**2 + self.x_2**2)**0.5 / 2., 3),
                    round(self.x_3 / 2., 3)
                    )


    def loadPoint2DicPoint(self):
        PointInfo = \
            {
                'Img': {
                    "num": self.num,
                    "Vis": self.Vis,
                    "Nir": self.Nir,
                    "dateVis": self.dateVis,
                    "dateNir": self.dateNir,
                    "timeLine": self.timeLine,
                    "timeDeviation": self.timeDeviation
                },
                'Attitude': {
                    'drone': {
                        "yaw": self.yawDrone,
                        "pitch": self.pitchDrone,
                        "roll": self.rollDrone
                    },
                    'gimbal': {
                        "yaw": self.yawGimbal,
                        "pitch": self.pitchGimbal,
                        "roll": self.rollGimbal
                    },
                    'IR2VI': {
                        "yaw": self.yawIR2VI,
                        "pitch": self.pitchIR2VI,
                        "roll": self.rollIR2VI
                    },
                    'displacement': {
                        "x_1": self.x_1,
                        "x_2": self.x_2,
                        "x_3": self.x_3
                    }
                },
                'GPS': {
                    "SN": self.gpsSN,
                    "Latitude": self.gpsLat,
                    "WE": self.gpsWE,
                    "Longitude": self.gpsLon,
                    "Dist Last Pt":self.gpsDist,
                    "Cap Last Pt":self.gpsCap,
                    "Dist Tot": self.gpsDistTot,
                    "UTM": {
                        "X": self.gpsUTM_X,
                        "Y": self.gpsUTM_Y,
                        "zone": self.gpsUTM_Zone
                    },
                    "alt": {
                        "ground": self.altGround,
                        "Geo": self.altGeo,
                        "takeOff": self.altTakeOff
                    }
                }
            }
        return PointInfo

    def loadDicPoint2Point(self, dic):
        self.num = dic['Img']["num"]
        self.Vis = dic['Img']["Vis"]
        self.Nir = dic['Img']["Nir"]
        self.dateVis = dic['Img']["dateVis"]
        self.dateNir = dic['Img']["dateNir"]
        self.timeLine = dic['Img']["timeLine"]
        self.timeDeviation = dic['Img']["timeDeviation"]

        self.yawDrone = dic['Attitude']['drone']["yaw"]
        self.pitchDrone = dic['Attitude']['drone']["pitch"]
        self.rollDrone = dic['Attitude']['drone']["roll"]
        self.yawGimbal = dic['Attitude']['gimbal']["yaw"]
        self.pitchGimbal = dic['Attitude']['gimbal']["pitch"]
        self.rollGimbal = dic['Attitude']['gimbal']["roll"]
        self.x_1 = dic['Attitude']['displacement']["x_1"]
        self.x_2 = dic['Attitude']['displacement']["x_2"]
        self.x_3 = dic['Attitude']['displacement']["x_3"]
        self.yawIR2VI = dic['Attitude']['IR2VI']["yaw"]
        self.pitchIR2VI = dic['Attitude']['IR2VI']["pitch"]
        self.rollIR2VI = dic['Attitude']['IR2VI']["roll"]

        self.gpsSN = dic['GPS']["SN"]
        self.gpsLat = dic['GPS']["Latitude"]
        self.gpsWE = dic['GPS']["WE"]
        self.gpsLon = dic['GPS']["Longitude"]
        self.gpsDist = dic['GPS']["Dist Last Pt"]
        self.gpsCap = dic['GPS']["Cap Last Pt"]
        self.gpsDistTot = dic['GPS']["Dist Tot"]
        self.gpsUTM_X = dic['GPS']["UTM"]["X"]
        self.gpsUTM_Y = dic['GPS']["UTM"]["Y"]
        self.gpsUTM_Zone = dic['GPS']["UTM"]["zone"]
        self.altGround = dic['GPS']["alt"]["ground"]
        self.altGeo = dic['GPS']["alt"]["Geo"]
        self.altTakeOff = dic['GPS']["alt"]["takeOff"]

    @staticmethod
    def savePtsJson(fileName, listDic=None):
        if listDic is None:
            copylistDic = []
        else:
            copylistDic = copy.deepcopy(listDic)
        listdicJson = []

        for ind, dico in enumerate(listDic):
            copylistDic[ind]['Img']['dateVis'] = str(dico['Img']['dateVis'])
            copylistDic[ind]['Img']['dateNir'] = str(dico['Img']['dateNir'])
            listdicJson.append(copylistDic[ind])
        with open(fileName, "w") as outfile:
            json.dump(listdicJson, outfile, indent=4)
        outfile.close()
        print("List of mission points saved successfully in ", fileName)

    @staticmethod
    def readPtsJson(fileName):
        def strDate2Datetime(strDate):
            """
            Convert string iso format date to python datetime format
            """
            try:
                myDate = datetime.strptime(strDate, '%Y-%m-%d %H:%M:%S.%f')
            except:
                myDate = datetime.strptime(strDate, '%Y-%m-%d %H:%M:%S')
            return myDate

        #
        dicShootingPts = []
        with open(fileName, 'r') as openfile:
            json_object = json.load(openfile)
        for num, dicPt in enumerate(json_object):
            dicPt['Img']['dateVis'] = strDate2Datetime(dicPt['Img']['dateVis'])
            dicPt['Img']['dateNir'] = strDate2Datetime(dicPt['Img']['dateNir'])
            dicShootingPts.append(dicPt)
        listPts = [ShootPoint()] * len(dicShootingPts)
        for ind in range(len(dicShootingPts)):
            listPts[ind] = ShootPoint()
            listPts[ind].loadDicPoint2Point(dicShootingPts[ind])
        return listPts

    @staticmethod
    def savePtsNpy(fileName, listDic=None):
        if listDic is None:
            listDic = []
        fh = open(fileName, 'wb')  # In binary format
        pickler = pickle.Pickler(fh, pickle.HIGHEST_PROTOCOL)
        for n in range(len(listDic)):
            pickler.dump(listDic[n])
        fh.close()
        print("List of mission points saved successfully in ", fileName)

    @staticmethod
    def readPtsNpy(fileName):
        endFile = False
        fh = open(fileName, 'rb')
        unpickler = pickle.Unpickler(fh)
        n = 0
        listPtPy = []
        while endFile is not True:
            try:
                dict1 = unpickler.load()
                listPtPy.append(ShootPoint())
                ShootPoint.loadDicPoint2Point(listPtPy[n], dict1)
                n = n + 1
            except:
                endFile = True
        fh.close()
        return listPtPy

    @staticmethod
    def expandDic(dicTree, dicFlat, newKey='', mute=True):
        if isinstance(dicTree, dict):
            for numKey in range(len(dicTree.keys())):
                cumulKey = newKey + '_' + list(dicTree.keys())[numKey]
                if newKey == '':
                    cumulKey = cumulKey.lstrip('_')
                Value = dicTree.get(list(dicTree.keys())[numKey])
                if not isinstance(Value, dict):
                    dicFlat[cumulKey] = Value
                else:
                    dicFlat = ShootPoint.expandDic(Value, dicFlat, newKey=cumulKey, mute=mute)
        return newdic


# ====================================================================================================
#      Procedures hors  class ShootPoint pour la phase de test 
# ====================================================================================================

def defaultconverter(o):
    if isinstance(o, datetime):
        return o.__str__()


def newPpoint(numero):
    # definition du dictionnaire "image" du nouveau point
    if numero > 9:
        nimgDNG = "00" + str(numero)
        nimgRAW = "0" + str(numero)
    else:
        nimgDNG = "000" + str(numero)
        nimgRAW = "00" + str(numero)

    dicPt = \
        {
            'Img':
                {"num": numero,
                 "Vis": "HYPERLAPSE_" + nimgDNG + ".DNG",
                 "Nir": "2022_0125_125011_" + nimgRAW + ".RAW",
                 "dateVis": datetime.fromisoformat('2022-01-25 11:45:17'),
                 "dateNir": datetime.fromisoformat('2022-01-25 12:35:07'),
                 "timeLine": numero * (1 + 0.01987),
                 "timeDeviation": 0.54
                 },
            'Attitude':
                {
                    'drone': {
                        "yaw": -142.8 + numero,
                        "pitch": -2.1 + numero,
                        "roll": -0.8 + numero
                    },
                    'gimbal': {
                        "yaw": -164.7 + numero / 10,
                        "pitch": -89.9 + numero / 10,
                        "roll": 0.0 + numero / 10
                    },
                    'displacement': {
                        "x_1": -0.067 + numero / 4,
                        "x_2": 2.922 + numero / 4,
                        "x_3": 0.0 + numero / 4
                    },
                    'IR2VI': {
                        "yaw": 1.12099 + numero / 2,
                        "pitch": 1.40684 + numero / 2,
                        "roll": 21.9 + numero / 2
                    }
                },
            'GPS': {
                "SN": 'N',
                "Latitude": 45.010203 + numero,
                "WE": 'E',
                "Longitude": 3.012345 + numero,
                "UTM": {
                    "X": 531429.0 + numero,
                    "Y": 5000000 + numero,
                    "zone": 31
                },
                "alt": {
                    "ground": 150.1 + numero,
                    "Geo": 550.1 + numero,
                    "takeOff": 120.12345 + numero
                }
            }
        }

    return dicPt


# ====================================================================================================
#
# ====================================================================================================
if __name__ == "__main__":
    dicShootingPts = []
    myPt_1 = ShootPoint()  # instanciation du point N°1  de la classe ShootPoint de prise de vue avec données par défaut
    # construit le dictionnaire arborescent du point N°1 à l'aide de la méthode de classe ShootPoint
    dicShootingPts = [myPt_1.loadPoint2DicPoint()]

    # Définition de nouveaux points  (Prédéfini ici  pour le test   voir def newPpoint(numero)  )
    for i in range(3, 13):
        dicPt = newPpoint(i)  # génère les données de test
        myPt = ShootPoint()  # instanciation d'un nouveau point de la classe ShootPoint (données par défaut)
        myPt.loadDicPoint2Point(dicPt)  # affectation du dictionnaire  au point N°i
        # création de la 'liste' des dictionnaires des points. La liste contient déjà le dictionnaire du point N°1
        dicShootingPts.append(myPt.loadPoint2DicPoint())

    # ----------------------------------------------------------------------------------------------------------------
    # Ecriture dans un fichier .json des données de la liste des points sous la forme d'une liste de dictionnaires.
    # Attention, d'origine ce format ne conserve pas le type datetime
    # ----------------------------------------------------------------------------------------------------------------
    fileName = "testFile.json"
    ShootPoint.savePtsJson(fileName, dicShootingPts)
    # Lecture de la liste des dictionnaires dans le fichier.json  et reconstruction de la liste des points
    listMyPt = ShootPoint.readPtsJson("testFile.json")

    for n in range(len(listMyPt)):
        if n % 3 == 0:
            print(listMyPt[n])

    # -----------------------------------------------------------------------------------------------------------------
    #   Ecriture  Csv
    # construction d'un dataframe pandas à partir de la liste des dictionnaires des points de prise de vue
    # et sauvegarde en fichier type csv. Attention les datetime sont converties en str !
    # On "applati" la structure arborescente du dictionnaire original pour le sauvegarder en format csv
    # Les clés sont donc différentes !
    # -----------------------------------------------------------------------------------------------------------------
    dicTot = []
    for n in range(len(dicShootingPts)):
        newdic = {}
        dicTot.append(ShootPoint.expandDic(dicShootingPts[n], newdic, mute=True))
    df = pd.DataFrame(dicTot)
    fileName = 'testFile.csv'
    df.to_csv('testFile.csv')
    print("List of mission points saved successfully.  ", fileName)

    # -----------------------------------------------------------------------------------------------------------------
    #   Ecriture  Lecture dans un fichier  par sérialisation du dictionnaire avec pickle (encodage)
    # -----------------------------------------------------------------------------------------------------------------

    fileName = 'testFile.npy'
    ShootPoint.savePtsNpy(fileName, dicShootingPts)
    # Lecture de la liste des dictionnaires dans le fichier.py  et reconstruction de la liste des points
    listPtPy = ShootPoint.readPtsNpy(fileName)
    for ind in range(len(listPtPy)):
        if ind % 3 == 0:
            print(listPtPy[ind])

    # -----------------------------------------------------------------------------------------------------------------
    #   exemples de manipulations sur les variables de class ShootPoint
    # -----------------------------------------------------------------------------------------------------------------
    # construction de la liste des dictionnaires contenant les données de la liste des points
    listDicPy = []
    for ind in range(len(listPtPy)):
        listDicPy.append(ShootPoint.loadPoint2DicPoint(listPtPy[ind]))

    # acces aux données par trois méthodes  (<class ShootPoint>)
    print('extraction  via')
    print('point           ',type(listPtPy[1].dateVis), listPtPy[1].dateVis)
    print('__getattribute__', type(ShootPoint.__getattribute__(listPtPy[1], 'dateVis')), ShootPoint.__getattribute__(listPtPy[1], 'dateVis'))
    print('dictionnaire    ', type(listDicPy[1]['Img']['dateVis']), listDicPy[1]['Img']['dateVis'])

    print('Calcul d\'une différence de date entre deux images  par deux méthodes')
    print((listPtPy[1].dateVis - listPtPy[0].dateVis).total_seconds(), ' s')
    print('debug  ', type(listPtPy[1].dateVis), type((listPtPy[1].dateVis - listPtPy[0].dateVis)))
    print(timedelta.total_seconds(listPtPy[1].dateVis - listPtPy[0].dateVis), ' s')
    # ---------------------------------------------------------------------------------------------------------------
    # Exemples de modification de la valeur de l'attribu  num  et de l'instance listMyPt[n]  de la classe ShootPoint
    # ---------------------------------------------------------------------------------------------------------------
    n = 6
    print('Exemples de modification des valeurs')
    print('============     Données initiales')
    print(listPtPy[n])
    print('changements ..............')
    # Atttention les deux premières méthodes ne modifient pas le dictionnaire associé au point !
    oldnum = listPtPy[n].num
    listPtPy[n].num = 99
    print(listPtPy[n].num, ' remplace ', oldnum)
    #
    oldname = listPtPy[n].Vis
    ShootPoint.__setattr__(listPtPy[n], 'Vis', "EIFFEL_TOWER_9999.DNG")
    print(ShootPoint.__getattribute__(listPtPy[n], 'Vis'), ' remplace ', oldname)
    #  méthode via le dictionnaire  (attention mettre le dictionnaire à jour avant de le modifier )
    olddateNir = listDicPy[n]['Img']['dateNir']
    listDicPy[n] = ShootPoint.loadPoint2DicPoint(listPtPy[n])
    listDicPy[n]['Img']['dateNir'] = datetime.fromisoformat('2022-01-25 12:59:01.987654')
    ShootPoint.loadDicPoint2Point(listPtPy[n], listDicPy[n])   # il faut mettre à jour le point !
    print(listDicPy[n]['Img']['dateNir'], ' remplace ', olddateNir)
    #
    print(listPtPy[n].dic)
    print('============     Données modifiées')
    print(listPtPy[n])
