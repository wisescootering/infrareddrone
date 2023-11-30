# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Selection of reference images for the stages of the mission.
#   29/10/2023   V002
# ---------------------------------------------------------------------------------


import os
import sys
import shutil
import rawpy
from functools import partial
from typing import Any, Dict, Optional, Tuple, List, Union
from pathlib import Path
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

        self.num_images = 5
        self.pref_screen = Uti.Prefrence_Screen()
        self.screen_width = width
        self.screen_height = height
        self.target_screen_index = self.pref_screen.defaultScreenID
        self.screen_adjust = self.pref_screen.screenAdjust
        self.window_display_size = self.pref_screen.windowDisplaySize

        self.type_img = type_img
        if self.type_img == "VIS" or self.type_img == "DNG":
            self.ext = "DNG"
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

            if self.image_takeoff_available:
                self.open_takeoff_image(self.path_image_takeoff)

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
            # Note:  Here we use the listImgRefPath table which contains the 5 reference images.
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
            if  not consistency_choice:
                return

            # ---------------Copy images from the camera's SD card to the computer's hard drive.----------------------
            Uti.show_info_message("IRDrone", f"Copying {(max((idMaxFly - idMinFly),0) + max((idMaxSync - idMinSync),0) )} "
                                f"images from the camera SD card to the computer disk may take a little time...",
                                "Be patient ;-) ",
                                QMessageBox.Icon.Information)

            if self.currentImgTyp == "NIR":

                # ----------  transfer of NIR images of the Sync and Fly phase (jpg) ----------------
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "jpg")
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync, idMaxSync, 0, 10)
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly, idMaxFly, 10, 30)
                # ----------  transfer of NIR images of the Sync and Fly phase (raw) ----------------
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "raw")
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync - 1, idMaxSync - 1, 30, 60)
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly - 1, idMaxFly - 1, 60, 100)

            elif self.currentImgTyp == "VIS":
                listInputImages = self.create_list_image_in_input_folder(inputFolder, "dng")
                # ----------   transfer of VIS images of the Sync  phase (dng) ----------------
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputSyncFolder, idMinSync, idMaxSync, 0, 30)
                # ----------   transfer of VIS images of the Fly  phase (dng)----------------
                self.load_inputFolder_2_outputFolder(inputFolder, listInputImages, outputFlyFolder, idMinFly, idMaxFly, 30, 98)
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


    def load_inputFolder_2_outputFolder(self, inputFolder: str, listInputImages: List[str], outputFolder: str, id_min: int, id_max: int, pgsbar0: int, pgrbar1: int) ->None:
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

    main_win_1 = LoadVisNirImagesDialog( 900, 600, 'VIS',  os.path.join(os.path.abspath('/'), "Air-Mission","FLY-20220125-1159-Blassac"))
    Uti.center_on_screen(main_win_1, screen_ID, screen_adjust, window_display_size)
    Uti.show(main_win_1)  # Uses the utils_interactiv module function to display the window
    main_win_2 = LoadVisNirImagesDialog(900, 550, 'NIR', os.path.join(os.path.abspath('/'), "Air-Mission", "FLY-20220125-1159-Blassac"))
    Uti.center_on_screen(main_win_2, screen_ID, [20, 40], (750, 550))
    Uti.show(main_win_2)  # Uses the utils_interactiv module function to display the window

    sys.exit(app.exec())