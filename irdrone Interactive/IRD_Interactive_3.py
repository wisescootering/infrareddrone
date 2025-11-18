# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Writing Exif-like dictionaries in files (one for each image)
#   Basic Exif data augmented with xmp data of the drone's attitude, shot number, timeline.
#   29/10/2023   V002
# ---------------------------------------------------------------------------------

import sys
import os
import os.path as osp
import json
from datetime import date, time, datetime
from pathlib import Path
import numpy as np
# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QDialog, QFileDialog, QLabel, \
    QRadioButton, QLineEdit, QPushButton, QMessageBox, QProgressBar, QFrame
from PyQt6.QtGui import QDoubleValidator, QPixmap, QColor, QIcon
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression
# -------------- IRDrone Library ------------------------------------
import IRD_interactive_utils as Uti
import IRD_interactive_geo as Geo
from IRD_interactive_utils import Prefrence_Screen
import IRD_Interactive_Exif_Xmp as ExifXmp
# -------------------- IRD Library -----------------------------------------------
sys.path.append(osp.join(osp.dirname(__file__), '..'))
import utils.utils_IRdrone_Class as ClassPt
import synchronization.synchro_by_aruco as synchro_by_aruco
import config as global_config



class Dialog_extract_exif(QDialog):
    # Creates a class signal to transmit the data to the parent which will here be an instance of the main window class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_dialog_extract_exif_to_main_window = pyqtSignal(bool)

    def __init__(self, dic_takeoff: dict):
        super().__init__()
        self.pref_screen = Uti.Prefrence_Screen()  # Initializing screen preferences
        self.init_GUI()  # Initializing the GUI
        self.setLayout(self.main_layout)
        self.dic_takeoff = dic_takeoff
        self.list_dic_exif_xmp = []
        self.folderMissionPath = None



    def init_GUI(self):
        self.image_display_size: tuple[int, int] = (200, 200)   # Size of the log image displayed in the main window.
        self.setStyleSheet(f"background-color: {self.pref_screen.background_color}; color: {self.pref_screen.txt_color};")
        #   Setting the top bar and window dimensions.
        self.setWindowTitle("Extraction of Exif data from the flight.")
        try:
            icon_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "IRDrone.ico")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                QApplication.setWindowIcon(icon)            # Set the applicable icon in the class.
        except Exception as e:
            print("error  in Class Dialog_extract_exif    initGUI  Setting the top command bar and window dimensions", e)
        width = int(self.pref_screen.windowDisplaySize[0]/1.5)   # Main window width
        height = int(self.pref_screen.windowDisplaySize[1]/2)  # Main window height

        #  Setting the window dimensions.
        # Create the central widget
        self.setGeometry(0, 0, width, height)
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        # Create the tre zones (and sub layouts for zone 3) and add them to the main layout
        zone1_layout = QHBoxLayout()
        zone2_layout = QVBoxLayout()
        zone3_layout = QVBoxLayout()
        bottom_command = QHBoxLayout()
        zone3_layout.addLayout(bottom_command)
        self.main_layout.addLayout(zone1_layout)
        self.main_layout.addLayout(zone2_layout)
        self.main_layout.addLayout(zone3_layout)

        # Creating the command bar in zone 3

        self.btn_preprocess_step1 = QPushButton("Extract and Save Exif tags")   # Define btn (type and label )
        self.btn_preprocess_step1.setFixedWidth(250)  # Dim btn
        self.btn_preprocess_step1.setStyleSheet("background-color: darkBlue; color: white;")  # Color btn
        self.btn_preprocess_step1.clicked.connect(self.extract_from_folder_mission)  # Connect btn
        bottom_command.addWidget(self.btn_preprocess_step1)  # add btn in  command bar

        btn_Cancel = QPushButton("Cancel")
        btn_Cancel.setFixedWidth(100)
        btn_Cancel.setStyleSheet("background-color: darkGray; color: black;")
        btn_Cancel.clicked.connect(self.cancel_clicked)
        bottom_command.addWidget(btn_Cancel)

        btn_Help = QPushButton("Help")
        btn_Help.setStyleSheet("background-color: darkGreen; color: white;")
        btn_Help.setFixedWidth(60)
        btn_Help.clicked.connect(self.help_clicked)
        bottom_command.addWidget(btn_Help)


        # Progress bar in zone 3
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("QProgressBar { color: white; }")
        zone3_layout.addWidget(self.progress_bar)
        self.progress_bar.setValue(0)

        # Image display in zone 2
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
            empty_pixmap = QPixmap(width, height)
            empty_pixmap.fill(QColor(Qt.GlobalColor.gray))  # transparent,gray, darkYellow etc)
            self.image_label.setText("Image area")
            self.image_label.setPixmap(empty_pixmap)  # Set the empty pixmap

        zone2_layout.addWidget(self.image_label)

        # Screen management.
        Uti.center_on_screen(self, screen_Id=1)

    '''
    def effective_recording_step_VIS(self, list_time_VIS: list[int, datetime]) -> datetime:
        """
        Calculation of the effective recording step of VIS images (it is a little greater than 2s announced by DJI)
        This calculation takes into account all images (from the first photographed at takeoff to the last photo of the mission)
        The absolute origin of the VIS timeline is in the config file
        :return: dt_time_VIS
        """
        #  Marking the last VIS shot
        data_array = np.array(list_time_VIS)
        index_of_latest = np.argmax(data_array[:, 1])
        num_shoot_end = int(data_array[index_of_latest, 0])
        time_shoot_end = datetime.strptime(data_array[index_of_latest, 1], "%Y:%m:%d %H:%M:%S")
        #  Real time interval between two VIS shots
        dt_time_VIS = (time_shoot_end - self.origin_date_VIS()).total_seconds() / (num_shoot_end - 1)
        print(f"TEST  dt_time_VIS = {dt_time_VIS} s")
        return dt_time_VIS


    def origin_date_VIS(self) -> datetime:
        config_file = Path(self.folderMissionPath, 'FlightAnalytics', 'config.json')
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                origin_date_py = datetime.strptime(dic_config['Date Exif'], "%Y:%m:%d %H:%M:%S")
        else:
            origin_date_py = None
        return origin_date_py
    '''

    def cancel_clicked(self):
        """Method called when the 'Cancel' button is clicked."""
        try:
            self.close()
        except Exception as e:
            print("Error in Class Dialog_extract_exif cancel_clicked", e)


    def help_clicked(self):
        """Method called when the 'Help' button is clicked."""
        # Show a help message
        Uti.show_info_message("IRDrone", "Currently being implemented ...", "")
        pass


    def extract_from_folder_mission(self):
        try:
            image_takeoff_available, path_image_mission = Uti.image_takeoff_available_test(self.dic_takeoff, self.pref_screen.default_user_dir)
            print(f'DEBUG 01 extract_from_folder_mission image_takeoff_available, path_image_mission {image_takeoff_available, path_image_mission}')

            if image_takeoff_available:
                print(f'DEBUG 01 extract_from_folder_mission  self.dic_takeoff {self.dic_takeoff}')
                # search for the mission file
                self.folderMissionPath = Path(self.dic_takeoff['File path mission'])
                self.coherent_answer = Uti.folder_name_consistency_analysis(self.folderMissionPath)
                self.extract_exif_from_images_folder(["AerialPhotography", "Synchro", "FlightAnalytics"])
                self.placeholder_method_dialog_extract_exif_2_32()
            else:
                try:
                    self.folderMissionPath = Path(QFileDialog.getExistingDirectory(self, 'Select Mission Folder', self.pref_screen.default_user_dir))
                    if self.folderMissionPath.exists() and self.folderMissionPath != self.pref_screen.default_user_dir:
                        self.coherent_answer = Uti.folder_name_consistency_analysis(self.folderMissionPath)
                        if self.coherent_answer:
                            print(f"TEST  the mission exists and it is in the location : {self.folderMissionPath}")
                            self.extract_exif_from_images_folder(["AerialPhotography", "Synchro", "FlightAnalytics"])
                            self.placeholder_method_dialog_extract_exif_2_32()
                        else:
                            Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n{self.folderMissionPath} \nwhich is not a Mission IRDrone folder.",
                                               " Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_<free text> ).\n or create a mission \n Use the <Create a New Mission> command.")
                    else:
                        Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n {self.folderMissionPath} \n",
                                                           " Your choice of folder is not recognized in IRDrone\n Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_[Optional text] ).")
                        self.coherent_answer = False
                except Exception as e:
                    print("error 1   in Class Dialog_extract_exif     extract_from_folder_mission :", e)
            if not self.coherent_answer:
                self.extract_from_folder_mission()
        except Exception as e:
            print("error 2   in Class Dialog_extract_exif   extract_from_folder_mission :", e)


    def extract_exif_from_images_folder(self, list_folder: list[str]) -> object:
        try:
            # récupération de l'altitude du  point de takeoff par rapport au niveau de la mer (above sea level)
            self.gps_info_takeoff = self.takeoff_info_GPS()
            self.progress_bar.setValue(5)
            for index, folder in enumerate(list_folder):
                if not self.coherent_answer:
                    self.cancel_clicked()
                self.progress_bar.setValue(100/len(list_folder))
                print(f'DEBUG 1001  dossier  {folder}')
                # Writing exif /xmp (enriched) data for the image folder
                folder_path = Path(self.folderMissionPath, folder)
                # 1) Create a list of all .dng, .jpg and .RAW files present in the folder
                list_path_image = [file for file in folder_path.glob('*') if file.suffix.lower() in ['.dng', '.jpg', '.raw']]
                print(f'DEBUG 1000  list_path_image {list_path_image}')
                # 2) Construction of a list of dictionaries of standard Exif / xmp data.
                self.list_dic_exif_xmp = self.get_EXIF_XMP_from_images_folder(list_path_image, verbose=True)
                print(f'DEBUG 1001  self.get_EXIF_XMP_from_images_folder  fin')
                # 3) # Enrichment of classic Exif data. (shot number, alt from sea level, relative time line ...)
                # 3.1)  altitudes
                self.dic_gps_info_takeoff = self.takeoff_info_GPS()
                self.true_alti_for_exif("dng")
                # 4) Writing Exif dictionaries to files (one for each image)
                self.writing_exif_data_to_exif_files(list_path_image, self.list_dic_exif_xmp)
            self.progress_bar.setValue(100)
        except Exception as e:
            print("error   in Class Dialog_extract_exif     extract_exif_from_images_folder  ", e)


    def takeoff_info_GPS(self):
        try:
            json_path = Path(self.folderMissionPath) / "FlightAnalytics" / "config.json"
            # Lecture du fichier config.json contenant les information sur le point de takeoff
            print(f'DEBUG takeoff_info_GPS  json_path {json_path}')
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except UnicodeDecodeError:
                print("⚠️ UTF-8 invalide, tentative avec Latin-1…")
                with open(json_path, "r", encoding="latin-1") as f:
                    data = json.load(f)
            except FileNotFoundError:
                print(Uti.Style.RED + f"❌ Fichier introuvable : {json_path}" + Uti.Style.RESET)
                return None
            except json.JSONDecodeError:
                print(Uti.Style.RED + f"❌ Erreur : fichier JSON invalide : {json_path}" + Uti.Style.RESET)
                return None

            # Récupération des données GPS
            gps_info_takeoff = {
                "GPS N-S": data.get("GPS N-S"),
                "GPS lat": data.get("GPS lat"),
                "GPS E-W": data.get("GPS E-W"),
                "GPS lon": data.get("GPS lon"),
                "GPS alti": data.get("GPS alti"),
            }

            return gps_info_takeoff

        except Exception as e:
            print("error   in Class Dialog_extract_exif     takeoff_info_GPS  ", e)

    def true_alti_for_exif(self, img_type):
        print("DEBUG  alti_exif")

        try:
            # 1) On récupère les indices des images correspondantes
            indices = [
                i for i, d in enumerate(self.list_dic_exif_xmp)
                if d.get("File Type", "").lower() == img_type
            ]

            # 2) On construit list_coordinates en suivant EXACTEMENT le même ordre
            list_coordinates = []
            for i in indices:
                dic = self.list_dic_exif_xmp[i]
                lat = Uti.gps_coordinate_to_float(dic["GPS Latitude"])
                lon = Uti.gps_coordinate_to_float(dic["GPS Longitude"])
                z_relatif_takeoff = float(dic["Relative Altitude"].strip())
                list_coordinates.append((lat, lon))

            # 3) Un seul appel à l'API IGN
            list_dic_coordinates = Geo.extract_alti_IGN(list_coordinates, verbose=True, bypass=False)
            print(f"DEBUG alti_exif list_dic_coordinates {list_dic_coordinates}")

            # 4) On injecte les données IGN dans les bons dic_exif
            for idx_exif, ign_coord in zip(indices, list_dic_coordinates):
                alti_ground = ign_coord['z']
                alti_drone_above_takeoff = float(self.list_dic_exif_xmp[idx_exif]["Relative Altitude"].strip())
                alti_drone_above_sea_level = alti_drone_above_takeoff + self.dic_gps_info_takeoff['GPS alti']
                alti_drone_above_ground =  alti_drone_above_sea_level - alti_ground
                self.list_dic_exif_xmp[idx_exif]["ground altitude"] = alti_ground
                self.list_dic_exif_xmp[idx_exif]["altitude above takeoff"] = alti_drone_above_takeoff
                self.list_dic_exif_xmp[idx_exif]["altitude above ground"] = alti_drone_above_ground
                self.list_dic_exif_xmp[idx_exif]["altitude above sea level"] = alti_drone_above_sea_level

            print("DEBUG alti_exif ign_coord added successfully")

        except Exception as e:
            print("error in Class Dialog_extract_exif true_alti_for_exif:", e)

    def get_EXIF_XMP_from_images_folder(self, list_pth: list[Path], verbose: bool = False) -> list[dict]:
        """
        Writing Exif and Xmp data from a list of images.
        Each image is processed individually by the get_EXIF_XMP procedure which
        extracts the data
        The exif/xmp data file has the same name as its image and has the extension .exif.
        It is readable in text format.

        The basic exif data is enriched (shot number, date of the shot, time line)

        The get_EXIF_XMP procedure uses third-party software: ExifTool.exe.
        However, it is very effective because ExifTool is capable of reading both classic Exif data and also XMP data.

        :param list_pth:
        :param verbose:
        :return: list_dic
        """
        try:
            list_dic = []
            list_time_VIS = []
            progressBarValue = 3
            for index, pth in enumerate(list_pth):
                progressBarValue = round(100 * index / (len(list_pth) - 1), 1)
                self.progress_bar.setValue(progressBarValue)
                #  Extracting original Exif data
                # print(f'DEBUG IRD3_0002 index pth  {index, pth}')
                dic = ExifXmp.get_EXIF_XMP(pth, index, verbose=verbose)
                # print('DEBUG IRD3_0003 ', dic)
                list_dic.append(dic)
            return list_dic
        except Exception as e:
            print("error in Class Dialog_extract_exif    get_EXIF_XMP_from_images_folder  ", e)

    @staticmethod
    def writing_exif_data_to_exif_files(list_pth: list[Path], list_dic: list[dict]):
        try:
            # Writing Exif data to .exif files
            for index, pth in enumerate(list_pth):
                exif_file = pth.with_suffix(".exif")
                with open(exif_file, "w") as fi:
                    json.dump(list_dic[index], fi, indent=" ")
        except Exception as e:
            print("TEST error in Class Dialog_extract_exif   writing_enriched_exif_data_to_exif_files   write json ", e)


    def placeholder_method_dialog_extract_exif_2_32(self):
        """
        Dummy (empty) method for connecting the "btn_preprocess_step1" button
        "btn_preprocess_step1" is connected to self.extract_from_folder_mission
        The "real" connection is in the open_window_31 method of the Main_Window class of the main module.
        def open_window_31(self):  de la class Main_Window() du module principal.
        The line of code is:
        self.Dialog_extract_exif.btn_preprocess_step1.clicked.connect(self.open_Dialog_synchro_clock)  # Connect Dialog_synchro_clock signal to Main_Window method
        """
        try:
            validate_answer = True
            self.data_signal_from_dialog_extract_exif_to_main_window.emit(validate_answer)
            Uti.show_info_message("IRDrone", "Exif data extraction and storage completed. \n ",
                                  "Synchronize the VIS and NIR timelines for this mission in the next step.")
            pass

        except Exception as e:
            print("error in placeholder_method       message :", e)


    def closeEvent(self, event):
        event.accept()


class Dialog_synchro_clock(QDialog):
    # Creates a class signal to transmit the data to the parent which will here be an instance of the window_11 class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_dialog_synchro_clock_to_main_window = pyqtSignal(bool)


    def __init__(self,  list_dic_exif_xmp, folderMissionPath):
        super().__init__()
        self.list_dic_exif_xmp = list_dic_exif_xmp
        self.folderMissionPath = folderMissionPath
        self.delta_clock = None
        self.delta_clock_initialization = None
        self.Fly = []
        self.pref_screen = Uti.Prefrence_Screen()  # Initializing screen preferences
        self.btn_rad1 = None
        self.btn_rad2 = None
        self.input_field_1 = None
        self.input_field_2 = None
        self.zone_324 = None
        self.btn_Synchro = None
        self.btn_OK_Sync_Next_Step = None
        self.btn_Cancel = None
        self.btn_Help = None

        self.init_GUI()

    def init_GUI(self):

        try:
            try:
                #   Setting the top command bar and window dimensions
                self.setStyleSheet(f"background-color: {self.pref_screen.background_color}; color: {self.pref_screen.txt_color};")
                self.setWindowTitle("Time lag between VIS and NIR images.")
                icon_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "IRDrone.ico")
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    QApplication.setWindowIcon(icon)  # Set the applicable icon in the class.
            except Exception as e:
                print("error   in Dialog_synchro_clock    initGUI  Setting the top command bar and window dimensions", e)

            width = int(self.pref_screen.windowDisplaySize[0] / 1.5)  # Main window width
            height = int(self.pref_screen.windowDisplaySize[1] / 2)  # Main window height

            #  Setting the window dimensions.
            self.setGeometry(0, 0, width, height)   # Create the central widget
            layout = QVBoxLayout()

            # Creating radio buttons
            self.btn_rad1 = QRadioButton("Enter the time offset value of NIR images relative to VIS images. \n"
                                         "> The value is expressed in seconds.  For example 45,09s\n"
                                         "  Attention please: the decimal separator being the comma. \n"
                                         "> A positive value indicates that the NIR camera clock is behind the VIS camera clock.")
            self.input_field_1 = QLineEdit()  # Creating input boxes
            self.input_field_1.setPlaceholderText("Enter a numeric value.")
            self.input_field_1.setValidator(QDoubleValidator())
            layout.addWidget(self.btn_rad1)               # Add  widgets in layout
            layout.addWidget(self.input_field_1)

            self.btn_rad2 = QRadioButton("Automatic offset calculation with the ARUCO procedure.")
            self.btn_rad2.setChecked(True)  # Default selection of first button
            self.input_field_2 = QLineEdit()
            self.input_field_2.setPlaceholderText("Enter a numeric value.")
            self.input_field_2.setValidator(QDoubleValidator())
            layout.addWidget(self.btn_rad2)
            layout.addWidget(self.input_field_2)

            #  control button area
            self.zone_324 = QWidget()
            layout.addWidget(self.zone_324)
            self.zone_324.layout = QHBoxLayout()

            self.btn_Synchro = QPushButton("Synchro TEST")
            self.btn_Synchro.setStyleSheet("background-color: darkBlue; color: white;")
            self.btn_Synchro.clicked.connect(self.on_synchro_clicked)
            self.zone_324.layout.addWidget(self.btn_Synchro)


            self.btn_OK_Sync_Next_Step = QPushButton("OK Synchro. Next Step >>>>>>>")
            self.btn_OK_Sync_Next_Step.clicked.connect(self.OK_Sync_Next_Step_clicked)
            # Disable OK  button
            self.btn_OK_Sync_Next_Step.setStyleSheet("background-color: darkGray; color: white;")
            self.btn_OK_Sync_Next_Step.setAutoDefault(False)
            self.btn_OK_Sync_Next_Step.setEnabled(False)
            self.zone_324.layout.addWidget(self.btn_OK_Sync_Next_Step)

            self.btn_Cancel = QPushButton("Cancel")
            self.btn_Cancel .setStyleSheet("background-color: gray; color: white;")
            self.btn_Cancel.clicked.connect(self.cancel_clicked)
            self.zone_324.layout.addWidget(self.btn_Cancel)

            self.btn_Help = QPushButton("Help")
            self.btn_Cancel.setStyleSheet("background-color: darkGreen; color: white;")
            self.btn_Help.clicked.connect(self.help_clicked)
            self.zone_324.layout.addWidget(self.btn_Help)

            self.zone_324.setLayout(self.zone_324.layout)
            self.setLayout(layout)

            # Screen management.
            Uti.center_on_screen(self, screen_Id=1)


        except Exception as e:
            print("error Dialog_synchro_clock class   in  def init_GIU :", e)


    def on_synchro_clicked(self):
        """
            Action to perform when pressing the button validate the choice of the type of synchronization method
            Here choice between synchronization with ARUCO or manual entry of the offset value.
        """
        if self.btn_rad2.isChecked():     # use of the ARUCO rotating sight
            self.aruco_process()
        elif self.btn_rad1.isChecked() and not self.input_field_1.text().strip():   # Checks if the input field is empty
            QMessageBox.warning(self, "Attention", "Please enter a numeric value.")
            return
        elif self.btn_rad1.isChecked():   # use of a manual value.
            self.manual_process()
        print("TEST 0030    self.delta_clock ", self.delta_clock, " s")
        # Enabled OK  button
        self.btn_OK_Sync_Next_Step.setStyleSheet("background-color: white; color: black;")
        self.btn_OK_Sync_Next_Step.setAutoDefault(True)
        self.btn_OK_Sync_Next_Step.setEnabled(True)


    def manual_process(self):
        """
            Manual entry of the offset value.
        """
        self.delta_clock = 0.
        try:
            input_text = self.input_field_1.text().replace(',', '.')  # Replacing commas with periods
            self.delta_clock = float(input_text)    # Attempting to convert text to float
            msg_txt2 = f"You have chosen a manual offset of the NIR and VIS camera clocks..\n The offset is : {self.delta_clock} s"
        except ValueError:
            QMessageBox.warning(self, "Error", "The value entered is not a valid number.")
            return
        QMessageBox.information(self, "IRDrone", msg_txt2)


    def aruco_process(self):
        """
            Synchronization with ARUCO
        """
        camera_definition = [('*.DNG', global_config.VIS_CAMERA), ('20*.RAW', global_config.NIR_CAMERA)]
        manual = False   # If true we can manually adjust the sync directly with sliders
        folder = os.path.join(self.folderMissionPath, "Synchro")
        if not self.input_field_2.text().strip():
            delta_clock_initialization = 0.
        else:
            try:
                input_text = self.input_field_2.text().replace(',', '.')  # Replacing commas with periods
                delta_clock_initialization = float(input_text)  # Attempting to convert text to float
            except ValueError:
                QMessageBox.warning(self, "Error", "The value entered is not a valid number.")
                return
        msg_txt2 = f"You have chosen an automatic calculation of the clock offset of the NIR and VIS cameras.\n " \
                   f"This calculation is based on the use of the ARUCO rotating sight.\n" \
                   f"You have chosen to initialize the calculation with the offset value: {delta_clock_initialization} s"
        QMessageBox.information(self, "IRDrone", msg_txt2)
        self.delta_clock = synchro_by_aruco.main_synchro(
            camera_definition, manual, delta_clock_initialization, folder,
            clean_proxy=False
        )


    def OK_Sync_Next_Step_clicked(self):
        """Method called when the 'OK' button is clicked.

        Updating dictionary data based on changes made by the user in free fields.
        Sends data ( validate_answer ) to Main_Window of Interactive_Main
        To do this, use the emission of a signal (data_signal.emit() )

        """
        try:
            self.time_line_img_NIR()     # Calculation of the time line of NIR images
            self.pairs_VIS_NIR()         # Matching VIS and NIR images
            self.geo_data()              # Calculation of geographic data (UTM coordinates, altitudes, heading, distances)

            # print("TEST  0136.DNG ", self.Fly[16])
            # print("TEST  0137.DNG ", self.Fly[17])
            # print("TEST  0138.DNG ", self.Fly[18])

            # builds a first version of the list of shooting points (ShootPoint class)
            list_Pts = self.build_list_shooting_point()
            # Writing list dictionary FLY/ShootPoint
            self.save_shooting_point(list_Pts)

            # End of data preparation preprocess
            validate_answer = True
            self.data_signal_from_dialog_synchro_clock_to_main_window.emit(validate_answer)
            txt_msg = f"Timeline synchronization has been taken into account...\n" \
                      f"The clock offset is equal to {self.delta_clock} s.\n" \
                      f"Visible and near-infrared images were matched.\n" \
                      f"The projection angles of the near-infrared image on the visible image were calculated."
            Uti.show_info_message("IRDrone", txt_msg, "You can start the process of processing your images.")

            self.close()
        except Exception as e:
            print("error in Dialog_synchro_clock ok_clicked: ", e)


    def build_list_shooting_point(self, verbose=True) -> list[dict]:
        """
         Built a partial version of shoot point before calculating alignment angles.
         At this stage the information is stored in the Fly dictionary
         The loadDicPointFly2Point method of class ShootPoint allows you to transfer the Fly dictionary into
         the data structure of class ShootPoint.

         Note: The ShootPoint Class was introduced in the early version of IRDrone. We therefore provide here the bridge between
         this primitive version and the interactive version.
          There is also the loadDicPoint2Point method of class ShootPoint. It is very similar to the previous one.
          However, the structure of the dictionary is different (tree of keys and sub keys). Plus some different key names
        of the key name of the interactive version.
          For this tree structure there is also the loadPoint2DicPoint method of class ShootPoint. It allows you to transfer
        the data structure of class ShootPoint to the tree dictionary (inverse operation of the previous one).

        :return: list_Pts    list of shooting point dictionaries (class ShootPoint)
        """
        list_Pts = []
        self.Fly = sorted(self.Fly, key=lambda x: int(x['Vis Shooting Number']))

        for index in range(len(self.Fly)):
            pt = ClassPt.ShootPoint()
            self.Fly[index]['Fly Shooting Number'] = index
            self.tempo_1(index)
            pt.loadDicPointFly2Point(self.Fly[index])
            if verbose: print(pt)  # "TEST"
            list_Pts.append(pt)

        return list_Pts


    def tempo_1(self, index):
        """
        These data are not yet calculated at this stage but they must be initialized to be able to build
        the point of class ShootPoint
        :param index:
        :return:
        """
        self.Fly[index]['Best Synchro']: int = 0
        self.Fly[index]['Best Mapping']: int = 0
        self.Fly[index]['Best Offset']: int = 0
        self.Fly[index]['x_1'] = 0.
        self.Fly[index]['x_2'] = 0.
        self.Fly[index]['x_3'] = 0.
        self.Fly[index]['Yaw IR to VI'] = 0.
        self.Fly[index]['Pitch IR to VI'] = 0.
        self.Fly[index]['Roll IR to VI'] = 0.
        self.Fly[index]['Yaw Coarse Align'] = 0.
        self.Fly[index]['Pitch Coarse Align'] = 0.
        self.Fly[index]['Roll Coarse Align'] = 0.
        self.Fly[index]['Alignment'] = 0


    def save_shooting_point(self, list_Pts):
        print("TEST 0041   save_shooting_point .... Currently being implemented ")


    def time_line_img_NIR(self):
        """
        1) Constructs the NIR image timeline by synchronizing it to the VIS image timeline.
        Please note, this does not mean that the NIR images themselves are synchronized with the VIS images.
        There will always be a small lag (which is not constant).
        This shift is inherent to the design of the SJCam M20 NIR camera “low coast” system, the triggering of which
        is not synchronized with that of the VIS camera of the DJI drone.

        2) Starts the construction of a list of dictionaries containing the summary of essential information on the images of the flight.
        This summary gives for each VIS image taken during the flight over the area to be studied:
            - The number of the VIS shot in the visible spectrum (since takeoff).
            - Its position on the timeline
            - The temporally closest NIR image in the near infrared spectrum.
            - the time difference between the two images (positive or negative).
            - The GPS position of the VIS image taken (provided by the exif data of the VIS image in dng format taken by the drone).
            - The attitude of the drone and the gimbal at the time of this shot.
              The angles {yaw, pitch, roll} of the gimbal and the drone are assigned to the VIS and NIR cameras, respectively.
              Please note: The yaw gimbal and drone correspond respectively to the VIS and NIR camera roll.
                          The roll gimbal and drone correspond respectively to the VIS and NIR camera yaw.
                          The gimbal and drone pitch correspond respectively to the VIS and NIR camera pitch.

        :return:
        """
        try:
            origin_date_py: datetime = self.origin_date_VIS()
            self.Fly: list[dict[str, any]] = []

            for index, dic in enumerate(self.list_dic_exif_xmp):
                if dic['File Name'].split(".")[1].lower() == "raw":
                    date_time_temp: datetime = Uti.datetimeJson2datetimePy(dic['Date/Time Original'])
                    time_line_NIR: float = (date_time_temp - origin_date_py).total_seconds() - self.delta_clock
                    self.list_dic_exif_xmp[index]['Time Line'] = time_line_NIR

                elif dic['File Name'].split(".")[1].lower() == "dng":
                    dicVis = {}
                    dicVis['Vis File Name'] = dic["File Name"]
                    dicVis['Vis Directory'] = dic['Directory']
                    dicVis['Vis Date/Time Original'] = dic['Date/Time Original']
                    dicVis['Vis Shooting Number'] = dic['Shooting Number']
                    dicVis['Vis Time Line'] = round(dic['Time Line'], 4)
                    dicVis['Drone Latitude'] = Uti.gps_coordinate_to_float(dic['GPS Latitude'])
                    if dicVis['Drone Latitude'] >= 0:
                        dicVis['Drone S-N'] = "N"
                    else:
                        dicVis['Drone S-N'] = "S"
                    dicVis['Drone Longitude'] = Uti.gps_coordinate_to_float(dic['GPS Longitude'])
                    if dicVis['Drone Longitude'] >= 0:
                        dicVis['Drone W-E'] = "E"
                    else:
                        dicVis['Drone W-E'] = "W"
                    dicVis['Altitude Drone/TakeOff'] = float(dic['Relative Altitude'])
                    dicVis['Camera Vis Yaw'] = dic['Gimbal Roll']
                    dicVis['Camera Vis Roll'] = dic['Gimbal Yaw']
                    dicVis['Camera Vis Pitch'] = dic['Gimbal Pitch']
                    dicVis['Camera Nir Yaw'] = dic['Flight Roll']
                    dicVis['Camera Nir Roll'] = dic['Flight Yaw']
                    dicVis['Camera Nir Pitch'] = dic['Flight Pitch']
                    self.Fly.append(dicVis)

        except Exception as e:
            print("error  in time_line_img_NIR", e)


    def pairs_VIS_NIR(self):

        try:
            for indexVis, dicVis in enumerate(self.Fly):
                minDt = None
                indexMinDt = None
                for indexNir, dic in enumerate(self.list_dic_exif_xmp):
                    if dic['File Name'].split(".")[1].lower() == "raw":
                        #  gap sign :
                        # if t_VIS < t_NIR <=> gap < 0   the NIR image was taken after the VIS image
                        # if t_VIS > t_NIR <=> gap > 0   the NIR image was taken before the VIS image
                        t_VIS = float(dicVis['Vis Time Line'])
                        t_NIR = float(dic['Time Line'])
                        Dt = t_VIS - t_NIR
                        if minDt is None or abs(Dt) < abs(minDt):
                            minDt = Dt
                            indexMinDt = indexNir

                self.Fly[indexVis]['Nir File Name'] = self.list_dic_exif_xmp[indexMinDt]['File Name']
                self.Fly[indexVis]['Nir Directory'] = self.list_dic_exif_xmp[indexMinDt]['Directory']
                self.Fly[indexVis]['Nir Date/Time Original'] = self.list_dic_exif_xmp[indexMinDt]['Date/Time Original']
                self.Fly[indexVis]['Nir Shooting Number'] = self.list_dic_exif_xmp[indexMinDt]['Shooting Number']
                self.Fly[indexVis]['Nir Time Line'] = round(self.list_dic_exif_xmp[indexMinDt]['Time Line'], 4)
                self.Fly[indexVis]['Dt Vis-Nir'] = round(minDt, 3)

                # Print for TEST
                if self.pref_screen.verbose:
                    # fTimeLine = Uti.format_number(self.Fly[indexVis]['Vis Time Line'], decimal=2)
                    # fDt = Uti.format_number(self.Fly[indexVis]['Dt Vis-Nir'], car="+")
                    # print(f"TEST  {self.Fly[indexVis]['Vis File Name']} |  {self.Fly[indexVis]['Nir File Name']} | {fTimeLine} s | {fDt} s")
                    pass

        except Exception as e:
            print("error in  pairs_VIS_NIR ", e)


    def geo_data(self):
        """
        Enriched the shooting point dictionary
             > UTM coordinates
             > Distance and heading to the next point
             > Total distance
             > Geographic altitude of the land (relative to sea level via IGN)

        :return:
        """

        for i in range(len(self.Fly)):
            self.Fly[i]['X UTM'], self.Fly[i]['Y UTM'], self.Fly[i]['Zone UTM'] = Geo.geo2UTM(self.Fly[i]['Drone Latitude'],  self.Fly[i]['Drone Longitude'])

        for i in range(len(self.Fly) - 1):
            self.Fly[i]['Dist To Next Pt'], self.Fly[i]['Cape To Next Pt'] = Geo.segmentUTM(self.Fly[i]['Drone Latitude'], self.Fly[i]['Drone Longitude'], self.Fly[i + 1]['Drone Latitude'], self.Fly[i + 1]['Drone Longitude'])
        self.Fly[-1]['Dist To Next Pt'], self.Fly[-1]['Cape To Next Pt'] = 0, 0

        cumulative_distance = 0
        self.Fly[0]['Dist Cumul'] = cumulative_distance
        for i in range(1, len(self.Fly)):
            cumulative_distance += self.Fly[i]['Dist To Next Pt']
            self.Fly[i]['Dist Cumul'] = cumulative_distance

        altitude = Geo.altitude_IGN([(self.Fly[i]['Drone Latitude'], self.Fly[i]['Drone Longitude']) for i in range(len(self.Fly))], bypass=False)
        altitudeTakeOff = self.altitude_take_off()
        print("TEST  altitudeTakeOff/ground ", altitudeTakeOff, " m")
        for i in range(len(self.Fly)):
            self.Fly[i]['Altitude Ground/Sea level'] = altitude[i]
            self.Fly[i]['Altitude Drone/Ground'] = self.Fly[i]['Altitude Drone/TakeOff'] + altitudeTakeOff - self.Fly[i]['Altitude Ground/Sea level']


    def origin_date_VIS(self) -> datetime:
        config_file = Path(self.folderMissionPath) / "FlightAnalytics" / "config.json"
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                origin_date_py = datetime.strptime(dic_config['Date Exif'], "%Y:%m:%d %H:%M:%S")
        else:
            origin_date_py = None
        return origin_date_py


    def altitude_take_off(self) -> float:
        config_file = Path(self.folderMissionPath) / "FlightAnalytics" / "config.json"
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                altitudeTakeOff = float(dic_config['GPS alti'])
        else:
            altitudeTakeOff = 0.
        return altitudeTakeOff


    def cancel_clicked(self):
        """Method called when the 'Cancel' button is clicked."""
        try:
            self.close()
        except Exception as e:
            print("Error in Class Windows_2 cancel_clicked", e)


    def help_clicked(self):
        """Method called when the 'Help' button is clicked."""
        # Displays a help message
        Uti.show_info_message("IRDrone", "Currently being implemented ...", "")
        pass




