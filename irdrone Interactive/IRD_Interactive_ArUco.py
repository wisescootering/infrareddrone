# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
# --------------------------------------------------------------------------------
#   IR_drone interactive
#
#   2025-12-17 00:35:10   V002   *
# ---------------------------------------------------------------------------------


import os
import os.path as osp
from pathlib import Path
import numpy as np
import cv2
import matplotlib.pyplot as plt
import time
import json
from json import JSONDecodeError
from typing import List, Tuple, Optional, Sequence, Dict, Any, Union, Callable, Iterable

import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy

import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import to_json_safe
from IRD_Interactive_utils import safe_path
from IRD_Interactive_color_style import Style

from config import RAWTHERAPEEPATH
assert Path(RAWTHERAPEEPATH).exists(), "Please install raw therapee first http://www.rawtherapee.com/downloads/ \nshall be installed:{}".format(RAWTHERAPEEPATH)


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
        spectral_band: str,
        suffix_image: str,
        save_check_detection_img: bool = False,
        verbose: bool = True,
        use_aruco_cache: bool = False,
        img_check_suffix="jpg",
        multi_thread=False,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[int], None]] = None
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
        Name of the subfolder containing the images (e.g. "AerialPhotography").
    spectral_band : str
        Image type: "VIS" or "NIR".
    suffix_image : str
        Image extension: "dng", "jpg", ...
    save_check_detection_img : bool, optional
        Save each detection result image in folder for checking. Default is False.
    verbose : bool, optional
        Print debug information. Default is False.
    use_aruco_cache : bool, optional
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

    """

    # 1) Retrieve list of images
    outputFolder, idMin, idMax, listImages = read_transfer_info(
        folderMissionPath, spectral_band, suffix_image, section="sync"
    )


    folder_images = folderMissionPath / name_folder

    dic_relative_time_line = load_relative_time_line(folderMissionPath, spectral_band)
    # print(f'DEBUG  001 dic_relative_time_line = {dic_relative_time_line} ')

    results = []
    x_vals = []
    y_vals = []

    max_workers = best_thread_count(io_bound=True)
    print(Style.CYAN + f"[INFO] Processing {len(listImages)} images using {max_workers} threads..." + Style.RESET)

    # ------------------------------------------------------------
    # Worker function (one image per thread)
    # ------------------------------------------------------------
    def process_one(i, img_name, folderMissionPath):
        img_path = folder_images / img_name
        ext = img_name.lower().split('.')[-1]

        # --------------------------------------------------------
        # 1) FAST PATH : cache EXIF détecté → aucun chargement image
        # --------------------------------------------------------
        cached = read_aruco_cache(img_path)
        if cached and use_aruco_cache:
            print(Style.YELLOW + f'[Warning]    USE CACHE {use_aruco_cache}' + Style.RESET)
            return i, img_name, cached

        # --------------------------------------------------------
        # 2) SLOW PATH : pas de cache pour les données aruco de détection d'angle → chargement image normal
        # --------------------------------------------------------
        if ext == "dng" and spectral_band in ["VIS", "NIR"]:
            img_cv, _ = load_dng_for_aruco(str(img_path), folderMissionPath.parent)
        else:
            img_cv = cv2.imread(str(img_path))

        if img_cv is None:
            return i, img_name, None

        # --------------------------------------------------------
        # 3) ArUco detection
        # --------------------------------------------------------
        result, _, marker_data_ID = detect_mobile_marker_absolute(
            image_cv=img_cv,
            img_path=img_path,
            arucoDict=get_aruco_dict("DICT_4X4_50"),
            fixed_ids=[5, 22, 16, 13],
            mobile_id=0,
            marker_data=None,
            title=name_folder + " - " + img_name,
            verbose=verbose,
            use_aruco_cache=use_aruco_cache,
        )
        result["relative_timeline"] = extract_relative_time_line(dic_relative_time_line, Path(img_path).name, spectral_band, suffix_image)
        # --------------------------------------------------------
        # Save check detection images (thread-safe and no GUI)
        # --------------------------------------------------------
        if save_check_detection_img and result is not None:
            check_detection_dir = safe_path(Path(folderMissionPath.parent) / "Synchro" / "Check_ARUCO")
            check_detection_dir.mkdir(exist_ok=True)

            if save_check_detection_img and result is not None and marker_data_ID is not None:

                img_check = draw_aruco_overlay(
                    img_cv,
                    result,
                    marker_data_ID,
                    fixed_ids=[5, 22, 16, 13]
                )

                out_path = check_detection_dir / f"{img_path.stem}_aruco.{img_check_suffix}"
                if img_check_suffix == "jpg":
                    cv2.imwrite(str(out_path), img_check, [cv2.IMWRITE_JPEG_QUALITY, 90])
                else:
                    cv2.imwrite(str(out_path), img_check)

            out_path = check_detection_dir / f"{img_path.stem}_aruco.{img_check_suffix}"
            if img_check_suffix == "jpg":
                cv2.imwrite(str(out_path), img_check, [cv2.IMWRITE_JPEG_QUALITY, 90])
            else:
                cv2.imwrite(str(out_path), img_check)

        return i, img_name, result

    # ------------------------------------------------------------
    # MULTITHREAD EXECUTION
    # ------------------------------------------------------------

    if not multi_thread:
        for i, img_name in enumerate(listImages, start=1):
            i, img_name, result = process_one(i, img_name, folderMissionPath)
            pct = int(100 * i / len(listImages))
            if progress_callback is not None:
                progress_callback(pct)
            if result:
                results.append({
                    "image": img_name,
                    "angle_abs": result["angle_abs"],
                    "angle_img": result["angle_img"],
                    "delta": result["delta_abs_img"],
                    "relative_timeline": result["relative_timeline"],
                })
                x_vals.append(result["relative_timeline"])
                y_vals.append(result["angle_img"])

    else:
        futures = []
        total = len(listImages)
        done = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:


            for i, img_name in enumerate(listImages, start=1):
                futures.append(executor.submit(process_one, i, img_name, folderMissionPath))
            for future in as_completed(futures):
                i, img_name, result = future.result()
                done += 1
                pct = int(100 * done / total)
                if progress_callback is not None:
                    progress_callback(pct)
                if result:
                    results.append({
                        "image": img_name,
                        "angle_abs": result["angle_abs"],
                        "angle_img": result["angle_img"],
                        "delta": result["delta_abs_img"],
                        "relative_timeline": result["relative_timeline"],
                    })
                    x_vals.append(result["relative_timeline"])
                    y_vals.append(result["angle_img"])

    # ------------------------------------------------------------
    # Order results chronologically
    # ------------------------------------------------------------

    # ordered = sorted(zip(results), key=lambda t: t[0])
    # results = [t[0] for t in ordered]
    ordered = sorted(zip(x_vals, y_vals, results), key=lambda t: t[0])
    x_vals = [t[0] for t in ordered]
    y_vals = [t[1] for t in ordered]
    results = [t[2] for t in ordered]

    return results, x_vals, y_vals

def detect_mobile_marker_absolute(image_cv=None,
                                  img_path=None,
                                  arucoDict=None,
                                  fixed_ids=[5, 22, 16, 13],
                                  mobile_id=0,
                                  marker_data=None,
                                  show=False,
                                  title="",
                                  verbose=True,
                                  use_aruco_cache=False
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
    if r and use_aruco_cache:
        print(Style.GREEN + f'[INFO] Traitement AVEC CACHE de {img_path}' + Style.RESET)
        return r, None, None
    else:
        print(Style.GREEN + f'[INFO] Détection des Aruco dans  {img_path}' + Style.RESET)

    img_cv_out = image_cv.copy() if image_cv is not None else None

    # --- détecter les marqueurs si cache non utilisé
    if marker_data is None:
        if image_cv is None or arucoDict is None:
            raise ValueError(Style.YELLOW + "Soit marker_data doit être fourni, soit image_cv et arucoDict." + Style.RESET)
        marker_data = detect_aruco_marker(image_cv.copy(), arucoDict, title=title, verbose=verbose)

    if not marker_data:
        if verbose: print(Style.YELLOW + "Aucun marqueur détecté !" + Style.RESET)
        return None, img_cv_out, None

    # organiser les données par ID
    marker_data_ID = {int(entry[0]): {"angle_img": entry[1],
                          "center": np.array(entry[2], dtype=float),
                          "corners": np.array(entry[3], dtype=float)}
          for entry in marker_data}

    # vérifier présence des marqueurs fixes et mobile
    missing_fixed = [fid for fid in fixed_ids if fid not in marker_data_ID]
    mobile_missing = int(mobile_id not in marker_data_ID)

    result = {
        "missing_fixed": missing_fixed,
        "mobile_id": int(mobile_id),
        "center_abs": None,
        "angle_abs": None,
        "angle_img": marker_data_ID[mobile_id]["angle_img"] if not mobile_missing else None,
        "delta_abs_img": None,
        "x_ref": None,
        "y_ref": None,
        "width_px": None,
        "height_px": None,
    }

    if missing_fixed or mobile_missing:
        if missing_fixed:
            if verbose: print(Style.YELLOW + f"⚠️Tous les marqueurs fixes ne sont pas détectés ! manquants = {missing_fixed}" + Style.RESET)
        if mobile_missing:
            if verbose: print(Style.RED + f"❌ Le marqueur mobile ({mobile_id}) n'est pas détecté !" + Style.RESET)
        write_aruco_cache(img_path, result)
        return result, img_cv_out, marker_data_ID

    # --- calcul des coordonnées et de l'angle absolu
    geom = compute_mobile_marker_geometry(marker_data_ID, fixed_ids, mobile_id)
    if geom is not None:
        result.update(geom)
    else:
        if verbose: print(Style.YELLOW + f"⚠  Impossible de calculer la géométrie absolue." + Style.RESET)

    write_aruco_cache(img_path, result)
    return result, img_cv_out, marker_data_ID


def detect_aruco_marker(
    image_cv: np.ndarray,
    arucoDict: "cv2.aruco_Dictionary",
    title: str = "",
    verbose: bool = True
) -> Tuple[List[Tuple[int, float, Tuple[int, int], np.ndarray]], np.ndarray]:
    """
    Détecte les marqueurs ArUco dans une image_cv (au format d'un tableau numpy compatible cv2).

    Retourne :
        - marker_data : liste de tuples (markerID, angle_deg, (cX, cY), corners_array)
    ⚠️ Aucun affichage, aucune GUI, aucun matplotlib.     Thread-safe.

    """

    verbose = True

    try:
        arucoParams = cv2.aruco.DetectorParameters_create()
    except AttributeError:
        arucoParams = cv2.aruco.DetectorParameters()

    corners_list, ids, _ = cv2.aruco.detectMarkers(image_cv, arucoDict, parameters=arucoParams)

    if corners_list is None or len(corners_list) == 0:
        if verbose:
            print(Style.YELLOW + "[WARNING] Aucun marqueur détecté" + Style.RESET)
        return []

    ids = ids.flatten()
    marker_data = []

    for markerCorners, markerID in zip(corners_list, ids):
        corners_array = markerCorners.reshape((4, 2))

        principal_axis_ = (
            (corners_array[0] - corners_array[3]) +
            (corners_array[1] - corners_array[2])
        )
        principal_axis = principal_axis_ / np.linalg.norm(principal_axis_)

        angle = float(np.rad2deg(np.arctan2(principal_axis[1], principal_axis[0])))

        cX = int(np.mean(corners_array[:, 0]))
        cY = int(np.mean(corners_array[:, 1]))

        if verbose:
            print(f"ID {markerID}, angle={angle:.1f}°, centre=({cX},{cY})")

        marker_data.append((int(markerID), angle, (cX, cY), corners_array))

    return marker_data

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

        data["aruco"] = aruco_data  # Update only the "aruco" key

        rel_tl = data.get("RelativeTimeLine", None)

        if rel_tl is not None:
            data["aruco"]["relative_timeline"] = copy.deepcopy(rel_tl)

        data_json_safe = {
            k: Uti.to_json_safe(v)
            for k, v in data.items()
        }

        # Save back to disk
        with open(exif_path, "w", encoding="utf-8") as f:
            json.dump(data_json_safe, f, indent=4, ensure_ascii=False)

        return True  # Success

    except Exception as e:
        print(f"[ERROR] Failed to write EXIF cache for {img_path}: {e}")
        return False  # Failure

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
            - "relative_timeline" key from top-level JSON (if exists)
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

    # Add top-level "relative time line" as "relative_timeline"
    rel_time = data.get("RelativeTimeLine", None)
    if rel_time is not None:
        aruco["relative_timeline"] = rel_time

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

def compute_mobile_marker_geometry(marker_data_ID, fixed_ids, mobile_id):
    """
    Calcul de toutes les grandeurs géométriques du marqueur mobile dans le repère absolu.
    """
    try:
        fixed_centers = [marker_data_ID[fid]["center"] for fid in fixed_ids]
        mobile_center = marker_data_ID[mobile_id]["center"]
        corners_m = marker_data_ID[mobile_id]["corners"]

        x_ref, y_ref, normX, normY = compute_reference_vectors(fixed_centers)
        if x_ref is None:
            return None

        u = compute_mobile_axis(corners_m)
        if u is None:
            return None

        angle_abs, u_coord, v_coord, delta_angle = compute_angle_and_coords(
            u, x_ref, y_ref, mobile_center, fixed_centers[0], normX, normY, marker_data_ID[mobile_id]["angle_img"]
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

# ----------------------
# Modules utilitaires
# ----------------------

def compute_time_shift_L2(
    time_line_VIS: Sequence[float],
    angles_unwrapped_VIS: Sequence[float],
    time_line_NIR: Sequence[float],
    angles_unwrapped_NIR: Sequence[float],
    use_median: bool = False
) -> Tuple[float, float, Dict[str, Optional[float]]]:
    """
    Estimate the temporal offset Δt such that:
        theta_VIS(t) ≈ theta_NIR(t - Δt)

    under the assumption of uniform angular velocity.
    The offset is computed analytically by L2 minimization.

    Parameters
    ----------
    time_line_VIS : sequence of float
        Time stamps of VIS images.
    angles_unwrapped_VIS : sequence of float
        Unwrapped angular measurements for VIS images.
    time_line_NIR : sequence of float
        Time stamps of NIR images.
    angles_unwrapped_NIR : sequence of float
        Unwrapped angular measurements for NIR images.
    use_median : bool, optional
        If True, use the median estimator for VIS intercept (robust to outliers).
        If False, use the mean (default: False).

    Returns
    -------
    time_shift : float
        Estimated temporal offset Δt (seconds).
    omega : float
        Estimated angular velocity (rad/s or deg/s).
    metrics : dict
        Dictionary of quality indicators:
            - n_vis
            - n_nir
            - r2_nir
            - dt_iqr
            - dt_std
            - omega_vis
            - delta_omega
            - rel_delta_omega
    """

    # --- Convert to numpy arrays ---
    t_vis = np.asarray(time_line_VIS, dtype=float)
    th_vis = np.asarray(angles_unwrapped_VIS, dtype=float)
    t_nir = np.asarray(time_line_NIR, dtype=float)
    th_nir = np.asarray(angles_unwrapped_NIR, dtype=float)

    if t_nir.size < 2:
        raise ValueError("At least two NIR points are required")

    if t_vis.size < 1:
        raise ValueError("At least one VIS point is required")

    # --- 1. Linear regression on NIR (reference) ---
    omega, b_nir = np.polyfit(t_nir, th_nir, 1)

    th_nir_fit = omega * t_nir + b_nir
    ss_res = np.sum((th_nir - th_nir_fit) ** 2)
    ss_tot = np.sum((th_nir - np.mean(th_nir)) ** 2)
    r2_nir = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

    # --- 2. VIS intercepts projected onto NIR slope ---
    b_vis_vals = th_vis - omega * t_vis

    if use_median:
        b_vis = np.median(b_vis_vals)
    else:
        b_vis = np.mean(b_vis_vals)

    # --- Individual time shifts ---
    dt_vals = (b_nir - b_vis_vals) / omega

    dt_iqr = np.percentile(dt_vals, 75) - np.percentile(dt_vals, 25)
    dt_std = np.std(dt_vals) if dt_vals.size > 1 else 0.0

    # --- 3. Optimal global time shift ---
    time_shift = (b_nir - b_vis) / omega

    # --- 4. VIS slope consistency check (optional) ---
    if t_vis.size >= 2:
        omega_vis, _ = np.polyfit(t_vis, th_vis, 1)
        delta_omega = omega_vis - omega
        rel_delta_omega = abs(delta_omega / omega)
    else:
        omega_vis = None
        delta_omega = None
        rel_delta_omega = None

    metrics = {
        "n_vis": int(t_vis.size),
        "n_nir": int(t_nir.size),
        "r2_nir": r2_nir,
        "dt_iqr": dt_iqr,
        "dt_std": dt_std,
        "omega_vis": omega_vis,
        "delta_omega": delta_omega,
        "rel_delta_omega": rel_delta_omega,
    }

    return time_shift, omega, metrics



def load_relative_time_line(folderMissionPath, spectral_band):
    """
    Load the relative timeline JSON file into self.dic_relative_time_line.
    """
    try:
        json_path = safe_path(Path(folderMissionPath) / spectral_band / "time_line.json")

        if not json_path.exists():
            print(f"⚠️ Timeline file not found: {json_path}")
            dic_relative_time_line = {}
            return


        with open(json_path, "r", encoding="utf-8") as f:
            dic_relative_time_line = json.load(f)
        print(Style.GREEN + "✔️ Relative timeline loaded successfully." + Style.RESET)

    except Exception as e:
        print(Style.RED + f"❌ Error loading timeline file: {e}" + Style.RESET)
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
            Extension of the file ('dng').

    Returns:
        float : relative time line
    """
    file_stem = Path(file_name).stem  # file name without extension

    # Default value if not found
    relative_timeline = -9999.0

    if type_img not in dic_relative_time_line:
        print(f"⚠️ extract_relative_time_line: type_img '{type_img}' not in dic_relative_time_line")
        return relative_timeline

    img_list = dic_relative_time_line[type_img]

    if ext.lower() in ["dng"]:
        # Look for exact match in the stem of img_path
        for dic in img_list:
            if Path(dic["img_path"]).stem == file_stem:
                relative_timeline = dic.get("relative_timeline", -9999.0)
                break
    else:
        print(Style.YELLOW + f"⚠️ extract_relative_time_line: file '{file_name}' with ext '{ext}' not handled" + Style.RESET)

    return relative_timeline

def unwrap_angles(angle_list_deg):
    """
    Déplie une liste d'angles en degrés (-180 à 180) en une série continue.
    """
    angles_rad = np.radians(angle_list_deg)
    unwrapped_rad = np.unwrap(angles_rad)  # rend la série continue
    return np.degrees(unwrapped_rad)       # on repasse en degrés

def print_marker_results(markers, image_type="VIS"):
    for marker in markers:
        markerID, angle, center, corners = marker
        print(f"{image_type}: ID {markerID}, angle={angle:.1f}°, centre={center}")

def get_aruco_dict(dict_name="DICT_4X4_50", verbose=False):
    """Retourne le dictionnaire ArUco compatible avec toutes les versions OpenCV."""
    try:
        if verbose:
            print(f"Dictionnaire ArUco {dict_name} chargé ✅")
        return cv2.aruco.getPredefinedDictionary(ARUCO_DICT[dict_name])

    except AttributeError:
        return cv2.aruco.Dictionary_get(ARUCO_DICT[dict_name])

def read_transfer_info(folderMissionPath: Path, spectral_band: str, suffix_image: str, section: str):
    """
    section = 'tkoff' ou 'sync'
    """
    # Construction du chemin du fichier JSON
    json_file = folderMissionPath / spectral_band / f"transfer_info_{spectral_band}_{suffix_image}.json"

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

def cached_jpeg_old(path):
    p = Path(path)
    return str(p.with_suffix("")) + "_RawTherapee.jpg"

def cached_jpeg(path, folder_mission):
    """
    Calcule le chemin du JPEG RawTherapee dans :
    folder_mission / Synchro / VIS|NIR
    """
    p = Path(path)
    folder_mission = Path(folder_mission)

    # Détection du canal (VIS / NIR)
    spectral_band = p.parent.name  # "VIS" ou "NIR"

    out_dir = folder_mission / "Synchro" / spectral_band
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"{p.stem}_RawTherapee.jpg"

    return str(out_file)

def load_dng_for_aruco(path, folder_mission):
    out_file = cached_jpeg(path, folder_mission)
    cmd = [
        RAWTHERAPEEPATH,
        "-t",
        "-o", out_file,
        "-j95",
        "-p", osp.join(
            osp.dirname(__file__),
            "..", "thirdparty", "rawtherapee", "Aruco_Detection.pp3"
        ),
        "-c", path
    ]
    if not osp.isfile(out_file):
        subprocess.call(cmd)

    img_cv = cv2.imread(out_file, cv2.IMREAD_COLOR)
    return img_cv, out_file

def cached_tif(path):
    return path[:-4]+"_RawTherapee.tif"

def load_tif_radiometric(in_file):
    flags = cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR
    flags |= cv2.IMREAD_IGNORE_ORIENTATION
    return cv2.cvtColor(cv2.imread(in_file, flags=flags), cv2.COLOR_BGR2RGB)/(2.**16-1)

def load_tif_aruco(in_file):
    flags = cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR
    flags |= cv2.IMREAD_IGNORE_ORIENTATION

    img16 = cv2.imread(in_file, flags=flags)
    img16 = cv2.cvtColor(img16, cv2.COLOR_BGR2RGB)

    # Convertir 16 bits → 8 bits pour OpenCV ArUco
    img8 = cv2.convertScaleAbs(img16, alpha=255.0/65535.0)

    return img8

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

def abstract_time_line_alignement(time_shift, omega, metrics):
    msg_1 = f"Time alignment results:\n" \
          f"  Estimated time shift      : {time_shift:.3f} s\n" \
          f"  Angular velocity (NIR)    : {omega/6:.4f} rpm\n" \
          f"  Number of VIS points      : {metrics['n_vis']}\n" \
          f"  Number of NIR points      : {metrics['n_nir']}\n" \
          f"  NIR linear fit R²         : {metrics['r2_nir']:.6f}\n" \
          f"  Δt interquartile range    : {metrics['dt_iqr']:.4f} s\n" \
          f"  Δt standard deviation     : {metrics['dt_std']:.4f} s\n"
    print(Style.GREEN + msg_1 + Style.RESET)

    if metrics.get("omega_vis") is not None:
        msg_2 = f"  Angular velocity (VIS)    : {metrics['omega_vis']/6:.4f} rpm\n" \
                f"  Relative Δomega           : {(100.0 * metrics['rel_delta_omega']):.2e} %"
        print(Style.GREEN + msg_2 + Style.RESET)
        return msg_1 + msg_2
    else:
        print("  VIS angular velocity      : not estimated (single VIS point)")
        return msg_1

def plot_angles_alignement_time_line(
    time: Union[Sequence[float], Sequence[Sequence[float]]],
    angles: Union[Sequence[float], Sequence[Sequence[float]]],
    title_angles: List[str],
    mode: str = "img",
    color: Union[str, List[str], None] = None,
    save_graph: bool = True,
    folder_save: Path = None,
    filename: str = "check_time_alignment.png",
) -> None:
    """
    Plot one or multiple angle curves versus their own time axes
    and save the figure to disk (GUI-safe, non-interactive).

    Parameters
    ----------
    time : sequence or sequence of sequences
        Time values (seconds).
    angles : sequence or sequence of sequences
        Angle values (degrees).
    title_angles : list of str
        Labels for each curve.
    mode : str
        "ground", "img" or "delta" to define the base label.
    color : str or list of str or None
        Color(s) for the curves.
    save_graph : bool
        If True, save the figure to disk.
    folder_save : Path
        Output directory for the figure.
    filename : str
        Name of the saved image file.
    """

    # --- Label selection ---
    if mode == "ground":
        label_base = "Ground reference angle"
    elif mode == "img":
        label_base = "Image reference angle"
    elif mode == "delta":
        label_base = "Delta angle (ground - image)"
    else:
        label_base = "Angle"

    # --- Normalize input to list of lists ---
    is_single_curve = isinstance(angles[0], (int, float, np.floating))

    if is_single_curve:
        angles_list = [angles]
        time_list = [time]
    else:
        angles_list = list(angles)
        time_list = list(time)

    if len(title_angles) != len(angles_list):
        raise ValueError("title_angles must match the number of curves.")

    # --- Figure creation (GUI-safe) ---
    fig, ax = plt.subplots(figsize=(8, 4))

    # --- Colors handling ---
    if color is None:
        colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    elif isinstance(color, list):
        colors = color
    else:
        colors = [color]

    # --- Plot curves ---
    for i, (t, y) in enumerate(zip(time_list, angles_list)):
        if len(t) != len(y):
            raise ValueError(f"Curve {i}: time and angles must have the same length.")

        ax.plot(
            t,
            y,
            marker="o",
            color=colors[i % len(colors)],
            label=f"{title_angles[i]} ({len(y)} img)"
        )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Angle (deg)")
    ax.set_title(f"Evolution of {label_base}")
    ax.legend()
    ax.grid(True)

    # --- Save and cleanup ---
    if save_graph:
        if folder_save is None:
            raise ValueError("folder_save must be specified when save_graph=True")

        folder_save.mkdir(parents=True, exist_ok=True)
        out_path = folder_save / filename
        fig.savefig(out_path, dpi=150, bbox_inches="tight")

    plt.close(fig)

def draw_aruco_overlay(
    img_cv: Optional[np.ndarray],
    result: Optional[Dict[str, Any]],
    marker_data_ID: Optional[Dict[int, Dict[str, Any]]],
    fixed_ids: Optional[Iterable[int]],
) -> Optional[np.ndarray]:
    """
    Draw ArUco-related overlays directly on an OpenCV image.

    This function is *PyQt-safe*: it does not modify the input image in place,
    but works on a copy and returns the annotated image.

    Overlays may include:
    - Fixed markers centers
    - Mobile marker center
    - Image-based orientation
    - Absolute (ground-referenced) orientation
    - Absolute reference frame arrows
    - Text legend (angles, deltas, status)

    Parameters
    ----------
    img_cv : np.ndarray or None
        Input image in OpenCV format (BGR, HxWx3).
    result : dict or None
        Dictionary containing ArUco computation results
        (angles, references, flags, etc.).
    marker_data_ID : dict or None
        Marker data indexed by marker ID. Each entry may contain
        'center', 'corners', etc.
    fixed_ids : iterable of int or None
        List of fixed marker IDs used as absolute references.

    Returns
    -------
    np.ndarray or None
        Annotated OpenCV image, or None if input image/result is invalid.
    """
    try:
        if img_cv is None or result is None:
            return img_cv

        img_cv_out = img_cv.copy()

        has_md = marker_data_ID is not None
        mid = result.get("mobile_id")

        has_mobile = has_md and mid in marker_data_ID
        has_corners = has_mobile and "corners" in marker_data_ID[mid]

        has_absolute_ref = (
            has_md
            and fixed_ids is not None
            and not result.get("missing_fixed", True)
            and result.get("x_ref") is not None
            and result.get("y_ref") is not None
        )

        # --- fixed markers
        if has_md and fixed_ids is not None and not result.get("missing_fixed", False):
            draw_fixed_markers(img_cv_out, marker_data_ID, fixed_ids)

        # --- mobile marker
        if has_mobile:
            center = marker_data_ID[mid]["center"]
            draw_mobile_center(img_cv_out, center)

        # --- image-based orientation
        u_img = None
        if has_mobile and has_corners:
            u_img = draw_image_orientation(
                img_cv_out,
                center,
                marker_data_ID[mid]["corners"],
            )

        # --- absolute orientation
        if has_absolute_ref and u_img is not None:
            draw_absolute_orientation(
                img_cv_out,
                center,
                u_img,
                result["x_ref"],
                result["y_ref"],
                marker_data_ID[mid]["corners"],
            )

        # --- draw absolute reference frame (if available)
        if (
            fixed_ids is not None
            and result.get("x_ref") is not None
            and result.get("y_ref") is not None
            and has_md
        ):
            c_tl = marker_data_ID[fixed_ids[0]]["center"]
            x_ref = result["x_ref"]
            y_ref = result["y_ref"]
            normX = result.get("width_px", 1.0)
            normY = result.get("height_px", 1.0)

            origin = tuple(c_tl.astype(int))
            end_x = (c_tl + x_ref * normX * 1.2).astype(int)
            end_y = (c_tl + y_ref * normY * 1.2).astype(int)

            cv2.arrowedLine(img_cv_out, origin, tuple(end_x), (0, 0, 0), 3, tipLength=0.05)
            cv2.arrowedLine(img_cv_out, origin, tuple(end_y), (0, 0, 0), 3, tipLength=0.05)

        # --- legend (always)
        lines = []

        if has_mobile and result.get("angle_img") is not None:
            lines.append(f"ID {mid}")
            lines.append(f"angle img = {result['angle_img']:.1f} deg")

        if has_absolute_ref and result.get("angle_abs") is not None:
            delta = (result["angle_abs"] - result["angle_img"] + 180) % 360 - 180
            lines.append(f"angle abs = {result['angle_abs']:.1f} deg")
            lines.append(f"delta img/abs = {delta:.1f} deg")
        else:
            lines.append("absolute reference: unavailable")

        scale = 2
        draw_legend(
            img_cv_out,
            lines,
            origin=(scale * 20, scale * 40),
            font_scale=scale,
            line_spacing=scale * 30,
        )
    except Exception as e:
        print(f'error in draw_aruco_overlay   {e}')

    return img_cv_out

def draw_legend(
    img_cv,
    lines,
    origin=(20, 40),
    font_scale=1.,
    line_spacing=28,
    color=(255, 255, 255),
    thickness=2,
):
    """
    Draw a multi-line legend on an OpenCV image.

    Parameters
    ----------
    lines : list of str
        Lines to display.
    origin : (int, int)
        Top-left corner of the legend.
    font_scale : float
        Text scale (increase for better visibility).
    line_spacing : int
        Vertical spacing between lines (pixels).
    """
    x0, y0 = origin
    for i, txt in enumerate(lines):
        cv2.putText(
            img_cv,
            txt,
            (x0, y0 + i * line_spacing),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

def draw_fixed_markers(img_cv,
                       marker_data_ID,
                       fixed_ids,
                       markerSize=15,
                       marker_color=(0, 0, 255),
                       marker_patern=-1):
    for fid in fixed_ids:
        if fid in marker_data_ID:
            ct = tuple(marker_data_ID[fid]["center"].astype(int))
            cv2.circle(img_cv, ct, markerSize, marker_color, marker_patern)

def draw_mobile_center(img_cv, center):
    cX, cY = tuple(center.astype(int))
    cv2.drawMarker(
        img_cv, (cX, cY),
        (0, 0, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=20,
        thickness=2,
    )

def draw_image_orientation(img_cv,
                           center,
                           corners,
                           scale=3,
                           color=(0, 255, 0),
                           thickness=4):

    u = ((corners[0] - corners[3]) + (corners[1] - corners[2]))
    n = np.linalg.norm(u)
    if n == 0:
        return

    u /= n
    marker_width = int(np.linalg.norm(corners[0] - corners[1]))
    line_length = scale * marker_width

    cX, cY = tuple(center.astype(int))
    endX = int(cX + u[0] * line_length)
    endY = int(cY + u[1] * line_length)

    cv2.line(img_cv, (cX, cY), (endX, endY), color, thickness)
    return u

def draw_absolute_orientation(img_cv,
                              center,
                              u_img,
                              x_ref,
                              y_ref,
                              corners,
                              scale=4,
                              color=(0, 165, 255),
                              ):
    ux = np.dot(u_img, x_ref)
    uy = np.dot(u_img, y_ref)
    u_abs = ux * x_ref + uy * y_ref

    marker_width = int(np.linalg.norm(corners[0] - corners[1]))
    line_length = scale * marker_width

    cX, cY = tuple(center.astype(int))
    endX = int(cX + u_abs[0] * line_length)
    endY = int(cY + u_abs[1] * line_length)

    draw_dashed_line(
        img_cv,
        (cX, cY),
        (endX, endY),
        color,
        thickness=4,
        dash_length=15,
    )


def draw_dashed_line(
    img_cv: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
    color: Tuple[int, int, int],
    thickness: int = 1,
    dash_length: int = 10
) -> None:
    """
    Draw a dashed line between two points on an OpenCV image.

    Parameters
    ----------
    img_cv : np.ndarray
        OpenCV image (BGR) on which the dashed line is drawn.
        The image is modified in place.
    pt1 : tuple[int, int]
        Starting point (x, y) in pixel coordinates.
    pt2 : tuple[int, int]
        Ending point (x, y) in pixel coordinates.
    color : tuple[int, int, int]
        Line color in BGR format.
    thickness : int, optional
        Line thickness in pixels (default is 1).
    dash_length : int, optional
        Length of each dash segment in pixels (default is 10).

    Notes
    -----
    - The dashed line is drawn in image (pixel) coordinates.
    - The pattern consists of alternating dash and gap segments
      of equal length (`dash_length`).
    - If `pt1` and `pt2` coincide, nothing is drawn.

    Examples
    --------
        >>> img_cv = np.zeros((400, 400, 3), dtype=np.uint8)
        >>> draw_dashed_line(
        ...     img_cv,
        ...     (100, 100),
        ...     (300, 250),
        ...     color=(0, 255, 0),
        ...     thickness=2,
        ...     dash_length=15
        ... )
        >>> cv2.imshow("Dashed line", img_cv)
        >>> cv2.waitKey(0)
        >>> cv2.destroyAllWindows()
    """
    p1 = np.asarray(pt1, dtype=float)
    p2 = np.asarray(pt2, dtype=float)

    line_vec = p2 - p1
    line_len = np.linalg.norm(line_vec)

    # Degenerate case: identical points
    if line_len == 0:
        return

    line_dir = line_vec / line_len
    num_dashes = int(line_len // (2 * dash_length))

    for i in range(num_dashes):
        start = p1 + line_dir * (2 * i * dash_length)
        end = p1 + line_dir * ((2 * i + 1) * dash_length)

        cv2.line(
            img_cv,
            tuple(start.astype(int)),
            tuple(end.astype(int)),
            color,
            thickness
        )


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

# --------------------------------------------------------------
# Utilisation
# --------------------------------------------------------------


if __name__ == "__main__":

    folderMissionPath = Path(r"C:\Air-Mission\FLY-20220125-1159-Blassac\AerialPhotography")
    name_folder = "VIS"

    verbose = False
    t0 = time.perf_counter()
    spectral_band = "VIS"  # "NIR"
    suffix_image = "dng"  # "jpg"
    VIS_results, VIS_x_vals, Vis_y_vals = process_aruco_images(
        folderMissionPath=folderMissionPath,
        name_folder=name_folder,
        spectral_band=spectral_band,
        suffix_image=suffix_image,
        save_check_detection_img=True,  # save each detection in  jpg image
        verbose=verbose,  # print detailed info
        use_aruco_cache=False,  # overwrite .exif cache if False
    )
    t1 = time.perf_counter()
    print(Style.CYAN + f"[TIMING] process_aruco_images : {t1 - t0:.3f} s" + Style.RESET)
    # angles_deg = [r['angle_img'] for r in VIS_results if r['angle_img'] is not None]
    angles_deg = [r['angle_abs'] for r in VIS_results if r['angle_abs'] is not None]
    if len(angles_deg) >= 1:
        angles_unwrapped_VIS = unwrap_angles(angles_deg)
    time_line_VIS = [r['relative_timeline'] for r in VIS_results if r['relative_timeline'] is not None]


    t0 = time.perf_counter()
    spectral_band = "NIR"  # "NIR"
    suffix_image = "dng"  # "jpg"
    name_folder = "NIR"
    NIR_results, NIR_x_vals, NIR_y_vals = process_aruco_images(
        folderMissionPath=folderMissionPath,
        name_folder=name_folder,
        spectral_band=spectral_band,
        suffix_image=suffix_image,
        save_check_detection_img=True,  # save each detection in  jpg image
        verbose=verbose,  # print detailed info
        use_aruco_cache=False,  # overwrite .exif cache if False
    )
    t1 = time.perf_counter()
    print(Style.CYAN + f"[TIMING] process_aruco_images : {t1 - t0:.3f} s" + Style.RESET)

    angles_deg = [r['angle_abs'] for r in NIR_results if r['angle_abs'] is not None]
    if len(angles_deg) >= 1:
        angles_unwrapped_NIR = unwrap_angles(angles_deg)
    else:
        angles_unwrapped_NIR = angles_deg
    time_line_NIR = [r['relative_timeline'] for r in NIR_results if r['relative_timeline'] is not None]


    print(f'[INFO]   la détection des mires aruco pour les images VIS et NIR est terminée. \n'
          f'.............................................................................\n')

    # ------------------------------------------------------------
    # Synchronisation des time line VIS et NIR
    # ------------------------------------------------------------
    time_shift, omega, metrics = compute_time_shift_L2(
        time_line_VIS,
        angles_unwrapped_VIS,
        time_line_NIR,
        angles_unwrapped_NIR,
        use_median=False,
    )
    abstract_time_line_alignement(time_shift, omega, metrics)

    # ------------------------------------------------------------
    # Optional graph
    # ------------------------------------------------------------
    graph_angle = True
    if graph_angle:
        if len(angles_unwrapped_VIS) >= 1 and len(angles_unwrapped_NIR) >= 1:
            time_NIR_shifted = [t + time_shift for t in time_line_NIR]
            folderMission = Path(r"C:\Air-Mission\FLY-20220125-1159-Blassac")
            folderSynchroPath = safe_path(Path(folderMission) / "Synchro")
            plot_angles_alignement_time_line([time_line_VIS, time_NIR_shifted],
                        [angles_unwrapped_VIS, angles_unwrapped_NIR],
                        ["VIS", "NIR"],
                        mode='ground',  # 'img',
                        color=['g', 'r'],
                        folder_save=folderSynchroPath,
                        filename="check_time_alignment.png")
    exit(2025)




'''

        
def show_Aruco_marker_old(result, img_out, marker_data_ID, fixed_ids, option_show=2, title=""):
    """
    module appelé par def detect_mobile_marker_absolute

    Affiche le marqueur Aruco avec son orientation.
    - result : dictionnaire retourné par detect_mobile_marker_absolute
    - img_out : image sur laquelle dessiner
    - marker_data_ID : dictionnaire des marqueurs (par ID)
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
            if fid in marker_data_ID:
                ct = tuple(marker_data_ID[fid]["center"].astype(int))
                cv2.circle(img_out, ct, 2, (0, 0, 255), -1)

    # --- dessiner repère absolu si disponible
    if result.get("x_ref") is not None and result.get("y_ref") is not None:
        title = "Repere absolu / sol"
        c_tl = marker_data_ID[fixed_ids[0]]["center"]
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
    cX, cY = tuple(marker_data_ID[result["mobile_id"]]["center"].astype(int))
    cv2.drawMarker(img_out, (cX, cY), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

    corners_m = marker_data_ID[result["mobile_id"]]["corners"]
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


'''


'''
12 images NIR.  use_median=True

1 image VIS :
N° 22  DT = -30.954
N° 28  DT = -31.052
N° 34  DT = -31.016
N° 38  DT = -30.958
2 images VIS :
N° 28-29 DT = -31.030
N° 36-37 DT = -30.968
3 images VIS :
N°35 à 37  DT = -30.986
5 images VIS :
N°33 à 37  DT = -30.985
9 images VIS :
N° 29 à 37  DT = -30.990
16 images VIS ;(totalité de la zone NIR) :
N° 22 à 37  DT =-31.008
'''
