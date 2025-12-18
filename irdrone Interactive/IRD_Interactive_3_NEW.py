# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive Phase 3
#   compute time_shift alignement
#   17/12/2025   V003
# ---------------------------------------------------------------------------------

import os
import os.path as osp
from pathlib import Path
import numpy as np
import cv2
import matplotlib.pyplot as plt
import time
import json
from json import JSONDecodeError
from typing import List, Tuple, Optional, Sequence, Dict, Any, Union
import copy

# ----------------------------------------------------
#     bib Multi Thread
# ----------------------------------------------------

import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


# ----------------------------------------------------
#     bib PyQt 6
# ----------------------------------------------------
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import (
    Qt,
    QThreadPool,
    QObject,
    pyqtSignal,
    QThreadPool,
    QTimer,
)
from PyQt6.QtWidgets import (
    QMessageBox,
    QApplication,
    QWidget,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
)

# ----------------------------------------------------
#     bib matplotlib
# ----------------------------------------------------
import matplotlib
matplotlib.use("Agg")  # backend non interactif. Fondamental ici avec PyQt
import matplotlib.pyplot as plt

# ----------------------------------------------------
#     bib IRD_Interactive
# ----------------------------------------------------
import IRD_Interactive_utils as Uti
from IRD_Interactive_utils import safe_path
import IRD_Interactive_ArUco as Aru
from IRD_Interactive_workers import ArucoWorker
from IRD_Interactive_workers import TimeShiftWorker
from IRD_Interactive_color_style import Style

# ----------------------------------------------------
#     Third party codes
# ----------------------------------------------------

if os.name == 'nt':
    RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
    assert osp.exists(RAWTHERAPEEPATH), "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
    EXIFTOOLPATH = osp.join(osp.dirname(__file__), "..", "thirdparty", "exiftool", "exiftool.exe")
    assert osp.exists(EXIFTOOLPATH), "Requires exif tool at {} from https://exiftool.org/".format(EXIFTOOLPATH)

else:
    RAWTHERAPEEPATH = "rawtherapee-cli"
    EXIFTOOLPATH = "exiftool"


class DialogSynchroAruco(QDialog):
    """
    Dialog for VIS / NIR timeline synchronization using ArUco-based angle estimation.

    Phase 3 of the processing pipeline:
      - 3.1 ArUco detection and angle extraction
      - 3.2 Time shift estimation between VIS and NIR timelines
    """

    data_signal_to_main = pyqtSignal(bool)

    def __init__(self, mission_parameters: dict, parent=None, multi_thread=True, use_aruco_cache=False):
        super().__init__(parent)



        self.multi_thread = multi_thread
        self.use_aruco_cache = use_aruco_cache

        self.mission_parameters = mission_parameters
        self.folderMissionPath = (mission_parameters.get("folderMissionPath") or mission_parameters.get("File path mission"))
        if self.folderMissionPath is None:
            QMessageBox.critical(
                self,
                "Missing mission folder",
                "The mission folder is not defined.\n"
                "Please run Phase 1 or Phase 2 first, or select a mission folder."
            )
            self.close()
            return

        self.setWindowTitle("Phase 3 – VIS / NIR time synchronization")
        self.setMinimumSize(900, 600)  # exemple, avant c'était 700x450
        self.resize(900, 900)  # taille initiale à l'ouverture

        self._init_gui()
        self._connect_signals()

        self._log("Dialog initialized.")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Titre en haut
        title = QLabel("<b>Timeline Synchronization</b>")
        main_layout.addWidget(title)

        # Fenêtre de log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        self.log_text.setMaximumHeight(200)
        main_layout.addWidget(self.log_text)

        # Boutons Run ArUco / Compute time alignment
        btn_layout = QHBoxLayout()
        self.btn_run_aruco = QPushButton("Run ArUco detection (VIS + NIR)")
        btn_layout.addWidget(self.btn_run_aruco)
        self.btn_compute_time_shift = QPushButton("Compute time alignment")
        self.btn_compute_time_shift.setEnabled(False)
        btn_layout.addWidget(self.btn_compute_time_shift)
        main_layout.addLayout(btn_layout)

        # Label de la progress bar (mettre en gras)
        self.progress_label = QLabel("ArUco detection – idle")
        self.progress_label.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(self.progress_label)

        # Progress bar juste au-dessus du bouton Close
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Graphic zone
        self.timeshift_plot_label = QLabel()
        self.timeshift_plot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeshift_plot_label.setMinimumHeight(600)
        self.timeshift_plot_label.setMaximumHeight(620)
        self.timeshift_plot_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )
        main_layout.addWidget(self.timeshift_plot_label)

        # Bouton Close en bas
        self.btn_close = QPushButton("Close")

        # Stretch pour pousser le bouton Close en bas
        main_layout.addStretch()


        main_layout.addWidget(self.btn_close)



    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.btn_run_aruco.clicked.connect(self.on_run_aruco)
        self.btn_compute_time_shift.clicked.connect(self.on_compute_time_shift)
        self.btn_close.clicked.connect(self.on_close)

    # ------------------------------------------------------------------
    # Slots (placeholders)
    # ------------------------------------------------------------------

    def on_run_aruco(self) -> None:
        """
        Step 3.1 – Run ArUco detection on VIS and NIR images using orchestrator.
        """
        try:
            self.aruco_orchestrator = ArucoOrchestrator(Path(self.folderMissionPath) / "AerialPhotography", multi_thread=self.multi_thread, use_aruco_cache=self.use_aruco_cache)
            self.aruco_orchestrator.signals.all_finished.connect(self.on_all_aruco_finished)
            self.aruco_orchestrator.signals.error.connect(self._on_aruco_error)
            self._log("Starting ArUco detection (VIS + NIR) using orchestrator...")
            self.aruco_orchestrator.signals.progress.connect(self.progress_bar.setValue)
            self.aruco_orchestrator.signals.stage.connect(self.progress_label.setText)
            self.progress_bar.setValue(0)
            self.aruco_orchestrator.start_VIS()


        except Exception as e:
            self.progress_bar.setValue(0)
            self._log(f"Error starting ArUco orchestrator: {e}")

    def on_all_aruco_finished(self):
        # Récupérer les résultats depuis l'orchestrateur
        self.aruco_results_vis = self.aruco_orchestrator.VIS_results
        self.x_vis = self.aruco_orchestrator.VIS_x_vals
        self.y_vis = self.aruco_orchestrator.VIS_y_vals

        self.aruco_results_nir = self.aruco_orchestrator.NIR_results
        self.x_nir = self.aruco_orchestrator.NIR_x_vals
        self.y_nir = self.aruco_orchestrator.NIR_y_vals


        self.progress_label.setText("ArUco VIS/NIR has been successfully detected ")
        self._log(f"ArUco detection completed for VIS ({len(self.aruco_results_vis)}) "
                  f"and NIR ({len(self.aruco_results_nir)})")
        self.progress_bar.setValue(0)

        self.btn_compute_time_shift.setEnabled(True)

    def _on_aruco_error(self, error_msg):
        self.progress_bar.setValue(0)
        self._log(f"Error during ArUco detection: {error_msg}")
        QMessageBox.critical(
            self,
            "ArUco detection error",
            f"An error occurred during VIS ArUco detection:\n{error_msg}"
        )

    def on_compute_time_shift(self) -> None:
        """
        Placeholder for time alignment computation (3.2).
        """
        self._log("Time alignment computation requested (not yet implemented).")
        self.progress_bar.setValue(100)

    def on_close(self) -> None:
        self._log("Dialog closed by user.")
        self.data_signal_to_main.emit(True)
        self.close()

    def _on_aruco_stage(self, stage: str):
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"ArUco detection – {stage}")

    # ------------------------------------------------------------------
    #       time shift
    # ------------------------------------------------------------------
    def on_compute_time_shift(self):
        self.progress_bar.setValue(3)
        try:
            self._log("Starting time shift calculation (phase 3.2)...")

            worker = TimeShiftWorker(
                vis_results=self.aruco_results_vis,
                vis_x=self.x_vis,
                vis_y=self.y_vis,
                nir_results=self.aruco_results_nir,
                nir_x=self.x_nir,
                nir_y=self.y_nir
            )
            worker.signals.finished.connect(self._on_timeshift_finished)
            worker.signals.error.connect(self._on_aruco_error)

            QThreadPool.globalInstance().start(worker)

        except Exception as e:
            self._log(f"Error starting time shift worker: {e}")
        self.progress_bar.setValue(50)

    def _on_timeshift_finished(
            self,
            time_shift: float,
            time_line_VIS,
            angles_VIS,
            time_line_NIR,
            angles_NIR,
    ):
        self._log(f"Time shift computed successfully : {time_shift} s")

        # ------------------------------------------------------------
        # 1) Sauvegarde des graphique
        # ------------------------------------------------------------
        output_dir = safe_path(Path(self.folderMissionPath) / "Synchro")
        filename = "check_time_before_alignment.png"
        xlim = self.compute_x_limits(time_line_VIS, time_line_NIR, time_shift=time_shift)
        plot_before = self.save_timeshift_plot(
            output_dir=output_dir,
            time_line_VIS=time_line_VIS,
            angles_VIS=angles_VIS,
            time_line_NIR=time_line_NIR,
            angles_NIR=angles_NIR,
            time_shift=time_shift,
            filename=filename,
            xlim=xlim,
        )
        filename = "check_time_alignment.png"

        time_NIR_shifted = [t + time_shift for t in time_line_NIR]

        plot_after = self.save_timeshift_plot(
            output_dir=output_dir,
            time_line_VIS=time_line_VIS,
            angles_VIS=angles_VIS,
            time_line_NIR=time_NIR_shifted,
            angles_NIR=angles_NIR,
            time_shift=time_shift,
            filename=filename,
            xlim=xlim,
        )

        self._log(f"Time shift plot saved to : {plot_before} and {plot_after}")
        self._log(f"Starting animation from {plot_before} to {plot_after}")


        # ------------------------------------------------------------
        # 2) Chargement et affichage du PNG dans le GUI
        # ------------------------------------------------------------
        try:

            self.animate_timeshift_plot(plot_before=plot_before, plot_after=plot_after)
        except Exeception as e:
            print(f'error in animate_timeshift_plot  {e}')

        """
        pixmap = QPixmap(str(plot_path))
        if pixmap.isNull():
            self._log("Failed to load time-shift plot image.")
            return
        # self.timeshift_plot_label.setPixmap(pixmap)
        scaled = pixmap.scaled(
            self.timeshift_plot_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.timeshift_plot_label.setPixmap(scaled)
        self.timeshift_plot_label.repaint()
        QApplication.processEvents()
        """

        # ------------------------------------------------------------
        # 3) Stockage état interne (si nécessaire)
        # ------------------------------------------------------------
        self.time_shift = time_shift
        self.time_line_VIS = time_line_VIS
        self.angles_VIS = angles_VIS
        self.time_line_NIR = time_line_NIR
        self.angles_NIR = angles_NIR

        # ------------------------------------------------------------
        # 4) UI finale
        # ------------------------------------------------------------
        self.progress_bar.setValue(100)
        self.progress_label.setText("Time shift successfully computed.")

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if self.timeshift_plot_label.pixmap():
            scaled = self.timeshift_plot_label.pixmap().scaled(
                self.timeshift_plot_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.timeshift_plot_label.setPixmap(scaled)

    def animate_timeshift_plot(self, plot_before: Path, plot_after: Path, delay_ms: int = 1500):
        """
        Affiche successivement deux images dans le QLabel avec un délai.
        """
        self._animation_images = [QPixmap(str(plot_before)), QPixmap(str(plot_after))]
        self._animation_index = 0

        if any(pix.isNull() for pix in self._animation_images):
            self._log("Failed to load one of the time-shift plot images for animation.")
            return

        # Affichage initial
        self.timeshift_plot_label.setPixmap(self._animation_images[self._animation_index].scaled(
            self.timeshift_plot_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

        # Timer pour alterner les images
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation_frame)
        self._animation_timer.start(delay_ms)

    def _update_animation_frame(self):
        self._animation_index = (self._animation_index + 1) % len(self._animation_images)
        pixmap = self._animation_images[self._animation_index].scaled(
            self.timeshift_plot_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.timeshift_plot_label.setPixmap(pixmap)

    def compute_x_limits(self, time_line_VIS, time_line_NIR, time_shift=0.0, padding_ratio: float = 0.05):
        """
        Retourne des limites x (xmin, xmax) robustes pour le graphique,
        en incluant toutes les données VIS et NIR, avant et après décalage.

        Parameters
        ----------
        time_line_VIS : list[float]
            Timeline VIS.
        time_line_NIR : list[float]
            Timeline NIR.
        time_shift : float
            Décalage temporel appliqué à la NIR.
        padding_ratio : float, optional
            Fraction de l'amplitude totale à ajouter comme marge à gauche et droite, by default 0.05

        Returns
        -------
        tuple[float, float]
            xmin et xmax pour l'axe horizontal.
        """
        if not (time_line_VIS or time_line_NIR):
            return 0.0, 1.0  # fallback si listes vides

        # Inclure NIR après shift pour que l'axe englobe tout
        all_times = list(time_line_VIS) + list(time_line_NIR) + [t + time_shift for t in time_line_NIR]

        t_min = min(all_times)
        t_max = max(all_times)
        amplitude = t_max - t_min
        padding = amplitude * padding_ratio
        return t_min - padding, t_max + padding

    def save_timeshift_plot(
            self,
            output_dir: Path,
            time_line_VIS,
            angles_VIS,
            time_line_NIR,
            angles_NIR,
            time_shift: float,
            filename: str = "check_time_alignment.png",
            xlim=None,
            ylim=None
    ):
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / filename

            fig, ax = plt.subplots(figsize=(10, 7))

            # VIS
            ax.plot(
                time_line_VIS,
                angles_VIS,
                label="VIS",
                color='g',
                lw=1.2,
                marker="o",
                markersize=5,
                markeredgewidth=0.5,
                markeredgecolor="black",
            )

            # NIR
            ax.plot(
                time_line_NIR,
                angles_NIR,
                label="NIR",
                color='r',
                lw=1.2,
                marker="o",
                markersize=5,
                markeredgewidth=0.5,
                markeredgecolor="black",
            )

            if xlim:
                ax.set_xlim(xlim)
            if ylim:
                ax.set_ylim(ylim)


            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Angle (deg)")
            ax.set_title(f"Time shift VIS / NIR = {time_shift:.3f} s")
            ax.legend()
            ax.grid(True, alpha=0.3)

            fig.tight_layout()
            fig.savefig(out_path, dpi=150)
            plt.close(fig)

            return out_path

        except Exception as e:
            self._log(f"Error during time shift plot generation: {e}")
            QMessageBox.critical(
                self,
                "Time shift plot error",
                f"An error occurred while generating the time alignment plot:\n{e}"
            )
            return None
# ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        self.log_text.append(message)

class ArucoOrchestrator:
    """
    orchestrateur pour lancer les workers VIS et NIR en parallèle
    et stocker leurs résultats.
    """
    def __init__(self, folderMissionPath, multi_thread=False, use_aruco_cache=False):
        self.folderMissionPath = folderMissionPath
        self.multi_thread = multi_thread
        self.use_aruco_cache = use_aruco_cache
        # Stockage des résultats
        self.VIS_results = []
        self.VIS_x_vals = []
        self.VIS_y_vals = []

        self.NIR_results = []
        self.NIR_x_vals = []
        self.NIR_y_vals = []

        self.signals = ArucoOrchestratorSignals()

        # flags pour savoir quand chaque worker a fini
        self._vis_done = False
        self._nir_done = False

        # thread pool global
        self.thread_pool = QThreadPool.globalInstance()


    def start_VIS(self):
        self._start_worker(
            name_folder="VIS",
            spectral_band="VIS",
            finished_callback=self._on_vis_finished,
        )

    def start_NIR(self):
        self._start_worker(
            name_folder="NIR",
            spectral_band="NIR",
            finished_callback=self._on_nir_finished,
        )


    def _start_worker(self, name_folder, spectral_band, finished_callback):
        worker = ArucoWorker(
            folderMissionPath=self.folderMissionPath,
            name_folder=name_folder,
            spectral_band=spectral_band,
            suffix_image="dng",
            save_check_detection_img=True,
            verbose=False,
            use_aruco_cache=self.use_aruco_cache,
            multi_thread=self.multi_thread
        )
        worker.signals.finished.connect(finished_callback)
        worker.signals.error.connect(self.signals.error.emit)
        # ✅ RELAIS DE LA PROGRESSION
        worker.signals.progress.connect(self.signals.progress.emit)
        worker.signals.stage.connect(self.signals.stage.emit)
        self.thread_pool.start(worker)

    def _on_vis_finished(self, results, x_vals, y_vals):
        self.VIS_results = results
        self.VIS_x_vals = x_vals
        self.VIS_y_vals = y_vals
        self._vis_done = True

        self.start_NIR()

    def _on_nir_finished(self, results, x_vals, y_vals):
        self.NIR_results = results
        self.NIR_x_vals = x_vals
        self.NIR_y_vals = y_vals
        self._nir_done = True

        self.signals.all_finished.emit()

class ArucoOrchestratorSignals(QObject):
    progress = pyqtSignal(int)
    stage = pyqtSignal(str)   # "VIS" ou "NIR"
    all_finished = pyqtSignal()
    error = pyqtSignal(str)


