# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   parallel processing with interactive windows.
#   20/10/2026   V003
# ---------------------------------------------------------------------------------

from typing import Any, Dict, Optional, Tuple, List, Union, Callable
import sys
import os
import os.path as osp
from pathlib import Path
import shutil
import json
import numpy as np
from datetime import date, time, datetime
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import threading
import subprocess
import psutil
import piexif
# -------------------- Image Library ------------------------------
import rawpy
import imageio
# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QFileDialog, QWidget,  QLineEdit, QFrame,  QPushButton,\
                            QProgressBar, QHBoxLayout,  QVBoxLayout, QLabel, QMessageBox, QDialog
from PyQt6.QtGui import QPixmap, QImage, QColor, QIcon, QRegularExpressionValidator
from PyQt6 import QtCore
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression, QUrl, QObject, pyqtSignal, QRunnable, QThreadPool

import matplotlib.pyplot as plt

# -------------- IRDrone Library ------------------------------------
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import interpolate_scalar_with_extrapolation
from IRD_Interactive_utils import safe_path
import IRD_interactive_geo as Geo
from IRD_Interactive_color_style import Style
import IRD_Interactive_ArUco as Aru
from config import SJCONVERTERPATH, EXIFTOOLPATH
assert Path(EXIFTOOLPATH).exists(), f"ExifTool not found at {EXIFTOOLPATH}, Use environment variable EXIFTOOLPATH to set the path."
assert Path(SJCONVERTERPATH).exists(), f"SJCam RAW converter not found at {SJCONVERTERPATH}, Use environment variable SJCONVERTERPATH to set the path."


# --------------------------------------------------------------------------------------------
#
#    Class for parallel processing with interactive windows.
#
# --------------------------------------------------------------------------------------------


class ImagePairingWorkerSignals(QObject):
    """Define the signals emitted by the image-pairing worker."""

    progress = pyqtSignal(int)   # Processing progress, expressed as a percentage.
    stage = pyqtSignal(str)      # Description of the current processing stage.
    finished = pyqtSignal(dict)  # Complete image-pairing result.
    error = pyqtSignal(str)      # Error message raised during processing.


class ImagePairingWorker(QRunnable):
    """
    Pair VIS images with their two nearest NIR images in time.

    The VIS timeline is used as the temporal reference. The NIR timeline is
    shifted by ``time_shift`` before image pairing and metadata interpolation.

    For each VIS image, the two NIR images with the smallest absolute time
    differences are selected. The signed time difference is defined as:

        dt = t_NIR_shifted - t_VIS

    Therefore:
        dt < 0: the NIR acquisition precedes the VIS acquisition.
        dt > 0: the NIR acquisition follows the VIS acquisition.
        dt = 0: both acquisitions have the same relative timestamp.

    NIR metadata are subsequently interpolated from the VIS timeline.
    Angular variables are interpolated along the shortest angular path.

    Parameters
    ----------
    time_shift : float
        Time correction applied to every NIR timestamp, in the same time
        units as the relative timelines.
    folderMissionPath : Path
        Root directory of the mission.
    control_mode : bool, optional
        If True, store additional interpolation-method information in the
        resulting NIR metadata. Defaults to False.
    """

    def __init__(
        self,
        time_shift: float,
        folderMissionPath: Path,
        control_mode: bool = False,
    ):
        """Initialize the worker and its processing state."""
        super().__init__()
        QObject.__init__(self)

        self.time_shift = time_shift
        self.folderMissionPath = safe_path(folderMissionPath)
        self.control_mode = control_mode

        self.dics_VIS = None
        self.dics_NIR = None
        self.time_line_VIS = None
        self.time_line_NIR = None

        self.signals = ImagePairingWorkerSignals()

    def run(self):
        """
        Execute the complete image-pairing workflow.

        The worker loads the VIS and NIR metadata, constructs image pairs,
        builds the shoot-point records, interpolates NIR metadata, saves the
        JSON result, and emits the completion signal.

        Any exception is printed to the console and reported through the
        error signal.
        """
        try:
            self.signals.stage.emit("Image pairing – initializing")
            self.signals.progress.emit(1)

            # Load VIS and NIR metadata and their relative timelines.
            self.dics_VIS, self.time_line_VIS = self.load_images_exif(
                safe_path(
                    self.folderMissionPath
                    / "AerialPhotography"
                    / "VIS"
                ),
                "dng",
            )
            self.dics_NIR, self.time_line_NIR = self.load_images_exif(
                safe_path(
                    self.folderMissionPath
                    / "AerialPhotography"
                    / "NIR"
                ),
                "dng",
            )

            # Select the two nearest NIR images for each VIS image.
            pairs = self.pairing_img()

            # Build the shoot-point structure from the selected images.
            shoot_points = self.build_shoot_points(
                pairs,
                self.dics_VIS,
                self.dics_NIR,
            )

            # Build the result structure before adding interpolated NIR data.
            pairing_result = self.build_pairing_result(shoot_points)

            # Interpolate each selected VIS metadata variable at NIR times.
            for key in self.build_list_interpol_key():
                self.interpolate_nir_scalar(shoot_points, key)

            # Save the pairing result as a JSON file.
            if pairing_result is None:
                pairing_result = {}

            self.save_shoot_points(pairing_result)

            self.signals.progress.emit(100)
            self.signals.stage.emit("Image pairing – completed")
            self.signals.finished.emit(pairing_result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.error.emit(str(e))

    def pairing_img(self):
        """
        Find the two temporally nearest NIR images for every VIS image.

        The NIR timestamps are corrected before the comparison:

            t_NIR_shifted = t_NIR + time_shift

        For each VIS timestamp, the method computes the absolute difference
        from every corrected NIR timestamp and selects the two smallest
        differences. The rank-1 NIR image is the closest; rank 2 is the
        second closest.

        The absolute differences are used only to rank the candidates.
        The returned ``dt_1`` and ``dt_2`` values are signed and follow this
        convention:

            dt = t_NIR_shifted - t_VIS

        A negative value means that NIR precedes VIS; a positive value means
        that NIR follows VIS; zero means simultaneous relative timestamps.

        The same NIR image may be selected for more than one VIS image.
        This method does not enforce one-to-one pairing or impose a maximum
        permitted time difference.

        Returns
        -------
        list of dict
            One dictionary per VIS image, containing its index and timestamp,
            the indices and corrected timestamps of the two selected NIR
            images, and their signed time differences.
        """
        t_VIS = np.array(self.time_line_VIS)
        t_NIR = np.array(self.time_line_NIR) + self.time_shift
        n_VIS = len(t_VIS)
        n_NIR = len(t_NIR)

        # Compute every absolute VIS-to-NIR time difference.
        # Shape: (number of VIS images, number of NIR images).
        dt_matrix = np.abs(t_VIS[:, None] - t_NIR[None, :])

        # Sort NIR candidates independently for each VIS image.
        # The first two indices correspond to the smallest absolute differences.
        nearest_idx = np.argsort(dt_matrix, axis=1)[:, :2]
        nearest_dt = np.take_along_axis(dt_matrix, nearest_idx, axis=1)

        pairs = []
        for i in range(n_VIS):
            idx_1 = int(nearest_idx[i, 0])
            idx_2 = int(nearest_idx[i, 1])

            pairs.append({
                "idx_VIS": i,
                "idx_NIR_1": idx_1,
                "idx_NIR_2": idx_2,
                "t_VIS": float(t_VIS[i]),
                "t_NIR_1_shifted": float(t_NIR[idx_1]),
                "t_NIR_2_shifted": float(t_NIR[idx_2]),

                # Signed time differences: corrected NIR time minus VIS time.
                "dt_1": float(t_NIR[idx_1] - t_VIS[i]),
                "dt_2": float(t_NIR[idx_2] - t_VIS[i]),
            })

            # Update progress during the pairing step.
            percent = int((i + 1) / max(1, n_VIS) * 100)
            self.signals.progress.emit(percent)
            self.signals.stage.emit("Pairing images")

        return pairs

    def load_images_exif(self, folder: Path, suffix: str = "dng"):
        """
        Load metadata from the EXIF sidecar files associated with images.

        Image files matching ``*.suffix`` are sorted by filename. For each
        image, the corresponding ``.exif`` file is loaded if it exists.
        The metadata dictionaries and their ``RelativeTimeLine`` values are
        returned in matching list order.

        If ``RelativeTimeLine`` cannot be converted to a float, it is replaced
        with 0.0. Images without an existing sidecar file are skipped.

        Parameters
        ----------
        folder : Path
            Directory containing the images and their EXIF sidecar files.
        suffix : str, optional
            Image filename extension without the leading dot. Defaults to
            ``"dng"``.

        Returns
        -------
        tuple[list[dict], list[float]]
            The loaded metadata dictionaries and their relative timestamps.
        """
        folder = Path(folder)
        list_dic = []
        time_line = []
        files = sorted(folder.glob(f"*.{suffix}"))
        n_files = len(files)

        for i, img_file in enumerate(files):
            exif_file = folder / f"{img_file.stem}.exif"
            if exif_file.exists():
                with open(exif_file, "r") as f:
                    dic = json.load(f)
                    list_dic.append(dic)

                    t = dic.get("RelativeTimeLine", 0.0)
                    try:
                        t = float(t)
                    except (ValueError, TypeError):
                        t = 0.0
                    time_line.append(t)

            # Update progress while loading this image folder.
            percent = int((i + 1) / max(1, n_files) * 100)
            self.signals.progress.emit(percent)
            self.signals.stage.emit(f"Loading {suffix.upper()} images")

        return list_dic, time_line

    def build_pairing_result(self, shoot_points):
        """
        Assemble the metadata describing the pairing operation.

        Parameters
        ----------
        shoot_points : list[dict]
            Shoot-point records containing each VIS image and its two
            selected NIR images.

        Returns
        -------
        dict
            The mission path, time correction, image counts, pairing method,
            creation timestamp, schema version, and shoot-point records.
        """
        pairing_result = {
            "mission_path": str(self.folderMissionPath),
            "time_shift": self.time_shift,
            "n_VIS": len(self.dics_VIS),
            "n_NIR": len(self.dics_NIR),
            "pairing_method": "nearest_time",
            "created_at": datetime.utcnow().isoformat(),
            "schema_version": "1.0",
            "shoot_points": shoot_points,
        }
        return pairing_result

    def build_shoot_points(self, pairs, dics_VIS, dics_NIR):
        """
        Build one shoot-point record for each VIS image.

        Each record contains the selected VIS metadata and a list of two NIR
        records, ordered by temporal proximity. The NIR records include their
        corrected relative timestamps and signed time differences.

        Parameters
        ----------
        pairs : list[dict]
            Pairing information returned by ``pairing_img``.
        dics_VIS : list[dict]
            VIS metadata dictionaries.
        dics_NIR : list[dict]
            NIR metadata dictionaries.

        Returns
        -------
        list[dict]
            Shoot-point records containing VIS metadata and two NIR entries.
        """
        shoot_points = []
        try:
            for p in pairs:
                i_VIS = p["idx_VIS"]
                i_NIR_1 = p["idx_NIR_1"]
                i_NIR_2 = p["idx_NIR_2"]

                dic_VIS = dics_VIS[i_VIS]
                dic_NIR_1 = dics_NIR[i_NIR_1]
                dic_NIR_2 = dics_NIR[i_NIR_2]

                shoot_point = {
                    "VIS": {
                        "idx": i_VIS,
                        "FileName": dic_VIS.get("FileName"),
                        "Directory": dic_VIS.get("Directory"),
                        "DateTimeOriginal": dic_VIS.get("DateTimeOriginal"),
                        "RelativeTimeLine": dic_VIS.get("RelativeTimeLine"),

                        "DroneLatitude": dic_VIS.get("DroneLatitude"),
                        "DroneLongitude": dic_VIS.get("DroneLongitude"),
                        "GroundAltitude": dic_VIS.get("GroundAltitude"),
                        "DroneAltitudeSeaLevel": dic_VIS.get("DroneAltitudeSeaLevel"),
                        "DroneAltitudeGround": dic_VIS.get("DroneAltitudeGround"),
                        "UTM_x": dic_VIS.get("UTM_x"),
                        "UTM_y": dic_VIS.get("UTM_y"),
                        "UTM_zone": dic_VIS.get("UTM_zone"),

                        "FlightYawDegree": dic_VIS.get("FlightYawDegree"),
                        "FlightPitchDegree": dic_VIS.get("FlightPitchDegree"),
                        "FlightRollDegree": dic_VIS.get("FlightRollDegree"),
                        "GimbalYawDegree": dic_VIS.get("GimbalYawDegree"),
                        "GimbalPitchDegree": dic_VIS.get("GimbalPitchDegree"),
                        "GimbalRollDegree": dic_VIS.get("GimbalRollDegree"),

                        "DistanceToLastPoint": dic_VIS.get("DistanceToLastPoint"),
                        "CapToLastPoint": dic_VIS.get("CapToLastPoint"),
                        "CumulDistance": dic_VIS.get("CumulDistance"),
                    },
                    "NIR": [
                        {
                            "rank": 1,
                            "idx": i_NIR_1,
                            "FileName": dic_NIR_1.get("FileName"),
                            "Directory": dic_NIR_1.get("Directory"),
                            "DateTimeOriginal": dic_NIR_1.get("DateTimeOriginal"),
                            "RelativeTimeLine_shifted": p["t_NIR_1_shifted"],
                            "dt": p["dt_1"],
                        },
                        {
                            "rank": 2,
                            "idx": i_NIR_2,
                            "FileName": dic_NIR_2.get("FileName"),
                            "Directory": dic_NIR_2.get("Directory"),
                            "DateTimeOriginal": dic_NIR_2.get("DateTimeOriginal"),
                            "RelativeTimeLine_shifted": p["t_NIR_2_shifted"],
                            "dt": p["dt_2"],
                        },
                    ],
                }

                shoot_points.append(shoot_point)
        except Exception as e:
            print(f"Error in build_shoot_points: {e}")

        return shoot_points

    def prepare_vis_arrays(self, shoot_points, key):
        """
        Prepare the VIS timestamps and values used for NIR interpolation.

        Missing values for the requested variable and for
        ``RelativeTimeLine`` are replaced by the previous valid value.
        If no previous value exists, 0.0 is used.

        Parameters
        ----------
        shoot_points : list[dict]
            Shoot-point records containing VIS metadata.
        key : str
            Name of the VIS metadata field to prepare.

        Returns
        -------
        tuple[numpy.ndarray, numpy.ndarray]
            The VIS relative timestamps and the corresponding numeric values.
        """
        cleaned_values = []
        for sp in shoot_points:
            value = sp["VIS"].get(key)
            if value is None:
                # Use the previous valid value, or 0.0 if none is available.
                value = cleaned_values[-1] if cleaned_values else 0.0
            cleaned_values.append(float(value))

        x_vis = np.array(cleaned_values, dtype=float)

        cleaned_values = []
        for sp in shoot_points:
            value = sp["VIS"].get("RelativeTimeLine")
            if value is None:
                # Use the previous valid value, or 0.0 if none is available.
                value = cleaned_values[-1] if cleaned_values else 0.0
            cleaned_values.append(float(value))

        t_vis = np.array(cleaned_values, dtype=float)
        return t_vis, x_vis

    def interpolate_nir_scalar(self, shoot_points, key):
        """
        Interpolate VIS metadata values at the corrected NIR timestamps.

        The VIS timeline provides the reference values. For each NIR record,
        the method locates the surrounding VIS timestamps and computes the
        interpolation coefficient:

            alpha = (t_NIR - t0) / (t1 - t0)

        For timestamps outside the VIS time range, alpha is clipped to [0, 1].
        Consequently, the nearest endpoint value is used rather than a
        mathematical extrapolation beyond the available VIS data.

        Angular variables are interpolated along the shortest angular path:
        ``FlightYawDegree`` and ``GimbalYawDegree`` are normalized to
        [-180, 180), whereas ``CapToLastPoint`` is normalized to [0, 360).
        All other variables use linear interpolation.

        Parameters
        ----------
        shoot_points : list[dict]
            Shoot-point records whose NIR entries receive interpolated values.
        key : str
            Name of the VIS metadata field to interpolate.
        """
        t_vis, x_vis = self.prepare_vis_arrays(shoot_points, key)

        # Collect all corrected NIR timestamps and their destination indices.
        t_nir_list = []
        nir_refs = []  # (shoot-point index, NIR-record index)
        for sp_idx, sp in enumerate(shoot_points):
            for nir_idx, nir in enumerate(sp["NIR"]):
                t_nir_list.append(float(nir["RelativeTimeLine_shifted"]))
                nir_refs.append((sp_idx, nir_idx))

        t_nir_arr = np.array(t_nir_list, dtype=float)

        # Find the VIS indices bracketing each NIR timestamp.
        idx_upper = np.searchsorted(t_vis, t_nir_arr, side="right")
        idx_lower = idx_upper - 1

        # Clamp indices to the first or last VIS sample at the boundaries.
        idx_lower[idx_lower < 0] = 0
        idx_upper[idx_upper >= len(t_vis)] = len(t_vis) - 1

        t0 = t_vis[idx_lower]
        t1 = t_vis[idx_upper]
        x0 = x_vis[idx_lower]
        x1 = x_vis[idx_upper]

        # Calculate interpolation coefficients.
        with np.errstate(divide="ignore", invalid="ignore"):
            alpha = (t_nir_arr - t0) / (t1 - t0)
            alpha[np.isnan(alpha)] = 0.0  # Handle identical adjacent timestamps.
            alpha = np.clip(alpha, 0, 1)  # Hold endpoint values outside the range.

        # Interpolate cyclic angles along the shortest angular path.
        cyclic_angle_keys_1 = {
            "FlightYawDegree",
            "GimbalYawDegree",
        }
        cyclic_angle_keys_2 = {
            "CapToLastPoint",
        }

        if key in cyclic_angle_keys_1:
            # Normalize angles to the range [-180°, 180°).
            delta = ((x1 - x0 + 180.0) % 360.0) - 180.0
            values = (x0 + alpha * delta) % 360.0
            values = ((values + 180.0) % 360.0) - 180.0

        elif key in cyclic_angle_keys_2:
            # Normalize angles to the range [0°, 360°).
            delta = ((x1 - x0 + 180.0) % 360.0) - 180.0
            values = (x0 + alpha * delta) % 360.0

        else:
            # Use ordinary linear interpolation for non-angular variables.
            values = (1 - alpha) * x0 + alpha * x1

        # Identify whether each NIR timestamp lies inside or outside the
        # VIS timeline. These labels are diagnostic metadata only.
        methods = np.where(
            t_nir_arr < t_vis[0],
            "extrap_before",
            np.where(
                t_nir_arr > t_vis[-1],
                "extrap_after",
                "linear_VIS",
            ),
        )

        # Store the interpolated values in their corresponding NIR records.
        for (sp_idx, nir_idx), val, mode in zip(nir_refs, values, methods):
            nir = shoot_points[sp_idx]["NIR"][nir_idx]
            nir.setdefault("Interpolated", {})
            nir["Interpolated"][key] = val

            if self.control_mode:
                nir["Interpolated"][f"{key}_method"] = mode

    def build_list_interpol_key(self):
        """
        Return the VIS metadata fields interpolated for the NIR records.

        Returns
        -------
        list[str]
            Names of the numeric metadata fields processed by
            ``interpolate_nir_scalar``.
        """
        list_key = [
            "DroneLatitude",
            "DroneLongitude",
            "GroundAltitude",
            "DroneAltitudeSeaLevel",
            "DroneAltitudeGround",
            "UTM_x",
            "UTM_y",
            "FlightYawDegree",
            "FlightPitchDegree",
            "FlightRollDegree",
            "GimbalYawDegree",
            "GimbalPitchDegree",
            "GimbalRollDegree",
            "DistanceToLastPoint",
            "CapToLastPoint",
            "CumulDistance",
        ]
        return list_key

    def save_shoot_points(self, pairing_result):
        """
        Save the pairing result to ``AerialPhotography/shoot_points.json``.

        The output directory is created if it does not already exist.

        Parameters
        ----------
        pairing_result : dict
            Pairing metadata and shoot-point records to serialize.

        Returns
        -------
        Path or None
            The output file path on success, or None if saving fails.
            A failure is also reported through the worker's error signal.
        """
        try:
            folder = safe_path(
                self.folderMissionPath / "AerialPhotography"
            )
            folder.mkdir(parents=True, exist_ok=True)

            file_path = folder / "shoot_points.json"

            pairing_result_json_safe = {
                k: Uti.to_json_safe(v)
                for k, v in pairing_result.items()
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(pairing_result_json_safe, f, indent=4, ensure_ascii=False)

            return file_path

        except Exception as e:
            self.signals.error.emit(f"Failed to save shoot_points.json: {e}")
            return None



# ============================================================================================

class TimeShiftWorkerSignals(QObject):
    def __init__(self):
        super().__init__()
    progress = pyqtSignal(int)  # pour la progress bar
    stage = pyqtSignal(str)
    finished = pyqtSignal(float,   # time_shift
                          list,    # time_line_VIS
                          list,    # angles_VIS
                          list,    # time_line_NIR
                          list,    # angles_NIR
                          str,     # abstract
                          bool,    # angle abs
                          bool     # angle image
                          )  # remonter les données car interdit de tracer avec pyplot à ce niveau dans un worker
    error = pyqtSignal(str)

class TimeShiftWorker(QRunnable):
    """
    Worker QRunnable for compute temporal offset  VIS/NIR.
    """
    def __init__(self, vis_results, vis_x, vis_y, nir_results, nir_x, nir_y):
        super().__init__()
        self.VIS_results = vis_results
        self.NIR_results = nir_results
        self.vis_x = vis_x
        self.vis_y = vis_y
        self.nir_x = nir_x
        self.nir_y = nir_y
        self.signals = TimeShiftWorkerSignals()
        self.abstract = True
        self.msg_abstract = " "
        self.angle_abs_for_shift_time = False
        self.angle_img_for_shift_time = False

    def run(self):
        """
        Execute the VIS/NIR temporal alignment based on ArUco angle measurements.

        This method performs the complete alignment pipeline:
        - extraction of relative timelines and raw angular measurements,
        - angle unwrapping performed *after* extraction and in a strictly identical
          manner for VIS and NIR,
        - estimation of the temporal shift and angular velocity using an L2 criterion.

        Important implementation notes
        -------------------------------
        1) Separation between extraction and unwrapping
           The function `extract_timeline_and_angles` intentionally returns *raw*
           angle values (no unwrapping). Angle unwrapping is performed afterwards
           using `unwrap_from_end`.

           This is mandatory for algorithmic consistency: VIS and NIR image streams
           are not processed in exactly the same order nor under identical internal
           conditions. Performing unwrapping inside the extraction step may therefore
           lead to different phase histories and incorrect synchronization results.

        2) Identical unwrapping strategy for VIS and NIR
           Both VIS and NIR angles are unwrapped using the same reference strategy
           (`unwrap_from_end`) and the same unwrapping function (`Aru.unwrap_angles`).
           This guarantees that both angle sequences share a consistent phase
           reference before time-shift estimation.

        3) Absolute angles versus image-relative angles
           By default, absolute angles (`angle_abs`) are used whenever available.
           These angles are invariant with respect to drone yaw and therefore more
           robust to small pilot-induced yaw motions during acquisition.

           Image-relative angles (`angle_img`), measured in the image frame, are
           used as a fallback solution only when absolute angles are not sufficiently
           available.

        4) Minimum number of samples for L2 time-shift estimation
           The L2-based time-shift estimation requires:
           - at least two NIR angle samples to define a reference angular evolution
             (a minimum of two points is required to define a line),
           - at least one VIS angle sample to project VIS measurements onto the
             NIR reference during the L2 optimization.

           These constraints are enforced through the constants:
           - `min_NIR_pts = 2`
           - `min_VIS_pts = 1`

        5) Time-shift estimation
           The temporal offset and angular velocity are estimated using
           `Aru.compute_time_shift_L2`, with a median-based strategy for increased
           robustness to outliers.

        If insufficient data are available, the method exits gracefully and emits
        a warning through the `finished` signal with a NaN time shift.

        Any exception raised during the process is caught and forwarded through
        the error signal.
        """

        time_line_VIS = []
        angles_unwrapped_VIS = []
        time_line_NIR = []
        angles_unwrapped_NIR = []
        self.angle_abs_for_shift_time = False
        self.angle_img_for_shift_time = False
        min_NIR_pts = 2
        min_VIS_pts = 1

        try:

            timeline_abs_VIS, angles_abs_VIS, ignored_abs_VIS = self.extract_timeline_and_angles(self.VIS_results, key="angle_abs")
            timeline_img_VIS, angles_img_VIS, ignored_VIS = self.extract_timeline_and_angles(self.VIS_results, key="angle_img")
            timeline_abs_NIR, angles_abs_NIR, ignored_abs_NIR = self.extract_timeline_and_angles(self.NIR_results, key="angle_abs")
            timeline_img_NIR, angles_img_NIR, ignored_NIR = self.extract_timeline_and_angles(self.NIR_results, key="angle_img")

            # Data integrity check
            if len(angles_abs_NIR) >= min_NIR_pts and len(angles_abs_VIS) >= min_VIS_pts:
                self.angle_abs_for_shift_time = True
                angles_unwrapped_VIS = self.unwrap_from_end(angles_abs_VIS, Aru.unwrap_angles)
                angles_unwrapped_NIR = self.unwrap_from_end(angles_abs_NIR, Aru.unwrap_angles)
                time_line_VIS = timeline_abs_VIS
                time_line_NIR = timeline_abs_NIR
                print(Style.GREEN + f"Time shift calculated using absolute angles" + Style.RESET)
                if ignored_abs_VIS > 0:
                    print(Style.YELLOW + f"⚠  {ignored_abs_VIS} images VIS skipped because fixed or mobile ArUco not detected" + Style.RESET)
                if ignored_abs_NIR > 0:
                    print(Style.YELLOW + f"⚠  {ignored_abs_NIR} images NIR skipped because fixed or mobile ArUco not detected" + Style.RESET)
            elif len(angles_img_NIR) >= min_NIR_pts and len(angles_img_VIS) >= min_VIS_pts:
                self.angle_img_for_shift_time = True
                angles_unwrapped_VIS = self.unwrap_from_end(angles_img_VIS, Aru.unwrap_angles)
                angles_unwrapped_NIR = self.unwrap_from_end(angles_img_NIR, Aru.unwrap_angles)
                time_line_VIS = timeline_img_VIS
                time_line_NIR = timeline_img_NIR
                print(Style.GREEN + f"Time shift calculated using relative angles" + Style.RESET)
                if ignored_VIS > 0:
                    print(Style.YELLOW + f"⚠  {ignored_VIS} images VIS skipped because fixed or mobile ArUco not detected" + Style.RESET)
                if ignored_NIR > 0:
                    print(Style.YELLOW + f"⚠  {ignored_NIR} images NIR skipped because fixed or mobile ArUco not detected" + Style.RESET)
            else:
                msg_abstract = ("WARNING\n"
                                "Insufficient data to automatically align VIS and NIR camera timelines.")
                print(Style.RED + msg_abstract + Style.RESET)
                time_shift = float("nan")
                self.signals.finished.emit(time_shift,
                                           time_line_VIS,
                                           angles_unwrapped_VIS,
                                           time_line_NIR,
                                           angles_unwrapped_NIR,
                                           msg_abstract,
                                           self.angle_abs_for_shift_time,
                                           self.angle_img_for_shift_time
                                           )
                return


            time_shift, omega, metrics = Aru.compute_time_shift_L2(
                time_line_VIS,
                angles_unwrapped_VIS,
                time_line_NIR,
                angles_unwrapped_NIR,
                use_median=True,
            )
            if self.abstract:
                msg_abstract = Aru.abstract_time_line_alignement(time_shift, omega, metrics)

            self.signals.finished.emit(time_shift,
                                       time_line_VIS,
                                       angles_unwrapped_VIS,
                                       time_line_NIR,
                                       angles_unwrapped_NIR,
                                       msg_abstract,
                                       self.angle_abs_for_shift_time,
                                       self.angle_img_for_shift_time
                                       )

        except Exception as e:
            self.signals.error.emit(str(e))

    def extract_timeline_and_angles(self, results, key="angle_abs"):
        """
        Extract relative timeline and (optionally unwrapped) angle values
        from ArUco results.

        Parameters
        ----------
        results : list of dict
            Output of ArUco detection.
        unwrap_func : callable or None
            Function applied to angle list

        Returns
        -------
        timeline : list
            Relative timeline values.
        angles : list
            Angle values .
        """
        timeline = []
        angles = []
        ignored = 0
        for r in results:
            angle = r.get(key)
            if angle is not None and r.get("relative_timeline") is not None:
                angles.append(angle)
                timeline.append(r["relative_timeline"])
            else:
                ignored += 1

        return timeline, angles, ignored

    def unwrap_from_end(self, angles, unwrap_func):
        """
        Unwrap angles starting from the last sample.
        """
        if len(angles) < 2:
            return angles

        angles_rev = angles[::-1]
        angles_unwrapped_rev = unwrap_func(angles_rev)
        return angles_unwrapped_rev[::-1]

class ArucoWorkerSignals(QObject):
    progress = pyqtSignal(int)  # Progress bar
    stage = pyqtSignal(str)
    finished = pyqtSignal(list, list, list)  # results, x_vals, y_vals
    error = pyqtSignal(str)
    log = pyqtSignal(str)  # Log message for the GUI

class ArucoWorker(QRunnable):
    """
    Worker QRunnable pour exécuter process_aruco_images en thread séparé.
    """
    def __init__(
        self,
        folderMissionPath: Path,
        name_folder: str,
        spectral_band: str,
        suffix_image: str,
        save_check_detection_img: bool = False,
        verbose: bool = False,
        use_aruco_cache: bool = False,
        multi_thread=False
    ):
        super().__init__()
        self.folderMissionPath = folderMissionPath
        self.name_folder = name_folder
        self.spectral_band = spectral_band
        self.suffix_image = suffix_image
        self.save_check_detection_img = save_check_detection_img
        self.verbose = verbose
        self.use_aruco_cache = use_aruco_cache
        self.multi_thread = multi_thread
        self.signals = ArucoWorkerSignals()

    def run(self):
        try:
            self.signals.stage.emit(f"Detect ArUco {self.spectral_band}")
            self.signals.progress.emit(3)
            results, x_vals, y_vals = Aru.process_aruco_images(
                folderMissionPath=self.folderMissionPath,
                name_folder=self.name_folder,
                spectral_band=self.spectral_band,
                suffix_image=self.suffix_image,
                save_check_detection_img=self.save_check_detection_img,
                verbose=self.verbose,
                use_aruco_cache=self.use_aruco_cache,
                multi_thread=self.multi_thread,
                progress_callback=self.signals.progress.emit,
                log_callback=self.signals.log.emit
            )
            self.signals.finished.emit(results, x_vals, y_vals)

        except Exception as e:
            self.signals.error.emit(str(e))

class ExifToolPersist:
    """
    Persistent ExifTool process wrapper using the "-stay_open True" protocol.

    Usage:
        et = ExifToolPersist(path_to_exiftool)
        et.start()
        meta = et.get_metadata("image.dng")
        et.close()

    Behaviour notes:
    - start() launches exiftool with "-stay_open True -@ -"
    - execute(args) writes the args followed by "-execute" and returns the raw text
      output produced by exiftool for that command (excluding the "{ready}" sentinel).
    - execute_json(args) will parse the returned output as JSON and return the parsed object.
    - get_metadata(filepath) is a convenience wrapper calling execute_json(["-json", filepath]).
    - close() stops the persistent process cleanly.
    """

    def __init__(self, exiftool_path: str):
        self.exiftool_path = exiftool_path
        self.process: Optional[subprocess.Popen] = None
        # Protect access to stdin/stdout to avoid interleaving from different threads
        self._io_lock = threading.Lock()

    def start(self) -> None:
        """Start persistent ExifTool process (no-op if already started)."""
        if self.process is not None:
            return

        # Launch exiftool in stay_open mode, reading/writing text
        self.process = subprocess.Popen(
            [self.exiftool_path, "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,               # use text mode for Python strings
            universal_newlines=True,
            bufsize=1,               # line-buffered
        )

        # Optionally read initial banner / first ready sentinel line if any.
        # ExifTool usually prints nothing extra, so we don't block here.

    def execute(self, args: List[str]) -> str:
        """
        Execute a single exiftool command via the persistent process.

        Parameters
        ----------
        args : List[str]
            List of strings that form the exiftool command arguments, e.g. ["-json", "file.dng"]

        Returns
        -------
        str
            Raw output produced by exiftool for these arguments (without the trailing '{ready}' sentinel).
        """
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("ExifToolPersist not started")

        # Build the command by writing each arg on its own line, then "-execute"
        with self._io_lock:
            # write args lines
            for a in args:
                self.process.stdin.write(a + "\n")
            # ask exiftool to execute but stay open
            self.process.stdin.write("-execute\n")
            self.process.stdin.flush()

            # read stdout until sentinel "{ready}" is found on its own line
            out_lines = []
            while True:
                line = self.process.stdout.readline()
                if line == "":
                    # EOF — process probably died; collect stderr and raise
                    stderr = ""
                    try:
                        stderr = self.process.stderr.read() if self.process.stderr is not None else ""
                    except Exception:
                        pass
                    raise RuntimeError(f"ExifTool process terminated unexpectedly. Stderr: {stderr!r}")
                # strip only newline for sentinel check
                if line.strip() == "{ready}":
                    break
                out_lines.append(line)

        return "".join(out_lines)

    def execute_json(self, args: List[str]) -> object:
        """
        Execute a command expecting JSON output and parse it.

        Returns the parsed JSON object (could be list/dict depending on command).
        """
        raw = self.execute(args)
        # exiftool outputs may include leading/trailing whitespace; strip before parsing
        raw_stripped = raw.strip()
        if not raw_stripped:
            return None
        try:
            return json.loads(raw_stripped)
        except json.JSONDecodeError as e:
            # raise a clearer error
            raise RuntimeError(f"Failed to parse exiftool JSON output: {e}; raw={raw!r}")

    def get_metadata(self, filepath: str) -> dict:
        """
        Convenience: return metadata (first object) for `filepath` as a dict.
        Returns empty dict on parse error or if exiftool returns empty output.
        """
        result = self.execute_json(["-json", filepath])
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        if isinstance(result, dict):
            return result
        return {}

    def close(self) -> None:
        """Terminate the persistent ExifTool process cleanly."""
        if self.process is None:
            return

        # ask exiftool to stop and then terminate
        try:
            with self._io_lock:
                if self.process.stdin:
                    self.process.stdin.write("-stay_open\nFalse\n")
                    self.process.stdin.flush()
        except Exception:
            pass

        try:
            self.process.wait(timeout=2.0)
        except Exception:
            try:
                self.process.terminate()
            except Exception:
                pass
        finally:
            self.process = None

    # context manager support
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

class CreateExif(QtCore.QObject):
    """
    Worker that scans a folder of DNG files and creates cleaned .exif JSON
    companion files using ExifTool (filtered keys only).

    Signals:
        progress(int)
        finished(dict, str)
        error(str)
    """

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(dict, str)
    error = QtCore.pyqtSignal(str)

    def __init__(self, folder_to_scan: str, msg: str, spectral_band: str = "VIS"):
        super().__init__()
        try:
            self.folder_to_scan = Path(folder_to_scan)
            self.msg = msg
            self.spectral_band = spectral_band

            self.exiftool_path = EXIFTOOLPATH
            self.et = ExifToolPersist(self.exiftool_path)

        except Exception as e1:
            print(f"[ERROR] CreateExif __init__: {e1}")
            import traceback
            traceback.print_exc()

    def update_exif_json(self, exif_path: Path, key: str, value):
        try:
            if not exif_path.exists():
                raise FileNotFoundError(exif_path)

            with exif_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("EXIF JSON is not a dictionary")

            data[key] = value

            with exif_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e2:
            print(f"[ERROR] in update_exif_json: {e2}")

    # =================================================================== #
    #                               RUN
    # =================================================================== #
    def run(self) -> None:
        try:
            files = list(self.folder_to_scan.glob("*.dng"))
            n = len(files)

            self.progress.emit(0)

            if n == 0:
                self.progress.emit(100)
                self.finished.emit({}, self.msg)
                return

            # Start persistent exiftool (if needed)
            self.et.start()

            # Determine files to process
            to_process = []
            for f in files:
                out_path = f.with_suffix(".exif")
                if not out_path.exists():
                    to_process.append(f)

            total = len(to_process)
            results: Dict[str, dict] = {}

            if total > 0:
                # CPU pool
                max_workers = psutil.cpu_count(logical=False) or 1
                done_counter = 0

                def _task_done(_):
                    nonlocal done_counter
                    done_counter += 1
                    percent = int(95 * done_counter / total)
                    self.progress.emit(percent)

                # ---------------- PARALLEL EXIF READING ---------------- #
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for f in to_process:
                        fut = executor.submit(
                            Uti.read_exif_and_write_json,
                            f,
                            self.exiftool_path
                        )
                        fut.add_done_callback(_task_done)
                        futures.append((f, fut))

                    for (f, fut) in futures:
                        cleaned_meta = fut.result()  # already filtered + saved as .exif
                        results[f.name] = cleaned_meta

            else:
                # nothing to compute, but still create timeline later
                self.progress.emit(95)

            # --------------- TIMELINE PROCESS (not parallel) --------------- #
            list_dic_exif = Uti.list_tempo_time_line(
                self.folder_to_scan,
                spectral_band=self.spectral_band
            )

            dic_timeline = Uti.time_line_analyser_images(
                list_dic_exif,
                spectral_band=self.spectral_band,
                img_suffix=".DNG",
                verbose=False
            )

            Uti.save_time_line_json(self.folder_to_scan, dic_timeline)

            for idx, pt in enumerate(dic_timeline[self.spectral_band]):
                my_path = Path(list_dic_exif[idx]["Directory"]) / f'{Path(list_dic_exif[idx]["FileName"]).stem}.exif'
                my_timeline = pt["relative_timeline"]
            for idx, pt in enumerate(dic_timeline[self.spectral_band]):
                my_path = (
                        Path(list_dic_exif[idx]["Directory"])
                        / f'{Path(list_dic_exif[idx]["FileName"]).stem}.exif'
                )

                try:
                    self.update_exif_json(
                        my_path,
                        "RelativeTimeLine",
                        pt["relative_timeline"]
                    )
                except Exception as e:
                    print(f"[ERROR] {my_path.name}: {e}")

            # Finish
            self.progress.emit(100)
            self.finished.emit(results, self.msg)

        except Exception as ex:
            self.error.emit(str(ex))

class Transfer_VIS(QtCore.QObject):
    """
    Worker class to transfer and rename VIS images from input directory
    to output directory in a separate thread, emitting progress updates
    and a finished signal when done.
    """

    progress: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    finished: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)

    def __init__(self, input_dir: Union[str, Path], output_dir: Union[str, Path]):
        super().__init__()
        self.input_dir: Path = Path(input_dir)
        self.output_dir: Path = Path(output_dir)
        self.exif_data = {}

    def run(self) -> None:
        try:
            assert self.input_dir.exists(), f"Input directory does not exist: {self.input_dir}"
            print(Style.GREEN + f"extract images in folder {self.input_dir}" + Style.RESET)
            list_file = Uti.list_files_with_suffix("dng", self.input_dir)
            # print(f"!! {list_file}")
            n = len(list_file)

            # --- progress bar : début ---
            self.progress.emit(0)

            cached = True

            # Liste des fichiers à traiter réellement
            to_process = []
            for f in list_file:
                out_path = f.with_suffix(".exif")
                if out_path.exists() and cached:
                    pass
                else:
                    to_process.append(f)

            n = len(to_process)
            if n == 0:
                self.progress.emit(100)
                self.finished.emit("No files to transfer")
                return

            done_counter = 0  # compteur pour progress bar

            for file in to_process:
                try:
                    input_img_name: str = Path(file).name
                    output_img_name: str = Uti.rename_file_VIS(input_img_name)

                    Uti.copy_and_rename_images(
                        self.input_dir,
                        input_img_name,
                        self.output_dir,
                        output_img_name,
                        verbose=False,
                    )
                except Exception as e:
                    print(f"[ERROR] transfer failed for {file}: {e}")

                done_counter += 1
                percent = int(100 * done_counter / n)
                self.progress.emit(percent)

            self.finished.emit("transfer_finished")

        except Exception as e:
            print("Error in WorkerTransfer_VIS.run:", e)
            self.error.emit(str(e))

class Transfer_NIR(QtCore.QObject):
    """
    Worker to convert NIR RAW files to DNG in parallel using ThreadPoolExecutor.
    Emits:
      - progress(int)
      - finished(str)
      - error(str)
    """

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)

    def __init__(self,
                 input_folder: Union[str, Path],
                 output_folder: Union[str, Path],
                 exe_path: Optional[str] = None,
                 nb_threads: str = "0",
                 max_workers: Optional[int] = None,
                 verbose: bool = False,
                 exiftool_path: Optional[str] = None):
        super().__init__()
        self.input_folder = Path(input_folder)
        self.output_folder = Path(output_folder)
        self.exe_path = exe_path or SJCONVERTERPATH
        self.nb_threads = nb_threads
        self.max_workers = max_workers
        self.verbose = verbose
        self.exiftool_path = exiftool_path or EXIFTOOLPATH
        self.dng_files: List[str] = []

    def run(self) -> None:
        try:
            self.output_folder.mkdir(parents=True, exist_ok=True)

            assert self.input_folder.exists(), f"Input directory does not exist: {self.input_folder}"
            print(Style.GREEN + f"extract images in folder {self.input_folder}" + Style.RESET)

            # RAW list
            raw_files = sorted([str(p) for p in self.input_folder.glob("*.RAW")])
            if not raw_files:
                raw_files = sorted([str(p) for p in self.input_folder.glob("*.raw")])

            n = len(raw_files)
            if n == 0:
                self.progress.emit(100)
                self.finished.emit("No NIR RAW files found")
                return

            # Determine worker count
            if self.max_workers is None:
                try:
                    cpu_physical = psutil.cpu_count(logical=False)
                    if cpu_physical is None:
                        raise ValueError("psutil returned None")
                    self.max_workers = max(1, cpu_physical)
                except Exception as e:
                    self.max_workers = max(1, (os.cpu_count() or 1))

            if self.verbose:
                print(f"[TRACE] WorkerTransfer_NIR: converting {n} files with max_workers={self.max_workers}")

            dng_results = []
            completed = 0

            # -------------------------------------
            # THREADPOOLEXECUTOR (PyQt6 OK)
            # -------------------------------------
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        Uti._convert_single_raw_to_dng,
                        raw,
                        self.exe_path,
                        str(self.output_folder),
                        self.nb_threads,
                        self.verbose,
                        self.exiftool_path
                    ): raw for raw in raw_files
                }

                for future in as_completed(futures):
                    raw = futures[future]
                    try:
                        dng_path = future.result()
                        if dng_path:
                            dng_results.append(dng_path)
                    except Exception as e:
                        print(f"[ERROR] conversion failed for {raw}: {e}")
                    finally:
                        completed += 1
                        pct = int(100 * completed / n)
                        if self.verbose:
                            print(f"[TRACE] completed = {completed} / {n}   pct = {pct}%")

                        # emit progress
                        if completed == n:
                            pct = 100
                        self.progress.emit(pct)

            # end
            self.dng_files = sorted(dng_results)
            msg = f"NIR conversion finished: {len(self.dng_files)} files created in {self.output_folder}"
            self.finished.emit(msg)

        except Exception as e:
            print("Error in WorkerTransfer_NIR.run:", e)
            self.error.emit(str(e))


class Alti_GPS(QtCore.QObject):
    """
    Retrieve ground elevations from GPS coordinates and update image metadata.

    This QObject is designed to perform altitude and GPS-related calculations
    in a worker thread, while communicating with the main GUI thread through
    Qt signals.

    The processing workflow consists of the following stages:

    1. EXIF metadata loading
       Read the .exif JSON sidecar files matching the selected spectral band.
       Extract GPS coordinates, takeoff-relative altitude, and projected UTM
       coordinates when available.

    2. Ground elevation retrieval:
       - For locations in France, query the IGN (Institut national de
         l'information géographique et forestière) elevation API, which
         provides high-resolution elevation data.
       - If an IGN request fails, make up to three consecutive attempts,
         with a short delay between attempts.
       - If all three attempts fail, automatically fall back to
         OpenTopoData, which provides global elevation coverage.
       - Locations outside France are automatically handled by
         OpenTopoData, since the IGN elevation API is intended for
         French territory.
       - OpenTopoData generally provides less precise elevation data
         than IGN for locations in France.

    3. Sea-level altitude calculation
       Combine the drone's takeoff-relative altitude with the ground elevation
       at the first GPS point to estimate the drone altitude above sea level.
       The estimated ground elevation is then used to derive the drone height
       above ground level.

    4. Timeline loading
       Read the VIS relative timeline from time_line.json. These timestamps
       are subsequently stored in the corresponding EXIF dictionaries.

    5. Distance and heading calculations
       Compute the distance between successive GPS points, the corresponding
       heading, and the cumulative flight distance using Geo.calcul_distance.

    6. EXIF metadata update
       Add the retrieved ground elevation, calculated altitude values,
       distances, headings, cumulative distance, and relative timeline to each
       EXIF dictionary, then save the updated JSON sidecar file.

    7. Plot-data preparation
       Normalize ground and sea-level altitudes relative to the minimum
       ground elevation. Emit the cumulative distance and normalized altitude
       arrays through the plot_data signal so that the main GUI thread can
       display the resulting profile.

    Signals
    -------
    progress : pyqtSignal(int)
        Processing progress, expressed as a percentage.
    finished : pyqtSignal(str)
        Completion message emitted after successful processing.
    error : pyqtSignal(str)
        Error message emitted if an unhandled exception occurs.
    plot_data : pyqtSignal(object, object, object)
        Emits the cumulative distance, normalized ground elevation, and
        normalized drone altitude above sea level, in that order.

    Parameters
    ----------
    folder : Union[str, Path]
        Directory containing the EXIF sidecar files and time_line.json.
    band : str, optional
        Spectral band identifier used to select the EXIF files.
        Defaults to "VIS".
    verbose : bool, optional
        If True, print additional information about the GPS data being read.
        Defaults to False.

    Notes
    -----
    The class relies on the external Geo module for IGN elevation retrieval
    and distance/heading calculations.

    The plot_data signal is emitted from the worker. The connected GUI slot
    should handle graphical display in the main Qt thread.

    The existing processing logic and variable names are intentionally
    preserved.
    """

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    plot_data = QtCore.pyqtSignal(object, object, object)

    def __init__(
        self,
        folder: Union[str, Path],
        band: str = "VIS",
        verbose: bool = False
    ):
        """
        Initialize the altitude and GPS processing worker.

        Parameters
        ----------
        folder : Union[str, Path]
            Directory containing the image EXIF sidecar files.
        band : str, optional
            Spectral band identifier used to select the EXIF files.
            Defaults to "VIS".
        verbose : bool, optional
            Enable additional GPS metadata output. Defaults to False.
        """
        super().__init__()
        self.folder = Path(folder)
        self.band = band
        self.verbose = verbose
        self.list_dic_exif = []

    def run(self) -> None:
        """
        Execute the complete altitude and GPS processing workflow.

        The method loads the EXIF metadata, retrieves ground elevations from
        the IGN service, reads the image timeline, computes distances and
        headings, updates the EXIF JSON files, and emits the data required
        to display the altitude profile.

        Progress updates are emitted throughout the processing stages.

        If no matching EXIF files or no timeline file is found, the method
        prints a warning and returns. Errors raised during individual EXIF
        reads or IGN batch requests are handled locally where possible.
        Other exceptions are reported through the error signal.

        Returns
        -------
        None
            Results are communicated through Qt signals and updated EXIF files.
        """
        try:
            # Collect the EXIF sidecar files matching the selected spectral band.
            exif_files = sorted([
                str(p)
                for p in self.folder.glob(f"{self.band}_*.exif")
            ])

            if not exif_files:
                print(
                    Style.YELLOW
                    + f'⚠ EXIF data are not available in folder {self.folder}'
                    + Style.RESET
                )
                return

            n = len(exif_files)

            self.progress.emit(0)
            gps_list = []
            list_exif_dict = []

            for idx, exif_path in enumerate(exif_files):
                # --- Read the EXIF sidecar file (JSON) ---
                try:
                    with open(exif_path, "r", encoding="utf-8") as f:
                        exif_dict = json.load(f)
                        list_exif_dict.append(exif_dict)
                except Exception as e:
                    print(f"[ERROR] Unable to read {exif_path}: {e}")
                    continue

                # --- Extract the GPS-related metadata fields ---
                keys = [
                    "DateTimeOriginal",
                    "DroneLatitude",
                    "DroneLongitude",
                    "DroneAltitudeTakeOff",
                    "UTM_x",
                    "UTM_y",
                    "UTM_zone"
                ]

                gps_list.append({
                    "file": exif_path,
                    "lat": exif_dict.get("DroneLatitude"),
                    "lon": exif_dict.get("DroneLongitude"),
                    "alt_tkoff": exif_dict.get("DroneAltitudeTakeOff"),
                    "UTM_x": exif_dict.get("UTM_x"),
                    "UTM_y": exif_dict.get("UTM_y"),
                })

                if self.verbose:
                    print(
                        f'[INFO] name = {Path(exif_path).stem} '
                        f'Latitude : {exif_dict.get("DroneLatitude")}°'
                        f'Longitude {exif_dict.get("DroneLongitude")}°'
                        f', Altitude/take off :  '
                        f'{exif_dict.get("DroneAltitudeTakeOff")} m'
                    )

            # --- Update the progress bar after reading the EXIF files ---
            pct = int(100 * idx / n)
            self.progress.emit(pct)

            self.progress.emit(10)

            lat = np.array([d["lat"] for d in gps_list])
            lon = np.array([d["lon"] for d in gps_list])
            alt_tkoff = np.array([d["alt_tkoff"] for d in gps_list])
            list_pts = [(lat[i], lon[i]) for i in range(len(gps_list))]

            # --- Retrieve ground elevations ---
            # Use the IGN (Institut national de l'information géographique
            # et forestière) API for France, or OpenTopoData for global coverage.
            # The returned elevation is the ground height above sea level
            # at each GPS coordinate.
            self.progress.emit(30)

            # --- Query the IGN elevation service in batches ---
            chunk_size = 300  # Maximum number of points per IGN API request.
            n = len(list_pts)
            alt_ground_list = []  # Accumulate the retrieved ground elevations.
            n_batches = (n + chunk_size - 1) // chunk_size  # Total number of batches.

            for b in range(n_batches):
                # Determine the start and end indices of the current batch.
                start = b * chunk_size
                end = min(start + chunk_size, n)
                pts_batch = list_pts[start:end]

                print(
                    Style.GREEN
                    + f"Processing batch {b + 1}/{n_batches} "
                      f"({len(pts_batch)} points)"
                    + Style.RESET
                )

                try:
                    dic_pts_geo = Geo.extract_alti_IGN(
                        pts_batch,
                        verbose=True,
                        bypass=False
                    )
                    elevations = dic_pts_geo


                except Exception as e:
                    print(f"[ERROR] Batch {b + 1} failed: {e}")

                    # Insert invalid elevation values for the failed batch.
                    elevations = [{"z": -9999} for _ in pts_batch]

                # Append the elevations returned for the current batch.
                alt_ground_list.extend([d["z"] for d in elevations])

                # --- Update progress during elevation retrieval ---
                pct = int(30 + 40 * (b + 1) / n_batches)  # From 30% to 70%.
                self.progress.emit(pct)

            # Convert the collected ground elevations to a NumPy array.
            alt_ground = np.array(alt_ground_list)
            alt_sea_level = alt_tkoff + alt_ground[0]

            # --- IGN elevation retrieval completed ---
            self.progress.emit(70)
            # print("[INFO] Altitudes IGN récupérées (avec gestion des erreurs)")

            # --- Load the image timeline ---
            time_line_path = next(self.folder.glob(f"time_line.json"), None)

            if not time_line_path:
                print(
                    Style.YELLOW
                    + f'⚠ Timeline data are not available in folder {self.folder}'
                    + Style.RESET
                )
                return

            with open(time_line_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            list_time_line_dict = data["VIS"]
            relative_timeline = np.array([
                d["relative_timeline"] for d in list_time_line_dict
            ])

            self.progress.emit(90)

            # --- Calculate distances and headings between successive points ---
            distP0P1, capP0P1 = Geo.calcul_distance(
                np.column_stack((lat, lon, alt_ground_list))
            )

            distance_cum = np.cumsum(distP0P1)  # Cumulative flight distance.

            # --- Update and save the EXIF metadata for each image ---
            for idx, exif_dict in enumerate(list_exif_dict):
                exif_dict["GroundAltitude"] = alt_ground[idx]
                exif_dict["DroneAltitudeSeaLevel"] = alt_sea_level[idx]
                exif_dict["DroneAltitudeGround"] = (
                    alt_sea_level[idx] - alt_ground[idx]
                )
                exif_dict["DistanceToLastPoint"] = distP0P1[idx]
                exif_dict["CapToLastPoint"] = capP0P1[idx]
                exif_dict["RelativeTimeLine"] = relative_timeline[idx]
                exif_dict["CumulDistance"] = distance_cum[idx]

                # Build the path to the corresponding EXIF sidecar file.
                json_path = (
                    Path(exif_dict["Directory"])
                    / (Path(exif_dict["FileName"]).stem + ".exif")
                )

                with json_path.open("w", encoding="utf-8") as f:
                    json.dump(
                        exif_dict,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

            self.progress.emit(90)

            # ======== PLOT-DATA CALCULATION (without Matplotlib) ========
            # Prepare the altitude arrays for display by the main GUI thread.
            try:
                # Minimum ground elevation used as the reference level.
                alt_ground_min = np.min(alt_ground)

                # Normalize both altitude arrays relative to the minimum
                # ground elevation, so that the lowest ground point is zero.
                alt_ground_norm = alt_ground - alt_ground_min
                alt_sea_level_norm = alt_sea_level - alt_ground_min

            except Exception as e:
                print(f'Error in plot-data calculation: {e}')

            # ======== EMIT DATA TO THE MAIN THREAD THROUGH A QT SIGNAL ========
            # The GUI can use these arrays to plot the flight altitude profile.
            self.plot_data.emit(
                distance_cum,
                alt_ground_norm,
                alt_sea_level_norm
            )

            # ==================================================================

            self.progress.emit(100)
            msg = "Altitude and GPS coordinate calculation completed"
            self.finished.emit(msg)

        except Exception as e:
            print("Error in Alti_GPS:", e)
            self.error.emit(str(e))

