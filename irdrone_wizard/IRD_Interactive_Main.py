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
    QMessageBox,
    QDialog,
    QFrame,
)
from PyQt6.QtCore import Qt, QLoggingCategory
from PyQt6.QtGui import QPixmap, QColor, QIcon, QPainter, QFont
from PyQt6.QtWidgets import QSplashScreen

print("IRDrone is starting, waiting ...", flush=True)

# Small buttons of the status bar
QUIET_BUTTON = """
QPushButton { background: white; color: #17365D; border: 1px solid #C5CFDA; border-radius: 5px;
              padding: 3px 10px; font-weight: bold; }
QPushButton:hover { background: #EEF3F8; }
"""


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
from IRD_Interactive_timeline import FlightTimelineDialog
from IRD_Interactive_new_mission import NewMissionDialog
from IRD_Interactive_review import ReviewDialog
from IRD_Interactive_mission_details import MissionDetailsDialog
from IRD_Interactive_home import HomePage, recent_missions
from IRD_Interactive_3 import DialogSynchroAruco
from IRD_Interactive_4 import DialogImageProcessing
from IRD_Interactive_5 import DialogGeoRef
from IRD_Interactive_6 import DialogArchive
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import Prefrence_Screen
from IRD_Interactive_color_style import Style
import config
from config import missing_tools_message
import IRD_Interactive_help as Help
from IRD_Interactive_workdir import WorkingDirBar, ensure_working_dir_at_startup
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
        self.btn_help = None
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

        #  Help button (bottom right of the window)
        self.btn_help = QPushButton("? Manual", self)
        self.btn_help.setStyleSheet(QUIET_BUTTON)
        self.btn_help.setToolTip("User manual")
        self.btn_help.clicked.connect(self.on_help)
        Progress.notifier.changed.connect(lambda _folder: self._show_current_mission())

        # No step bar: the steps are run from the home page (New mission, then
        # the step rail and "Continue" of the mission page).
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        # Home page: New / Open mission and recent missions, then the current
        # mission (what is done, what comes next)
        image_path = os.path.join(self.pref_screen.default_app_dir, "Icon", "image_IRdrone_appli.jpg")
        self.home = HomePage(hero_image=Path(image_path))
        self.home.setMinimumSize(*self.image_display_size)
        self.home.new_mission.connect(self.open_window_define_mission)
        self.home.open_mission.connect(self.on_open_mission)
        self.home.open_recent.connect(self.on_open_recent)
        self.home.run_step.connect(self.run_step)
        self.home.step_clicked.connect(self.open_step)
        self.home.review.connect(self.on_review)
        self.home.set_recent(recent_missions(Path(self.pref_screen.default_user_dir)))
        self.main_layout.addWidget(self.home, 1)

        # Status bar: working folder, free space and its gear (left), manual (right).
        # The mission itself is on the page (title, open folder, All missions).
        status = QFrame()
        status.setObjectName("statusbar")
        status.setStyleSheet("#statusbar { background: #F0F3F7; border-top: 1px solid #DDE3EA; }"
                             " #statusbar QLabel { background: transparent; }")
        bottom_layout = QHBoxLayout(status)
        bottom_layout.setContentsMargins(12, 4, 12, 4)
        self.working_dir_bar = WorkingDirBar(self)
        self.working_dir_bar.changed.connect(self._on_working_dir_changed)
        self.working_dir_bar.gear.setStyleSheet(QUIET_BUTTON)
        bottom_layout.addWidget(self.working_dir_bar)
        bottom_layout.addSpacing(30)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_help)
        self.main_layout.addWidget(status)

        for step, tile in self.home.rail.tiles.items():
            Help.attach_help(tile, f"ch:step{step}", parent=self)   # right-click: manual
        # every button of the main window: a tool tip and, on right-click, its section of the manual
        home = self.home
        for widget, label, tip in (
            (home.card_new, "btn:home_missions",
             "Create a mission from the SD cards of the drone and of the infrared camera (Step 1)."),
            (home.card_open, "btn:home_missions",
             "Choose the folder of a mission already created (FLY-YYYYMMDD-hhmm-place)."),
            (home.btn_all, "btn:home_missions", "Back to the first page: new mission, open a mission, recent missions."),
            (home.btn_continue, "btn:home_continue", ""),       # tool tip set with the next step
            (home.btn_review, "ch:review",
             "Check every aligned image on a time line, flag the misaligned ones and realign them by hand."),
            (home.btn_show_map, "btn:home_map", home.btn_show_map.toolTip()),
            (home.btn_show_image, "btn:home_map", home.btn_show_image.toolTip()),
            (self.working_dir_bar.gear, "btn:home_workdir",
             "Change the working folder (the folder that holds the missions)."),
            (self.btn_help, "sec:help", "Open this manual. Right-click any button: the manual at that button."),
        ):
            Help.attach_help(widget, label, tip, parent=self)

    def _on_working_dir_changed(self, folder):
        """New working folder chosen with the gear button."""
        self.pref_screen.default_user_dir = folder
        self.def_user_dir = folder
        self.home.set_recent(recent_missions(Path(folder)))
        print(f"Working folder: {folder}")

    def _show_current_mission(self):
        """Refresh the mission page (title, steps, map)."""
        folder = Progress.mission_folder(self.mission_parameters, self.folderMissionPath)
        try:
            self.home.show_mission(folder)
        except Exception as e:  # the home page must never block the steps
            print(f"Home page not updated: {e}")

    # ===================================================================================
    #                   Button #1 click handlers
    #     Step 1 Define the mission
    # ===================================================================================


    def open_window_define_mission(self):
        """Step 1 - new mission: images found on the SD cards, details, copy.
        "Flight timeline" at the end goes on with Step 2."""
        busy = self._open_step_window()
        if busy:
            QMessageBox.warning(self, "IRDrone", f"Close the {busy} window before creating a mission.")
            return
        dialog = NewMissionDialog(Path(self.pref_screen.default_user_dir), parent=self)
        dialog.mission_created.connect(self.handle_new_mission)
        dialog.exec()
        if dialog.action == "classic":
            self.open_window_define_mission_classic()
        elif dialog.action == "timeline":
            self.open_window_load_set_images()

    def handle_new_mission(self, mission_parameters: dict):
        """A mission was created by the new mission window: it becomes the current one."""
        folder = Path(mission_parameters["File path mission"])
        self.mission_parameters = dict(mission_parameters)
        self.mission_parameters["folderMissionPath"] = folder
        self.folderMissionPath = folder
        self._show_current_mission()
        self.home.set_recent(recent_missions(Path(self.pref_screen.default_user_dir)))

    def open_window_define_mission_classic(self):
        """
        Classic Step 1: open dialog_load_takeoff_image (take-off image, then the form).
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
        else:
            print("The user has not validated his entries.")

        self.dialog_load_takeoff_image.close()


    # ===================================================================================
    #                   Button #2 click handlers
    #     Step 2 load set of VIS and NIR images of he mission.
    # ===================================================================================


    def open_window_load_set_images(self):
        """
        Step 2: flight timeline. The synchronisation and survey phases are
        detected automatically and confirmed by the user; "Confirm and
        synchronize" chains into Step 3. The classic selection (5 images per
        camera) stays available from the timeline window.
        """
        if not self.ensure_mission_parameters():
            return
        folderMissionPath = Path(Progress.mission_folder(self.mission_parameters, self.folderMissionPath))
        try:
            dialog = FlightTimelineDialog(folderMissionPath, parent=self)
        except Exception as e:
            print(Style.RED + f"Flight timeline unavailable ({e}): classic selection." + Style.RESET)
            self.open_window_classic_selection()
            return
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if dialog.action == "classic":
            self.open_window_classic_selection()
            return
        if not accepted:
            return
        Progress.mark_step_done(folderMissionPath, 2)
        if dialog.action == "synchronize":
            self.on_pre_process_images(auto_run=True)

    def open_window_classic_selection(self):
        """
        load set of VIS and NIR images of he mission.
        """
        # ------------------ setting window size to load image sets -------------------------------------
        active_screen_id = QApplication.screens().index(QApplication.activeWindow().screen()) if QApplication.activeWindow() else 0
        screen_geometry = QApplication.screens()[active_screen_id].availableGeometry()
        width = screen_geometry.width() - 20  # width of the window
        height = 500  # height of the window

        # ----------------------- Choice of mission file -------------------------------------------------
        # The current mission (Step 1, "Open mission..." or another step) is used
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

    def on_pre_process_images(self, auto_run=False):
        """
        Phase 3 – VIS / NIR synchronization.
        auto_run: start the detection and the time alignment right away (from Step 2).
        """
        if not self.ensure_mission_parameters():
            return

        try:
            self.dialog_synchro_aruco = DialogSynchroAruco(
                self.mission_parameters,
                parent=self,
                auto_run=bool(auto_run),
            )
            self.dialog_synchro_aruco.data_signal_to_main.connect(
                self.handle_data_from_dialog_synchro_aruco
            )
            # Pairing done, "Image processing": Step 4 opens, the user starts it
            self.dialog_synchro_aruco.continue_requested.connect(self.on_process_images)
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


    def on_process_images(self, auto_run=False):
        """Step 4. auto_run (chained from Step 3): the alignment starts at once."""
        if not self.ensure_mission_parameters():
            return

        try:
            self.dialog_image_processing = DialogImageProcessing(
                self.mission_parameters, self, auto_run=bool(auto_run)
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

    def run_step(self, step: int):
        """'Continue' of the home page: the step, chained to the next ones when possible."""
        if step == 1:
            self.open_window_define_mission()
        elif step == 2:
            self.open_window_load_set_images()
        elif step == 3:
            self.on_pre_process_images(auto_run=True)
        elif step == 4:
            self.on_process_images()
        elif step == 5:
            self.on_post_process_images()
        elif step == 6:
            self.on_archive_mission()

    def open_step(self, step: int):
        """A step of the rail: the next ones are chained as with "Continue";
        a step already done is opened as is (Step 3 without running on its own).
        Step 1 created the loaded mission: its details are edited instead
        (no new mission, the SD cards are not read again)."""
        folder = Progress.mission_folder(self.mission_parameters, self.folderMissionPath)
        if step == 1 and folder is not None and 1 in Progress.done_steps(folder):
            self.edit_mission_details()
            return
        if step == 3 and folder is not None and 3 in Progress.done_steps(folder):
            self.on_pre_process_images(auto_run=False)
        else:
            self.run_step(step)

    def edit_mission_details(self):
        """Description, pilot, cameras of the loaded mission (Step 1 done)."""
        folder = Progress.mission_folder(self.mission_parameters, self.folderMissionPath)
        if folder is None:
            return
        try:
            dialog = MissionDetailsDialog(Path(folder), parent=self)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Mission details", f"mission_parameters.json cannot be read:\n{e}")
            return
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changed:
            self.load_mission(Path(folder))          # the new details everywhere

    def on_review(self):
        """Review of the aligned images (end of Step 4)."""
        if not self.ensure_mission_parameters():
            return
        folder = Progress.mission_folder(self.mission_parameters, self.folderMissionPath)
        try:
            dialog = ReviewDialog(Path(folder), parent=self)
        except (FileNotFoundError, ValueError) as e:
            QMessageBox.warning(self, "Review unavailable", str(e))
            return
        dialog.exec()
        self._show_current_mission()

    def on_open_recent(self, folder):
        busy = self._open_step_window()
        if busy:
            QMessageBox.warning(self, "IRDrone", f"Close the {busy} window before opening another mission.")
            return
        if self.load_mission(Path(folder)):
            print(f"Mission opened: {self.folderMissionPath}")

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
        """'Open a mission' card: switch to an existing mission."""
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
