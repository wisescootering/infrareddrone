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
                 numero: int = 0,
                 nameVis: str = "EIFFEL_TOWER_00.DNG",
                 nameNir: str = "2022_0101_130000_000.RAW",
                 visDate: str = '2022-01-01 12:00:00',
                 nirDate: str = '2022-01-01 12:00:00',
                 timeLine: float = 0.,
                 timeDeviation: float = 0.):
        super().__init__()
        self.num = numero
        self.Vis = nameVis
        self.VisDirectory = f'C:\\Air-Mission\\FLY-20010101-0201_Vide\\AerialPhotography'
        self.VisShootNum = 1
        self.VisTimeLine = timeLine
        self.Nir = nameNir
        self.NirDirectory = f'C:\\Air-Mission\\FLY-20010101-0101_Vide\\AerialPhotography'
        self.NirShootNum = 3
        self.NirTimeLine = 0.
        self.dateVis = datetime.fromisoformat(visDate)
        self.dateNir = datetime.fromisoformat(nirDate)
        self.timeLine = timeLine
        self.timeDeviation = timeDeviation
        self.bestSynchro = 0
        self.bestMapping = 0
        self.bestOffset = 0
        self.alignment = 0
        self.altGround = 324.
        self.altGeo = 35.
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
        self.yawCoarseAlign = 0
        self.pitchCoarseAlign = 0
        self.rollCoarseAlign = 0
        self.distStarPt = 0
        self.capLastPt = 0
        self.distLastPt = 0
        self.dic = ShootPoint.loadPoint2DicPoint(self)

    def __str__(self):
        """
        Formatting class data for printing on screen.
        Pour l'affichage des vitesse  on suppose que la fréquence de prise de vue des images du DJI  est 2.02 s
        ToDo:  utiliser pour la fréquence de prise de vue des images du DJI la variable calculée
        :return:
        """
        return "___________________________________________________________________________________________________\n" \
               "Point {0} .....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDrone.....IRDron..... \n" \
               "___________________________________________________________________________________________________\n" \
               "Visible image       :   {1}         |  Date of shooting: {3} | N° shooting : {40}                  \n" \
               "Near Infrared image :   {2}    |  Date of shooting: {4} | N° shooting : {41}                       \n" \
               "Vis Time line :   {42} s   |  Nir Time line {43} s                                                 \n" \
               "Time line: {5} s                                                                                   \n" \
               "Time deviation Nir to Vis: {6} s                                                                   \n" \
               "Selected for alignment process : {36}                                                              \n" \
               "Best synchro : {34}                                                                                \n" \
               "Selected for mapping : {35}                                                                        \n" \
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
               " Ir to Vi | yaw: {23}°  | pitch: {24}° | roll: {25}° | Theoretical alignment                       \n" \
               " Ir to Vi | yaw: {37}°  | pitch: {38}° | roll: {39}° | Coarse alignment                            \n" \
            .format(self.num, self.Vis, self.Nir, self.dateVis, self.dateNir,
                    round(self.timeLine, 4), round(self.timeDeviation, 3),
                    self.gpsSN, round(self.gpsLat, 6), self.gpsWE, round(self.gpsLon, 6),
                    round(self.gpsUTM_X, 2), round(self.gpsUTM_Y, 2), self.gpsUTM_Zone,
                    self.altGround, self.altGeo, self.altTakeOff,
                    self.yawDrone, self.pitchDrone, self.rollDrone,
                    self.yawGimbal, self.pitchGimbal, self.rollGimbal,
                    round(self.yawIR2VI, 5), round(self.pitchIR2VI, 5), round(self.rollIR2VI, 5),
                    round(self.x_1, 3), round(self.x_2, 3), round(self.x_3, 3),
                    round(self.gpsDist, 3), round(self.gpsCap, 3), round(self.gpsDistTot, 3),
                    round((self.x_1**2 + self.x_2**2)**0.5 / 2.02, 3),
                    round(self.x_3 / 2.02, 3), round(self.bestSynchro, 0), round(self.bestMapping, 0), round(self.alignment, 0),
                    round(self.yawCoarseAlign, 5), round(self.pitchCoarseAlign, 5), round(self.rollCoarseAlign, 5),
                    self.VisShootNum, self.NirShootNum, self.VisTimeLine, self.NirTimeLine
                    )


    def loadPoint2DicPoint(self) -> dict:
        PointInfo = \
            {
                'Img': {
                    "num": self.num,
                    "Vis": self.Vis,
                    "VisDirectory": self.VisDirectory,
                    "dateVis": self.dateVis,
                    "VisShootNum": self.VisShootNum,
                    "VisTimeLine": self.VisTimeLine,
                    "Nir": self.Nir,
                    "NirDirectory": self.NirDirectory,
                    "dateNir": self.dateNir,
                    "NirShootNum": self.NirShootNum,
                    "NirTimeLine": self.NirTimeLine,
                    "timeLine": self.timeLine,
                    "timeDeviation": self.timeDeviation,
                    "bestSynchro": self.bestSynchro,
                    "bestMapping": self.bestMapping,
                    "bestOffset": self.bestMapping,
                    "alignment": self.alignment
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
                    'Coarse': {
                        "yaw": self.yawCoarseAlign,
                        "pitch": self.pitchCoarseAlign,
                        "roll": self.rollCoarseAlign
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
                    "Dist Next Pt": self.gpsDist,
                    "Cap Next Pt": self.gpsCap,
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


    def loadDicPoint2Point(self, dic: dict):
        self.num = dic['Img']["num"]
        self.Vis = dic['Img']["Vis"]
        self.VisDirectory = dic['Img']['VisDirectory']
        self.dateVis = dic['Img']['dateVis']
        self.VisShootNum = dic['Img']['VisShootNum']
        self.VisTimeLine = dic['Img']['VisTimeLine']
        self.Nir = dic['Img']["Nir"]
        self.NirDirectory = dic['Img']['NirDirectory']
        self.dateNir = dic['Img']['dateNir']
        self.NirShootNum = dic['Img']['NirShootNum']
        self.NirTimeLine = dic['Img']['NirTimeLine']
        self.timeLine = dic['Img']["timeLine"]
        self.timeDeviation = dic['Img']["timeDeviation"]
        self.bestSynchro = dic['Img']['bestSynchro']
        self.bestMapping = dic['Img']['bestMapping']
        self.bestOffset = dic['Img']['bestOffset']
        self.alignment = dic['Img']['alignment']

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
        self.yawCoarseAlign = dic['Attitude']['Coarse']["yaw"]
        self.pitchCoarseAlign = dic['Attitude']['Coarse']["pitch"]
        self.rollCoarseAlign = dic['Attitude']['Coarse']["roll"]

        self.gpsSN = dic['GPS']["SN"]
        self.gpsLat = dic['GPS']["Latitude"]
        self.gpsWE = dic['GPS']["WE"]
        self.gpsLon = dic['GPS']["Longitude"]
        self.gpsDist = dic['GPS']["Dist Next Pt"]
        self.gpsCap = dic['GPS']["Cap Next Pt"]
        self.gpsDistTot = dic['GPS']["Dist Tot"]
        self.gpsUTM_X = dic['GPS']["UTM"]["X"]
        self.gpsUTM_Y = dic['GPS']["UTM"]["Y"]
        self.gpsUTM_Zone = dic['GPS']["UTM"]["zone"]
        self.altGround = dic['GPS']["alt"]["ground"]
        self.altGeo = dic['GPS']["alt"]["Geo"]
        self.altTakeOff = dic['GPS']["alt"]["takeOff"]


    def loadDicPointFly2Point(self, dic: dict):
        """
        Ce module assure la passerelle entre la version brute initiale de IRDrone et
        la version interactive.
        Dans la version interactive les paramètres d'un point de prise de vue de la phase de vol "FLY"
        sont stockés dans un dictionnaire sous forme de clé:valeur.
        Certaines clés n'exitaient pas dans la version initiale.
        On les inclus dans de nouvelles variables de la class shootPoint pour assurer la compatibilité ascendante.
        :param dic:
        :return:
        """
        self.num = dic['Fly Shooting Number']
        self.Vis = dic['Vis File Name']
        self.VisDirectory = dic['Vis Directory']       # new
        self.dateVis = datetime.strptime(dic['Vis Date/Time Original'], '%Y:%m:%d %H:%M:%S')
        self.VisShootNum = dic['Vis Shooting Number']  # new
        self.VisTimeLine = dic['Vis Time Line']        # nex equiv.    self.timeLine
        self.Nir = dic["Nir File Name"]
        self.NirDirectory = dic['Nir Directory']       # new
        self.dateNir = datetime.strptime(dic['Nir Date/Time Original'], '%Y:%m:%d %H:%M:%S')
        self.NirShootNum = dic['Nir Shooting Number']  # new
        self.NirTimeLine = dic['Nir Time Line']        # nex  equiv.   self.timeLine + self.timeDeviation   (vérifier le signe !!)
        self.timeLine = dic['Vis Time Line']
        self.timeDeviation = dic['Dt Vis-Nir']
        self.bestSynchro = dic['Best Synchro']
        self.bestMapping = dic['Best Mapping']
        self.bestOffset = dic['Best Offset']
        self.alignment = dic['Alignment']
        self.yawDrone = dic['Camera Nir Roll']
        self.pitchDrone = dic['Camera Nir Pitch']
        self.rollDrone = dic['Camera Nir Yaw']
        self.yawGimbal = dic['Camera Vis Roll']
        self.pitchGimbal = dic['Camera Vis Pitch']
        self.rollGimbal = dic['Camera Vis Yaw']
        self.x_1 = dic['x_1']
        self.x_2 = dic['x_2']
        self.x_3 = dic['x_3']
        self.yawIR2VI = dic['Yaw IR to VI']
        self.pitchIR2VI = dic['Pitch IR to VI']
        self.rollIR2VI = dic['Roll IR to VI']
        self.yawCoarseAlign = dic['Yaw Coarse Align']
        self.pitchCoarseAlign = dic['Pitch Coarse Align']
        self.rollCoarseAlign = dic['Roll Coarse Align']
        self.gpsSN = dic['Drone S-N']
        self.gpsLat = dic['Drone Latitude']
        self.gpsWE = dic['Drone W-E']
        self.gpsLon = dic['Drone Longitude']
        self.gpsDist = dic['Dist To Next Pt']
        self.gpsCap = dic['Cape To Next Pt']
        self.gpsDistTot = dic['Dist Cumul']
        self.gpsUTM_X = dic['X UTM']
        self.gpsUTM_Y = dic['Y UTM']
        self.gpsUTM_Zone = dic['Zone UTM']
        self.altGround = dic['Altitude Drone/Ground']
        self.altGeo = dic['Altitude Ground/Sea level']
        self.altTakeOff = dic['Altitude Drone/TakeOff']

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
                 "VisDirectory": f'C:\\Air-Mission\\FLY-20010101-0201_Vide\\AerialPhotography',
                 "dateVis": datetime.fromisoformat('2022-01-25 11:45:17'),
                 "VisShootNum": 130 + numero,
                 "VisTimeLine": numero * (1 + 0.01987),
                 "Nir": "2022_0125_125011_" + nimgRAW + ".RAW",
                 "NirDirectory": f'C:\\Air-Mission\\FLY-20010101-0201_Vide\\AerialPhotography',
                 "dateNir": datetime.fromisoformat('2022-01-25 12:35:07'),
                 "NirShootNum": int(round(numero * 3/2)),
                 "NirTimeLine": numero * (1 + 0.01987) + 200.5 * (1 + 0.01),
                 "timeLine": numero * (1 + 0.01987),
                 "timeDeviation": (numero * (1 + 0.01987))-(numero * (1 + 0.01987) + 200.5 * (1 + 0.01)),
                 "bestSynchro": 0,
                 "bestMapping": 0,
                 "bestOffset": 0,
                 "alignment": 0
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
                    'Coarse': {
                        "yaw": 1.2 + numero / 2,
                        "pitch": 1.5 + numero / 2,
                        "roll": 23.9 + numero / 2
                    },
                    'IR2VI': {
                        "yaw": 1.12099 + numero / 2,
                        "pitch": 1.40684 + numero / 2,
                        "roll": 21.9 + numero / 2
                    }
                },
            'GPS': {
                "SN": 'N',
                "Latitude": 45.010203 + numero/10,
                "WE": 'E',
                "Longitude": 3.012345 + numero/10,
                "Dist Next Pt": 3.33,
                "Cap Next Pt": 55.5,
                "Dist Tot": numero * 3.33,
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
    # et le place comme premier élément de la liste des dictionnaires des points de prise de vue
    dicShootingPts = [myPt_1.loadPoint2DicPoint()]

    # Définition de nouveaux points  (Prédéfini ici  pour le test   voir def newPpoint(numero)  )
    for i in range(1, 13):
        dicPt = newPpoint(i)  # génère les données de test
        myPt = ShootPoint()   # instanciation d'un nouveau point de la classe ShootPoint (données par défaut)
        myPt.loadDicPoint2Point(dicPt)  # affectation du dictionnaire  au point N°i
        # insertion dans la 'liste' des dictionnaires des points. La liste contient déjà le dictionnaire du point N°1
        dicShootingPts.append(myPt.loadPoint2DicPoint())

    # ----------------------------------------------------------------------------------------------------------------
    # Ecriture dans un fichier .json des données de la liste des points sous la forme d'une liste de dictionnaires.
    # Attention, d'origine ce format ne conserve pas le type datetime
    # ----------------------------------------------------------------------------------------------------------------
    fileName = "testFile.json"    # sera sauvé dans ce cas dans le dossier qui contient le présent script python
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
    print('point           ', type(listPtPy[1].dateVis), listPtPy[1].dateVis)
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
    ShootPoint.__setattr__(listPtPy[n], 'Vis', "EIFFEL_TOWER_99.DNG")
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
