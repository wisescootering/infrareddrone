# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Main window of the interactive IRDrone GUI
#   7/10/2023   V001
# ---------------------------------------------------------------------------------


import os
import sys
# ------------------PyQt6 Library -----------------------------------
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,  QWidget, QPushButton, QLabel, QFrame, QProgressBar, QDialog, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor, QIcon
# -------------- IRDrone Library ------------------------------------
from IRD_Interactive_1 import Window_11, Window_12
from IRD_Interactive_2 import LoadVisNirImagesDialog
from IRD_Interactive_3 import Window_21
import IRD_interactive_utils as Uti
from IRD_interactive_utils import Prefrence_Screen



class Main_Window(QMainWindow):

    def __init__(self):
        """
        Initialize the Main_Window.

        Initialize the main window of the application.

        """
        super().__init__()
        self.dic_takeoff: dict = None

        self.prefrence_screen = Prefrence_Screen()
        self.dic_takeoff_light: dict = {"key": "value"}
        self.dic_takeoff: dict = None
        self.initGUI()


    def initGUI(self):
        self.image_display_size: tuple[int, int] = (500, 500)   # Size of the log image displayed in the main window.

        # self.location_info = None

        self.setStyleSheet("background-color: white; color: black;")
        self.def_app_dir = self.prefrence_screen.default_app_dir
        self.def_user_dir = self.prefrence_screen.default_user_dir

        # Définir la disposition et les widgets
        # Créer le widget central
        #   Setting the top bar and window dimensions.
        self.setWindowTitle("IRdrone interactive v01")
        icon_path = os.path.join(self.prefrence_screen.default_app_dir, "Icon", "IRDrone.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            QApplication.setWindowIcon(icon)  # Set the applicable icon in the class.

        width = self.prefrence_screen.windowDisplaySize[0]   # Main window width
        height = self.prefrence_screen.windowDisplaySize[1]  # Main window height
        self.setGeometry(0, 0, width, height)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        #self.central_widget.setStyleSheet("background-color: black;")
        self.main_layout = QVBoxLayout(self.central_widget)


        # Creating the command bar
        self.btn_create_mission = QPushButton("Step 1 : Define the mission", self)
        self.btn_create_mission.setStyleSheet("background-color: darkBlue; color: white;")
        self.btn_load_images = QPushButton("Step 2 : Choice of reference image set.", self)
        self.btn_load_images.setAutoDefault(False)
        self.btn_load_images.setEnabled(False)
        self.btn_load_images.setStyleSheet("background-color: Gray; color: darkGray;")

        self.btn_pre_process_images = QPushButton("Step 3 : Image pre-processing", self)
        self.btn_pre_process_images.setStyleSheet("background-color: darkGray; color: white;")
        self.btn_process_images = QPushButton("Step 4 : Image processing", self)
        self.btn_process_images.setStyleSheet("background-color: darkRed; color: white;")
        self.btn_help = QPushButton("Help", self)
        self.btn_help.setStyleSheet("background-color: darkGreen; color: white;")
        self.btn_help.setFixedWidth(60)

        self.btn_create_mission.clicked.connect(self.open_window_11)
        self.btn_load_images.clicked.connect(self.open_window_21)
        self.btn_pre_process_images.clicked.connect(self.on_pre_process_images)
        self.btn_process_images.clicked.connect(self.on_process_images)
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
        image_path = os.path.join(self.prefrence_screen.default_app_dir, "Icon", "image_IRdrone_appli.jpg")
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
    # ===================================================================================


    def open_window_11(self):
        """
        Open Window_11.

        Open the Window_11 when the corresponding button is clicked.

        """
        try:
            self.window_11 = Window_11(self)
            self.window_11.show()
            self.dic_takeoff_light = self.window_11.dic_takeoff_light

            self.window_11.btnNextStep.clicked.connect(self.open_window_12)  # Connect Window_12 signal to Main_Window method
        except Exception as e:
            print("Error in Main_Window open_window_11:", e)


    def open_window_12(self):
        """
        Open Window_12.

        Open the Window_12 when called from Window_11.

        """
        self.window_12 = Window_12(self, self.dic_takeoff_light) # Instantiate Window_12
        try:
            self.window_12.data_signal_from_window_12_to_main_window.connect(self.handle_data_from_window_12)
            self.window_12.show()
        except Exception as e:
            print("Error in Main_Window open_window_12:", e)


    def handle_data_from_window_12(self, validate: bool, dic_takeoff: dict):
        """
        Handle data from Window_12.

        Handle data received from Window_12 and close parent windows.

        Args:
            validate (bool): True if the user has validated the entries, False otherwise.
            dic_takeoff (dict): A dictionary containing image_path, location, and pilot data.

        """
        if validate:
            self.dic_takeoff = dic_takeoff
            self.window_12.data_signal_from_window_12_to_main_window.disconnect()  # Disconnect the signal
            self.window_12.close()  # Close window_12
            self.btn_load_images.setAutoDefault(True)
            self.btn_load_images.setEnabled(True)
            self.btn_load_images.setStyleSheet("background-color: Gray; color: White;")
        else:
            print("The user has not validated his entries.")

        self.window_11.close()


    # ===================================================================================
    #                   Button #2 click handlers
    # ===================================================================================

    def open_window_21(self):
        """ load set of VIS and NIR images of he mission. """
        screens = QApplication.screens()
        active_widget = QApplication.activeWindow()
        active_screen_id = QApplication.screens().index(active_widget.screen()) if active_widget else 0
        target_screen_id = screens[active_screen_id]
        screen_geometry = target_screen_id.availableGeometry()
        width = screen_geometry.width() - 20  # width of the window
        height = 500  # height of the window


        # ----------------------- Choice of mission file -------------------------------------------------

        folderMissionPath, coherent_response = self.choose_folder_name()
        if not coherent_response:
            return()

        # ---------------- Loads the 5 reference “VIS” images --------------------------------------------

        if self.dic_takeoff is not None:
            dialog_VIS = LoadVisNirImagesDialog(width, height, "VIS",
                                                                  folderMission=folderMissionPath, path_image_takeoff=self.dic_takeoff["File path take-off"])
        else:
            dialog_VIS = LoadVisNirImagesDialog(width, height, "VIS",
                                                                  folderMission=folderMissionPath)
        result = dialog_VIS.exec()
        if result == QDialog.DialogCode.Accepted:
            print("reference_images VIS")
            pass
        LoadVisNirImagesDialog.reset_flags()

        # ---------------- Loads the 5 reference “NIR” images --------------------------------------------

        dialog_NIR = LoadVisNirImagesDialog(width, height, "NIR", folderMission=folderMissionPath)
        result = dialog_NIR.exec()
        if result == QDialog.DialogCode.Accepted:
            print("reference_images NIR")
            pass
        LoadVisNirImagesDialog.reset_flags()


    def choose_folder_name(self):
        try:
            image_takeoff_available = self.image_takeoff_available_test(self.dic_takeoff['File path mission'])
            if image_takeoff_available:
                # construction du nom du dossier de la mission
                folderMissionPath = self.dic_takeoff['File path mission']
                coherent_response = True
                Uti.show_info_message("IRDrone", f"Your images will be transferred to the  mission folder : \n {folderMissionPath}",
                                      f"They will be distributed between the folders {self.window_12.AerialPhotoFolder} and {self.window_12.SynchroFolder}")
                return folderMissionPath, coherent_response
            else:
                Uti.show_warning_OK_Cancel_message("IRDrone", "Choose the mission folder.", "It is of the form : \n FLY_Year Month Day_hour minute_[Place]", QMessageBox.Icon.Information)
                try:
                    folderMissionPath = QFileDialog.getExistingDirectory(self, 'Select Mission Folder', self.prefrence_screen.default_user_dir)
                    if folderMissionPath and folderMissionPath != self.prefrence_screen.default_user_dir:
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
                    print("error 1   in choose_folder_name :", e)
        except Exception as e:
            print("error 2   in choose_folder_name :", e)


    def image_takeoff_available_test(self, path_image_takeoff):
        try:
            image_takeoff_available = False
            # Test if the takeoff point image is available..
            if path_image_takeoff is not None:
                if os.path.exists(path_image_takeoff):
                    coherent_response = Uti.folder_name_consistency_analysis(path_image_takeoff)
                    if coherent_response:
                        self.path_image_takeoff = path_image_takeoff
                        image_takeoff_available = True
            return image_takeoff_available
        except Exception as e:
            print("error   in image_takeoff_available", e)


    # ===================================================================================
    #                   Button #3 click handlers
    # ===================================================================================
    def on_pre_process_images(self):
        Uti.show_info_message("IRDrone", "En cours d'implémentation ...", "")
        pass

    # ===================================================================================
    #                   Button #4 click handlers
    # ===================================================================================
    def on_process_images(self):
        Uti.show_info_message("IRDrone", "En cours d'implémentation ...", "")
        pass


    # ===================================================================================
    #                   Button #5 click handlers
    # ===================================================================================
    def on_help(self):
        Uti.show_info_message("IRDrone", "En cours d'implémentation ...", "")
        pass


def main():
    """Fonction principale pour exécuter l'application."""
    app = QApplication(sys.argv)
    main_window = Main_Window()
    # Vérifier si main_window est modale ou non
    if main_window.isModal():
        #print("TEST   main_window est une fenêtre modale.")
        pass
    else:
        #print("TEST   main_window n'est pas une fenêtre modale.")
        pass
    screen = Prefrence_Screen()
    Uti.center_on_screen(main_window, screen_Id=screen.defaultScreenID, screen_adjust=screen.screenAdjust, window_display_size=screen.windowDisplaySize)
    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

