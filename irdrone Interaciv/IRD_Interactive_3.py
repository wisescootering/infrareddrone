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
sys.path.append(osp.join(osp.dirname(__file__), '../utils'))
import utils_IRdrone_Class as ClassPt



class Dialog_extract_exif(QDialog):
    # Creates a class signal to transmit the data to the parent which will here be an instance of the main window class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_dialog_extract_exif_to_main_window = pyqtSignal(bool)


    def __init__(self, dic_takeoff: dict):
        super().__init__()
        self.pref_screen = Uti.Prefrence_Screen()    # Initializing screen preferences
        self.init_GUI()                              # Initializing the GUI
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
            print("error   in Window_31    initGUI  Setting the top command bar and window dimensions", e)
        width = int(self.pref_screen.windowDisplaySize[0]/1.5)   # Main window width
        height = int(self.pref_screen.windowDisplaySize[1]/2)  # Main window height

        #  Setting the window dimensions.
        # Créer le widget central
        self.setGeometry(0, 0, width, height)
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        # Create the tre zones (and sublayouts for zone 3) and add them to the main layout
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
        self.progress_bar = QProgressBar(self)
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


    def get_EXIF_XMP_interactive(self, list_pth: list[Path], verbose: bool = False) -> list[dict]:
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
        try:
            self.close()
        except Exception as e:
            print("Error in Calss Windows_1 cancel_clicked", e)


    def help_clicked(self):
        """Méthode appelée lorsque le bouton 'Help' est cliqué."""
        # Afficher un message d'aide
        Uti.show_info_message("IRDrone", "En cours d'implémentation ...", "")
        pass


    def extract_from_folder_mission(self):
        try:
            image_takeoff_available, path_image_mission = Uti.image_takeoff_available_test(self.dic_takeoff, self.pref_screen.default_user_dir)

            if image_takeoff_available:
                # construction du nom du dossier de la mission
                self.folderMissionPath = Path(self.dic_takeoff['File path mission'])
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
                self.extract_from_folder_mission()
        except Exception as e:
            print("error 2   in extract_from_folder_mission :", e)


    def extract_2(self):
        try:
            if not self.coherent_response:
                self.cancel_clicked()

            # Writing exif /xmp (enriched) data for the AerialPhotography folder
            folder_path_FLY = Path(self.folderMissionPath, "AerialPhotography")
            # 1) Create a list of all .dng, .jpg and .RAW files present in the AerialPotography folder
            list_path_image = [file for file in folder_path_FLY.glob('*') if file.suffix.lower() in ['.dng', '.jpg', '.raw']]
            # 2) Construction of a list of dictionaries of standard and enriched Exif / xmp data (shot number, VIS time line).
            self.list_dic_exif_xmp = self.get_EXIF_XMP_interactive(list_path_image, verbose=False)
            # 3) Writing Exif dictionaries to files (one for each image)
            self.writing_enriched_exif_data_to_exif_files(list_path_image, self.list_dic_exif_xmp)

            self.placeholder_method_dialog_extract_exif_2_32()
        except Exception as e:
            print("error   in extract_2  ", e)


    def placeholder_method_dialog_extract_exif_2_32(self):
        """
        Dummy (empty) method for connecting the "btn_preprocess_step1" button
        "btn_preprocess_step1" is connected to self.extract_from_folder_mission -> self.extract_2
        The "real" connection is in the open_window_31 method of the Main_Window class of the main module.
        def open_window_31(self):  de la class Main_Window() du module principal.
        The line of code is:
        self.Dialog_extract_exif.btn_preprocess_step1.clicked.connect(self.open_Dialog_synchro_clock)  # Connect Dialog_synchro_clock signal to Main_Window method
        """
        try:
            validate_answer = True
            self.data_signal_from_dialog_extract_exif_to_main_window.emit(validate_answer)
            Uti.show_info_message("IRDrone", "Extraction et stockage des données Exif terminés. \n ",
                                  "Synchroniser les time-line VIS et NIR  for this mission in the next step.")
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
        self.pref_screen = Uti.Prefrence_Screen()    # Initializing screen preferences
        self.init_GUI()
        self.list_dic_exif_xmp = list_dic_exif_xmp
        self.folderMissionPath = folderMissionPath
        self.delta_horloge = None
        self.delta_horloge_ini = None

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
            # Créer le widget central
            self.setGeometry(0, 0, width, height)

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
        # Action à effectuer lors de l'appui sur le bouton valider le choix du type de méthode de synchronisation
        # Ici choix entre synchro avec ARUCO  ou entrée manuelle de la valeur du décalage.
        #
        self.list_dic_exif_xmp[319]["toto"] = "TEST"   # TEST


        if self.btn_rad2.isChecked():
            # ---------------------------------------------------------
            # utilisation de la mire tournante ARUCO
            # ---------------------------------------------------------
            msg_txt1 = f"IRDrone"

            if not self.input_field_2.text().strip():
                self.delta_horloge_ini = 0
                if self.pref_screen.verbose: print("TEST  Option 2 sélectionnée. La valeur du décalage initial des horloges est:", self.delta_horloge_ini, " s")
                msg_txt2 = f"Vous avez choisi un calcul automatique du décalge des horloges des caméras NIR et VIS.\n " \
                           f"Ce calcul est basé sur l'utilisation de la mire tournante ARUCO."
            else:
                # Remplacement des virgules par des points
                input_text = self.input_field_2.text().replace(',', '.')

                # Tentative de conversion du texte en float
                try:
                    self.delta_horloge_ini = float(input_text)
                    if self.pref_screen.verbose: print("TEST  Option 2 sélectionnée. La valeur du décalage initial des horloges est:", self.delta_horloge_ini, " s")
                    msg_txt2 = f"Vous avez choisi un calcul automatique du décalge des horloges des caméras NIR et VIS.\n " \
                           f"Ce calcul est basé sur l'utilisation de la mire tournante ARUCO.\n"\
                           f"Vous avez choisi d'initialiser le calcul avec la valeur de décalage : {self.delta_horloge_ini} s"
                except ValueError:
                    QMessageBox.warning(self, "Erreur", "La valeur dinitialisation entrée n'est pas un nombre valide.")
                    return


            self.aruco_process()

        # Vérifie si le champ de saisie est vide
        elif self.btn_rad1.isChecked() and not self.input_field_1.text().strip():
            QMessageBox.warning(self, "Attention", "Veuillez entrer une valeur numérique.")
            return
        elif self.btn_rad1.isChecked():
            # ---------------------------------------------------------
            # utilisation d'une valeur manuelle.
            # ---------------------------------------------------------
            # Remplacement des virgules par des points
            input_text = self.input_field_1.text().replace(',', '.')

            # Tentative de conversion du texte en float
            try:
                self.delta_horloge = float(input_text)
                if self.pref_screen.verbose: print("TEST  Option 1 sélectionnée. La valeur du décalage des horloges est:", self.delta_horloge, " s")
                msg_txt1 = f"IRDrone"
                msg_txt2 = f"Vous avez choisi manuellement le décalge des horloges des caméras NIR et VIS.\n Il est de : {self.delta_horloge} s"
            except ValueError:
                QMessageBox.warning(self, "Erreur", "La valeur entrée n'est pas un nombre valide.")
                return

            self.manual_process()

        QMessageBox.information(self, msg_txt1, msg_txt2)
        # Enabled OK  button
        self.btn_OK_Sync_Next_Step.setStyleSheet("background-color: white; color: black;")
        self.btn_OK_Sync_Next_Step.setAutoDefault(True)
        self.btn_OK_Sync_Next_Step.setEnabled(True)


    def manual_process(self):
        if self.delta_horloge_ini is None or self.delta_horloge_ini == 0:
            delta_horloge_initialisation = 0
            # lancer la procédure de clacul automatique avec une valeur d'initialisation nulle
            if self.pref_screen.verbose: print("TEST  méthode manuelle ... en cours d'implémentation")
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!   Phase de TEST !!!!!!!!!!!!!!!!!!!!!!!
            self.delta_horloge = self.delta_horloge_ini + 3894.91
            pass
        elif self.delta_horloge_ini is float:
            delta_horloge_initialisation = self.delta_horloge_ini
            # lancer la procédure de clacul automatique
            print(f"TEST   méthode manuelle  {delta_horloge_initialisation} s ... en cours d'implémentation")
            self.delta_horloge = self.delta_horloge_ini



    def aruco_process(self):
        if self.delta_horloge_ini is None or self.delta_horloge_ini == 0:
            delta_horloge_initialisation = 0
            # lancer la procédure de clacul automatique avec une valeur d'initialisation nulle
            if self.pref_screen.verbose: print("TEST  ARUCO sans valeur initiale ... en cours d'implémentation")
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!   Phase de TEST !!!!!!!!!!!!!!!!!!!!!!!
            self.delta_horloge = self.delta_horloge_ini + 3894.91
            pass
        elif self.delta_horloge_ini is float:
            delta_horloge_initialisation = self.delta_horloge_ini
            # lancer la procédure de clacul automatique
            print(f"TEST   ARUCO avec valeur initiale  {delta_horloge_initialisation} s ... en cours d'implémentation")
            self.delta_horloge = self.delta_horloge_ini


    def OK_Sync_Next_Step_clicked(self):
        """Method called when the 'OK' button is clicked.

        Updating dictionary data based on changes made by the user in free fields.
        Sends data ( validate_answer ) to Main_Window of Interactive_Main
        To do this, use the emission of a signal (data_signal.emit() )

        """
        try:
            self.time_line_img_NIR()     # Calcul de la time line
            self.pairs_VIS_NIR()         # Appariment des images VIS et NIR
            self.geo_data()              # Calcul des données géographiques (coordonnées UTM, altitudes, cap, distances)

            print("TEST  0136.DNG ", self.Fly[16])
            print("TEST  0137.DNG ", self.Fly[17])
            print("TEST  0138.DNG ", self.Fly[18])

            # construit une première version de la liste des points de prise de vue (class ShootPoint)
            list_Pts = self.build_list_shooting_point()
            # Writing list dictionnary FLY/ShootPoint
            self.save_shooting_point(list_Pts)

            # Fin du preprocess de  préparation des données
            validate_answer = True
            self.data_signal_from_dialog_synchro_clock_to_main_window.emit(validate_answer)
            txt_msg = f"La synchronisation des time-line a bien été prise en compte ...\n" \
                      f"Le décalage des horloges est égal à {self.delta_horloge} s\n" \
                      f"Les images visible et proche infrarouge ont été appariées\n" \
                      f"Les angles de projection de l'image proche infrarouge sur l'image visible ont été calculés"
            Uti.show_info_message("IRDrone", txt_msg, "Vous pouvez lancer le processus de traitement de vos images")

            self.close()
        except Exception as e:
            print("error in Dialog_synchro_clock ok_clicked: ", e)


    def build_list_shooting_point(self) -> list[dict]:
        """
         Construit une version partielle de shoot point  avant le calcul des angles d'alignement.
         A ce stade les informations sont stockées dans le dictionnaire Fly
         La méthode loadDicPointFly2Point de class ShootPoint permet de transferer le dictionnaire Fly dans
         la stucture de données de class ShootPoint.

         Note: La Class ShootPoint a été introduite dès la version primitive d'IRDrone. On assure donc ici la passerelle entre
         cette version primitive et la version interactive.
          Il existe aussi la méthode loadDicPoint2Point de class ShootPoint. Elle est grandement similaire à la précédente.
          Toutefois la structure du dictionnaire est différente (arbre de clés et sous clés). De plus certain noms de clé différent
        du nom de clé de la version interactive.
          Pour cette structure en arbre il existe aussi le méthode loadPoint2DicPoint de class ShootPoint. Elle permet de transférer
        la structure de donnée de class ShootPoint au dictionnaire en arbre  (opération inverse de la précédente).

        :return: list_Pts    liste des dictionnaires des points de prises de vues (class ShootPoint)
        """
        list_Pts = []
        self.Fly = sorted(self.Fly, key=lambda x: int(x['Vis Shooting Number']))

        for index in range(len(self.Fly)):
            pt = ClassPt.ShootPoint()
            self.Fly[index]['Fly Shooting Number'] = index
            self.tempo_1(index)
            pt.loadDicPointFly2Point(self.Fly[index])
            if True: print(pt)  # "TEST"
            list_Pts.append(pt)

        return list_Pts


    def tempo_1(self, index):
        """
        Ces données ne sont pas encore calculées à ce stade mais elles doivent être initialisées pour pouvoir construire
        le point de class ShootPoint
        :param index:
        :return:
        """
        self.Fly[index]['Best Synchro'] = 10
        self.Fly[index]['Best Mapping'] = 11
        self.Fly[index]['Best Offset'] = 12
        self.Fly[index]['x_1'] = 1.
        self.Fly[index]['x_2'] = 2.
        self.Fly[index]['x_3'] = 3.
        self.Fly[index]['Yaw IR to VI'] = 0.
        self.Fly[index]['Pitch IR to VI'] = 0.
        self.Fly[index]['Roll IR to VI'] = 0.
        self.Fly[index]['Yaw Coarse Align'] = 0.
        self.Fly[index]['Pitch Coarse Align'] = 0.
        self.Fly[index]['Roll Coarse Align'] = 0.
        self.Fly[index]['Alignment'] = 1


    def save_shooting_point(self, list_Pts):
        print("TEST   save_shooting_point .... EN DEVELOPPEMENT ")


    def time_line_img_NIR(self):
        """
        1) Construit la time line des images NIR en la synchronisant à la time line des images VIS.
        Attention cela ne signifie pas que les images NIR elles mêmes sont synchronisées avec les images VIS.
        Il y aura toujours un petit décalage (qui n'est pas constant).
        Ce décalage est inhérent au design du système "low coast" de caméra NIR SJCam M20 dont le déclenchement
        n'est pas synchronisé avec celui de la caméra VIS du drone DJI.

        2) Débute la construction de liste des dictionnaires contenant le résumé des informations essentielles sur les images du vol.
        Ce résumé donne pour chaque image VIS prise lors du survol de la zone à étudier:
            - Le numéro de la prise de vue VIS dans le spectre visible (depuis le décollage).
            - Sa position sur la time line
            - L'image NIR dans le spectre proche infrarouge  temporellement la plus proche.
            - l'écart temporel entre les deux images (positif ou négatif).
            - La position GPS de la prise de vue de l'image VIS  (fournie par les données exif de l'image VIS au format dng  prise par le drone).
            - L'attitude du drone et du gimbal au moment de cette prise de vue.
              Les angles {yaw, pitch, roll} du gimbal et du drone sont affectés respectivement aux caméras VIS et NIR.
              Attention : Le yaw gimbal et drone correspondent respectivement au roll caméra VIS et NIR.
                          Le roll  gimbal et drone correspondent respectivement au yaw caméra VIS et NIR.
                          Le pitch gimbal et drone correspondent respectivement au pitch caméra VIS et NIR.

        :return:
        """
        try:
            origine_date_py: datetime = self.origine_date_VIS()
            self.Fly: list[dict[str, any]] = []

            for index, dic in enumerate(self.list_dic_exif_xmp):
                if dic['File Name'].split(".")[1].lower() == "raw":
                    date_time_temp: datetime = Uti.datetimeJson2datetimePy(dic['Date/Time Original'])
                    time_line_NIR: float = (date_time_temp - origine_date_py).total_seconds() - self.delta_horloge
                    self.list_dic_exif_xmp[index]['Time Line'] = time_line_NIR

                elif dic['File Name'].split(".")[1].lower() == "dng":
                    dicVis = { }
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
                        #  signe de l'écart :
                        # si t_VIS < t_NIR <=> ecart < 0   l'image NIR a été prise après l'image VIS
                        # si t_VIS > t_NIR <=> ecart > 0   l'image NIR a été prise avant l'image VIS
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

                # Print pour TEST
                if self.pref_screen.verbose:
                    # fTimeLine = Uti.format_nombre(self.Fly[indexVis]['Vis Time Line'], decimal=2)
                    # fDt = Uti.format_nombre(self.Fly[indexVis]['Dt Vis-Nir'], car="+")
                    # print(f"TEST  {self.Fly[indexVis]['Vis File Name']} |  {self.Fly[indexVis]['Nir File Name']} | {fTimeLine} s | {fDt} s")
                    pass

        except Exception as e:
            print("error in  pairs_VIS_NIR ", e)


    def geo_data(self):
        """
        Complete les dictionnaire de points de prise de vue
             > Coordonnées UTM
             > Distance et cap au point suivant
             > Cumul de distance
             > Altitude géographique du terrain (par rapport au niveau de la mer via IGN)

        :return:
        """

        for i in range(len(self.Fly)):
            self.Fly[i]['X UTM'], self.Fly[i]['Y UTM'], self.Fly[i]['Zone UTM'] = Geo.geo2UTM(self.Fly[i]['Drone Latitude'],  self.Fly[i]['Drone Longitude'])

        for i in range(len(self.Fly) - 1):
            self.Fly[i]['Dist To Next Pt'], self.Fly[i]['Cape To Next Pt'] = Geo.segmentUTM(self.Fly[i]['Drone Latitude'], self.Fly[i]['Drone Longitude'], self.Fly[i + 1]['Drone Latitude'], self.Fly[i + 1]['Drone Longitude'])
        self.Fly[-1]['Dist To Next Pt'], self.Fly[-1]['Cape To Next Pt'] = 0, 0

        cumul = 0
        self.Fly[0]['Dist Cumul'] = cumul
        for i in range(1, len(self.Fly)):
            cumul = cumul + self.Fly[i]['Dist To Next Pt']
            self.Fly[i]['Dist Cumul'] = cumul

        altitude = Geo.altitude_IGN([(self.Fly[i]['Drone Latitude'], self.Fly[i]['Drone Longitude']) for i in range(len(self.Fly))], bypass=False)
        altitudeTakeOff = self.altitude_take_off()
        print("TEST  altitudeTakeOff/ground ", altitudeTakeOff, " m")
        for i in range(len(self.Fly)):
            self.Fly[i]['Altitude Ground/Sea level'] = altitude[i]
            self.Fly[i]['Altitude Drone/Ground'] = self.Fly[i]['Altitude Drone/TakeOff'] + altitudeTakeOff - self.Fly[i]['Altitude Ground/Sea level']


    def origine_date_VIS(self) -> datetime:
        config_file = Path(self.folderMissionPath, 'config.json')
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                origine_date_py = datetime.strptime(dic_config['Date Exif'], "%Y:%m:%d %H:%M:%S")
        else:
            origine_date_py = None
        return origine_date_py


    def altitude_take_off(self) -> float:
        config_file = Path(self.folderMissionPath, 'config.json')
        if config_file.exists():
            with open(config_file, "r") as fi:
                dic_config = json.load(fi)
                altitudeTakeOff = float(dic_config['GPS alti'])
        else:
            altitudeTakeOff = 0.
        return altitudeTakeOff


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        try:
            self.close()
        except Exception as e:
            print("Error in Calss Windows_2 cancel_clicked", e)


    def help_clicked(self):
        """Méthode appelée lorsque le bouton 'Help' est cliqué."""
        # Afficher un message d'aide
        Uti.show_info_message("IRDrone", "En cours d'implémentation ...", "")
        pass




