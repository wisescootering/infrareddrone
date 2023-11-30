import sys
import os
import shutil
import json
from datetime import date, time, datetime
from typing import Any, Dict, Optional, Tuple, List, Union
from pathlib import Path
import numpy as np

# -------------------- Image Library ------------------------------
import rawpy
import imageio
# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QDialog, QFileDialog, QLabel, \
    QRadioButton, QLineEdit, QPushButton, QMessageBox, QProgressBar, QFrame
from PyQt6.QtGui import QDoubleValidator, QPixmap, QColor, QIcon
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression


# -------------- IRDrone Library ------------------------------------
import IRD_interactive_utils as Uti
from IRD_interactive_utils import Prefrence_Screen
import IRD_Interactive_Exif_Xmp as ExifXmp

class Window_31(QDialog):
    def __init__(self,  dic_takeoff=dict()):
        super().__init__()
        self.pref_screen = Uti.Prefrence_Screen()    # Initializing screen preferences
        self.init_GUI()                              # Initializing the GUI
        self.setLayout(self.main_layout)
        self.dic_takeoff = dic_takeoff
        self.folderMissionPath = None


    def init_GUI(self):
        try:
            try:
                #   Setting the top command bar and window dimensions
                self.setStyleSheet("background-color: white; color: black;")
                self.setWindowTitle("Extraction of Exif data from the flight.")
                # print("TEST screen.directory depuis initGUI de la class window_11:    ", self.pref_screen.directory)
                self.default_app_dir = os.path.join("C:/", "Program Files", "IRdrone")
                self.default_user_dir = os.path.join("C:/", "Air-Mission")
                icon_path = os.path.join(self.default_app_dir, "Icon", "IRDrone.ico")
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    self.setWindowIcon(icon)
            except Exception as e:
                print("error   in Window_31    initGUI  Setting the top command bar and window dimensions", e)

            # Set layout and widgets
            # Create the central widget
            self.central_widget = QWidget()
            # Create the main layout
            self.main_layout = QVBoxLayout(self.central_widget)

            # Create the four zones (sublayouts) and add them to the main layout
            zone1_layout = QHBoxLayout()
            zone2_layout = QVBoxLayout()
            zone3_layout = QVBoxLayout()

            zone4_layout = QVBoxLayout()
            bottom_command = QHBoxLayout()
            zone4_layout.addLayout(bottom_command)

            self.main_layout.addLayout(zone1_layout)
            self.main_layout.addLayout(zone2_layout)
            self.main_layout.addLayout(zone3_layout)
            self.main_layout.addLayout(zone4_layout)

            # Area 1

            # Area 2  Image area.

            # ----------------  Creating a neutral image -----------------
            width = self.pref_screen.windowDisplaySize[1]  # int(600)
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

            #  Area 4    Previous Step an Next Step button
            self.btn_preprocess_step1 = QPushButton("Extract and Save Exif tags")
            self.btn_preprocess_step1.setFixedWidth(250)
            self.btn_preprocess_step1.setStyleSheet("background-color: darkBlue; color: white;")
            self.btn_Cancel = QPushButton("Cancel")
            self.btn_Cancel.setFixedWidth(100)
            self.btn_Cancel.setStyleSheet("background-color: darkGray; color: black;")

            self.btn_Help = QPushButton("Help")
            self.btn_Help.setFixedWidth(100)
            self.btn_Help.setStyleSheet("background-color: darkGray; color: black;")

            #self.btn_NextStep = QPushButton("next step >>>>")
            #self.btn_NextStep.setFixedWidth(100)
            #self.btn_NextStep.setStyleSheet("background-color: darkGray; color: black;")
            # Disable Next Step  button
            #self.btn_NextStep.setAutoDefault(False)
            #self.btn_NextStep.setEnabled(False)
            #self.btn_NextStep.setStyleSheet("background-color: darkGray; color:gray;")

            bottom_command.addWidget(self.btn_preprocess_step1)
            bottom_command.addWidget(self.btn_Cancel)
            bottom_command.addWidget(self.btn_Help)
            #bottom_command.addWidget(self.btn_NextStep)

            # Progress bar
            self.progress_bar = QProgressBar(self)
            self.progress_bar.setStyleSheet("QProgressBar { color: white; }")
            zone4_layout.addWidget(self.progress_bar)
            self.progress_bar.setValue(0)


            self.btn_preprocess_step1.clicked.connect(self.extract_from_folder_mission)
            self.btn_Cancel.clicked.connect(self.cancel_clicked)
            self.btn_Help.clicked.connect(self.help_clicked)
            self.resize(600, 600)
            Uti.center_on_screen(self, screen_Id=1)

        except Exception as e:
            print("error Window_31 class   in  def init_GUI :", e)


    def extract_2(self):
        if not self.coherent_response:
            self.cancel_clicked()

        # Writing exif /xmp (enriched) data for the AerialPhotography folder
        folder_path_FLY = Path(self.folderMissionPath, "AerialPhotography")
        # 1) Create a list of all .dng, .jpg and .RAW files present in the AerialPotography folder
        list_path_image = [file for file in folder_path_FLY.glob('*') if file.suffix.lower() in ['.dng', '.jpg', '.raw']]
        # 2)
        # Construction of a list of dictionaries of standard and enriched Exif / xmp data (shot number, VIS time line).
        list_dic_exif_xmp = self.get_EXIF_XMP_interactive(list_path_image, verbose=False)
        # 3) Writing Exif dictionaries to files (one for each image)
        self.writing_enriched_exif_data_to_exif_files(list_path_image, list_dic_exif_xmp)

        self.placeholder_method_31_2_32()


    def get_EXIF_XMP_interactive(self, list_pth: list[Path], verbose: bool = False) -> list[Dict]:
        """
        Writing Exif and Xmp data from a list of images.
        Each image is processed individually by the get_EXIF_XMP procedure which
        extracts the data
        The exif/xmp data file has the same name as its image and has the extension .exif.
        It is readable in text format.

        The basic exif data is enriched (shot number, date of the shot, time line)

        The get_EXIF_XMP procedure uses third-party software: ExifTool.exe.
        However, it is very effective because ExifTool is capable of reading both classic Exif data and also XMP data.
        In addition it also allows you to write keys (including personal keys).
        Useful for example to add geographic altitude or "true time" to a timeline.

        :param list_pth:
        :param verbose:
        :return: list_dic
        """
        try:
            list_dic = []
            list_time_VIS = []
            for index, pth in enumerate(list_pth):
                progressBarValue = round(100 * index / (len(list_pth) - 1), 1)
                self.progress_bar.setValue(progressBarValue)
                #  Extracting original Exif data
                dic = ExifXmp.get_EXIF_XMP(pth, index, verbose=verbose)

                # Enrichment of classic Exif data. (shot number, corrected shooting time, etc.)
                if dic["File Name"].split(".")[1].lower() == "raw":
                    shootNum, shootDate = Uti.extract_date_RAW_SJCam(dic["File Name"])
                    dic["Date/Time Original"] = Uti.datetimePy2datetimeJson(shootDate)
                elif dic["File Name"].split(".")[1].lower() == "jpg":
                    shootNum, _ = Uti.extract_date_RAW_SJCam(dic["File Name"])
                elif dic["File Name"].split(".")[1].lower() == "dng":
                    shootNum = Uti.extract_num_DNG_DJI(dic["File Name"])
                    list_time_VIS.append((shootNum, dic["Date/Time Original"]))
                dic["Shooting Number"] = shootNum
                list_dic.append(dic)
            # Enriching Exif data from VIS images with timeline values.
            self.dt_time_VIS = self.effective_recording_step_VIS(list_time_VIS)
            for index in range(len(list_dic)):
                if list_dic[index]["File Name"].split(".")[1].lower() == "dng":
                    list_dic[index]["Time Line"] = (list_dic[index]["Shooting Number"] - 1) * self.dt_time_VIS
            return list_dic
        except Exception as e:
            print("error in get_EXIF_XMP_interactive  ", e)


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
        dt_time_VIS = (time_shoot_end - self.origine_date_VIS()).total_seconds() / (num_shoot_end - 1)
        print(f"TEST  dt_time_VIS = {dt_time_VIS} s")
        return dt_time_VIS


    def origine_date_VIS(self) -> datetime:
        config_file = Path(self.folderMissionPath, 'config.json')
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                origine_date_py = datetime.strptime(dic_config['Date Exif'], "%Y:%m:%d %H:%M:%S")
        else:
            origine_date_py = None
        return origine_date_py


    def writing_enriched_exif_data_to_exif_files(self, list_pth, list_dic):
        try:
            # Writing enriched Exif data to .exif files
            for index, pth in enumerate(list_pth):
                exif_file = pth.with_suffix(".exif")
                with open(exif_file, "w") as fi:
                    json.dump(list_dic[index], fi, indent=" ")
        except Exception as e:
            print("TEST error in writing_enriched_exif_data_to_exif_files   write json ", e)


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        self.close()


    def help_clicked(self):
        """Méthode appelée lorsque le bouton 'Help' est cliqué."""
        # Afficher un message d'aide
        pass


    def extract_from_folder_mission(self, dic_takeoff):
        try:
            image_takeoff_available, path_image_mission = Uti.image_takeoff_available_test(dic_takeoff, self.pref_screen.default_user_dir)

            if image_takeoff_available:
                # construction du nom du dossier de la mission
                self.folderMissionPath = Path(dic_takeoff['File path mission'])
                self.coherent_response = Uti.folder_name_consistency_analysis(self.folderMissionPath)
                self.extract_2()
            else:
                try:
                    self.folderMissionPath = Path(QFileDialog.getExistingDirectory(self, 'Select Mission Folder', self.pref_screen.default_user_dir))
                    if self.folderMissionPath.exists() and self.folderMissionPath != self.pref_screen.default_user_dir:
                        self.coherent_response = Uti.folder_name_consistency_analysis(self.folderMissionPath)
                        if self.coherent_response:
                            print(f"TEST  la mission existe  et elle est à l'emplacement : {self.folderMissionPath}")
                            self.extract_2()
                        else:
                            Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n{self.folderMissionPath} \nwhich is not a Mission IRDrone folder.",
                                               " Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_<free text> ).\n or create a mission \n Use the <Create a New Mission> command.")
                    else:
                        Uti.show_warning_OK_Cancel_message("IRDrone", f"You have chosen the folder : \n {self.folderMissionPath} \n",
                                                           " Your choice of folder is not recognized in IRDrone\n Choose a compatible folder ( name FLY_YYYYMMDD_hhmm_[Optional text] ).")
                        self.coherent_response = False
                except Exception as e:
                    print("error 1   in extract_from_folder_mission :", e)
            if not self.coherent_response:
                self.extract_from_folder_mission(dic_takeoff)
        except Exception as e:
            print("error 2   in extract_from_folder_mission :", e)


    def placeholder_method_31_2_32(self):
        """
        Dummy (empty) method for connecting the "Next Step" button.
        The "real" connection is in the open_window_31 method of the Main_Window class of the main module.
        def open_window_31(self):  de la class Main_Window() du module principal.
        The line of code is:
        self.window_31.btnNextStep.clicked.connect(self.open_window_32)  # Connect Window_32 signal to Main_Window method
        """
        try:
            Uti.show_info_message("IRDrone", "Extraction et stockage des données Exif terminés. \n ",
                                  "Synchroniser les time-line VIS et NIR  for this mission in the next step.")
            pass

        except Exception as e:
            print("error in placeholder_method       message :", e)


    def closeEvent(self, event):
        event.accept()


class Window_32(QDialog):
    # Creates a class signal to transmit the data to the parent which will here be an instance of the window_11 class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_window_32_to_main_window = pyqtSignal(bool)
    def __init__(self,  dic_takeoff=dict()):
        super().__init__()
        self.pref_screen = Uti.Prefrence_Screen()    # Initializing screen preferences
        self.init_GUI()
        self.dic_takeoff = dic_takeoff
        self.delta_horloge = None
        self.delta_horloge_ini = None

    def init_GUI(self):

        try:
            try:
                #   Setting the top command bar and window dimensions
                self.setStyleSheet("background-color: white; color: black;")
                self.setWindowTitle("Time lag between VIS and NIR images.")
                # print("TEST screen.directory depuis initGUI de la class window_11:    ", self.pref_screen.directory)
                self.default_app_dir = os.path.join("C:/", "Program Files", "IRdrone")
                self.default_user_dir = os.path.join("C:/", "Air-Mission")
                icon_path = os.path.join(self.default_app_dir, "Icon", "IRDrone.ico")
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    self.setWindowIcon(icon)
            except Exception as e:
                print("error   in initUI  ", e)

            self.setGeometry(100, 100, 800, 600)

            layout = QVBoxLayout()

            # Creating radio buttons
            self.btn_rad1 = QRadioButton("Enter the time offset value of NIR images relative to VIS images. \n"
                                         "> The value is expressed in seconds.  For example 45,09s\n"
                                         "  Attention please: the decimal separator being the comma. \n"
                                         "> A positive value indicates that the NIR camera clock is behind the VIS camera clock.")
            self.btn_rad2 = QRadioButton("Automatic offset calculation with the ARUCO procedure.")
            self.btn_rad1.setChecked(True)  # Default selection of first button

            # Creating input boxes
            self.input_field_1 = QLineEdit()
            self.input_field_1.setPlaceholderText("Enter a numeric value.")
            self.input_field_1.setValidator(QDoubleValidator())
            self.input_field_2 = QLineEdit()
            self.input_field_2.setPlaceholderText("Enter a numeric value.")
            self.input_field_2.setValidator(QDoubleValidator())

            # Ajout des widgets au layout
            layout.addWidget(self.btn_rad1)
            layout.addWidget(self.input_field_1)
            layout.addWidget(self.btn_rad2)
            layout.addWidget(self.input_field_2)


            self.zone_321 = QWidget()
            layout.addWidget(self.zone_321)

            self.zone_322 = QWidget()
            layout.addWidget(self.zone_322)

            self.zone_323 = QWidget()
            layout.addWidget(self.zone_323)

            self.zone_324 = QWidget()
            layout.addWidget(self.zone_324)

            self.btn_Synchro = QPushButton("Synchro TEST")
            self.btn_OK = QPushButton("Next Step  >>>>>>>>>>>")
            self.btn_Cancel = QPushButton("Cancel")
            self.btn_Help = QPushButton("Help")

            self.zone_324.layout = QHBoxLayout()
            self.zone_324.layout.addWidget(self.btn_Synchro)
            self.zone_324.layout.addWidget(self.btn_OK)
            self.zone_324.layout.addWidget(self.btn_Cancel)
            self.zone_324.layout.addWidget(self.btn_Help)
            self.zone_324.setLayout(self.zone_324.layout)

            self.btn_Synchro.clicked.connect(self.on_synchro_clicked)
            self.btn_OK.clicked.connect(self.ok_synchro_clicked)
            self.btn_Cancel.clicked.connect(self.cancel_clicked)
            self.btn_Help.clicked.connect(self.help_clicked)

            # Disable OK  button
            self.btn_OK.setStyleSheet("background-color: darkGray; color: white;")
            self.btn_OK.setAutoDefault(False)
            self.btn_OK.setEnabled(False)

            self.setLayout(layout)

            Uti.center_on_screen(self, screen_Id=1)


        except Exception as e:
            print("error Window_32 class   in  def init_GIU :", e)


    def on_synchro_clicked(self):
        # Action à effectuer lors de l'appui sur le bouton valider
        VERBOSE = True
        #
        # Ici choix entre synchro avec ARUCO  ou entrée manuelle de la valeur du décalage.

        if self.btn_rad2.isChecked():
            msg_txt1 = f"IRDrone"

            if not self.input_field_2.text().strip():
                self.delta_horloge_ini = 0
                if VERBOSE: print("TEST  Option 2 sélectionnée. La valeur du décalage initial des horloges est:", self.delta_horloge_ini, " s")
                msg_txt2 = f"Vous avez choisi un calcul automatique du décalge des horloges des caméras NIR et VIS.\n " \
                           f"Ce calcul est basé sur l'utilisation de la mire tournante ARUCO."
            else:
                # Remplacement des virgules par des points
                input_text = self.input_field_2.text().replace(',', '.')

                # Tentative de conversion du texte en float
                try:
                    self.delta_horloge_ini = float(input_text)
                    if VERBOSE: print("TEST  Option 2 sélectionnée. La valeur du décalage initial des horloges est:", self.delta_horloge_ini, " s")
                    msg_txt2 = f"Vous avez choisi un calcul automatique du décalge des horloges des caméras NIR et VIS.\n " \
                           f"Ce calcul est basé sur l'utilisation de la mire tournante ARUCO.\n"\
                           f"Vous avez choisi d'initialiser le calcul avec la valeur de décalage : {self.delta_horloge_ini} s"
                except ValueError:
                    QMessageBox.warning(self, "Erreur", "La valeur dinitialisation entrée n'est pas un nombre valide.")
                    return


            self.aruco_process()

        # Vérification si le champ de saisie est vide
        elif self.btn_rad1.isChecked() and not self.input_field_1.text().strip():
            QMessageBox.warning(self, "Attention", "Veuillez entrer une valeur numérique.")
            return
        elif self.btn_rad1.isChecked():
            # Remplacement des virgules par des points
            input_text = self.input_field_1.text().replace(',', '.')

            # Tentative de conversion du texte en float
            try:
                self.delta_horloge = float(input_text)
                if VERBOSE: print("TEST  Option 1 sélectionnée. La valeur du décalage des horloges est:", self.delta_horloge, " s")
                msg_txt1 = f"IRDrone"
                msg_txt2 = f"Vous avez choisi manuellement le décalge des horloges des caméras NIR et VIS.\n Il est de : {self.delta_horloge} s"
            except ValueError:
                QMessageBox.warning(self, "Erreur", "La valeur entrée n'est pas un nombre valide.")
                return

        QMessageBox.information(self, msg_txt1, msg_txt2)
        # Enabled OK  button
        self.btn_OK.setStyleSheet("background-color: white; color: black;")
        self.btn_OK.setAutoDefault(True)
        self.btn_OK.setEnabled(True)


    def aruco_process(self):
        if self.delta_horloge_ini is None or self.delta_horloge_ini == 0:
            delta_horloge_initialisation = 0
            # lancer la procédure de clacul automatique
            print("TEST   ARUCO sans valeur initiale ... en cours d'implémentation")
            self.delta_horloge = self.delta_horloge_ini + 1000
            pass
        elif self.delta_horloge_ini is float:
            delta_horloge_initialisation = self.delta_horloge_ini
            # lancer la procédure de clacul automatique
            print(f"TEST   ARUCO avec valeur initiale  {delta_horloge_initialisation} s ... en cours d'implémentation")
            self.delta_horloge = self.delta_horloge_ini + 1000



    def ok_synchro_clicked(self):
        """Method called when the 'OK' button is clicked.

        Updating dictionary data based on changes made by the user in free fields.
        Sends data ( validate_answer ) to Main_Window of Interactive_Main
        To do this, use the emission of a signal (data_signal.emit() )

        """
        try:
            #self.update_dic_takeoff()
            self.validate_answer = True
            self.data_signal_from_window_32_to_main_window.emit(self.validate_answer)
            Uti.show_info_message("IRDrone", "La synchronisation des time-line a bien été prise en compte ...", f"Le décalage des horloges est égal à {self.delta_horloge} s")

            self.close()
        except Exception as e:
            print("error in Window_32 ok_clicked: ", e)


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        self.close()


    def help_clicked(self):
        """Méthode appelée lorsque le bouton 'Help' est cliqué."""
        # Afficher un message d'aide
        pass




