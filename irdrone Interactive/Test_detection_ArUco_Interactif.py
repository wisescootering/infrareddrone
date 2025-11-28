
import os
import os.path as osp
from pathlib import Path
import numpy as np
import cv2
import matplotlib.pyplot as plt
import time
import json
from json import JSONDecodeError
from typing import List, Tuple, Optional, Dict, Any, Union
import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import IRD_interactive_utils as Uti




# ----------------------
# Dictionnaires ArUco disponibles
# ----------------------
ARUCO_DICT = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
}



def process_aruco_images(
        folderMissionPath: Path,
        name_folder: str,
        typ_img: str,
        ext_img: str,
        show: bool = False,
        verbose: bool = False,
        force_aruco_cache: bool = False,
        max_workers: int = 4
):
    """
    Multi-threaded processing of ArUco detections.
    Full optimization: if EXIF cache exists, do NOT load image.


    Process a sequence of VIS/NIR images to detect ArUco markers and compute
    absolute/mobile angles for each frame in the sequence.

    Parameters
    ----------
    folderMissionPath : Path
        Path to the mission folder (e.g. C:/Air-Mission/FLY-xxxxxx).
    name_folder : str
        Name of the subfolder containing the images (e.g. "Synchro").
    typ_img : str
        Image type: "VIS" or "NIR".
    ext_img : str
        Image extension: "dng", "jpg", ...
    show : bool, optional
        Show each detection result image. Default is False.
    verbose : bool, optional
        Print debug information. Default is False.
    force_aruco_cache : bool, optional
        If True, force reprocessing and overwrite ArUco EXIF cache.

    Returns
    -------
    results : list of dict
        Each entry contains:
            {
                "image": filename,
                "angle_abs": ...,
                "angle_img": ...,
                "delta": ...
            }
    x_vals : list of int
        Image index values used for regression or plotting.
    y_vals : list of float
        Angle_img values used for regression or plotting.
    """

    # 1) Retrieve list of images
    outputFolder, idMin, idMax, listImages = read_transfer_info(
        folderMissionPath, typ_img, ext_img, section="sync"
    )

    folder_images = folderMissionPath / name_folder

    dic_relative_time_line = load_relative_time_line(folderMissionPath)

    results = []
    x_vals = []
    y_vals = []

    max_workers = best_thread_count(io_bound=True)
    print(Uti.Style.CYAN + f"[INFO] Processing {len(listImages)} images using {max_workers} threads..." + Uti.Style.RESET)

    # ------------------------------------------------------------
    # Worker function (one image per thread)
    # ------------------------------------------------------------
    def process_one(i, img):
        img_path = folder_images / img
        ext = img.lower().split('.')[-1]

        # --------------------------------------------------------
        # 1) FAST PATH : cache EXIF détecté → aucun chargement image
        # --------------------------------------------------------
        cached = read_aruco_cache(img_path)
        if cached and force_aruco_cache:
            return i, img, cached

        # --------------------------------------------------------
        # 2) SLOW PATH : pas de cache pour les données aruco de détection d'angle → chargement image normal
        # --------------------------------------------------------
        if ext == "dng":
            img_cv, _ = load_dng(str(img_path), template="Aruco_Detection.pp3")
        elif ext == "raw":
            print('DEBUG   en cours de développement')
            return i, img, None
        else:
            img_cv = cv2.imread(str(img_path))

        if img_cv is None:
            return i, img, None

        # --------------------------------------------------------
        # 3) ArUco detection
        # --------------------------------------------------------
        result, _ = detect_mobile_marker_absolute(
            image=img_cv,
            img_path=img_path,
            arucoDict=get_aruco_dict("DICT_4X4_50"),
            fixed_ids=[5, 22, 16, 13],
            mobile_id=0,
            marker_data=None,
            show=show,
            title=name_folder + " - " + img,
            verbose=verbose,
            force_aruco_cache=force_aruco_cache,
        )
        result["relative_time_line"] = extract_relative_time_line(dic_relative_time_line, Path(img_path).name, typ_img, ext_img)

        return i, img, result

    # ------------------------------------------------------------
    # MULTITHREAD EXECUTION
    # ------------------------------------------------------------
    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i, img in enumerate(listImages, start=1):
            futures.append(executor.submit(process_one, i, img))

        for future in as_completed(futures):
            i, img, result = future.result()

            if result:
                results.append({
                    "image": img,
                    "angle_abs": result["angle_abs"],
                    "angle_img": result["angle_img"],
                    "delta": result["delta_abs_img"],
                    "relative_time_line": result["relative_time_line"],
                })
                x_vals.append(result["relative_time_line"])
                y_vals.append(result["angle_img"])

    # ------------------------------------------------------------
    # Order results chronologically
    # ------------------------------------------------------------
    ordered = sorted(zip(x_vals, y_vals, results), key=lambda t: t[0])
    x_vals = [t[0] for t in ordered]
    y_vals = [t[1] for t in ordered]
    results = [t[2] for t in ordered]

    return results, x_vals, y_vals


def detect_mobile_marker_absolute(image=None,
                                  img_path=None,
                                  arucoDict=None,
                                  fixed_ids=[5, 22, 16, 13],
                                  mobile_id=0,
                                  marker_data=None,
                                  show=False,
                                  title="",
                                  verbose=False,
                                  force_aruco_cache=False
                                  ):
    """
    Calcule l'angle et la position du marqueur mobile dans le repère défini par
    4 marqueurs fixes.

    Si certains marqueurs fixes sont manquants, le calcul absolu n'est pas effectué
    et seule l'orientation image est retournée (mode dégradé).

    result contient :
      - missing_fixed : True si un ou plusieurs marqueurs fixes sont absents
      - mobile_id
      - center_abs : (u,v) coords normalisées dans le repère des fixes
      - angle_abs  : angle du marker mobile dans le repère absolu (°)
      - angle_img  : angle du marker mobile dans le repère image (°)
      - delta_abs_img : différence angle_abs - angle_img (°)
      - x_ref, y_ref : vecteurs unité du repère sol
      - width_px, height_px : tailles du repère
    """

    r = read_aruco_cache(img_path)
    if r and force_aruco_cache:
        print(Uti.Style.GREEN + f'[INFO] Traitement AVEC CACHE de {img_path}' + Uti.Style.RESET)
        return r, None
    else:
        print(Uti.Style.GREEN + f'[INFO] Traitement de {img_path}' + Uti.Style.RESET)

    img_out = image.copy() if image is not None else None

    # --- détecter les marqueurs si besoin
    if marker_data is None:
        if image is None or arucoDict is None:
            raise ValueError("Soit marker_data doit être fourni, soit image et arucoDict.")
        marker_data, _ = detect_aruco_marker(image.copy(), arucoDict, show=False, title=title, verbose=verbose)

    if not marker_data:
        if verbose: print("Aucun marqueur détecté !")
        return None, img_out

    # organiser les données par ID
    md = {int(entry[0]): {"angle_img": entry[1],
                          "center": np.array(entry[2], dtype=float),
                          "corners": np.array(entry[3], dtype=float)}
          for entry in marker_data}

    # vérifier présence des marqueurs fixes et mobile
    missing_fixed = [fid for fid in fixed_ids if fid not in md]
    mobile_missing = mobile_id not in md

    result = {
        "missing_fixed": missing_fixed,
        "mobile_id": int(mobile_id),
        "center_abs": None,
        "angle_abs": None,
        "angle_img": md[mobile_id]["angle_img"] if not mobile_missing else None,
        "delta_abs_img": None,
        "x_ref": None,
        "y_ref": None,
        "width_px": None,
        "height_px": None,
        "relative_time_line": None,
    }

    if missing_fixed or mobile_missing:
        if missing_fixed:
            if verbose: print(Uti.Style.YELLOW + f"⚠️Tous les marqueurs fixes ne sont pas détectés ! manquants = {missing_fixed}" + Uti.Style.RESET)
        if mobile_missing:
            if verbose: print(Uti.Style.RED + f"❌ Le marqueur mobile ({mobile_id}) n'est pas détecté !" + Uti.Style.RESET)
        if show and img_out is not None:
            show_Aruco_marker(result, img_out, md, fixed_ids, title)
        write_aruco_cache(img_path, result)
        # print(f'DEBUG 0014  result = {result}')
        return result, img_out

    # --- calcul des coordonnées et de l'angle absolu
    geom = compute_mobile_marker_geometry(md, fixed_ids, mobile_id)
    if geom is not None:
        result.update(geom)
    else:
        if verbose: print(f"⚠  Impossible de calculer la géométrie absolue.")

    # --- affichage
    if show and img_out is not None:
        show_Aruco_marker(result, img_out, md, fixed_ids, title)

    write_aruco_cache(img_path, result)
    # print(f'DEBUG 0004  result = {result}')
    return result, img_out


def write_aruco_cache(img_path: str, aruco_data: dict) -> bool:
    """
    Safely write ArUco analysis data into a companion .exif JSON file.

    This function attempts to load an existing .exif JSON file associated
    with the given image path, updates the "aruco" key, and writes the updated
    data back to disk. Any unexpected I/O or JSON errors are caught to avoid
    interrupting higher-level logic.

    Parameters
    ----------
    img_path : str
        Path to the original image (e.g. DNG, JPG, etc.).
        The .exif file uses the same name but the `.exif` extension.
    aruco_data : dict
        Dictionary containing the ArUco-related information to store.

    Returns
    -------
    bool
        True if writing succeeded, False if an error occurred.
    """

    exif_path = Path(img_path).with_suffix(".exif")

    try:
        # Load existing EXIF JSON data if the file exists
        if exif_path.exists():
            try:
                with open(exif_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (JSONDecodeError, OSError):
                # File exists but is unreadable/corrupted
                data = {}
        else:
            data = {}

        # Update only the "aruco" key
        data["aruco"] = aruco_data

        # Save back to disk
        with open(exif_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        return True  # Success

    except Exception as e:
        print(f"[ERROR] Failed to write EXIF cache for {img_path}: {e}")
        return False  # Failure


def read_aruco_cache_old(img_path: str) -> Optional[Dict[str, Any]]:
    """
    Check if a companion .exif JSON file exists for the given image,
    and whether it contains a non-empty "aruco" key.

    Parameters
    ----------
    img_path : str
        Path to the original image (e.g., DNG, JPG, etc.).
        The .exif file uses the same name but with a `.exif` extension.

    Returns
    -------
    dict or None
        The dictionary stored under the "aruco" key if found and non-empty,
        otherwise None.

    Notes
    -----
    Any file I/O or JSON parsing errors are caught silently and return None.
    """
    exif_path = Path(img_path).with_suffix(".exif")

    if not exif_path.exists():
        return None

    try:
        with open(exif_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (JSONDecodeError, OSError):
        # File exists but is unreadable or corrupted
        return None

    aruco = data.get("aruco", None)

    # Ensure the "aruco" entry is a non-empty dictionary
    if isinstance(aruco, dict) and aruco:
        return aruco

    return None

from pathlib import Path
from typing import Optional, Dict, Any
import json
from json import JSONDecodeError



def read_aruco_cache(img_path: str) -> Optional[Dict[str, Any]]:
    """
    Load the cached ArUco data and the relative timeline from a companion .exif JSON file.

    Parameters
    ----------
    img_path : str
        Path to the original image (e.g., DNG, JPG, etc.).
        The .exif file uses the same name but with a `.exif` extension.

    Returns
    -------
    dict or None
        Dictionary containing:
            - all key-value pairs from the "aruco" entry (if any)
            - "relative_time_line" key from top-level JSON (if exists)
        Returns None if file does not exist or is unreadable.
    """
    exif_path = Path(img_path).with_suffix(".exif")

    if not exif_path.exists():
        return None

    try:
        with open(exif_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (JSONDecodeError, OSError):
        # File exists but is unreadable or corrupted
        return None

    # Start with ArUco dictionary
    aruco = data.get("aruco", {})
    if not isinstance(aruco, dict):
        aruco = {}

    # Add top-level "relative time line" as "relative_time_line"
    rel_time = data.get("relative time line", None)
    if rel_time is not None:
        aruco["relative_time_line"] = rel_time

    if not aruco:
        return None

    return aruco



def compute_reference_vectors(fixed_centers):
    """
    Calcule les vecteurs de référence du repère absolu à partir des 4 coins.
    Renvoie x_ref, y_ref et leurs normes normX, normY.
    """
    c_tl, c_tr, c_br, c_bl = fixed_centers
    Xref = ((c_tr - c_tl) + (c_br - c_bl)) / 2.0
    Yref = ((c_bl - c_tl) + (c_br - c_tr)) / 2.0
    normX, normY = np.linalg.norm(Xref), np.linalg.norm(Yref)
    if normX == 0 or normY == 0:
        return None, None, 0, 0
    x_ref, y_ref = Xref / normX, Yref / normY
    # orientation directe
    if x_ref[0] * y_ref[1] - x_ref[1] * y_ref[0] < 0:
        y_ref = -y_ref
    return x_ref, y_ref, normX, normY


def compute_mobile_axis(corners):
    """
    Calcule l'axe principal du marqueur mobile.
    Renvoie un vecteur unitaire u, ou None si norme nulle.
    """
    principal_axis = (corners[0] - corners[3]) + (corners[1] - corners[2])
    npa = np.linalg.norm(principal_axis)
    if npa == 0:
        return None
    return principal_axis / npa


def compute_angle_and_coords(u, x_ref, y_ref, mobile_center, origin, normX, normY, angle_img):
    """
    Calcule angle absolu, coordonnées normalisées et écart angulaire.
    """
    ux, uy = float(np.dot(u, x_ref)), float(np.dot(u, y_ref))
    angle_abs = np.degrees(np.arctan2(uy, ux))
    vec_center = mobile_center - origin
    u_coord = float(np.dot(vec_center, x_ref) / normX)
    v_coord = float(np.dot(vec_center, y_ref) / normY)
    delta_angle = (angle_abs - angle_img + 180) % 360 - 180
    return angle_abs, u_coord, v_coord, delta_angle


def compute_mobile_marker_geometry(md, fixed_ids, mobile_id):
    """
    Calcule toutes les grandeurs géométriques du marqueur mobile dans le repère absolu.
    """
    try:
        fixed_centers = [md[fid]["center"] for fid in fixed_ids]
        mobile_center = md[mobile_id]["center"]
        corners_m = md[mobile_id]["corners"]

        x_ref, y_ref, normX, normY = compute_reference_vectors(fixed_centers)
        if x_ref is None:
            return None

        u = compute_mobile_axis(corners_m)
        if u is None:
            return None

        angle_abs, u_coord, v_coord, delta_angle = compute_angle_and_coords(
            u, x_ref, y_ref, mobile_center, fixed_centers[0], normX, normY, md[mobile_id]["angle_img"]
        )

        return {
            "center_abs": (u_coord, v_coord),
            "angle_abs": angle_abs,
            "delta_abs_img": delta_angle,
            "x_ref": x_ref,
            "y_ref": y_ref,
            "width_px": normX,
            "height_px": normY,
        }

    except Exception as e:
        print(f"Erreur dans compute_mobile_marker_geometry : {e}")
        return None


def show_Aruco_marker(result, img_out, md, fixed_ids, option_show=2, title=""):
    """
    module appelé par def detect_mobile_marker_absolute

    Affiche le marqueur Aruco avec son orientation.
    - result : dictionnaire retourné par detect_mobile_marker_absolute
    - img_out : image sur laquelle dessiner
    - md : dictionnaire des marqueurs (par ID)
    - fixed_ids : liste des IDs fixes (optionnel)
    - option_show : 1 = pyplot rapide, 2 = pyplot classique
    - title : titre de la figure

   Couleurs en format BGR pour OpenCv accessibles par get_color_BGR("orange") ...

    """
    if img_out is None or result is None:
        return

    # --- dessiner centres fixes si disponibles
    if fixed_ids is not None and not result.get("missing_fixed", False):
        for fid in fixed_ids:
            if fid in md:
                ct = tuple(md[fid]["center"].astype(int))
                cv2.circle(img_out, ct, 2, (0, 0, 255), -1)

    # --- dessiner repère absolu si disponible
    if result.get("x_ref") is not None and result.get("y_ref") is not None:
        title = "Repere absolu / sol"
        c_tl = md[fixed_ids[0]]["center"]
        x_ref = result["x_ref"]
        y_ref = result["y_ref"]
        normX = result["width_px"]
        normY = result["height_px"]

        origin = tuple(c_tl.astype(int))
        end_x = (c_tl + x_ref * normX * 1.2).astype(int)
        end_y = (c_tl + y_ref * normY * 1.2).astype(int)
        cv2.arrowedLine(img_out, origin, tuple(end_x), (0, 0, 0), 3, tipLength=0.05)
        cv2.arrowedLine(img_out, origin, tuple(end_y), (0, 0, 0), 3, tipLength=0.05)
    else:
        title = "Repere image"

    # --- centre et orientation de l'ARUCO mobile
    cX, cY = tuple(md[result["mobile_id"]]["center"].astype(int))
    cv2.drawMarker(img_out, (cX, cY), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

    corners_m = md[result["mobile_id"]]["corners"]
    u = ((corners_m[0] - corners_m[3]) + (corners_m[1] - corners_m[2]))
    u /= np.linalg.norm(u)

    # orientation absolue / sol
    if result.get("x_ref") is not None:
        ux = np.dot(u, result["x_ref"])
        uy = np.dot(u, result["y_ref"])
        u_abs = ux * result["x_ref"] + uy * result["y_ref"]
        marker_width = int(np.linalg.norm(corners_m[0] - corners_m[1]))
        line_length = 4 * marker_width
        endX_abs = int(cX + u_abs[0] * line_length)
        endY_abs = int(cY + u_abs[1] * line_length)
        draw_dashed_line(img_out, (cX, cY), (endX_abs, endY_abs), get_color_BGR("orange"), thickness=4, dash_length=15)

    # orientation image
    marker_width = int(np.linalg.norm(corners_m[0] - corners_m[1]))
    line_length = 3 * marker_width
    endX_img = int(cX + u[0] * line_length)
    endY_img = int(cY + u[1] * line_length)
    cv2.line(img_out, (cX, cY), (endX_img, endY_img), get_color_BGR("vert"), 6)

    # texte résumé
    angle_abs = result.get("angle_abs", 0)
    delta_angle = angle_abs - result["angle_img"] if result.get("angle_abs") is not None else 0
    delta_angle = (delta_angle + 180) % 360 - 180

    text_str = f"ID{result['mobile_id']} img={result['angle_img']:.1f}°"
    if result.get("angle_abs") is not None:
        text_str += f" abs={angle_abs:.1f}° Δ={delta_angle:.1f}°"

    # affiche avec pyplot
    fig, ax = plt.subplots()
    ax.imshow(cv2.cvtColor(img_out, cv2.COLOR_BGR2RGB))
    ax.set_title(title if title else "Repere absolu")
    ax.text(0.01, 0.95, text_str, color='white', fontsize=10,
            transform=ax.transAxes, verticalalignment='top')
    ax.axis("off")
    plt.show()
    plt.close(fig)

    plt.close('all')


def draw_dashed_line(img, pt1, pt2, color, thickness=1, dash_length=10):
    """
    Trace une ligne pointillée entre pt1 et pt2.
    - pt1, pt2 : tuples (x, y)
    - dash_length : longueur d’un segment (pixels)

    # Exemple d'utilisation
    cX, cY = 100, 100
    endX, endY = 300, 250
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    draw_dashed_line(img, (cX, cY), (endX, endY), (0, 255, 0), thickness=2, dash_length=15)
    cv2.imshow("Dashed line", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    """
    pt1 = np.array(pt1)
    pt2 = np.array(pt2)
    line_vec = pt2 - pt1
    line_len = np.linalg.norm(line_vec)
    line_dir = line_vec / line_len
    num_dashes = int(line_len / dash_length / 2)

    for i in range(num_dashes):
        start = pt1 + line_dir * (2 * i * dash_length)
        end = pt1 + line_dir * ((2 * i + 1) * dash_length)
        cv2.line(img, tuple(start.astype(int)), tuple(end.astype(int)), color, thickness)


def get_color_BGR(name):
    """
    Retourne la couleur BGR correspondant au nom donné.
    """
    colors = {
        "rouge":       (0, 0, 255),
        "vert":        (0, 255, 0),
        "bleu":        (255, 0, 0),
        "cyan":        (255, 255, 0),
        "magenta":     (255, 0, 255),
        "orange":      (0, 165, 255),
        "rose":        (203, 192, 255),
        "blanc":       (255, 255, 255),
        "gris":        (128, 128, 128),
        "violet":      (211, 0, 148),
        "jaune":       (0, 255, 255),
        "turquoise":   (208, 224, 64),
        "marron":      (42, 42, 165),
        "olive":       (0, 128, 128),
        "lavande":     (250, 230, 230),
        "bleu_clair":  (255, 200, 100),
        "vert_clair":  (144, 238, 144),
        "rose_foncé":  (147, 20, 80),
        "beige":       (220, 245, 245),
        "noir":        (0, 0, 0)
    }
    return colors.get(name.lower(), (0, 0, 0))  # Retourne noir si non trouvé



def best_thread_count(io_bound: bool = True) -> int:
    """
    Determine an optimal number of threads based on the workload type.

    Parameters
    ----------
    io_bound : bool, optional
        If True (default), the function returns a thread count suitable
        for I/O-bound tasks (disk access, file loading, RawPy, network).
        If False, it returns a thread count suitable for CPU-bound tasks.

    Returns
    -------
    int
        A reasonable number of worker threads.
    """
    cpu_count: int = multiprocessing.cpu_count()

    if io_bound:
        # For I/O-bound tasks: use half the logical CPUs, capped at 32.
        return int(min(32, cpu_count / 2))

    # For CPU-bound tasks: use all logical CPU cores.
    return cpu_count


# ----------------------
# Détection ArUco avec angle, centre
# ----------------------


def detect_aruco_marker(
    image: np.ndarray,
    arucoDict: "cv2.aruco_Dictionary",
    title: str = "",
    show: bool = False,
    verbose: bool = True
) -> Tuple[List[Tuple[int, float, Tuple[int, int], np.ndarray]], np.ndarray]:
    """
    Détecte les marqueurs ArUco dans une image.

    Retourne :
        - marker_data : liste de tuples (markerID, angle_deg, (cX, cY), corners_array)
        - image_out   : l'image originale ou l'image annotée (si show=True)

    Paramètres
    ----------
    image : np.ndarray
        Image BGR OpenCV.
    arucoDict : cv2.aruco_Dictionary
        Dictionnaire ArUco utilisé pour la détection.
    title : str
        Titre optionnel pour l'affichage.
    show : bool
        Affiche l'image avec les marqueurs détectés.
    verbose : bool
        Affiche les informations textuelles de détection.

    Notes
    -----
    - L’image d’entrée N’EST PAS modifiée. Si show=True, seule l’image retournée est annotée.
    """

    # ---- Création des paramètres ArUco
    try:
        arucoParams = cv2.aruco.DetectorParameters_create()
    except AttributeError:
        arucoParams = cv2.aruco.DetectorParameters()

    # ---- Détection initiale
    corners_list, ids, _ = cv2.aruco.detectMarkers(image, arucoDict, parameters=arucoParams)

    if corners_list is None or len(corners_list) == 0:
        if verbose:
            print("Aucun marqueur détecté !")
        return [], image   # retourne deux valeurs !

    ids = ids.flatten()
    marker_data = []

    # Copie pour l'affichage (NE MODIFIE JAMAIS l'image d'entrée)
    img_visu = image.copy()

    # ---- Boucle sur les marqueurs détectés
    for markerCorners, markerID in zip(corners_list, ids):
        corners_array = markerCorners.reshape((4, 2))

        # Calcul du vecteur principal
        principal_axis_ = (corners_array[0] - corners_array[3]) + (corners_array[1] - corners_array[2])
        principal_axis = principal_axis_ / np.linalg.norm(principal_axis_)

        # Angle en degrés
        angle = float(np.rad2deg(np.arctan2(principal_axis[1], principal_axis[0])))

        # Centre (cX, cY)
        cX = int(np.mean(corners_array[:, 0]))
        cY = int(np.mean(corners_array[:, 1]))

        if verbose:
            print(f"{title}: ID {markerID}, angle={angle:.1f}°, centre=({cX},{cY})")

        # --- Affichage si demandé
        if show:
            # Dessin du quadrilatère
            for i in range(4):
                pt1 = tuple(corners_array[i].astype(int))
                pt2 = tuple(corners_array[(i + 1) % 4].astype(int))
                cv2.line(img_visu, pt1, pt2, (0, 255, 0), 2)

            # Centre
            cv2.circle(img_visu, (cX, cY), 5, (0, 0, 255), -1)

            # ID
            cv2.putText(img_visu, f"ID{markerID}", (cX + 5, cY - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # Axe principal
            marker_width = int(np.linalg.norm(corners_array[0] - corners_array[1]))
            line_length = 4 * marker_width
            endX = int(cX + principal_axis[0] * line_length)
            endY = int(cY + principal_axis[1] * line_length)
            cv2.line(img_visu, (cX, cY), (endX, endY), (0, 255, 0), 2)

        # Append du résultat
        marker_data.append((int(markerID), angle, (cX, cY), corners_array))

    # ---- Affichage final (une seule fois)
    if show:
        plt.imshow(cv2.cvtColor(img_visu, cv2.COLOR_BGR2RGB))
        plt.title(title)
        plt.axis("off")
        plt.show()

    return marker_data, img_visu


# ----------------------
# Modules utilitaires
# ----------------------
# Affichage console
#

def load_relative_time_line(folderMissionPath):
    """
    Load the relative timeline JSON file into self.dic_relative_time_line.
    """

    json_path = Path(folderMissionPath) / "FlightAnalytics" / "time_line.json"

    if not json_path.exists():
        print(f"⚠️ Timeline file not found: {json_path}")
        dic_relative_time_line = {}
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            dic_relative_time_line = json.load(f)
        print(Uti.Style.GREEN + "✔️ Relative timeline loaded successfully." + Uti.Style.RESET)

    except Exception as e:
        print(Uti.Style.RED + f"❌ Error loading timeline file: {e}" + Uti.Style.RESET)
        dic_relative_time_line = {}
    return dic_relative_time_line



def extract_relative_time_line(dic_relative_time_line, file_name: str, type_img: str, ext: str) -> float:
    """
    Return the relative time line for a given image file.
    Handles VIS/dng, NIR/raw, and NIR/jpg (special case).

    Parameters:
        file_name : str
            The name of the image file (with extension).
        type_img : str
            Either 'VIS' or 'NIR'.
        ext : str
            Extension of the file ('dng', 'raw', 'jpg').

    Returns:
        float : relative time line
    """
    file_stem = Path(file_name).stem  # file name without extension

    # Default value if not found
    relative_time_line = 999.0

    if type_img not in dic_relative_time_line:
        print(f"⚠️ extract_relative_time_line: type_img '{type_img}' not in dic_relative_time_line")
        return relative_time_line

    img_list = dic_relative_time_line[type_img]

    if ext.lower() in ["dng", "raw"]:
        # Look for exact match in the stem of img_path
        for dic in img_list:
            if Path(dic["img_path"]).stem == file_stem:
                relative_time_line = dic.get("relative_timeline", 999.0)
                break

    elif ext.lower() == "jpg" and type_img == "NIR":
        # Special case: NIR/jpg → find the RAW image with num_img = JPG num_img - 1
        try:
            jpg_num = int(file_stem.split("_")[-1])
        except Exception as e:
            print(f"⚠️ extract_relative_time_line: cannot extract num_img from '{file_name}' : {e}")
            return relative_time_line

        for dic in img_list:
            if dic.get("num_img") == jpg_num - 1:
                relative_time_line = dic.get("relative_timeline", 999.0)
                break

    else:
        print(f"⚠️ extract_relative_time_line: file '{file_name}' with ext '{ext}' not handled")

    return relative_time_line



def plot_angles(
    time: Union[List[float], List[List[float]]],
    angles: Union[List[float], List[List[float]]],
    mode: str = "img",
    color: Union[str, List[str], None] = None
) -> None:
    """
    Plot one or multiple angle curves versus their own time axes.

    Parameters
    ----------
    time : list or list of lists
        Time values for each curve.
    angles : list or list of lists
        Angle values for each curve.
    mode : str
        "ground", "img" or "delta" to define the base label.
    color : str or list of str or None
        Color(s) for the curves. If None, default matplotlib colors are used.
    """

    # Determine the label
    if mode == "ground":
        label_base = "Ground reference angle"
    elif mode == "img":
        label_base = "Image reference angle"
    elif mode == "delta":
        label_base = "Delta angle (ground - image)"
    else:
        label_base = ""

    plt.figure(figsize=(8, 4))

    # Detect if there is a single curve
    is_single_curve = isinstance(angles[0], (int, float, np.floating))

    # Normalize to list of lists
    if is_single_curve:
        angles_list = [angles]
        time_list = [time]
    else:
        angles_list = angles
        time_list = time

    # Handle colors
    if color is None:
        # Use matplotlib default color cycle
        colors_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
        colors = [colors_cycle[i % len(colors_cycle)] for i in range(len(angles_list))]
    elif isinstance(color, list):
        colors = color
    else:
        # Single color given → use matplotlib default cycle for other curves
        colors_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
        colors = [color] + [colors_cycle[i % len(colors_cycle)] for i in range(1, len(angles_list))]

    def get_color(i: int) -> str:
        return colors[i % len(colors)]

    # Plotting
    for i, (t, y) in enumerate(zip(time_list, angles_list)):
        if len(t) != len(y):
            raise ValueError(f"Curve {i}: time and angles must have the same length.")

        plt.plot(
            t, y,
            marker="o",
            color=get_color(i),
            label=f"{label_base} ({i})" if len(angles_list) > 1 else label_base
        )

    plt.xlabel("Time (s)")
    plt.ylabel("Angle (°)")
    plt.title(f"Evolution of {label_base}")
    plt.legend()
    plt.grid(True)
    plt.show()




def unwrap_angles(angle_list_deg):
    """
    Déplie une liste d'angles en degrés (-180 à 180) en une série continue.
    """
    angles_rad = np.radians(angle_list_deg)
    unwrapped_rad = np.unwrap(angles_rad)  # rend la série continue
    return np.degrees(unwrapped_rad)       # on repasse en degrés


def print_marker_results(markers, image_type="VI"):
    for marker in markers:
        markerID, angle, center, corners = marker
        print(f"{image_type}: ID {markerID}, angle={angle:.1f}°, centre={center}")


# Retourne le dictionnaire ArUco COMPATIBLE avec toutes les versions OpenCV.
def get_aruco_dict(dict_name="DICT_4X4_50", verbose=False):
    """Retourne le dictionnaire ArUco compatible avec toutes les versions OpenCV."""
    try:
        if verbose:
            print(f"Dictionnaire ArUco {dict_name} chargé ✅")
        return cv2.aruco.getPredefinedDictionary(ARUCO_DICT[dict_name])

    except AttributeError:
        return cv2.aruco.Dictionary_get(ARUCO_DICT[dict_name])


def read_transfer_info(folderMissionPath: Path, typ_img: str, ext_img: str, section: str):
    """
    section = 'tkoff' ou 'sync'
    """

    # Construction du chemin du fichier JSON
    json_file = folderMissionPath / "FlightAnalytics" / f"transfer_info_{typ_img}_{ext_img}.json"
    # print(f"DEBUG  def read_transfer_info    Lecture du fichier : {json_file}")

    # Chargement du fichier JSON
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Vérification que la section existe
    if section not in data:
        raise KeyError(f"La section '{section}' n'existe pas dans le fichier JSON.")

    block = data[section]

    outputFolder = block.get("outputFolder")
    idMin = block.get("idMin")
    idMax = block.get("idMax")
    listCopiedImages = block.get("listCopiedImages", [])

    return outputFolder, idMin, idMax, listCopiedImages


def cached_tif(path):
    return path[:-4]+"_RawTherapee.tif"


def load_dng(path, template="DJI_neutral.pp3"):
    out_file = cached_tif(path)
    # assert osp.isfile(RAWTHERAPEEPATH), "RAWTHERAPEE NOT FOUND"
    cmd = [
        RAWTHERAPEEPATH,
        "-t", "-o", out_file,
        "-p", osp.join(osp.dirname(__file__), "..", "thirdparty", "rawtherapee", template),
        "-c", path
    ]
    if not osp.isfile(out_file):
        subprocess.call(cmd)
    else:
        # logging.info("DNG already processed by RAW THERAPEE {}".format(path))
        # print(f'DEBUG  "DNG already processed by RAW THERAPEE {format(path) }')
        pass
    assert osp.isfile(out_file), f"DNG file not converted! {out_file}"
    return load_tif(out_file), out_file


def load_tif_balth(in_file):
    flags = cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR
    flags |= cv2.IMREAD_IGNORE_ORIENTATION
    return cv2.cvtColor(cv2.imread(in_file, flags=flags), cv2.COLOR_BGR2RGB)/(2.**16-1)


def load_tif(in_file):
    flags = cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR
    flags |= cv2.IMREAD_IGNORE_ORIENTATION

    img16 = cv2.imread(in_file, flags=flags)
    img16 = cv2.cvtColor(img16, cv2.COLOR_BGR2RGB)

    # Convertir 16 bits → 8 bits pour OpenCV ArUco
    img8 = cv2.convertScaleAbs(img16, alpha=255.0/65535.0)

    return img8


def detection_arruco_VIS_NIR(base_dir, name_folder, name_image_VI, name_image_IR, aruco_dict):
    vis_path = os.path.join(base_dir, name_folder, name_image_VI)  # "VI.tif"
    ir_path = os.path.join(base_dir, name_folder, name_image_IR)  # "IR.tif"

    img_vis = cv2.imread(vis_path)
    img_ir = cv2.imread(ir_path)
    if img_vis is None or img_ir is None:
        raise FileNotFoundError("Impossible de charger l'une des images")


    # Copier les images pour dessin
    img_vis_draw = img_vis.copy()
    img_ir_draw = img_ir.copy()

    markers_vis, img_vis_annotated = detect_aruco_marker(img_vis.copy(), aruco_dict, show=True, title="Visible")
    markers_ir, img_ir_annotated = detect_aruco_marker(img_ir.copy(), aruco_dict, show=True, title="Infrarouge")

    print("\nRésultats détection :")
    print_marker_results(markers_vis, "Visible    ")
    print_marker_results(markers_ir, "Infra Rouge")

    # Affichage côte-à-côte
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    axes[0].imshow(cv2.cvtColor(img_vis_annotated, cv2.COLOR_BGR2RGB))
    axes[0].set_title("Visible (VI)")
    axes[0].axis("off")

    axes[1].imshow(cv2.cvtColor(img_ir_annotated, cv2.COLOR_BGR2RGB))
    axes[1].set_title("Infrarouge (IR)")
    axes[1].axis("off")

    plt.tight_layout()
    plt.show()
    return


# --------------------------------------------------------------
# Utilisation
# --------------------------------------------------------------
if __name__ == "__main__":
    if os.name == 'nt':
        RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
        assert osp.exists(RAWTHERAPEEPATH), "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
        EXIFTOOLPATH = osp.join(osp.dirname(__file__), "..", "thirdparty", "exiftool", "exiftool.exe")
        assert osp.exists(EXIFTOOLPATH), "Requires exif tool at {} from https://exiftool.org/".format(EXIFTOOLPATH)

    else:
        RAWTHERAPEEPATH = "rawtherapee-cli"
        EXIFTOOLPATH = "exiftool"

    print(f'DEBUG  cpu_count { multiprocessing.cpu_count()}')

    folderMissionPath = Path(r"C:\Air-Mission\FLY-20220125-1159-Blassac")
    name_folder = "Synchro"


    t0 = time.perf_counter()
    typ_img = "VIS"  # "NIR"
    ext_img = "dng"  # "jpg"
    results, x_vals, y_vals = process_aruco_images(
        folderMissionPath=folderMissionPath,
        name_folder=name_folder,
        typ_img=typ_img,
        ext_img=ext_img,
        show=False,  # show each detection window?
        verbose=False,  # print detailed info?
        force_aruco_cache=True,  # overwrite .exif cache if False
    )
    t1 = time.perf_counter()
    print(Uti.Style.CYAN + f"[TIMING] process_aruco_images : {t1 - t0:.3f} s" + Uti.Style.RESET)
    angles_deg = [r['angle_img'] for r in results if r['angle_img'] is not None]
    if len(angles_deg) > 1:
        angles_unwrapped_VIS = unwrap_angles(angles_deg)
    time_VIS = [r['relative_time_line'] for r in results if r['relative_time_line'] is not None]

    t0 = time.perf_counter()
    typ_img = "NIR"  # "NIR"
    ext_img = "jpg"  # "jpg"
    results, x_vals, y_vals = process_aruco_images(
        folderMissionPath=folderMissionPath,
        name_folder=name_folder,
        typ_img=typ_img,
        ext_img=ext_img,
        show=False,  # show each detection window?
        verbose=False,  # print detailed info?
        force_aruco_cache=True,  # overwrite .exif cache if False
    )
    t1 = time.perf_counter()
    print(Uti.Style.CYAN + f"[TIMING] process_aruco_images : {t1 - t0:.3f} s" + Uti.Style.RESET)
    angles_deg = [r['angle_img'] for r in results if r['angle_img'] is not None]
    if len(angles_deg) > 1:
        angles_unwrapped_NIR = unwrap_angles(angles_deg)
    time_NIR = [r['relative_time_line'] for r in results if r['relative_time_line'] is not None]

    # ------------------------------------------------------------
    # Optional graph
    # ------------------------------------------------------------
    graph_angle = True
    if graph_angle:
        if len(angles_unwrapped_VIS) > 1 and len(angles_unwrapped_NIR) > 1:
            plot_angles([time_VIS, time_NIR], [angles_unwrapped_VIS, angles_unwrapped_NIR], mode='img', color='g')

            time_shift = -31.0  # seconds
            time_NIR_shifted = [t + time_shift for t in time_NIR]
            plot_angles([time_VIS, time_NIR_shifted],[angles_unwrapped_VIS, angles_unwrapped_NIR],mode='img',color=['b', 'r']
            )
    exit(2025)
