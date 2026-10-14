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
import rawpy
import imageio

# ----------------------------------------------------
#     bib Multi Thread
# ----------------------------------------------------

import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil


# ----------------------------------------------------
#     bib PyQt 6
# ----------------------------------------------------
from PyQt6.QtGui import (
    QPixmap,
    QImage
)
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
    QDoubleSpinBox
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
import IRD_Interactive_GeoRef as GeoRef
from IRD_Interactive_utils import safe_path
from IRD_Interactive_workers import TimeShiftWorker
from IRD_Interactive_workers import ImagePairingWorker
from IRD_Interactive_color_style import Style
from config import RAWTHERAPEEPATH, EXIFTOOLPATH
assert Path(EXIFTOOLPATH).exists(), f"ExifTool not found at {EXIFTOOLPATH}, Use environment variable EXIFTOOLPATH to set the path."
assert Path(RAWTHERAPEEPATH).exists(), f"RawTherapee not found at {RAWTHERAPEEPATH}, Use environment variable RAWTHERAPEEPATH to set the path."


class DialogGeoRef(QDialog):
    """
    Dialog for géoréférencement.

    Phase 5 of the processing pipeline:
          - post processing
    """

    data_signal_to_main = pyqtSignal(bool)
    log_signal = pyqtSignal(str)
    image_signal = pyqtSignal(str)

    def __init__(self, mission_parameters: dict, parent=None, multi_thread=False):
        super().__init__(parent)

        self.multi_thread = multi_thread

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

        self.setWindowTitle("Phase 5 – Géoréférencement")
        self.setMinimumSize(900, 600)  # exemple, avant c'était 700x450
        self.resize(900, 900)  # taille initiale à l'ouverture

        self._init_gui()
        self._connect_signals()

        # Connect the logger signal to the GUI log window.
        self.log_signal.connect(self._log)

        # Connect the image signal to the image display method.
        self.image_signal.connect(self._display_image)

        # Forward GeoRef logger messages to this dialog.
        GeoRef.logger.log_callback = self.log_signal.emit

        self._log("Dialog initialized.")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_gui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Titre en haut
        title = QLabel("<b>Géoréférencement</b>")
        main_layout.addWidget(title)

        # Fenêtre de log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        self.log_text.setMaximumHeight(200)
        main_layout.addWidget(self.log_text)

        # Boutons Run GeoRef
        btn_layout = QHBoxLayout()
        self.btn_run_GeoRef = QPushButton("Run Geo ref")
        btn_layout.addWidget(self.btn_run_GeoRef)
        main_layout.addLayout(btn_layout)

        # Label de la progress bar (mettre en gras)
        self.progress_label = QLabel("Geo Ref ")
        self.progress_label.setStyleSheet("font-weight: bold;")
        main_layout.addWidget(self.progress_label)

        # Progress bar juste au-dessus du bouton Close
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Image preview zone
        self.image_preview_label = QLabel("Aucune image sélectionnée")
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumHeight(250)
        self.image_preview_label.setStyleSheet(
            "QLabel { background-color: #f5f5f5; border: 1px solid #cccccc; }"
        )
        main_layout.addWidget(self.image_preview_label, stretch=1)

        # Bouton Close en bas
        self.btn_close = QPushButton("Close")

        # Stretch pour pousser le bouton Close en bas
        main_layout.addStretch()


        main_layout.addWidget(self.btn_close)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.btn_run_GeoRef.clicked.connect(self.on_run_GeoRef)
        self.btn_close.clicked.connect(self.on_close)

    # ------------------------------------------------------------------
    # Slots (placeholders)
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        self._log("Dialog closed by user.")
        self.data_signal_to_main.emit(True)
        self.close()

    # ------------------------------------------------------------------
    #  Display image for geo ref in image preview zone
    # ------------------------------------------------------------------


    def _display_image(self, image_path: str) -> None:
        """Display an image preview while preserving its aspect ratio."""

        pixmap = QPixmap()

        if image_path.lower().endswith(".dng"):
            # Extract the embedded JPEG thumbnail from the DNG.
            with rawpy.imread(image_path) as raw:
                try:
                    thumb = raw.extract_thumb()

                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        pixmap.loadFromData(thumb.data)
                    else:
                        # Fallback if the embedded thumbnail is not JPEG.
                        rgb = raw.postprocess()
                        image_bytes = imageio.imsave(
                            imageio.RETURN_BYTES, rgb, format="png"
                        )
                        pixmap.loadFromData(image_bytes, "PNG")

                except Exception as exc:
                    self._log(
                        f"Thumbnail extraction failed: {exc}. "
                        "Using full-resolution processing."
                    )

                    # Fallback if thumbnail extraction fails.
                    rgb = raw.postprocess()
                    image_bytes = imageio.imsave(
                        imageio.RETURN_BYTES, rgb, format="png"
                    )
                    pixmap.loadFromData(image_bytes, "PNG")

        else:
            # Load TIFF and other supported formats directly.
            pixmap.load(image_path)

        if pixmap.isNull():
            self._log(f"Unable to load image for preview: {image_path}")
            return

        # Scale the preview to fit the label.
        scaled_pixmap = pixmap.scaled(
            self.image_preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.image_preview_label.setPixmap(scaled_pixmap)
        self._log(f"Image preview loaded: {image_path}")


    def _display_image_01(self, image_path: str) -> None:
        """Display an image in the preview label while preserving its aspect ratio."""

        if image_path.lower().endswith(".dng"):
            # Decode the DNG image using rawpy.
            with rawpy.imread(image_path) as raw:
                rgb = raw.postprocess()

            # Convert the RGB array to PNG bytes, then to QPixmap.
            image_bytes = imageio.imsave(
                imageio.RETURN_BYTES, rgb, format="png"
            )
            image = QImage.fromData(image_bytes)
            pixmap = QPixmap.fromImage(image)

        else:
            # Load standard image formats directly.
            pixmap = QPixmap(image_path)

        if pixmap.isNull():
            self._log(f"Unable to load image for preview: {image_path}")
            return

        # Scale the image to fit the preview label.
        scaled_pixmap = pixmap.scaled(
            self.image_preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self.image_preview_label.setPixmap(scaled_pixmap)
        self._log(f"Image preview loaded: {image_path}")



    # ------------------------------------------------------------------
    #       Géo référencement
    # ------------------------------------------------------------------


    def on_run_GeoRef(self) -> None:
        """
        Step 5.1 – Run Géoréférencement.
        """
        try:
            self._log(f"En cours de développement ")
            self.progress_bar.setValue(0)
            QMessageBox.information(self, "Geo Ref",
                                    "Sélectionnez une ou plusieurs images\n"
                                    "Attention elles doivent être du même type.\n"
                                    "Type acceptés : dng (DJI) \n"
                                    "                tiff  \n"
                                    "                tif multispectral groupe de 4 images .\n"
                                    "                Exemple HYPRLASE_0121_1.tif, HYPRLASE_0121_2.tif, HYPRLASE_0121_3.tif, HYPRLASE_0121_4.tif\n"
                                    "                Dans ce dernier cas sélectionner le quadruplet d'images "
                                    )
            GeoRef.georef_main(image_callback=self.image_signal.emit)


        except Exception as e:
            self.progress_bar.setValue(0)
            self._log(f"Error starting Geo Ref: {e}")
            import traceback
            traceback.print_exc()

    def on_GeoRef_finished(self):

        self.progress_label.setText("Geo ref has been successfully ")
        self._log(f"Geo ref has been successfully")
        self.progress_bar.setValue(0)


    def _on_GeoRef_stage(self, stage: str):
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Geo Ref – {stage}")

    def _on_GeoRef_error(self, error_msg):
        self.progress_bar.setValue(0)
        self._log(f"Error during GeoRef: {error_msg}")
        QMessageBox.critical(
            self,
            "Geo Ref detection error",
            f"An error occurred during Geo Ref:\n{error_msg}"
        )


    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------


    def _log(self, message: str) -> None:
        """Append a message and refresh the log display."""
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()
        self.log_text.repaint()





