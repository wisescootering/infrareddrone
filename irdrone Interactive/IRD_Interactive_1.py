# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Creation of the mission by selection of the first image taken by the DJI (visible spectrum, image in dng format)
#   29/10/2023   V002
# ---------------------------------------------------------------------------------

from typing import Any, Dict, Optional, Tuple, List, Union, Callable
import sys
import os
from pathlib import Path
import shutil
import json
from datetime import date, time, datetime
import time
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
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression, QUrl

# -------------- IRDrone Library ------------------------------------
import IRD_Interactive_utils as Uti
import IRD_interactive_geo as Geo
from IRD_Interactive_utils import Prefrence_Screen
import IRD_Interactive_workers as Worker
from IRD_Interactive_color_style import Style
from config import OUTPUT_FOLDER_NAME

# --------------------------------------------------------------------------------------------
#
#                     Window_create_file_structure
#
#                Creation of the mission file structure
#
# --------------------------------------------------------------------------------------------

class Window_create_file_structure(QDialog):
    """
    Creation of the mission file structure
    C:/Air-Mission/
        └── FLY-YYYYMMDD-hhmm-<txt>/
            │
            ├── AerialPhotography/
            │       └── VIS/
            │             └──  [VIS_0001.dng, VIS_0002.dng, ...]
            │             └──  [VIS_0001.exif, VIS_0002.exif, ...]
            │             └──  time_line.json
            │       └── NIR/
            │             └──  [NIR_0001.dng, NIR_0002.dng, ...]
            │             └──  [NIR_0001.exif, NIR_0002.exif, ...]
            │             └──  time_line.json
            ├── Synchro/
            ├── ImgIRdrone/
            ├── mapping_MULTI/
            └── cameras/
            ├── FlightAnalytics/
            │       └── mission_parameters.json              ( mission parameters )
            │       └── transfer_info_VIS_dng.json (minimal version)
            └──


            At this stage, we do not have   └── cameras/
                                            │       └── camera_IRdrone.json


    """
    # Creates a class signal to transmit the data to the parent which will here be an instance of the window_11 class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_dialog_create_file_structure_to_main_window = pyqtSignal(bool, dict)

    def __init__(self, parent, mission_parameters_light: Dict[str, Any]):
        super().__init__(parent)
        # -----------Name of folders to store mission images. ----------------
        try:
            self.transfer_thread_VIS = None
            self.transfer_worker_VIS = None
            self.exif_thread_VIS = None
            self.exif_worker_VIS = None
            self.exif_started_VIS = False
            self.exif_results = None
            self.worker = None
            self.input_dir_VIS: Path = Path()
            self.output_dir_VIS: Path = Path()
            self.output_dir_NIR: Path = Path()
            self.exif_started_VIS = False
            self.path_folder_NIR: Optional[Path] = None
            self.nir_thread = None
            self.nir_worker = None
            self.nir_started = False
            self._exif_threads = {}
            self._exif_workers = {}
            self.thread_vis = None
            self.worker_vis = None
            self.thread_nir = None
            self.worker_nir = None

            self.path_image_takeoff = None
            self.name_image_takeoff = None
            self.dirname_image_takeoff = None
            self.suffix_image_takeoff = None
            self.path_folder_NIR = None
            self.altitude_DJI = None
            self.dic_info_geo = None
            self.Date_Exif = None

            self.pref = Prefrence_Screen()
            self.layout = None
            self.zone_121 = None
            self.zone_122 = None
            self.zone_122_layout = None
            self.btn_1221 = None
            self.btn_1222 = None
            self.time_layout = None
            self.location_label = None
            self.location_field = None
            self.location_layout = None
            self.phase_label = None

            self.validate_answer = True
            self.date_layout = None
            self.time_label = None
            self.time_field = None

            self.GPS_label = None
            self.GPS_NS_lat: str = None
            self.GPS_lat: float = None
            self.GPS_lat_field = None
            self.GPS_NS = None
            self.GPS_EW = None
            self.GPS_lon = None
            self.GPS_lon_field = None
            self.GPS_alti = None
            self.GPS_layout = None
            self.description_label = None
            self.description_field = None
            self.description_layout = None
            self.pilot_Name = "Alain"
            self.pilot_ID = None
            self.pilot_Name_field = None
            self.pilot_layout = None
            self.pilot_ID_field = None
            self.pilot_label = None

            self.camera_VIS_ID_field = None
            self.camera_VIS_maker_field = None
            self.camera_VIS_tlapse_field = None
            self.camera_VIS_layout = None
            self.camera_VIS_t_layout = None
            self.camera_VIS_t_label = None
            self.camera_VIS_label = None
            self.camera_VIS_deltatime_field = None
            self.camera_VIS_deltatime = None
            self.camera_VIS_timelaspe = None
            self.camera_VIS_maker = None
            self.camera_VIS_ID = None

            self.camera_NIR_ID_field = None
            self.camera_NIR_maker_field = None
            self.camera_NIR_tlapse_field = None
            self.camera_NIR_layout = None
            self.camera_NIR_t_layout = None
            self.camera_NIR_t_label = None
            self.camera_NIR_label = None
            self.camera_NIR_deltatime_field = None
            self.camera_NIR_deltatime = None
            self.camera_NIR_timelaspe = None
            self.camera_NIR_maker = None
            self.camera_NIR_ID = None

            self.image_VIS_format = None
            self.image_VIS_format_label = None
            self.image_VIS_format_field = None
            self.image_VIS_format_layout = None

            self.image_NIR_format = None
            self.image_NIR_format_label = None
            self.image_NIR_format_field = None
            self.image_NIR_format_layout = None
            self.image_NIR_filter_layout = None
            self.image_NIR_filter_maker = None
            self.image_NIR_filter_maker_field = None
            self.image_NIR_filter_band = None
            self.image_NIR_filter_band_field = None
            self.image_NIR_filter_label = None


            self.AerialPhotoFolder: str = self.pref.AerialPhotoFolder  # folder of images taken by VIS and NIR cameras
            self.AerialPhotoFolder_VIS: str = self.pref.AerialPhotoFolder_VIS  # folder of images taken by VIS and NIR cameras
            self.AerialPhotoFolder_NIR: str = self.pref.AerialPhotoFolder_NIR  # folder of images taken by VIS and NIR cameras
            self.AnalyticFolder: str = self.pref.AnalyticFolder  # technical folder containing information on the mission
            self.ImgIRdroneFolder: str = self.pref.ImgIRdroneFolder  # folder of images processed by IRDrone
            self.SynchroFolder: str = self.pref.SynchroFolder  # folder for images from the camera synchronization phase
            self.MappingFolder: str = self.pref.MappingFolder  # folder for image assembly with Open Drone Map
            self.CameraFolder: str = self.pref.CameraFolder  # Used by ODM
            self.missionFolder: str = self.pref.directory

            self.mission_parameters_light: dict = mission_parameters_light
            self.mission_parameters: dict[str, Any] = {}
            self.date_label = None
            self.date_field = None

            self.py_date_time = datetime.strptime(self.mission_parameters_light['Date Exif'], "%Y:%m:%d %H:%M:%S")
            self.py_date = self.py_date_time.date()
            self.py_time = self.py_date_time.time()

            self.progress_bar = None



            self.initGUI()
        except Exception as e:
            print(f' error in   Window_create_file_structure  __init__  : {e}')

    def initGUI(self) -> None:
        """
        Initialize the graphical user interface (GUI) for the mission creation dialog.

        Sets up the window title, geometry, main layouts, action buttons, progress bar,
        and initial input fields. Connects signals to their corresponding slots.
        """
        try:
            # Set window title
            self.setWindowTitle("Create a mission")

            # Main vertical layout
            self.layout: QVBoxLayout = QVBoxLayout(self)

            # Set window size
            width: int = 680  # 700
            height: int = 700  # 500
            self.setGeometry(0, 0, width, height)

            # Initialize input fields for takeoff point
            self.init_fields()
            self.update_mission_parameters()

            # Zone 121: Placeholder widget (can hold dynamic content)
            self.zone_121: QWidget = QWidget()
            self.layout.addWidget(self.zone_121)

            # Zone 122: Buttons and progress bar
            self.zone_122: QWidget = QWidget()
            self.layout.addWidget(self.zone_122)

            # Action buttons
            self.btn_1221: QPushButton = QPushButton("Validate create mission.")
            self.btn_1221.setStyleSheet("background-color: darkGray; color: black;")
            self.btn_1222: QPushButton = QPushButton("<< previous step")
            self.btn_1222.setStyleSheet("background-color: darkGray; color: black;")

            # ---- Nouveau layout vertical principal ----
            zone_122_vlayout = QVBoxLayout()
            self.zone_122.setLayout(zone_122_vlayout)

            # Phase label au-dessus de la barre, centré
            self.phase_label = QLabel("Waiting …")
            self.phase_label.setStyleSheet("font-weight: bold; color: black;")
            self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            zone_122_vlayout.addWidget(self.phase_label)

            # Progress bar setup
            self.progress_bar: QProgressBar = QProgressBar(self)
            self.progress_bar.setStyleSheet("QProgressBar { color: white; }")
            self.progress_bar.setValue(0)
            zone_122_vlayout.addWidget(self.progress_bar)

            # Layout horizontal pour les boutons
            self.zone_122_layout = QHBoxLayout()
            self.zone_122_layout.addWidget(self.btn_1222)
            self.zone_122_layout.addWidget(self.btn_1221)
            zone_122_vlayout.addLayout(self.zone_122_layout)

            # Connect buttons to slots
            self.btn_1221.clicked.connect(self.ok_clicked)
            self.btn_1222.clicked.connect(self.cancel_clicked)

            # Set initial focus sequence for UI fields
            self.focus_sequence()

            # Center window on the specified screen
            Uti.center_on_screen(self, screen_Id=1)

            # Set overall style
            self.setStyleSheet("background-color: white; color: black;")
        except Exception as e:
            print(f'error in initGUI : {e}')

    def focus_sequence(self) -> None:
        try:
            self.date_field.returnPressed.connect(self.time_field.setFocus)
            self.time_field.returnPressed.connect(self.location_field.setFocus)

            self.location_field.returnPressed.connect(self.GPS_lat_field.setFocus)
            self.GPS_lat_field.returnPressed.connect(self.GPS_lon_field.setFocus)

            self.GPS_lon_field.returnPressed.connect(self.description_field.setFocus)

            self.description_field.returnPressed.connect(self.pilot_Name_field.setFocus)

            self.pilot_Name_field.returnPressed.connect(self.pilot_ID_field.setFocus)
            self.pilot_ID_field.returnPressed.connect(self.camera_VIS_maker_field.setFocus)

            self.camera_VIS_maker_field.returnPressed.connect(self.camera_VIS_ID_field.setFocus)
            self.camera_VIS_ID_field.returnPressed.connect(self.camera_VIS_tlapse_field.setFocus)
            self.camera_VIS_tlapse_field.returnPressed.connect(self.camera_VIS_deltatime_field.setFocus)
            self.camera_VIS_deltatime_field.returnPressed.connect(self.image_VIS_format_field.setFocus)

            self.image_VIS_format_field.returnPressed.connect(self.camera_NIR_maker_field.setFocus)
            self.camera_NIR_maker_field.returnPressed.connect(self.camera_NIR_ID_field.setFocus)
            self.camera_NIR_ID_field.returnPressed.connect(self.camera_NIR_tlapse_field.setFocus)
            self.camera_NIR_tlapse_field.returnPressed.connect(self.camera_NIR_deltatime_field.setFocus)
            self.camera_NIR_deltatime_field.returnPressed.connect(self.image_NIR_format_field.setFocus)

            self.image_NIR_format_field.returnPressed.connect(self.image_NIR_filter_maker_field.setFocus)
            self.image_NIR_filter_maker_field.returnPressed.connect(self.image_NIR_filter_band_field.setFocus)

            self.image_NIR_filter_band_field.returnPressed.connect(self.btn_1221.setFocus)
        except Exception as e:
            print("error __init__  Sequence of focuses ", e)

    def init_fields(self) -> None:
        """
        Initializes takeoff point data fields.
        The Date, Time, GPS coordinates and Location fields are pre-populated.
        They are extracted from the Exif data of the image taken at takeoff.
        These fields cannot be modified by the user (setReadOnly(True),
        with the exception of the location field (setReadOnly(False).
        """
        try:
            self._init_date_mission()
            self._init_time_mission()
            self._init_location()
            self._init_GPS()
            self._init_description()
            self._init_pilot()
            self._init_VIS_camera()
            self._init_NIR_camera()
            self._init_NIR_filter()
        except Exception as e:
            print(f'error in init_fields : {e}')

    # ======= Bouton principal ==========

    def ok_clicked(self) -> None:
        """
        Slot called when 'OK' is clicked.
        Explicitly triggers the full mission pipeline:
            1. VIS transfer
            2. EXIF VIS
            3. NIR transfer
            4. EXIF NIR
            5. Final message
        """
        try:
            self.btn_1221.setEnabled(False)

            # Update mission info
            self.update_mission_parameters()
            self.create_mission_folder()
            self.update_image_takeoff()
            self.update_transfert_info_VIS_dng_json()

            # Directories VIS
            self.input_dir_VIS = Path(self.mission_parameters.get("original File path take-off")).parent
            self.output_dir_VIS = Path(self.mission_parameters["File path mission"]) / "AerialPhotography" / "VIS"
            assert self.input_dir_VIS.exists(), f"Input VIS directory does not exist: {self.input_dir_VIS}"
            assert self.output_dir_VIS.exists(), f"Output VIS directory does not exist: {self.output_dir_VIS}"
            # --- Launch pipeline ---
            self.start_mission_pipeline()

        except Exception as e:
            print(f"[ERROR] in ok_clicked: {e}")
            self.btn_1221.setEnabled(True)


    def cancel_clicked(self) -> None:
        """
        Slot called when the 'Cancel' button is clicked.
        Closes the current dialog window.
        """
        try:
            self.close()
        except Exception as e:
            print("Error in Window_create_file_structure.cancel_clicked:", e)

    # ==== Orchestrateur des worker(s)  et pipe line =============


    def start_mission_pipeline(self):
        pipeline = [
            self.start_transfer_VIS,
            self.start_exif_VIS_step,
            self.start_transfer_NIR,
            self.start_exif_NIR_step,
            self.start_alti_GPS,
            self._final_mission_done
        ]
        self._run_pipeline(pipeline, step_index=0)

    def _run_pipeline(self, pipeline, step_index, *args):
        """Exécute le pipeline étape par étape."""
        if step_index >= len(pipeline):
            return
        step_fn = pipeline[step_index]

        def done_callback(result, msg):
            self._run_pipeline(pipeline, step_index + 1, result, msg)             # Quand le worker courant termine, passer au suivant
        step_fn(done_callback, *args)  # Lancer l’étape


    # =======  Gestion worker transfer_VIS ===================


    def start_transfer_VIS(self, done, *args):
        print("[PIPE] !!!!! Starting VIS transfer")

        self.thread_vis = QtCore.QThread()
        self.worker_vis = Worker.Transfer_VIS(self.input_dir_VIS, self.output_dir_VIS)
        self.worker_vis.moveToThread(self.thread_vis)

        self.thread_vis.started.connect(self.worker_vis.run)
        self.worker_vis.progress.connect(self.on_transfer_VIS_progress)
        self.worker_vis.finished.connect(lambda msg: done("VIS_TRANSFER_OK", msg))
        self.worker_vis.error.connect(self.on_transfer_VIS_error)

        # cleanup
        self.worker_vis.finished.connect(self.thread_vis.quit)
        self.worker_vis.finished.connect(self.worker_vis.deleteLater)
        self.thread_vis.finished.connect(self.thread_vis.deleteLater)

        self.thread_vis.start()

    def on_transfer_VIS_error(self, message: str) -> None:
        """Handle TRANSFER worker errors (display and proceed)."""
        try:
            self.btn_1221.setEnabled(True)
            print("[ERROR] TRANSFER worker:", message)
            Uti.show_info_message("IRDrone", "EXIF worker error", message)
            self.close()
        except Exception as e:
            print(f'error in on_transfer_VIS_error {e}')

    def on_transfer_VIS_progress(self, pct: int) -> None:
        """Slot appelé par WorkerTransfer_VIS.progress"""
        try:
            self.progress_bar.setValue(pct)
            self.phase_label.setText(f"Transfer VIS: {pct}%")
        except Exception as e:
            print("Error in on_transfer_VIS_progress:", e)

    # =======  Gestion worker transfer_NIR ===================


    def start_transfer_NIR(self, done, *args):
        # print("[PIPE] Starting NIR transfer")
        self.progress_bar.setValue(0)
        self.phase_label.setText(f"Waiting …")

        Uti.show_info_message("IRDrone", "Choose the image folder", "Near Infrared (NIR)")
        src_nir_folder = self.load_NIR_directory()

        dest_nir_folder = Path(self.mission_parameters["File path mission"]) / "AerialPhotography" / "NIR"
        self.output_dir_NIR = dest_nir_folder

        self.thread_nir = QtCore.QThread()
        self.worker_nir = Worker.Transfer_NIR(src_nir_folder, dest_nir_folder)
        self.worker_nir.moveToThread(self.thread_nir)

        self.thread_nir.started.connect(self.worker_nir.run)
        self.worker_nir.progress.connect(self.on_nir_progress)
        self.worker_nir.finished.connect(lambda msg: done("NIR_TRANSFER_OK", msg))

        self.worker_nir.finished.connect(self.thread_nir.quit)
        self.worker_nir.finished.connect(self.worker_nir.deleteLater)
        self.thread_nir.finished.connect(self.thread_nir.deleteLater)

        self.thread_nir.start()

    def on_nir_progress(self, pct: int) -> None:
        try:
            self.progress_bar.setValue(pct)
            self.phase_label.setText(f"Transfer NIR : {pct}%")
        except Exception as e:
            print("Error in on_nir_progress:", e)

    def on_nir_finished(self, msg: str) -> None:
        try:
            self.nir_started = False
            self.btn_1221.setEnabled(True)
            mission_folder = Path(self.mission_parameters["File path mission"]).name
            print(f'[INFO] NIR transfer finished: {msg}')
            Uti.show_info_message(
                "IRDrone",
                "Mission creation completed",
                f"The mission '{mission_folder}' has been successfully created."
            )
            self.data_signal_from_dialog_create_file_structure_to_main_window.emit(self.validate_answer, self.mission_parameters)
            self.close()
        except Exception as e:
            print("error in on_nir_finished:", e)

    def on_nir_error(self, message: str) -> None:
        try:
            print("[ERROR] NIR worker:", message)
            self.nir_started = False
            self.btn_1221.setEnabled(True)
            Uti.show_info_message("IRDrone", "NIR worker error", message)
            self.close()
        except Exception as e:
            print("error in on_nir_error:", e)

    def load_NIR_directory(self) -> Optional[Path]:
        try:
            dlg = QFileDialog()
            dlg.setWindowTitle("Select a NIR RAW/JPG (SJCam M20)")

            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
            dlg.setNameFilter("SJCam Images (*.RAW *.JPG *.JPEG)")

            # --- Ouvre sur C:
            dlg.setDirectory("C:/")

            # --- Ajoute des entrées utiles dans la sidebar
            dlg.setSidebarUrls([
                QUrl.fromLocalFile("C:/"),
                QUrl("file:///"),  # Montages de disques, cartes SD, USB
            ])

            if dlg.exec():
                file_path = dlg.selectedFiles()[0]
                file_path = Path(file_path)
                folder = file_path.parent
                self.path_folder_NIR = folder
                sample_image_NIR = file_path
                return folder

            print("[INFO] NIR selection cancelled by user.")
            return None

        except Exception as e:
            print("error in load_NIR_directory:", e)
            return None


    # =======  Gestion worker Exif   for VIS and NIR =========


    def start_exif_worker(self, folder: str, band: str, callbacks: Optional[List[Callable]] = None):
        """
        Generic EXIF worker starter for any spectral band (VIS, NIR, ...).

        Parameters
        ----------
        folder : str
            Directory containing .dng files.
        band : str
            Spectral band name ('VIS', 'NIR', etc.).
        callbacks : list of callables
            Functions called on finish: cb(exif_data, msg)
        """
        try:
            # print(f"[PIPE] Starting EXIF {band} on folder: {folder}")
            thread = QtCore.QThread()
            worker = Worker.CreateExif(folder, f"EXIF {band}", spectral_band=band)
            worker.moveToThread(thread)

            # Store references to avoid garbage collection
            self._exif_threads[band] = thread
            self._exif_workers[band] = worker

            worker.progress.connect(lambda pct: self.on_exif_progress(band, pct))
            worker.error.connect(lambda msg: self.on_exif_error(band, msg))

            def _finished(meta_dict, msg):
                try:
                    # toujours exécuter le handler interne (stockage, logs) dans le main thread
                    self.on_exif_finished(band, meta_dict, msg)
                except Exception as e:
                    print(f"[ERROR] on_exif_finished({band}) raised: {e}")

                if not callbacks:
                    return

                # schedule execution of callbacks in the main event loop to avoid thread-affinity issues
                def _run_callbacks():
                    for i, cb in enumerate(callbacks):
                        try:
                            cb(meta_dict, msg)
                        except Exception as e:
                            # don't let one failing callback kill the sequence — log and continue
                            print(f"[ERROR] callback {i} for EXIF {band} raised: {e}")
                            import traceback
                            traceback.print_exc()

                QtCore.QTimer.singleShot(0, _run_callbacks)

            worker.finished.connect(_finished)

            # Cleanup
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)

            # Run
            thread.started.connect(worker.run)
            thread.start()

        except Exception as e:
            print(f"[ERROR] start_exif_worker({band}): {e}")

    def on_exif_progress(self, band: str, pct: int):
        verbose = False
        if verbose: print(f"[INF0]   [EXIF {band}] progress = {pct}%")
        self.phase_label.setText(f"EXIF {band} : {pct}%")
        self.progress_bar.setValue(pct)

    def on_exif_error(self, band: str, msg: str):
        print(f"[ERROR] EXIF {band}: {msg}")
        Uti.show_info_message("IRDrone", f"Erreur EXIF {band}", msg)
        self.close()

    def on_exif_finished(self, band: str, exif_data: dict, msg: str):
        try:
            self.exif_results = exif_data
        except Exception as e:
            print(f"[ERROR] on_exif_finished({band}): {e}")

    def start_exif_VIS_step(self, done: Callable, *args):
        try:
            folder = self.output_dir_VIS
            cb = lambda exif_data, msg: done(exif_data, msg)
            self.start_exif_worker(folder=folder, band="VIS", callbacks=[cb])
        except Exception as e:
            print(f"[ERROR] start_exif_VIS_step: {e}")
            done({}, f"Error starting EXIF VIS: {e}")

    def start_exif_NIR_step(self, done: Callable, *args):
        try:
            folder = getattr(self, "output_dir_NIR", None)
            if folder is None:
                print("[WARN] start_exif_NIR_step: no output_dir_NIR set")
                done({}, "No NIR folder")
                return
            cb = lambda exif_data, msg: done(exif_data, msg)
            self.start_exif_worker(folder=str(folder), band="NIR", callbacks=[cb])
        except Exception as e:
            print(f"[ERROR] start_exif_NIR_step: {e}")
            done({}, f"Error starting EXIF NIR: {e}")


    # ====== Gestion des altitudes et points GPS  =================================

    def start_alti_GPS(self, done, *args):
        """Démarre le worker Alti_GPS dans un thread séparé."""
        self.thread_alti = QtCore.QThread()
        self.worker_alti = Worker.Alti_GPS(self.output_dir_VIS)
        self.worker_alti.moveToThread(self.thread_alti)

        # Signals worker -> slots main thread
        self.worker_alti.progress.connect(self.on_alti_progress)
        self.worker_alti.error.connect(self.on_alti_error)
        self.worker_alti.finished.connect(lambda msg: done("VIS_ALTI_OK", msg))
        self.worker_alti.plot_data.connect(self.on_alti_plot_data)

        # Cleanup
        self.worker_alti.finished.connect(self.thread_alti.quit)
        self.worker_alti.finished.connect(self.worker_alti.deleteLater)
        self.thread_alti.finished.connect(self.thread_alti.deleteLater)

        # Start worker
        self.thread_alti.started.connect(self.worker_alti.run)
        self.thread_alti.start()

    def on_alti_progress(self, pct: int) -> None:
        """Slot appelé par WorkerAlti_GPS.progress"""
        try:
            self.phase_label.setText(f"Altitude: {pct}%")
            self.progress_bar.setValue(pct)
        except Exception as e:
            print("Error in on_alti_progress:", e)

    def on_alti_error(self, message: str) -> None:
        """Slot pour gérer les erreurs du worker Alti_GPS"""
        try:
            self.btn_1221.setEnabled(True)
            print("[ERROR] Alti_GPS worker:", message)
            Uti.show_info_message("IRDrone", "Alti_GPS worker error", message)
            self.close()
        except Exception as e:
            print(f'error in on_alti_error {e}')

    def on_alti_plot_data(self, distance_cum, alt_ground_norm, alt_sea_level_norm):
        """Slot appelé dans le thread principal pour stocker les données et tracer."""
        try:
            # Stocker pour un usage ultérieur
            self._last_plot_data = (distance_cum, alt_ground_norm, alt_sea_level_norm)

            # Tracer dans le thread principal, de manière sûre
            import matplotlib.pyplot as plt
            plt.figure(figsize=(12, 5))
            plt.plot(distance_cum, alt_sea_level_norm, label="Drone")
            plt.plot(distance_cum, alt_ground_norm, label="Sol")
            plt.xlabel("Distance cumulée (m)")
            plt.ylabel("Altitude normalisée (m)")
            plt.title("Profil altitude drone / sol")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            out_file_path = Uti.safe_path(Path(self.missionFolder) / "FlightAnalytics" / "fly_vertical_profil.png")
            plt.savefig(out_file_path, dpi=150)
            plt.close()
            print(Style.GREEN + f'Fly vertical profil saved successfully in  {out_file_path}' + Style.RESET)
        except Exception as e:
            print(f"[ERROR] in on_alti_plot_data: {e}")




    # === Message final. Indique à l'utilisateur le nom du dossier de la mission =====


    def _final_mission_done(self, done: Callable, exif_or_nir_data, msg: str):
        """
        Dernière étape de la chaîne :
        affiche le message final à l’utilisateur.
        """
        try:
            mission_dir = self.mission_parameters.get("File path mission", None)

            if mission_dir is None:
                Uti.show_info_message(
                    "IRDrone",
                    "Mission completed",
                    "The mission is completed, but the folder could not be determined."
                )

            else:
                Uti.show_info_message(
                    "IRDrone",
                    "Mission created",
                    f"The mission has been successfully created:\n\n{mission_dir}"
                )

            # Réactiver le bouton si c'est ton workflow
            if hasattr(self, "btn_1221"):
                self.btn_1221.setEnabled(True)

            self.data_signal_from_dialog_create_file_structure_to_main_window.emit(self.validate_answer, self.mission_parameters)
            # Fin de la chaîne → appeler done pour être conforme à l’API
            done("END", msg)
            self.close()

        except Exception as e:
            print(f"[ERROR] in _final_mission_done: {e}")
            done(None, f"Final callback error: {e}")

    def show_plot(self, distance_cum, alt_ground_norm, alt_sea_level_norm):
        import matplotlib.pyplot as plt

        plt.figure(figsize=(12, 5))

        plt.plot(distance_cum, alt_sea_level_norm, label="Drone (réf sol min)", linewidth=2)
        plt.plot(distance_cum, alt_ground_norm, label="Sol (réf sol min)", linewidth=2)

        plt.xlabel("Distance cumulée (m)")
        plt.ylabel("Altitude normalisée (m)")
        plt.title("Profil altitude drone / sol")
        plt.grid(True)
        plt.legend()
        plt.tight_layout()

        plt.show()

    # ==================================================
    #            autres modules de la
    #    class Window_create_file_structure(QDialog)
    # ==================================================


    def load_takeoff_image(self):
        """
        Ouvrir une boîte de dialogue pour sélectionner une image.
        Ici on n'admet uniquement des images au format DNG
        Elles doivent provenir de la caméra du drone qui capture des images dans le spectre VISIBLE (VIS).
        """

        directory = os.path.abspath('/')   # DD racine
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image", directory, "Images (*.dng)")  # (*.png *.xpm *.jpg *.dng)")

        try:
            if file_name:
                self.path_image_takeoff = Path(Uti.safe_path(file_name))
                self.name_image_takeoff = os.path.basename(self.path_image_takeoff)
                self.dirname_image_takeoff = str(self.path_image_takeoff.parent)
                self.suffix_image_takeoff = self.path_image_takeoff.suffix
                self.mission_parameters_light["File path"] = file_name
                if file_name.lower().endswith(".dng"):
                    # Charger une image DNG avec rawpy. Attention cette étape est longue ...
                    self.progress_bar.setValue(10)
                    with rawpy.imread(file_name) as raw:
                        rgb = raw.postprocess()
                        self.progress_bar.setValue(20)
                    image_bytes = imageio.imsave(imageio.RETURN_BYTES, rgb, format='png')
                    self.progress_bar.setValue(30)
                    image = QImage.fromData(image_bytes)
                    pixmap = QPixmap.fromImage(image)
                else:
                    # Charger et afficher l'image
                    pixmap = QPixmap(file_name)
                self.progress_bar.setValue(40)
                # Redimensionner l'image pour qu'elle s'adapte à l'espace disponible
                pixmap = pixmap.scaled(self.image_label.width(), self.image_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
                self.image_label.setPixmap(pixmap)

                # Extraire les données EXIF et obtenir les coordonnées GPS
                # Attention :   l'altitude donnée par les données Exif des images (.dng) prises par le drone DJI Mavic Air 2 est
                # l'altitude mesurée par rapport au sol au point de décollage.
                # L'information de la clé Exif  "GPS GPSAltitudeRef" qui renvoie 0  (cad "Above Sea Level") est erronée !!
                latitude_exif, longitude_exif, altitude_exif, date_time_excif, maker, model, id_camera = Uti.extract_exif(file_name)
                latitude, longitude, self.altitude_DJI = Uti.convert_coordinates(latitude_exif, longitude_exif, altitude_exif)
                self.progress_bar.setValue(45)

                # Utilise API IGN (Institut Géographique National. France) ou bien OpenTopoData (Monde)
                # Renvoie en fonction des coordonnées GPS, l'altitude géographique.
                # C'est le niveau du sol par rapport au niveau de la mer
                self.dic_info_geo = Geo.extract_alti_IGN([(latitude, longitude)], bypass=False)[0]
                self.progress_bar.setValue(60)
                # Utilise l'API Open Street Map pour obtenir les données géographiques (lieu-dit, ville, code postal, ...)
                self.dic_info_geo = Geo.extract_geoTag(self.dic_info_geo, bypass=False)
                self.progress_bar.setValue(80)
                # Mettre à jour le label d'information avec les données de localisation
                geo_data = f"Wpt: take-off \n" \
                           f"image: {file_name.lower()}\n" \
                           f"Coordonnées: {round(self.dic_info_geo.get('lat'),6)}      {round(self.dic_info_geo.get('lon'),6)}   Alti. {round(self.dic_info_geo.get('z'),3)} m  (above sea level)\n" \
                           f"Date: {date_time_excif}  \n" \
                           f"Lieu-dit: {self.dic_info_geo.get('lieu_dit')}    {self.dic_info_geo.get('road') if self.dic_info_geo.get('road') is not None else ''}\n"\
                           f"Commune: {self.dic_info_geo.get('ville')}    {self.dic_info_geo.get('code_postal')}     {self.dic_info_geo.get('dept')} \n" \
                           f"Région: {self.dic_info_geo.get('region')} \n" \
                           f"Pays: {self.dic_info_geo.get('pays')}"

                self.info_Geo_label.setText(geo_data)
                self.info_Geo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
                Uti.center_on_screen(self.central_widget, screen_Id=0, screen_adjust=(1, 1), window_display_size=(800, 600))
                self.btn_NextStep.setAutoDefault(True)
                self.btn_NextStep.setEnabled(True)
                self.btn_NextStep.setStyleSheet("background-color: darkGray; color:Black;")
                self.progress_bar.setValue(100)

            else:
                return

        except Exception as e:
            print("error 1 in on_load_Image_take_off:", e)

        try:
            self.Date_Exif = str(date_time_excif)
            self.mission_parameters_light['Maker'] = str(maker)
            self.mission_parameters_light['Model'] = str(model)
            self.mission_parameters_light['Body serial number'] = str(id_camera)
            self.mission_parameters_light['Date Exif'] = str(date_time_excif)
            self.py_date_time = datetime.strptime(str(date_time_excif), "%Y:%m:%d %H:%M:%S")
            self.mission_parameters_light['Location'] = self.dic_info_geo['ville']
            if self.dic_info_geo['lat'] >= 0:
                self.mission_parameters_light["GPS N-S"] = "N"
            else:
                self.mission_parameters_light["GPS N-S"] = "S"
            if self.dic_info_geo['lon'] >= 0:
                self.mission_parameters_light["GPS E-W"] = "E"
            else:
                self.mission_parameters_light["GPS E-W"] = "W"
            self.mission_parameters_light["GPS lat"] = self.dic_info_geo['lat']
            if self.dic_info_geo['lon'] < 10:
                self.mission_parameters_light["GPS lon"] = f"00{self.dic_info_geo['lon']}"
            elif 10 <= self.dic_info_geo['lon'] < 10:
                self.mission_parameters_light["GPS lon"] = f"0{self.dic_info_geo['lon']}"
            else:
                self.mission_parameters_light["GPS lon"] = f"{self.dic_info_geo['lon']}"

            self.mission_parameters_light["GPS lon"] = str(self.dic_info_geo['lon'])
            self.mission_parameters_light["GPS alti"] = str(self.dic_info_geo['z'])  # altitude above sea level
            self.mission_parameters_light["GPS coordinate"] = f"{self.mission_parameters_light['GPS N-S']} {str(self.dic_info_geo['lat'])} {self.mission_parameters_light['GPS E-W']} {self.dic_info_geo['lon']}"

            self.mission_parameters_light["GPS drone alti"] = self.altitude_DJI  # altitude above takeoff point
        except Exception as e:
            print("error 2 in load_takeoff_image ", e)


        try:
            self.mission_parameters_light["original name image take-off"] = self.name_image_takeoff
            num = int(Path(self.name_image_takeoff).stem.split("_")[-1])
            suffix = self.suffix_image_takeoff[1:]  # example "DNG"
            self.mission_parameters_light["name image take-off"] = f"VIS_{num:04d}.{suffix}"
            self.mission_parameters_light["suffix image take-off"] = suffix
        except Exception as e:
            print("error 3 in load_takeoff_image ", e)
        return

    def build_mission_folder_name(self):
        """
        Create mission folder
        Convert date and time objects to strings
        """
        try:

            date_str = self.py_date.strftime('%Y%m%d')
            time_str = self.py_time.strftime('%H%M')
            if self.location_field.text():
                fileName = f"FLY-{date_str}-{time_str}-{self.location_field.text()}"
            else:
                fileName = f"FLY-{date_str}-{time_str}"
            path = os.path.join(self.pref.default_user_dir, fileName)
            directory = os.path.normpath(path).replace('\\', '/')
            return directory
        except Exception as e:
            print("error in build_mission_folder_name :", e)

    def create_mission_folder(self):
        """
        Create the mission folder structure (only creates missing folders,
        never overwrites existing ones).
        """
        base_dir = Path(self.build_mission_folder_name())

        # List of subfolders to create inside the mission folder
        subfolders = [
            self.AerialPhotoFolder,
            self.AnalyticFolder,
            self.ImgIRdroneFolder,
            self.SynchroFolder,
            self.MappingFolder,
            self.CameraFolder,
            self.AerialPhotoFolder_VIS,
            self.AerialPhotoFolder_NIR,
        ]

        try:
            # Create base directory + subfolders
            for sf in subfolders:
                (base_dir / sf).mkdir(parents=True, exist_ok=True)

            # Optional: change folder icons
            try:
                change_icon = True
                icon_dir = Path(self.pref.default_app_dir) / "Icon"

                if change_icon:
                    Uti.change_icon(base_dir, icon_dir / "IRdrone_appli.ico")
                    Uti.change_icon(base_dir / self.AerialPhotoFolder, icon_dir / "AerialPhoto.ico")
                    Uti.change_icon(base_dir / self.AnalyticFolder, icon_dir / "FlyAnalytic.ico")
                    Uti.change_icon(base_dir / self.ImgIRdroneFolder, icon_dir / "ImgIRdrone.ico")
                    Uti.change_icon(base_dir / self.SynchroFolder, icon_dir / "synchro.ico")
                    Uti.change_icon(base_dir / self.MappingFolder, icon_dir / "mapping_MULTI.ico")
                    Uti.change_icon(base_dir / self.CameraFolder, icon_dir / "camera.ico")

            except Exception as e:
                print("Error in create_mission_folder (icon change):", e)

        except Exception as e:
            print("Error in create_mission_folder (creating folder tree):", e)

        # --- Save mission_parameters JSON ---
        try:
            mission_parameters_path = base_dir / "FlightAnalytics" / "mission_parameters.json"
            mission_parameters_path.parent.mkdir(parents=True, exist_ok=True)

            with open(mission_parameters_path, "w", encoding="utf-8") as f:
                json.dump(self.mission_parameters, f, ensure_ascii=False, indent=4)

            # Build the message for the user
            txt_date = f"{self.py_date_time.year}{self.py_date_time.month}{self.py_date_time.day}"
            txt_time = f"{self.py_date_time.hour}{self.py_date_time.minute}"
            txt_comment = str(self.mission_parameters['Location'])

        except Exception as e:
            print("Error in create_mission_folder (saving JSON):", e)

    def _init_date_mission(self):
        try:
            self.date_label = QLabel("Date:")
            self.date_field = QLineEdit(self)
            # Date formatting
            date_pattern = QRegularExpression(r"^(?:19|20)\d\d/(?:0[1-9]|1[0-2])/(?:0[1-9]|[12][0-9]|3[01])$")
            date_validator = QRegularExpressionValidator(date_pattern, self)
            self.date_field.setValidator(date_validator)
            self.date_field.setInputMask("9999/99/99")
            self.date_field.setPlaceholderText("YYYY/MM/DD")
            if int(self.py_date_time.month) < 10:
                str_month = str(f"0{self.py_date_time.month}")
            else:
                str_month = str(self.py_date_time.month)
            if int(self.py_date_time.day) < 10:
                str_day = str(f"0{self.py_date_time.day}")
            else:
                str_day = str(f"{self.py_date_time.day}")
            date_takeoff = f"{str(self.py_date_time.year)}/{str_month}/{str_day}"
            self.date_field.setText(date_takeoff)
            self.date_field.setStyleSheet("background-color: gray; color: white;")
            self.date_field.setReadOnly(True)

            self.date_layout = QHBoxLayout()
            self.date_layout.addWidget(self.date_label)
            self.date_layout.addWidget(self.date_field)
            self.layout.addLayout(self.date_layout)
        except Exception as e:
            print("error in _init_date_mission : ", e)

    def _init_time_mission(self):
        try:
            self.time_label = QLabel("Hour:")
            self.time_field = QLineEdit(self)
            # Time formatting
            time_pattern = QRegularExpression(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
            time_validator = QRegularExpressionValidator(time_pattern, self)
            self.time_field.setValidator(time_validator)
            self.time_field.setInputMask("99:99")
            self.time_field.setPlaceholderText("hh:mm")
            if int(self.py_date_time.hour) < 10:
                str_hour = str(f"0{self.py_date_time.hour}")
            else:
                str_hour = str(self.py_date_time.hour)
            if int(self.py_date_time.minute) < 10:
                str_minute = str(f"0{self.py_date_time.minute}")
            else:
                str_minute = str(self.py_date_time.minute)

            time_takeoff = f"{str_hour}/{str_minute}"
            self.time_field.setText(time_takeoff)

            self.time_field.setStyleSheet("background-color: gray; color: white;")
            self.time_field.setReadOnly(True)

            self.time_layout = QHBoxLayout()
            self.time_layout.addWidget(self.time_label)
            self.time_layout.addWidget(self.time_field)
            self.layout.addLayout(self.time_layout)
        except Exception as e:
            print("error _init_time_mission : ", e)

    def _init_location(self):
        try:
            self.location_label = QLabel("Location :")
            self.location_field = QLineEdit(self)
            self.location_field.setText(self.mission_parameters_light['Location'])
            self.location_field.setStyleSheet(
                "background-color: white; "
                "color: black; "
                "font-family: 'Comic Sans MS'; "
                "font-size: 12pt; "
                "font-weight: bold; "
                "font-style: italic;"
            )
            self.location_field.setReadOnly(False)
            self.location_layout = QHBoxLayout()
            self.location_layout.addWidget(self.location_label)
            self.location_layout.addWidget(self.location_field)
            self.layout.addLayout(self.location_layout)
        except Exception as e:
            print("error _init_location : ", e)

    def _init_GPS(self):
        try:
            self.GPS_label = QLabel("GPS:")
            # Formatting GPS coordinates
            self.GPS_NS_lat: str = None
            self.GPS_lat: float = None
            self.GPS_lat_field = QLineEdit(self)
            GPS_lat_pattern = QRegularExpression(r"^[NS] \d{2}\.\d{5}$")
            GPS_lat_validator = QRegularExpressionValidator(GPS_lat_pattern, self)
            self.GPS_lat_field.setValidator(GPS_lat_validator)
            self.GPS_lat_field.setText("N ")
            self.GPS_lat_field.setInputMask(">A 99.99999;_")  # "A" will allow entry of any letter compatible with [NS] GPS_lat_pattern
            self.GPS_lat_field.setPlaceholderText("N  00.00000")
            self.GPS_lat_field.setText(f"E 48.858370 ")
            self.GPS_lat_field.setStyleSheet("background-color: gray; color: white;")
            self.GPS_lat_field.setReadOnly(True)

            try:
                lat_takeoff = f"{self.mission_parameters_light['GPS N-S']} {str(self.mission_parameters_light['GPS lat'])}"
                self.GPS_lat_field.setText(lat_takeoff)
            except Exception as e:
                print("error in init_fields   GPS field  : ", e)

            self.GPS_NS: str = None
            self.GPS_EW: str = None
            self.GPS_lon: float = None
            self.GPS_lon_field = QLineEdit(self)
            GPS_lon_pattern = QRegularExpression(r"^[EW] \d{3}\.\d{5}$")
            GPS_lon_validator = QRegularExpressionValidator(GPS_lon_pattern, self)
            self.GPS_lon_field.setValidator(GPS_lon_validator)
            self.GPS_lon_field.setText("E ")
            self.GPS_lon_field.setInputMask(">A 999.99999;_")
            self.GPS_lon_field.setPlaceholderText("E 000.00000")
            self.GPS_lon_field.setText(f"E 2.294481 ")
            self.GPS_lon_field.setStyleSheet("background-color: gray; color: white;")
            self.GPS_lon_field.setReadOnly(True)
            try:
                if float(self.mission_parameters_light['GPS lon']) < 10:
                    str_longitude = f"00{str(self.mission_parameters_light['GPS lon'])}"
                elif 10 <= float(self.mission_parameters_light['GPS lon']) < 100:
                    str_longitude = f"0{str(self.mission_parameters_light['GPS lon'])}"
                else:
                    str_longitude = f"{str(self.mission_parameters_light['GPS lon'])}"

                lon_takeoff = f"{self.mission_parameters_light['GPS E-W']} {str_longitude}"
                self.GPS_lon_field.setText(lon_takeoff)
            except Exception as e:
                print("error in init_fields   GPS field  : ", e)

            self.GPS_alti = str(self.mission_parameters_light['GPS alti'])

            self.GPS_layout = QHBoxLayout()
            self.GPS_layout.addWidget(self.GPS_label)
            self.GPS_layout.addWidget(self.GPS_lat_field)
            self.GPS_layout.addWidget(self.GPS_lon_field)
            self.layout.addLayout(self.GPS_layout)
        except Exception as e:
            print("error _init_GPS : ", e)

    def _init_description(self):
        try:
            self.description_label = QLabel("Short description :")
            self.description_field = QLineEdit(self)

            self.description_layout = QHBoxLayout()
            self.description_layout.addWidget(self.description_label)
            self.description_layout.addWidget(self.description_field)
            self.layout.addLayout(self.description_layout)
            self.description_field.setText("Phase de test")
            self.description_field.setStyleSheet(
                "background-color: white; "
                "color: black; "
                "font-family: 'Comic Sans MS'; "
                "font-size: 12pt; "
                "font-weight: bold; "
                "font-style: italic;"
            )
            self.description_field.setReadOnly(False)
        except Exception as e:
            print("error _init_description : ", e)

    def _init_pilot(self):
        try:
            self.pilot_Name: str = "Florine"
            self.pilot_ID: str = "FRA-RP-0000001957"

            self.pilot_label = QLabel("Pilot:")
            self.pilot_Name_field = QLineEdit(self)
            self.pilot_Name_field.setText(self.pilot_Name)
            self.pilot_Name_field.setStyleSheet(
                "background-color: white; "
                "color: black; "
                "font-family: 'Comic Sans MS'; "
                "font-size: 12pt; "
                "font-weight: bold; "
                "font-style: italic;"
            )
            self.pilot_Name_field.setReadOnly(False)

            self.pilot_ID_field = QLineEdit(self)
            self.pilot_ID_field.setText(self.pilot_ID)

            self.pilot_layout = QHBoxLayout()
            self.pilot_layout.addWidget(self.pilot_label)
            self.pilot_layout.addWidget(self.pilot_Name_field)
            self.pilot_layout.addWidget(self.pilot_ID_field)
            self.layout.addLayout(self.pilot_layout)
        except Exception as e:
            print("error _init_pilot : ", e)

    def _init_VIS_camera(self):
        try:
            # camera VIS part 1
            self.camera_VIS_maker: str = self.mission_parameters_light["Maker"]
            self.camera_VIS_ID: str = self.mission_parameters_light["Model"]

            self.camera_VIS_label: str = QLabel("Camera VIS  maker | Id:")
            self.camera_VIS_maker_field = QLineEdit(self)
            self.camera_VIS_maker_field.setText(self.camera_VIS_maker)
            self.camera_VIS_maker_field.setStyleSheet("background-color: gray; color: white;")
            self.camera_VIS_maker_field.setReadOnly(True)
            self.camera_VIS_ID_field = QLineEdit(self)
            self.camera_VIS_ID_field.setText(self.camera_VIS_ID)
            self.camera_VIS_ID_field.setStyleSheet("background-color: gray; color: white;")
            self.camera_VIS_ID_field.setReadOnly(True)

            self.camera_VIS_layout = QHBoxLayout()
            self.camera_VIS_layout.addWidget(self.camera_VIS_label)
            self.camera_VIS_layout.addWidget(self.camera_VIS_maker_field)
            self.camera_VIS_layout.addWidget(self.camera_VIS_ID_field)
            self.layout.addLayout(self.camera_VIS_layout)

            # camera VIS part 2
            self.camera_VIS_timelaspe: int = 2
            self.camera_VIS_deltatime: float = 0.00

            self.camera_VIS_t_label = QLabel("       timelapse | delta time in s:")
            self.camera_VIS_tlapse_field = QLineEdit(self)
            self.camera_VIS_tlapse_field.setText(str(self.camera_VIS_timelaspe))
            self.camera_VIS_deltatime_field = QLineEdit(self)
            self.camera_VIS_deltatime_field.setText(str(self.camera_VIS_deltatime))

            self.camera_VIS_t_layout = QHBoxLayout()
            self.camera_VIS_t_layout.addWidget(self.camera_VIS_t_label)
            self.camera_VIS_t_layout.addWidget(self.camera_VIS_tlapse_field)
            self.camera_VIS_t_layout.addWidget(self.camera_VIS_deltatime_field)
            self.layout.addLayout(self.camera_VIS_t_layout)

            # camera VIS part 3
            self.image_VIS_format: str = os.path.splitext(self.mission_parameters_light["File path"])[1][1:]
            self.image_VIS_format_label = QLabel("Image VIS format:")
            self.image_VIS_format_field = QLineEdit(self)
            self.image_VIS_format_field.setText(self.image_VIS_format)
            self.image_VIS_format_field.setStyleSheet("background-color: gray; color: white;")
            self.image_VIS_format_field.setReadOnly(True)

            self.image_VIS_format_layout = QHBoxLayout()
            self.image_VIS_format_layout.addWidget(self.image_VIS_format_label)
            self.image_VIS_format_layout.addWidget(self.image_VIS_format_field)
            self.layout.addLayout(self.image_VIS_format_layout)
        except Exception as e:
            print("error _init_VIS_camera : ", e)

    def _init_NIR_camera(self):
        try:
            # camera NIR part 1
            self.camera_NIR_maker: str = "SJCam"
            self.camera_NIR_ID: str = "M20"

            self.camera_NIR_label = QLabel("Camera NIR  maker | Id:")
            self.camera_NIR_maker_field = QLineEdit(self)
            self.camera_NIR_maker_field.setText(self.camera_NIR_maker)
            self.camera_NIR_ID_field = QLineEdit(self)
            self.camera_NIR_ID_field.setText(self.camera_NIR_ID)

            self.camera_NIR_layout = QHBoxLayout()
            self.camera_NIR_layout.addWidget(self.camera_NIR_label)
            self.camera_NIR_layout.addWidget(self.camera_NIR_maker_field)
            self.camera_NIR_layout.addWidget(self.camera_NIR_ID_field)
            self.layout.addLayout(self.camera_NIR_layout)

            # camera NIR part 3
            self.image_NIR_format: str = "RAW"
            self.image_NIR_format_label = QLabel("Image NIR format:")
            self.image_NIR_format_field = QLineEdit(self)
            self.image_NIR_format_field.setText(self.image_NIR_format)

            self.image_NIR_format_layout = QHBoxLayout()
            self.image_NIR_format_layout.addWidget(self.image_NIR_format_label)
            self.image_NIR_format_layout.addWidget(self.image_NIR_format_field)
            self.layout.addLayout(self.image_NIR_format_layout)
            # camera NIR part 2
            self.camera_NIR_timelaspe: int = 3  # in second
            self.camera_NIR_deltatime: float = 3894.91  # in second

            self.camera_NIR_t_label = QLabel("       timelapse in s | delta time in s:")
            self.camera_NIR_tlapse_field = QLineEdit(self)
            self.camera_NIR_tlapse_field.setText(str(self.camera_NIR_timelaspe))
            self.camera_NIR_deltatime_field = QLineEdit(self)
            self.camera_NIR_deltatime_field.setText(str(self.camera_NIR_deltatime))

            self.camera_NIR_t_layout = QHBoxLayout()
            self.camera_NIR_t_layout.addWidget(self.camera_NIR_t_label)
            self.camera_NIR_t_layout.addWidget(self.camera_NIR_tlapse_field)
            self.camera_NIR_t_layout.addWidget(self.camera_NIR_deltatime_field)
            self.layout.addLayout(self.camera_NIR_t_layout)
        except Exception as e:
            print("error _init_NIR_camera : ", e)

    def _init_NIR_filter(self):
        try:
            # camera NIR part 4 (filter)
            self.image_NIR_filter_maker: str = "KOLARI VISION USA"  # Optic Concept LP830
            self.image_NIR_filter_band: int = 810  # 830

            self.image_NIR_filter_label = QLabel("NIR Filter    maker | band in nm:")
            self.image_NIR_filter_maker_field = QLineEdit(self)
            self.image_NIR_filter_maker_field.setText(self.image_NIR_filter_maker)
            self.image_NIR_filter_band_field = QLineEdit(self)
            self.image_NIR_filter_band_field.setText(str(self.image_NIR_filter_band))

            self.image_NIR_filter_layout = QHBoxLayout()
            self.image_NIR_filter_layout.addWidget(self.image_NIR_filter_label)
            self.image_NIR_filter_layout.addWidget(self.image_NIR_filter_maker_field)
            self.image_NIR_filter_layout.addWidget(self.image_NIR_filter_band_field)
            self.layout.addLayout(self.image_NIR_filter_layout)
        except Exception as e:
            print("error _init_NIR_filter : ", e)

    def update_image_takeoff(self, verbose: bool = True) -> None:
        """
        Copies the take-off image to the exact destination path provided
        in mission_parameters["path mission image take-off"].

        The method checks:
          - that the source file exists,
          - that the destination directory exists,
        and performs the copy. Raises RuntimeError on failure.

        Returns
        -------
        None
        """
        try:
            # Retrieve paths (string → Path)
            src_path = Path(self.mission_parameters["original File path take-off"])  # full path incl. filename

            dst_path = Path(self.mission_parameters["path mission image take-off"])  # full path incl. filename

            if verbose: print(Style.GREEN + f"Sauvegarde de l'image du takeoff : {src_path}\n  → vers : {dst_path}" + Style.RESET)

            # --- Sanity checks ------------------------------------------------------
            if not src_path.exists():
                raise RuntimeError(Style.YELLOW + f"Le fichier source n'existe pas : {src_path}" + Style.RESET)

            if not src_path.is_file():
                raise RuntimeError(Style.YELLOW + f"Le chemin source n'est pas un fichier : {src_path}" + Style.RESET)

            dst_dir = dst_path.parent
            if not dst_dir.exists():
                raise RuntimeError(Style.YELLOW + f"Le dossier de destination n'existe pas : {dst_dir}" + Style.RESET)

            if not dst_dir.is_dir():
                raise RuntimeError(Style.YELLOW + f"Le chemin parent de destination n'est pas un dossier : {dst_dir}" + Style.RESET)

            # --- Effective copy -----------------------------------------------------
            try:
                shutil.copy2(src_path, dst_path)
                if verbose: print(Style.GREEN + f"Image du take off copiée avec succès vers : {dst_path}" + Style.RESET)
            except Exception as exc:
                raise RuntimeError(f"Erreur pendant la copie : {exc}") from exc
        except Exception as e1:
            print(f'error in update_image_takeoff: {e1}')
            import traceback
            traceback.print_exc()

    def update_transfert_info_VIS_dng_json(self, verbose: bool = True) -> None:
        """
        Initialise ou met à jour le fichier transfer_info_VIS_dng.json
        dans <missionFolder>/FlightAnalytics.

        Le fichier existant n'est réécrit que si les valeurs importantes
        ont réellement changé.
        """

        # ----------------------------------------------------------
        # Vérifications préalables minimales
        # ----------------------------------------------------------
        required_keys = ["File path mission"]
        for key in required_keys:
            if key not in self.mission_parameters:
                print(f"DEBUG: Clé manquante dans mission_parameters : {key}")
                return

        if "name image take-off" not in self.mission_parameters_light:
            print("[DEBUG]: clé 'name image take-off' absente dans mission_parameters_light")
            return

        # ----------------------------------------------------------
        # Construction du dictionnaire nouveau (MÀJ potentielle)
        # ----------------------------------------------------------
        dic_light = {
            "spectral_band": "VIS",
            "img_suffix": "dng",
            "tkoff": {
                "outputFolder": str(Path(self.missionFolder) / "AerialPhotography" / "VIS"),
                "original name": self.mission_parameters_light["original name image take-off"],
                "idMin": 1,
                "idMax": 1,
                "listCopiedImages": [
                    self.mission_parameters_light["name image take-off"]
                ]
            },

            "sync": {
                "outputFolder": str(Path(self.missionFolder) / "AerialPhotography" / "VIS")
            },

            "fly": {
                "outputFolder": str(Path(self.missionFolder) / "AerialPhotography" / "VIS")
            }
        }

        # ----------------------------------------------------------
        # Chemin du fichier JSON cible
        # ----------------------------------------------------------
        folder_fa = Path(self.missionFolder) / "AerialPhotography" / "VIS"
        json_file = folder_fa / "transfer_info_VIS_dng.json"
        folder_fa.mkdir(parents=True, exist_ok=True)

        # ----------------------------------------------------------
        # Si le fichier existe, charger et comparer
        # ----------------------------------------------------------
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    old_dic = json.load(f)
            except Exception as exc:
                if verbose: print(Style.YELLOW + f"ERREUR: Impossible de lire {json_file}\n{exc}" + Style.RESET)
                old_dic = None

            if isinstance(old_dic, dict):

                # ------------------------------------------------------
                # Comparaison sélective
                # ------------------------------------------------------

                def same_value(key: str) -> bool:
                    """Compare les clés de haut niveau (str -> Any)"""
                    return old_dic.get(key.lower()) == dic_light.get(key.lower())

                def same_output_folder(key: str) -> bool:
                    """Compare uniquement la sous-clé outputFolder."""
                    old = old_dic.get(key, {})
                    new = dic_light.get(key, {})
                    return isinstance(old, dict) and isinstance(new, dict) \
                           and old.get("outputFolder") == new.get("outputFolder")

                all_same = True

                # Comparaison complète sur spectral_band / img_suffix
                for key in ["spectral_band", "img_suffix"]:
                    if not same_value(key):
                        print(Style.YELLOW + f'DEBUG  ECART lors de Comparaison complète sur spectral_band / img_suffix")' + Style.RESET)
                        all_same = False
                        break

                # Comparaison SEULEMENT outputFolder pour sync / fly
                if all_same and not same_output_folder("sync"):
                    print(Style.YELLOW + "DEBUG: Modifications détectées → same_output_folder(sync)." + Style.RESET)
                    print(Style.YELLOW + f'NEUTRALISE' + Style.RESET)
                    all_same = True  # False
                    return

                if all_same and not same_output_folder("fly"):
                    print(Style.YELLOW + "DEBUG: Modifications détectées → same_output_folder(fly)." + Style.RESET)
                    print(Style.YELLOW + f'NEUTRALISE' + Style.RESET)
                    all_same = True  # False
                    return

                if all_same:
                    if verbose: print("DEBUG: Aucun changement détecté → fichier conservé tel quel.")
                    return

                print(Style.YELLOW + "DEBUG: Modifications détectées → réécriture du fichier JSON." + Style.RESET)

        # ----------------------------------------------------------
        # Écriture du fichier (nouveau ou mise à jour)
        # ----------------------------------------------------------
        try:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(dic_light, f, indent=4, ensure_ascii=False)

            if verbose: print(f"DEBUG: Fichier écrit/mis à jour : {json_file}")

        except Exception as exc:
            print(f"ERREUR: Impossible d'écrire le fichier JSON : {json_file}\n{exc}")

    def update_mission_parameters(self):
        """
        Initialise le dictionnaire self.mission_parameters.
        First checks the validity of the data (date, time, GPS coordinates, etc.)
        """

        self.fields_consistency_analysis()
        self.missionFolder = self.build_mission_folder_name()
        try:
            self.mission_parameters = {
                "File path mission": self.missionFolder,
                "original File path take-off": self.mission_parameters_light["File path"],  # original file path of the take-off image
                "original name image take-off": self.mission_parameters_light["original name image take-off"],
                "name image take-off": self.mission_parameters_light["name image take-off"],
                "suffix image take-off": self.mission_parameters_light["suffix image take-off"],
                "path mission image take-off": str(Path(self.missionFolder) / "AerialPhotography" / "VIS" / self.mission_parameters_light["name image take-off"]),
                "Body serial number": self.mission_parameters_light["Body serial number"],
                "Date Exif": f"{Uti.datePy2dateJson(self.py_date)} {Uti.timePy2timeJson(self.py_time)}",
                "Date": Uti.datePy2dateJson(self.py_date),
                "Time": Uti.timePy2timeJson(self.py_time),
                "Location": self.location_field.text(),
                "Description": self.description_field.text(),
                "GPS coordinate": f"{self.GPS_NS} {str(self.GPS_lat)} {self.GPS_EW} {str(self.GPS_lon)}",
                "GPS N-S": self.GPS_NS,
                "GPS lat": float(self.GPS_lat),
                "GPS E-W": self.GPS_EW,
                "GPS lon":  float(self.GPS_lon),
                "GPS alti": float(self.GPS_alti),
                "GPS drone alti": self.mission_parameters_light["GPS drone alti"],
                "Pilot": self.pilot_Name_field.text(),
                "Pilot ID": self.pilot_ID_field.text(),
                "camera VIS maker": self.camera_VIS_maker_field.text(),
                "camera VIS ID": self.camera_VIS_ID_field.text(),
                "camera VIS timelapse": int(self.camera_VIS_tlapse_field.text()),
                "camera VIS deltatime": float(self.camera_VIS_deltatime_field.text()),
                "img VIS ext": self.image_VIS_format_field.text(),
                "camera NIR maker": self.camera_NIR_maker_field.text(),
                "camera NIR ID": self.camera_NIR_ID_field.text(),
                "camera NIR timelapse": int(self.camera_NIR_tlapse_field.text()),
                "camera NIR deltatime": float(self.camera_NIR_deltatime_field.text()),
                "original img NIR ext": self.image_NIR_format_field.text(),
                "camera NIR filter maker": self.image_NIR_filter_maker_field.text(),
                "camera NIR filter band": int(self.image_NIR_filter_band_field.text()),
                "synchro": "Synchro/synchro.npy",
                "output": "ImgIRdrone",
                "visible": "AerialPhotography/VIS/*.DNG",
                "nir": "AerialPhotography/NIR/*.DNG",
                "AerialPhotography folder": self.AerialPhotoFolder,
                "FlightAnalytics folder": self.AnalyticFolder,
                "ImgIRdrone folder": self.ImgIRdroneFolder,
                "Synchro folder": self.SynchroFolder,
                "ODM folder": self.MappingFolder,
                "cameras folder": self.CameraFolder
            }

            # print(f'DEBUG  update_mission_parameters  original name image take-off {self.mission_parameters_light["original name image take-off"]}')
            # print(f'DEBUG  update_mission_parameters  name image take-off {self.mission_parameters_light["name image take-off"]}')
        except Exception as e:
            print('error in update_mission_parameters ', e)

    def fields_consistency_analysis(self):
        """
        Checks the validity of the data ( GPS coordinates, etc.)
        """
        try:
            # ------------- validation of GPS input ------------------------
            gps_lat_str = self.GPS_lat_field.text()
            gps_lon_str = self.GPS_lon_field.text()

            # Latitude field
            if len(gps_lat_str.split()) == 2:
                self.GPS_NS, lat_value = gps_lat_str.split()
                if float(lat_value) > 90.:
                    Uti.show_info_message("IRDrone", "Please provide a valid latitude!", " lat in [0°, 90°]",
                                          icon=QMessageBox.Icon.Warning)
                    return
                self.GPS_lat = float(lat_value)

            # Longitude field
            if len(gps_lon_str.split()) == 2:
                self.GPS_EW, lon_value = gps_lon_str.split()
                if float(lon_value) > 180.:
                    Uti.show_info_message("IRDrone", "Please provide a valid longitude!", " lon in [0°, 180°]",
                                          icon=QMessageBox.Icon.Warning)
                    return
                self.GPS_lon = float(lon_value)

            # ------------- processing of entry location
            # ------------- processing of entry short description
            # ------------- processing of entry Pilot
            # ------------- processing of entry VIS camera
            # ------------- processing of entry NIR camera

        except ValueError as e:
            print("Error:", e)
            Uti.show_info_message("IRDrone", str(e), "", icon=QMessageBox.Icon.Warning)
            return
        except Exception as e:
            print("Unexpected error in fields_consistency_analysis :", e)
            Uti.show_info_message("IRDrone", "An unexpected error occurred.", "", icon=QMessageBox.Icon.Warning)
            return




    # =================================================================
    #
    #                  MODULES OBSOLETES ...
    #
    # =================================================================

# --------------------------------------------------------------------------------------------
#
#              Window_Load_TakeOff_Image
#
#                Load take-off image
#
# --------------------------------------------------------------------------------------------
class Window_Load_TakeOff_Image(QDialog):

    def __init__(self, parent):
        super().__init__(parent)
        self.image_label = None  # declare (placeholder)
        self.main_layout = None  # idem if needed
        self.central_widget = None
        self.btn_load_image = None
        self.btn_NextStep = None,
        self.btnPreviousStep = None
        self.progress_bar = None
        self.image_display_size = None
        self.empty_pixmap = None
        self.layout = None

        self.info_Geo_label = None
        self.mission_parameters_light: dict = dict()
        self.dic_info_geo: dict = dict()
        self.init_mission_parameters_light()
        self.altitude_DJI: float = 0.0
        self.Date_Exif = None
        self.py_date_time = None

        self.path_image_takeoff: Optional[Path] = None
        self.dirname_image_takeoff: str = None
        self.name_image_takeoff: str = None
        self.suffix_image_takeoff: str = None

        # self.default_app_dir = os.path.join("C:/", "Program Files", "IRdrone")
        # self.default_user_dir = os.path.join("C:/", "Air-Mission")
        # self.default_user_dir = Path("~/Air-Mission").expanduser()
        self.default_user_dir = OUTPUT_FOLDER_NAME
        assert self.default_user_dir.exists(), f"User directory does not exist: {self.default_user_dir}"
        # self.default_user_dir.mkdir(parents=True, exist_ok=True)

        self.prefScreen = Uti.Prefrence_Screen()  # Initializing screen preferences

        self.initGUI()  # Initializing the GUI  Using attributes previously created
        self.setLayout(self.main_layout)


    def initGUI(self):
        """
            Initializes the GUI.
            The graphical interface has 4 areas.

            > Area N° 1: “Load take-off image” control button.
                         User can only upload images in dng format. The images taken in the visible spectrum of the drone camera are of the dng type.

            > Area N° 2: Graphic zone for displaying the image.
                         The image display is a little long due to the size of the drone's dng images but also the extraction of EXIF data and
                         the querying of geographic information systems. The progress bar indicates the progress of the image loading.

            > Area N° 3: Text zone for displaying temporal and geographic location information of the image.
                         The shooting date and GPS coordinates (latitude, longitude) are extracted from the EXIF tag.
                         The geographical altitude is obtained by querying the IGN database (France)
                         The map location data (road, place, village, postal code, etc.) are obtained by interrogating the Open Street Map database.

            > Area N° 4: "Previous step" and "Next step" control buttons and a progress bar.
                         The "Previous step" command button is only available if an image has been loaded
        """
        try:
            #   Setting the top command bar and window dimensions

            self.setStyleSheet("background-color: white; color: black;")
            self.setWindowTitle("Choose the image taken by the drone during takeoff.")
            icon_path = os.path.join(self.default_app_dir, "Icon", "IRDrone.ico")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                self.setWindowIcon(icon)
        except Exception as e:
            print("error   in initUI  ", e)

        # Set layout and widgets
        # Create the central widget
        self.central_widget = QWidget()
        # Create the main layout
        self.main_layout = QVBoxLayout(self.central_widget)

        # Create the four zones (sublayouts) and add them to the main layout
        zone1_layout = QHBoxLayout()
        zone2_layout = QVBoxLayout()
        zone3_layout = QVBoxLayout()
        zone4_layout = QHBoxLayout()

        self.main_layout.addLayout(zone1_layout)
        self.main_layout.addLayout(zone2_layout)
        self.main_layout.addLayout(zone3_layout)
        self.main_layout.addLayout(zone4_layout)

        # Area 1

        self.btn_load_image = QPushButton("Load take-off image")
        self.btn_load_image.setFixedWidth(300)
        self.btn_load_image.setStyleSheet("background-color: darkBlue; color: white;")
        zone1_layout.addWidget(self.btn_load_image)

        # Area 2  Image area.

        # ----------------  Creating a neutral image -----------------
        width = self.prefScreen.windowDisplaySize[1]
        num_images = 1
        # print("TEST dim Ecran   l x H :", int((width - 100) / num_images), int((width - 100) / num_images * 3 / 4))
        self.image_display_size = (int((width - 100) / num_images), int((width - 100) / num_images * 3 / 4))  # image area size
        # Create an empty pixmap of the desired size and adjust the size if necessary
        self.empty_pixmap = QPixmap(int((width - 100) / num_images), int((width - 100) / num_images * 3 / 4))
        self.empty_pixmap.fill(QColor(Qt.GlobalColor.darkGray))  # transparent, gray, darkYellow etc)
        # Adjust the size if necessary
        self.empty_pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)

        self.image_label = QLabel("Image taken during takeoff.")
        zone2_layout.addWidget(self.image_label)
        self.image_label.setPixmap(self.empty_pixmap)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Area 3    Location information
        self.info_Geo_label = QLabel("Location information")
        self.info_Geo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_Geo_label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)  # Add a frame
        zone3_layout.addWidget(self.info_Geo_label)
        self.info_Geo_label.setStyleSheet("background-color: gray;")
        self.info_Geo_label.setFixedHeight(150)

        default_geo_data = f"Wpt:  \n" \
                           f"image:\n" \
                           f"Coordonnées:\n" \
                           f"Date:  \n" \
                           f"Lieu-dit: \n" \
                           f"Commune: \n" \
                           f"Région:   \n" \
                           f"Pays: "

        self.info_Geo_label.setText(default_geo_data)
        self.info_Geo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        #  Area 4    Previous Step an Next Step button
        self.btnPreviousStep = QPushButton("<< previous step")
        self.btnPreviousStep.setFixedWidth(100)
        self.btnPreviousStep.setStyleSheet("background-color: darkGray; color: black;")
        self.btn_NextStep = QPushButton("next step >>>>")
        self.btn_NextStep.setFixedWidth(100)
        self.btn_NextStep.setStyleSheet("background-color: darkGray; color: black;")
        # Disable Next Step  button
        self.btn_NextStep.setAutoDefault(False)
        self.btn_NextStep.setEnabled(False)
        self.btn_NextStep.setStyleSheet("background-color: darkGray; color:gray;")

        zone4_layout.addWidget(self.btnPreviousStep)
        zone4_layout.addWidget(self.btn_NextStep)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setStyleSheet("QProgressBar { color: white; }")
        zone4_layout.addWidget(self.progress_bar)
        self.progress_bar.setValue(0)

        self.btn_load_image.clicked.connect(self.load_takeoff_image)
        self.btn_NextStep.clicked.connect(self.placeholder_method)
        self.btnPreviousStep.clicked.connect(self.cancel_clicked)

        # Set window size
        width: int = 680  # 700
        height: int = 700  # 500
        self.setGeometry(0, 0, width, height)

        # self.resize(600, 600)
        Uti.center_on_screen(self, screen_Id=1)


    def init_mission_parameters_light(self):
        """
        Initialise une version simplifiée du  dictionnaire self.mission_parameters_light.

        """
        try:
            self.mission_parameters_light = {
                "File path mission": None,
                "original File path take-off": None,
                "File path": "C:/",
                "Maker": "Nimbus",
                "Model": "Old",
                "Body serial number": "570608",
                "Date Exif": "1900:01:01 12:00:00",
                "Date": '1900-01-01',
                "Time": f"12:00:00",
                "Location": "Paris",
                "Description": "Eiffel tower",
                "GPS coordinate": f"N 48.858370 E 2.294481",
                "GPS N-S": "N",
                "GPS lat": 48.858370,
                "GPS E-W": "E",
                "GPS lon":  2.294481,
                "GPS alti": 33.5,
                "GPS drone alti": 330,
                "AerialPhotography folder": "AerialPhotography",
                "FlightAnalytics folder": "FlightAnalytics",
                "ImgIRdrone folder": "ImgIRdrone",
                "Synchro folder": "Synchro",
                "ODM folder": "mapping_MULTI",
                "cameras folder": "cameras"
            }
            # print( "TEST   sortie de   init_mission_parameters       self.mission_parameters_light  :", self.mission_parameters_light)
        except Exception as e:
            print('error in init_mission_parameters', e)


    @staticmethod
    def placeholder_method():
        """
        Dummy (empty) method for connecting the "Next Step" button.
        The "real" connection is in the open_window_11 method of the Main_Window class of the main module.
        def open_window_11(self):  de la class Main_Window() du module principal.
        The line of code is:
        self.window_11.btn_NextStep.clicked.connect(self.open_window_12)  # Connect Window_create_file_structure signal to Main_Window method

        If we delete the line of code in initGUI method: self.btn_NextStep.clicked.connect(self.placeholder_method)
        as well as this method (placeholder_method) the code works perfectly!
        """
        try:
            Uti.show_info_message("IRDrone", "Your takeoff point has been taken into account for this mission. \n ",
                                  "You can complete the settings for this mission in the next step.")
            pass

        except Exception as e:
            print("error in placeholder_method       message :", e)


    def closeEvent(self, event):
        event.accept()


    def load_takeoff_image(self):
        """
        Ouvrir une boîte de dialogue pour sélectionner une image.
        Ici on n'admet uniquement des images au format DNG
        Elles doivent provenir de la caméra du drone qui capture des images dans le spectre VISIBLE (VIS).
        """

        directory = os.path.abspath('/')   # DD racine
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image", directory, "Images (*.dng)")  # (*.png *.xpm *.jpg *.dng)")

        try:
            if file_name:
                self.path_image_takeoff = Path(Uti.safe_path(file_name))
                self.name_image_takeoff = os.path.basename(self.path_image_takeoff)
                self.dirname_image_takeoff = str(self.path_image_takeoff.parent)
                self.suffix_image_takeoff = self.path_image_takeoff.suffix
                self.mission_parameters_light["File path"] = file_name
                if file_name.lower().endswith(".dng"):
                    # Charger une image DNG avec rawpy. Attention cette étape est longue ...
                    self.progress_bar.setValue(10)
                    with rawpy.imread(file_name) as raw:
                        rgb = raw.postprocess()
                        self.progress_bar.setValue(20)
                    image_bytes = imageio.imsave(imageio.RETURN_BYTES, rgb, format='png')
                    self.progress_bar.setValue(30)
                    image = QImage.fromData(image_bytes)
                    pixmap = QPixmap.fromImage(image)
                else:
                    # Charger et afficher l'image
                    pixmap = QPixmap(file_name)
                self.progress_bar.setValue(40)
                # Redimensionner l'image pour qu'elle s'adapte à l'espace disponible
                pixmap = pixmap.scaled(self.image_label.width(), self.image_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
                self.image_label.setPixmap(pixmap)

                # Extraire les données EXIF et obtenir les coordonnées GPS
                # Attention :   l'altitude donnée par les données Exif des images (.dng) prises par le drone DJI Mavic Air 2 est
                # l'altitude mesurée par rapport au sol au point de décollage.
                # L'information de la clé Exif  "GPS GPSAltitudeRef" qui renvoie 0  (cad "Above Sea Level") est erronée !!
                latitude_exif, longitude_exif, altitude_exif, date_time_excif, maker, model, id_camera = Uti.extract_exif(file_name)
                latitude, longitude, self.altitude_DJI = Uti.convert_coordinates(latitude_exif, longitude_exif, altitude_exif)
                self.progress_bar.setValue(45)

                # Utilise API IGN (Institut Géographique National. France) ou bien OpenTopoData (Monde)
                # Renvoie en fonction des coordonnées GPS, l'altitude géographique.
                # C'est le niveau du sol par rapport au niveau de la mer
                self.dic_info_geo = Geo.extract_alti_IGN([(latitude, longitude)], bypass=False)[0]
                self.progress_bar.setValue(60)
                # Utilise l'API Open Street Map pour obtenir les données géographiques (lieu-dit, ville, code postal, ...)
                self.dic_info_geo = Geo.extract_geoTag(self.dic_info_geo, bypass=False)
                self.progress_bar.setValue(80)
                # Mettre à jour le label d'information avec les données de localisation
                geo_data = f"Wpt: take-off \n" \
                           f"image: {file_name.lower()}\n" \
                           f"Coordonnées: {round(self.dic_info_geo.get('lat'),6)}      {round(self.dic_info_geo.get('lon'),6)}   Alti. {round(self.dic_info_geo.get('z'),3)} m  (above sea level)\n" \
                           f"Date: {date_time_excif}  \n" \
                           f"Lieu-dit: {self.dic_info_geo.get('lieu_dit')}    {self.dic_info_geo.get('road') if self.dic_info_geo.get('road') is not None else ''}\n"\
                           f"Commune: {self.dic_info_geo.get('ville')}    {self.dic_info_geo.get('code_postal')}     {self.dic_info_geo.get('dept')} \n" \
                           f"Région: {self.dic_info_geo.get('region')} \n" \
                           f"Pays: {self.dic_info_geo.get('pays')}"

                self.info_Geo_label.setText(geo_data)
                self.info_Geo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
                Uti.center_on_screen(self.central_widget, screen_Id=0, screen_adjust=(1, 1), window_display_size=(800, 600))
                self.btn_NextStep.setAutoDefault(True)
                self.btn_NextStep.setEnabled(True)
                self.btn_NextStep.setStyleSheet("background-color: darkGray; color:Black;")
                self.progress_bar.setValue(100)

            else:
                return

        except Exception as e:
            print("error 1 in on_load_Image_take_off:", e)


        try:
            self.Date_Exif = str(date_time_excif)
            self.mission_parameters_light['Maker'] = str(maker)
            self.mission_parameters_light['Model'] = str(model)
            self.mission_parameters_light['Body serial number'] = str(id_camera)
            self.mission_parameters_light['Date Exif'] = str(date_time_excif)
            self.py_date_time = datetime.strptime(str(date_time_excif), "%Y:%m:%d %H:%M:%S")
            self.mission_parameters_light['Location'] = self.dic_info_geo['ville']
            if self.dic_info_geo['lat'] >= 0:
                self.mission_parameters_light["GPS N-S"] = "N"
            else:
                self.mission_parameters_light["GPS N-S"] = "S"
            if self.dic_info_geo['lon'] >= 0:
                self.mission_parameters_light["GPS E-W"] = "E"
            else:
                self.mission_parameters_light["GPS E-W"] = "W"
            self.mission_parameters_light["GPS lat"] = self.dic_info_geo['lat']
            if self.dic_info_geo['lon'] < 10:
                self.mission_parameters_light["GPS lon"] = f"00{self.dic_info_geo['lon']}"
            elif 10 <= self.dic_info_geo['lon'] < 10:
                self.mission_parameters_light["GPS lon"] = f"0{self.dic_info_geo['lon']}"
            else:
                self.mission_parameters_light["GPS lon"] = f"{self.dic_info_geo['lon']}"

            self.mission_parameters_light["GPS lon"] = str(self.dic_info_geo['lon'])
            self.mission_parameters_light["GPS alti"] = str(self.dic_info_geo['z'])  # altitude above sea level
            self.mission_parameters_light["GPS coordinate"] = f"{self.mission_parameters_light['GPS N-S']} {str(self.dic_info_geo['lat'])} {self.mission_parameters_light['GPS E-W']} {self.dic_info_geo['lon']}"

            self.mission_parameters_light["GPS drone alti"] = self.altitude_DJI  # altitude above takeoff point
        except Exception as e:
            print("error 2 in load_takeoff_image ", e)


        try:
            self.mission_parameters_light["original name image take-off"] = self.name_image_takeoff
            num = int(Path(self.name_image_takeoff).stem.split("_")[-1])
            suffix = self.suffix_image_takeoff[1:]  # example "DNG"
            self.mission_parameters_light["name image take-off"] = f"VIS_{num:04d}.{suffix}"
            self.mission_parameters_light["suffix image take-off"] = suffix
        except Exception as e:
            print("error 3 in load_takeoff_image ", e)
        return


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        try:
            self.close()
        except Exception as e:
            print("error in Window_Load_TakeOff_Image   cancel_clicked :", e)










