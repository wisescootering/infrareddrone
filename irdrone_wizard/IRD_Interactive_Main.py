# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   Main window of the interactive IRDrone GUI
#   10/09/2026   V003
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
    QMessageBox,
    QDialog,
)
from PyQt6.QtCore import Qt, QLoggingCategory
from PyQt6.QtGui import QPixmap, QColor, QIcon, QPainter, QFont
from PyQt6.QtWidgets import QSplashScreen

print("IRDrone is starting, waiting ...", flush=True)


def _make_splash() -> QSplashScreen:
    """Small start-up window shown while the heavy modules are imported."""
    pix = QPixmap(420, 130)
    pix.fill(QColor("#2b2b2b"))
    painter = QPainter(pix)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
    painter.drawText(pix.rect().adjusted(0, 15, 0, 0), Qt.AlignmentFlag.AlignHCenter, "IRDrone")
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(pix.rect().adjusted(0, 0, 0, -20), Qt.AlignmentFlag.AlignCenter, "Loading, please wait ...")
    painter.end()
    return QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)


# Windows: Qt 6 prints "DirectWrite: CreateFontFaceFromHDC() failed ... 8514oem"
# when it meets the old bitmap fonts of the system while looking for a font.
# Harmless (the text is drawn with another font): hide these font warnings.
# QT_LOGGING_RULES=qt.qpa.fonts.warning=true shows them again.
QLoggingCategory.setFilterRules("qt.qpa.fonts.warning=false")

# The QApplication must exist before the splash screen can be displayed
_app = QApplication.instance() or QApplication(sys.argv)
_splash = _make_splash()
_splash.show()
_app.processEvents()

# -------------- IRDrone Library ------------------------------------
from IRD_Interactive_1 import Window_Load_TakeOff_Image, Window_create_file_structure
from IRD_Interactive_2 import LoadVisNirImagesDialog
from IRD_Interactive_3 import DialogSynchroAruco
from IRD_Interactive_4 import DialogImageProcessing
from IRD_Interactive_5 import DialogGeoRef
from IRD_Interactive_6 import DialogArchive
from IRD_Interactive_styles import colored_button_style, BUTTON_STYLE
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import Prefrence_Screen
from IRD_Interactive_color_style import Style
import config
from config import missing_tools_message
import IRD_Interactive_help as Help
from IRD_Interactive_workdir import MissionLabel, WorkingDirBar, ensure_working_dir_at_startup
import IRD_Interactive_progress as Progress


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
        self.btn_post_process_images = None
        self.btn_archive = None
        self.btn_help = None
        self.nb_btn = 6
        self.btn_width = int(self.pref_screen.windowDisplaySize[0] / self.nb_btn) - 10
        self.command_layout = None
        self.image_label = QLabel(self)
        self.empty_pixmap = QPixmap(100, 100)
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
        self.btn_create_mission = QPushButton("Step 1\nDefine the mission", self)
        self.btn_create_mission.setStyleSheet(colored_button_style("darkGreen"))
        self.btn_create_mission.setFixedWidth(self.btn_width)
        self.btn_create_mission.setMinimumHeight(56)
        self.btn_create_mission.clicked.connect(self.open_window_define_mission)
        #  btn load_images
        self.btn_load_images = QPushButton("Step 2\nSelect reference images", self)
        self.btn_load_images.setAutoDefault(True)
        self.btn_load_images.setEnabled(True)   # (True) pour test  et (False) en prod !
        self.btn_load_images.setStyleSheet(colored_button_style("purple"))
        self.btn_load_images.setFixedWidth(self.btn_width)
        self.btn_load_images.setMinimumHeight(56)
        self.btn_load_images.clicked.connect(self.open_window_load_set_images)
        #  btn pre_process_images
        self.btn_pre_process_images = QPushButton("Step 3\nImage pre-processing", self)
        self.btn_pre_process_images.setStyleSheet(colored_button_style("#505050"))
        self.btn_pre_process_images.setFixedWidth(self.btn_width)
        self.btn_pre_process_images.setMinimumHeight(56)
        self.btn_pre_process_images.clicked.connect(self.on_pre_process_images)
        #  btn process_images
        self.btn_process_images = QPushButton("Step 4\nImage processing", self)
        self.btn_process_images.setStyleSheet(colored_button_style("darkRed"))
        self.btn_process_images.setFixedWidth(self.btn_width)
        self.btn_process_images.setMinimumHeight(56)
        self.btn_process_images.clicked.connect(self.on_process_images)
        #  btn post process_images
        self.btn_post_process_images = QPushButton("Step 5\nImage post-processing", self)
        self.btn_post_process_images.setStyleSheet(colored_button_style("#C87800"))
        self.btn_post_process_images.setFixedWidth(self.btn_width)
        self.btn_post_process_images.setMinimumHeight(56)
        self.btn_post_process_images.clicked.connect(self.on_post_process_images)
        #  btn archive
        self.btn_archive = QPushButton("Step 6\nArchive the mission", self)
        self.btn_archive.setStyleSheet(colored_button_style("#2E5C8A"))
        self.btn_archive.setFixedWidth(self.btn_width)
        self.btn_archive.setMinimumHeight(56)
        self.btn_archive.clicked.connect(self.on_archive_mission)
        #  btn help (bottom right of the window)
        self.btn_help = QPushButton("?", self)
        self.btn_help.setStyleSheet(BUTTON_STYLE)
        self.btn_help.setFixedWidth(30)
        self.btn_help.clicked.connect(self.on_help)

        # Step buttons: (button, text, color) to grey them out once the step is done
        self.step_buttons = {
            1: (self.btn_create_mission, "Step 1\nDefine the mission", "darkGreen"),
            2: (self.btn_load_images, "Step 2\nSelect reference images", "purple"),
            3: (self.btn_pre_process_images, "Step 3\nImage pre-processing", "#505050"),
            4: (self.btn_process_images, "Step 4\nImage processing", "darkRed"),
            5: (self.btn_post_process_images, "Step 5\nImage post-processing", "#C87800"),
            6: (self.btn_archive, "Step 6\nArchive the mission", "#2E5C8A"),
        }
        Progress.notifier.changed.connect(lambda _folder: self._show_current_mission())

        # Layout for command bar
        self.command_layout = QHBoxLayout()
        self.command_layout.addWidget(self.btn_create_mission)
        self.command_layout.addWidget(self.btn_load_images)
        self.command_layout.addWidget(self.btn_pre_process_images)
        self.command_layout.addWidget(self.btn_process_images)
        self.command_layout.addWidget(self.btn_post_process_images)
        self.command_layout.addWidget(self.btn_archive)

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

        # Bottom bar: working folder + gear (left), help button (right)
        bottom_layout = QHBoxLayout()
        self.working_dir_bar = WorkingDirBar(self)
        self.working_dir_bar.changed.connect(self._on_working_dir_changed)
        bottom_layout.addWidget(self.working_dir_bar)
        bottom_layout.addSpacing(30)
        # Current mission (defined in Step 1, or chosen when opening another step)
        self.mission_label = MissionLabel(self)
        bottom_layout.addWidget(self.mission_label)
        self.btn_open_mission = QPushButton("Change mission...", self)
        self.btn_open_mission.setStyleSheet(BUTTON_STYLE)
        self.btn_open_mission.setToolTip("Switch to another existing mission folder (FLY-YYYYMMDD-hhmm-location)")
        self.btn_open_mission.clicked.connect(self.on_open_mission)
        bottom_layout.addWidget(self.btn_open_mission)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_help)
        self.main_layout.addLayout(bottom_layout)

        for widget, label, tip in (
            (self.btn_create_mission, "ch:step1", "Define the mission and transfer the images."),
            (self.btn_load_images, "ch:step2", "Select the reference images."),
            (self.btn_pre_process_images, "ch:step3", "Synchronize the VIS and NIR cameras."),
            (self.btn_process_images, "ch:step4", "Align the VIS and NIR images."),
            (self.btn_post_process_images, "ch:step5", "Georeference, map and build the DTM."),
            (self.btn_archive, "ch:step6", "Archive the mission (cleans the mission folder)."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

    def _on_working_dir_changed(self, folder):
        """New working folder chosen with the gear button."""
        self.pref_screen.default_user_dir = folder
        self.def_user_dir = folder
        print(f"Working folder: {folder}")

    def _show_current_mission(self):
        """Refresh the mission shown at the bottom of the window and the step buttons."""
        self.mission_label.set_mission(self.mission_parameters, self.folderMissionPath)
        self._show_done_steps()

    def _show_done_steps(self):
        """Grey out the steps done for the current mission, with a check mark.
        They stay clickable (a step can be run again)."""
        folder = Progress.mission_folder(self.mission_parameters, self.folderMissionPath)
        done = Progress.done_steps(folder)
        for step, (button, text, color) in self.step_buttons.items():
            if step in done:
                button.setText("\u2705 " + text)
                button.setStyleSheet(colored_button_style("#A9A9A9"))
                button.setToolTip(f"Done ({done[step].replace('T', ' ')}). Click to run it again.")
            else:
                button.setText(text)
                button.setStyleSheet(colored_button_style(color))
                button.setToolTip("")

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
            Progress.mark_step_done(self.folderMissionPath, 1)
            self._show_current_mission()
            self.dialog_create_file_structure.data_signal_from_dialog_create_file_structure_to_main_window.disconnect()  # Disconnect the signal
            self.dialog_create_file_structure.close()  # Close dialog_create_file_structure
            self.btn_load_images.setAutoDefault(True)
            self.btn_load_images.setEnabled(True)
            self._show_done_steps()  # Step 2 keeps its color, or its check mark if already done
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
        # The current mission (Step 1, "Change mission..." or another step) is used
        # directly: the folder is only asked when no mission is loaded yet.
        try:
            if not self.ensure_mission_parameters():
                return
            folderMissionPath = Path(Progress.mission_folder(self.mission_parameters, self.folderMissionPath))
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

        vis_loaded = dialog_VIS.exec() == QDialog.DialogCode.Accepted
        dialog_VIS.reset_flags()
        # ---------------- Loads the 5 reference “NIR” images --------------------------------------------
        dialog_NIR = LoadVisNirImagesDialog(width,
                                            height,
                                            spectral_band="NIR",
                                            suffix="dng",
                                            folderMission=folderMissionPath,
                                            path_image_takeoff=self.pathImageTakeoff)
        nir_loaded = dialog_NIR.exec() == QDialog.DialogCode.Accepted
        dialog_NIR.reset_flags()
        if vis_loaded and nir_loaded:
            Progress.mark_step_done(folderMissionPath, 2)



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
            self.dialog_synchro_aruco = DialogSynchroAruco(
                self.mission_parameters,
                parent=self,
            )
            self.dialog_synchro_aruco.data_signal_to_main.connect(
                self.handle_data_from_dialog_synchro_aruco
            )
            self.dialog_synchro_aruco.show()

        except Exception as e:
            print("Error in  class Main_Window(QMainWindow)   in on_pre_process_images     opening Dialog_Synchro_Aruco:", e)

    def handle_data_from_dialog_synchro_aruco(self, validate: bool):
        if validate:
            print(Style.GREEN + "✔   Step 3 completed successfully." + Style.RESET)
        else:
            print(Style.YELLOW + "⚠  Step 3 cancelled by user." + Style.RESET)



    # ===================================================================================
    #                   Button #4 click handlers
    #     Step 4 process images
    # ===================================================================================


    def on_process_images(self):
        if not self.ensure_mission_parameters():
            return

        try:
            self.dialog_image_processing = DialogImageProcessing(
                self.mission_parameters, self
            )
            self.dialog_image_processing.show()
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(
                self,
                "Image processing unavailable",
                str(e),
            )

    # ===================================================================================
    #                   Button #5 click handlers
    #     Step 5 post process images.  Georef, etc
    # ===================================================================================

    def on_post_process_images(self):
        """
        Phase 5 – Georef and Mapping
        """

        if not self.ensure_mission_parameters():
            return



        try:

            self.dialog_GeoRef = DialogGeoRef(self.mission_parameters)
            self.dialog_GeoRef.data_signal_to_main.connect(
                self.handle_data_from_dialog_GeoRef
            )
            self.dialog_GeoRef.show()

        except Exception as e:
            print("Error in  class Main_Window(QMainWindow)   in on_post_process_images     opening Dialog_GeoRef:", e)

    def handle_data_from_dialog_GeoRef(self, validate: bool):
        if validate:
            print(Style.GREEN + "✔   Phase 5 completed successfully." + Style.RESET)
        else:
            print(Style.YELLOW + "⚠  Phase 5 cancelled by user." + Style.RESET)



    # ===================================================================================
    #                   Button #6 click handlers
    #     Step 6 archive the mission
    # ===================================================================================

    def on_archive_mission(self):
        """Phase 6 – Archive the mission (refused while another step window is open)."""
        for attr, name in (("dialog_synchro_aruco", "Step 3"),
                           ("dialog_image_processing", "Step 4"),
                           ("dialog_GeoRef", "Step 5")):
            dialog = getattr(self, attr, None)
            try:
                if dialog is not None and dialog.isVisible():
                    QMessageBox.warning(self, "Archive unavailable",
                                        f"Close the {name} window before archiving the mission.")
                    return
            except RuntimeError:
                pass  # window already destroyed
        dialog = getattr(self, "dialog_archive", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.raise_()
                return
        except RuntimeError:
            pass
        if not self.ensure_mission_parameters():
            return
        try:
            self.dialog_archive = DialogArchive(self.mission_parameters, parent=self)
            self.dialog_archive.show()
        except Exception as e:
            QMessageBox.critical(self, "Archive unavailable", str(e))

    # ===================================================================================
    #                   Help button
    # ===================================================================================


    def on_help(self):
        """Open the user manual on the overview chapter."""
        Help.show_help("ch:overview", parent=self)


    # ====================================================================================
    #                  Methods for class main_windows
    # ===================================================================================

    def ensure_mission_parameters(self) -> bool:
        """
        Ensure that mission_parameters are available: if no mission is loaded,
        ask for an existing mission folder and load it.

        Returns
        -------
        bool
            True if mission_parameters are available, False otherwise.
        """
        if self.mission_parameters is not None:
            return True
        QMessageBox.information(self, "IRDrone", "Choose the mission folder\n"
                                                 "(format FLY-YYYYMMDD-hhmm-location).")
        return self.choose_and_load_mission()

    def choose_and_load_mission(self) -> bool:
        """Ask for an existing mission folder and make it the current mission."""
        folder, ok = Uti.choose_mission_folder_phase_2(self, default_user_dir=str(config.OUTPUT_FOLDER_NAME))
        if not ok or not folder:
            return False
        return self.load_mission(Path(folder))

    def load_mission(self, folderMissionPath: Path) -> bool:
        """Load FlightAnalytics/mission_parameters.json of folderMissionPath and
        make it the current mission (bottom bar and step buttons updated)."""
        try:
            mission_json = Uti.safe_path(folderMissionPath / "FlightAnalytics" / "mission_parameters.json")
            if not mission_json.exists():
                raise FileNotFoundError("mission_parameters.json not found")

            with open(mission_json, "r", encoding="utf-8") as f:
                self.mission_parameters = json.load(f)

            # Inject mission path explicitly
            self.mission_parameters["folderMissionPath"] = folderMissionPath
            self.folderMissionPath = folderMissionPath
            self._show_current_mission()
            return True

        except Exception as e:
            QMessageBox.critical(
                self,
                "Mission loading error",
                f"Unable to load mission parameters:\n{e}"
            )
            return False

    def _open_step_window(self):
        """Name of a Step 3-6 window still open (it works on the current mission), else None."""
        for attr, name in (("dialog_synchro_aruco", "Step 3"),
                           ("dialog_image_processing", "Step 4"),
                           ("dialog_GeoRef", "Step 5"),
                           ("dialog_archive", "Step 6")):
            dialog = getattr(self, attr, None)
            try:
                if dialog is not None and dialog.isVisible():
                    return name
            except RuntimeError:
                pass  # window already destroyed
        return None

    def on_open_mission(self):
        """'Change mission...' button: switch to another existing mission."""
        busy = self._open_step_window()
        if busy:
            QMessageBox.warning(self, "IRDrone", f"Close the {busy} window before opening another mission.")
            return
        if self.choose_and_load_mission():
            print(f"Mission opened: {self.folderMissionPath}")


def warn_missing_tools(parent=None):
    """Tell the user which external tools (ExifTool, RawTherapee, SJCam converter)
    were not found. The wizard still opens: only the steps using them will fail."""
    message = missing_tools_message()
    if message:
        QMessageBox.warning(
            parent, "External tools not found",
            "Some external tools were not found:\n\n" + message +
            "\n\nThe wizard will open, but the steps that need them will fail.")
    return message


def main():
    """Main function to run the interactive application.."""
    app = _app
    # Close the splash first: it stays on top and would hide the first-launch dialog.
    _splash.close()
    ensure_working_dir_at_startup()
    main_window = Main_Window()
    # Check if main_window is modal or not
    if main_window.isModal():
        # print("TEST  main_window is a modal window.")
        pass
    else:
        # print("TEST   main_window is not a modal window.")
        pass
    # The splash is closed above: center_on_screen uses the active window to choose the screen
    screen = Prefrence_Screen()
    Uti.center_on_screen(main_window, screen_Id=screen.defaultScreenID, screen_adjust=screen.screenAdjust, window_display_size=screen.windowDisplaySize)
    main_window.show()
    warn_missing_tools(main_window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
