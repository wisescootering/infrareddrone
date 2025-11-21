# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Exif Xmp data
#   29/10/2023   V002   *
# ---------------------------------------------------------------------------------
import os.path as osp
import subprocess
from pathlib import Path
import json
from datetime import datetime, date
import time
# -------------- IRDrone Library ------------------------------------
import IRD_interactive_utils as Uti



def get_EXIF_XMP(pth: Path, index, utilise_cache=False, verbose: bool = False):
    """
    Extract gimbal and drone information from the XMP data
    and classical EXIF tags  of a specified image file
    using ExifTool and cache the data in a .exif file.

    Parameters:
    pth (Path): The path to the image file
    Supported formats are: jpg, dng and the RAW format of the SJCam M20 camera .

    Returns:
    dict: A dictionary containing the extracted gimbal and exif information.

    1 Vérification du Cache :

    > exif_file = pth.with_suffix(".exif"): Ceci définit le chemin vers un fichier .exif qui est supposé
    contenir un cache des données EXIF pour l'image spécifiée.
    > if exif_file.exists(): Vérifie si ce fichier cache existe.
    Si Oui : Il ouvre le fichier, charge les données EXIF sous forme de dictionnaire JSON et le renvoie.
    Si Non : Il passe à l'étape suivante pour extraire les données EXIF en utilisant ExifTool.

    2 Utilisation d'ExifTool :

    > cmd = [EXIFTOOLPATH, pth]: Ceci définit la commande à exécuter dans le terminal, où EXIFTOOLPATH devrait
        être  le chemin vers l'exécutable ExifTool et pth est le chemin de l'image.
    > p = subprocess.run(cmd, capture_output=True, text=True): Exécute la commande dans le terminal et capture la sortie
    > output_text = p.stdout: Stocke la sortie standard de la commande (c.-à-d. le résultat de l'exécution de la commande)
        dans une variable.

    3 Traitement des Données Extraites :

    > lines = output_text.split("\n"): Divise la sortie texte en lignes, créant une liste où chaque élément
        est une ligne de texte.
    > selection = [li for li in lines if "Degree" in li]: Sélectionne les lignes qui contiennent le mot "Degree".
        Cela pourrait être utilisé pour identifier et extraire les informations spécifiques liées à l'attitude du gimbal.
    > dic = dict(): Crée un dictionnaire vide pour stocker les paires clé-valeur des données EXIF.
    > La boucle for qui suit extrait les clés et les valeurs des lignes sélectionnées et les stocke dans le dictionnaire.

    4 Stockage et Retour des Données :
    > with open(exif_file, "w") as fi: json.dump(dic, fi): Sauvegarde le dictionnaire de données EXIF dans un
        fichier pour une utilisation future (caching).
    > return dic: Renvoie le dictionnaire de données EXIF.

    REMARQUE :  A propos de l'arborescence et de la localisation de exiftool.exe

        Projet-IRdrone/
        └── Code_Python/
            └── irdrone/
                ├── irdrone/
                │   ├── exiftool/
                │   │   └── exiftool.exe
                │   └── ...
                └── irdrone Interactive/
                    └── IRD_Interactive_Exif_Xmp.py

    Définir le chemin relatif vers "exiftool.exe" en utilisant Path

    EXIFTOOLPATH = Path(__file__).parent.parent / "irdrone" / "exiftool" / "exiftool.exe"

    Ici  Path(__file__)  représente sur ma machine le chemin complet depuis lequel j'éxécute le code :
    C:\Documents-Alain\Projet-IRdrone\Code_Python\irdrone\irdrone Interactive\IRD_Interactive_Exif_Xmp.py
    Ensuite il faut remonter de deux niveaux  DEPUIS LE FICHIER IRD_Interactive_Exif_Xmp.py
    pour atteindre irdrone (celui sous Code_Python)
    et ensuite on va descendre  de trois niveaux pour attteindre le fichier exe exiftool.exe

    Note: ATTENTION avec os.path le niveau du fichier est IMPLICITE et on remonterai d'un seul niveau.
    La commande  osp.dirname(__file__)  part de irdrone Interactive  et pas de IRD_Interactive_Exif_Xmp.py
    On écrirait donc  (si  le signe ":" signifie remonte d'un niveau et   ":",":" de deux etc) :

    EXIFTOOLPATH = osp.join(osp.dirname(__file__), "::", "irdrone", "exiftool", "exiftool.exe")

    """

    EXIFTOOLPATH = Path(__file__).parent.parent / "irdrone" / "exiftool" / "exiftool.exe"
    # Vérifie si le fichier existe
    if EXIFTOOLPATH.exists():
        pass
    else:
        print(f"error  'exiftool.exe' was not found at {EXIFTOOLPATH}")
        return

    exif_file = pth.with_suffix(".exif")
    # ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠
    #  Utilisation du cache neutralisée (par la présence de False)
    #  Sinon le fichier exif déjà stocké est lu directement
    #  ...
    #  Attention en phase de test si les données inscrites dans le fichier .exif sont modifiée par ailleurs mettre False
    #  Dans une version définitive du code ou pour gagner du temps si le .exif est figé  mettre True !

    if exif_file.exists() and utilise_cache:
        with open(exif_file, "r") as fi:
            dic = json.load(fi)

    # ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠ ⚠
    else:
        cmd = [EXIFTOOLPATH, pth]
        p = subprocess.run(cmd,  capture_output=True, text=True)
        output_text = p.stdout
        lines = output_text.split("\n")
        dic = dict()

        for li in lines:
            if "ExifTool Version Number" in li:
                if verbose: print("dev |", li)
                pass
            elif "use -b option to extract" in li:
                if verbose: print("dev |", li)
                pass
            elif "Error" in li:
                if verbose: print("dev |", li)
                pass
            elif ":" not in li:
                if verbose: print("dev |", li)
                continue
            elif "Degree" in li:
                key = li.split(" Degree")[0]
                val = float(li.split(": ")[1])
                dic[key] = val
                if verbose: print("dev |", li)
            else:
                try:
                    key, val = li.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if verbose: print("dev |", li)
                    dic[key] = val
                except Exception as e:
                    if verbose: print(Uti.Style.YELLOW + f"⚠️ Ligne ignorée (mauvais format) : {li}     {e}" + Uti.Style.RESET)
                    pass

    return dic




def get_EXIF_XMP_new_mais_bug(pth: Path, index=None, verbose: bool = False):
    """
    Nouvelle version utilisant 'exiftool -j' qui renvoie du JSON propre.

    Retourne un dictionnaire EXIF/XMP complet, parfaitement formaté.
    """

    EXIFTOOLPATH = Path(__file__).parent.parent / "irdrone" / "exiftool" / "exiftool.exe"

    if not EXIFTOOLPATH.exists():
        print(f"❌ ERROR – exiftool.exe not found at {EXIFTOOLPATH}")
        return {}

    # Chemin du cache
    exif_file = pth.with_suffix(".exif")

    # ----------- OPTION : UTILISATION DU CACHE -------------------
    utilise_cache = False  # mettre True si tu veux activer le cache

    if utilise_cache and exif_file.exists():
        try:
            if verbose:
                print(f"📄 Lecture cache : {exif_file}")
            with open(exif_file, "r") as fi:
                return json.load(fi)
        except Exception as e:
            print(f"⚠️ Erreur lecture cache → recalcul : {e}")

    # ----------- EXTRACTION EXIF via exiftool -j -------------------
    cmd = [str(EXIFTOOLPATH), "-j", str(pth)]

    p = subprocess.run(cmd, capture_output=True, text=True)

    if p.returncode != 0:
        print("❌ Erreur exiftool :", p.stderr)
        return {}

    try:
        data = json.loads(p.stdout)

        if not data:
            print("⚠️ Aucune donnée JSON retournée")
            return {}

        dic = data[0]  # exiftool -j renvoie une liste

        if verbose:
            print(f"✔ JSON EXIF obtenu ({len(dic)} champs)")

    except Exception as e:
        print("❌ Erreur parsing JSON:", e)
        return {}

    # ----------- SAUVEGARDE DU CACHE -------------------
    if utilise_cache:
        try:
            with open(exif_file, "w") as fi:
                json.dump(dic, fi, indent=2)
        except Exception as e:
            print(f"⚠️ Impossible d’écrire cache : {e}")

    return dic
