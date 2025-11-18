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

# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar, QFileDialog,  QMessageBox, QApplication
from PyQt6.QtGui import QPixmap, QColor, QImage, QCloseEvent, QIcon
from PyQt6.QtCore import Qt
# -------------- IRDrone Library -------------------------------------
import IRD_interactive_utils as Uti
from IRD_interactive_utils import center_on_screen


"""
      This code allows you to choose the reference images for a mission and then distribute the different images in the
     mission files. For each category of images (VIS taken by the drone camera and NIR taken by the on-board IR camera) 
     the user must choose 5 reference images:
         > Take-off image.       In general for the DJI drone this will be the first image recorded HYPERLAPSE_0001.
                                For the on-board NIR camera we can visually choose the image which is "closest" to
                                the first image from the drone.  
         > First sync image.    This is the first stable image where the ARUCO target is visible. 
                                The ideal is that the ARUCO sight has not started to rotate.
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
        The synchronization step is carried out at the take-off point at an altitude of approximately 3 m and at the fixed point.
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
                 type_img: str,
                 folderMission: Optional[Path] = None,
                 path_image_takeoff: Optional[Path] = None):
        super().__init__()

        if folderMission is None or not folderMission.exists():
            raise ValueError(f"Invalid folderMission: {folderMission}")

        # ---- Basic GUI and screen parameters
        self.num_images: int = 5
        self.pref_screen: Uti.Prefrence_Screen = Uti.Prefrence_Screen()
        self.screen_width: int = width
        self.screen_height: int = height
        self.target_screen_index: int = self.pref_screen.defaultScreenID
        self.screen_adjust: float = self.pref_screen.screenAdjust
        self.window_display_size: tuple[int, int] = self.pref_screen.windowDisplaySize

        # ---- Image type and extension
        self.type_img: str = type_img
        self.ext: str
        if self.type_img in ("VIS", "DNG"):
            self.ext = "dng"
            self.type_img = "VIS"
        elif self.type_img in ("NIR", "jpg"):
            self.ext = "jpg"
            self.type_img = "NIR"
        else:
            self.ext = "jpg"

        # ---- Directories
        self.currentUserDir: str = self.pref_screen.current_directory
        self.user_dir: str = self.currentUserDir
        self.new_user_dir: str = self.currentUserDir
        self.folderMissionPath: Path = folderMission
        self.outputTakeoffFolder: Path = Path(self.folderMissionPath) / "FlightAnalytics"
        self.outputFlightAnalyticsFolder: Path = Path(self.folderMissionPath) / "FlightAnalytics"
        self.outputTakeoffFolder.mkdir(parents=True, exist_ok=True)
        self.outputFlightAnalyticsFolder.mkdir(parents=True, exist_ok=True)

        # ---- Image availability flags
        self.image_0_available: bool = False
        self.image_first_sync_available: bool = False
        self.image_last_sync_available: bool = False
        self.image_first_fly_available: bool = False
        self.image_last_fly_available: bool = False
        self.flags: list[bool] = [False] * self.num_images

        # ---- Placeholder for images
        self.listVisRefPath: list[Optional[str]] = [None] * self.num_images
        self.listNirRefPath: list[Optional[str]] = [None] * self.num_images
        self.listImgRefPath: list[Optional[str]] = [None] * self.num_images
        self.currentImgTyp: str = self.type_img
        self.image_labels: list[QLabel] = [QLabel() for _ in range(self.num_images)]
        self.image_name_labels: list[QLabel] = [QLabel() for _ in range(self.num_images)]
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
        verbose = True

        if self.outputFlightAnalyticsFolder:
            if self.type_img == "NIR":
                self.info_nir_jpg = self.load_transfer_info(self.outputFlightAnalyticsFolder, "NIR", "jpg")
                if self.info_nir_jpg:
                    self._set_image_flags_from_info(self.info_nir_jpg)

            elif self.type_img == "VIS":
                self.info_vis_dng = self.load_transfer_info(self.outputFlightAnalyticsFolder, "VIS", "dng")
                if self.info_vis_dng:
                    self._set_image_flags_from_info(self.info_vis_dng)


        self.timeline: list[dict] = []
        self.path_image_takeoff: Optional[Path] = path_image_takeoff   # Takeoff image path
        self.image_takeoff_available: bool = False   # Takeoff image path
        self.image_display_size: tuple[int, int] = (100, 100)  # Image display size (will be set in init_GUI)
        self.empty_pixmap: Optional[QPixmap] = None  # Empty pixmap placeholder (will be set in init_GUI)


        # ---- Initialize takeoff image availability
        self.init_image_takeoff_available(path_image_takeoff)

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
        type_img : str
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
            self.setWindowTitle(f"Load the {self.type_img} images of the mission")
            icon_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "IRDrone.ico")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                self.setWindowIcon(icon)
            self.setGeometry(0, 0, self.screen_width, self.screen_height)

            # First mission image | First image of the Sync sequence | Last image of the Sync sequence | First Fly image | Last Fly image
            # list of paths to the 5 reference images
            self.listVisRefPath = [None] * self.num_images
            self.listNirRefPath = [None] * self.num_images
            self.listImgRefPath = [None] * self.num_images
            self.currentImgTyp = self.type_img
            # Creating placeholders for images
            self.image_labels = [QLabel() for _ in range(self.num_images)]
            # Creating placeholders for image captions
            self.img_legend = ["Take-off image:",
                               "First sync image.",
                               "Last sync image.",
                               "First fly image.",
                               "Last fly image."]
            self.image_name_labels = [QLabel(self.img_legend[i]) for i in range(self.num_images)]

            # Creating command bar buttons (one per image)
            btn_legend = ["Load first mission image.",
                          "Load first sync image.",
                          "Load last sync image.",
                          "Load first fly image.",
                          "Load last fly image."]
            # Connecting buttons to actions
            button_width = int(0.9 * (self.screen_width // self.num_images))
            self.btn_command = [QPushButton(btn_legend[i]) for i in range(self.num_images)]
            for btn in self.btn_command:
                btn.setFixedWidth(button_width)
                btn.setStyleSheet("background-color: darkGray; color: black;")

            # Button to load all mission images once reference images are chosen
            button_width = int(0.7 * (self.screen_width // self.num_images))
            self.btn_load_all_images = QPushButton("Unload all mission images")
            self.btn_load_all_images.setFixedWidth(button_width)
            self.btn_help = QPushButton("Help")
            self.btn_help.setStyleSheet("background-color: darkGreen; color: white;")
            self.btn_help.setFixedWidth(button_width)

            button_width = int(0.7 * (self.screen_width // self.num_images))
            self.btn_validate_load_all_images = QPushButton("Validate (next step) >>>")
            self.btn_validate_load_all_images.setFixedWidth(button_width)
            self.btn_validate_load_all_images.setEnabled(False)
            self.btn_validate_load_all_images.setStyleSheet("background-color: gray; color: darkGray;")

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
                int((self.screen_width - 100) / self.num_images),
                int((self.screen_width - 100) / self.num_images * 3 / 4)
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
            bottom_command.addWidget(self.btn_validate_load_all_images)
            bottom_command.addWidget(self.btn_help)
            bottom_layout.addLayout(bottom_command)
            bottom_layout.addWidget(self.progress_bar)

            layout.addLayout(top_layout)
            layout.addLayout(middle_layout)
            layout.addLayout(bottom_layout)

            center_on_screen(self, self.target_screen_index, self.screen_adjust, self.window_display_size)

            # Disable btn_load_all_images at startup. Will be enabled when all five reference images are loaded
            self.btn_load_all_images.setEnabled(False)
            self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: gray;")

            # Load images if interactive sequence was already completed once
            if self.type_img == "VIS":
                if self.image_0_available:
                    print(Uti.Style.GREEN + '[INFO] Loading takeoff image' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 0)
                elif self.image_takeoff_available:
                    self.open_takeoff_image(self.path_image_takeoff)

                if self.image_first_sync_available:
                    print(Uti.Style.GREEN + '[INFO] Loading first sync image' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 1)
                if self.image_last_sync_available:
                    print(Uti.Style.GREEN + '[INFO] Loading last sync image VIS' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 2)
                if self.image_first_fly_available:
                    print(Uti.Style.GREEN + '[INFO] Loading first fly image VIS' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 3)
                if self.image_last_fly_available:
                    print(Uti.Style.GREEN + '[INFO] Loading last fly image VIS' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 4)

                if all(self.flags):
                    self.btn_load_all_images.setEnabled(True)
                    self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")

            elif self.type_img == "NIR":
                if self.image_0_available:
                    print(Uti.Style.GREEN + '[INFO] Loading takeoff image' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 0)
                if self.image_first_sync_available:
                    print(Uti.Style.GREEN + '[INFO] Loading first sync image NIR' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 1)
                if self.image_last_sync_available:
                    print(Uti.Style.GREEN + '[INFO] Loading last sync image NIR' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 2)
                if self.image_first_fly_available:
                    print(Uti.Style.GREEN + '[INFO] Loading first fly image NIR' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 3)
                if self.image_last_fly_available:
                    print(Uti.Style.GREEN + '[INFO] Loading last fly image NIR' + Uti.Style.RESET)
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 4)

            # Setting button actions
            for index, btn in enumerate(self.btn_command):
                btn.clicked.connect(partial(self.open_image, index, self.image_labels[index], self.image_name_labels[index], self.ext))
            self.btn_load_all_images.clicked.connect(self.on_load_all_images)
            self.btn_validate_load_all_images.clicked.connect(self.on_validate_load_all_images)
            self.btn_help.clicked.connect(self.on_help)
            self.btn_help.setStyleSheet("background-color: green; color: white;")
            self.setLayout(layout)

        except Exception as e:
            print("Error in step2 init_GUI:", e)


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
           - Les images jpeg (format jpg)
           - les images raw  (format RAW).
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
            #      They correspond to the correct type of image (NIR or VIS) because we are in the "on_load_all_images"
            #      procedure called by the button .btn_load_all_images which is in the window opened by
            #      load_Vis_Nir_images.LoadVisNirImagesDialog(... ,EXT, ... ) where EXT in {"NIR", "VIS"}.
            #      This procedure is therefore automatically in the right context.

            idMinSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[1]))[0].split("_")[-1])
            idMaxSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[2]))[0].split("_")[-1])
            outputSyncFolder = os.path.join(outputFolder, "Synchro")
            if not os.path.isdir(outputSyncFolder):
                # print("The destination folder ", outputSyncFolder, " of the images does not exist!")
                Uti.show_error_message(f"The destination folder {outputSyncFolder} for the images does not exist!\n"
                                       f"Check that you have already created the mission.")

            idMinFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[3]))[0].split("_")[-1])
            idMaxFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[4]))[0].split("_")[-1])

            idTakeoff = int(os.path.splitext(os.path.basename(self.listImgRefPath[0]))[0].split("_")[-1])

            outputFlyFolder = os.path.join(outputFolder, "AerialPhotography")
            outputTakeoffFolder = os.path.join(outputFolder, "FlightAnalytics")
            outputFlightAnalyticsFolder = os.path.join(outputFolder, "FlightAnalytics")
            if not os.path.isdir(outputFlyFolder):
                # print("The destination folder ", outputFlyFolder, " of the images does not exist!")
                Uti.show_error_message(f"The destination folder {outputFlyFolder} for the images does not exist!\n"
                                       f"Check that you have already created the mission.")
                return

            # --------------------- Entry folder  --------------------------------------
            #  Normally these are the DCIM files on the SD card of the drone and the NIR camera

            inputFolder = os.path.dirname(self.listImgRefPath[0])

            if not os.path.isdir(inputFolder):
                # print("The image input folder ", inputFolder, " does not exist.")
                Uti.show_error_message(f"The input folder { inputFolder} of the images does not exist!")
                exit()
            # Consistency test normally all images were extracted from the same folder
            consistency_choice = self.choice_of_reference_images_consistency_analysis(inputFolder)
            if not consistency_choice:
                return

            # ---------------Copy images from the camera's SD card to the computer's hard drive.----------------------
            Uti.show_info_message("IRDrone", f"Copying {(max((idMaxFly - idMinFly),0) + max((idMaxSync - idMinSync),0) )} "
                                f"images from the camera SD card to the computer disk may take a little time...",
                                "Be patient ;-) ",
                                QMessageBox.Icon.Information)


            if self.currentImgTyp == "NIR":
                # -----------------------------------------------------------------------------------
                #                               NIR
                # -----------------------------------------------------------------------------------

                # ----------  build time line NIR
                self.timeline = self.time_line_analyser_images(inputFolder, img_Typ=self.currentImgTyp, extension=".RAW", verbose=False)

                # ----------  transfer of NIR images of the tkoff, Sync and Fly phase (jpg & raw) ----------------
                self.process_image_transfer(
                    inputFolder, ["jpg", "raw"],
                    outputSyncFolder, outputFlyFolder, outputFlightAnalyticsFolder,
                    idTakeoff, idMinSync,  idMaxSync, idMinFly, idMaxFly, offset=[0, -1],
                    progressSync=[(0, 10), (0, 30)],
                    progressFly=[(10, 100), (30, 100)]
                )

            elif self.currentImgTyp == "VIS":
                # -----------------------------------------------------------------------------------
                #                               VIS
                # -----------------------------------------------------------------------------------

                # ----------  build time line NIR
                self.timeline = self.time_line_analyser_images(inputFolder, img_Typ=self.currentImgTyp, extension=".DNG", verbose=False)

                # ----------   transfer of VIS images of the tkoff, Sync  phase (dng) ----------------
                self.process_image_transfer(
                    inputFolder, "dng",
                    outputSyncFolder, outputFlyFolder, outputFlightAnalyticsFolder,
                    idTakeoff, idMinSync, idMaxSync, idMinFly, idMaxFly,
                    progressSync=(0, 30),
                    progressFly=(30, 100)
                )

            # print("All images have been transferred successfully.")
            Uti.show_info_message("IRDrone", f"Your {(max((idMaxFly - idMinFly),0) + max((idMaxSync - idMinSync),0))}  images have been transferred \n from directory {inputFolder}  of the camera SD card \n to the mission directory {outputFlyFolder}.",
                                  "You can close this window.", QMessageBox.Icon.Information)
            self.btn_validate_load_all_images.setEnabled(True)
            self.btn_validate_load_all_images.setStyleSheet("background-color: gray; color: white;")

            # Optionnel : fermer le dialogue automatiquement (si tu veux)
            # self.accept()

            return getattr(self, "timeline", None)

        except Exception as e:
            print("error in on_load_all_images  :", e)
            return None


    @staticmethod
    def extract_files_images(
            inputFolder: Union[str, Path],
            extension: str = ".tif",
            verbose: bool = False
    ) -> List[Path]:
        """
        Returns a list of image files of a given type present in a folder.

        Parameters
        ----------
        inputFolder : str or Path
            Base folder to scan.
        extension : str, optional
            Extension of files to process (default ".tif").
            Supported values: .dng, .raw, .tif, .jpg, .jpeg, .png (case-insensitive).
        verbose : bool, optional
            If True, prints the number of files found (default False).

        Returns
        -------
        list[Path]
            Sorted list of file paths matching the extension.
        """
        # Normalize extension (case-insensitive, ensure it starts with a dot)
        extension = extension.lower()
        if not extension.startswith("."):
            extension = "." + extension

        valid_extensions = [".dng", ".raw", ".tif", ".jpg", ".jpeg", ".png"]
        if extension not in valid_extensions:
            raise ValueError(f"Extension '{extension}' not supported. Choose from {valid_extensions}.")

        # Folder path to scan
        folder_path = Path(inputFolder)

        # List files with matching extension (case-insensitive)
        files = sorted([f for f in folder_path.iterdir() if f.suffix.lower() == extension])

        if verbose:
            print(Uti.Style.GREEN + f"🔍 {len(files)} files {extension.upper()} found" + Uti.Style.RESET)

        return files


    def time_line_analyser_images(
            self,
            inputFolder: Union[Path, str],
            img_Typ: Optional[str] = None,
            extension: str = ".tif",
            verbose: bool = False
    ) -> Dict:
        """
        Analyze image files in a folder:
          - extract the date and time from the filename
          - extract the shot number (XXX)
          - compute time differences between consecutive images
          - check the regularity of time intervals
          - estimate the nominal period (median, mode, outlier filtering)
          - display any detected "jumps"
          - adaptive filtering tolerance automatically computed (1% of median)

        Parameters
        ----------
        inputFolder : Path | str
            Path to the folder containing the image files.
        img_Typ : str | None, optional
            Image type, "VIS" or "NIR", by default None.
        extension : str, optional
            File extension to filter images, by default ".tif".
        verbose : bool, optional
            If True, prints detailed information during analysis, by default False.

        Returns
        -------
        dict
            Dictionary containing files, numbers, dates, deltas, time_line, and camera type.
        """

        fichiers = self.extract_files_images(inputFolder, extension=extension)

        dates: list[datetime] = []
        numeros: list[int] = []

        if img_Typ == "NIR":
            for f in fichiers:
                stem = f.stem
                try:
                    # For time calculation, the year is ignored.
                    # On some cameras (e.g., SJCam M20), if the battery is removed,
                    # the default date can be the camera manufacturing date !
                    annee, reste = stem.split("_", 1)
                    moisjour, heuresec, numero = reste.split("_")

                    dt = datetime.strptime(f"{annee}{moisjour}{heuresec}", "%Y%m%d%H%M%S")
                    if verbose:
                        print(Uti.Style.GREEN + f'image {extension} N° : {numero} | time {heuresec}' + Uti.Style.RESET)

                    dates.append(dt)
                    numeros.append(int(numero))
                except Exception as e:
                    print(Uti.Style.YELLOW + f"⚠️ Filename ignored ({stem}): {e}" + Uti.Style.RESET)

        elif img_Typ == "VIS":
            for f in fichiers:
                stem = f.stem
                file_path = Path(f)
                # extract the shot number
                match = re.search(r'(\d+)$', stem)
                if match:
                    numero = int(match.group(1))
                else:
                    print("Shot number not found")
                # extract capture date
                dt = self.extract_dng_capture_date(file_path)
                dates.append(dt)
                numeros.append(int(numero))
                if verbose:
                    print(f'image {extension} N° : {numero} | time {dt}')

        else:
            print(Uti.Style.YELLOW + f"⚠️ Invalid image type ({img_Typ}). (must be VIS or NIR)" + Uti.Style.RESET)

        dates = np.array(dates)
        numeros = np.array(numeros)

        if len(dates) > 1:
            deltas = np.diff([d.timestamp() for d in dates])
            if verbose:
                print(deltas)
        else:
            deltas = np.array([])

        if len(deltas) == 0:
            print(Uti.Style.YELLOW + f"⚠️ Not enough images to compute intervals." + Uti.Style.RESET)
            return {"dates": dates, "numeros": numeros, "deltas": deltas}

        print(Uti.Style.GREEN + f"🔍 {len(dates)} {extension.upper()} files found" + Uti.Style.RESET)

        # --- Total sequence duration ---
        total_duration = (dates[-1] - dates[0]).total_seconds()
        print(f"⏱️ Total sequence duration : {total_duration:.3f} s ({str(dates[-1] - dates[0])})")

        # --- Method 1: Median ---
        periode_mediane = np.median(deltas)

        # --- Method 2: Mode ---
        counts = Counter(np.round(deltas, 3))
        periode_mode, freq = counts.most_common(1)[0]

        # --- Method 3: Outlier filtering ---
        tol = max(0.001, 0.01 * periode_mediane)  # 1% of median, min 1 ms
        filtered_deltas = deltas[np.abs(deltas - periode_mediane) < tol]
        if len(filtered_deltas) > 0:
            periode_filtre = np.mean(filtered_deltas)
        else:
            periode_filtre = periode_mediane
            print(Uti.Style.YELLOW + f"⚠️ No intervals within defined tolerance for filtering." + Uti.Style.RESET)

        # --- Best time-lapse estimate ---
        estims = np.array([periode_mediane, periode_mode, periode_filtre])
        periode_time_lapse = np.median(estims)
        print(Uti.Style.GREEN + f"📌 best_timelapse_estimate : {periode_time_lapse:.3f} s" + Uti.Style.RESET)

        # --- Jump detection ---
        sauts: list[tuple[int, int, float]] = []
        for i, d in enumerate(deltas):
            if not np.isclose(d, periode_mediane, atol=tol):
                sauts.append((i, i + 1, d))

        # --- True recording period accounting for detected jumps ---
        true_record_period = self.true_recording_period(dates, sauts, periode_time_lapse)

        # --- Construct the actual timeline ---
        time_line = self.buid_time_line(dates, sauts, true_record_period, numeros, fichiers, verbose=False)

        # --- Overall summary ---
        print(f"🕒 Timeline computed: {time_line[-1]:.3f} s up to the last image (n={len(time_line)})")

        dic_timeline = self.build_time_line_dictionnary(
            fichiers=fichiers,
            numeros=numeros,
            dates=dates,
            deltas=deltas,
            time_line=time_line,
            cam_type=self.currentImgTyp
        )

        return dic_timeline


    @staticmethod
    def buid_time_line(dates: list[float],
                       sauts: list[tuple[int, int, float]],
                       periode_reelle: float,
                       numeros: list[int],
                       fichiers: list[Path],
                       verbose: bool = False
                       ) -> np.ndarray:
        """
        Construct a vector of actual elapsed times since the first image,
        taking into account real jumps, apparent jumps (EXIF artifacts), and abnormal jumps.
        If verbose=True, display the timeline image by image with the type of jump.

        Parameters
        ----------
        dates : list[float]
            List of timestamps (raw image acquisition times).
        sauts : list[tuple[int, int, float]]
            List of detected jumps as tuples (index1, index2, delta_time).
        periode_reelle : float
            Nominal real period between images.
        numeros : list[int]
            List of raw image numbers for display purposes.
        verbose : bool, optional
            If True, prints detailed timeline information, by default False.

        Returns
        -------
        np.ndarray
            Array of adjusted timeline values in seconds.
        """

        n = len(dates)
        if n == 0:
            return np.array([])

        time_line = np.zeros(n, dtype=float)

        # --- 1) Classify jumps ---
        classified_jumps: list[tuple[int, int, float, str]] = []  # (idx1, idx2, delta, type)
        dict_sauts: dict[int, float] = {}

        for idx1, idx2, d_saut in sauts:
            ratio = d_saut / periode_reelle

            # Case 1: real jump (integer multiple of period)
            if np.isclose(ratio, round(ratio), atol=0.49 / periode_reelle):
                type_saut = "real"
                dict_sauts[idx1] = d_saut

            # Case 2: apparent jump (EXIF artifact)
            elif d_saut < 2 * periode_reelle:
                type_saut = "apparent"
                # not added to dict_sauts because ignored

            # Case 3: abnormal jump
            else:
                type_saut = "abnormal"
                dict_sauts[idx1] = d_saut

            classified_jumps.append((idx1, idx2, d_saut, type_saut))

        # --- 2) Display jumps (only now that type is known) ---
        if classified_jumps:
            print(Uti.Style.YELLOW + f"⚠️ {len(classified_jumps)} jumps detected :" + Uti.Style.RESET)
            for idx1, idx2, delta, type_saut in classified_jumps:
                if type_saut == "real":
                    label = "real jump"
                    color = Uti.Style.YELLOW
                elif type_saut == "apparent":
                    label = "apparent jump"
                    color = Uti.Style.GREEN
                else:
                    label = "abnormal jump"
                    color = Uti.Style.RED

                print(
                    color
                    + f"   - Between {Path(fichiers[idx1]).name} and {Path(fichiers[idx2]).name} : {delta:.3f} s → {label}"
                    + Uti.Style.RESET
                )
        else:
            print(Uti.Style.GREEN + "✅ No jumps detected" + Uti.Style.RESET)

        # --- 3) Construct adjusted timeline ---
        if verbose:
            print("\n--- Adjusted real timeline ---")
            print(f"raw image N° : {numeros[0]:03d} | time_line {time_line[0]:.3f} s")

        for i in range(1, n):
            delta = periode_reelle  # default value
            saut_txt = ""

            if (i - 1) in dict_sauts:
                d_saut = dict_sauts[i - 1]
                ratio = d_saut / periode_reelle

                # Same classification as above
                if np.isclose(ratio, round(ratio), atol=0.49 / periode_reelle):
                    delta = d_saut
                    saut_txt = f" | real jump {d_saut:.3f} s"
                elif d_saut < 2 * periode_reelle:
                    saut_txt = f" | apparent jump ({d_saut:.3f} s)"
                else:
                    delta = d_saut
                    saut_txt = f" | abnormal jump {d_saut:.3f} s"

            time_line[i] = time_line[i - 1] + delta

            if verbose:
                print(f"raw image N° : {numeros[i]:03d} | time_line {time_line[i]:.3f} s{saut_txt}")

        if verbose:
            print("---------------------------------\n")

        return time_line



    def process_image_transfer(
            self,
            inputFolder: Union[str, Path],
            img_types: Union[str, List[str]],
            outputSyncFolder: Union[str, Path],
            outputFlyFolder: Union[str, Path],
            outputFlightAnalyticsFolder: Union[str, Path],
            idTkoff: int,
            idMinSync: int,
            idMaxSync: int,
            idMinFly: int,
            idMaxFly: int,
            offset: Union[int, List[int]] = 0,
            progressSync: Union[Tuple[int, int], List[Tuple[int, int]]] = (0, 30),
            progressFly: Union[Tuple[int, int], List[Tuple[int, int]]] = (30, 96),
    ) -> None:
        """
        Process and transfer images for one or multiple file extensions.
        Handles Takeoff, Sync and Fly phases, applies index offsets per extension,
        and generates one JSON summary file *per extension*.

        Parameters
        ----------
        inputFolder : Path or str
            Folder containing the original input images.

        img_types : str or list[str]
            Image extension(s) to process, e.g. "jpg", "raw", or ["jpg", "raw"].
            Each extension is processed independently and results in a separate JSON file.

        outputSyncFolder : Path
            Destination folder for Sync-phase images.

        outputFlyFolder : Path
            Destination folder for Fly-phase images.

        outputFlightAnalyticsFolder : Path
            Destination folder for the Takeoff image and JSON export.

        idTkoff : int
            Base index of the Takeoff image (before offset correction).

        idMinSync, idMaxSync : int
            Base index range for Sync-phase images (before applying offsets).

        idMinFly, idMaxFly : int
            Base index range for Fly-phase images (before applying offsets).

        offset : int or list[int], optional
            Index shift applied to each extension.
            Example: offset=[0, -1] for ["jpg", "raw"] if RAW numbering is shifted.
            If a single integer is given, it is applied to all extensions.
            Default is 0.

        progressSync, progressFly : tuple(int,int) or list[tuple], optional
            Progress-bar ranges. A single tuple applies to all extensions.
            Otherwise, provide one range per extension.

        Returns
        -------
        None
        """

        # Normalize to Path
        inputFolder = Path(inputFolder)

        # Normalize img_types → list[str]
        if isinstance(img_types, str):
            img_types = [img_types]
        else:
            img_types = list(img_types)

        n = len(img_types)

        # Normalize offset
        if isinstance(offset, int):
            offset = [offset] * n
        elif isinstance(offset, list):
            if len(offset) != n:
                raise ValueError("offset list must have same length as img_types")
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
        # Loop on extensions → generate one JSON per extension
        # ----------------------------------------------------------
        for i, ext in enumerate(img_types):
            # Apply per-extension offset
            idTk = idTkoff + offset[i]
            idMinS = idMinSync + offset[i]
            idMaxS = idMaxSync + offset[i]
            idMinF = idMinFly + offset[i]
            idMaxF = idMaxFly + offset[i]

            sync_prog = progressSync[i]
            fly_prog = progressFly[i]

            # List of images with this extension
            listInputImages = self.create_list_image_in_input_folder(inputFolder, ext)

            # --- Takeoff (one image)
            takeOff_list = self.load_inputFolder_2_outputFolder(
                inputFolder, listInputImages,
                outputFlightAnalyticsFolder,
                idTk, idTk,
                *sync_prog
            )

            # --- Sync phase
            sync_list = self.load_inputFolder_2_outputFolder(
                inputFolder, listInputImages,
                outputSyncFolder,
                idMinS, idMaxS,
                *sync_prog
            )

            # --- Fly phase
            fly_list = self.load_inputFolder_2_outputFolder(
                inputFolder, listInputImages,
                outputFlyFolder,
                idMinF, idMaxF,
                *fly_prog
            )

            # --- JSON creation (one per extension)
            self.save_transfer_info(
                output_folder=outputFlightAnalyticsFolder,
                input_folder=inputFolder,
                cam_type=self.currentImgTyp,
                img_type=ext,  # IMPORTANT: single extension
                tkoff_data={
                    "outputFolder": str(outputFlightAnalyticsFolder),
                    "idMin": idTk,
                    "idMax": idTk,
                    "listCopiedImages": takeOff_list,
                },
                sync_data={
                    "outputFolder": str(outputSyncFolder),
                    "idMin": idMinS,
                    "idMax": idMaxS,
                    "listCopiedImages": sync_list,
                },
                fly_data={
                    "outputFolder": str(outputFlyFolder),
                    "idMin": idMinF,
                    "idMax": idMaxF,
                    "listCopiedImages": fly_list,
                }
            )

        # Final global progress
        self.progress_bar.setValue(100)


    @staticmethod
    def save_transfer_info(
            output_folder: Union[str, Path],
            input_folder: Union[str, Path],
            cam_type: str,
            img_type: str,
            tkoff_data: Optional[Dict] = None,
            sync_data: Optional[Dict] = None,
            fly_data: Optional[Dict] = None,
    ) -> Path:
        """
        Save transfer information (Sync and Fly phases) into a single JSON file.

        Parameters
        ----------
        output_folder : str | Path
            Folder where the JSON file will be created.
        input_folder : str | Path
            Source input folder.
        cam_type : str
            Camera type (e.g., "VIS" or "NIR").
        img_type : str
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

        Returns
        -------
        Path
            Path to the saved JSON file.
        """

        # Ensure output folder exists
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        # JSON file name including camera and image type
        json_name = f"transfer_info_{cam_type}_{img_type}.json"
        json_path = output_folder / json_name

        # Base data
        data = {
            "cam_type": cam_type,
            "img_type": img_type,
            "inputFolder": str(input_folder),
        }

        # take-off data
        if tkoff_data:
            data["tkoff"] = {
                "outputFolder": str(tkoff_data.get("outputFolder", "")),
                "idMin": int(tkoff_data.get("idMin", -1)),
                "idMax": int(tkoff_data.get("idMax", -1)),
                "listCopiedImages": list(map(str, tkoff_data.get("listCopiedImages", []))),
            }

        # Sync phase data
        if sync_data:
            data["sync"] = {
                "outputFolder": str(sync_data.get("outputFolder", "")),
                "idMin": int(sync_data.get("idMin", -1)),
                "idMax": int(sync_data.get("idMax", -1)),
                "listCopiedImages": list(map(str, sync_data.get("listCopiedImages", []))),
            }

        # Fly phase data
        if fly_data:
            data["fly"] = {
                "outputFolder": str(fly_data.get("outputFolder", "")),
                "idMin": int(fly_data.get("idMin", -1)),
                "idMax": int(fly_data.get("idMax", -1)),
                "listCopiedImages": list(map(str, fly_data.get("listCopiedImages", []))),
            }

        # Write JSON file
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(Uti.Style.GREEN + f"[INFO] JSON file saved: {json_path}" + Uti.Style.RESET)
        return json_path


    @staticmethod
    def load_transfer_info(
            output_folder: Union[str, Path],
            cam_type: str,
            img_type: str,
            verbose: bool = False
    ) -> Optional[Dict]:

        """
        Load transfer information (Sync/Fly) previously saved in a JSON file.

        Parameters
        ----------
        output_folder : str | Path
            Folder containing the saved JSON file.
        cam_type : str
            Camera type ("VIS" or "NIR").
        img_type : str
            Image type ("jpg", "raw", "dng").

        Returns
        -------
        dict | None
            A dictionary containing all loaded information:
            {
                "cam_type": ...,
                "img_type": ...,
                "inputFolder": ...,
                "tkoff": { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] },
                "sync": { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] },
                "fly":  { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] }
            }

            Returns None if the JSON file does not exist or is invalid.
        """

        # Construct full path to the JSON file
        output_folder = Path(output_folder)
        json_path = output_folder / f"transfer_info_{cam_type}_{img_type}.json"

        # Check if the JSON file exists
        if not json_path.exists():
            if verbose : print(Uti.Style.YELLOW + f"[WARN] JSON file not found: {json_path}. Creating an empty JSON file." + Uti.Style.RESET)
            # Crée un fichier JSON vide
            json_path.parent.mkdir(parents=True, exist_ok=True)  # s'assure que le dossier existe
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)
            return None

        try:
            # Load JSON data
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            print(Uti.Style.GREEN + f"[INFO] JSON file loaded: {json_path}" + Uti.Style.RESET)
            return data

        except Exception as e:
            print(Uti.Style.RED + f"[ERROR] Failed to read {json_path}: {e}" + Uti.Style.RESET)
            return None

    @staticmethod
    def build_time_line_dictionnary(
            fichiers: List[Path],
            numeros: List[int],
            dates: List[Union[datetime, str]],
            deltas: np.ndarray,
            time_line: np.ndarray,
            cam_type: str = "VIS"
    ) -> Dict[str, List[Dict[str, Union[float, int, str]]]]:
        """
        Build a dictionary containing the timeline of an image sequence
        for a given camera type (VIS, NIR, etc.).

        Returns a dictionary in the form:
            { cam_type: [ {img_path, num_img, date_img, delta_img, time_line_relative}, ... ] }

        Each entry corresponds to an image and contains:
            - img_path : full path of the image
            - num_img  : image capture number
            - date_img : date in ISO format
            - delta_img: interval since previous image (s)
            - time_line_relative: cumulative time since first image (s)
        """

        data: List[Dict[str, Union[float, int, str]]] = []

        for i, f in enumerate(fichiers):
            delta: float = float(deltas[i - 1]) if i > 0 and i - 1 < len(deltas) else 0.0

            # Format the date as ISO string if datetime, else use string directly
            if isinstance(dates[i], datetime):
                date_str: str = dates[i].isoformat(timespec="seconds")
            else:
                date_str = str(dates[i])

            data.append({
                "img_path": str(f),
                "num_img": int(numeros[i]),
                "date_img": date_str,
                "delta_img": round(delta, 6),
                "time_line_relative": round(float(time_line[i]), 6)
            })

        return {cam_type: data}

    @staticmethod
    def save_time_line_json(
            output_dir: Union[str, Path],
            *timeline_dicts: Dict[str, List[Dict]]
    ) -> Path:
        """
        Save multiple timelines (VIS, NIR, etc.) into a single JSON file.

        Example of usage:
            save_time_line_json(output_dir, vis_timeline, nir_timeline)

        The final JSON file will have the structure:
        {
            "VIS": [ ... ],
            "NIR": [ ... ]
        }
        """

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file: Path = output_dir / "time_line.json"

        # Merge all timeline dictionaries by camera key
        merged: dict[str, list[dict]] = {}
        for d in timeline_dicts:
            merged.update(d)

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=4, ensure_ascii=False)

        print(Uti.Style.GREEN + f"💾 JSON file saved: {out_file}" + Uti.Style.RESET)
        return out_file


    @staticmethod
    def extract_dng_capture_date(file_path: Path, verbose: bool = False) -> Optional[datetime]:
        """
        Extracts the capture date of a DJI DNG file using EXIF tags (DateTimeOriginal).

        Returns a datetime object or None if the tag is not found.
        """
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
                date_tag = tags.get('EXIF DateTimeOriginal')
                if date_tag:
                    # Expected format: 'YYYY:MM:DD HH:MM:SS'
                    dt = datetime.strptime(str(date_tag), '%Y:%m:%d %H:%M:%S')
                    if verbose:
                        print(f"Capture date: {dt}")
                    return dt
                else:
                    print(Uti.Style.YELLOW + f"⚠️ DateTimeOriginal not found in {file_path.name}" + Uti.Style.RESET)
                    return None
        except Exception as e:
            print(f"❌ Error extracting EXIF from {file_path.name}: {e}")
            return None


    @staticmethod
    def true_recording_period(
            dates: list[datetime],
            sauts: list[tuple[int, int, float]],
            periode_time_lapse: float
    ) -> float:
        """
        Computes the true recording period of an image sequence, taking into account detected jumps.

        Logic:
        - If jumps are present, compute the mean jump duration.
        - If the mean jump is an exact multiple of the estimated time-lapse period,
          the jumps are considered "real" (i.e., intentional or consistent with the capture rate),
          and the true recording period is set to the estimated time-lapse period.
        - Otherwise, or if no jumps are detected, the true recording period is calculated
          as the total elapsed time divided by the number of intervals (dates - 1),
          which accounts for possible small timing variations or EXIF artifacts ("apparent" jumps).

        Parameters
        ----------
        dates : list[datetime]
            List of capture times for each image in the sequence.
        sauts : list[tuple[int, int, float]]
            List of detected jumps as tuples (index1, index2, delta_time).
            These can be "real", "apparent", or "abnormal".
        periode_time_lapse : float
            Estimated nominal period between consecutive images (s).

        Returns
        -------
        float
            The true recording period in seconds.
        """
        n_intervals = len(dates) - 1
        if n_intervals <= 0:
            return 0.0

        if sauts:
            delta_jumps = np.array([d for (_, _, d) in sauts])
            mean_jump = np.mean(delta_jumps)

            # Check if the mean jump is a multiple of the estimated period
            if np.isclose(mean_jump / periode_time_lapse, round(mean_jump / periode_time_lapse), atol=0.01):
                # Jumps are exact multiples → true period = estimated period
                true_record_period = periode_time_lapse
                print(Uti.Style.GREEN + f"📌 true_recording_period (excluding jumps): {true_record_period:.3f} s" + Uti.Style.RESET)
            else:
                # True period = total duration / number of intervals
                true_record_period = (dates[-1] - dates[0]).total_seconds() / n_intervals
                print(Uti.Style.GREEN + f"📌 true_recording_period: {true_record_period:.3f} s" + Uti.Style.RESET)
        else:
            # No jumps → true period = total duration / number of intervals
            true_record_period = (dates[-1] - dates[0]).total_seconds() / n_intervals
            print(Uti.Style.GREEN + f"📌 true_recording_period: {true_record_period:.3f} s" + Uti.Style.RESET)

        return true_record_period


    def load_inputFolder_2_outputFolder(self,
                                        inputFolder: str,
                                        listInputImages: List[str],
                                        outputFolder: str,
                                        id_min: int,
                                        id_max: int,
                                        pgsbar0: int,
                                        pgrbar1: int) -> List[str]:
        """
        Load images from the input folder to the output folder based on specified criteria.

        Parameters:
        - inputFolder (str): The folder from which images will be loaded.
        - listInputImages (List[Tuple[int, str]]): List of image data, where each item is a tuple containing an image number and image name.
        - outputFolder (str): The folder to which selected images will be copied.
        - id_min (int): The minimum image number to be considered for copying.
        - id_max (int): The maximum image number to be considered for copying.
        - pgsbar0 (int): Initial value for progress bar updating.
        - pgrbar1 (int): Final value for progress bar updating.

        Returns:
        None
        """
        listFileName = []
        for imgFileName in listInputImages:   # imgFileName   name + extension
            num_img, name_img = self.extract_num_image(imgFileName)
            if id_min <= num_img <= id_max:
                listFileName.append(imgFileName)
                self.copy_images(inputFolder, imgFileName, outputFolder)
                self.progress_bar.setValue(pgsbar0 + int((pgrbar1-pgsbar0)*(len(listFileName) / (id_max + 1 - id_min))))

        #  end of loading images associated with the imgTyp type in the mission files
        LoadVisNirImagesDialog.flagAllImageOK = True
        return listFileName


    @staticmethod
    def create_list_image_in_input_folder(input_folder: Union[str, str], ext: str) -> Optional[List[str]]:
        """
        Create a list of image file names with a specific extension in the given input folder.

        Parameters:
        - input_folder (Union[str, str]): The folder from which image file names will be listed.
        - ext (str): The file extension to filter image files.

        Returns:
        - List[str]: A list of image file names with the specified extension.
          Returns None if the input_folder is not a directory.
        """

        # Checks if the given path is a folder
        if not os.path.isdir(input_folder):
            return None
        # List all files in folder
        files = os.listdir(input_folder)
        # Filter the list to keep only .ext type files
        listInputImages = [f for f in files if f.lower().endswith('.' + ext)]
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


    @staticmethod
    def copy_images(inputDir: str, imgName: str, outputDir: str) -> Optional[str]:
        """
        Copy an image file from the input directory to the output directory.

        Parameters:
        - inputDir (str): The directory from which the image file will be copied.
        - imgName (str): The name of the image file to be copied.
        - outputDir (str): The directory to which the image file will be copied.

        Returns:
        - str: A message indicating the result of the copy operation.
        """
        source = os.path.join(inputDir, imgName)     # Constructs the full path of the source file
        # Check if the source file exists
        if not os.path.isfile(source):
            return "The source file does not exist."
        # Check if the destination folder exists, create it if not
        if not os.path.isdir(outputDir):
            os.makedirs(outputDir)
        destination = os.path.join(outputDir, imgName)   # Construct the full path of the destination file
        shutil.copy(source, destination)    # Copy file
        return f"File {imgName} was successfully copied from {inputDir} to {outputDir}."


    def init_image_takeoff_available(self, path_image_takeoff: str) -> None:
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
            if self.type_img in {"VIS", "DNG", "dng", "Dng", "vis", "Vis"}:
                self.ext = "DNG"
                # Check if the path to the takeoff image is provided and it exists

                # ---------------------------------------------------
                # Test if the takeoff point image is available..
                # if path_image_takeoff is not None:
                #    if os.path.exists(path_image_takeoff):
                # ---------------------------------------------------
                if path_image_takeoff is not None and os.path.exists(path_image_takeoff):
                    self.path_image_takeoff = path_image_takeoff
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
            file_path = Uti.safe_path(file_path)
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
                filename, file_extension = os.path.splitext(os.path.basename(file_path))
                self.image_name_labels[0].setText(f"{self.img_legend[0]}  : \n {filename}  {file_extension}")
                self.image_name_labels[0].setStyleSheet("color: darkBlue;")

                self.listImgRefPath[0] = file_path
                self.listVisRefPath[0] = file_path

            # Updated class flags with new values. New window position if moved
            self.currentUserDir = self.new_user_dir
            if all(elem is True for elem in self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
        except Exception as e:
            print("error in open_takeoff_image : ", e)


    def open_sync_and_fly_image_VIS_or_NIR(self, type_img: str, typ_ext: str, index: int) -> None:
        """
        Open and display a synchronization or flight image (VIS), given its type and index.

        If typ_ext is 'dng', uses rawpy for RAW decoding; otherwise uses QPixmap directly.

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
            if typ_ext.lower() == "dng":
                file_path = Path(self.info_vis_dng[key_1]['outputFolder']) / self.info_vis_dng[key_1]['listCopiedImages'][index_img]
                file_path = Uti.safe_path(file_path)
                input_file_path = Path(self.info_vis_dng['inputFolder']) / self.info_vis_dng[key_1]['listCopiedImages'][index_img]
                input_file_path = Uti.safe_path(input_file_path)
            elif typ_ext.lower() == "jpg":
                file_path = Path(self.info_nir_jpg[key_1]['outputFolder']) / self.info_nir_jpg[key_1]['listCopiedImages'][index_img]
                file_path = Uti.safe_path(file_path)
                input_file_path = Path(self.info_nir_jpg['inputFolder']) / self.info_nir_jpg[key_1]['listCopiedImages'][index_img]
                input_file_path = Uti.safe_path(input_file_path)
            else:
                raise ValueError(f"Invalid file extension: {typ_ext.lower()}")

            if not file_path:
                raise FileNotFoundError(f"File not found: {file_path}")

            # --- Load image according to its type ---
            typ_ext = typ_ext.lower()
            if typ_ext == "dng":
                # Use rawpy for RAW files
                with rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess()
                    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
                    pixmap = QPixmap.fromImage(image)
            else:
                # Direct load for JPG, PNG, etc.
                pixmap = QPixmap(str(file_path))
                if pixmap.isNull():
                    raise ValueError(f"Unable to load image: {file_path}")

            # --- Scale and display ---
            pixmap = pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            self.image_labels[index].setPixmap(pixmap)

            # --- Filename and legend information ---
            filename, file_extension = os.path.splitext(os.path.basename(file_path))
            self.image_name_labels[index].setText(f"{self.img_legend[0]}  : \n {filename}  {file_extension}")
            self.image_name_labels[index].setStyleSheet("color: darkBlue;")

            # --- Store input/output paths ---
            self.listImgRefPath[index] = input_file_path
            self.listVisRefPath[index] = input_file_path

            # --- Update flags and UI ---
            self.flags[index] = True
            self.new_user_dir = os.path.dirname(file_path)
            self.user_dir = os.path.dirname(file_path)
            self.currentUserDir = self.new_user_dir

            if all(self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")

        except Exception as e:
            print("error in open_sync_and_fly_image_VIS_or_NIR:", e)


    def open_image(self, numBtn: int, image_label: QLabel, image_name_label: QLabel, image_type: str):
        """
        Open an image and update relevant UI components.

        This method attempts to open and display an image based on the provided image type.
        It also sets various flags and updates UI components based on the operation's success.

        Parameters:
        - numBtn (int): Index used for referencing certain UI components and flags.
        - image_label (QLabel): QLabel to display the image.
        - image_name_label (QLabel): QLabel to display the image name.
        - image_type (str): Type of the image to be opened ("dng" or "jpg").

        Returns:
        None
        """
        try:
            flags = self.flags
            self.user_dir = self.currentUserDir
            flags[numBtn] = self.open_and_display_image(numBtn, image_label, image_name_label, image_type)
            # Updated class flags with new values. New window position if moved
            self.flags[numBtn] = flags[numBtn]
            self.currentUserDir = self.new_user_dir
            if all(self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
        except Exception as e:
            print("error in open_image : ", e)


    def open_and_display_image(self, numBtn: int, image_label: QLabel, image_name_label: QLabel, image_type: str):
        """
        Open and display an image of a specified type.

        This method tries to open an image file of the specified type, process it if necessary,
        and then display it in the provided QLabel. It also updates other relevant UI components.

        Parameters:
        - numBtn (int): Index used for referencing certain UI components and flags.
        - image_label (QLabel): QLabel to display the image.
        - image_name_label (QLabel): QLabel to display the image name.
        - image_type (str): Type of the image to be opened ("dng" or "jpg").

        Returns:
        - bool: Flag indicating whether the image was successfully opened and displayed.
        """

        try:
            flag = False
            if all(elem is False for elem in self.flags) or not os.path.exists(self.user_dir):
                self.user_dir = os.path.abspath('/')
                self.new_user_dir = self.user_dir
            self.new_user_dir = self.user_dir

            file_path, _ = QFileDialog.getOpenFileName(None, f"Select an image {image_type}", self.user_dir,
                                                       f"Images (*.{image_type});;All files (*)")
            if file_path:
                self.new_user_dir = os.path.dirname(file_path)
                if image_type.lower() == "dng":
                    # Use rawpy library to open DNG files
                    with rawpy.imread(file_path) as raw:
                        rgb = raw.postprocess()
                        pixmap = QPixmap.fromImage(
                            QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888))
                elif image_type.lower() == "jpg":
                    # Opens normal JPG files with QPixmap
                    pixmap = QPixmap(file_path)
                else:
                    print(f"Unsupported image format : {image_type}")
                    flag = False
                    # return flag, self.new_user_dir
                    return flag
                pixmap = pixmap.scaled(image_label.size(), Qt.AspectRatioMode.KeepAspectRatio)
                image_label.setPixmap(pixmap)
                filename, file_extension = os.path.splitext(os.path.basename(file_path))
                image_name_label.setText(f"{self.img_legend[numBtn]}  : \n {filename}  {file_extension}")
                image_name_label.setStyleSheet("color: darkBlue;")
                self.listImgRefPath[numBtn] = file_path
                if image_type == "DNG":
                    self.listVisRefPath[numBtn] = file_path

                elif image_type == "jpg":
                    self.listNirRefPath[numBtn] = file_path
                flag = True
            # return flag, self.new_user_dir
            return flag
        except Exception as e:
            print("error in open_and_display_image ; ", e)


    @staticmethod
    def on_help() -> None:
        """
        """
        try:
            Uti.show_info_message("IRDrone", "Sorry, this feature is under development.", "")
        except Exception as e:
            print("error", e)
        pass


    def choice_of_reference_images_consistency_analysis(self, inputFolder: str) -> bool:
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
        message = ""
        if (inputFolder != os.path.dirname(self.listImgRefPath[1]) or
                inputFolder != os.path.dirname(self.listImgRefPath[2]) or
                inputFolder != os.path.dirname(self.listImgRefPath[3]) or
                inputFolder != os.path.dirname(self.listImgRefPath[4])):

            consistency_choice = False
            labels = ["first image of Sync", "last image of Sync", "first image of Fly", "last image of Fly"]
            for idx, label in zip(range(1, 5), labels):
                if inputFolder != os.path.dirname(self.listImgRefPath[idx]):
                    message += f" | {label} \n"
        else:
            consistency_choice = True

        if not consistency_choice:
            # Uti.show_error_message` is a method to display error messages to the user.
            Uti.show_error_message(f"We detected an inconsistency in the choice of reference images: \n {message} \n Please note they must come from the same folder: \n {inputFolder} !")

        return consistency_choice

    @staticmethod
    def _dict_has_keys( d: dict, keys: list[str]) -> bool:
        """ Vérifie que le dictionnaire contient toutes les clés requises. """
        if not isinstance(d, dict):
            return False
        for k in keys:
            if k not in d:
                print(f"DEBUG: clé manquante : '{k}'")
                return False
            if d[k] in (None, ""):
                print(f"DEBUG: valeur vide pour '{k}'")
                return False
        return True

    @staticmethod
    def _validate_takeoff_paths(info: dict) -> bool:
        """ Vérifie l'existence des chemins source et destination. """
        try:
            src = Path(info["File path take-off"])
            dst_full = Path(info["path mission image take-off"])
        except Exception as exc:
            print(f"DEBUG: cannot build Path: {exc}")
            return False

        if not src.exists() or not src.is_file():
            print(f"DEBUG: fichier source inexistant : {src}")
            return False

        if not dst_full.parent.exists():
            print(f"DEBUG: dossier destination inexistant : {dst_full.parent}")
            return False

        return True

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

# ================================================================================
#              modules hors des class
# ================================================================================
def choose_folder_mission(
    dic_takeoff: dict,
    pref_screen_default_user_dir: str,
    AerialPhotoFolder: str,
    SynchroFolder: str
) -> Tuple[Path, bool]:
    """
    Choose the mission folder for IRDrone images.

    This function checks whether a takeoff image is available. If yes, it uses
    the folder indicated in dic_takeoff['File path mission'] and checks its consistency.
    Otherwise, it prompts the user to select a mission folder manually via a dialog.

    Parameters
    ----------
    dic_takeoff : dict
        Dictionary containing takeoff information including the mission file path.
    pref_screen_default_user_dir : str
        Default directory to open for folder selection dialog.
    AerialPhotoFolder : str
        Name of the folder to store aerial photos.
    SynchroFolder : str
        Name of the folder to store synchronization images.

    Returns
    -------
    Tuple[Path, bool]
        folderMissionPath: Path object pointing to the selected mission folder
        coherent_response: Boolean indicating if the folder name is consistent
    """
    try:
        image_takeoff_available, path_image_takeoff = Uti.image_takeoff_available_test(dic_takeoff, pref_screen_default_user_dir)

        if image_takeoff_available:
            # --- Construct the mission folder path ---
            folderMissionPath = Path(dic_takeoff['File path mission'])
            coherent_response = Uti.folder_name_consistency_analysis(folderMissionPath)

            if coherent_response:
                Uti.show_info_message(
                    "IRDrone",
                    f"Your images will be transferred to the mission folder:\n{folderMissionPath}",
                    f"They will be distributed between the folders {AerialPhotoFolder} and {SynchroFolder}"
                )
            else:
                coherent_response = False

            return folderMissionPath, coherent_response

        else:
            # --- Ask user to choose a mission folder ---
            Uti.show_warning_OK_Cancel_message(
                "IRDrone",
                "Choose the mission folder.",
                "It should follow the format: FLY_YearMonthDay_hourminute_[Place]",
                QMessageBox.Icon.Information
            )
            try:
                folderMissionPath = Path(QFileDialog.getExistingDirectory('Select Mission Folder', pref_screen_default_user_dir))

                if folderMissionPath.exists() and folderMissionPath != pref_screen_default_user_dir:
                    coherent_response = Uti.folder_name_consistency_analysis(folderMissionPath)
                    if not coherent_response:
                        Uti.show_warning_OK_Cancel_message(
                            "IRDrone",
                            f"You have chosen the folder:\n{folderMissionPath}\nwhich is not a Mission IRDrone folder.",
                            "Choose a compatible folder (name FLY_YYYYMMDD_hhmm_<free text>) or create a new mission using the <Create a New Mission> command."
                        )
                else:
                    Uti.show_warning_OK_Cancel_message(
                        "IRDrone",
                        f"You have chosen the folder:\n{folderMissionPath}\n",
                        "Your choice of folder is not recognized in IRDrone.\nChoose a compatible folder (name FLY_YYYYMMDD_hhmm_[Optional text])."
                    )
                    coherent_response = False

                return folderMissionPath, coherent_response

            except Exception as e:
                print("Error 1 in choose_folder_mission:", e)

    except Exception as e:
        print("Error 2 in choose_folder_mission:", e)


