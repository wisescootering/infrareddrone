import sys
import numpy as np
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, \
    QProgressBar, QFrame, QMessageBox
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt, QTimer
from PIL import Image


# ==========================================================
#
# Procédure qui permet de choisir une image et de la transfromer en icone.
#
# Les formats d'image acceptées sont : jpg, png et bmp
# L'icone crée possède 4 résolutions [(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
#
# ==========================================================

class ImageToIconeApp(QWidget):
    """
    A PyQt5 GUI application to load a image and transform in ico file.
    Thank chatGpt ;-))
    """
    SIZE = int(400)  # Size of images  on screen. Min 256  Maxi 410 pixel
    IMAGE_DISPLAY_SIZE = (SIZE, SIZE)  # Define the display size (width, height)
    # Parameters used in the function  "def center_on_screen"(self):"
    TARGET_SCREEN = 1  # Set to 0 for the first screen, 1 for the second screen, and so on
    SCREEN_ADJUST = (260, 40)  # 40 for taskbar and + 200(screen 1) or 0 (screen2) for other GUI elements
    DEFAULT_IMAGE_DIR = r"C:/Documents-Alain/Projet-IRdrone/test interactif"  # attention mettre / et pas \ pour compatibilité avec la procédure convertImg2ico
    DEFAULT_IMAGE_NAME = "image_ico"

    def __init__(self):
        """Initialize the GUI components."""
        super().__init__()

        self.image_originale = None  # Store the original image
        self.image_courante = None
        self.image_bw = None  # image noir et blanc
        self.image_originale_array = None
        self.image_courante_array = None
        self.image_grayscale_array = None
        self.setWindowTitle('IRDrone interactive v01')
        QTimer.singleShot(100, self.center_on_screen)  # Delay the call to center_on_screen by 100ms
        self.list_format_image = ('jpg', 'jpeg', 'bmp', 'png', 'JPG', 'PNG', 'JPEG')  # '.tif', '.tiff',
        self.init_ui()

    # ==========================================================
    #
    # Initialisation des objets de la fenêtre interactive
    #  (boutons, zone graphique, progress bar etc)
    #
    # ==========================================================

    def init_ui(self):
        """Set up the UI layout and components."""

        main_layout = QVBoxLayout(self)

        # Load buttons layout
        load_buttons_layout = QHBoxLayout()
        self.load_btn_charge_image = QPushButton('Load Image')
        self.load_btn_charge_image.setStyleSheet("background-color: darkBlue; color: white;")
        self.load_btn_charge_image.clicked.connect(self.load_and_display_image)
        load_buttons_layout.addWidget(self.load_btn_charge_image)

        main_layout.addLayout(load_buttons_layout)

        # Create an empty pixmap of the desired size
        self.empty_pixmap = QPixmap(*self.IMAGE_DISPLAY_SIZE)
        self.empty_pixmap.fill(Qt.GlobalColor.gray)  # transparent,gray, darkYellow etc)

        # Images display layout
        images_layout = QHBoxLayout()
        self.image_courante_label = QLabel(self)
        self.image_courante_label.setPixmap(self.empty_pixmap)  # Set the empty pixmap
        self.image_courante_label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)  # Add a frame
        images_layout.addWidget(self.image_courante_label, 1)
        images_layout.addStretch()
        main_layout.addLayout(images_layout)

        # Buttons for grayscale conversion
        action_buttons_layout = QHBoxLayout()
        self.convert2gray_btn = QPushButton('Convert to Grayscale', self)
        action_buttons_layout.addWidget(self.convert2gray_btn)
        self.convert2gray_btn.clicked.connect(self.convert_images_to_grayscale)
        self.convert2gray_btn.setEnabled(False)
        main_layout.addLayout(action_buttons_layout)

        # Buttons restore
        action_buttons_layout = QHBoxLayout()
        self.restore_btn = QPushButton('Restore Original', self)
        action_buttons_layout.addWidget(self.restore_btn)
        self.restore_btn.clicked.connect(self.restore_images)
        self.restore_btn.setEnabled(False)
        main_layout.addLayout(action_buttons_layout)

        # Layout for "transform to ico"
        # > Zone graphique
        transform_layout = QHBoxLayout()
        self.icon_image_label = QLabel(self)
        self.icon_image_label.setPixmap(self.empty_pixmap)  # Set the empty pixmap
        self.icon_image_label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)  # Add a frame
        transform_layout.addStretch(1)  # Add spacer with stretch factor to push the image to the center
        transform_layout.addWidget(self.icon_image_label)
        transform_layout.addStretch(1)  # Add spacer with stretch factor to push the image to the center
        main_layout.addLayout(transform_layout)
        # > Zone bouton associée  transform to ico button
        self.convert2ico_btn = QPushButton('transform to ico file', self)
        self.convert2ico_btn.clicked.connect(self.convertImg2ico)
        self.convert2ico_btn.setEnabled(False)

        main_layout.addWidget(self.convert2ico_btn)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        main_layout.addWidget(self.progress_bar)

        self.setLayout(main_layout)

        self.reset_timer = QTimer(self)
        self.reset_timer.timeout.connect(self.reset_progress_bar)

    # ==========================================================
    #
    # Procédures liées à l'application
    #
    # ==========================================================

    def load_and_display_image(self):
        """
        Load and display an image
        """
        try:
            if True:
                self.image_courante_path, _ = QFileDialog.getOpenFileName(self, "Open Image", self.DEFAULT_IMAGE_DIR,
                                                                          "Image files (*.jpg *.jpeg *.png *.bmp *.DNG *.ico)")
                if self.image_courante_path:
                    if not self.control_format_image(self.image_courante_path): return
                    self.image_courante, self.image_courante_array = self.load_image(self.image_courante_path)
                    self.image_courante_label.setPixmap(
                        self.image_courante.scaled(*self.IMAGE_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio))
                    self.image_originale, self.image_originale_array = self.image_courante, self.image_courante_array

                    self.restore_btn.setEnabled(True)
                    self.convert2gray_btn.setEnabled(True)
                    self.convert2ico_btn.setEnabled(True)

        except Exception as e:
            print("error in load_and_display_image :", e)

    def load_image(self, image_path):
        """Load an image from the given path and return it as a QPixmap and a numpy array."""
        self.icon_image_label.setPixmap(self.empty_pixmap)  # Set the empty pixmap
        self.progress_bar.setValue(0)

        image = QImage(image_path)
        pixmap = QPixmap.fromImage(image)
        image_array = self.image_to_array(image)
        image_array = image_array[:, :, ::-1]  # Inverse l'ordre des canaux (BGR to RGB)

        return pixmap, image_array


    def image_to_array(self, image):
        """Convert QImage to numpy array."""
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        return np.array(ptr).reshape(image.height(), image.width(), 4)[:, :, :3]

    def control_format_image(self, image_path):
        file_extension = image_path.split('.')[-1].lower()  # Extract image file extension
        # Ensure image have the right type
        if file_extension in self.list_format_image:
            img_format_OK = True
        else:
            error_msg = (f"Error: The  image have bad formats.\n"
                         f"Image - Format: {file_extension}\n"
                         f"Formats admissibles :{self.list_format_image}")
            img_format_OK = False
            self.show_error_message(error_msg)

        return img_format_OK

    def image_to_array(self, image):
        """Convert QImage to numpy array."""
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())
        return np.array(ptr).reshape(image.height(), image.width(), 4)[:, :, :3]

    def convert_images_to_grayscale(self):
        """Convert a image to grayscale."""
        try:
            grayscale_image = self.image_courante.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
            pixmap_gray = QPixmap.fromImage(grayscale_image).scaled(*self.IMAGE_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
            # affiche l'image en niveaux de gris
            self.image_courante_label.setPixmap(pixmap_gray)
            # convertie l'image en niveau de gris en tableau numpy  (attention ici a la résolution de l'image QT
            self.image_grayscale_array = self.image_to_array(pixmap_gray.toImage())

            self.image_courante = pixmap_gray
            self.image_courante_array = self.image_grayscale_array

            self.progress_bar.setValue(100)
            self.reset_timer.start(1000)  # wait 1 s
        except Exception as e:
            print('convert_to_grayscale   error is :" ', e)
    def restore_images(self):
        """Restore the images to their original state."""
        if self.image_originale:
            self.image_courante_array = self.image_originale_array
            self.image_courante = self.image_originale
            # affiche l'image restorée
            self.image_courante_label.setPixmap(
                self.image_courante.scaled(*self.IMAGE_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio))

            self.progress_bar.setValue(100)
            self.reset_timer.start(1000)  # wait 1 s

    def convertImg2ico(self):
        #  On procède en plusieurs étapes  :
        #  Step 1> visualise l'image de l'icone pendant 1s
        #  Step 2> puis on lance  self.open_save_dialog
        # lambda: permet de lancer une "copie" de la procédure (sans cela la procédure est appelée immédiatement)
        try:
            # Convert the numpy array to QPixmap and display it
            image_array = self.image_courante_array
            square_image = self.make_square(image_array)
            self.img_ico_ecran = self.array_to_pixmap(square_image)
            self.icon_image_label.setPixmap(self.img_ico_ecran.scaled(*self.IMAGE_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio))

            # QTimer pour retarder l'ouverture de la fenêtre de l'explorateur de 2 secondes (2000 ms)
            QTimer.singleShot(1000, lambda: self.open_save_dialog(square_image))
        except Exception as e:
            print("exception in convertImg2ico : ", e)

    def open_save_dialog(self, square_image):
        try:
            # code pour ouvrir la fenêtre de l'explorateur et sauver l'icone
            height, width, _ = square_image.shape
            # Enregistrement de  l'image carrée au format ICO
            # Construction  du chemin par défaut pour l'icône
            default_icon_path = self.DEFAULT_IMAGE_DIR + '/' + \
                                self.image_courante_path.rsplit('/', 1)[-1].rsplit('.', 1)[0] + '.ico'
            # Ouverture d'une boîte de dialogue pour permettre à l'utilisateur de choisir le nom et le dossier de destination
            icon_path, _ = QFileDialog.getSaveFileName(self, "Save Icon", default_icon_path,
                                                       "Icon files (*.ico);;All Files (*)")
            # Si l'utilisateur a choisi un nom de fichier, enregistrez l'image
            if icon_path:
                self.save_as_ico(square_image, icon_path)
                if icon_path != default_icon_path:
                    # Affiche une QMessageBox pour résumer la procédure si l'emplacement ou le nom ne sont pas ceux par défaut
                    self.show_info_message("IRdrone interactive utility v01", f"Le fichier a été sauvegardé avec succès.",
                                           f"Emplacement : {icon_path}", QMessageBox.Icon.Information)
        except Exception as e:
            print("open_save_dialog Ereur est: ", e)

    def make_square(self, image_array):
        # Ne pas simplifier car sinon problème d'arrondi avec les nombres impairs !
        height, width, _ = image_array.shape

        if height == width:  # Si l'image est déjà carrée
            return image_array
        if height > width:  # Si la hauteur est plus grande que la largeur
            diff = height - width
            top_crop = diff // 2
            bottom_crop = diff - top_crop
            return image_array[top_crop:-bottom_crop, :]
        else:  # Si la largeur est plus grande que la hauteur
            diff = width - height
            left_crop = diff // 2
            right_crop = diff - left_crop
            return image_array[:, left_crop:-right_crop]

    def save_as_ico(self, image_array, original_file_name):
        # Convertir le tableau numpy en une image PIL
        image = Image.fromarray(image_array)
        # Créer une nouvelle image ICO avec plusieurs tailles
        icon_filename = original_file_name.rsplit('.', 1)[0] + '.ico'
        with open(icon_filename, 'wb') as icon_file:
            image.save(icon_file, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

    def array_to_pixmap(self, array):
        """Convert numpy array to QPixmap."""
        """ inversion de canaux"""
        height, width, channel = array.shape
        bytesPerLine = 3 * width
        return QPixmap.fromImage(QImage(array.tobytes(), width, height, bytesPerLine, QImage.Format.Format_RGB888))

        # ==========================================================
        #
        # Procédures de gestion des fenêtres et boutons
        #
        # ==========================================================

    def show(self):
        super().show()
        self.center_on_screen()

    def reset_progress_bar(self):
        self.progress_bar.setValue(0)

    def center_on_screen(self):
        """Center the main window on the desired screen."""

        screens = QApplication.screens()
        if self.TARGET_SCREEN < len(screens):
            target_screen = screens[self.TARGET_SCREEN]
            screen_geometry = target_screen.availableGeometry()

            # Adjusting for screen
            max_image_height = screen_geometry.height() - self.SCREEN_ADJUST[self.TARGET_SCREEN]
            if self.IMAGE_DISPLAY_SIZE[1] > max_image_height:
                ratio = self.IMAGE_DISPLAY_SIZE[0] / self.IMAGE_DISPLAY_SIZE[1]
                new_width = int(max_image_height * ratio)
                self.resize(new_width, max_image_height)

            x = (screen_geometry.width() - self.width()) // 2 + screen_geometry.left()
            y = (screen_geometry.height() - self.height()) // 2 + screen_geometry.top() - 20
            self.move(x, y)
        else:
            print(f"Warning: Screen {self.TARGET_SCREEN} not found. Defaulting to primary screen.")
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
            self.move(x, y)

    def show_info_message(self, title, text, informativeText, icon):
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setText(text)
        msg_box.setInformativeText(informativeText)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def show_error_message(self, message):
        """Display an error message."""
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Icon.Critical)
        msgBox.setText(message)
        msgBox.setWindowTitle("Error")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
        msgBox.exec()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWin = ImageToIconeApp()
    mainWin.center_on_screen()  # Center the window on screen
    mainWin.show()
    sys.exit(app.exec())