# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Selection of reference images for the stages of the mission.
#   29/10/2023   V002
# ---------------------------------------------------------------------------------
import warnings
# warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message="sipPyTypeDict\\(\\) is deprecated.*"
)

import os
import sys
import shutil
import rawpy
from functools import partial
from typing import Any, Dict, Optional, Tuple, List, Union
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
import numpy as np
import exifread
import re
import json
from PIL import Image
import io

# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar, QFileDialog,  QMessageBox, QApplication
from PyQt6.QtGui import QPixmap, QColor, QImage, QCloseEvent, QIcon
from PyQt6.QtCore import Qt
# -------------- IRDrone Library -------------------------------------
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import center_on_screen
from IRD_Interactive_color_style import Style


"""
      This code allows you to choose the reference images for a mission and then distribute the different images in the
     mission phases. For each category of images/spectral band (VIS taken by the drone camera and NIR taken by the on-board IR camera) 
     the user must choose 5 reference images:
         > Take-off image.      In general for the DJI drone this will be the first image recorded HYPERLAPSE_0001.
                                For the on-board NIR camera we can visually choose the image which is "closest" to
                                the first image from the drone.  
         > First sync image.    This is the first stable image where the ARUCO target is visible. 
                                The ideal is that the ARUCO sight has just started to rotate.
         > Last sync image.     This is the last image where the ARUCO target is visible. 
                                Ideally the ARUCO sight movement cycle should be completed.
         > First fly image.     This is the image taken by the drone when it begins its trajectory above the area 
                                to be studied. Altitude, orientation and speed are stabilized.
         > last fly image.      This is the image taken by the drone when it ends its trajectory above the area to 
                                be studied. There is no harm in choosing the last image taken by the camera during 
                                the mission until landing. However, this risks unnecessarily increasing the calculation
                                time and the alignment of the images is not guaranteed after leaving the area to be 
                                studied (variable altitude and too high speed).

     The "Mission" :
        The mission has five step:
        > Step 1       : Take-off.
        > Step 2 (SYNC): Synchronization.
        > Step 3       : Route to the area to be studied.
        > Step 4 (FLY) : Flight over the area to be studied which constitutes the flight itself and named FLY.
        > Step 5       : Return to the take-off point.
    
     Take-off:
        Takeoff is a quick step where after triggering the NIR camera (SJCam) the rotors are started and the drone rises
        to 2-3 m above the ground. The drone (DJI) shot in hyper lapse mode is then triggered.
        This moment will be the reference point for the entire mission (zero point of the timeline).
    
     The synchronization (SYNC):
        The synchronization step is carried out at the take-off point at an altitude of approximately 2 m and at the fixed point.
        The drone is above a sight (ARUCO) which rotates on itself.
        The set of images associated with this synchronization step goes from the first image of the mission taken by
        the drone and the image taken just before the start of step 3.
    
     The flight (FLY):
        The FLY includes the images recorded during the flight in stabilized mode over the area to be studied.
        The trajectory above the area connects a starting point (Fly start point) to an ending point (Fly end point)
        Note: As a general rule, images taken during the flight to the area to be studied are excluded from flight images.
        In fact, the altitude varies quickly and the drone moves at high speed. However, this rule is not obligatory.

"""


class LoadVisNirImagesDialog(QDialog):
    flagAllImageOK = False
    num_images = 5
    flags = [False] * num_images

    def __init__(self,
                 width: int,
                 height: int,
                 spectral_band: str = None,
                 suffix: str = None,
                 folderMission: Optional[Path] = None,
                 path_image_takeoff: Optional[Path] = None,
                 original_path_image_takeoff: Optional[Path] = None,
                 verbose=False):
        super().__init__()

        if folderMission is None or not folderMission.exists():
            raise ValueError(Style.YELLOW + f"⚠  Invalid folderMission: {folderMission}" + Style.RESET)

        # ---- Basic GUI and screen parameters
        self.number_images_reference: int = 5
        self.pref_screen: Uti.Prefrence_Screen = Uti.Prefrence_Screen()
        self.screen_width: int = width
        self.screen_height: int = height
        self.target_screen_index: int = self.pref_screen.defaultScreenID
        self.screen_adjust: float = self.pref_screen.screenAdjust
        self.window_display_size: tuple[int, int] = self.pref_screen.windowDisplaySize
        self.verbose = verbose

        # ---- spectral_band and image suffix
        # First mission image | First image of the Sync sequence | Last image of the Sync sequence | First Fly image | Last Fly image
        # list of paths to the 5 reference images
        try:

            # ---- Image availability flags
            self.image_0_available: bool = False
            self.image_first_sync_available: bool = False
            self.image_last_sync_available: bool = False
            self.image_first_fly_available: bool = False
            self.image_last_fly_available: bool = False
            self.flags: list[bool] = [False] * self.number_images_reference

            self.currentSpectralBand: str = spectral_band
            self.listRefPath = [None] * self.number_images_reference
            self.listImgRefPath = [None] * self.number_images_reference

            self.folderMissionPath = folderMission
            self.spectral_band: str = spectral_band
            self.img_suffix: str = suffix
            self.info_dng = None
            if self.spectral_band.lower() in ("vis", "visible", "vi"):
                self.outputTakeoffFolder = (Path(self.folderMissionPath) / "AerialPhotography" / spectral_band)
                self.outputTakeoffFolder = Uti.safe_path(self.outputTakeoffFolder)
                self.info_dng = self.load_phases_mission_info(Path(self.outputTakeoffFolder).parent, suffix, verbose=False)
                if self.info_dng:
                    self._set_image_flags_from_info(self.info_dng)
                    self.info_vis_dng_available = True
                else:
                    if self.verbose: print(Style.YELLOW + f'⚠  transfer_info_VIS_dng.json n\'a pas été détecté ...' + Style.RESET)
            elif self.spectral_band.lower() in ("nir", "ir", "near infrared"):
                self.img_suffix = "dng"
                self.spectral_band = "NIR"
                self.outputTakeoffFolder = (Path(self.folderMissionPath) / "AerialPhotography" / spectral_band)
                self.outputTakeoffFolder = Uti.safe_path(self.outputTakeoffFolder)
                self.info_dng = self.load_phases_mission_info(Path(self.outputTakeoffFolder).parent, suffix, verbose=False)
                if self.info_dng:
                    self._set_image_flags_from_info(self.info_dng)
                    self.info_nir_dng_available = True
                else:
                    if self.verbose: print(Style.YELLOW + f'⚠  transfer_info_NIR_dng.json n\'a pas été détecté ...' + Style.RESET)
            else:
                self.img_suffix = "jpg"
                print(Style.YELLOW + f'⚠  suffix jpg non pris en charge ...' + Style.RESET)
        except Exception as e:
            print(f'error  in __init__   spectral_band and image suffix:  {e}')

        # ---- Directories
        self.currentUserDir: str = self.pref_screen.current_directory
        self.user_dir: str = self.currentUserDir
        self.new_user_dir: str = self.currentUserDir
        self.outputFlightAnalyticsFolder: Path = Path(self.folderMissionPath) / "FlightAnalytics"
        self.outputTakeoffFolder.mkdir(parents=True, exist_ok=True)
        self.outputFlightAnalyticsFolder.mkdir(parents=True, exist_ok=True)



        self.image_labels: list[QLabel] = [QLabel() for _ in range(self.number_images_reference)]
        self.image_name_labels: list[QLabel] = [QLabel() for _ in range(self.number_images_reference)]
        self.img_legend: list[str] = ["Take-off image:",
                                      "First sync image.",
                                      "Last sync image.",
                                      "First fly image.",
                                      "Last fly image."]

        # ---- Command buttons
        self.btn_command: list[QPushButton] = []
        self.btn_load_all_images: Optional[QPushButton] = None
        self.btn_validate_load_all_images: Optional[QPushButton] = None
        self.btn_help: Optional[QPushButton] = None

        # ---- GUI progress bar
        self.progress_bar: Optional[QProgressBar] = None

        # ---- Load previous transfer info if available
        self.timeline: list[dict] = []
        self.path_image_takeoff: Optional[Path] = path_image_takeoff   # Take-off image path
        self.original_path_image_takeoff = original_path_image_takeoff  # Original take-off image path
        self.image_takeoff_available: bool = False   # Takeoff image path
        self.image_display_size: tuple[int, int] = (100, 100)  # Image display size (will be set in init_GUI)
        self.empty_pixmap: Optional[QPixmap] = None  # Empty pixmap placeholder (will be set in init_GUI)


        # ---- Initialize takeoff image availability
        self.init_image_takeoff_available(path_image_takeoff, original_path_image_takeoff)

        # ---- Initialize GUI
        self.init_GUI()


    def init_GUI(self) -> None:
        """
        Initialize the main GUI for loading mission images, setting up image placeholders,
        captions, command buttons, and progress bar. Supports both VIS and NIR image types
        and can pre-load reference images if available.

        The GUI is structured in three main sections:
        1. Top command bar with buttons to load individual reference images.
        2. Middle image area displaying placeholders and captions for each reference image.
        3. Bottom command bar with buttons to load all images, validate, or access help,
           along with a progress bar.

        Buttons are disabled initially and will be enabled when the required reference
        images are loaded. Pre-existing loaded images are automatically displayed if the
        interactive sequence has been run previously.

        Attributes (from self)
        ----------------------
        screen_width : int
        screen_height : int
        num_images : int
        spectral_band : str
        image_labels : list[QLabel]
        image_name_labels : list[QLabel]
        btn_command : list[QPushButton]
        btn_load_all_images : QPushButton
        btn_validate_load_all_images : QPushButton
        btn_help : QPushButton
        progress_bar : QProgressBar

    Returns
    -------
    None
        """

        try:

            self.setStyleSheet("background-color: white; color: black;")
            # Setting the top command bar and window dimensions
            self.setWindowTitle(f"Load the {self.spectral_band} images of the mission")
            icon_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "IRDrone.ico")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                self.setWindowIcon(icon)
            self.setGeometry(0, 0, self.screen_width, self.screen_height)


            self.currentSpectralBand = self.spectral_band
            # Creating placeholders for images
            self.image_labels = [QLabel() for _ in range(self.number_images_reference)]
            # Creating placeholders for image captions
            self.img_legend = ["Take-off image:",
                               "First sync image.",
                               "Last sync image.",
                               "First fly image.",
                               "Last fly image."]
            self.image_name_labels = [QLabel(self.img_legend[i]) for i in range(self.number_images_reference)]

            # Creating command bar buttons (one per image)
            btn_legend = ["Load first mission image.",
                          "Load first sync image.",
                          "Load last sync image.",
                          "Load first fly image.",
                          "Load last fly image."]
            # Connecting buttons to actions
            button_width = int(0.9 * (self.screen_width // self.number_images_reference))
            self.btn_command = [QPushButton(btn_legend[i]) for i in range(self.number_images_reference)]
            for btn in self.btn_command:
                btn.setFixedWidth(button_width)
                btn.setStyleSheet("background-color: darkGray; color: black;")

            # Button to load all mission images once reference images are chosen
            button_width = int(0.7 * (self.screen_width // self.number_images_reference))
            self.btn_load_all_images = QPushButton("validate phase mission images")
            self.btn_load_all_images.setFixedWidth(button_width)
            self.btn_help = QPushButton("Help")
            self.btn_help.setStyleSheet("background-color: darkGreen; color: white;")
            self.btn_help.setFixedWidth(button_width)

            # button_width = int(0.7 * (self.screen_width // self.number_images_reference))
            # self.btn_validate_load_all_images = QPushButton("Validate (next step) >>>")
            # self.btn_validate_load_all_images.setFixedWidth(button_width)
            # self.btn_validate_load_all_images.setEnabled(False)
            # self.btn_validate_load_all_images.setStyleSheet("background-color: gray; color: darkGray;")

            # Progress bar when loading all images
            self.progress_bar = QProgressBar()
            self.progress_bar.setValue(0)

            # Creating the layout of the main window
            layout = QVBoxLayout()  # main layout
            # top layout for command bar
            top_layout = QHBoxLayout()
            for btn in self.btn_command:
                top_layout.addWidget(btn)
            # middle layout for images and their captions
            middle_layout = QHBoxLayout()  # uses vertical layouts for labels
            for label in self.image_name_labels:
                middle_layout.addWidget(label)

            # ---------------- Image area: Creating a neutral placeholder image -----------------
            self.image_display_size = (
                int((self.screen_width - 100) / self.number_images_reference),
                int((self.screen_width - 100) / self.number_images_reference * 3 / 4)
            )  # image area size
            # Create an empty pixmap of the desired size
            self.empty_pixmap = QPixmap(*self.image_display_size)
            self.empty_pixmap.fill(QColor(Qt.GlobalColor.gray))  # neutral gray
            # Adjust size if necessary
            self.empty_pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            # Display the take-off image (if available) as the first image
            # This folder will be used as the default to search for other images

            # Creating a list to store pairs (image, QLabel)
            image_label_pairs = []
            for index, image_label in enumerate(self.image_labels):
                image_label.setPixmap(self.empty_pixmap)
                name_label = self.image_name_labels[index]
                name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # center QLabel text

                # CSS styling to reduce spacing between image and caption
                image_label.setStyleSheet("margin-bottom: 100px;")
                image_label.setStyleSheet("margin-top: 30px;")
                # Add each (image-QLabel) pair to the list
                image_label_pairs.append((image_label, name_label))

            # Creating a list to store pairs (image, legend)
            middle_layout = QHBoxLayout()
            for image_label, name_label in zip(self.image_labels, self.image_name_labels):
                # Creating vertical layout for each pair (image, legend)
                pair_layout = QVBoxLayout()
                pair_layout.addWidget(image_label)
                pair_layout.addWidget(name_label)
                # Add pair layout to middle horizontal layout
                middle_layout.addLayout(pair_layout)

            # bottom layout for "load mission images" buttons and progress bar
            bottom_layout = QVBoxLayout()
            bottom_command = QHBoxLayout()
            bottom_command.addWidget(self.btn_load_all_images)
            bottom_command.addWidget(self.btn_help)
            bottom_layout.addLayout(bottom_command)
            bottom_layout.addWidget(self.progress_bar)
            # bottom_command.addWidget(self.btn_validate_load_all_images)

            layout.addLayout(top_layout)
            layout.addLayout(middle_layout)
            layout.addLayout(bottom_layout)

            center_on_screen(self, self.target_screen_index, self.screen_adjust, self.window_display_size)

            # Disable btn_load_all_images at startup. Will be enabled when all five reference images are loaded
            self.btn_load_all_images.setEnabled(False)
            self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: gray;")

            # Load images if interactive sequence was already completed once
            if self.image_0_available:
                print(Style.GREEN + '[INFO] Loading takeoff image' + Style.RESET)
                self.open_takeOff_sync_and_fly_image_VIS_or_NIR(self.spectral_band, self.img_suffix, 0)
            elif self.image_takeoff_available and self.spectral_band == "VIS":
                self.open_takeoff_image(self.path_image_takeoff)

            if self.image_first_sync_available:
                print(Style.GREEN + '[INFO] Loading first sync image' + Style.RESET)
                self.open_takeOff_sync_and_fly_image_VIS_or_NIR(self.spectral_band, self.img_suffix, 1)
            if self.image_last_sync_available:
                print(Style.GREEN + '[INFO] Loading last sync image VIS' + Style.RESET)
                self.open_takeOff_sync_and_fly_image_VIS_or_NIR(self.spectral_band, self.img_suffix, 2)
            if self.image_first_fly_available:
                print(Style.GREEN + '[INFO] Loading first fly image VIS' + Style.RESET)
                self.open_takeOff_sync_and_fly_image_VIS_or_NIR(self.spectral_band, self.img_suffix, 3)
            if self.image_last_fly_available:
                print(Style.GREEN + '[INFO] Loading last fly image VIS' + Style.RESET)
                self.open_takeOff_sync_and_fly_image_VIS_or_NIR(self.spectral_band, self.img_suffix, 4)

            if all(self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")


            # Setting button actions
            for index, btn in enumerate(self.btn_command):
                btn.clicked.connect(partial(self.open_image, index, self.image_labels[index], self.image_name_labels[index], self.img_suffix))
            self.btn_load_all_images.clicked.connect(self.on_load_all_images)
            # self.btn_validate_load_all_images.clicked.connect(self.on_validate_load_all_images)
            self.btn_help.clicked.connect(self.on_help)
            self.btn_help.setStyleSheet("background-color: green; color: white;")
            self.setLayout(layout)

        except Exception as e:
            print("Error in step2 init_GUI:", e)

    def closeEvent(self, event: QCloseEvent):
        try:
            if LoadVisNirImagesDialog.flagAllImageOK:
                LoadVisNirImagesDialog.flagAllImageOK = False
                event.accept()
            else:
                reply = QMessageBox.warning(self, "IRDrone", "You have not loaded the images of your mission.\n Do you really want to exit?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Yes:
                    event.accept()
                else:
                    event.ignore()
        except Exception as e:
            print("error in closeEvent(self, event: QCloseEvent) :", e)

    def on_validate_load_all_images(self):
        self.close()

    def on_load_all_images(self):
        """

        :return:

         The structure of image names is different depending on the camera.
          > For the DJI drone camera which takes images in the visible spectrum ("VIS") we have names
          like HYPERLAPSE_XXXX.DNG.   Here XXXX is the image number between 0001 and 9999.
          Note that we only recover dng files (they contain the correct EXIF data)

          > For the SJCam M20 camera embedded under the DJI drone and which takes images in
          the near infrared ("NIR") spectrum, we have two types of images:
           - jpeg images  (jpg format )
           - raw images (RAW format ).
          This double recording is automatic as soon as you record RAW images on the SJCam M20.
          The RAW format does not meet ADOBE standards.
          The EXIF data must therefore be found in the associated jpeg image.
         Finally for NIR images we have the name structures:
                - YYYY_MMDD_hhmmss_aaa.jpg where aaa is the (even) number of the image between 002 and 998.
                - YYYY_MMDD_hhmms's'_bbb.RAW where bbb = aaa -1 is the (odd) number between 001 and 997
          Note: By examining the names of the raw and jpg images we can deduce that the RAW image
          is saved before the associated jpeg image.

        """
        try:
            # ---------------- destination folders -----------------------------------------------------------
            outputFolder = self.folderMissionPath

            # ---------------------- number of the first and last images to transfer
            # Note:  Here we use the listImgRefPath table which contains the 5 reference images:
            #      - listImgRefPath[0]= takeoff image
            #      - listImgRefPath[1]= first image for synchro
            #      - listImgRefPath[2]= last image for synchro
            #      - listImgRefPath[3]= first image for fly
            #      - listImgRefPath[4]= last image for fly
            #      They correspond to the correct spectral band of image (NIR or VIS) because we are in the "on_load_all_images"
            #      procedure called by the button .btn_load_all_images which is in the window opened by
            #      load_Vis_Nir_images.LoadVisNirImagesDialog(... ,EXT, ... ) where EXT in {"NIR", "VIS"}.
            #      This procedure is therefore automatically in the right context.

            idMinFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[3]))[0].split("_")[-1])
            idMaxFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[4]))[0].split("_")[-1])

            idTakeoff = int(os.path.splitext(os.path.basename(self.listImgRefPath[0]))[0].split("_")[-1])

            outputFlyFolder = os.path.join(outputFolder, "AerialPhotography", self.currentSpectralBand)
            outputTakeoffFolder = os.path.join(outputFolder, "AerialPhotography", self.currentSpectralBand)
            outputFlightAnalyticsFolder = os.path.join(outputFolder, "FlightAnalytics")
            if not os.path.isdir(outputFlyFolder):
                # print("The destination folder ", outputFlyFolder, " of the images does not exist!")
                Uti.show_error_message(f"The destination folder {outputFlyFolder} for the images does not exist!\n"
                                       f"Check that you have already created the mission.")
                return


            idMinSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[1]))[0].split("_")[-1])
            idMaxSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[2]))[0].split("_")[-1])
            outputSyncFolder = os.path.join(outputFolder, "AerialPhotography", self.currentSpectralBand)
            if not os.path.isdir(outputSyncFolder):
                # print("The destination folder ", outputSyncFolder, " of the images does not exist!")
                Uti.show_error_message(f"The destination folder {outputSyncFolder} for the images does not exist!\n"
                                       f"Check that you have already created the mission.")
                return


            # --------------------- Entry folder  --------------------------------------
            #  Normally these are the DCIM files on the SD card of the drone and the NIR camera

            inputFolder = Path(self.listImgRefPath[0]).parent

            # Consistency test normally all images were extracted from the same folder
            consistency_choice = self.choice_of_reference_images_consistency_analysis()
            if not consistency_choice:
                if not os.path.isdir(inputFolder):
                    # print("The image input folder ", inputFolder, " does not exist.")
                    Uti.show_error_message(Style.YELLOW + f"⚠  The input folder {inputFolder} of the images does not exist!" + Style.RESET)
                    exit()
                return


            if self.currentSpectralBand == "VIS":
                # ----------   choose set of VIS images for the tkoff,  Sync  and Fly phase (dng) ----------------
                self.process_image_transfer(outputFlyFolder,
                                            "dng",
                                            outputSyncFolder, outputFlyFolder, outputFlightAnalyticsFolder,
                                            idTakeoff, idMinSync, idMaxSync, idMinFly, idMaxFly,
                                            progressSync=(0, 30), progressFly=(30, 100),
                                            )

            elif self.currentSpectralBand == "NIR":
                # ----------  choose set of NIR images for the  tkoff, Sync and Fly phase (jpg & raw) ----------------
                self.process_image_transfer(outputFlyFolder,
                                            "dng",
                                            outputSyncFolder, outputFlyFolder, outputFlightAnalyticsFolder,
                                            idTakeoff, idMinSync,  idMaxSync, idMinFly, idMaxFly,
                                            progressSync=[(0, 10), (0, 30)], progressFly=[(10, 100), (30, 100)],
                                            )

            # self.btn_validate_load_all_images.setEnabled(True)
            # self.btn_validate_load_all_images.setStyleSheet("background-color: gray; color: white;")

            # Optionnel : fermer le dialogue automatiquement
            self.accept()

            return getattr(self, "timeline", None)

        except Exception as e:
            print("error in on_load_all_images  :", e)
            return None

    def process_image_transfer(
            self,
            inputFolder: Union[str, Path],
            list_img_suffix: Union[str, List[str]],
            outputSyncFolder: Union[str, Path],
            outputFlyFolder: Union[str, Path],
            outputFlightAnalyticsFolder: Union[str, Path],
            idTk: int,
            idMinS: int,
            idMaxS: int,
            idMinF: int,
            idMaxF: int,
            offset: Union[int, List[int]] = 0,
            progressSync: Union[Tuple[int, int], List[Tuple[int, int]]] = (0, 30),
            progressFly: Union[Tuple[int, int], List[Tuple[int, int]]] = (30, 96),
    ) -> None:
        """
        Process images for one or multiple file suffix (dng, raw, jpg, tiff ...)
        and a self.currentSpectralBand  (VIS or NIR)
        Handles Takeoff, Sync and Fly phases, applies index offsets per suffix,
        and generates one JSON summary file *per suffix*.

        Parameters
        ----------
        inputFolder : Path or str
            Folder containing the original input images.

        list_img_suffix : str or list[str]
            Image suffix(s) to process, e.g. "jpg", "raw", or ["jpg", "raw"].
            Each suffix is processed independently and results in a separate JSON file.

        idTkoff : int
            Base index of the Takeoff image .

        idMinSync, idMaxSync : int
            Base index range for Sync-phase images .

        idMinFly, idMaxFly : int
            Base index range for Fly-phase images .

        progressSync, progressFly : tuple(int,int) or list[tuple], optional
            Progress-bar ranges. A single tuple applies to all suffix.
            Otherwise, provide one range per suffix.

        Returns
        -------
        None
        """
        try:
            # Normalize to Path
            inputFolder = Path(inputFolder)

            # Normalize list_img_suffix → list[str]
            if isinstance(list_img_suffix, str):
                list_img_suffix = [list_img_suffix]
            else:
                list_img_suffix = list(list_img_suffix)

            n = len(list_img_suffix)

            # Normalize offset
            if isinstance(offset, int):
                offset = [offset] * n
            elif isinstance(offset, list):
                if len(offset) != n:
                    raise ValueError("offset list must have same length as list_img_suffix")
            else:
                raise TypeError("offset must be int or list[int]")

            # Normalize progress ranges
            def normalize_progress(val):
                if isinstance(val, list) and isinstance(val[0], tuple):
                    return val
                return [tuple(val)] * n

            progressSync = normalize_progress(progressSync)
            progressFly = normalize_progress(progressFly)

            # ----------------------------------------------------------
            # Loop on suffix → generate one JSON per suffix
            # ----------------------------------------------------------
            for i, suffix in enumerate(list_img_suffix):

                sync_prog = progressSync[i]
                fly_prog = progressFly[i]

                # List of images with this suffix
                listInputImages = self.create_list_image_in_input_folder(inputFolder, suffix)

                output_Folder = Path(self.folderMissionPath, "AerialPhotography", self.spectral_band)

                # --- Takeoff (one image)
                takeOff_list = self.list_images_phase_mission(
                    Uti.safe_path(Path(inputFolder)), listInputImages,
                    Uti.safe_path(Path(outputFlyFolder)),
                    idTk, idTk,
                    *sync_prog
                )

                if self.spectral_band.lower() == "nir":
                    original_name = str(takeOff_list[0])
                else:
                    original_name = str(Path(self.original_path_image_takeoff).name)

                tkoff_data = {
                    "outputFolder": str(output_Folder),
                    "original name": original_name,
                    "idMin": idTk,
                    "idMax": idTk,
                    "listCopiedImages": takeOff_list,
                }

                # --- Sync phase
                sync_list = self.list_images_phase_mission(
                    Path(inputFolder), listInputImages,
                    Path(outputFlyFolder),
                    idMinS, idMaxS,
                    *sync_prog
                )
                sync_data = {
                    "outputFolder": str(output_Folder),
                    "idMin": idMinS,
                    "idMax": idMaxS,
                    "listCopiedImages": sync_list,
                }

                # --- Fly phase
                fly_list = self.list_images_phase_mission(
                    Path(inputFolder), listInputImages,
                    Path(outputFlyFolder),
                    idMinF, idMaxF,
                    *fly_prog
                )
                fly_data = {
                    "outputFolder": str(output_Folder),
                    "idMin": idMinF,
                    "idMax": idMaxF,
                    "listCopiedImages": fly_list,
                }

                # --- JSON creation (one per suffix)

                self.save_phases_mission_info(
                    output_folder=output_Folder,
                    input_folder=inputFolder,
                    img_suffix=suffix,  # IMPORTANT: single suffix
                    tkoff_data=tkoff_data,
                    sync_data=sync_data,
                    fly_data=fly_data
                )

            # Final global progress
            self.progress_bar.setValue(100)
        except Exception as e:
            print(f'error in process_image_transfer : {e}')

    def save_phases_mission_info(self, output_folder: Union[str, Path],
                                 input_folder: Union[str, Path],
                                 img_suffix: str,
                                 tkoff_data: Optional[Dict] = None,
                                 sync_data: Optional[Dict] = None,
                                 fly_data: Optional[Dict] = None,
                                 ) -> Path:
        """
        Save transfer information (Take Off, Synchronization and Fly phases) into a single JSON file.

        Parameters
        ----------
        output_folder : str | Path
            Folder where the JSON file will be created.
        input_folder : str | Path
            Source input folder.
        img_suffix : str
            Image type (e.g., "jpg", "raw", "dng").
        tkoff_data : dict | None, optional
            Data for the take-off phase:
                {"outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...]}
        sync_data : dict | None, optional
            Data for the Sync phase:
                {"outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...]}
        fly_data : dict | None, optional
            Data for the Fly phase:
                {"outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...]}


            Spectral_band , e.g.,
            VIS" wavelength range: [400, 700] nm
            NIR" wavelength range: [700, 1100]nm.


        Returns
        -------
        Path
            Path to the saved JSON file.
        """
        try:
            # Ensure output folder exists
            output_folder_spectral_band = Uti.safe_path(Path(output_folder).parent / self.spectral_band)
            Path(output_folder_spectral_band).mkdir(parents=True, exist_ok=True)

            # JSON file name including spectral band and image type (suffix)
            json_name = f"transfer_info_{self.spectral_band}_{img_suffix}.json"
            json_path = Uti.safe_path(Path(output_folder_spectral_band, json_name))

            # Base data
            data = {
                "spectral_band": str(self.spectral_band),
                "img_suffix": img_suffix,
                "inputFolder": str(input_folder),
            }

            # take-off data
            if tkoff_data:
                data["tkoff"] = {
                    "outputFolder": str(output_folder_spectral_band),
                    "original name": str(tkoff_data.get("original name", "")),
                    "idMin": int(tkoff_data.get("idMin", -1)),
                    "idMax": int(tkoff_data.get("idMax", -1)),
                    "listCopiedImages": list(map(str, tkoff_data.get("listCopiedImages", []))),
                }

            # Sync phase data
            if sync_data:
                data["sync"] = {
                    "outputFolder": str(output_folder_spectral_band),
                    "idMin": int(sync_data.get("idMin", -1)),
                    "idMax": int(sync_data.get("idMax", -1)),
                    "listCopiedImages": list(map(str, sync_data.get("listCopiedImages", []))),
                }

            # Fly phase data
            if fly_data:
                data["fly"] = {
                    "outputFolder": str(output_folder_spectral_band),
                    "idMin": int(fly_data.get("idMin", -1)),
                    "idMax": int(fly_data.get("idMax", -1)),
                    "listCopiedImages": list(map(str, fly_data.get("listCopiedImages", []))),
                }

            # Write JSON file
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            print(Style.GREEN + f"[INFO] JSON file saved: {json_path}" + Style.RESET)
            return json_path
        except Exception as e:
            print(f'error in save_phases_mission_info : {e}')


    def load_phases_mission_info(self,
                                 output_folder: Union[str, Path],
                                 img_suffix: str,
                                 verbose: bool = False
                                 ) -> Optional[Dict]:

        """
        Load transfer information (take off/Sync/Fly) previously saved in a JSON file.

        Parameters
        ----------
        output_folder : str | Path
            Folder containing the saved JSON file.
        spectral_band : str
             ("VIS" or "NIR").
        img_suffix : str
            Image type ("jpg", "raw", "dng").

        Returns
        -------
        dict | None
            A dictionary containing all loaded information:
            {
                "spectral_band": ...,
                "img_suffix": ...,
                "inputFolder": ...,
                "tkoff": { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] },
                "sync": { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] },
                "fly":  { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] }
            }

            Returns None if the JSON file does not exist or is invalid.
        """

        # Construct full path to the JSON file
        output_folder_spectral_band = Uti.safe_path(Path(output_folder) / self.spectral_band)
        json_path = output_folder_spectral_band / f"transfer_info_{self.spectral_band}_{img_suffix}.json"

        # Check if the JSON file exists
        if not json_path.exists():
            if verbose: print(Style.YELLOW + f"⚠ JSON file not found: {json_path}. Creating an empty JSON file." + Style.RESET)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)
            return None

        try:
            # Load JSON data
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(Style.GREEN + f"[INFO] JSON file loaded: {json_path}" + Style.RESET)
            return data

        except Exception as e:
            print(Style.RED + f"[ERROR] Failed to read {json_path}: {e}" + Style.RESET)
            return None


    def list_images_phase_mission(self,
                                        inputFolder: Path,
                                        listInputImages: List[str],
                                        outputFolder: Path,
                                        id_min: int,
                                        id_max: int,
                                        pgsbar0: int,
                                        pgrbar1: int) -> List[str]:
        """
        Returns:
        """
        listFileName = []
        try:
            for imgFileName in listInputImages:   # imgFileName  =  name + suffix
                num_img, name_img = self.extract_num_image(imgFileName)
                if id_min <= num_img <= id_max:
                    outputImageName = f"{self.currentSpectralBand}_{num_img:04d}{Path(imgFileName).suffix}"
                    listFileName.append(outputImageName)
                    self.progress_bar.setValue(pgsbar0 + int((pgrbar1-pgsbar0)*(len(listFileName) / (id_max + 1 - id_min))))
            LoadVisNirImagesDialog.flagAllImageOK = True
        except Exception as e:
            print("error in list_images_phase_mission :", e)
        return listFileName


    def init_image_takeoff_available(self, path_image_takeoff: str, original_path_image_takeoff: str):
        """
        Initialize the availability of a takeoff image based on the provided path and image type.

        This method checks whether the provided path to the takeoff image exists and whether
        the image type is either "VIS" or "DNG". If both conditions are true, it sets the
        `image_takeoff_available` attribute to True and stores the path; otherwise, it sets
        the `image_takeoff_available` attribute to False.

        Parameters:
        - path_image_takeoff (str): The path to the takeoff image.

        Returns:
        None
        """
        try:
            self.image_takeoff_available = False    # Initialize as False
            # Check if the image type is "VIS" or "DNG"
            if self.spectral_band.lower() in {"vis", "visible", "vi"}:
                self.img_suffix = "DNG"

                # ---------------------------------------------------
                # Test if the takeoff point image is available..
                # if path_image_takeoff is not None:
                #    if os.path.exists(path_image_takeoff):
                # ---------------------------------------------------
                if os.path.exists(self.folderMissionPath):
                    if Uti.safe_path(Path(self.folderMissionPath) / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json") is not None:
                        self.path_image_takeoff = Uti.safe_path(Path(self.folderMissionPath) / "AerialPhotography" / "VIS")
                        self.image_takeoff_available = True
                        self.image_0_available = True

        except Exception as e:
            print("error   in init_image_takeoff_available", e)

    def open_takeoff_image(self, path_image_takeoff: Path) -> None:
        """
        Open and display a takeoff image given its path.

        This method attempts to open an image from a specified path, processes it,
        and displays it on the user interface. It also sets various attributes and
        updates the UI components accordingly. If the image file is successfully processed
        and displayed, relevant path attributes are updated, and UI components are adjusted
        to reflect the loaded image.

        Parameters:
        - path_image_takeoff (Path): The path to the takeoff image to be opened and displayed.

        Returns:
        None
        """
        try:

            file_path = path_image_takeoff
            file_path = Uti.safe_path(Path(file_path) / self.info_dng["original name"])
            if file_path:
                self.flags[0] = True
                self.new_user_dir = os.path.dirname(file_path)
                self.user_dir = os.path.dirname(file_path)
                # Use rawpy library to open DNG files
                with rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess()
                    pixmap = QPixmap.fromImage(
                        QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888))
                pixmap = pixmap.scaled(* self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
                self.image_labels[0].setPixmap(pixmap)
                filename, file_suffix = os.path.splitext(os.path.basename(file_path))
                self.image_name_labels[0].setText(f"{self.img_legend[0]}  : \n {filename}  {file_suffix}")
                self.image_name_labels[0].setStyleSheet("color: darkBlue;")

                self.listImgRefPath[0] = file_path
                self.listRefPath[0] = file_path

            # Updated class flags with new values. New window position if moved
            self.currentUserDir = self.new_user_dir
            if all(elem is True for elem in self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
        except Exception as e:
            print("error in open_takeoff_image : ", e)

    def open_takeOff_sync_and_fly_image_VIS_or_NIR(self, spectral_band: str, img_suffix: str, index: int) -> None:
        """
        Open and display a synchronization or flight image (VIS), given its type and index.

        If img_suffix is 'dng', uses rawpy for RAW decoding; otherwise uses QPixmap directly.

        This method attempts to open an image from a specified path, processes it,
        and displays it on the user interface. It also sets various attributes and
        updates the UI components accordingly. If the image file is successfully processed
        and displayed, relevant path attributes are updated, and UI components are adjusted
        to reflect the loaded image.
        """
        try:
            # --- Select block and image to open ---
            index_map = {
                0: ("tkoff", 0),
                1: ("sync", 0),
                2: ("sync", -1),
                3: ("fly", 0),
                4: ("fly", -1)
            }

            try:
                key_1, index_img = index_map[index]
            except KeyError:
                raise ValueError(f"Invalid index: {index}")

            # --- Construct full paths ---
            path_image = Uti.safe_path(Path(self.folderMissionPath) / "AerialPhotography" / spectral_band)
            if img_suffix.lower() == "dng":
                file_path = Uti.safe_path(Path(path_image) / self.info_dng[key_1]["listCopiedImages"][index_img])

            else:
                raise ValueError(f"Invalid file suffix: {img_suffix.lower()}")

            if not file_path:
                raise FileNotFoundError(f"File not found: {file_path}")

            # --- Load image according to its type ---
            self.open_and_display_new_image(file_path, img_suffix, index)


        except Exception as e:
            print("error in open_takeOff_sync_and_fly_image_VIS_or_NIR:", e)

    def open_and_display_new_image(self, file_path, img_suffix,  index):

        try:
            # --- Load image according to its type ---
            img_suffix = img_suffix.lower()
            if img_suffix == "dng":
                with rawpy.imread(str(file_path)) as raw:
                    # =========================
                    # Tentative vignette
                    # =========================
                    try:
                        thumb = raw.extract_thumb()

                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            pil_img = Image.open(io.BytesIO(thumb.data)).convert("RGB")

                        elif thumb.format == rawpy.ThumbFormat.BITMAP:
                            pil_img = Image.fromarray(thumb.data).convert("RGB")

                        else:
                            raise ValueError(Style.YELLOW + f"⚠   Format de vignette non supporté" + Style.RESET)

                    except rawpy.LibRawNoThumbnailError:
                        print("Aucune vignette, dématriçage complet")
                        rgb = raw.postprocess(
                            use_auto_wb=True,
                            no_auto_bright=True,
                            output_bps=8
                        )
                        pil_img = Image.fromarray(rgb, mode="RGB")

                # =========================
                # PIL -> QImage (robuste)
                # =========================
                np_img = np.array(pil_img, dtype=np.uint8)
                h, w, ch = np_img.shape
                bytes_per_line = ch * w

                qimage = QImage(
                    np_img.data,
                    w,
                    h,
                    bytes_per_line,
                    QImage.Format.Format_RGB888
                ).copy()  # copie explicite pour la sécurité mémoire

                pixmap = QPixmap.fromImage(qimage)

            else:
                pixmap = QPixmap(str(file_path))
                if pixmap.isNull():
                    raise ValueError(f"Unable to load image: {file_path}")

            # --- Scale and display ---
            pixmap = pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            self.image_labels[index].setPixmap(pixmap)

            # --- Filename and legend information ---
            filename, file_suffix = os.path.splitext(os.path.basename(file_path))
            self.image_name_labels[index].setText(f"{self.img_legend[0]}  : \n {filename}  {file_suffix}")
            self.image_name_labels[index].setStyleSheet("color: darkBlue;")

            # --- Store input/output paths ---
            self.listImgRefPath[index] = file_path
            self.listRefPath[index] = file_path

            # --- Update flags and UI ---
            self.flags[index] = True
            self.new_user_dir = os.path.dirname(file_path)
            self.user_dir = os.path.dirname(file_path)
            self.currentUserDir = self.new_user_dir
        except Exception as e:
            print("error in open_and_display_new_image:", e)

    def open_image(self, numBtn: int, image_label: QLabel, image_name_label: QLabel, img_suffix: str):
        """
        Open an image and update relevant UI components.

        This method attempts to open and display an image based on the provided image type.
        It also sets various flags and updates UI components based on the operation's success.

        Parameters:
        - numBtn (int): Index used for referencing certain UI components and flags.
        - image_label (QLabel): QLabel to display the image.
        - image_name_label (QLabel): QLabel to display the image name.
        - img_suffix (str): Type of the image to be opened ("dng" or "jpg").

        Returns:
        None
        """
        try:
            flags = self.flags
            self.user_dir = Uti.safe_path(self.folderMissionPath / "AerialPhotography" / self.spectral_band)
            self.new_user_dir = self.user_dir
            if not os.path.exists(self.user_dir):
                self.user_dir = os.path.abspath('/')
                self.new_user_dir = self.user_dir
            elif all(elem is False for elem in self.flags) and not os.path.exists(self.user_dir):
                self.user_dir = os.path.abspath('/')
                self.new_user_dir = self.user_dir
            self.new_user_dir = self.user_dir

            print(f'debug 002  self.user_dir = {self.user_dir}')

            file_path, _ = QFileDialog.getOpenFileName(None, f"Select an image {img_suffix}", str(self.user_dir),
                                                       f"Images (*.{img_suffix});;All files (*)")
            if file_path:
                self.new_user_dir = os.path.dirname(file_path)

            self.open_and_display_new_image(file_path, img_suffix, numBtn)

            # Updated class flags with new values. New window position if moved
            # self.flags[numBtn] = flags[numBtn]
            self.currentUserDir = self.new_user_dir
            if all(self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
        except Exception as e:
            print("error in open_image : ", e)

    def choice_of_reference_images_consistency_analysis(self) -> bool:
        """
        Analyze the consistency of the choice of reference images.

        This method checks if all specified reference images are located within the provided
        input folder. An inconsistency is detected if any of the reference images are not
        found in the provided input folder, and an error message will be displayed, detailing
        which images are inconsistent.

        Parameters:
        - inputFolder (str): The path of the folder expected to contain the reference images.

        Returns:
        - bool: True if the choice of reference images is consistent (all images are in the
                input folder), False otherwise.
        """
        # Vérification minimale : liste non vide
        if not hasattr(self, "listImgRefPath") or not self.listImgRefPath:
            Uti.show_error_message("No reference image paths found.")
            return False

        values = self.listImgRefPath
        list_path = []
        for idx, value in enumerate(values):
            list_path.append(Uti.safe_path(Path(value).parent))
        first_path = list_path[0]

        # Consistance : tous identiques ?
        consistency_choice = (len(set(list_path)) == 1)

        if not consistency_choice:
            # Pour construire le message des éléments différents
            labels = [
                "first image of Sync",
                "last image of Sync",
                "first image of Fly",
                "last image of Fly",
                "extra image"
            ]

            message = ""
            for idx, (value, label) in enumerate(zip(list_path, labels)):
                if value != first_path:
                    message += f" - {label} differs: {value}\n"

            Uti.show_error_message(
                "We detected an inconsistency in the choice of reference images:\n"
                f"{message}\n"
                f"They must all be identical (same reference image)."
            )

        return consistency_choice

    def _set_image_flags_from_info(self, info: dict) -> None:
        """
        Analyse la structure d'un dictionnaire transfer_info_* (NIR ou VIS)
        et active/désactive les drapeaux :

            - image_0_available
            - image_first_sync_available
            - image_last_sync_available
            - image_first_fly_available
            - image_last_fly_available

        selon les règles définies pour les sections :
            tkoff, sync, fly.
        """

        # ----------------------------------------------------------------------
        # Initialisation : tout à False
        # ----------------------------------------------------------------------
        self.image_0_available = False
        self.image_first_sync_available = False
        self.image_last_sync_available = False
        self.image_first_fly_available = False
        self.image_last_fly_available = False

        # Un helper local pour vérifier la structure
        def _validate_section(sec: dict) -> Optional[list]:
            """
            Vérifie qu'une section contient :
                - outputFolder
                - listCopiedImages (liste)
            Renvoie cette dernière si OK, sinon None.
            """
            if not isinstance(sec, dict):
                return None

            if "outputFolder" not in sec:
                return None
            if "listCopiedImages" not in sec:
                return None

            lst = sec["listCopiedImages"]
            if not isinstance(lst, list):
                return None

            return lst

        # ----------------------------------------------------------------------
        # 1) TAKEOFF  ("tkoff")
        # ----------------------------------------------------------------------
        tkoff = info.get("tkoff")
        lst = _validate_section(tkoff)
        if lst is not None and len(lst) == 1:
            self.image_0_available = True
        else:
            self.image_0_available = False

        # ----------------------------------------------------------------------
        # 2) SYNCHRO ("sync")
        # ----------------------------------------------------------------------
        sync = info.get("sync")
        lst = _validate_section(sync)
        if lst is not None:
            if len(lst) >= 2:
                self.image_first_sync_available = True
                self.image_last_sync_available = True
            elif len(lst) == 1:
                self.image_first_sync_available = True
                self.image_last_sync_available = False
            else:
                # lst == [] ou None
                self.image_first_sync_available = False
                self.image_last_sync_available = False

        # ----------------------------------------------------------------------
        # 3) FLY ("fly")
        # ----------------------------------------------------------------------
        fly = info.get("fly")
        lst = _validate_section(fly)
        if lst is not None:
            if len(lst) >= 2:
                self.image_first_fly_available = True
                self.image_last_fly_available = True
            elif len(lst) == 1:
                self.image_first_fly_available = True
                self.image_last_fly_available = False
            else:
                self.image_first_fly_available = False
                self.image_last_fly_available = False

    @staticmethod
    def extract_files_images(
            inputFolder: Union[str, Path],
            img_suffix: str = ".tif",
            verbose: bool = False
    ) -> List[Path]:
        """
        Returns a list of image files of a given type present in a folder.

        Parameters
        ----------
        inputFolder : str or Path
            Base folder to scan.
        img_suffix : str, optional
            img_suffix of files to process (default ".tif").
            Supported values: .dng, .raw, .tif, .jpg, .jpeg, .png (case-insensitive).
        verbose : bool, optional
            If True, prints the number of files found (default False).

        Returns
        -------
        list[Path]
            Sorted list of file paths matching the img_suffix.
        """
        # Normalize img_suffix (case-insensitive, ensure it starts with a dot)
        img_suffix = img_suffix.lower()
        if not img_suffix.startswith("."):
            img_suffix = "." + img_suffix

        valid_img_suffix = [".dng", ".raw", ".tif", ".jpg", ".jpeg", ".png"]
        if img_suffix not in valid_img_suffix:
            raise ValueError(f"img_suffix '{img_suffix}' not supported. Choose from {valid_img_suffix}.")

        # Folder path to scan
        folder_path = Path(inputFolder)

        # List files with matching img_suffix (case-insensitive)
        files = sorted([f for f in folder_path.iterdir() if f.suffix.lower() == img_suffix])

        if verbose:
            print(Style.GREEN + f"🔍 {len(files)} files {img_suffix.upper()} found" + Style.RESET)

        return files

    @staticmethod
    def on_help() -> None:
        """
        """
        try:
            Uti.show_info_message("IRDrone", "Sorry, this feature is under development.", "")
        except Exception as e:
            print("error", e)
        pass

    @staticmethod
    def _dict_has_keys(d: dict, keys: list[str]) -> bool:
        """ Vérifie que le dictionnaire contient toutes les clés requises. """
        if not isinstance(d, dict):
            return False
        for k in keys:
            if k not in d:
                print(Style.YELLOW + f"⚠ clé manquante : '{k}'" + Style.RESET)
                return False
            if d[k] in (None, ""):
                print(Style.YELLOW + f"⚠ valeur vide pour '{k}'" + Style.RESET)
                return False
        return True

    @staticmethod
    def _validate_takeoff_paths(info: dict) -> bool:
        """ Vérifie l'existence des chemins source et destination. """
        try:
            src = Path(info["File path take-off"])
            dst_full = Path(info["path mission image take-off"])
        except Exception as exc:
            print(Style.YELLOW + f"⚠  cannot build Path: {exc}" + Style.RESET)
            return False

        if not src.exists() or not src.is_file():
            print(Style.YELLOW + f"⚠  fichier source inexistant : {src}" + Style.RESET)
            return False

        if not dst_full.parent.exists():
            print(Style.YELLOW + f"⚠  dossier destination inexistant : {dst_full.parent}" + Style.RESET)
            return False

        return True

    @staticmethod
    def create_list_image_in_input_folder(input_folder: Union[str, str], suffix: str) -> Optional[List[str]]:
        """
        Create a list of image file names with a specific img_suffix in the given input folder.

        Parameters:
        - input_folder (Union[str, str]): The folder from which image file names will be listed.
        - suffix (str): The file img_suffix to filter image files.

        Returns:
        - List[str]: A list of image file names with the specified img_suffix.
          Returns None if the input_folder is not a directory.
        """

        # Checks if the given path is a folder
        if not os.path.isdir(input_folder):
            return None
        # List all files in folder
        files = os.listdir(input_folder)
        # Filter the list to keep only .suffix type files
        listInputImages = [f for f in files if f.lower().endswith('.' + suffix)]
        return listInputImages

    @staticmethod
    def extract_num_image(imgPath: str) -> Tuple[int, str]:
        """
        Extract the frame index and frame name from an image path.

        Given an image path in the format 'C:/...../HYPERLAPSE_9999.dng', this method
        extracts the frame name ('HYPERLAPSE_9999') and frame index (9999).

        Parameters:
        - imgPath (str): The path to the image file.

        Returns:
        - Tuple[int, str]: A tuple containing the frame index as an integer and the
                           frame name as a string.
        """
        frame_name: str = os.path.splitext(os.path.basename(imgPath))[0]
        frame_index: int = int(frame_name.split("_")[-1])
        return frame_index, frame_name

    @classmethod
    def reset_flags(cls):
        """
        Class method of class LoadVisNirImagesDialog(QDialog)
            used by def on_load_images_VIS_and_NIR(self) of class class MainWindow(QMainWindow):
            with the instruction load_Vis_Nir_images.LoadVisNirImagesDialog.reset_flags()

            Allows you to reset the flag and dir when the set of reference images is complete
            We can then make the “load all images” button visible.
        """
        cls.flags = [False] * cls.num_images
        cls.currentUserDir = os.path.join(os.path.abspath('/'), "Air-Mission")

    @classmethod
    def reset_flag_AllImageOK(cls):
        cls.flagAllImageOK = False
        cls.currentUserDir = os.path.join(os.path.abspath('/'), "Air-Mission")




