# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Creation of the mission by selection of the first image taken by the DJI (visible spectrum, image in dng format)
#   29/10/2023   V002
# ---------------------------------------------------------------------------------


import sys
import os
import shutil
import json
from datetime import date, time, datetime
from typing import Any, Dict, Optional, Tuple, List, Union

# -------------------- Image Library ------------------------------
import rawpy
import imageio
# -------------- PyQt6 Library ------------------------------------
from PyQt6.QtWidgets import QFileDialog, QWidget,  QLineEdit, QFrame,  QPushButton,\
                            QProgressBar, QHBoxLayout,  QVBoxLayout, QLabel, QMessageBox, QDialog
from PyQt6.QtGui import QPixmap, QImage, QColor, QIcon, QRegularExpressionValidator
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression

# -------------- IRDrone Library ------------------------------------
import IRD_interactive_utils as Uti
import IRD_interactive_geo as Geo
from IRD_interactive_utils import Prefrence_Screen

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
        self.prefScreen = Uti.Prefrence_Screen()    # Initializing screen preferences
        self.initGUI()                              # Initializing the GUI
        self.setLayout(self.main_layout)
        self.dic_takeoff_light = dict()
        self.dic_info_geo = dict()
        self.init_dic_takeoff_light()


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
            self.default_app_dir= os.path.join("C:/", "Program Files", "IRdrone") 
            self.default_user_dir = os.path.join("C:/", "Air-Mission")
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
        width =  self.prefScreen.windowDisplaySize[1]    #int(600)
        num_images = 1
        #print("TEST dim Ecran   l x H :", int((width - 100) / num_images), int((width - 100) / num_images * 3 / 4))
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
        self.resize(600, 600)
        Uti.center_on_screen(self, screen_Id=1)


    def init_dic_takeoff_light(self):
        """Initialise une version simplifiée du  dictionnaire self.dic_takeoff_light.

        """
        try:
            self.dic_takeoff_light = {
                "File path": "C:/",
                "Maker": "Nimbus",
                "Model": "Old",
                "Body serial number": "570608",
                "Date Exif": "1900:01:01 12:00:00",
                "Date": '1900-01-01',
                "Time": f"12:00:00",
                "Location": "Paris",
                "Description": "Eiffel tower",
                "GPS coordinate": f"N 48.858370° E 2.294481°",
                "GPS N-S": "N",
                "GPS lat": 48.858370,
                "GPS E-W": "E",
                "GPS lon":  2.294481,
                "GPS alti": 33.5,
                "GPS drone alti": 330
            }
            #print( "TEST   sortie de   init_dic_takeoff       self.dic_takeoff_light  :", self.dic_takeoff_light)
        except Exception as e:
            print('error in init_dic_takeoff', e)


    def placeholder_method(self):
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
        # Ouvrir une boîte de dialogue pour sélectionner une image. Ici on n'admet uniquement des images au format DNG
        # Elles doivent provenir de la caméra du drone qui capture des images dans le spectre visible.
        directory = os.path.abspath('/')   # DD racine
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image", directory, "Images (*.dng)") # (*.png *.xpm *.jpg *.dng)")


        try:
            if file_name:
                self.dic_takeoff_light["File path"] = file_name
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

                # Utilise API IGN (Institut Géographique National. France)  pour obtenir, en fonction des coordonnées GPS, l'altitude géographique.
                # C'est le niveau du sol par rapport au niveau de la mer
                self.dic_info_geo = Geo.extract_alti_IGN([(latitude, longitude)], bypass=False)
                self.progress_bar.setValue(60)
                # Utilise l'API Open Street Map pour obtenir les données géographiques (lieu-dit, ville, code postal, ...)
                self.dic_info_geo = Geo.extract_geoTag(self.dic_info_geo )
                self.progress_bar.setValue(80)
                # Mettre à jour le label d'information avec les données de localisation
                # ... (formatez les données comme vous le souhaitez)
                geo_data = f"Wpt: take-off \n" \
                           f"image: {file_name.lower()}\n" \
                           f"Coordonnées: {round(self.dic_info_geo.get('lat'),6)}°      {round(self.dic_info_geo.get('lon'),6)}°   Alti. {round(self.dic_info_geo.get('z'),3)} m  (above sea level)\n" \
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
            self.dic_takeoff_light['Maker'] = str(maker)
            self.dic_takeoff_light['Model'] = str(model)
            self.dic_takeoff_light['Body serial number'] = str(id_camera)
            self.dic_takeoff_light['Date Exif'] = str(date_time_excif)
            self.py_date_time = datetime.strptime(str(date_time_excif), "%Y:%m:%d %H:%M:%S")
            self.dic_takeoff_light['Location'] = self.dic_info_geo['ville']
            if self.dic_info_geo['lat'] >= 0:
                self.dic_takeoff_light["GPS N-S"] = "N"
            else:
                self.dic_takeoff_light["GPS N-S"] = "S"
            if self.dic_info_geo['lon'] >= 0:
                self.dic_takeoff_light["GPS E-W"] = "E"
            else:
                self.dic_takeoff_light["GPS E-W"] = "W"
            self.dic_takeoff_light["GPS lat"] = self.dic_info_geo['lat']
            if self.dic_info_geo['lon'] <10:
                self.dic_takeoff_light["GPS lon"] = f"00{self.dic_info_geo['lon']}"
            elif 10 <= self.dic_info_geo['lon'] < 10:
                self.dic_takeoff_light["GPS lon"] = f"0{self.dic_info_geo['lon']}"
            else:
                self.dic_takeoff_light["GPS lon"] = f"{self.dic_info_geo['lon']}"

            self.dic_takeoff_light["GPS lon"] = str(self.dic_info_geo['lon'])
            self.dic_takeoff_light["GPS alti"] = str(self.dic_info_geo['z'])
            self.dic_takeoff_light["GPS coordinate"] = f"{self.dic_takeoff_light['GPS N-S']} {str(self.dic_info_geo['lat'])}° {self.dic_takeoff_light['GPS E-W']} {self.dic_info_geo['lon']}°"

            self.dic_takeoff_light["GPS drone alti"] = self.altitude_DJI
        except Exception as e:
            print("error 2 in load_takeoff_image ", e)

        return


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        try:
            self.close()
        except Exception as e:
            print("error in Window_Load_TakeOff_Image   cancel_clicked :", e)


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
            ├── Synchro/
            ├── ImgIRdrone/
            ├── mapping_MULTI/
            └── cameras/
            │       └── camera_IRdrone.json
            ├── FlightAnalytics/
            │       └── HYPERLAPSE_0001.dng      ( first image at the  take-off)
            └── config.json                      ( mission parameters )


    """
    # Creates a class signal to transmit the data to the parent which will here be an instance of the window_11 class
    # Here the return is a boolean (click on OK True or False and the dictionary containing the answers to the questionnaire)
    data_signal_from_dialog_create_file_structure_to_main_window = pyqtSignal(bool, dict)

    def __init__(self, parent, dic_takeoff_light: Dict[str, Any]):
        super().__init__(parent)
        # -----------Name of folders to store mission images. ----------------

        self.pref = Prefrence_Screen()

        self.AerialPhotoFolder: str = self.pref.AerialPhotoFolder  # folder of images taken by VIS and NIR cameras
        self.AnalyticFolder: str = self.pref.AnalyticFolder  # technical folder containing information on the mission
        self.ImgIRdroneFolder: str = self.pref.ImgIRdroneFolder  # folder of images processed by IRDrone
        self.SynchroFolder: str = self.pref.SynchroFolder  # folder for images from the camera synchronization phase
        self.MappingFolder: str = self.pref.MappingFolder  # folder for image assembly with Open Drone Map
        self.CameraFolder: str = self.pref.CameraFolder  # Used by ODM
        self.missionFolder: str = self.pref.directory

        self.dic_takeoff_light: dict = dic_takeoff_light

        self.py_date_time = datetime.strptime(self.dic_takeoff_light['Date Exif'], "%Y:%m:%d %H:%M:%S")
        self.py_date = self.py_date_time.date()
        self.py_time = self.py_date_time.time()

        self.initGUI()


    def initGUI(self):
        """
                 Definition of the user interface
        :return:
        """

        self.setWindowTitle("Create a mission")

        # Layouts
        self.layout = QVBoxLayout(self)
        width: int = 700   # Main window width
        height: int = 500  # Main window height
        self.setGeometry(0, 0, width, height)

        # ---------------- init field of takeoff point -------------
        self.init_fields()
        self.update_dic_takeoff()

        self.zone_121 = QWidget()
        self.layout.addWidget(self.zone_121)

        self.zone_122 = QWidget()
        self.layout.addWidget(self.zone_122)

        self.btn_1221 = QPushButton("Validate create mission.")
        self.btn_1221.setStyleSheet("background-color: darkGray; color: black;")
        self.btn_1222 = QPushButton("<< previous step")
        self.btn_1222.setStyleSheet("background-color: darkGray; color: black;")

        self.zone_122.layout = QHBoxLayout()
        self.zone_122.layout.addWidget(self.btn_1222)
        self.zone_122.layout.addWidget(self.btn_1221)
        self.zone_122.setLayout(self.zone_122.layout)

        self.btn_1221.clicked.connect(self.ok_clicked)
        self.btn_1222.clicked.connect(self.cancel_clicked)

        self.focus_sequence()
        Uti.center_on_screen(self, screen_Id=1)
        self.setStyleSheet("background-color: white; color: black;")


    def ok_clicked(self):
        """Method called when the 'OK' button is clicked.

        Updating dictionary data based on changes made by the user in free fields.

        Creates the main mission folder (FLY_date_time_place) and the folder structure in the main folder
         >AerialPhotography, FlightAnalytics, ImgIRdrone, Synchro, mapping_MULTI, cameras

         Save the dictionary in a json file placed in the main folder.

        Sends data ( validate_answer & self.dic_takeoff ) to Main_Window of Interactive_Main
        To do this, use the emission of a signal (data_signal.emit() )

        """
        try:
            self.update_dic_takeoff()
            self.validate_answer = True
            self.create_mission_folder()
            self.data_signal_from_dialog_create_file_structure_to_main_window.emit(self.validate_answer, self.dic_takeoff)
            self.close()
        except Exception as e:
            print("error in Window_create_file_structure ok_clicked: ", e)


    def cancel_clicked(self):
        """Méthode appelée lorsque le bouton 'Cancel' est cliqué."""
        try:
            self.close()
        except Exception as e:
            print("error in Window_create_file_structure  cancel_clicked  ", e)


    def focus_sequence(self):
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


    def init_fields(self):
        """
        Initializes takeoff point data fields.
        The Date, Time, GPS coordinates and Location fields are pre-populated.
        They are extracted from the Exif data of the image taken at takeoff.
        These fields cannot be modified by the user (setReadOnly(True),
        with the exception of the location field (setReadOnly(False).
        """
        # ---------------- date field-------------------------------
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
            print("error in init_fields   date field : ", e)

        # ---------------- time  field  -------------------------------
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
            print("error in init_fields   time field : ", e)

        # ------------------- Location field -------------------------
        try:
            self.location_label = QLabel("Location :")
            self.location_field = QLineEdit(self)
            self.location_field.setText(self.dic_takeoff_light['Location'])
            self.location_field.setStyleSheet(
                "background-color: white; "
                "color: black; "
                "font-family: 'Comic Sans MS'; "
                "font-size: 12pt; "
                "font-weight: bold; "
                "font-style: italic;"
            )
            self.location_field.setReadOnly(False)
        except Exception as e:
            print("error in init_fields   Location field : ", e)

        self.location_layout = QHBoxLayout()
        self.location_layout.addWidget(self.location_label)
        self.location_layout.addWidget(self.location_field)
        self.layout.addLayout(self.location_layout)


        # ----------------  GPS field -------------------------------

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
            lat_takeoff = f"{self.dic_takeoff_light['GPS N-S']} {str(self.dic_takeoff_light['GPS lat'])}"
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
            if float(self.dic_takeoff_light['GPS lon']) < 10:
                str_longitude = f"00{str(self.dic_takeoff_light['GPS lon'])}"
            elif 10 <= float(self.dic_takeoff_light['GPS lon']) < 100:
                str_longitude = f"0{str(self.dic_takeoff_light['GPS lon'])}"
            else:
                str_longitude = f"{str(self.dic_takeoff_light['GPS lon'])}"

            lon_takeoff = f"{self.dic_takeoff_light['GPS E-W']} {str_longitude}"
            self.GPS_lon_field.setText(lon_takeoff)
        except Exception as e:
            print("error in init_fields   GPS field  : ", e)

        self.GPS_alti = str(self.dic_takeoff_light['GPS alti'])

        self.GPS_layout = QHBoxLayout()
        self.GPS_layout.addWidget(self.GPS_label)
        self.GPS_layout.addWidget(self.GPS_lat_field)
        self.GPS_layout.addWidget(self.GPS_lon_field)
        self.layout.addLayout(self.GPS_layout)


        # ------------------- Description --------------------------------
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


        # ------------- Pilot imput --------------------------------------
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

        # ------------- VIS camera input ---------------------------------

        try:
            # camera VIS part 1
            self.camera_VIS_maker: str = self.dic_takeoff_light["Maker"]
            self.camera_VIS_ID: str = self.dic_takeoff_light["Model"]

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
            self.image_VIS_format: str = os.path.splitext(self.dic_takeoff_light["File path"])[1][1:]
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
            print("error --init-- camera Vis", e)

        # ------------- NIR camera input ---------------------------------------

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

            # camera NIR part 2
            self.camera_NIR_timelaspe: int = 3           # in second
            self.camera_NIR_deltatime: float = 3894.91     # in second

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

            # camera NIR part 3
            self.image_NIR_format: str = "RAW"
            self.image_NIR_format_label = QLabel("Image NIR format:")
            self.image_NIR_format_field = QLineEdit(self)
            self.image_NIR_format_field.setText(self.image_NIR_format)

            self.image_NIR_format_layout = QHBoxLayout()
            self.image_NIR_format_layout.addWidget(self.image_NIR_format_label)
            self.image_NIR_format_layout.addWidget(self.image_NIR_format_field)
            self.layout.addLayout(self.image_NIR_format_layout)

            # camera NIR part 4
            self.image_NIR_filter_maker: str = "KOLARI VISION USA"
            self.image_NIR_filter_band: int = 810

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
            print("error --init-- camera NIR", e)


    def update_dic_takeoff(self):
        """Initialise le dictionnaire self.dic_takeoff.

        First checks the validity of the data (date, time, GPS coordinates, etc.)
        """

        self.fields_consistency_analysis()
        self.missionFolder = self.build_mission_folder_name()
        try:

            self.dic_takeoff = {
                "File path mission": self.missionFolder,
                "File path take-off": self.dic_takeoff_light["File path"],
                "Body serial number": self.dic_takeoff_light["Body serial number"],
                "Date Exif": f"{Uti.datePy2dateJson(self.py_date)} {Uti.timePy2timeJson(self.py_time)}",
                "Date": Uti.datePy2dateJson(self.py_date),
                "Time": Uti.timePy2timeJson(self.py_time),
                "Location": self.location_field.text(),
                "Description": self.description_field.text(),
                "GPS coordinate": f"{self.GPS_NS} {str(self.GPS_lat)}° {self.GPS_EW} {str(self.GPS_lon)}°",
                "GPS N-S": self.GPS_NS,
                "GPS lat": float(self.GPS_lat),
                "GPS E-W": self.GPS_EW,
                "GPS lon":  float(self.GPS_lon),
                "GPS alti": float(self.GPS_alti),
                "GPS drone alti": self.dic_takeoff_light["GPS drone alti"],
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
                "img NIR ext": self.image_NIR_format_field.text(),
                "camera NIR filter maker": self.image_NIR_filter_maker_field.text(),
                "camera NIR filter band": int(self.image_NIR_filter_band_field.text()),
                "synchro": "Synchro/synchro.npy",
                "output": "ImgIRdrone",
                "visible": "AerialPhotography/*.DNG",
                "visible_timelapse": round(float(self.camera_VIS_tlapse_field.text())*10)/10,
                "nir": "AerialPhotography/*.RAW",
                "nir_timelapse": round(float(self.camera_NIR_tlapse_field.text())*10)/10,
                "AerialPhotography folder": self.AerialPhotoFolder,
                "FlightAnalytics folder": self.AnalyticFolder,
                "ImgIRdrone folder": self.ImgIRdroneFolder,
                "Synchro folder": self.SynchroFolder,
                "ODM folder": self.MappingFolder,
                "cameras folder": self.CameraFolder
            }
        except Exception as e:
            print('error in update_dic_takeoff ', e)


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


    def build_mission_folder_name(self):
        try:
            # Create mission folder
            # Convert date and time objects to strings
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

        # Create mission folder
        directory = self.build_mission_folder_name()
        try:
            if not os.path.exists(directory):
                os.makedirs(directory)
                os.makedirs(os.path.join(directory, self.AerialPhotoFolder))
                os.makedirs(os.path.join(directory, self.AnalyticFolder))
                os.makedirs(os.path.join(directory, self.ImgIRdroneFolder))
                os.makedirs(os.path.join(directory, self.SynchroFolder))
                os.makedirs(os.path.join(directory, self.MappingFolder))
                os.makedirs(os.path.join(directory, self.CameraFolder))

                try:
                    change_ico = True
                    dir_ico = os.path.join(self.pref.default_app_dir, "Icon")
                    if change_ico:
                        self.change_icon(directory, os.path.join(dir_ico, "IRdrone_appli.ico"))
                        self.change_icon(os.path.join(directory, self.AerialPhotoFolder), os.path.join(dir_ico, "AerialPhoto.ico"))
                        self.change_icon(os.path.join(directory, self.AnalyticFolder), os.path.join(dir_ico, "FlyAnalytic.ico"))
                        self.change_icon(os.path.join(directory, self.ImgIRdroneFolder), os.path.join(dir_ico, "ImgIRdrone.ico"))
                        self.change_icon(os.path.join(directory, self.SynchroFolder), os.path.join(dir_ico, "synchro.ico"))
                        self.change_icon(os.path.join(directory, self.MappingFolder), os.path.join(dir_ico, "mapping_MULTI.ico"))
                        self.change_icon(os.path.join(directory, self.CameraFolder), os.path.join(dir_ico, "camera.ico"))
                except Exception as e:
                    print("error. in create_mission_folder   change icon :", e)
                    pass
        except Exception as e:
            print("error. in create_mission_folder   creating folder tree :", e)

        try:
            # Save to JSON file
            with open(os.path.join(directory, "config.json"), "w") as file:
                json.dump(self.dic_takeoff, file, ensure_ascii=False, indent=4)

            txt_Date = str(self.py_date_time.year) + str(self.py_date_time.month) + str(self.py_date_time.day)
            txt_Time = str(self.py_date_time.hour) + str(self.py_date_time.minute)
            txt_comment = str(self.dic_takeoff['Location'])
            Uti.show_info_message("IRDrone", "Mission has been successfully created, ", 
                                  f"in the folder :   \n"
                                  f"FLY_{txt_Date}_{txt_Time}_{txt_comment}")

            self.accept()  # Close the form    alternative   self.close()
        except Exception as e:
            print("error  in create_mission_folder   save JSON  :", e)


    def change_icon(self, folder_path, file_path):
        if not folder_path:  # choice of the target folder whose icon will be changed
            print("No folder selected or operation canceled.")
            exit()
        if not os.path.exists(folder_path):
            print("folder ", folder_path, " not exist.")
            exit()
        try:  # Checking if the folder is editable
            temp_file = os.path.join(folder_path, 'temp.txt')
            with open(temp_file, 'w') as f:
                f.write('test')
            os.remove(temp_file)
        except PermissionError:
            print("The selected folder cannot be edited.")
            exit()

        try:
            if not file_path:  # Checking the path to the ico file
                print("No .ico file selected or operation canceled.")
                exit()
            if not os.path.exists(file_path):
                print("file icon ", file_path, " not exist.")
                exit()
        except Exception as e:
            print("error icon file : ", e)

        # Copies the desktop.ini file from a temporary location
        desktop_ini_path = os.path.join(folder_path, 'desktop.ini')

        # Creates a desktop.ini file with the custom icon in a temporary location
        temp_desktop_ini_path = os.path.join(os.path.expanduser("~"), 'temp_desktop.ini')
        with open(temp_desktop_ini_path, 'w') as desktop_ini:
            desktop_ini.write('[.ShellClassInfo]\n')
            desktop_ini.write('IconResource={},0\n'.format(file_path))

        # Copy file from temporary location to target folder
        shutil.copy(temp_desktop_ini_path, desktop_ini_path)

        # Mark the folder as system for the custom icon to be used
        os.system(f'attrib +s "{folder_path}"')

        # print(f"Folder icon {folder_name} has been successfully replaced.")

        return
