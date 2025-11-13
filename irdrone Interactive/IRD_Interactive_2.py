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


    def __init__(self, width: int, height: int, type_img: str,  folderMission: Path = None, path_image_takeoff: Path = None):
        super().__init__()

        if folderMission is None or not folderMission.exists():
            raise ValueError(f"folderMission invalide : {folderMission}")

        self.num_images = 5
        self.pref_screen = Uti.Prefrence_Screen()
        self.screen_width = width
        self.screen_height = height
        self.target_screen_index = self.pref_screen.defaultScreenID
        self.screen_adjust = self.pref_screen.screenAdjust
        self.window_display_size = self.pref_screen.windowDisplaySize

        self.type_img = type_img
        if self.type_img == "VIS" or self.type_img == "DNG":
            self.ext = "dng"
            self.type_img = "VIS"
        elif self.type_img == "NIR" or self.type_img == "jpg":
            self.ext = "jpg"
            self.type_img = "NIR"
        else:
            self.ext = "jpg"


        self.currentUserDir = self.pref_screen.current_directory
        self.user_dir = self.currentUserDir
        self.new_user_dir = self.currentUserDir

        if os.path.exists(folderMission):
            self.folderMissionPath = folderMission
        else:
            print("error. Problem with: ", folderMission)

        self.init_image_takeoff_available(path_image_takeoff)


        # ---- lecture des données à transférer si elles existe déjà

        verbose = True
        self.image_0_available = False
        self.image_first_sync_available = False
        self.image_last_sync_available = False
        self.image_first_fly_available = False
        self.image_last_fly_available = False
        self.outputTakeoffFolder = Path(self.folderMissionPath) / "FlightAnalytics" if self.folderMissionPath else None
        self.outputTakeoffFolder.mkdir(parents=True, exist_ok=True)
        if self.outputTakeoffFolder:
            if self.type_img == "NIR":
                self.info_nir_jpg = self.load_transfer_info(self.outputTakeoffFolder, "NIR", "jpg")
                if self.info_nir_jpg:
                    if verbose:
                        print(f"📂 Données NIR (jpg) rechargées : \n"
                              f"  Dossier source sync: {self.info_nir_jpg['sync']['outputFolder']}\n"
                              f"  Phase Sync : {len(self.info_nir_jpg['sync']['listCopiedImages'])} images\n"
                              f"  Dossier source fly: {self.info_nir_jpg['fly']['outputFolder']}\n"
                              f"  Phase Fly  : {len(self.info_nir_jpg['fly']['listCopiedImages'])} images\n"
                              )
                    self.image_0_available = True
                    self.image_first_sync_available = True
                    self.image_last_sync_available = True
                    self.image_first_fly_available = True
                    self.image_last_fly_available = True

                else:
                    print("⚠️  Aucun fichier de transfert NIR jpg trouvé.")
            elif self.type_img == "VIS":
                self.info_vis_dng = self.load_transfer_info(self.outputTakeoffFolder, "VIS", "dng")
                if self.info_vis_dng:
                    if verbose:
                        print(f"📂 Données VIS (dng) rechargées : \n"
                              f"  Dossier source sync: {self.info_vis_dng['sync']['outputFolder']}\n"
                              f"  Phase Sync : {len(self.info_vis_dng['sync']['listCopiedImages'])} images\n"
                              f"  Dossier source fly: {self.info_vis_dng['fly']['outputFolder']}\n"
                              f"  Phase Fly  : {len(self.info_vis_dng['fly']['listCopiedImages'])} images\n"
                              )
                    self.image_0_available = False
                    self.image_first_sync_available = True
                    print(f'DEBUG 410   self.image_first_sync_available = {self.image_first_sync_available}')
                    self.image_last_sync_available = True
                    self.image_first_fly_available = True
                    self.image_last_fly_available = True
                else:
                    print("⚠️  Aucun fichier de transfert VIS dng trouvé.")

        self.init_GUI()

    def init_GUI(self):
        try:

            self.setStyleSheet("background-color: white; color: black;")
            #   Setting the top command bar and window dimensions
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
            # Creating locations for images
            self.image_labels = [QLabel() for _ in range(self.num_images)]
            # Creating locations for image captions.
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
                          "Load first image of fly.",
                          "Load last image of fly."]
            # Connection of buttons to actions
            button_width = int(0.9 * (self.screen_width // self.num_images))
            self.btn_command = [QPushButton(btn_legend[i]) for i in range(self.num_images)]
            for btn in self.btn_command:
                btn.setFixedWidth(button_width)
                btn.setStyleSheet("background-color: darkGray; color: black;")

            # Button to load all the images in the mission once the reference images have been chosen.
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

            # Progress bar when loading all images.
            self.progress_bar = QProgressBar()
            self.progress_bar.setValue(0)

            # Creating the layout of the main window.
            layout = QVBoxLayout()     # layout principal
            # top window for command bar
            top_layout = QHBoxLayout()
            for btn in self.btn_command:
                top_layout.addWidget(btn)
            # middle window for images and their captions
            middle_layout = QHBoxLayout()  # uses a vertical layout to stack labels
            for label in self.image_name_labels:
                middle_layout.addWidget(label)

            # ---------------- Image area. Creating a neutral image -----------------
            self.image_display_size = (int((self.screen_width-100)/self.num_images), int((self.screen_width-100)/self.num_images*3/4))  # image area size
            # Create an empty pixmap of the desired size and adjust the size if necessary
            self.empty_pixmap = QPixmap(* self.image_display_size)
            self.empty_pixmap.fill(QColor(Qt.GlobalColor.gray))  # transparent, gray, darkYellow etc)
            # Adjust the size if necessary
            self.empty_pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            #      Affiche l'image du Take-off (si elle est  disponible) comme première image.
            #      Dans ce cas le dossier qui la contient sera le dossier par défaut pour rechercher les autres images.

            # Creating a list to store pairs (image, QLabel)
            image_label_pairs = []
            for index, image_label in enumerate(self.image_labels):
                image_label.setPixmap(self.empty_pixmap)
                name_label = self.image_name_labels[index]
                name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Centers the QLabel text.

                # Applies CSS styling to reduce spacing between image and text
                image_label.setStyleSheet("margin-bottom: 100px;")
                image_label.setStyleSheet("margin-top: 30px;")
                # Add each (image-QLabel) pair to the list
                image_label_pairs.append((image_label, self.image_name_labels[index]))

            # Creating a list to store pairs (image, legend).
            middle_layout = QHBoxLayout()

            for image_label, name_label in zip(self.image_labels, self.image_name_labels):
                # Creating a vertical layout for each pair (image, legend).
                pair_layout = QVBoxLayout()

                # Adds image and caption to vertical layout.
                pair_layout.addWidget(image_label)
                pair_layout.addWidget(name_label)

                # Adds the vertical layout of the pair (image , legend) to the horizontal layout of the middle window.
                middle_layout.addLayout(pair_layout)



            #  bottom window for "load mission images" command and progress bar.
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

            # Disables btn_*_load_all_images on startup. It will be activated when all five images are loaded.
            self.btn_load_all_images.setEnabled(False)
            self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: gray;")

            # Chargement des images si séquence interactive déjà faite une fois
            print(f'DEBUG 420 self.type_img = {self.type_img}')
            if self.type_img == "VIS":
                if self.image_takeoff_available:
                    self.open_takeoff_image(self.path_image_takeoff)
                if self.image_first_sync_available:
                    print(f'BEBUG 102   chargement first image sync')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 1)
                if self.image_last_sync_available:
                    print(f'BEBUG 103   chargement last image sync VIS')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 2)
                if self.image_first_fly_available:
                    print(f'BEBUG 104   chargement first image fly VIS')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 3)
                if self.image_last_fly_available:
                    print(f'BEBUG 105   chargement last image fly VIS')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 4)
                if all(self.flags):
                    self.btn_load_all_images.setEnabled(True)
                    self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
            elif self.type_img == "NIR":
                if self.image_0_available:
                    print(f'BEBUG 201   chargement image NIR 0')
                if self.image_first_sync_available:
                    print(f'BEBUG 202   chargement first image sync NIR')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 1)
                if self.image_last_sync_available:
                    print(f'BEBUG 203   chargement last image sync NIR')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 2)
                if self.image_first_fly_available:
                    print(f'BEBUG 204   chargement first image fly NIR')
                    self.open_sync_and_fly_image_VIS_or_NIR(self.type_img, self.ext, 3)
                if self.image_last_fly_available:
                    print(f'BEBUG 205   chargement last image fly NIR')
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
            print("error in step2  init_GUI :", e)


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
            print(f'DEBUG 700  os.path.basename(self.listImgRefPath[1]) = {os.path.basename(self.listImgRefPath[1])}')
            print(f'DEBUG 701  os.path.basename(self.listImgRefPath[2]) = {os.path.basename(self.listImgRefPath[2])}')

            idMinSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[1]))[0].split("_")[-1])
            idMaxSync = int(os.path.splitext(os.path.basename(self.listImgRefPath[2]))[0].split("_")[-1])
            outputSyncFolder = os.path.join(outputFolder, "Synchro")
            if not os.path.isdir(outputSyncFolder):
                # print("The destination folder ", outputSyncFolder, " of the images does not exist!")
                Uti.show_error_message(f"The destination folder {outputSyncFolder} for the images does not exist!\n"
                                       f"Check that you have already created the mission.")

            idMinFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[3]))[0].split("_")[-1])
            idMaxFly = int(os.path.splitext(os.path.basename(self.listImgRefPath[4]))[0].split("_")[-1])

            idMinTakeoff = int(os.path.splitext(os.path.basename(self.listImgRefPath[0]))[0].split("_")[-1])
            idMaxTakeoff = idMinTakeoff


            outputFlyFolder = os.path.join(outputFolder, "AerialPhotography")
            outputTakeoffFolder = os.path.join(outputFolder, "FlightAnalytics")
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

                # ----------  calcul de la time line NIR
                print(f'TEST 0061  calcul time line NIR  en developpement ....')
                print(f'TEST 0062  inputFolder : {inputFolder}  pour images NIR')
                dates_NIR, numeros_NIR, deltas_NIR, time_line_NIR, fichiers_img_NIR = \
                    self.time_line_analyser_images(inputFolder, img_Typ=self.currentImgTyp, extension=".RAW", verbose=False)
                self.save_time_line_json(
                    fichiers=fichiers_img_NIR,
                    numeros=numeros_NIR,
                    dates=dates_NIR,
                    deltas=deltas_NIR,
                    time_line=time_line_NIR,
                    output_dir=outputTakeoffFolder,
                    cam_type=self.currentImgTyp
                )

                # ----------  transfer of NIR images of the Sync and Fly phase (jpg) ----------------
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "jpg")
                listSyncImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync, idMaxSync, 0, 10)
                listFlyImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly, idMaxFly, 10, 30)
                self.save_transfer_info(
                    output_folder=outputTakeoffFolder,
                    input_folder=inputFolder,
                    cam_type=self.currentImgTyp,
                    img_type="jpg",
                    sync_data={
                        "outputFolder": outputSyncFolder,
                        "idMin": idMinSync,
                        "idMax": idMaxSync,
                        "listCopiedImages": listSyncImages,
                    },
                    fly_data={
                        "outputFolder": outputFlyFolder,
                        "idMin": idMinFly,
                        "idMax": idMaxFly,
                        "listCopiedImages": listFlyImages
                    }
                )
                # ----------  transfer of NIR images of the Sync and Fly phase (raw) ----------------
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "raw")
                listSyncImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync - 1, idMaxSync - 1, 30, 60)
                listFlyImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly - 1, idMaxFly - 1, 60, 100)
                self.save_transfer_info(
                    output_folder=outputTakeoffFolder,
                    input_folder=inputFolder,
                    cam_type=self.currentImgTyp,
                    img_type="raw",
                    sync_data={
                        "outputFolder": outputSyncFolder,
                        "idMin": idMinSync,
                        "idMax": idMaxSync,
                        "listCopiedImages": listSyncImages,
                    },
                    fly_data={
                        "outputFolder": outputFlyFolder,
                        "idMin": idMinFly,
                        "idMax": idMaxFly,
                        "listCopiedImages": listFlyImages
                    }
                )
            elif self.currentImgTyp == "VIS":
                # ----------  calcul de la time line NIR
                print(f'TEST 0070  calcul time line VIS  en developpement ....')
                dates_VIS, numeros_VIS, deltas_VIS, time_line_VIS, fichiers_img_VIS = \
                    self.time_line_analyser_images(inputFolder, img_Typ=self.currentImgTyp, extension=".DNG", verbose=False)
                self.save_time_line_json(
                    fichiers=fichiers_img_VIS,
                    numeros=numeros_VIS,
                    dates=dates_VIS,
                    deltas=deltas_VIS,
                    time_line=time_line_VIS,
                    output_dir=outputTakeoffFolder,
                    cam_type=self.currentImgTyp
                )
                # ----------   transfer of VIS images of the Sync  phase (dng) ----------------
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "dng")
                listSyncImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync, idMaxSync, 0, 30)
                # ----------   transfer of VIS images of the Fly  phase (dng)----------------
                listFlyImages = self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly, idMaxFly, 30, 98)
                self.save_transfer_info(
                    output_folder=outputTakeoffFolder,
                    input_folder=inputFolder,
                    cam_type=self.currentImgTyp,
                    img_type="dng",
                    sync_data={
                        "outputFolder": outputSyncFolder,
                        "idMin": idMinSync,
                        "idMax": idMaxSync,
                        "listCopiedImages": listSyncImages,
                    },
                    fly_data={
                        "outputFolder": outputFlyFolder,
                        "idMin": idMinFly,
                        "idMax": idMaxFly,
                        "listCopiedImages": listFlyImages
                    }
                )

                # ----------   transfer of VIS images of the take-off (dng)----------------
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputTakeoffFolder, idMinTakeoff, idMaxTakeoff, 98, 100)

            self.progress_bar.setValue(100)

            # print("All images have been transferred successfully.")
            Uti.show_info_message("IRDrone", f"Your {(max((idMaxFly - idMinFly),0) + max((idMaxSync - idMinSync),0))}  images have been transferred \n from directory {inputFolder}  of the camera SD card \n to the mission directory {outputFlyFolder}.",
                                  "You can close this window.", QMessageBox.Icon.Information)
            self.btn_validate_load_all_images.setEnabled(True)
            self.btn_validate_load_all_images.setStyleSheet("background-color: gray; color: white;")


        except Exception as e:
            print("error in on_load_all_images  :", e)


    def extract_files_images(self, inputFolder, extension=".tif", verbose=False):
        """
        retourne la liste des images d'un type donné présentes dans un dossier

        Paramètres
        ----------
        base_dir : Path ou str
            Chemin de base
        folder_name : str
            Nom du sous-dossier à examiner
        extension : str
            Extension des fichiers à traiter (par défaut ".tif").
            Valeurs admises : .raw, .tif, .jpg, .jpeg, .png (insensible à la casse).
        return:
        ----------
        fichiers : liste des chemins des images
        """
        # Normaliser l'extension (insensible à la casse, toujours avec un point)
        extension = extension.lower()
        if not extension.startswith("."):
            extension = "." + extension

        extensions_valides = [".dng", ".raw", ".tif", ".jpg", ".jpeg", ".png"]
        if extension not in extensions_valides:
            raise ValueError(f"Extension '{extension}' non supportée. "
                             f"Choisir parmi {extensions_valides}")

        # Chemin du dossier à explorer
        folder_path = Path(inputFolder)

        # Liste des fichiers avec extension correspondante, insensible à la casse
        fichiers = sorted([f for f in folder_path.iterdir()
                           if f.suffix.lower() == extension])

        if verbose: print(f"🔍 {len(fichiers)} fichiers {extension.upper()} trouvés")

        return fichiers


    def time_line_analyser_images(self, inputFolder, img_Typ=None, extension=".tif", verbose=False):
        """
        Analyse les fichiers d'un dossier :
          - extrait la date et l'heure du nom de fichier
          - extrait le numéro de prise de vue (XXX)
          - calcule les écarts de temps entre images successives
          - vérifie la régularité des intervalles de temps
          - estime la période nominale (méthode médiane, mode, filtrage outliers)
          - affiche les éventuels "sauts" détectés
          - tolérance de filtrage calculée automatiquement (1% de la médiane)
        """

        fichiers = self.extract_files_images(inputFolder, extension=extension)

        dates = []
        numeros = []

        if img_Typ == "NIR":
            for f in fichiers:
                stem = f.stem
                try:
                    # Pour le calcul du temps on ne tient pas compte de l'année.
                    # En effet pour la SJCam M20 si la batterie est démontée la date par défaut est celle de sa construction (par exemple année 2019)
                    # Si l'opérateur n'a pas réinitialisé la date alors ladifférence avec la date de la mission peut être de plusieurs années ( 7 ans en 2026)
                    # Cela va conduire à manipler inutilement des très grand nombre.
                    # Toutefois cela pourrait présenter une difficulté dans le cas d'images réalisées à cheval sur deux années
                    # ce qui est toutefois très improbable !
                    # Il est hautement souhaitable de mettre la caméra SJCam à l'heure  (pas besoin d'être précis à la seconde!)
                    annee, reste = stem.split("_", 1)
                    moisjour, heuresec, numero = reste.split("_")

                    dt = datetime.strptime(f"{annee}{moisjour}{heuresec}", "%Y%m%d%H%M%S")
                    if verbose:
                        print(f'image {extension} N° : {numero} | time {heuresec}')

                    dates.append(dt)
                    numeros.append(int(numero))
                except Exception as e:
                    print(f"⚠️ Nom de fichier ignoré ({stem}): {e}")


        elif img_Typ == "VIS":
            for f in fichiers:
                stem = f.stem
                file_path = Path(f)
                # extraction du numero de la prise de vue
                match = re.search(r'(\d+)$', stem)
                if match:
                    numero = int(match.group(1))
                else:
                    print("Numéro de prise non trouvé")
                # extraction de la date de la prise de vue
                dt = self.extract_dng_capture_date(file_path)
                dates.append(dt)
                numeros.append(int(numero))
                if verbose:
                    print(f'image {extension} N° : {numero} | time {dt}')

        else:
            print(f"⚠️ type invalide ({img_Typ}): {e}")

        dates = np.array(dates)
        numeros = np.array(numeros)

        if len(dates) > 1:
            deltas = np.diff([d.timestamp() for d in dates])
            if verbose: print(deltas)
        else:
            deltas = np.array([])

        if len(deltas) == 0:
            print("⚠️ Pas assez d'images pour calculer des intervalles.")
            return dates, numeros, deltas

        print(f"🔍 {len(dates)} fichiers {extension.upper()} trouvés")
        # --- Durée totale de la séquence ---
        duree_totale = (dates[-1] - dates[0]).total_seconds()
        print(f"⏱️ Durée totale de la séquence : {duree_totale:.3f} s "
              f"({str(dates[-1] - dates[0])})")

        # --- Méthode 1 : Médiane ---
        periode_mediane = np.median(deltas)
        # print(f"📌 Période estimée (médiane) : {periode_mediane:.3f} s")

        # --- Méthode 2 : Mode ---
        counts = Counter(np.round(deltas, 3))
        periode_mode, freq = counts.most_common(1)[0]
        # print(f"📌 Période estimée (mode)    : {periode_mode:.3f} s "
        #      f"(fréquence: {freq}/{len(deltas)})")

        # --- Tolérance adaptative pour filtrage ---
        tol = max(0.001, 0.01 * periode_mediane)  # 1% de la période, minimum 1 ms

        # --- Méthode 3 : Filtrage outliers ---
        ecarts_corrects = deltas[np.abs(deltas - periode_mediane) < tol]
        if len(ecarts_corrects) > 0:
            periode_filtre = np.mean(ecarts_corrects)
            # print(f"📌 Période estimée (filtrée): {periode_filtre:.3f} s "
            #       f"(tolérance {tol:.3f} s)")
        else:
            periode_filtre = periode_mediane
            print("⚠️ Aucun intervalle dans la tolérance définie pour le filtrage.")

        # --- Meilleure estimation du time-lapse ---
        estims = np.array([periode_mediane, periode_mode, periode_filtre])
        periode_time_lapse = np.median(estims)
        print(f"📌 Meilleure estimation du time-lapse : {periode_time_lapse:.3f} s")
        # --- Détection des sauts ---
        sauts = []
        for i, d in enumerate(deltas):
            if not np.isclose(d, periode_mediane, atol=tol):
                sauts.append((i, i + 1, d))  # on garde juste les indices
        # --- Période réelle d'enregistrement en tenant compte des sauts ---
        periode_reelle = self.vraie_periode_enregistrement(dates, sauts, periode_time_lapse)

        if sauts:
            print(f"⚠️ {len(sauts)}  Sauts détectés :")
            for idx1, idx2, delta in sauts:
                f1 = fichiers[idx1]
                f2 = fichiers[idx2]
                print(f"   - Entre fichier {f1} et fichier {f2} : {delta:.3f} s")
        else:
            print(f"✅️ {len(sauts)}  Aucun saut détecté :")

        # --- Construction de la timeline réelle ---
        def construire_time_line(dates, sauts, periode_reelle, numeros, verbose=False):
            """
            Construit un vecteur des temps réels écoulés depuis la première image,
            en tenant compte des vrais sauts et de la période réelle.
            Si verbose=True, affiche la timeline image par image avec indication des sauts.
            """
            n = len(dates)
            if n == 0:
                return np.array([])

            time_line = np.zeros(n, dtype=float)
            # dictionnaire pour accès rapide aux deltas des sauts
            dict_sauts = {i: d for (i, _, d) in sauts}

            if verbose:
                print("\n--- Timeline réelle (ajustée) ---")
                print(f"image raw N° : {numeros[0]:03d} | time_line {time_line[0]:.3f} s")

            for i in range(1, n):
                # Par défaut : avance normale
                delta = periode_reelle
                saut_txt = ""

                # Si un saut est signalé pour l'intervalle précédent
                if (i - 1) in dict_sauts:
                    d_saut = dict_sauts[i - 1]
                    ratio = d_saut / periode_reelle

                    # Cas 1 : vrai saut → multiple entier (±0.49 s de marge)
                    if np.isclose(ratio, round(ratio), atol=0.49 / periode_reelle):
                        delta = d_saut
                        saut_txt = f" | saut {d_saut:.3f} s)"
                        # saut_txt = f" | saut {d_saut:.3f} s (x{ratio:.1f})"
                    # Cas 2 : saut faible (< 2x période) → ignoré (artefact EXIF)
                    elif d_saut < 2 * periode_reelle:
                        # delta reste = periode_reelle
                        saut_txt = f" | saut ignoré ({d_saut:.3f} s)"
                    else:
                        # saut anormal, on le garde mais on le signale
                        delta = d_saut
                        saut_txt = f" | saut anormal {d_saut:.3f} s"

                # incrément de la timeline
                time_line[i] = time_line[i - 1] + delta

                if verbose:
                    print(f"image raw N° : {numeros[i]:03d} | time_line {time_line[i]:.3f} s{saut_txt}")

            if verbose:
                print("---------------------------------\n")

            return time_line

        time_line = construire_time_line(dates, sauts, periode_reelle, numeros, verbose=True)

        # Résumé global
        print(f"🕒 Timeline calculée : {time_line[-1]:.3f} s jusqu'à la dernière image "
              f"(n={len(time_line)})")

        return dates, numeros, deltas, time_line, fichiers


    def save_transfer_info(self,
            output_folder,
            input_folder,
            cam_type,
            img_type,
            sync_data=None,
            fly_data=None,
            ):
        """
        Sauvegarde les informations de transfert (phases Sync et Fly) dans un fichier JSON unique.

        Parameters
        ----------
        output_folder : str | Path
            Dossier dans lequel sera créé le fichier JSON.
        input_folder : str | Path
            Dossier source d'entrée.
        cam_type : str
            Type de caméra (ex: "VIS" ou "NIR").
        img_type : str
            Type d'image (ex: "jpg", "raw", "dng").
        sync_data : dict | None
            Données de la phase Sync :
                {"outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...]}
        fly_data : dict | None
            Données de la phase Fly :
                {"outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...]}
        """

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        # Nom du fichier avec type caméra et type image
        json_name = f"transfer_info_{cam_type}_{img_type}.json"
        json_path = output_folder / json_name

        data = {
            "cam_type": cam_type,
            "img_type": img_type,
            "inputFolder": str(input_folder),
        }

        if sync_data:
            data["sync"] = {
                "outputFolder": str(sync_data.get("outputFolder", "")),
                "idMin": int(sync_data.get("idMin", -1)),
                "idMax": int(sync_data.get("idMax", -1)),
                "listCopiedImages": list(map(str, sync_data.get("listCopiedImages", []))),
            }

        if fly_data:
            data["fly"] = {
                "outputFolder": str(fly_data.get("outputFolder", "")),
                "idMin": int(fly_data.get("idMin", -1)),
                "idMax": int(fly_data.get("idMax", -1)),
                "listCopiedImages": list(map(str, fly_data.get("listCopiedImages", []))),
            }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"[INFO] Fichier JSON sauvegardé : {json_path}")
        return json_path


    def load_transfer_info(self, output_folder, cam_type, img_type):
        """
        Recharge les informations de transfert (Sync/Fly) sauvegardées dans un fichier JSON.

        Parameters
        ----------
        output_folder : str | Path
            Dossier contenant le fichier JSON sauvegardé.
        cam_type : str
            Type de caméra ("VIS" ou "NIR").
        img_type : str
            Type d'image ("jpg", "raw", "dng").

        Returns
        -------
        dict
            Un dictionnaire contenant toutes les informations lues :
            {
                "cam_type": ...,
                "img_type": ...,
                "inputFolder": ...,
                "sync": { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] },
                "fly":  { "outputFolder": ..., "idMin": ..., "idMax": ..., "listCopiedImages": [...] }
            }

            Retourne None si le fichier JSON n'existe pas ou s'il est invalide.
        """
        output_folder = Path(output_folder)
        json_path = output_folder / f"transfer_info_{cam_type}_{img_type}.json"

        if not json_path.exists():
            print(f"[WARN] Fichier JSON introuvable : {json_path}")
            return None

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[INFO] Fichier JSON chargé : {json_path}")
            return data
        except Exception as e:
            print(f"[ERREUR] Impossible de lire {json_path} : {e}")
            return None


    def save_time_line_json(self,
                            fichiers, numeros, dates, deltas, time_line,
                            output_dir, cam_type="VIS"
                            ):
        """
        Sauvegarde la timeline d'une séquence sous forme de fichier JSON.

        Chaque entrée correspond à une image et contient :
            - img_path : chemin complet de l'image
            - num_img  : numéro de la prise de vue
            - date_img : date au format ISO
            - delta_img: intervalle de temps depuis l'image précédente (s)
            - time_line_relative: temps cumulé depuis la première image (s)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        out_file = output_dir / f"time_line_{cam_type}.json"

        data = []
        for i, f in enumerate(fichiers):
            # delta pour la première image = 0
            delta = float(deltas[i - 1]) if i > 0 and i - 1 < len(deltas) else 0.0

            # conversion de la date en format lisible JSON
            if isinstance(dates[i], datetime):
                date_str = dates[i].isoformat(timespec="seconds")
            else:
                date_str = str(dates[i])

            data.append({
                "img_path": str(f),
                "num_img": int(numeros[i]),
                "date_img": date_str,
                "delta_img": round(delta, 6),
                "time_line_relative": round(float(time_line[i]), 6)
            })

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"💾 Fichier JSON sauvegardé : {out_file}")
        return out_file


    def extract_dng_capture_date(self, file_path: Path, verbose: bool = False) -> Optional[datetime]:
        """
        Extrait la date de capture d'un fichier DNG DJI via les tags EXIF (DateTimeOriginal).

        Retourne un datetime ou None si non trouvée.
        """
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
                date_tag = tags.get('EXIF DateTimeOriginal')
                if date_tag:
                    # format attendu : '2025:09:30 12:34:56'
                    dt = datetime.strptime(str(date_tag), '%Y:%m:%d %H:%M:%S')
                    if verbose: print(f'date de prise de vue  {dt}')
                    return dt
                else:
                    print(f"⚠️ DateTimeOriginal non trouvée dans {file_path.name}")
                    return None
        except Exception as e:
            print(f"❌ Erreur lors de l'extraction EXIF de {file_path.name} : {e}")
            return None


    def vraie_periode_enregistrement(self, dates, sauts, periode_time_lapse):
        """
         --- Période réelle d'enregistrement en tenant compte des sauts ---
         """
        n_intervalles = len(dates) - 1
        if n_intervalles > 0:
            if sauts:
                delta_sauts = np.array([d for (_, _, d) in sauts])
                mean_saut = np.mean(delta_sauts)
                # test si mean_saut est multiple de la période estimée
                if np.isclose(mean_saut / periode_time_lapse, round(mean_saut / periode_time_lapse), atol=0.01):
                    # les sauts sont des multiples exacts → période réelle = période estimée
                    periode_reelle = periode_time_lapse
                    print(f"📌 Période réelle d'enregistrement (hors sauts) : {periode_reelle:.3f} s")
                else:
                    # période réelle = durée totale / nombre d'intervalles
                    periode_reelle = (dates[-1] - dates[0]).total_seconds() / n_intervalles
                    print(f"📌 Période réelle d'enregistrement : {periode_reelle:.3f} s")
            else:
                # pas de sauts → période réelle = durée totale / nombre d'intervalles
                periode_reelle = (dates[-1] - dates[0]).total_seconds() / n_intervalles
                print(f"📌 Période réelle d'enregistrement : {periode_reelle:.3f} s")

        return periode_reelle


    def _format_duree(seconds: float) -> str:
        """Retourne une chaîne lisible en secondes ou minutes selon la durée."""
        if seconds > 300:  # plus de 5 minutes
            return f"{seconds / 60:.1f} min"
        else:
            return f"{seconds:.0f} s"


    def load_inputFolder_2_outputFolder(self, inputFolder: str, listInputImages: List[str], outputFolder: str, id_min: int, id_max: int, pgsbar0: int, pgrbar1: int) -> None:
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


    def create_list_image_in_input_folder(self, input_folder: Union[str, str], ext: str) -> Optional[List[str]]:
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


    def extract_num_image(self, imgPath: str) -> Tuple[int, str]:
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


    def copy_images(self, inputDir: str, imgName: str, outputDir: str) -> Optional[str]:
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
            if self.type_img in {"VIS", "DNG"}:
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
        except Exception as e:
            print("error   in init_image_takeoff_available", e)

    def safe_path(self, path):
        return Path(path).resolve().as_posix()
    

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
            file_path = self.safe_path(file_path)
            if file_path:
                print(f'DEBUG 500  première image VIS (takeoff) {file_path}')
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
                print(f'DEBUG 600   self.listImgRefPath[0] = {self.listImgRefPath[0]}')
                self.listVisRefPath[0] = file_path
                print(f'DEBUG 601   self.listVisRefPath[0] = {self.listVisRefPath[0]}')

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
        """
        try:
            # --- Sélection du bloc et de l’image à ouvrir ---
            if index == 1:
                key_1, index_img = 'sync', 0
            elif index == 2:
                key_1, index_img = 'sync', -1
            elif index == 3:
                key_1, index_img = 'fly', 0
            elif index == 4:
                key_1, index_img = 'fly', -1
            else:
                raise ValueError(f"Index invalide : {index}")

            # --- Construction du chemin complet ---
            if typ_ext.lower() == "dng":
                file_path = Path(self.info_vis_dng[key_1]['outputFolder']) / self.info_vis_dng[key_1]['listCopiedImages'][index_img]
                file_path = self.safe_path(file_path)
                input_file_path = Path(self.info_vis_dng['inputFolder']) / self.info_vis_dng[key_1]['listCopiedImages'][index_img]
                input_file_path = self.safe_path(input_file_path)
            elif typ_ext.lower() == "jpg":
                file_path = Path(self.info_nir_jpg[key_1]['outputFolder']) / self.info_nir_jpg[key_1]['listCopiedImages'][index_img]
                file_path = self.safe_path(file_path)
                input_file_path = Path(self.info_nir_jpg['inputFolder']) / self.info_nir_jpg[key_1]['listCopiedImages'][index_img]
                input_file_path = self.safe_path(input_file_path)
            else:
                raise ValueError(f"type extension invalide: {typ_ext.lower()}")

            if not file_path:
                raise FileNotFoundError(f"Fichier introuvable : {file_path}")

            # --- Chargement selon le type d’image ---
            typ_ext = typ_ext.lower()
            if typ_ext == "dng":
                # Utilisation de rawpy pour les fichiers RAW
                with rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess()
                    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
                    pixmap = QPixmap.fromImage(image)
            else:
                # Utilisation directe pour JPG, PNG, etc.
                pixmap = QPixmap(str(file_path))
                if pixmap.isNull():
                    raise ValueError(f"Impossible de charger l'image : {file_path}")

            # --- Mise à l’échelle et affichage ---
            pixmap = pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            self.image_labels[index].setPixmap(pixmap)

            # --- Infos et légende ---
            filename, file_extension = os.path.splitext(os.path.basename(file_path))
            self.image_name_labels[index].setText(f"{self.img_legend[0]}  : \n {filename}  {file_extension}")
            self.image_name_labels[index].setStyleSheet("color: darkBlue;")

            # --- Mémorisation des chemins d'entrée/sortie ---
            self.listImgRefPath[index] = input_file_path
            self.listVisRefPath[index] = input_file_path

            # --- Mise à jour des flags et de l’interface ---
            self.flags[index] = True
            self.new_user_dir = os.path.dirname(file_path)
            self.user_dir = os.path.dirname(file_path)
            self.currentUserDir = self.new_user_dir

            if all(self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")

        except Exception as e:
            print("error in open_sync_and_fly_image_VIS_or_NIR:", e)
            
            

    def open_sync_and_fly_image_VIS_or_NIR_old(self, type_img: str, typ_ext: str, index: int) -> None:
        """
        Open and display a first_synchro image VIS  given its path.

        This method attempts to open an image from a specified path, processes it,
        and displays it on the user interface. It also sets various attributes and
        updates the UI components accordingly. If the image file is successfully processed
        and displayed, relevant path attributes are updated, and UI components are adjusted
        to reflect the loaded image.
        """
        try:
            if index == 1:
                key_1 = 'sync'
                index_img = 0
            elif index == 2:
                key_1 = 'sync'
                index_img = -1
            elif index == 3:
                key_1 = 'fly'
                index_img = 0
            elif index == 4:
                key_1 = 'fly'
                index_img = -1
                
                                
            file_path = Path(self.info_vis_dng[key_1]['outputFolder']) / self.info_vis_dng[ key_1]['listCopiedImages'][index_img]
            file_path = self.safe_path(file_path)
            if not file_path or not file_path.exists():
                raise FileNotFoundError(f"Fichier introuvable : {file_path}")

            # --- Chargement selon le type d’image ---
            typ_ext = typ_ext.lower()
            if file_path:
                self.flags[index] = True
                self.new_user_dir = os.path.dirname(file_path)
                self.user_dir = os.path.dirname(file_path)
                # Use rawpy library to open DNG files
                with rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess()
                    pixmap = QPixmap.fromImage(
                        QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888))
                pixmap = pixmap.scaled(* self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
                self.image_labels[index].setPixmap(pixmap)
                filename, file_extension = os.path.splitext(os.path.basename(file_path))
                self.image_name_labels[index].setText(f"{self.img_legend[0]}  : \n {filename}  {file_extension}")
                self.image_name_labels[index].setStyleSheet("color: darkBlue;")
                input_file_path = Path(self.info_vis_dng['inputFolder']) / self.info_vis_dng[ key_1]['listCopiedImages'][index_img]
                input_file_path = self.safe_path(input_file_path)
                self.listImgRefPath[index] = input_file_path
                self.listVisRefPath[index] = input_file_path

            # Updated class flags with new values. New window position if moved
            self.currentUserDir = self.new_user_dir
            if all(elem is True for elem in self.flags):
                self.btn_load_all_images.setEnabled(True)
                self.btn_load_all_images.setStyleSheet("background-color: darkBlue; color: white;")
        except Exception as e:
            print("error in open_sync_and_fly_image_VIS_or_NIR : ", e)



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

            if all(LoadVisNirImagesDialog.flags):
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


    def on_help(self) -> None:
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

            if inputFolder != os.path.dirname(self.listImgRefPath[1]):
                message = f"{message} | first image of Sync \n"
            if inputFolder != os.path.dirname(self.listImgRefPath[2]):
                message = f"{message} | last image of Sync \n"
            if inputFolder != os.path.dirname(self.listImgRefPath[3]):
                message = f"{message} | first image of Fly  \n"
            if inputFolder != os.path.dirname(self.listImgRefPath[4]):
                message = f"{message} | last image of Fly \n"
        else:
            consistency_choice = True

        if not consistency_choice:
            # Uti.show_error_message` is a method to display error messages to the user.
            Uti.show_error_message(f"We detected an inconsistency in the choice of reference images: \n {message} \n Please note they must come from the same folder: \n {inputFolder} !")

        return consistency_choice


def choose_folder_mission(dic_takeoff, pref_screen_default_user_dir, AerialPhotoFolder, SynchroFolder):
    image_takeoff_available, path_image_takeoff = Uti.image_takeoff_available_test(dic_takeoff, pref_screen_default_user_dir)
    try:
        if image_takeoff_available:
            # construction du nom du dossier de la mission
            folderMissionPath = Path(dic_takeoff['File path mission'])
            coherent_response = Uti.folder_name_consistency_analysis(folderMissionPath)
            if coherent_response:
                Uti.show_info_message("IRDrone", f"Your images will be transferred to the  mission folder : \n {folderMissionPath}",
                                      f"They will be distributed between the folders {AerialPhotoFolder} and {SynchroFolder}")
            else:
                coherent_response = False
            return folderMissionPath, coherent_response
        else:
            Uti.show_warning_OK_Cancel_message("IRDrone", "Choose the mission folder.", "It is of the form : \n FLY_Year Month Day_hour minute_[Place]", QMessageBox.Icon.Information)
            try:
                folderMissionPath = Path(QFileDialog.getExistingDirectory('Select Mission Folder', pref_screen_default_user_dir))
                if folderMissionPath.exists() and folderMissionPath != pref_screen_default_user_dir:
                    coherent_response = Uti.folder_name_consistency_analysis(folderMissionPath)
                    if not coherent_response:
                        Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n{folderMissionPath} \nwhich is not a Mission IRDrone folder.",
                                                           " Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_<free text> ).\n or create a mission \n Use the <Create a New Mission> command.")
                else:
                    Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n {folderMissionPath} \n",
                                                       " Your choice of folder is not recognized in IRDrone\n Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_[Optional text] ).")
                    coherent_response = False

                return folderMissionPath, coherent_response
            except Exception as e:
                print("error 1   in choose_folder_mission :", e)
    except Exception as e:
        print("error 2   in choose_folder_mission :", e)


if __name__ == '__main__':
    pref_screen = Uti.Prefrence_Screen()
    default_app_dir = pref_screen.default_app_dir
    default_user_dir = pref_screen.default_user_dir
    # setting to manage multiple screens
    screen_ID = pref_screen.defaultScreenID  # DEFAULT_SCREEN_ID = 1  Set to 0 for screen 1, 1 for screen 2, and so on
    screen_adjust = pref_screen.screenAdjust  # SCREEN_ADJUST = [0, 40]   # 40 for taskbar and
    window_display_size = pref_screen.windowDisplaySize  # WINDOW_DISPLAY_SIZE = (800, 600)
    VERBOSE = True

    app = QApplication(sys.argv)  # initializes the Qt application loop (ESSENTIAL!)

    main_win_1 = LoadVisNirImagesDialog(900, 600, 'VIS',  os.path.join(os.path.abspath('/'), "Air-Mission", "FLY-20220125-1159-Blassac"))
    Uti.center_on_screen(main_win_1, screen_ID, screen_adjust, window_display_size)
    Uti.show(main_win_1)  # Uses the utils_interactiv module function to display the window
    main_win_2 = LoadVisNirImagesDialog(900, 550, 'NIR', os.path.join(os.path.abspath('/'), "Air-Mission", "FLY-20220125-1159-Blassac"))
    Uti.center_on_screen(main_win_2, screen_ID, [20, 40], (750, 550))
    Uti.show(main_win_2)  # Uses the utils_interactiv module function to display the window

    sys.exit(app.exec())
