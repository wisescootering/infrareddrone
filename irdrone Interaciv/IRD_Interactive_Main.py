# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Main window of the interactive IRDrone GUI
#   29/10/2023   V002
# ---------------------------------------------------------------------------------


import os
import os.path as osp
import sys
from pathlib import Path
# ------------------PyQt6 Library -----------------------------------
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,  QWidget, QPushButton, QLabel, QFrame, QProgressBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor, QIcon
# -------------- IRDrone Library ------------------------------------
from IRD_Interactive_1 import Window_Load_TakeOff_Image, Window_create_file_structure
from IRD_Interactive_2 import LoadVisNirImagesDialog, choose_folder_mission
from IRD_Interactive_3 import Dialog_extract_exif, Dialog_synchro_clock
import IRD_interactive_utils as Uti
from IRD_interactive_utils import Prefrence_Screen
# -------------------- IRD Library -----------------------------------------------
sys.path.append(osp.join(osp.dirname(__file__), '../utils'))



class Main_Window(QMainWindow):

    def __init__(self):
        """
        Initialize the main window of the interactive application.
        """
        super().__init__()
        self.pref_screen = Prefrence_Screen()
        self.dic_takeoff_light: dict = {"key": "value"}
        self.dic_takeoff: dict = None
        self.list_dic_exif_xmp: list[dict] = None
        self.list_summary: list[dict] = None
        self.pathImageTakeoff = None
        self.init_GUI()


    def init_GUI(self):
        self.image_display_size: tuple[int, int] = (500, 500)   # Size of the log image displayed in the main window.
        self.setStyleSheet("background-color: white; color: black;")
        self.def_app_dir = self.pref_screen.default_app_dir
        self.def_user_dir = self.pref_screen.default_user_dir

        # Set layout and widgets.  Create the central widget
        #   Setting the top bar and window dimensions.
        self.setWindowTitle("IRdrone interactive v01")
        icon_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "IRDrone.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            QApplication.setWindowIcon(icon)  # Set the applicable icon in the class.

        width = self.pref_screen.windowDisplaySize[0]   # Main window width
        height = self.pref_screen.windowDisplaySize[1]  # Main window height
        self.setGeometry(0, 0, width, height)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        #  Creating the command bar:
        #  btn create_mission
        self.btn_create_mission = QPushButton("Step 1 : Define the mission", self)
        self.btn_create_mission.setStyleSheet("background-color: darkBlue; color: white;")
        self.btn_create_mission.clicked.connect(self.open_window_define_mission)
        #  btn load_images
        self.btn_load_images = QPushButton("Step 2 : Choice of reference image set.", self)
        self.btn_load_images.setAutoDefault(False)
        self.btn_load_images.setEnabled(False)   # (True) pour test  et (False) en prod !
        self.btn_load_images.setStyleSheet("background-color: Gray; color: darkGray;")
        self.btn_load_images.clicked.connect(self.open_window_load_set_images)
        #  btn pre_process_images
        self.btn_pre_process_images = QPushButton("Step 3 : Image pre-processing", self)
        self.btn_pre_process_images.setStyleSheet("background-color: darkGray; color: white;")
        self.btn_pre_process_images.clicked.connect(self.on_pre_process_images)
        #  btn process_images
        self.btn_process_images = QPushButton("Step 4 : Image processing", self)
        self.btn_process_images.setStyleSheet("background-color: darkRed; color: white;")
        self.btn_process_images.clicked.connect(self.on_process_images)
        #  btn help
        self.btn_help = QPushButton("Help", self)
        self.btn_help.setStyleSheet("background-color: darkGreen; color: white;")
        self.btn_help.setFixedWidth(60)
        self.btn_help.clicked.connect(self.on_help)

        # Layout for command bar
        self.command_layout = QHBoxLayout()
        self.command_layout.addWidget(self.btn_create_mission)
        self.command_layout.addWidget(self.btn_load_images)
        self.command_layout.addWidget(self.btn_pre_process_images)
        self.command_layout.addWidget(self.btn_process_images)
        self.command_layout.addWidget(self.btn_help)

        self.main_layout.addLayout(self.command_layout)

        # Image display area
        self.image_label = QLabel(self)
        self.image_label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)  # Add a frame
        self.image_label.setFrameStyle(QFrame.Shape.Box)
        self.image_label.setMinimumSize(*self.image_display_size)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # IRDrone default image
        image_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "image_IRdrone_appli.jpg")
        if os.path.exists(image_path):
            # Load image and Adjust the size if necessary
            default_pixmap = QPixmap(image_path)
            default_pixmap = default_pixmap.scaled(*self.image_display_size, Qt.AspectRatioMode.KeepAspectRatio)
            self.image_label.setPixmap(default_pixmap)  # Display the image in  QLabel
        else:
            # Create an empty pixmap of the desired size and adjust the size if necessary
            self.empty_pixmap = QPixmap(width, height)
            self.image_label.setText("Image area")
            self.empty_pixmap.fill(QColor(Qt.GlobalColor.gray))  # transparent,gray, darkYellow etc)
            self.image_label.setPixmap(self.empty_pixmap)  # Set the empty pixmap

        self.main_layout.addWidget(self.image_label)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setStyleSheet("QProgressBar { color: white; }")
        self.main_layout.addWidget(self.progress_bar)
        self.progress_bar.setValue(0)

    # ===================================================================================
    #                   Button #1 click handlers
    #     Step 1 Define the mission
    # ===================================================================================

    def open_window_define_mission(self):
        """
        Open dialog_load_takeoff_image when the corresponding button is clicked.
        """
        try:
            self.dialog_load_takeoff_image = Window_Load_TakeOff_Image(self)
            self.dialog_load_takeoff_image.show()
            self.dic_takeoff_light = self.dialog_load_takeoff_image.dic_takeoff_light
            self.dialog_load_takeoff_image.btn_NextStep.clicked.connect(self.open_window_create_file_structure)  # Connect dialog_create_file_structure signal to Main_Window method
        except Exception as e:
            print("Error in Main_Window open_window_define_mission:", e)


    def open_window_create_file_structure(self):
        """
        Open dialog_create_mission_file_structure when called from dialog_load_takeoff_image.
        """
        self.dialog_create_file_structure = Window_create_file_structure(self, self.dic_takeoff_light)  # Instantiate Window_12
        try:
            self.dialog_create_file_structure.data_signal_from_dialog_create_file_structure_to_main_window.connect(self.handle_data_from_dialog_create_file_structure)
            self.dialog_create_file_structure.show()
        except Exception as e:
            print("Error in Main_Window open_window_create_file_structure:", e)


    def handle_data_from_dialog_create_file_structure(self, validate: bool, dic_takeoff: dict):
        """
        Handle data from Window_create_file_structure and close parent windows.
        Args:
            validate (bool): True if the user has validated the entries, False otherwise.
            dic_takeoff (dict): A dictionary containing image_path, location, and pilot data.
        """
        if validate:
            self.dic_takeoff = dic_takeoff
            self.dialog_create_file_structure.data_signal_from_dialog_create_file_structure_to_main_window.disconnect()  # Disconnect the signal
            self.dialog_create_file_structure.close()  # Close dialog_create_file_structure
            self.btn_load_images.setAutoDefault(True)
            self.btn_load_images.setEnabled(True)
            self.btn_load_images.setStyleSheet("background-color: Gray; color: White;")
        else:
            print("The user has not validated his entries.")

        self.dialog_load_takeoff_image.close()


    # ===================================================================================
    #                   Button #2 click handlers
    #     Step 2 load set of VIS and NIR images of he mission.
    # ===================================================================================


    def open_window_load_set_images(self):
        """
        load set of VIS and NIR images of he mission.
        """
        # ------------------ setting window size to load image sets -------------------------------------
        active_screen_id = QApplication.screens().index(QApplication.activeWindow().screen()) if QApplication.activeWindow() else 0
        screen_geometry = QApplication.screens()[active_screen_id].availableGeometry()
        width = screen_geometry.width() - 20  # width of the window
        height = 500  # height of the window

        # ----------------------- Choice of mission file -------------------------------------------------
        folderMissionPath, coherent_response = choose_folder_mission(self.dic_takeoff, self.pref_screen.default_user_dir, self.dialog_create_file_structure.AerialPhotoFolder, self.dialog_create_file_structure.SynchroFolder)
        if not coherent_response: return()
        # ---------------- Loads the 5 reference “VIS” images --------------------------------------------
        if self.dic_takeoff is not None: self.pathImageTakeoff = self.dic_takeoff["File path take-off"]
        dialog_VIS = LoadVisNirImagesDialog(width, height, "VIS", folderMission=folderMissionPath, path_image_takeoff=self.pathImageTakeoff)
        dialog_VIS.exec()
        dialog_VIS.reset_flags()
        # ---------------- Loads the 5 reference “NIR” images --------------------------------------------
        dialog_NIR = LoadVisNirImagesDialog(width, height, "NIR", folderMission=folderMissionPath)
        dialog_NIR.exec()
        dialog_NIR.reset_flags()


    # ===================================================================================
    #                   Button #3 click handlers
    #     Step 3 pre process images  (clock synchronization, adjustment of shooting frequencies
    #     creating the timeline, calculation of geographic coordinates,
    #     camera attitudes( yaw, pitch roll).
    # ===================================================================================


    def on_pre_process_images(self):
        """
        preprocess_step 1  Extract and save Exif tags)
        Open the dialog_extract_exif when the corresponding button (btn_pre_process_images) is clicked.
        """
        try:
            self.dialog_extract_exif = Dialog_extract_exif(self.dic_takeoff)     # Instantiate Window dialog_extract_exif
            self.dialog_extract_exif.data_signal_from_dialog_extract_exif_to_main_window.connect(self.handle_data_from_dialog_extract_exif)
            self.dialog_extract_exif.show()
            self.dialog_extract_exif.btn_preprocess_step1.clicked.connect(self.open_dialog_synchro_clock)  # Connect dialog_synchro_clock signal to Main_Window method
        except Exception as e:
            print("Error in Main_Window open_dialog_extract_exif:", e)

    def handle_data_from_dialog_extract_exif(self, validate: bool):
        """
        Handle data received from dialog_extract_exif .
        Args: validate (bool): True if the user has validated the entries, False otherwise.
        """
        if validate:
            self.list_dic_exif_xmp: list[dict] = self.dialog_extract_exif.list_dic_exif_xmp
            self.folderMissionPath: Path = self.dialog_extract_exif.folderMissionPath
            print(f"TEST  for Fly {self.folderMissionPath} Extraction built {len(self.list_dic_exif_xmp)} dictionary exif/xmp")
            self.dialog_extract_exif.data_signal_from_dialog_extract_exif_to_main_window.disconnect()  # Disconnect the signal
        else:
            print("The user has not validated his entries.")

    def open_dialog_synchro_clock(self):
        """
        preprocess_step 2  Synchro time-line NIR/VIS
        Open the dialog_synchro_clock when called from dialog_extract_exif.
        """
        try:
            self.dialog_synchro_clock = Dialog_synchro_clock(self.list_dic_exif_xmp, self.folderMissionPath)  # Instantiate dialog_synchro_clock
            self.dialog_synchro_clock.data_signal_from_dialog_synchro_clock_to_main_window.connect(self.handle_data_from_dialog_synchro_clock)
            self.dialog_synchro_clock.show()
        except Exception as e:
            print("Error in Main_Window open_dialog_synchro_clock:", e)


    def handle_data_from_dialog_synchro_clock(self, validate: bool):
        """
        Handle data received from dialog_synchro_clock and close parent windows.
        Args: validate (bool): True if the user has validated the entries, False otherwise.
        """
        if validate:
            self.list_dic_exif_xmp = self.dialog_extract_exif.list_dic_exif_xmp
            # print(f"TEST  Main sortie dialog_synchro_clock \n {self.list_dic_exif_xmp[-1]}")
            print(f"TEST  The clock offset is : {self.dialog_synchro_clock.delta_clock} s. \n END PREPROCESS")
            self.dialog_synchro_clock.data_signal_from_dialog_synchro_clock_to_main_window.disconnect()  # Disconnect the signal
            self.dialog_synchro_clock.close()  # Close dialog_synchro_clock
        else:
            print("The user has not validated his entries.")
        self.dialog_extract_exif.close()
        pass


    # ===================================================================================
    #                   Button #4 click handlers
    #     Step 4 process images
    # ===================================================================================


    def on_process_images(self):
        Uti.show_info_message("IRDrone", "Currently being implemented ...", "")
        pass


    # ===================================================================================
    #                   Button #5 click handlers
    # ===================================================================================


    def on_help(self):
        Uti.show_info_message("IRDrone", "Currently being implemented ...", "")
        pass


def main():
    """Main function to run the interactive application.."""
    app = QApplication(sys.argv)
    main_window = Main_Window()
    # Check if main_window is modal or not
    if main_window.isModal():
        # print("TEST  main_window is a modal window.")
        pass
    else:
        # print("TEST   main_window is not a modal window.")
        pass
    screen = Prefrence_Screen()
    Uti.center_on_screen(main_window, screen_Id=screen.defaultScreenID, screen_adjust=screen.screenAdjust, window_display_size=screen.windowDisplaySize)
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

