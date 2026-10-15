# -*- coding: utf-8 -*-

import sys
# print(f"✔ Python used : {sys.executable}")
# print(f"✔", "\n✔ ".join(sys.path))
import numpy as np
# print(f"✔ Version NumPy : {np.__version__}")
import math
try:
    from osgeo import gdal
    gdal.UseExceptions()
    # print(f"✔ Version GDAL : {gdal.__version__}")
    # print(f"✔ File GDAL : {gdal.__file__}")
except Exception as e:
    print(f"✖ Error GDAL : {e}")

import os
import os.path as osp
import shlex
from pathlib import Path
import argparse
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import cv2
# print(f"✔ Version cv2 : {cv2.__version__}")
import re
from collections import defaultdict
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter
from scipy.interpolate import RectBivariateSpline
from scipy.interpolate import LinearNDInterpolator
from scipy.interpolate import RBFInterpolator
from scipy.interpolate import griddata
from scipy.ndimage import map_coordinates
from affine import Affine

from typing import Any, Dict, Optional, Tuple, List, Union, Sequence, Iterable
import json
import subprocess
import rasterio
# print(f"✔ Version rasterio : {rasterio.__version__}")
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.enums import ColorInterp
from rasterio.crs import CRS
from osgeo import gdal, ogr, osr

from datetime import datetime
import time

# ----------------------------------------------------
#     bib PyQt 6
# ----------------------------------------------------
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import (
    Qt,
    QThreadPool,
    QObject,
    pyqtSignal,
    QThreadPool,
    QTimer,
)
from PyQt6.QtWidgets import (
    QMessageBox,
    QApplication,
    QWidget,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
)


from IRD_interactive_geo import data_sig
import IRD_Interactive_utils as Uti


if os.name == 'nt':
    RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
    assert osp.exists(RAWTHERAPEEPATH), "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
    EXIFTOOLPATH = osp.join(osp.dirname(__file__), "..", "thirdparty", "exiftool", "exiftool.exe")
    assert osp.exists(EXIFTOOLPATH), "Requires exif tool at {} from https://exiftool.org/".format(EXIFTOOLPATH)

else:
    RAWTHERAPEEPATH = "rawtherapee-cli"
    EXIFTOOLPATH = "exiftool"

# ============================================================
#  CLASS
# ============================================================

class CliLogger:
    """
        Console logger with optional ANSI colors and GUI message forwarding.

        Messages are printed to the console and can also be forwarded
        to a GUI through the optional log_callback.
    """
    def __init__(self, use_color=None):
        # Automatically detect whether color output is supported if not specified.
        if use_color is None:
            self.use_color = sys.stdout.isatty() and os.getenv("TERM") != "dumb"
        else:
            self.use_color = use_color

        # Unicode symbols used in log messages.
        self.symbols = {
            "ok": "\u2714",           # ✔
            "error": "\u2716",        # ✖
            "warn": "\u26A0\uFE0F",   # ⚠️  (⚠ + variation selector)
            "info": "\u2139\uFE0F",   # ℹ️  (ℹ + variation selector)
            "timer": "\u23F1",        # ⏱
            "hourglass": "\u23F3",    # ⏳
            "tech": "\U0001F527",     # 🔧
            "search": "\U0001F50D",   # 🔍
            "compute": "\U0001F5A5\uFE0F",  # 🖥️  (desktop computer + VS16)
            "rocket": "\U0001F680",      # 🚀
            "checklist": "\U0001F4CB",   # 📋
            "fire": "\U0001F525",        # 🔥
            "bug": "\U0001F41B",         # 🐛  python
            "debug": "\U00002699\uFE0F",  # ⚙
            "botanique": "🌿",            # 🌿️
        }

        # ANSI color escape sequences.
        self.colors = {
            "reset": "\033[0m",
            "bold": "\033[1m",
            "underline": "\033[4m",

            # Standard colors (widely supported).
            "black": "\033[30m",
            "red": "\033[31m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "cyan": "\033[36m",
            "white": "\033[37m",
            "bright_white": "\033[97m",

            # Additional colors (not supported by all terminals).
            "orange": "\033[38;5;208m",
            "bright_red": "\033[91m",
            "bright_green": "\033[92m",
            "bright_yellow": "\033[93m",
            "bright_blue": "\033[94m",
            "bright_magenta": "\033[95m",
            "bright_cyan": "\033[96m",
        }

        self.log_callback = None

    def _format(self, level, message, _bold=False, _underline=False):
        """Format a log message with its symbol and optional ANSI styling."""
        symbol = self.symbols[level]

        if not self.use_color:
            return f"{symbol} {message}"

        color_map = {
            "ok": "green",
            "info": "bright_white",
            "error": "red",
            "warn": "yellow",
            "timer": "blue",
            "debug": "orange",
            "tech": "reset"
        }

        color = self.colors[color_map[level]]
        reset = self.colors["reset"]
        if _bold:
            return f"{color}{symbol} {self.colors['bold']}{message}{reset}"
        elif _underline:
            return f"{color}{symbol} {self.colors['underline']}{message}{reset}"
        else:
            return f"{color}{symbol} {message}{reset}"

    def _write(self, level, message, _bold=False, _underline=False):
        """Write a formatted message to the console and optional GUI."""
        formatted_message = self._format(
            level, message, _bold=_bold, _underline=_underline
        )

        # Keep the existing console output.
        if level == "error":
            print(formatted_message, file=sys.stderr)
        else:
            print(formatted_message)

        # Forward a plain-text message to the GUI, if connected.
        if self.log_callback is not None:
            symbol = self.symbols[level]
            self.log_callback(f"{symbol} {message}")

    def ok(self, message):
        """Log a successful operation."""
        self._write("ok", message)

    def error(self, message):
        """Log an error message to the standard error stream."""
        self._write("error", message)

    def warning(self, message):
        """Log a warning message."""
        self._write("warn", message)

    def warn(self, message):
        """Alias for warning()."""
        self.warning(message)

    def info(self, message, _bold=False, _underline=False):
        """Log an informational message with optional styling."""
        self._write(
            "info", message, _bold=_bold, _underline=_underline
        )

    def timer(self, message):
        """Log a timing-related message."""
        self._write("timer", message)

    def tech(self, message):
        """Log a technical message."""
        self._write("tech", message)

    def debug(self, message):
        """Log a debugging message."""
        self._write("debug", message)


# Logger partagé par les fonctions du module
logger = CliLogger(use_color=True)

# ============================================================
#  FONCTION PRINCIPALE
# ============================================================

def georeference_tiff_MNT(tif_path,
                          raw_exif,
                          output_path,
                          folder_input,
                          img_name,
                          offset_xi_Y=0,
                          offsetUTMx=0,
                          offsetUTMy=0,
                          ampli=1.2,
                          zhang_dic=None,
                          cache=False,
                          verbose=False,
                          info=True,
                          tag_img=False,
                          graphic_2D=True,
                          graphic_3D=True,
                          graphic_ortho=False,
                          view_graphic=False,
                          save_graphic=True,
                          comp_error_rms=False,
                          tol_MC=0.01,
                          bitdepth="float32",
                          topo_style="IGN",
                          carte_topo=True,
                          raster_topo=False,
                          img_override=None,
                          ):
    """
    Georeference and orthorectify an image using a digital terrain model (DTM).

    Processing pipeline:
        Image coordinates -> VIS camera coordinates -> Drone coordinates
        -> Geographic coordinates (UTM).

    The function interprets DJI EXIF metadata, establishes the camera geometry,
    builds a terrain model from IGN elevation reference points, projects the
    terrain grid into the source image, resamples the image, and saves the
    orthorectified result as a georeferenced raster.

    Optional outputs include diagnostic graphics, a Monte Carlo positional
    error map, a topographic raster, and contour lines for QGIS.

    Args:
        tif_path: Path to the input TIFF image.
        raw_exif: EXIF metadata used to determine the camera and drone geometry.
        output_path: Output path parameter supplied by the caller.
        folder_input: Input folder containing the image and output subfolders.
        img_name: Base name used to identify generated files.
        offset_xi_Y: Additional yaw correction, in radians.
        offsetUTMx: Eastward correction to the nadir position, in meters.
        offsetUTMy: Northward correction to the nadir position, in meters.
        ampli: Scale factor applied to the estimated image footprint.
        zhang_dic: Optional Zhang camera-calibration parameters.
        cache: Cache-related option.
        verbose: Enable additional diagnostic messages.
        info: Information-display option.
        tag_img: Save and use a diagnostic image with reference markings.
        graphic_2D: Enable 2D diagnostic graphics.
        graphic_3D: Enable 3D terrain graphics.
        graphic_ortho: Enable display of the orthorectified image.
        view_graphic: Display generated graphics.
        save_graphic: Save generated graphics.
        comp_error_rms: Compute a positional error map using Monte Carlo simulation.
        tol_MC: Tolerance used by the Monte Carlo error calculation.
        bitdepth: Output GeoTIFF data type.
        topo_style: Topographic contour style.
        carte_topo: Generate topographic contour data.
        raster_topo: Save the topographic elevation raster.
        img_override: Optional image array supplied instead of loading the TIFF.

    Returns:
        Path to the generated georeferenced GeoTIFF.

    Raises:
        FileNotFoundError: If the input image cannot be loaded.
    """

    t_global0 = time.perf_counter()
    # ------------------------------------------------------------------------------
    # 0) Interpret DJI drone metadata
    # ------------------------------------------------------------------------------
    t0 = time.perf_counter()

    # Returns: distances in meters (m) and angles in radians (rad)
    latitude, longitude, z_ground, Z_cam_nadir, Z_cam_sealevel, UTM_x, UTM_y, zoneUTM, xi_Y, xi_P, xi_R = DJI2IRDrone(raw_exif, verbose=False)

    # Correct the GPS position of the nadir
    if offsetUTMx != 0 or offsetUTMy != 0:
        logger.info(
            f"Nadir position correction East | North: "
            f"{offsetUTMx} m, {offsetUTMy} m"
        )

    UTM_x, UTM_y = UTM_x + offsetUTMx, UTM_y + offsetUTMy


    Cam_Center = (UTM_x, UTM_y, Z_cam_nadir)


    # ------------------------------------------------------------------------------
    #  1) Raw image
    # ------------------------------------------------------------------------------

    # --- 1.01 Load the raw image

    if img_override is not None:
        img_raw = img_override
    else:
        logger.debug(f"Loading image {tif_path} in raw_DJI mode")
        img_raw = cv2.imread(str(tif_path), cv2.IMREAD_UNCHANGED)
        if img_raw is None:
            raise FileNotFoundError(tif_path)

    Ny_raw, Nx_raw = img_raw.shape[:2]
    bands = 1 if img_raw.ndim == 2 else img_raw.shape[2]
    if verbose:
        logger.info(f' raw image : Ny_raw = {Ny_raw} Nx_raw= {Nx_raw}  bands = {bands}')

    t1 = time.perf_counter()
    logger.timer(f" EXIF : {t1 - t0:.3f} s")

    # --- 1.02 Image geometry (GSD)

    if zhang_dic is not None and bands == 3:

        # --- 1.02-1 Zhang undistortion parameters, if available for an RGB image

        Nx, Ny = Nx_raw, Ny_raw
        fx, fy = zhang_dic["mtx"][0][0], zhang_dic["mtx"][1][1]
        cx, cy = zhang_dic["mtx"][0][2], zhang_dic["mtx"][1][2]
        txt = "Zhang calibration available."
        dist = np.array(zhang_dic["dist"][0] if isinstance(zhang_dic["dist"][0], list)
                        else zhang_dic["dist"],
                        dtype=np.float64)
        K = np.array(zhang_dic["mtx"], dtype=np.float64)

    else:
        # --- 1.02-2 Default parameters for single-band or four-band multispectral images
        # NOTE: Zhang undistortion has already been applied to these images by IRDrone.
        # Use the IRDrone virtual camera parameters, which account for
        # lens-distortion correction and image cropping.
        # For IRDrone images, the virtual camera FOV is stored in the layer EXIF metadata.

        Ny, Nx = img_raw.shape[:2]
        fov_x = raw_exif.get("FOV")

        try:
            fov_x = raw_exif.get("FOV")

            if fov_x is not None:
                if isinstance(fov_x, str):
                    fov_x = fov_x.lower().replace("deg", "").strip()
                fov_x = float(fov_x)


        except (ValueError, TypeError):
            logger.warning("Invalide FOV  → fallback focal_pix=2918")
            fov_x = None

        if fov_x:
            focal_pix = Nx / (2 * np.tan(np.deg2rad(fov_x/2)))
            logger.info(f' IRDrone multispectal camera FOV  {fov_x}°')
        else:

            focal_pix = 2918
            logger.warn(f' IRDrone default   FOV.')
        fx, fy, cx, cy = focal_pix, focal_pix, Nx / 2, Ny / 2
        txt = "Image with corrected optical distortion."
        dist = None

    # --- 1.03 Mark the raw image and save the result
    # This option is useful for development and for creating educational images.

    t0 = time.perf_counter()
    if tag_img:
        tif_path_taged = folder_input / "geo_ref" / f"{img_name}_taged.tif"
        img = tag_image(img_raw, tif_path_taged, cx, cy, verbose=True)
    else:
        img = img_raw

    t1 = time.perf_counter()
    logger.timer(f" Tag image : {t1 - t0:.3f} s")

    fov_x, fov_y = 2 * np.arctan(Nx / (2 * fx)), 2 * np.arctan(Ny / (2 * fy))
    gsd_x, gsd_y = 2 * Z_cam_nadir * np.tan(fov_x / 2) / Nx, 2 * Z_cam_nadir * np.tan(fov_y / 2) / Ny


    logger.info(f"-----------------------------------------\n"
          f"{txt}\n"
          f"bands : {bands}\n"      
          f"taille : {Nx} x {Ny}\n"
          f"focales: fx = {fx:.3f} fy = {fy:.3f}  \n"
          f"centre : cx = {cx:.3f} cy = {cy:.3f}   \n"
          f"écart sur x = {int(Nx / 2 - cx)} pix ({100 * (Nx / 2 - int(cx)) / Nx:.2f}%)  | sur y = {int(Ny / 2 - cy)} pix ({100 * (Ny / 2 - int(cy)) / Ny:.2f}%) \n"
          f"fov_x = {np.rad2deg(fov_x):.4f} °  ; fov_y = {np.rad2deg(fov_y):.4f} ° \n"
          f"GSD X = {gsd_x:.4f} m/px  ;  Y={gsd_y:.4f} m/px\n"
          f"Correction manuelles :\n"
          f"offset Yaw = {np.rad2deg(offset_xi_Y) : .2f}°\n"
          f"offset UTM Est= {offsetUTMx: .3f} m  Nord = {offsetUTMy: .3f} m\n"
          f"------------------------------------------------"
          )

    # ------------------------------------------------------------------------------
    #  2) Coordinate transformation matrices: image frame to geographic frame
    # ------------------------------------------------------------------------------

    R_Img2Gnd = R_yaw(xi_Y + offset_xi_Y)


    # ------------------------------------------------------------------------------
    #
    #   3) GEOREFERENCING
    #
    #  Case 02: orthorectification using the IGN digital terrain model (DTM)
    #
    # ------------------------------------------------------------------------------

    # crs_utm = f"EPSG:{32600 + zoneUTM}"
    zone = 32600 + zoneUTM
    crs_utm = CRS.from_epsg(int(zone))  # UTM Nord
    Z0 = 0

    # ------------------------------------------------------------
    # 3.02: Orthorectification using the IGN DTM
    # ------------------------------------------------------------

    t0 = time.perf_counter()

    # The DTM grid must be centered on the nadir
    # that is, the projection of the optical center (pixel (cx, cy))

    X0, Y0, Z0 = UTM_x, UTM_y, 0.0

    # --------------------------------------------------------------------------------------------------
    #  3.02-1) Define DTM reference points and boundaries
    # --------------------------------------------------------------------------------------------------
    # The DTM is based on a limited number of surveyed IGN reference points.
    # These points are used to build a continuous terrain model using spline
    # interpolation. A terrain grid is then generated, terrain elevations are
    # evaluated, the image is projected onto the terrain, and the resulting
    # terrain points are mapped back to sensor pixels.
    # Xg_IGN, Yg_IGN, Zg_IGN are the reference point coordinates in UTM.
    # Zg_IGN contains elevations relative to sea level.
    # A 15 x 15 grid provides square cells.
    # A 9 x 9 grid may be sufficient for relatively flat terrain.

    N_mesh_x, N_mesh_y = next_odd(15), next_odd(15)  # next_odd returns the next odd integer.
    if verbose:
        logger.info(f' Mesh =  {N_mesh_x} x {N_mesh_y}')

    # ampli is the scale factor applied to the image footprint on a flat ground plane.

    Xg_IGN, Yg_IGN, Zg_IGN, bound_IGN_pix = \
        compute_MNT_mesh(N_mesh_x, N_mesh_y,
                         xi_Y + offset_xi_Y,
                         R_Img2Gnd,
                         Nx, Ny,
                         fx, fy,
                         cx, cy,
                         UTM_x, UTM_y, Z0,
                         z_ground, Cam_Center,
                         folder_input, img_name,
                         save_graphic=save_graphic,
                         ampli=ampli,
                         zoneUTM=zoneUTM,
                         txt="Points Ref alti IGN",
                         verbose=verbose,
                         graphic_2D=graphic_2D,
                         view_graphic=view_graphic
                         )

    t1 = time.perf_counter()
    logger.timer(f" Total  mesh IGN : {t1 - t0:.3f} s")

    # --- Build the continuous DTM using spline interpolation

    t0 = time.perf_counter()
    # Select the DTM interpolation method
    # Available options:
    # "RectBivariateSpline_cubic"
    # "RectBivariateSpline_quadratic"
    # "RectBivariateSpline_linear"

    altitude = build_MNT_interpolator(Xg_IGN, Yg_IGN, Zg_IGN - z_ground, method="RectBivariateSpline_quadratic")

    t1 = time.perf_counter()
    logger.timer(f" Build_MNT_interpolator : {t1 - t0:.3f} s")


    if graphic_3D or save_graphic:
        t0 = time.perf_counter()

        plot_terrain_3d(Xg_IGN, Yg_IGN, Zg_IGN, UTM_x, UTM_y, z_ground, xi_Y + offset_xi_Y, N_mesh_x, N_mesh_y,
                        altitude, folder_input, img_name, view_graphic=view_graphic, save_graphic=save_graphic,
                        nx_subdiv=160, ny_subdiv=120, title=r"$MNT (source\,IGN^{\circledR})$")

        t1 = time.perf_counter()
        logger.timer(f" Graphic MNT : {t1 - t0:.3f} s")

    # print(f'[DEBUG]  Xg_IGN  {type(Xg_IGN)}\n'
    #       f' {Xg_IGN}\n'
    #       f'Zg_IGN   {type(Zg_IGN)}\n'
    #       f'{Zg_IGN}\n'
    #       f'bound_IGN_pix    {type(bound_IGN_pix)}\n'
    #       f' {bound_IGN_pix}')

    # --------------------------------------------------------------
    #  3.02-2) Build the north-up GIS orthorectification grid
    #     Estimate the minimum footprint
    # --------------------------------------------------------------
    t0 = time.perf_counter()

    Xmin_est, Xmax_est, Ymin_est, Ymax_est = estimate_ground_bbox_from_camera(
        Nx, Ny, R_Img2Gnd, Cam_Center, fx, fy, cx, cy, Z0, altitude, ampli=1.025)

    # Build the reduced GIS grid
    Xo = np.arange(Xmin_est, Xmax_est, gsd_x)
    Yo = np.arange(Ymax_est, Ymin_est, -gsd_y)
    Xo_grid, Yo_grid = np.meshgrid(Xo, Yo)

    t1 = time.perf_counter()
    logger.timer(f" Construction grille ortho GIS  : {t1 - t0:.3f} s")

    # -----------------------------------------------------------------
    # 3.02-3) Terrain elevation
    # NOTE: This is a simple orthogonal projection
    # (perpendicular to the horizontal plane) of the grid points
    # from the regular GIS grid onto the DTM
    # ------------------------------------------------------------------

    t0 = time.perf_counter()

    Zg_grid = altitude(Xo_grid, Yo_grid)  # Elevation relative to the nadir altitude

    t1 = time.perf_counter()
    logger.timer(f" Compute altitude grid : {t1 - t0:.3f} s")

    # --------------------------------------------------
    # 3.02-4) Project terrain points into the image
    # --------------------------------------------------
    # Lens-distortion correction is performed at the same time as the projection

    t0 = time.perf_counter()

    P_sol = np.stack([Xo_grid, Yo_grid, Zg_grid], axis=-1)

    R_Gnd2Cam = R_Img2Gnd.T  # rotation inverse Gnd -> Cam

    # NOTE: Lens distortion in single-band TIFF images from IRDrone
    # has already been corrected during multispectral processing.

    if img.ndim == 2:
        img = img[:, :, np.newaxis]

    H, W, spectral_band = img.shape

    if spectral_band == 1 or spectral_band == 4:
        dist = None

    u, v, Zc = project_ground_to_camera_batch(
        P_sol,
        R_Gnd2Cam,
        Cam_Center,
        fx, fy,
        cx, cy,
        dist=dist,  # zhang_dic["dist"][0],
        verbose=True
    )

    mask = ((u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1) & (Zc < 0))

    t1 = time.perf_counter()
    logger.timer(f" Projection terrain → image : {t1 - t0:.3f} s")

    # ------------------------------------------------------------
    # 3.02-5) Resample the image
    # ------------------------------------------------------------
    t0 = time.perf_counter()
    img = img.astype(np.float32)  # ⚠️ Convert to float32 for accurate interpolation
    ortho = np.zeros((*u.shape, spectral_band), dtype=img.dtype)

    for c in range(spectral_band):
        v_img = (H - 1) - v  # Convert camera coordinates to NumPy image coordinates; essential for Rasterio and QGIS output
        band = map_coordinates(img[..., c],
                                [v_img.ravel(), u.ravel()],
                                order=1,
                                mode='constant',
                                cval=0
                               ).reshape(u.shape)
        ortho[..., c] = band

    ortho[~mask] = 0  # Mark black peripheral areas as transparent

    t1 = time.perf_counter()
    logger.timer(f" Resampling image : {t1 - t0:.3f} s")


    # ---------------------------------------------------------------
    # # 3.02-6) Simple GIS affine transform.
    #  Note: use -gsd_y for north-up orientation
    # ---------------------------------------------------------------
    t0 = time.perf_counter()

    # Actual origin of the orthorectified image
    X0 = Xo_grid[0, 0]
    Y0 = Yo_grid[0, 0]

    transform = Affine(gsd_x, 0.0, X0, 0.0, -gsd_y, Y0)

    # Dynamic color adjustment and BGR-to-RGB conversion
    # A float32 NumPy image is suitable for scientific use
    # Normalize values to the [0, 1] range.

    if img_raw.dtype == np.uint16:
        img_ortho = ortho.astype(np.float32) / 65535.0
    elif img_raw.dtype == np.uint8:
        img_ortho = ortho.astype(np.float32) / 255.0
    else:
        img_ortho = ortho

    ortho_path = folder_input / "geo_ref" / f"{img_name}_graph_ortho.png"
    graph_ortho(img_ortho[..., ::-1], 0, 0, ortho_path,
                view_graphic=view_graphic, save_graphic=save_graphic, graphic_ortho=graphic_ortho)  # BGR to RGB conversion for QGIS

    t1 = time.perf_counter()
    logger.timer(f" Affine SIMPLE GIS. : {t1 - t0:.3f} s")

    # ---------------------------------------
    #  Error maps (GPS, DTM, yaw, drone altitude, etc.)
    # ---------------------------------------
    if comp_error_rms:
        error_method = "Monte Carlo"

        logger.info(f' Compute RMS error .  Method : {error_method}')

        xi_yaw = xi_Y + offset_xi_Y

        sigma_yaw_deg = 0.3     # °   ~ 0.2° to 1°   DJI drone heading accuracy.
        sigma_xy = 2            # m   ~ 1–3 m        DJI drone GPS XY-UTM position accuracy. ±1.5 m when hovering.
        sigma_z = 1.5           # m   ~ 0.5–2 m      DJI drone GPS Z-position accuracy. ±0.5 m when hovering.
        sigma_z_mnt = 1         # m   ~ 0.5–3 m      DTM elevation accuracy (IGN elevation API).


        t0 = time.perf_counter()

        error_rms = compute_error_rmse_montecarlo(
            P_sol,
            u, v,
            Cam_Center,
            xi_yaw,
            fx, fy,
            cx, cy,
            gsd_x, gsd_y,
            sigma_yaw_deg, sigma_xy, sigma_z, sigma_z_mnt,
            project_ground_to_camera_batch,
            R_yaw,
            N_max=400, N_min=4, tol_MC=tol_MC,
            verbose=True
        )


        error_path = get_unique_path(folder_input / "geo_ref" / f"{img_name}_error_rms.tif")
        error_rms[~mask] = np.nan
        error_rms = np.clip(error_rms, 0, np.percentile(error_rms[mask], 98))  # Visual clipping
        write_geotiff_affine(error_path, error_rms.astype(np.float32), transform, crs_utm, no_data=np.nan)

        t1 = time.perf_counter()
        logger.timer(f" Compute error RMS. Method {error_method}: {t1 - t0:.3f} s")

    # ---------------------------------------
    # Topographic maps
    # ---------------------------------------
    if carte_topo:
        t0 = time.perf_counter()
        # Each pixel stores the terrain elevation above sea level.
        map_topo = P_sol[..., 2] + (Z_cam_sealevel - Z_cam_nadir)
        map_topo[~mask] = np.nan
        if raster_topo:
            # Generate an elevation raster (.tif) for QGIS.
            topo_path = get_unique_path(folder_input / "geo_ref" / f"{img_name}_topo.tif")
            write_geotiff_affine(topo_path, map_topo.astype(np.float32), transform, crs_utm, no_data=np.nan)

        # Generate a contour-line file (.geojson) for QGIS.
        contour_path = get_unique_path(folder_input / "geo_ref" / f"{img_name}_contours.geojson")
        generate_contours_dual(map_topo.astype(np.float32), transform, crs_utm, contour_path)

        # Generate a QGIS style file (.qml).
        # Use the same base name ({img_name}_contours) as the contour-line file.
        # QGIS will automatically apply this style to the contour-line file.
        # Available styles: "IGN", "BW", "SOFT".
        topo_style = "IGN"
        qml_path = contour_path.with_suffix(".qml")
        generate_qml_style_qgis(qml_path, style=topo_style, label_on_line=True)

        t1 = time.perf_counter()
        logger.timer(f" Topographic map: {t1 - t0:.3f} s")

    # ------------------------------------------------------------------------------
    # 4) Save the orthorectified GeoTIFF
    # ------------------------------------------------------------------------------
    t0 = time.perf_counter()

    if tag_img:
        geo_path_0 = folder_input / "geo_ref" / f"{img_name}_georef_TAG.tif"
    else:
        geo_path_0 = folder_input / "geo_ref" / f"{img_name}_georef.tif"
    geo_path = get_unique_path(geo_path_0)

    write_geotiff_affine(geo_path, img_ortho, transform, crs_utm, bitdepth=bitdepth)
    t1 = time.perf_counter()
    logger.timer(f" Save the orthorectified GeoTIFF using Rasterio : {t1 - t0:.3f} s")
    logger.timer(f" --- TOTAL GEOREFERENCING TIME: {t1 - t_global0:.3f} s \n")

    return geo_path


# ============================================================
#  AUXILIARY FUNCTIONS
# ============================================================

def next_odd(N_mesh):
    """
    Return the smallest odd integer greater than or equal to N_mesh
    after rounding N_mesh up to the next integer.

    This ensures that the mesh always contains an odd number of points,
    allowing for a central point in the grid.

    Examples
    --------
    8     -> 9
    9     -> 9
    9.2   -> 11
    10.5  -> 11
    """
    n = np.ceil(N_mesh).astype(int)
    return n + (n % 2 == 0)


def safe_path(path: Union[str, Path]) -> Path:
    try:
        return Path(path).resolve()
    except Exception as e:
        logger.error(f" Invalid path {path} : {e}")
        return Path(path)


def estimate_ground_bbox_from_camera(Nx, Ny, R_Cam2Gnd, Cam_Center,
                                     fx, fy, cx, cy, Z0, altitude,
                                     ampli=1.0):
    """
    Estimate the minimum ground footprint from the sensor corners.

    For now, the ground is assumed to be horizontal (A = B = 0).
    The terrain model (DTM) is not yet taken into account.

    Parameters
    ----------
    Nx, Ny : int
        Sensor dimensions in pixels.
    R_Cam2Gnd : ndarray (3, 3)
        Rotation matrix from the camera frame to the ground frame.
    Cam_Center : ndarray (3,)
        Camera position.
    fx, fy : float
        Focal lengths.
    cx, cy : float
        Optical center coordinates.
    Z0 : float
        Reference altitude.
    ampli : float
        Expansion factor providing a safety margin.

    Returns
    -------
    bbox : tuple
        Estimated ground footprint bounds (Xmin, Xmax, Ymin, Ymax).
    """
    corners_pix = np.array([
        [-cx, -cy],  # Top-left corner
        [Nx - 1 - cx, -cy],  # Top-right corner
        [Nx - 1 - cx, Ny - 1 - cy],  # Bottom-right corner
        [-cx, Ny - 1 - cy]  # Bottom-left corner
    ])

    # Points at the midpoints of the sensor edges
    edge_centers_pix = np.array([
        [0, -cy],  # Top edge midpoint
        [0, Ny - 1 - cy],  # Bottom edge midpoint
        [-cx, 0],  # Left edge midpoint
        [Nx - 1 - cx, 0]  # Right edge midpoint
    ])

    # Points at one-quarter and three-quarters of the sensor edges
    edge_sup_pix = np.array([
        [-cx, -cy + Ny / 4], [-cx, -cy + 3 * Ny / 4],
        [Nx - 1 - cx, -cy + Ny / 4],
        [Nx - 1 - cx, -cy + 3 * Ny / 4],
        [-cx + Nx / 4, -cy], [-cx + 3 * Nx / 4, -cy],
        [-cx + Nx / 4, Ny - 1 - cy],
        [-cx + + 3 * Nx / 4, Ny - 1 - cy]
    ])

    all_pix = np.vstack([corners_pix, edge_centers_pix, edge_sup_pix])

    Xc, Yc, Zc = project_camera_to_MNT(
        all_pix,  # Sensor pixels to project, shape (N, 2)
        Nx, Ny,  # Sensor dimensions
        R_Cam2Gnd,  # Camera-to-ground rotation matrix
        Cam_Center,  # Camera position in the ground coordinate frame
        fx, fy,  # Focal lengths
        cx, cy,  # Optical center coordinates
        altitude,  # Altitude function: altitude(X, Y)
        verbose=False
    )

    Xmin, Xmax = np.min(Xc), np.max(Xc)
    Ymin, Ymax = np.min(Yc), np.max(Yc)

    # Apply the optional expansion factor
    Xc_center = 0.5 * (Xmin + Xmax)
    Yc_center = 0.5 * (Ymin + Ymax)
    Xmin = Xc_center + ampli * (Xmin - Xc_center)
    Xmax = Xc_center + ampli * (Xmax - Xc_center)
    Ymin = Yc_center + ampli * (Ymin - Yc_center)
    Ymax = Yc_center + ampli * (Ymax - Yc_center)

    return Xmin, Xmax, Ymin, Ymax


# -----------------------------------------------
#  Raw image conversion: DNG to TIFF, with EXIF
# -----------------------------------------------

def dng2tiff(folder, img_name, suffix="dng", bit=16):
    img_tiff_folder = folder / "geo_ref"
    img_tiff_folder.mkdir(parents=True, exist_ok=True)

    dng_file = folder / f"{img_name}.{suffix}"
    tiff_file = img_tiff_folder / f"{img_name}.tif"

    if not dng_file.exists():
        raise FileNotFoundError(dng_file)

    pp3 = osp.join(
        osp.dirname(__file__),
        "..", "thirdparty", "rawtherapee", "DJI_color.pp3"
    )

    cmd = [
        RAWTHERAPEEPATH,
        "-o", str(tiff_file),
        "-Y",
        "-t",
        f"-b{bit}",
        "-p", pp3,
        "-c", str(dng_file)
    ]

    logger.tech(f"Running: {shlex.join(cmd)}")
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in result.stdout.splitlines():
        logger.tech(f"{line}")

    return tiff_file


def load_companion_exif(folder, img_name, suffix="dng", alti_takeoff=None):
    exif_file = folder / f"{img_name}.exif"
    img_file = folder / f"{img_name}.{suffix}"
    if not exif_file.exists():
        logger.warn(
            f"Companion EXIF file {img_name}.exif is missing from folder {folder}"
        )
        try:
            read_exif_and_write_json(img_file, exif_file, alti_takeoff=alti_takeoff)
        except Exception as e:
            logger.error(f" Read_exif_and_write_json failed for {img_file}: {e}")
            return {}


    with open(exif_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def save_exif_companion(raw_exif, folder_input, img_name, verbose=False):
    """
    Save the enriched raw_exif data to the companion file img_name.exif.
    """

    folder_input = Path(folder_input)
    exif_path = folder_input / f"{img_name}.exif"

    with open(exif_path, "w", encoding="utf-8") as f:
        json.dump(raw_exif, f, indent=4, ensure_ascii=False)

    if verbose:
        logger.ok(f"\n--- Companion EXIF file updated: {exif_path}")

    return exif_path


def read_exif_and_write_json(dng_path: Path, exiftool_path: str,
                             interactive: bool = True,  alti_takeoff=None) -> dict:
    """
    Extract selected EXIF/XMP metadata from a DNG file using ExifTool
    and save a clean .exif JSON file next to the image.
    """
    try:
        # 1) Run ExifTool
        cmd = [EXIFTOOLPATH, "-json", str(dng_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        metadata_list = json.loads(result.stdout)
        if not metadata_list:
            raise RuntimeError("ExifTool returned empty output")

        full_metadata = metadata_list[0]

        # 2) Keep only essential keys
        essential_keys = [
            "FileName", "Directory", "DateTimeOriginal",
            "Make", "Model", "CameraSerialNumber",
            "Orientation",
            "ExposureTime", "FNumber", "ISO", "ExposureCompensation",
            "FocalLength", "FOV", "FocalLengthIn35mmFormat",
            "HyperfocalDistance",
            "GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSPosition",
            "FlightYawDegree", "FlightPitchDegree", "FlightRollDegree",
            "GimbalYawDegree", "GimbalPitchDegree", "GimbalRollDegree",
            "DroneLatitude", "DroneLongitude", "DroneAltitudeTakeOff",
            "DroneAltitudeSeaLevel", "DroneAltitudeGround", "GroundAltitude",
            "UTM_x", "UTM_y", "UTM_zone", "TakeOffAltitudeSeaLevel",
            "AltitudeTakeoffSource",
        ]

        # Special handling of GPSAltitude for DJI drones
        gps_alt = full_metadata.get("GPSAltitude")
        if gps_alt:
            alt_info = parse_and_normalize_gps_altitude(gps_alt)
            meters = np.round(alt_info["meters"], 3)
            full_metadata["DroneAltitudeTakeOff"] = f'{np.round(meters, 3): .3f}'
            full_metadata["GPSAltitude"] = f"{meters} m Above Take Off"

        gps_lat = full_metadata.get("GPSLatitude")
        gps_lon = full_metadata.get("GPSLongitude")
        if gps_lat and gps_lon:
            full_metadata["DroneLatitude"] = f'{np.round(gps_coordinate_to_float(gps_lat), 6): .6f}'
            full_metadata["DroneLongitude"] = f'{np.round(gps_coordinate_to_float(gps_lon), 6): .6f}'
            UTM_x, UTM_y, UTM_zone = geo2UTM(gps_coordinate_to_float(gps_lat), gps_coordinate_to_float(gps_lon))
            full_metadata["UTM_x"], full_metadata["UTM_y"], full_metadata["UTM_zone"] = UTM_x, UTM_y, UTM_zone
            coordinates = [(gps_coordinate_to_float(gps_lat), gps_coordinate_to_float(gps_lon))]

        # 3) Retrieve the ground elevation

        ground_Altitude = full_metadata.get("GroundAltitude")
        if not ground_Altitude:
            #  Retrieve the ground elevation at the image nadir above sea level using the IGN API.
            if gps_lat and gps_lon:
                dic_geo_list = data_sig(coordinates, geotag=False, verbose=True)
            else:
                dic_geo_list = None
            if dic_geo_list is None or len(dic_geo_list) != 1:
                raise ValueError("Error retrieving DTM elevations (API)")
            logger.ok(f"ground_Altitude =  {dic_geo_list[0]['z']} m")
            ground_Altitude = dic_geo_list[0]['z']
            full_metadata["GroundAltitude"] = f'{np.round(ground_Altitude, 3): .3f}'

        # 4) Calculate the drone altitude above sea level

        drone_Altitude_SeaLevel = full_metadata.get("DroneAltitudeSeaLevel")

        if not drone_Altitude_SeaLevel:

            if "DroneAltitudeTakeOff" not in full_metadata:
                raise ValueError(
                    "Cannot calculate drone altitude without DroneAltitudeTakeOff"
                )

            meters = float(full_metadata["DroneAltitudeTakeOff"])

            # 🔍 0. Check the command-line option
            if alti_takeoff:
                takeoff_altitude = float(alti_takeoff)
                logger.info(
                    f"Takeoff altitude provided via command line: "
                    f"{takeoff_altitude: .3f} m"
                )
                logger.ok(
                    f"Takeoff altitude / sea level: {takeoff_altitude: .3f} m"
                )

            # 🔍 1. Search existing EXIF files
            else:
                folder = dng_path.parent
                takeoff_altitude = find_takeoff_altitude_from_exif_folder(folder, logger)

            # 🖥️ 2. Fall back to the GUI
            if takeoff_altitude is None:
                if interactive:
                    logger.warn("The takeoff point altitude is missing.")
                    logger.warn(
                        "Warning: all processed images will share the same takeoff point.")
                    prompt = "Enter the takeoff point altitude above sea level:"
                    takeoff_altitude = ask_takeoff_altitude_gui(prompt, default=ground_Altitude)
                    logger.info(
                        f"Takeoff altitude provided by the user: "
                        f"{takeoff_altitude: .3f} m"
                    )
                    logger.ok(
                        f"Takeoff altitude / sea level: {takeoff_altitude: .3f} m"
                    )
                else:
                    raise ValueError("Takeoff altitude required in non-interactive mode")

            # 🧮 Calculate the altitude
            drone_Altitude_SeaLevel = takeoff_altitude + meters

            full_metadata["DroneAltitudeSeaLevel"] = f'{np.round(drone_Altitude_SeaLevel, 3): .3f}'
            full_metadata["DroneAltitudeGround"] = f'{np.round(drone_Altitude_SeaLevel - ground_Altitude , 3): .3f}'
            full_metadata["TakeOffAltitudeSeaLevel"] = f'{np.round(takeoff_altitude): .3f}'
            full_metadata["AltitudeTakeoffSource"] = "USER_INPUT"

            logger.ok(
                f"Drone altitude / sea level = {drone_Altitude_SeaLevel: .3f} m"
            )
            logger.ok(
                f"Companion EXIF file {str(dng_path.stem)}.exif has been reconstructed"
            )


        #  Keep only the selected metadata
        cleaned = {k: full_metadata.get(k) for k in essential_keys if k in full_metadata}

        # 5) Write the companion .exif JSON
        out_path = dng_path.with_suffix(".exif")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        return cleaned

    except Exception as e:
        logger.error(f" Read_exif_and_write_json failed for {dng_path}: {e}")
        return {}


def find_takeoff_altitude_from_exif_folder(folder: Path, logger) -> float:
    """
    Search for TakeOffAltitudeSeaLevel in existing .exif companion files.
    """
    exif_files = list(folder.glob("*.exif"))

    if not exif_files:
        logger.info("No companion .exif files found")
        return None

    for exif_file in exif_files:
        try:
            with open(exif_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 🥇 Direct match
            if "TakeOffAltitudeSeaLevel" in data:
                alti_Takeoff = float(data["TakeOffAltitudeSeaLevel"])
                logger.ok(
                    f"Takeoff altitude / sea level: {alti_Takeoff: .2f} m "
                    f"(found in {exif_file.name})"
                )
                return alti_Takeoff

            # 🥈 Derivable value
            if "DroneAltitudeSeaLevel" in data and "DroneAltitudeTakeOff" in data:
                alti_Takeoff = float(data["DroneAltitudeSeaLevel"]) - float(data["DroneAltitudeTakeOff"])
                logger.ok(
                    f"Takeoff altitude / sea level: {alti_Takeoff: .3f} m "
                    f"(derived from {exif_file.name})"
                )
                return alti_Takeoff

        except Exception as e:
            logger.warn(f"Failed to read EXIF file {exif_file.name}: {e}")

    logger.warn("No takeoff altitude found in the EXIF files")
    return None

def ask_takeoff_altitude_gui(prompt: str, default=None) -> float:
    """
    Open a Tkinter dialog to ask user for takeoff ground altitude (meters AMSL).
    Robust to comma/point decimal separators.
    """
    import tkinter as tk
    from tkinter import simpledialog, messagebox

    root = tk.Tk()
    root.withdraw()

    if default is not None:
        prompt_full = f"{prompt}\n(Suggested value: {round(default, 2)} m)"
    else:
        prompt_full = prompt

    while True:
        value = simpledialog.askstring(
            "Takeoff Altitude",
            prompt_full,
            parent=root
        )

        # ❌  User cancelled the dialog
        if value is None:
            root.destroy()
            raise ValueError("User input cancelled")

        # 🔧 Normalize the input
        value = value.strip().replace(",", ".")

        try:
            altitude = float(value)
        except ValueError:
            messagebox.showerror(
                "Input Error",
                "Please enter a valid number.\nExample: 563.8 or 563,8"
            )
            continue

        # 🔍 Physical plausibility check
        if altitude < -440 or altitude > 9000:
            messagebox.showerror(
                "Invalid Value",
                "Altitude outside the plausible range (-440 m to 9000 m)"
            )
            continue

        root.destroy()
        return altitude

def parse_and_normalize_gps_altitude(value: str) -> dict:
    """
    Extract and normalize altitude like:
        '0.6 m'
        '0.6 m above sea level'
        '350 ft'
        '350 ft Above Take Off'
    Returns a dict with value in meters and metadata.
    """
    s = value.strip().lower()

    # Regex: capture a number followed by a unit
    # Examples: '120.5 m', '350 ft', '12.34m', '50ft'
    match = re.search(r"([+-]?\d+(?:\.\d*)?)\s*(m|ft)\b", s)
    if not match:
        raise ValueError(
            f"Cannot extract altitude and unit from GPSAltitude: {value}"
        )

    number_str, unit = match.groups()
    number = float(number_str)

    # Unit conversion
    meters = number if unit == "m" else number * 0.3048

    return {
        "original_value": number,
        "original_unit": unit,
        "meters": round(meters, 3),
    }

def gps_coordinate_to_float(gps_coordinate: str) -> float:
    """
    Convert a GPS coordinate (Exif dng DJI) in the format 'DD deg MM' SS.SS\" D' to a floating point number.
    If the direction is N or W, the value is positive. If the direction is S or E, the value is negative.

    Example usage:  coord_str = "45 deg 10' 12.74\" N"
                    decimal_coord = gps_coordinate_to_float(coord_str)
                    print(decimal_coord)   # 45.17020556
    """
    # Replace 'deg' with a space and split the string
    parts = gps_coordinate.replace('deg', '').split()
    if len(parts) != 4 or parts[1][-1] != '\'' or parts[2][-1] != '"' or parts[3] not in ('N', 'S', 'E', 'W'):
        raise ValueError("Invalid GPS coordinate string format")

    # Extract degrees, minutes, seconds, and direction
    degrees = float(parts[0])
    minutes = float(parts[1][:-1])  # Remove the apostrophe
    seconds = float(parts[2][:-1])  # Remove the double quote
    direction = parts[3]

    # Convert to decimal degrees
    decimal_coord = degrees + minutes / 60 + seconds / 3600

    # Apply the sign according to the direction
    if direction in ['S', 'W']:
        decimal_coord = -decimal_coord

    return decimal_coord

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

    xUTM = round(x0 + K0 * A * (x1 + x2 + x3), 3)    # mm
    yUTM = round(y0 + K0 * A * (y1 + y2 + y3), 3)    # mm

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


def DJI2IRDrone(raw_exif, verbose=True):
    """
    Interpret DJI metadata for use in IRDrone.

    This function corrects the erroneous altitude definition provided by DJI
    and maps the drone attitude angles reported by DJI to the IRDrone model
    angles: xi_Y, xi_P, and xi_R.

    The IRDrone model uses only right-handed orthonormal coordinate frames.

    Geographic frame:
        {x_Gnd, y_Gnd, z_Gnd}
        x_Gnd points west to east, y_Gnd points south to north,
        and z_Gnd points upward.

    Image frame:
        {x_Img, y_Img, z_Img}
        x_Img points from left to right, y_Img points from bottom to top,
        and z_Img points from the ground toward the sensor.

    Images are captured in "gimbal-lock" mode, meaning that the camera's
    viewing axis points toward the nadir.

    Note:
        FlightYawDegree represents the heading, in the range [-180, +180],
        measured clockwise (positive toward the east).
        The heading is the opposite of the yaw angle xi_Y used in IRDrone,
        which represents the angle between the geographic north axis
        (y_Gnd) and the image vertical axis (y_Img).

        The same convention applies to GimbalYawDegree.

        If the pilot does not correctly align the camera at takeoff, i.e.
        (GimbalYawDegree - FlightYawDegree) != 0, this angular difference
        remains constant throughout the flight.

    The option_Yaw setting selects the yaw source:
        - option_Yaw = "Flight": xi_Y = -np.deg2rad(float(raw_exif['FlightYawDegree']))
        - option_Yaw = "Gimbal": xi_Y = -np.deg2rad(float(raw_exif['GimbalYawDegree']))

    Choosing between these options is not straightforward. The "Flight"
    option appears to be more reliable, although this is not certain.
    Field tests are needed to confirm this.

    Parameters
    ----------
    raw_exif : dict
        Dictionary containing the DJI metadata.
    verbose : bool
        If True, display the computed altitude, attitude angles, and UTM
        coordinates.

    Returns
    -------
    tuple
        latitude, longitude, z_ground, Z_cam_nadir, Z_cam_sealevel,
        UTM_x, UTM_y, zoneUTM, xi_Y, xi_P, xi_R
    """

    latitude = float(raw_exif['DroneLatitude'])
    longitude = float(raw_exif['DroneLongitude'])
    z_ground = float(raw_exif['GroundAltitude'])  # Ground elevation above sea level
    Z_cam_nadir = float(raw_exif['DroneAltitudeGround'])  # Drone altitude above ground level at the nadir
    Z_cam_sealevel = Z_cam_nadir + z_ground  # Drone altitude above sea level
    UTM_x = float(raw_exif['UTM_x'])
    UTM_y = float(raw_exif['UTM_y'])
    zoneUTM = int(raw_exif['UTM_zone'])

    option_Yaw = "Flight"

    if option_Yaw == "Flight":
        xi_Y = - np.deg2rad(float(raw_exif['FlightYawDegree']))
    elif option_Yaw == "Gimbal":
        xi_Y = - np.deg2rad(float(raw_exif['GimbalYawDegree']))
    else:
        print("Error in DJI2IRDrone: unknown Yaw option!")

    xi_P = np.deg2rad(float(raw_exif['FlightPitchDegree']))
    xi_R = np.deg2rad(float(raw_exif['FlightRollDegree']))

    gamma_Cap = np.deg2rad(float(raw_exif['FlightYawDegree']))
    gamma_Cap_Nav = cap_nav(gamma_Cap)  # In radians

    if verbose:
        logger.info(f"--------------------------------------------------------------------------\n"
                    f" Drone altitude / ground level  Z_cam_nadir    = {Z_cam_nadir: .2f} m\n"
                    f" Drone altitude / sea level     Z_cam_sealevel = {Z_cam_sealevel: .2f} m\n"
                    f" Yaw xi_Y = {np.rad2deg(xi_Y)} ° | Pitch xi_P = {np.rad2deg(xi_P)} ° | Roll xi_R = {np.rad2deg(xi_R)} °\n"
                    f" Heading = {np.rad2deg(gamma_Cap)} ° | Navigation heading = {np.rad2deg(gamma_Cap_Nav)} °\n"
                    f" UTM_x = {UTM_x : .2f} m  |   UTM_y = {UTM_y : .2f} m \n"
                    f" ")

    return latitude, longitude, z_ground, Z_cam_nadir, Z_cam_sealevel, UTM_x, UTM_y, zoneUTM, xi_Y, xi_P, xi_R


# ---------------------------------------------
#  ELEMENTARY ROTATIONS (geographic frame)
# ---------------------------------------------

def R_yaw(xi_Y):
    c, s = np.cos(xi_Y), np.sin(xi_Y)
    return np.array([[c, -s, 0],
                     [s, c, 0],
                     [0, 0, 1]])


def R_roll(xi_P):
    c, s = np.cos(xi_P), np.sin(xi_P)
    return np.array([[c, 0, s],
                     [0, 1, 0],
                     [-s, 0, c]])


def R_pitch(xi_R):
    c, s = np.cos(xi_R), np.sin(xi_R)
    return np.array([[1, 0, 0],
                     [0, c, -s],
                     [0, s, c]])


def cap_nav(cap):
    """
    Convert a heading angle in the range [-pi, +pi] to a navigation
    heading in the range [0, 2*pi].

    Heading and navigation-heading correspondence:
        Heading  0       (   0°)  <=> North   Navigation heading 0       (  0°)
        Heading +pi/2    ( +90°)  <=> East    Navigation heading pi/2   (+90°)
        Heading +pi      (+180°)  <=> South   Navigation heading pi     (180°)
        Heading -pi      (-180°)  <=> South   Navigation heading pi     (180°)
        Heading -pi/2    ( -90°)  <=> West    Navigation heading 3*pi/2 (270°)
        Heading  0       (   0°)  <=> North   Navigation heading 2*pi   (360°)

    Important:
        In a right-handed coordinate frame {O, x_Gnd, y_Gnd, z_Gnd}:
            x_Gnd points west to east.
            y_Gnd points south to north.
            z_Gnd = x_Gnd cross y_Gnd, pointing downward to upward.

        Heading angles are measured clockwise.

        The DJI drone provides gamma_Cap = FlightYawDegree.

    Parameters
    ----------
    cap : float
        Heading angle in radians.

    Returns
    -------
    capNav : float
        Navigation heading angle in radians.
    """
    if cap >= 0:
        capNav = cap
    else:
        capNav = 2 * np.pi + cap
    return capNav


# --------------------------------------------
#   MNT
# --------------------------------------------

def compute_MNT_mesh(
        N_mesh_x, N_mesh_y,
        xi_Yaw,
        R_Img2Gnd,
        Nx, Ny,
        fx, fy,
        cx, cy,
        UTM_x, UTM_y, Z0,
        z_ground,
        Cam_Center,
        folder_input,
        img_name,
        zoneUTM=31,
        ampli=1,
        txt="Maillage sol continu",
        verbose=True,
        view_graphic=False,
        graphic_2D=False,
        save_graphic=True
):
    """
    Build a terrain grid and retrieve its elevations from the IGN elevation API.

    Parameters
    ----------
    N_mesh_x, N_mesh_y : int
        Dimensions of the reference-point grid used to build the DTM.
    xi_Yaw : float
        Rotation angle between the geographic frame R_Gnd and the image frame R_Img.
    R_Img2Gnd : ndarray
        Rotation matrix from R_Img to R_Gnd.
    Nx, Ny : int
        Sensor dimensions in pixels.
    fx, fy : float
        Focal lengths along the sensor x and y axes, in pixels.
    cx, cy : float
        Optical center coordinates, in pixels.
    UTM_x, UTM_y : float
        Nadir position (projection of the optical center) in the R_Gnd
        coordinate frame, in meters.
    Z0 : float
        Reference altitude.
    Cam_Center : ndarray
        Drone coordinates at the time of image capture.
    z_ground : float
        Nadir elevation above sea level.
    folder_input : str or Path
        Input folder used for generated outputs.
    img_name : str
        Image name used to identify generated outputs.
    zoneUTM : int
        UTM zone used for coordinate conversion.
    ampli : float
        Expansion factor applied to the sensor footprint.
    txt : str
        Description used for the generated graphics.
    verbose : bool
        Enable diagnostic messages.
    view_graphic : bool
        Display the generated graphics.
    graphic_2D : bool
        Enable 2D grid and DTM visualization.
    save_graphic : bool
        Save the generated graphics.

    Returns
    -------
    Xg, Yg, Zg : ndarray
        Grid coordinates and terrain elevations.
    bound_pix : list
        Pixel-coordinate boundary points used for the ground footprint.
    """

    # -------------------------------------------------------------------
    # 0) Transformation matrix from the geographic frame R_Gnd
    #    to the camera frame R_Cam
    R_Cam2Gnd = R_Img2Gnd

    # -------------------------------------------------------------------
    # 1) Ground footprint on a horizontal plane
    # The rectangular sensor boundaries are defined relative to the optical center.
    # After Zhang calibration corrects lens distortion, the optical center
    # is not exactly at the geometric center of the sensor (variation of ~<1%).
    # The diagram below shows the nine points defining the sensor boundaries.
    #         7        6              5
    #         x--------x--------------x
    #         |        |              |
    #       8 x--------o--------------x 4
    #         |        |              |
    #         |        |              |
    #         x--------x--------------x
    #         1        2              3
    #
    # The sensor boundaries are artificially expanded to extend the DTM coverage.
    # This can help partially address, at low computational cost, the problem
    # of sloping terrain near the theoretical footprint boundary and below
    # the nadir altitude.
    # However, a value close to 1 does not guarantee that corner clipping
    # will be avoided.
    # An excessively large value increases the number of ground points
    # outside the image unnecessarily.
    #
    # bound_pix = [(pt0), (pt1), (pt2), (pt3), (pt4), (pt5), (pt6), (pt7), (pt8)]

    if verbose:
        logger.info(f" Ground footprint expansion factor: {ampli} ")

    # --- Project the sensor boundaries onto a horizontal plane
    # Important note: although the pinhole projection is oblique,
    # the footprint on a horizontal plane remains a rectangle centered
    # on the nadir, because the sensor itself is also horizontal.
    # X_Bound and Y_Bound are UTM coordinates in meters, expressed
    # in the R_Gnd coordinate frame.
    # A point in this frame is defined by:
    # OM = X_Bound * x_Gnd + Y_Bound * y_Gnd + Z_Bound * z_Gnd
    #

    # --- Build the ground grid on a horizontal plane
    # The grid is centered on the nadir. The nadir altitude is Z = 0 m.
    # These grid points serve as reference points for constructing
    # the DTM interpolator.
    # Expanded sensor boundaries
    cx_a, cy_a = cx * ampli, cy * ampli  # Left and top boundaries
    Nx_a, Ny_a = Nx * ampli, Ny * ampli  # Right and bottom boundaries

    # Make the boundaries symmetric
    Nn_x = int(max(cx * ampli, (Nx - cx) * ampli - 1))  # Left and right boundaries
    Nn_y = int(max(cy * ampli, (Ny - cy) * ampli - 1))  # Top and bottom boundaries

    bound_pix = [(0, 0),
                 (-Nn_x, -Nn_y), (0, -Nn_y), (Nn_x, -Nn_y),
                 (Nn_x, 0),
                 (Nn_x, Nn_y), (0, Nn_y), (-Nn_x, Nn_y),
                 (-Nn_x, 0)
                 ]

    X_Bound, Y_Bound, Z_Bound = \
        project_camera_to_horizontal_plane(bound_pix, R_Cam2Gnd, Cam_Center, fx, fy)

    Xg, Yg = build_continuous_ground_mesh(X_Bound, Y_Bound, Nx=N_mesh_x, Ny=N_mesh_y)
    Zg = Xg * 0

    if graphic_2D or save_graphic:
        # --- Sensor boundaries
        # This boundary is a rectangle centered on the optical center,
        # expressed in sensor pixel coordinates in bound_capteur.

        bound_capteur = [(0, 0),
                         (-cx, -cy), (0, -cy), (Nx - 1 - cx, -cy),
                         (Nx - 1 - cx, 0),
                         (Nx - 1 - cx, Ny - 1 - cy), (0, Ny - 1 - cy), (-cx, Ny - 1 - cy),
                         (-cx, 0)
                         ]
        X_Bound_capt, Y_Bound_capt, Z_Bound_capt = \
            project_camera_to_horizontal_plane(bound_capteur, R_Cam2Gnd, Cam_Center, fx, fy)

        graph_mesh_2D(Xg, Yg, X_Bound_capt, Y_Bound_capt, UTM_x, UTM_y, xi_Yaw,
                      folder_input, img_name,
                      txt=txt, view_graphic=view_graphic, save_graphic=save_graphic)

    # 2) Build the list of geographic coordinates

    # 2.1 Convert the coordinates (Xg, Yg) from UTM to geographic coordinates
    coordinates = []
    index_map = []  # Used to reconstruct the grid later

    # Define the grid indices
    #
    # i: ground-grid row index (Y direction)
    # j: ground-grid column index (X direction)
    #
    # Convention used:
    #   j = 0       -> left
    #   j = Nx-1    -> right
    #
    #   i = 0       -> bottom
    #   i = Ny-1    -> top
    #
    # Therefore:
    #   (i, j) = (0, 0) corresponds to the bottom-left corner.
    #
    # WARNING:
    # This convention differs from the image-coordinate convention,
    # where (0, 0) usually corresponds to the top-left corner.

    n_pts = 0
    for i in range(np.shape(Xg)[0]):
        for j in range(np.shape(Xg)[1]):
            lat, lon = UTM2geo(Xg[i, j], Yg[i, j], zoneUTM)
            coordinates.append((lat, lon))
            index_map.append((i, j))
            n_pts += 1

            # print(f"[DEBUG]  (i,j) = ({i} , {j})   lat ={lat :.5f}  | lon ={lon :.5f}")

    # 2.2 Retrieve the DTM reference-point elevations using the IGN API

    t0 = time.perf_counter()

    dic_geo_list = data_sig(coordinates, geotag=False, verbose=True)

    t1 = time.perf_counter()
    logger.timer(f" IGN API query: {t1 - t0:.3f} s")
    t0 = time.perf_counter()

    if dic_geo_list is None or len(dic_geo_list) != n_pts:
        raise ValueError("Error retrieving DTM elevations (API)")

    # print(f"[DEBUG]   dic_geo_list = {dic_geo_list} ")

    n_pts = 0
    for i in range(np.shape(Xg)[0]):
        for j in range(np.shape(Xg)[1]):
            Zg[i, j] = dic_geo_list[n_pts]['z']
            lat, lon = UTM2geo(Xg[i, j], Yg[i, j], zoneUTM)
            # print(f"[DEBUG] lon, lat , z = {lon}, {lat} , {Zg[i, j]}\n"
            #      f"{dic_geo_list[n_pts]['lon'] -lon}, {dic_geo_list[n_pts]['lat']-lat}, {dic_geo_list[n_pts]['z']- Zg[i, j]}")
            n_pts += 1

    return Xg, Yg, Zg, bound_pix


def build_continuous_ground_mesh(XB, YB, Nx=11, Ny=9):
    """
    Construit une grille terrain cartésienne régulière
    centrée exactement sur le nadir.

    XB, YB : coordonnées projetées des limites (points du capteur)
    Nx, Ny : doivent être impairs

    Retour
    ------
    Xg, Yg : arrays (Ny, Nx)
    """

    if Nx % 2 == 0 or Ny % 2 == 0:
        raise ValueError("Nx et Ny doivent être impairs pour centrer la grille sur le nadir")

    # centre (nadir)
    x0 = 0.5 * (np.min(XB) + np.max(XB))
    y0 = 0.5 * (np.min(YB) + np.max(YB))

    # demi-largeurs
    Lx = 0.5 * (np.max(XB) - np.min(XB))
    Ly = 0.5 * (np.max(YB) - np.min(YB))

    # pas
    dx = 2 * Lx / (Nx - 1)
    dy = 2 * Ly / (Ny - 1)

    # indices centrés
    ix = np.arange(-(Nx // 2), Nx // 2 + 1)
    iy = np.arange(-(Ny // 2), Ny // 2 + 1)

    # axes
    x = x0 + ix * dx
    y = y0 + iy * dy

    Xg, Yg = np.meshgrid(x, y)

    return Xg, Yg


def generate_contours(
    topo_array,
    transform,
    crs_utm,
    output_path,
    interval=10.0,
    fmt="GeoJSON"
):
    """
    Génère des courbes de niveau vectorielles à partir d'un raster numpy
    """

    # dimensions
    h, w = topo_array.shape

    # --- création raster GDAL en mémoire
    driver = gdal.GetDriverByName("MEM")
    ds = driver.Create("", w, h, 1, gdal.GDT_Float32)

    ds.SetGeoTransform((
        transform.c,
        transform.a,
        transform.b,
        transform.f,
        transform.d,
        transform.e
    ))

    srs = osr.SpatialReference()
    srs.ImportFromWkt(crs_utm.to_wkt())
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    band.WriteArray(topo_array)
    band.SetNoDataValue(np.nan)

    # --- création sortie vecteur
    drv = ogr.GetDriverByName(fmt)

    if output_path.exists():
        drv.DeleteDataSource(str(output_path))

    out_ds = drv.CreateDataSource(str(output_path))
    layer = out_ds.CreateLayer("contours", srs, ogr.wkbLineString)

    # champ altitude
    field_defn = ogr.FieldDefn("elev", ogr.OFTReal)
    layer.CreateField(field_defn)

    # --- génération des contours
    gdal.ContourGenerate(
        band,
        interval,     # intervalle (ex: 10m)
        0,            # base
        [],           # niveaux fixes
        0,            # ignore nodata
        0,
        layer,
        0,            # ID
        1             # champ elev
    )

    # cleanup
    out_ds = None
    ds = None


def generate_contours_dual(
    topo_array,
    transform,
    crs_utm,
    output_path,
    interval_minor=1.0,
    interval_major=10.0,
    fmt="GeoJSON",
    label_every_curve=False  # si True, crée un label pour chaque courbe, sinon seulement pour les principales
):
    """
    Génère :
    - courbes secondaires (1m)
    - courbes principales (10m)
    - champ 'type' : 1=minor, 10=major
    - labels optionnels pour chaque courbe
    """

    h, w = topo_array.shape

    # --- raster GDAL mémoire
    driver = gdal.GetDriverByName("MEM")
    ds = driver.Create("", w, h, 1, gdal.GDT_Float32)

    ds.SetGeoTransform((
        transform.c, transform.a, transform.b,
        transform.f, transform.d, transform.e
    ))

    srs = osr.SpatialReference()
    srs.ImportFromWkt(crs_utm.to_wkt())
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    band.WriteArray(topo_array)
    band.SetNoDataValue(np.nan)

    # --- sortie vecteur
    drv = ogr.GetDriverByName(fmt)

    if output_path.exists():
        drv.DeleteDataSource(str(output_path))

    out_ds = drv.CreateDataSource(str(output_path))
    layer = out_ds.CreateLayer("contours", srs, ogr.wkbLineString)

    # champs

    layer.CreateField(ogr.FieldDefn("elev", ogr.OFTReal))     # elevation de la courbe de niveau
    layer.CreateField(ogr.FieldDefn("type", ogr.OFTInteger))  # ID de la courbe de niveau

    # --- génération des courbes fines (1m)
    gdal.ContourGenerate(
        band,
        interval_minor,
        0,          # base
        [],         # niveaux fixes
        0,          # ignore nodata
        0,
        layer,
        1,          # champ elev = 1
        0           # champ ID
    )

    # --- mise à jour du champ 'type'
    for feat in layer:
        elev = feat.GetField("elev")
        # Si multiple de interval_major → courbe majeure
        if np.isclose(elev % interval_major, 0, atol=0.001):
            feat.SetField("type", 10)
        else:
            feat.SetField("type", 1)
        layer.SetFeature(feat)

    out_ds = None
    ds = None

    logger.ok(f" Contours générés : {output_path}")



def generate_qml_style_qgis(qml_path, style="IGN", label_on_line=True):
    """
    Génère un QML avec :
    - symbologie courbes 1m / 10m
    - labels :
        - sur la ligne (avec buffer)
    """

    # ----------------------------------------
    # Style des courbes et des labels
    # ----------------------------------------

    if style == "IGN":
        placement = '2'  # sur la ligne
        buffer_minor = "0.8"
        buffer_major = "2"
        color_minor = "205,86,2,255"
        color_major = "179,79,7,255"
        width_minor = "0.25"
        width_major = "0.5"
        font_Size_minor = "9"
        font_Size_major = "12"
        font_Family_minor = "Arial Narrow"
        font_Family_major = "Arial Rounded MT Bold"
        font_color_minor = "179,79,7,255"
        font_color_major = "179,79,7,255"

    elif style == "BW":
        placement = '2'  # sur la ligne
        buffer_minor = "0.5"
        buffer_major = "1"
        color_major = "0,0,0,255"
        color_minor = "0,0,0,255"
        width_major = "0.6"
        width_minor = "0.2"
        font_Size_minor = "9"
        font_Size_major = "12"
        font_Family_minor = "Arial"
        font_Family_major = "Arial"
        font_color_minor = "0,0,0,255"
        font_color_major = "0,0,0,255"

    elif style == "SOFT":
        placement = '2'  # sur la ligne
        buffer_minor = "0.5"
        buffer_major = "1"
        color_major = "120,120,120,255"
        color_minor = "180,180,180,255"
        width_major = "0.4"
        width_minor = "0.2"
        font_Size_minor = "8"
        font_Size_major = "10"
        font_Family_minor = "Calibri"
        font_Family_major = "Calibri"
        font_color_minor = "70,70,70,255"
        font_color_major = "50,50,50,255"

    else:
        raise ValueError(f"Style inconnu pour la carte topographique : {style}")


    qml = f"""<qgis version="3.22.5-Białowieża" labelsEnabled="1">
  <renderer-v2 type="RuleRenderer">
    <rules key="root">
      <!-- Courbes 10m -->
      <rule key="rule_10m" filter="abs(round(&quot;elev&quot;) % 10) = 0" label="10 m" symbol="0"/>
      <!-- Courbes 1m -->
      <rule key="rule_1m" filter="NOT (abs(round(&quot;elev&quot;) % 10) = 0)" label="1 m" symbol="1"/>
    </rules>
    <symbols>
      <!-- Symbole courbes 10m -->
      <symbol name="0" type="line">
        <layer class="SimpleLine" pass="0" enabled="1">
          <prop k="line_color" v="{color_major}"/>
          <prop k="line_width" v="{width_major}"/>
          <prop k="line_style" v="solid"/>
        </layer>
      </symbol>
      <!-- Symbole courbes 1m -->
      <symbol name="1" type="line">
        <layer class="SimpleLine" pass="0" enabled="1">
          <prop k="line_color" v="{color_minor}"/>
          <prop k="line_width" v="{width_minor}"/>
          <prop k="line_style" v="solid"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>

  <!-- Étiquetage rule-based -->
  <labeling type="rule-based">
    <rules key="root_label">
      <!-- Courbes 10m -->
      <rule key="label_10m" filter="abs(round(&quot;elev&quot;) % 10) = 0">
        <settings>
          <text-style 
                fieldName="elev"
                fontSize="{font_Size_minor}"
                fontFamily="{font_Family_major}"
                textColor="{font_color_major}">
            <text-buffer bufferSize="{buffer_major}" 
                bufferSizeUnits="MM" 
                bufferDraw="1" 
                bufferColor="255,255,255,255"/>
          </text-style>
          <placement placement="{placement}"/>
        </settings>
      </rule>
      <!-- Courbes 1m -->
      <rule key="label_1m" filter="NOT (abs(round(&quot;elev&quot;) % 10) = 0)">
        <settings>
          <text-style 
                fieldName="elev"
                fontSize="{font_Size_minor}"
                fontFamily="{font_Family_minor}"
                textColor="{font_color_minor}">
            <text-buffer 
                bufferSize="{buffer_minor}" 
                bufferSizeUnits="MM" 
                bufferDraw="1" 
                bufferColor="255,255,255,255"/>
          </text-style>
          <placement placement="{placement}"/>
        </settings>
      </rule>
    </rules>
  </labeling>
</qgis>
"""

    with open(qml_path, "w", encoding="utf-8") as f:
        f.write(qml)

    logger.ok(f" Pref .QML généré : {qml_path}")


# ------------------------------------------------------------------------
#      modules géo référencement
# ------------------------------------------------------------------------
def get_unique_path(path, verbose=False):

    if not path.exists():
        logger.info(f' Save file in {path}')
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    i = 1
    while True:
        new_path = parent / f"{stem}_{i}{suffix}"
        if not new_path.exists():
            if verbose:
                logger.warn(f' File {stem}{path.suffix} protected or open in QGIS')
            logger.ok(f' Save file in {new_path}')
            return new_path
        i += 1


def write_geotiff_affine(path_out, img, transform, crs, no_data=0, compress=True, bitdepth="float32"):


    h, w = img.shape[:2]
    bands = 1 if img.ndim == 2 else img.shape[2]

    if img.ndim == 3 and img.shape[2] == 3:
        img_out = img[..., ::-1]  # plus rapide que cv2.cvtColor(img, cv2.COLOR_BGR2RGB) car tab numpy
    else:
        img_out = img

    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": bands,
        "dtype": img_out.dtype,
        "crs": crs,
        "transform": transform,
        "nodata": no_data,
        "photometric": "RGB" if bands == 3 else "MINISBLACK",
        "interleave": "pixel",
        "BIGTIFF": "IF_SAFER",

        # --- optimisations raster ---
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256
    }
    if compress:
        predictor = 3 if np.issubdtype(img_out.dtype, np.floating) else 2
        # option pour "compress"  "deflate"  "lzw" (compression moins effficace mais lègérement plus rapide)
        profile.update({
            "compress": "deflate",
            "predictor": predictor,
            "zlevel": 4
        })

    with rasterio.open(path_out, "w", **profile) as dst:

        if bitdepth == "uint8":
            img_out = (img_out * 255).astype(np.uint8)
            logger.info(f'sortie rasterio bitdepth ={bitdepth}')

        if bands == 1:
            if img_out.ndim == 3:
                img_out = img_out[:, :, 0]
            dst.write(img_out, 1)

        else:
            dst.write(np.moveaxis(img_out, -1, 0))

        if bands == 4:
            dst.set_band_description(1, "Red")
            dst.set_band_description(2, "Green")
            dst.set_band_description(3, "Blue")
            dst.set_band_description(4, "NIR")
            dst.update_tags(4, wavelength="NIR")

        elif bands == 3:
            dst.set_band_description(1, "Red")
            dst.set_band_description(2, "Green")
            dst.set_band_description(3, "Blue")

        elif bands == 1:
            dst.set_band_description(1, "Gray")


def project_camera_to_horizontal_plane(
        pix,
        R_Cam2Gnd,
        Cam_Center,
        fx, fy,
        Z0=0,
        verbose=False):
    """

    """

    X_s, Y_s, Z_s = [], [], []
    for u, v in pix:
        # CAMERA -> SOL
        # coordonnées du rayon issu de la caméra pinhole et passant par un pixel image
        ray_Cam = np.array([u / fx, v / fy, -1])
        ray_Cam /= np.linalg.norm(ray_Cam)  # normalisation du rayon

        # calcul du point d'intersection  du rayon caméra avec le sol horizontal
        # les coordonnées de ce point sont données dans le repère R_Gnd

        ray_Gnd = R_Cam2Gnd @ ray_Cam
        Xc, Yc, Zc = Cam_Center
        rx, ry, rz = ray_Cam
        t = (Z0 - Zc) / rz
        P_s = Cam_Center + t * ray_Gnd

        X_s.append(P_s[0])
        Y_s.append(P_s[1])
        Z_s.append(P_s[2])

    return X_s, Y_s, Z_s


def project_camera_to_MNT(
        pix,  # pixels du capteur à projeter, shape (N, 2)
        Nx, Ny,  # taille capteur
        R_Cam2Gnd,  # rotation caméra -> sol
        Cam_Center,  # position caméra dans R_Gnd
        fx, fy,  # focale
        cx, cy,  # centre optique
        altitude,  # fonction altitude(X, Y)
        verbose=False
):
    """
    Projet des rayons caméra sur le MNT via la fonction altitude.

    Paramètres
    ----------
    pix : np.ndarray
        Pixels à projeter, shape (N, 2). Coordonnées ralatives au centre optique
    Nx, Ny : int
        Dimensions du capteur
    R_Cam2Gnd : np.ndarray
        Rotation 3x3 caméra -> sol
    Cam_Center : np.ndarray
        Position caméra (X, Y, Z) dans R_Gnd
    fx, fy : float
        Focale en pixels
    cx, cy : float
        Centre optique en pixels
    altitude : callable
        Fonction altitude(X, Y) renvoyant Z
    verbose : bool
        Affichage debug

    Retour
    ------
    X_s, Y_s, Z_s : np.ndarray
        Coordonnées 3D du sol projeté, shape (N,)
    """

    X_s = []
    Y_s = []
    Z_s = []

    for u, v in pix:
        # vecteur du rayon en repère caméra
        ray_cam = np.array([u / fx, v / fy, -1.0])
        ray_cam /= np.linalg.norm(ray_cam)

        # transforme le rayon en repère sol
        ray_gnd = R_Cam2Gnd @ ray_cam

        # intersection avec le MNT : méthode simple (Newton, dichotomie, ou ici itérative)
        # approche initiale : marcher le long du rayon jusqu'à Z ~= altitude(X,Y)

        max_iter = 100
        tol = 0.01  # tolérance 10 cm
        t = 0.0
        count_iter = 0
        for _ in range(max_iter):
            count_iter += 1
            P = Cam_Center + t * ray_gnd
            P = Cam_Center + t * ray_gnd
            Z_t = altitude(P[0], P[1])
            dz = Z_t - P[2]
            if abs(dz) < tol:
                break
            t += dz / ray_gnd[2]  # correction simple sur Z
        X_s.append(P[0])
        Y_s.append(P[1])
        Z_s.append(P[2])

        if verbose:
            print(f"[DEBUG]  iter intersection = {count_iter}   |  altitude Z_t = {Z_t} m'\n"
                  f"[DEBUG] pixel ({u_pix},{v_pix}) -> sol ({P[0]:.2f},{P[1]:.2f},{P[2]:.2f})")

    return np.array(X_s), np.array(Y_s), np.array(Z_s)


def project_ground_to_camera_batch(
        P_sol,
        R_Gnd2Cam,
        Cam_Center,
        fx, fy,
        cx, cy,
        dist=None,
        verbose=False):
    # -----------------------------------------------------------------------------
    # SOL -> CAMERA
    # P_sol coordonnées UTM d'un point dans repère R_Gnd
    # Cam_Center coordonnées UTM du centre optique  dans repère R_Gnd
    # Pcam coordonnées (en m) dans le repère de la caméra  (origine centre optique)
    # ------------------------------------------------------------------------------
    dP_Gnd = P_sol - Cam_Center  # (...,3)

    P_cam = np.einsum(
        'ij,...j->...i',
        R_Gnd2Cam,
        dP_Gnd
    )

    Xcam = P_cam[..., 0]
    Ycam = P_cam[..., 1]
    Zcam = P_cam[..., 2]

    # ---------------------
    # CHECK GEOMETRIQUE
    # ---------------------

    # logger.warn(f" Zc stats : {np.min(Zcam)} , {np.max(Zcam)}")
    if np.any(Zcam >= 0):
        logger.warn(" points derrière caméra")

    # ------------------------------------------
    # Projection perspective (modèle pinhole)
    # ------------------------------------------

    x = Xcam / -Zcam
    y = Ycam / -Zcam

    # ----------------------------------------------
    # DISTORSION LENTILLE (modèle Zhang / OpenCV)
    # ----------------------------------------------

    if dist is not None:
        k1, k2, p1, p2, k3 = dist

        r2 = x * x + y * y
        r4 = r2 * r2
        r6 = r4 * r2

        radial = 1 + k1 * r2 + k2 * r4 + k3 * r6

        x_dist = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        y_dist = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y

        x = x_dist
        y = y_dist

    # ---------------------------------------------------------
    # Conversion coordonnées pixels centreé sur centre optique
    # ----------------------------------------------------------

    u = fx * x + cx
    v = fy * y + cy

    return u, v, Zcam

# ---- calcul d'erreur

def compute_error_rmse_montecarlo(
        P_sol,
        u_ref, v_ref,
        Cam_Center,
        xi_Y,
        fx, fy,
        cx, cy,
        gsd_x, gsd_y,
        sigma_yaw_deg,
        sigma_xy,
        sigma_z,
        sigma_z_mnt,
        project_ground_to_camera_batch,
        R_yaw,
        N_max=500,
        N_min=4,
        tol_MC=0.01,
        verbose=True):
    """
    Monte-Carlo global sur toutes les sources d'erreur.
    tol : critère de convergence relatif sur la RMSE (1% par défaut)
    """

    sigma_yaw = np.deg2rad(sigma_yaw_deg)

    # accumulateur
    sum_sq = np.zeros_like(u_ref, dtype=np.float64)

    rmse_prev = None

    for k in range(1, N_max + 1):

        # ---------------------------------
        # tirage des perturbations
        # ---------------------------------

        dx = np.random.normal(0, sigma_xy)
        dy = np.random.normal(0, sigma_xy)
        dz = np.random.normal(0, sigma_z)

        dyaw = np.random.normal(0, sigma_yaw)

        dz_mnt = np.random.normal(0, sigma_z_mnt)

        # ---------------------------------
        # paramètres perturbés
        # ---------------------------------

        Cam_pert = (
            Cam_Center[0] + dx,
            Cam_Center[1] + dy,
            Cam_Center[2] + dz
        )

        R_pert = R_yaw(xi_Y + dyaw)

        P_pert = P_sol.copy()
        P_pert[..., 2] += dz_mnt

        # ---------------------------------
        # reprojection
        # ---------------------------------

        u_p, v_p, _ = project_ground_to_camera_batch(
            P_pert,
            R_pert.T,
            Cam_pert,
            fx, fy,
            cx, cy,
            verbose=False
        )

        du = u_p - u_ref
        dv = v_p - v_ref

        err = np.sqrt((du * gsd_x) ** 2 + (dv * gsd_y) ** 2)

        sum_sq += err ** 2

        # ---------------------------------
        # RMSE courante
        # ---------------------------------

        rmse = np.sqrt(sum_sq / k)

        # ---------------------------------
        # contrôle convergence
        # ---------------------------------

        if k > N_min:

            diff = np.nanmean(np.abs(rmse - rmse_prev) / (rmse_prev + 1e-9))

            if verbose:
                print(f"[Monte Carlo] iter={k} convergence={100 * diff:.2f}%")

            if diff < tol_MC:
                if verbose:
                    print(f"[Monte Carlo] convergence {100 * diff:.5f}% atteinte à N={k}")
                break

        rmse_prev = rmse.copy()

    return rmse

# -------------------

def is_regular_grid(Xg, Yg, tol=1e-10):
    """
    Détecte si une grille est régulière.
    """
    x_ref = Xg[0, :]
    y_ref = Yg[:, 0]

    cond_x = np.allclose(Xg, np.tile(x_ref, (Yg.shape[0], 1)), atol=tol)
    cond_y = np.allclose(Yg, np.tile(y_ref[:, None], (1, Xg.shape[1])), atol=tol)

    return cond_x and cond_y

def build_MNT_interpolator(Xg, Yg, Zg, method="RectBivariateSpline_quadratic", type_grid="auto"):

    if type_grid == "auto":
        regular = is_regular_grid(Xg, Yg)
    else:
        regular = (type_grid == "regular")

    logger.info(f" regular grid = {regular}")

    # choix de la méthode d'interpolation du MNT
    # options possibles :
    # "RectBivariateSpline_cubic"
    # "RectBivariateSpline_quadratic"
    # "RectBivariateSpline_linear"

    # =====================================================
    # GRILLE REGULIERE
    # =====================================================
    if regular:

        # axes réels de la grille
        x = Xg[0, :]
        y = Yg[:, 0]

        logger.info(f" interpolation method :  {method}\n"
                    f"            grid size : {len(x)} x {len(y)}")

        # -------------------------------------------------
        # Interpolation bicubique
        # -------------------------------------------------
        if method == "RectBivariateSpline_cubic":
            """
            Interpolation spline bicubique (ordre 3).

            Propriétés :
            - continuité C2 (fonction + dérivées 1 et 2 continues)
            - surface très lisse
            - bon comportement pour calculs géométriques
            - coût de calcul le plus élevé
            """

            spline = RectBivariateSpline(y, x, Zg, kx=3, ky=3)

        # -------------------------------------------------
        # Interpolation quadratique
        # -------------------------------------------------
        elif method == "RectBivariateSpline_quadratic":
            """
            Interpolation spline quadratique (ordre 2).

            Propriétés :
            - continuité C1 (fonction + dérivée première continue)
            - surface lisse mais moins que bicubique
            - compromis précision / vitesse souvent intéressant
            - coût de calcul inférieur au bicubique
            """

            spline = RectBivariateSpline(y, x, Zg, kx=2, ky=2)

        # -------------------------------------------------
        # Interpolation linéaire (bilinéaire)
        # -------------------------------------------------
        elif method == "RectBivariateSpline_linear":
            """
            Interpolation bilinéaire (ordre 1).

            Propriétés :
            - continuité C0 (fonction continue)
            - dérivées discontinues aux limites des cellules
            - surface facettée (plan par cellule)
            - très rapide
            - souvent suffisant pour un MNT
            """

            spline = RectBivariateSpline(y, x, Zg, kx=1, ky=1)

            return altitude

        # -------------------------------------------------
        # fonction altitude pour les splines
        # -------------------------------------------------

        def altitude(X, Y):

            X = np.asarray(X)
            Y = np.asarray(Y)

            shp = X.shape

            z = spline.ev(Y.ravel(), X.ravel())

            return z.reshape(shp)

    # =====================================================
    # GRILLE IRREGULIERE
    # =====================================================
    else:

        pts = np.column_stack((Xg.ravel(), Yg.ravel()))
        z = Zg.ravel()

        spline = RBFInterpolator(
            pts,
            z,
            kernel="thin_plate_spline"
        )

        def altitude(X, Y):

            X = np.asarray(X)
            Y = np.asarray(Y)

            shp = X.shape

            pts_eval = np.column_stack((X.ravel(), Y.ravel()))

            z = spline(pts_eval)

            return z.reshape(shp)

    return altitude

# ---------------  éléments graphiques

def plot_terrain_3d(Xg_abs, Yg_abs, Zg_abs, X0, Y0, Z0, xi_Yaw, N_mesh_x, N_mesh_y,
                    altitude, folder_input, img_name, graphic_3D=False, view_graphic=False, save_graphic=False,
                    title="Terrain", nx_subdiv=60, ny_subdiv=45, axes_terrain=True):

    if not view_graphic and not save_graphic:
        return
    geo_path = folder_input / "geo_ref" / f"{img_name}_MNT.png"

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    # coordonnées relatives au nadir (X0, Y0, Z0)
    Xg = Xg_abs - X0
    Yg = Yg_abs - Y0
    Zg = Zg_abs - Z0

    # print(f'[DEBUG]   nx_subdiv={nx_subdiv} ny_subdiv={ny_subdiv}')

    # --- grille dense pour surface lisse du MNT ---
    x_dense = np.linspace(Xg_abs.min(), Xg_abs.max(), nx_subdiv)
    y_dense = np.linspace(Yg_abs.min(), Yg_abs.max(), ny_subdiv)
    Xd_abs, Yd_abs = np.meshgrid(x_dense, y_dense)

    # --- calcul des altitudes de la grille dense via l'interpolateur ---
    # altitude ; renvoie les altitudes relatives au nadir.
    Zd = altitude(Xd_abs, Yd_abs)

    # print(f'[DEBUG]   dim Xd_abs={np.shape(Xd_abs)} dim Yd_abs ={np.shape(Yd_abs)}')

    # coordonnées relatives
    Xd = Xd_abs - X0
    Yd = Yd_abs - Y0

    # --- surface lisse du MNT ---
    ax.plot_surface(Xd, Yd, Zd,
                    cmap="gray",  # "terrain",
                    alpha=0.55,
                    linewidth=0.1,
                    color="lightgray",
                    antialiased=True
                    )

    # --- points du MNT originaux ---
    ax.scatter(Xg, Yg, Zg, color="darkgreen", s=2)
    ax.scatter(0, 0, 0, color="red", s=4)
    # ---- Axes terrain explicites
    z_ref = np.min(Zg) - 30
    if axes_terrain:
        # Vecteurs repère sol horizontal
        x0, y0, z0 = 0, 0, z_ref
        Lg = 20  # longueur flèche en m

        arrow3d(ax, (x0, y0, z_ref), (Lg, 0, 0), 'blue')
        arrow3d(ax, (x0, y0, z_ref), (0, Lg, 0), 'blue')
        arrow3d(ax, (x0, y0, z_ref), (0, 0, 0.6 * Lg), 'blue')

        legend_repere = "ENZ"
        if legend_repere == "vector":
            ax.text(x0 + Lg, y0, z_ref, r"$\vec{x}_{Gnd}$", color='blue')
            ax.text(x0, y0 + Lg, z_ref, r"$\vec{y}_{Gnd}$N", color='blue')
            ax.text(x0, y0, z_ref + 0.6 * Lg, r"$\vec{z}_{Gnd}$", color='blue')
        elif legend_repere == "ENZ":
            ax.text(x0 + Lg, y0, z_ref, "E ", color='blue')
            ax.text(x0, y0 + Lg, z_ref, "N", color='blue')
            ax.text(x0, y0, z_ref + 0.6 * Lg, "Z", color='blue')
        else:
            pass

    # --- Plan horizontal de référence (légèrement sous le sol)
    Xp, Yp = np.meshgrid(
        np.linspace(np.min(Xg), np.max(Xg), 2),
        np.linspace(np.min(Yg), np.max(Yg), 2))
    Zp = np.full_like(Xp, z_ref)
    ax.plot_surface(Xp, Yp, Zp, color='lightgray', alpha=0.25, edgecolor='none')

    # Respect de distances sur les axes X/Y
    force_square_xy(ax)
    ax.set_proj_type('ortho')
    ax.set_box_aspect((1, 1, 1))

    # --- Nettoyage visuel du repère 3D
    ax.grid(False)

    ax.xaxis.pane.set_visible(False)
    ax.yaxis.pane.set_visible(False)
    ax.zaxis.pane.set_visible(False)

    ax.set_xlabel("EW (m from nadir)")
    ax.set_ylabel("SN (m from nadir)")
    ax.set_zlabel("Altitude relative (m)")
    ax.set_title(title)

    # réglage aspect ratio pour visualisation réaliste
    ax.set_box_aspect([1, 1, 1])
    # --- sauvegarde éventuelle ---
    if save_graphic:
        fig.savefig(geo_path, dpi=300, bbox_inches="tight")
        logger.ok(f" Save graphic in : {geo_path}")

    # --- affichage éventuel ---
    if view_graphic:
        plt.show()
    else:
        plt.close(fig)

def arrow3d(ax, O_h, V, color):
    O_h = np.array(O_h)
    V = np.array(V)

    # corps
    ax.plot([O_h[0], O_h[0] + V[0]],
            [O_h[1], O_h[1] + V[1]],
            [O_h[2], O_h[2] + V[2]],
            color=color, linewidth=1)

    # petite flèche finale
    ax.quiver(O_h[0] + 0.85 * V[0], O_h[1] + 0.85 * V[1], O_h[2] + 0.85 * V[2],
              0.15 * V[0], 0.15 * V[1], 0.15 * V[2],
              color=color, arrow_length_ratio=0.3)

def force_square_xy(ax):
    xmin, xmax = ax.get_xlim3d()
    ymin, ymax = ax.get_ylim3d()
    zmin, zmax = ax.get_zlim3d()

    dx = xmax - xmin
    dy = ymax - ymin
    L = max(dx, dy)

    xc = 0.5 * (xmax + xmin)
    yc = 0.5 * (ymax + ymin)

    ax.set_xlim3d(xc - L / 2, xc + L / 2)
    ax.set_ylim3d(yc - L / 2, yc + L / 2)

    # optionnel : harmoniser aussi Z pour une vraie boîte cubique
    zc = 0.6 * (zmax + zmin)
    # ax.set_zlim3d(zc - L / 2, zc + L / 2)

def graph_mesh_2D(Xg_abs, Yg_abs, X_Bound_abs, Y_Bound_abs, UTM_x, UTM_y, xi_Yaw,
                  folder_input, img_name, save_graphic=True,
                  txt="", view_graphic=False):
    """
    Grille centrée sur le nadir. Repère EW-SN . unité : m
    :param Xg_abs:
    :param Yg_abs:
    :param X_Bound_abs:
    :param Y_Bound_abs:
    :param UTM_x:
    :param UTM_y:
    :return:
    """

    if not view_graphic and not save_graphic:
        return
    geo_path = folder_input / "geo_ref" / f"{img_name}_Grid.png"

    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111)

    Xg = Xg_abs - UTM_x
    Yg = Yg_abs - UTM_y

    Ny, Nx = Xg.shape

    X_Bound = np.array(X_Bound_abs) - UTM_x
    Y_Bound = np.array(Y_Bound_abs) - UTM_y

    # -----------------------------
    # tracé des lignes de la grille
    # -----------------------------
    for i in range(Ny):
        plt.plot(Xg[i, :], Yg[i, :], 'k', linewidth=0.8)

    for j in range(Nx):
        plt.plot(Xg[:, j], Yg[:, j], 'k', linewidth=0.8)

    # -----------------------------
    # axes capteur
    # -----------------------------
    scale = 3 * min((Xg.max() - Xg.min())/Nx, (Yg.max() - Yg.min())/Ny)
    plt.arrow(0, 0, scale * np.cos(xi_Yaw), scale * np.sin(xi_Yaw),
                width=0.3, color="red")
    plt.arrow(0, 0, -scale * np.sin(xi_Yaw), scale * np.cos(xi_Yaw),
        width=0.3, color="green")

    # -----------------------------
    # affichage des indices (i,j)
    # -----------------------------
    dx = 0.003 * (Xg.max() - Xg.min())
    dy = 0.003 * (Yg.max() - Yg.min())
    for i in range(Ny):
        for j in range(Nx):
            x, y = Xg[i, j], Yg[i, j]
            plt.text(x+dx, y+dy, f"({i},{j})",
                fontsize=3, color="darkgreen", ha="center", va="center")

    # ----------------------------------------------------------
    # affichage des indices B(k) des 9 points de référence.
    # ----------------------------------------------------------

    for k, (x, y) in enumerate(zip(X_Bound, Y_Bound)):
        plt.text(x+2*dx, y+2*dy, f"B{k}", color="red", fontsize=9)


    # -----------------------------
    # bornes capteur projetées
    # -----------------------------

    x = X_Bound[1:]
    y = Y_Bound[1:]

    # fermeture du polygone
    x = np.append(x, x[0])
    y = np.append(y, y[0])

    plt.plot(x, y, color='black')
    plt.fill(x, y, color='gray', alpha=0.3, label="Emprise capteur")


    # points rouges par dessus
    plt.scatter(x, y, c='red', s=20, label="Bornes image")

    # centre caméra nadir
    plt.scatter(0, 0, c='blue', s=40, label="Nadir caméra")


    # plt.grid(True, alpha=0.3)
    plt.title(txt)
    plt.legend()
    plt.axis('equal')

    # --- sauvegarde éventuelle ---
    if save_graphic:
        fig.savefig(geo_path, dpi=300, bbox_inches="tight")
        logger.ok(f" graphic saved : {geo_path}")

    # --- affichage éventuel ---
    if view_graphic:
        plt.show()
    else:
        plt.close(fig)

def plot_grille_image(u, v, cx=0, cy=0):
    plt.scatter(u, v, s=2)
    plt.scatter(cx, cy, s=10, color='r')
    plt.gca().invert_yaxis()
    plt.title("Projection grille sol -> image")
    plt.show()

def graph_ortho(ortho_display, xo, yo, ortho_path, graphic_ortho=False, view_graphic=False, save_graphic=False):
    if graphic_ortho:
        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111)
        plt.imshow(ortho_display, origin="lower")  # , extent=extent)
        # plt.scatter(xo, yo, c="red", marker="+", s=100)
        plt.gca().invert_yaxis()
        plt.xlabel("ΔX terrain (m)")
        plt.ylabel("ΔY terrain (m)")
        plt.title("Orthorectification — Test")
        # --- sauvegarde éventuelle ---
        if save_graphic:
            fig.savefig(ortho_path, dpi=300, bbox_inches="tight")
            logger.ok(f" graphic saved : {ortho_path}")
        # --- affichage éventuel ---
        if view_graphic:
            print(f'DEBUG  view_graphic ={view_graphic}')
            plt.show()
        else:
            plt.close(fig)
    else:
        pass

# -----------   Tag image

def tag_image(img_raw, tif_path_taged, cx, cy,
              verbose=False, draw_square_tag=False,
              draw_axe=False, draw_arrow_x=False, draw_arrow_y=True,
              draw_grid=True, grid_step=None):
    """
    création d'une image brute avec les marques
    :return:
    """

    # -------------------------------------------------------
    # création d'une image brute avec les marques
    # -------------------------------------------------------
    cx = int(cx)
    cy = int(cy)

    # - 1) Image sans les marques
    Ny_raw, Nx_raw = img_raw.shape[:2]
    bands = 1 if img_raw.ndim == 2 else img_raw.shape[2]

    # - 2) Adaptation dynamique couleur selon profondeur
    if img_raw.dtype == np.uint16:
        CMAX = 65535
    elif img_raw.dtype == np.uint32:
        CMAX = 4294967295
    else:
        CMAX = 255
    # Passage en couleur si besoin
    if img_raw.ndim == 2:
        img = cv2.cvtColor(img_raw, cv2.COLOR_GRAY2BGR)
    else:
        img = img_raw.copy()

    # _ 3) Impression des marques de repère image
    # centre image (cx, cy) (si Undistord en général cx != Nx_raw // 2 et cy != Ny_raw // 2 )
    # --------- 3.0) grille régulière
    if draw_grid:
        if grid_step is None:
            grid_step = Nx_raw // 10  # densité par défaut

        grid_color = (CMAX, CMAX, CMAX)

        draw_grid_centered(
            img,
            cx,
            cy,
            grid_step,
            grid_color,
            thickness=2
        )

    # ----- 3.1) Axes et vecteurs image
    L = Nx_raw // 4
    if draw_axe:
        # axe x horizontal
        cv2.arrowedLine(img, (0, cy), (2 * cx, cy), (CMAX // 1.5, CMAX // 1.5, CMAX // 1.5), 4, tipLength=0.00)
        # axe y vertical
        cv2.arrowedLine(img, (cx, 0), (cx, 2 * cy), (CMAX // 1.5, CMAX // 1.5, CMAX // 1.5), 4, tipLength=0.00)
    if draw_arrow_x:
        # x_img → droite (rouge)
        cv2.arrowedLine(img, (cx, cy), (cx + L, cy), (0, 0, 0.5 * CMAX), 10, tipLength=0.05)
    if draw_arrow_y:
        # y_img → haut (vert)
        cv2.arrowedLine(img, (cx, cy), (cx, cy - L), (0, 0.5 * CMAX, 0), 10, tipLength=0.05)

    # ----- 3.2) Pavés et Carrés
    if draw_square_tag:
        S = 200
        Dx = Nx_raw // 4
        Dy = Ny_raw // 4

        # --------- 3.2.1) Quadrant I  Noir
        draw_square(img, cx + Dx, cy - Dx, S, (20, 20, 20))
        # --------- 3.2.2) Quadrant II  Gris
        draw_square(img, cx - Dx, cy - Dx, S, (CMAX / 3, CMAX / 3, CMAX / 3))
        # --------- 3.2.3) Quadrant III  Blanc
        draw_square(img, cx - Dx, cy + Dx, S, (CMAX, CMAX, CMAX))
        # --------- 3.2.4) Quadrant IV  Intérieur transparent
        draw_square_outline(img, cx + Dx, cy + Dx, S, (CMAX, CMAX, CMAX), thickness=6)
        # --------- 3.2.5) carré contour blanc entre le carrés quadrant
        draw_square_outline(img, cx, cy, Nx_raw // 2 + S, (CMAX, CMAX, CMAX), thickness=4)

    # --------- 3.3) Centre optique
    cv2.circle(img, (cx, cy), 12, (0, 0, 0), -1)

    # --------- 3.4) Centre géométrique
    cv2.circle(img, (Nx_raw // 2, Ny_raw // 2), 8, (CMAX, CMAX, 0), -1)

    # - 4)  Sauvegardes TIFF avec Tags
    cv2.imwrite(str(tif_path_taged), img)



    if verbose:
        print(f"Image avec Tags sauvegardée :  {tif_path_taged}")

    return img
    # -------------------------------------------------------
    # Fin création d'une image brute avec les marques
    # -------------------------------------------------------

def draw_grid_centered(img, cx, cy, step_x, color, thickness=1):

    Ny, Nx = img.shape[:2]

    step_y = step_x  # int(step_x * 3 / 4)

    # lignes verticales
    x = cx
    while x < Nx:
        cv2.line(img, (int(x), 0), (int(x), Ny), color, thickness)
        x += step_x

    x = cx - step_x
    while x >= 0:
        cv2.line(img, (int(x), 0), (int(x), Ny), color, thickness)
        x -= step_x

    # lignes horizontales
    y = cy
    while y < Ny:
        cv2.line(img, (0, int(y)), (Nx, int(y)), color, thickness)
        y += step_y

    y = cy - step_y
    while y >= 0:
        cv2.line(img, (0, int(y)), (Nx, int(y)), color, thickness)
        y -= step_y

def draw_square(img, xc, yc, size, color):
    h = size // 2
    cv2.rectangle(img, (int(xc - h), int(yc - h)), (int(xc + h), int(yc + h)), color, -1)

def draw_square_outline(img, x_center, y_center, size, color, thickness=3):
    h = size // 2
    pt1 = (int(x_center - h), int(y_center - h))
    pt2 = (int(x_center + h), int(y_center + h))
    cv2.rectangle(img, pt1, pt2, color, thickness)

# --------------------------------------------------
# sélection interactive des images
# --------------------------------------------------


def choose_images(folder_mission: Path):

    root = tk.Tk()
    root.withdraw()

    filepaths = filedialog.askopenfilenames(
        parent=root,
        title="Sélectionner les images",
        initialdir=str(folder_mission),
        filetypes=[
            ("Images DNG, TIF", "*.dng *.tif"),
            ("All files", "*.*")
        ]
    )

    root.destroy()

    if not filepaths:
        print("Aucune image sélectionnée.")
        sys.exit(0)

    paths = [Path(p) for p in filepaths]

    folder_input = paths[0].parent
    list_path = sorted(paths)
    list_img = sorted([p.name for p in paths])
    list_img_name = sorted([p.stem for p in paths])

    return folder_input, list_img_name, list_img, list_path



def choose_images_dev():
    """
    A conserver. Permet d'utiliser le lancement par ligne de commande
    et d'accéder au mode interactif
    :return:
    """

    root = tk.Tk()
    root.withdraw()

    filepaths = filedialog.askopenfilenames(
        title="Sélectionner les images",
        filetypes=[("Images DNG, TIF", "*.dng  *.tif"), ("All files", "*.*")]
    )

    if not filepaths:
        print("Aucune image sélectionnée.")
        sys.exit(0)

    paths = [Path(p) for p in filepaths]

    folder_input = paths[0].parent
    list_path = sorted(paths)
    list_img = sorted([p.name for p in paths])  # name + suffix
    list_img_name = sorted([p.stem for p in paths])  # name

    return folder_input, list_img_name, list_img, list_path



# --------------------------------------------------
# ligne de commande
# --------------------------------------------------

def add_bool_arg(parser, name, default, help_text):
    group = parser.add_mutually_exclusive_group()

    group.add_argument(f"--{name}", dest=name, action="store_true",
                       help=f"{help_text} (default={default})")

    group.add_argument(f"--no-{name}", dest=name, action="store_false",
                       help=f"disable {help_text}")

    parser.set_defaults(**{name: default})

def parse_args():
    parser = argparse.ArgumentParser(description="Orthorectification GeoRef")

    parser.add_argument("--input_dir", help="dossier images (ex: .../VIS)")
    parser.add_argument("--images", nargs="+", help="liste images sans extension")
    parser.add_argument("--suffix", default="dng")
    parser.add_argument("--mode",
                        default="raw_DJI",
                        choices=["raw_DJI", "multispectral"],
                        help="type image entrée")
    parser.add_argument("--topo_style", default="IGN")

    parser.add_argument("--bitdepth",
                        default="float32",
                        choices=["float32", "uint8"],
                        help="type image sortie")

    parser.add_argument("--offsetyaw",
                        type=float,
                        default=0,
                        help="offset yaw en degrés")

    parser.add_argument("--offsetUTMx",
                        type=float,
                        default=0,
                        help="offset UTM vers EST en m")

    parser.add_argument("--offsetUTMy",
                        type=float,
                        default=0,
                        help="offset UTM vers Nord en m")

    parser.add_argument("--altitakeoff",
                        default=None,
                        help="altitude du point de decollage")

    add_bool_arg(parser, "verbose", False, "mode verbose")
    add_bool_arg(parser, "tag_img", False, "ajouter tag image")
    add_bool_arg(parser, "graphic_3D", True, "graphic 3D MNT")
    add_bool_arg(parser, "graphic_2D", True, "graphic 2D Grid MNT")
    add_bool_arg(parser, "graphic_ortho", False, "image ortho dng")
    add_bool_arg(parser, "view_graphic", False, "show graphic")
    add_bool_arg(parser, "save_graphic", True, "save graphic")
    add_bool_arg(parser, "comp_error_rms", False, "calcul erreur position")
    add_bool_arg(parser, "carte_topo", True, "carte topographique")
    add_bool_arg(parser, "raster_topo", False, "raster topographique")


    args = parser.parse_args()
    return args

def calib_cam_DJI():
    zhang_dic = {
        "mtx": [
            [2898.4683237896006, 0.0, 2032.1512913688591],
            [0.0, 2898.600429204581, 1510.6273628340032],
            [0.0, 0.0, 1.0]
        ],
        "dist": [[
            0.18456929958351967,
            -0.45530898548721,
            0.0002736394422800173,
            0.00012010401446102354,
            0.24480724034299267
        ]],
        "size": [3992, 2992],
        "camera": "DJI_RAW"
    }

    return zhang_dic

# -----------------------------------------------------------------
#   détection automatique du mode de traitement
#    > "raw_DJI" :    raw dng du DJI
#    > "miltispectral" : quadruplet R\G\B\NIR de tif de IRDrone
# ------------------------------------------------------------------

def detect_mode(paths, args_mode):

    if not paths:
        raise ValueError("Aucun fichier fourni")

    suffixes = {p.suffix.lower() for p in paths}

    has_dng = any(s == ".dng" for s in suffixes)
    has_tif = any(s in [".tif", ".tiff"] for s in suffixes)

    # --- cas invalide : mélange ---
    if has_dng and has_tif:
        raise ValueError(
            "Mélange de fichiers DNG et TIF détecté.\n"
            "Veuillez sélectionner uniquement des images RAW DJI (.dng)\n"
            "ou uniquement des images multispectrales (.tif)."
        )


    # --- cas RAW DJI ---
    if has_dng:
        return "raw_DJI"

    # --- cas multispectral ---
    if has_tif:
        return "multispectral"

    # --- cas non supporté ---
    raise ValueError(f"Format non supporté : {suffixes}")

# --------------------------------------------------
# traitement d'une image
# --------------------------------------------------

def process_image(folder_input, img_name, args, zhang_dic,  tol_MC=0.01, img_override=None, tif_override=None, logger=None, georef_success=0):


    geo_ref_dir = folder_input / "geo_ref"

    if not geo_ref_dir.exists():
        geo_ref_dir.mkdir(parents=True, exist_ok=True)
        logger.ok(f"Création du dossier : {geo_ref_dir}")

    if args.mode == "raw_DJI":
        logger.info(f"--- Traitement {img_name}.{args.suffix}")
        geo_tif = folder_input / "geo_ref" / f"{img_name}_geo.tif"

    elif args.mode == "multispectral":
        base_name = img_name.rsplit("_", 1)[0]  # enlève _1 de la bande N°1
        logger.info(f"--- Traitement {base_name}")
        geo_tif = folder_input / "geo_ref" / f"{base_name}_0_geo.tif"

    try:

        if img_override is not None:
            # --- multispectral : image déjà chargée ---
            img = img_override
            tif_path = None  # ⚠️ pas de fichier source

        else:
            # --- mode raw_DJI --- seul le nom de l'image est chargé à ce stade
            if args.suffix.lower() == "dng":
                tif_path = dng2tiff(folder_input, img_name)  # création d'une image .tif à partie de l'image .dng
            elif args.suffix.lower() == "tif":
                logger.warn(f'  le suffix {args.suffix} n\'est pas pris en charge en mode raw DJI')
                sys.exit(1)
            else:
                logger.error(f' le suffix {args.suffix} n\'est pas pris en charge.')
                sys.exit(1)

            img = cv2.imread(str(tif_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                raise FileNotFoundError(tif_path)

        # --- recherche des données exif essentielles pour le géoréférencement et l'orthorectification.
        # Coordonnées GPS de la prise de vue, attitude du drone (Yaw), altitude takeoff, altitude du nadir.

        raw_exif = load_companion_exif(folder_input, img_name, suffix=args.suffix, alti_takeoff=args.altitakeoff)

        if raw_exif is None:
            raise RuntimeError("EXIF manquant")

        tif_ref = tif_override if tif_override is not None else tif_path

        output_name = img_name

        if args.mode == "multispectral":
            output_name = base_name + "_0"  # le nom est construit en remplaçant le numéro de bande spectrale (1,2,3,4) par 0

        new_geo_path = \
            georeference_tiff_MNT(
            tif_ref,
            raw_exif,
            geo_tif,
            folder_input,
            output_name,
            offset_xi_Y=np.deg2rad(args.offsetyaw),
            offsetUTMx=args.offsetUTMx,
            offsetUTMy=args.offsetUTMy,
            zhang_dic=zhang_dic,
            cache=False,
            verbose=args.verbose,
            tag_img=args.tag_img,
            bitdepth=args.bitdepth,
            graphic_3D=args.graphic_3D,
            graphic_2D=args.graphic_2D,
            graphic_ortho=args.graphic_ortho,
            view_graphic=args.view_graphic,
            save_graphic=args.save_graphic,
            comp_error_rms=args.comp_error_rms,
            tol_MC=tol_MC,
            topo_style=args.topo_style,
            raster_topo=args.raster_topo,
            carte_topo=args.carte_topo,
            img_override=img,
        )

        if new_geo_path:
            georef_success += 1
            logger.ok(f"{georef_success} géoréférencement terminé : {new_geo_path}")

        else:
            logger.warn(f" Process terminé sans génération du fichier georef")
        return georef_success

    except Exception as e:

        # import traceback
        logger.error(f" Erreur sur {img_name}: {e}")
        # traceback.print_exc()

# -----------------------------------------------------------------------
# process multispectral
# -----------------------------------------------------------------------

def process_multispectral(folder_input, base, band_paths, args, zhang_dic, tol_MC=0.01, georef_success=0):

    # --- sécurité ---
    expected = {1, 2, 3, 4}
    if set(band_paths.keys()) != expected:
        raise ValueError(f"{base} bandes invalides : {band_paths.keys()}")

    # --- lecture des 4 bandes spectrales séparées ---
    img_r = cv2.imread(str(band_paths[1]), cv2.IMREAD_UNCHANGED)
    img_g = cv2.imread(str(band_paths[2]), cv2.IMREAD_UNCHANGED)
    img_b = cv2.imread(str(band_paths[3]), cv2.IMREAD_UNCHANGED)
    img_nir = cv2.imread(str(band_paths[4]), cv2.IMREAD_UNCHANGED)

    # --- validation dimensions des bandes ---
    if not (img_r.shape == img_g.shape == img_b.shape == img_nir.shape):
        raise ValueError(f"{base} bandes spectrales incohérentes")

    # --- stack ---
    # normalisation globale des 4 bandes spectrales
    def normalize(img):
        return (img - img.min()) / (img.max() - img.min() + 1e-6)

    img_r = normalize(img_r)
    img_g = normalize(img_g)
    img_b = normalize(img_b)
    img_nir = normalize(img_nir)

    # image multispectrale   R|G|B|NIR

    img = np.stack([img_r, img_g, img_b, img_nir], axis=-1)

    # --- suffix pour sortie compatible georef QGIS---
    args.suffix = "tif"

    ref_path = band_paths[1]  # ex: HYPERLAPSE_0271_1.tif
    ref_name = ref_path.stem  # ex: HYPERLAPSE_0271_1

    # --- pipeline ---
    georef_success = process_image(
                                    folder_input,
                                    ref_name,
                                    args,
                                    zhang_dic,
                                    logger=logger,
                                    tol_MC=tol_MC,
                                    img_override=img,  # injection directe de l'image 4 couches
                                    georef_success=georef_success
                                )
    return georef_success

def group_multispectral(paths, logger):
    pattern = re.compile(r"(.+?)_(\d)\.(tif|tiff)$", re.IGNORECASE)

    groups = defaultdict(dict)

    for p in paths:
        m = pattern.match(p.name)
        if not m:
            continue

        base, band, _ = m.groups()
        groups[base][int(band)] = p

    valid = {}
    rejected = {}

    for base, bands in groups.items():
        if set(bands.keys()) == {1, 2, 3, 4}:
            valid[base] = bands
        else:
            rejected[base] = bands
            logger.warn(f"{base} rejeté. Bandes présentes: {sorted(bands.keys())}")

    logger.info(f'quadruplets valides = {len(valid)}')
    if len(rejected) != 0: logger.warn(f'quadruplets rejetés = {rejected}')

    return valid, rejected


def georef_main(image_callback=None, mission_parameters=None):
    logger = CliLogger(use_color=True)
    logger.log_callback = globals()["logger"].log_callback


    args = parse_args()  # arguments ligne de commande

    zhang_dic = calib_cam_DJI()  # calibration caméra DJI

    tolerence_Monte_Carlo = 0.0025

    # ==================================================
    # MODE LIGNE DE COMMANDE
    # ==================================================
    if args.input_dir:

        folder_input = Path(args.input_dir)

        if not folder_input.exists() or not folder_input.is_dir():
            logger.error(f"Dossier invalide : {folder_input}")
            sys.exit(1)

        # ----------------------------------------------
        # Construction de paths
        # ----------------------------------------------
        if args.images:
            paths = []

            for name in args.images:
                # --- test DNG ---
                if args.mode == "raw_DJI":
                    dng_path = folder_input / f"{name}.dng"
                    if dng_path.exists():
                        paths.append(dng_path)
                        continue

                # --- test multispectral ---
                elif args.mode == "multispectral":
                    for i in range(1, 5):
                        tif_path = folder_input / f"{name}_{i}.tif"
                        if tif_path.exists():
                            paths.append(tif_path)
                else:
                    pass

            if not paths:
                logger.error("Aucune image trouvée correspondant à --images")
                sys.exit(1)

        else:
            # scan auto
            logger.info(f'Scan automatique du dossier {folder_input}')
            paths = (
                    list(folder_input.glob("*.dng")) +
                    list(folder_input.glob("*.tif")) +
                    list(folder_input.glob("*.tiff"))
            )

        if not paths:
            logger.error("Aucune image trouvée dans le dossier")
            sys.exit(1)

        # ----------------------------------------------
        # Détection du mode
        # ----------------------------------------------

        try:
            mode = detect_mode(paths, args.mode)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        logger.info(f"Mode détecté : {mode}")

        # ----------------------------------------------
        # RAW DJI
        # ----------------------------------------------
        if mode == "raw_DJI":

            list_img_name = sorted(p.stem for p in paths if p.suffix.lower() == ".dng")

            logger.info(f"{len(list_img_name)} images DNG à traiter")
            georef_sucsess = 0
            for img_name in list_img_name:
                georef_success = process_image(
                                            folder_input,
                                            img_name,
                                            args,
                                            zhang_dic,
                                            logger=logger,
                                            tol_MC=tolerence_Monte_Carlo,
                                            georef_sucsess=georef_unsucces
                                        )
            Uti.show_info_message("IRDrone", f"{georef_success }image géoréférencée avec succes ...", "")


        # ----------------------------------------------
        # MULTISPECTRAL
        # ----------------------------------------------
        elif mode == "multispectral":

            tif_paths = [p for p in paths if p.suffix.lower() in [".tif", ".tiff"]]

            valid, rejected = group_multispectral(tif_paths, logger)

            for base, bands in valid.items():
                process_multispectral(
                    folder_input,
                    base,
                    bands,
                    args,
                    zhang_dic,
                    tolerence_Monte_Carlo
                )

    # ==================================================
    # MODE INTERACTIF
    # ==================================================
    else:

        logger.info(f"Mode interactif : sélection des images ...\n", _bold=True)

        folder_mission = Path(
            mission_parameters["File path mission"]
        )

        folder_input, list_img_name, list_img, list_path = choose_images(
            folder_mission
        )

        if not list_path:
            logger.error("Aucune image sélectionnée")
            sys.exit(1)

        try:
            args.mode = None
            mode = detect_mode(list_path, args.mode)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        # --- réglages developpement ---
        if args.offsetyaw == 0:
            args.offsetyaw = 6.
        if args.offsetUTMx == 0:
            args.offsetUTMx = - 3.8
        if args.offsetUTMy == 0:
            args.offsetUTMy = 3.8
        logger.warn(
            f'forcage des arguments pour le développement ...\n'
            f'      offset yaw = {args.offsetyaw}°\n'
            f'      offset UTM vers Est = {args.offsetUTMx} m\n'
            f'      offset UTM vers Nord = {args.offsetUTMy} m\n'
        )

        logger.info(f"Mode détecté : {mode}")

        # ----------------------------------------------
        # RAW DJI
        # ----------------------------------------------
        if mode == "raw_DJI":
            args.mode = "raw_DJI"
            args.suffix = "dng"
            logger.info(f'Dossier : {folder_input}')
            logger.info(f'{len(list_img_name)} images à traiter : {list_img_name}')

            args.comp_error_rms = False

            georef_success = 0

            for img_path in list_path:
                img_name = img_path.stem

                # gestion de l'affichage de l'image à géoréferencée. Envoie du chemin
                if image_callback is not None:
                    image_callback(str(img_path))


                georef_success = process_image(
                                                folder_input,
                                                img_name,
                                                args,
                                                zhang_dic,
                                                logger=logger,
                                                tol_MC=tolerence_Monte_Carlo,
                                                georef_success=georef_success
                                            )
            Uti.show_info_message("IRDrone", f"{georef_success} images géoréférencées avec succes ...", "")

        # ----------------------------------------------
        # MULTISPECTRAL
        # ----------------------------------------------
        elif mode == "multispectral":
            args.mode = "multispectral"
            valid, rejected = group_multispectral(list_path, logger)
            logger.info(f"list_path : {list_path}")
            georef_success = 0

            for base, bands in valid.items():
                logger.info(f"Traitement multispectral : {base}")

                # Display the red spectral band in the GUI preview.
                if image_callback is not None:
                    red_band_path = bands[1]
                    image_callback(str(red_band_path))


                georef_success = process_multispectral(
                                                        folder_input,
                                                        base,
                                                        bands,
                                                        args,
                                                        zhang_dic,
                                                        tolerence_Monte_Carlo,
                                                        georef_success=georef_success
                                                    )

            Uti.show_info_message("IRDrone", f"{georef_success} images multispectrales géoréférencées avec succes ...", "")


# ================================================================
# programme principal pour le développement
# ou utilisation en ligne de commande.
# ================================================================

if __name__ == "__main__":

    logger = CliLogger(use_color=True)

    args = parse_args()  # arguments ligne de commande

    zhang_dic = calib_cam_DJI()   # calibration caméra DJI

    tolerence_Monte_Carlo = 0.0025

    # ==================================================
    # MODE LIGNE DE COMMANDE
    # ==================================================
    if args.input_dir:

        folder_input = Path(args.input_dir)

        if not folder_input.exists() or not folder_input.is_dir():
            logger.error(f"Dossier invalide : {folder_input}")
            sys.exit(1)

        # ----------------------------------------------
        # Construction de paths
        # ----------------------------------------------
        if args.images:
            paths = []

            for name in args.images:
                # --- test DNG ---
                if args.mode == "raw_DJI":
                    dng_path = folder_input / f"{name}.dng"
                    if dng_path.exists():
                        paths.append(dng_path)
                        continue

                # --- test multispectral ---
                elif args.mode == "multispectral":
                    for i in range(1, 5):
                        tif_path = folder_input / f"{name}_{i}.tif"
                        if tif_path.exists():
                            paths.append(tif_path)
                else:
                    pass

            if not paths:
                logger.error("Aucune image trouvée correspondant à --images")
                sys.exit(1)

        else:
            # scan auto
            logger.info(f'Scan automatique du dossier {folder_input}')
            paths = (
                list(folder_input.glob("*.dng")) +
                list(folder_input.glob("*.tif")) +
                list(folder_input.glob("*.tiff"))
            )

        if not paths:
            logger.error("Aucune image trouvée dans le dossier")
            sys.exit(1)


        # ----------------------------------------------
        # Détection du mode
        # ----------------------------------------------


        try:
            mode = detect_mode(paths, args.mode)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)
        logger.info(f"Mode détecté : {mode}")

        # ----------------------------------------------
        # RAW DJI
        # ----------------------------------------------
        if mode == "raw_DJI":

            list_img_name = sorted(p.stem for p in paths if p.suffix.lower() == ".dng")

            logger.info(f"{len(list_img_name)} images DNG à traiter")

            georef_success = 0

            for img_name in list_img_name:
                georef_success = process_image(
                                                folder_input,
                                                img_name,
                                                args,
                                                zhang_dic,
                                                logger=logger,
                                                tol_MC=tolerence_Monte_Carlo,
                                                georef_success=georef_success
                                            )

            Uti.show_info_message("IRDrone", f"{georef_success} images géoréférencées avec succes ...", "")

        # ----------------------------------------------
        # MULTISPECTRAL
        # ----------------------------------------------
        elif mode == "multispectral":

            tif_paths = [p for p in paths if p.suffix.lower() in [".tif", ".tiff"]]

            valid, rejected = group_multispectral(tif_paths, logger)

            georef_success = 0

            for base, bands in valid.items():

                georef_success = process_multispectral(
                                                    folder_input,
                                                    base,
                                                    bands,
                                                    args,
                                                    zhang_dic,
                                                    tolerence_Monte_Carlo,
                                                    georef_success=georef_success
                                                )
            Uti.show_info_message("IRDrone", f"{georef_success} images géoréférencées avec succes ...", "")

    # ==================================================
    # MODE INTERACTIF
    # ==================================================
    else:

        logger.info(f"Mode interactif : sélection des images ...\n", _bold=True)

        folder_input, list_img_name, list_img, list_path = choose_images_dev()

        if not list_path:
            logger.error("Aucune image sélectionnée")
            sys.exit(1)

        try:
            args.mode = None
            mode = detect_mode(list_path, args.mode)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        # --- réglages developpement ---
        if args.offsetyaw == 0:
            args.offsetyaw = 6.
        if args.offsetUTMx == 0:
            args.offsetUTMx = - 3.8
        if args.offsetUTMy == 0:
            args.offsetUTMy = 3.8
        logger.warn(
            f'forcage des arguments pour le développement ...\n'
            f'      offset yaw = {args.offsetyaw}°\n'
            f'      offset UTM vers Est = {args.offsetUTMx} m\n'
            f'      offset UTM vers Nord = {args.offsetUTMy} m\n'
        )


        logger.info(f"Mode détecté : {mode}")


        # ----------------------------------------------
        # RAW DJI
        # ----------------------------------------------
        if mode == "raw_DJI":
            args.mode = "raw_DJI"
            args.suffix = "dng"
            logger.info(f'Dossier : {folder_input}')
            logger.info(f'{len(list_img_name)} images à traiter : {list_img_name}')

            args.comp_error_rms = False

            georef_success = 0

            for img_path in list_path:
                img_name = img_path.stem

                georef_success = process_image(
                                                folder_input,
                                                img_name,
                                                args,
                                                zhang_dic,
                                                logger=logger,
                                                tol_MC=tolerence_Monte_Carlo,
                                                georef_success=georef_success
                                            )

        # ----------------------------------------------
        # MULTISPECTRAL
        # ----------------------------------------------
        elif mode == "multispectral":
            args.mode = "multispectral"
            valid, rejected = group_multispectral(list_path, logger)

            georef_success = 0

            for base, bands in valid.items():
                logger.info(f"Traitement multispectral : {base}")

                georef_success = process_multispectral(
                                                        folder_input,
                                                        base,
                                                        bands,
                                                        args,
                                                        zhang_dic,
                                                        tolerence_Monte_Carlo,
                                                        georef_success=georef_success
                                                    )

    sys.exit(0)





