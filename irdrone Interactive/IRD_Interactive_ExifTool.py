# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
import os.path as osp
import subprocess
from pathlib import Path
import json


def get_exif_info(scr, dst, tmp):
    EXIFTOOLPATH = osp.join("C:\Documents-Alain\Projet-IRdrone\Code_Python\irdrone\irdrone\exiftool\exiftool.exe")
    #EXIFTOOLPATH = Path(__file__).parent/"Code_Python"/ "irdrone"/ "irdrone" / "exiftool" / "exiftool.exe"

    print(EXIFTOOLPATH)
    # 1- Lecture des données Exif d'une image fileName.tif  (commande  '-r')
    # 2- Modification des Tags(ou ajout par exemple Copyright)
    #  Ici passage par un fichier temporaire  fileName_exiftool_temp
    # 3- Ecriture (commande  "-overwrite_original", "-fast") dans le même fichier fileName.tif
    pth_scr = Path(scr)
    pth_dst = Path(dst)
    pth_tmp = Path(tmp)

    cameraMaker = 'irdrone_4'
    cameraModel = 'multispectral_4'
    uniquecameramodel = 'IRDrone DJIMavicAir2/SJCamM20'
    serialnumber = 'v1.30 / 2022'

    cmd = [EXIFTOOLPATH, "-TagsFromFile", pth_scr,
           f'-Make={cameraMaker}',
           f'-Model={cameraModel}',
           f'-UniqueCameraModel={uniquecameramodel}',
           f'-SerialNumber ={serialnumber}',
           pth_dst, "-overwrite_original", "-fast"]
    p = subprocess.run(cmd)

    """

    cmd = [EXIFTOOLPATH, pth_tmp,
           '-Make=irdrone',
           '-Model=multispectral',
           '-UniqueCameraModel=IRDrone DJIMavicAir2/SJCamM20',
           '-SerialNumber=v1.30/2022',
           '-CameraSerialNumber=v1.30/2022',
           '-FocalLength=4.6',
           '-FocalLengthIN35mmFormat=27',
           '-FieldOfView=67.8',
           '-LensInfo=27mm f/2.8',
           '-LensModel=720',
           '-Copyright=Wise Scootering - Balthazar Neveu',
           '-Artist=Flo',
           "-overwrite_original", pth_dst, "-fast"]
    p = subprocess.run(cmd)

    """
    cmd = [EXIFTOOLPATH, pth_scr,
           '-r',
           '-Make=irdrone',
           '-Model=multispectral',
           '-UniqueCameraModel=IRDrone DJIMavicAir2/SJCamM20',
           '-SerialNumber=v1.30/2022',
           '-CameraSerialNumber=v1.30/2022',
           '-FocalLength=4.6',
           '-FocalLengthIN35mmFormat=27',
           '-ScaleFactorTo35mmEquivalent=5.9',
           '-FieldOfView=67.8',
           '-LensInfo=27mm f/2.8',
           '-Copyright=Wise Scootering - Balthazar Neveu',
           "-overwrite_original", "-fast"]
    # p = subprocess.run(cmd)

    """
    # recopie les données Exif de l'image dans un fichier .json
    exif_file = Path(src.split('.')[0] + '.json')
    subprocess.run(cmd,  capture_output=True, text=True)
    cmd = [EXIFTOOLPATH, Path(pth_dst), '-r','-w!', 'json']
    subprocess.run(cmd)

    cmd = [EXIFTOOLPATH, "-TagsFromFile", pth_src, pth_dst, "-overwrite_original", "-fast"]
    p = subprocess.run(cmd)


    if True:
        cmd = [EXIFTOOLPATH, Path(pth_dst)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        output_text = p.stdout
        lines = output_text.split("\n")
        #selection = [li for li in lines if "Degree" in li]
        selection = [li for li in lines]
        dic = dict()
        for li in selection:
            print(li)
            try:
                a = li.split(":")
                key = a[0].replace(" ", "")
                val = a[1].replace(" ", "")
                dic[key] = val
            except:
                pass
            #with open(exif_file, "w") as fi:
            #    json.dump(dic, fi)
                pass
        print(dic)
    """

    return


if __name__ == "__main__":
    print("debut test Exiftool")
    # fichier source contenant les données
    strPathImage_dng = 'C:\Air-Mission\FLY-20220125-1159-Blassac\HYPERLAPSE_0216.DNG'
    # fichier de destination où seront copiées les données
    strPathImage_dst = 'C:\Air-Mission\FLY-20220125-1159-Blassac\essai-dst.tif'
    # fichier temporaire
    strPathImage_tmp = 'C:\Air-Mission\FLY-20220125-1159-Blassac\essai-tmp.tif'
    dico = get_exif_info(strPathImage_dng, strPathImage_dst, strPathImage_tmp)