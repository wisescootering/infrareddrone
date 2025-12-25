# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Main window of the interactive IRDrone GUI
#   29/10/2023   V002
# ---------------------------------------------------------------------------------

import warnings

# Remove only deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import sys
# print("Python  :", sys.executable)
# print("Path for modules :", sys.path)
import os
import os.path as osp
sys.path.append(osp.join(osp.dirname(__file__), ".."))
from pathlib import Path
import json
# ------------------PyQt6 Library -----------------------------------
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QLabel,
    QFrame,
    QProgressBar,
    QMessageBox,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QColor, QIcon
# -------------- IRDrone Library ------------------------------------
from IRD_Interactive_1 import Window_Load_TakeOff_Image, Window_create_file_structure
from IRD_Interactive_2 import LoadVisNirImagesDialog
from IRD_Interactive_3 import DialogSynchroAruco
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import Prefrence_Screen
from IRD_Interactive_color_style import Style



class Main_Window(QMainWindow):

    def __init__(self):
        """
        Initialize the main window of the interactive application.
        """
        super().__init__()
        self.pref_screen = Prefrence_Screen()
        self.mission_parameters_light: dict = {"key": "value"}
        self.mission_parameters: dict = None
        self.list_dic_exif_xmp: list[dict] = None
        self.list_summary: list[dict] = None
        self.pathImageTakeoff = None
        self.original_pathImageTakeoff = None
        self.folderMissionPath = None


        self.image_display_size = (100, 100)
        self.def_app_dir = None
        self.def_user_dir = None
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.btn_create_mission = None
        self.btn_load_images = None
        self.btn_pre_process_images = None
        self.btn_process_images = None
        self.btn_help = None
        self.command_layout = None
        self.image_label = QLabel(self)
        self.empty_pixmap = QPixmap(100, 100)
        self.progress_bar = QProgressBar(self)
        self.dialog_load_takeoff_image = None
        self.dialog_create_file_structure = None
        self.dialog_extract_exif = None
        self.folderMissionPath: Path = None
        self.dialog_synchro_clock = None
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
        self.btn_load_images.setAutoDefault(True)
        self.btn_load_images.setEnabled(True)   # (True) pour test  et (False) en prod !
        self.btn_load_images.setStyleSheet("background-color: purple; color: white;")  # color: darkGray;")
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
            # Create an empty pixmap of the desired size
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
            self.mission_parameters_light = self.dialog_load_takeoff_image.mission_parameters_light
            self.dialog_load_takeoff_image.btn_NextStep.clicked.connect(self.open_window_create_file_structure)  # Connect dialog_create_file_structure signal to Main_Window method
        except Exception as e:
            print("Error in Main_Window open_window_define_mission:", e)


    def open_window_create_file_structure(self):
        """
        Open dialog_create_mission_file_structure when called from dialog_load_takeoff_image.
        """
        self.dialog_create_file_structure = Window_create_file_structure(self, self.mission_parameters_light)  # Instantiate Window_12
        try:
            self.dialog_create_file_structure.data_signal_from_dialog_create_file_structure_to_main_window.connect(
                self.handle_data_from_dialog_create_file_structure
            )
            self.dialog_create_file_structure.show()
        except Exception as e:
            print("Error in Main_Window open_window_create_file_structure:", e)


    def handle_data_from_dialog_create_file_structure(self, validate: bool, mission_parameters: dict):
        """
        Handle data from Window_create_file_structure and close parent windows.
        Args:
            validate (bool): True if the user has validated the entries, False otherwise.
            mission_parameters (dict): A dictionary containing image_path, location, and pilot data.
        """
        if validate:
            self.mission_parameters = mission_parameters
            self.folderMissionPath = self.mission_parameters['File path mission']
            self.dialog_create_file_structure.data_signal_from_dialog_create_file_structure_to_main_window.disconnect()  # Disconnect the signal
            self.dialog_create_file_structure.close()  # Close dialog_create_file_structure
            self.btn_load_images.setAutoDefault(True)
            self.btn_load_images.setEnabled(True)
            self.btn_load_images.setStyleSheet("background-color: purple; color: White;")
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
        try:
            if self.folderMissionPath and self.dialog_create_file_structure:
                folderMissionPath, coherent_answer = Uti.choose_folder_mission(self.mission_parameters,
                                                                               self.pref_screen.default_user_dir,
                                                                               self.dialog_create_file_structure.AerialPhotoFolder,
                                                                               self.dialog_create_file_structure.SynchroFolder
                                                                               )
                if not coherent_answer: return
            else:
                if self.folderMissionPath:
                    default_user_dir = Uti.safe_path(self.folderMissionPath)
                else:
                    default_user_dir = r"C:\\Air-Mission"
                Uti.show_info_message("IRDrone", f"Choose the mission folder.", "")
                folderMissionPath, coherent_answer = Uti.choose_mission_folder_phase_2(self, verbose=True, default_user_dir=default_user_dir)
                if not coherent_answer: return
                if folderMissionPath:
                    self.folderMissionPath = folderMissionPath
                    self._load_mission_json()
                    if not self.mission_parameters:
                        raise RuntimeError("Mission parameters not loaded")
            self.pathImageTakeoff = Uti.safe_path(Path(self.mission_parameters["path mission image take-off"]).parent)
            self.original_pathImageTakeoff = Uti.safe_path(Path(self.mission_parameters["original File path take-off"]))

        except Exception as e:
            print(Style.RED + f'error in open_window_load_set_images (Choice of mission file) :  {e}')
        # ---------------- Loads the 5 reference “VIS” images --------------------------------------------
        dialog_VIS = LoadVisNirImagesDialog(width,
                                            height,
                                            spectral_band="VIS",
                                            suffix="dng",
                                            folderMission=folderMissionPath,
                                            path_image_takeoff=self.pathImageTakeoff,
                                            original_path_image_takeoff=self.original_pathImageTakeoff)

        dialog_VIS.exec()
        dialog_VIS.reset_flags()
        # ---------------- Loads the 5 reference “NIR” images --------------------------------------------
        dialog_NIR = LoadVisNirImagesDialog(width,
                                            height,
                                            spectral_band="NIR",
                                            suffix="dng",
                                            folderMission=folderMissionPath,
                                            path_image_takeoff=self.pathImageTakeoff)
        dialog_NIR.exec()
        dialog_NIR.reset_flags()



    def _load_mission_json(self):
        try:
            json_path = (
                    self.folderMissionPath
                    / "FlightAnalytics"
                    / "mission_parameters.json"
            )
            with json_path.open("r", encoding="utf-8") as f:
                self.mission_parameters = json.load(f)
        except Exception as e:
            print(Style.RED + f'error in _load_mission_json {e}' + Style.RESET)


    # ===================================================================================
    #                   Button #3 click handlers
    #     Step 3 pre process images  (clock synchronization, adjustment of shooting frequencies
    #     creating the absolut time line, calculation of geographic coordinates,
    #     camera attitudes( yaw, pitch roll).
    # ===================================================================================

    def on_pre_process_images(self):
        """
        Phase 3 – VIS / NIR synchronization
        """
        if not self.ensure_mission_parameters():
            return

        try:
            self.dialog_synchro_aruco = DialogSynchroAruco(self.mission_parameters)
            self.dialog_synchro_aruco.data_signal_to_main.connect(
                self.handle_data_from_dialog_synchro_aruco
            )
            self.dialog_synchro_aruco.show()

        except Exception as e:
            print("Error in  class Main_Window(QMainWindow)   in on_pre_process_images     opening Dialog_Synchro_Aruco:", e)

    def handle_data_from_dialog_synchro_aruco(self, validate: bool):
        if validate:
            print("Phase 3 completed successfully.")
        else:
            print("Phase 3 cancelled by user.")



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


    # ====================================================================================
    #                  Méthodes de la class main_windows
    # ===================================================================================

    def ensure_mission_parameters(self) -> bool:
        """
        Ensure that mission_parameters are available.
        If not, ask the user to select an existing mission folder
        and load mission_parameters from disk.

        Returns
        -------
        bool
            True if mission_parameters are available, False otherwise.
        """
        try:
            if self.mission_parameters is not None:
                return True

            # Ask user to select a mission folder
            folderMissionPath, ok = Uti.choose_mission_folder_phase_2(self, default_user_dir="C:\\Air-Mission")

            if not ok:
                return False
            folderMissionPath = Path(folderMissionPath)
        except Exception as e:
            print(f'DEBUG  in ensure_mission_parameters  {e}  ')

        try:
            mission_json = Uti.safe_path(folderMissionPath / "FlightAnalytics" / "mission_parameters.json")
            if not mission_json.exists():
                raise FileNotFoundError("mission_parameters.json not found")

            with open(mission_json, "r", encoding="utf-8") as f:
                self.mission_parameters = json.load(f)

            # Inject mission path explicitly
            self.mission_parameters["folderMissionPath"] = folderMissionPath

            return True

        except Exception as e:
            QMessageBox.critical(
                self,
                "Mission loading error",
                f"Unable to load mission parameters:\n{e}"
            )
            return False


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

