# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   General utility
#   29/10/2023   V002   *
# ---------------------------------------------------------------------------------


import os
import os.path as osp
import sys
import json
from json import JSONDecodeError
import shutil
from datetime import datetime, date
import time
from typing import Any, Dict, Optional, Tuple, List, Union, Sequence, Iterable
from pathlib import Path
from fractions import Fraction
import re
import numpy as np
from fractions import Fraction
import tempfile
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from collections import Counter


import cv2
import matplotlib.pyplot as plt
import copy

from IRD_Interactive_color_style import Style
from config import OUTPUT_FOLDER_NAME


# -------------------- Exif Library -------------------------------
import piexif
import exifread
from PIL import Image
import rawpy
# -----------------------PyQt6 Library ----------------------------
from PyQt6.QtWidgets import QMessageBox, QApplication, QFileDialog, QWidget
# -----------------------------------------------------------------
from IRD_interactive_geo import geo2UTM
from IRD_Interactive_color_style import Style

sys.path.append(osp.join(osp.dirname(__file__), ".."))
import config as cf



class Prefrence_Screen:

    def __init__(self):
        super().__init__()
        self.current_directory = os.getcwd()
        # print("TEST  Current Directory:", self.current_directory)
        self.directory = os.path.abspath('/')
        self.directory = Path("~").expanduser().as_posix()
        # print("TEST  directory", self.directory)
        self.default_app_dir = os.path.join(self.directory, "Program Files", "IRdrone")
        self.default_user_dir = cf.OUTPUT_FOLDER_NAME
        self.verbose = True
        # setting to manage multiple screens
        self.defaultScreenID: int = 1  # Set to 0 for screen 1, 1 for screen 2, and so on
        self.screenAdjust = [0, 40]  # 40 for taskbar and
        self.windowDisplaySize = (800, 640)
        self.AerialPhotoFolder: str = "AerialPhotography"  # folder of images taken by VIS and NIR cameras
        self.AerialPhotoFolder_VIS: str = "AerialPhotography/VIS"  # folder of images taken by VIS and NIR cameras
        self.AerialPhotoFolder_NIR: str = "AerialPhotography/NIR"  # folder of images taken by VIS and NIR cameras
        self.AnalyticFolder: str = "FlightAnalytics"  # technical folder containing information on the mission
        self.ImgIRdroneFolder: str = "ImgIRdrone"  # folder of images processed by IRDrone
        self.SynchroFolder: str = "Synchro"  # folder for images from the camera synchronization phase
        self.MappingFolder: str = "mapping_MULTI"  # folder for image assembly with Open Drone Map
        self.CameraFolder: str = "cameras"  # here the “s” of cameras is obligatory. Used by ODM
        self.background_color = "white"
        self.txt_color = "black"

def parse_filename(file_name: str, allowed_suffix: Optional[Iterable[str]] = None) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Extract:
        - prefix (string before the last "_<digits>")
        - index (integer)
        - suffix (lowercase)

    Validates the suffix if allowed_suffix is provided.

    Returns:
        (prefix, index, suffix)
        If pattern does not match → index = None, prefix = None
        If suffix not allowed → suffix = None
    """
    p = Path(file_name)
    base = p.name
    img_suffix = p.suffix[1:].lower() if p.suffix else None  # suffix without "."

    # --- Validate suffix if whitelist provided ---
    if allowed_suffix is not None:
        allowed = {e.lower() for e in allowed_suffix}
        if img_suffix not in allowed:
            img_suffix = None  # suffix invalid

    # --- Extract prefix and number ---
    # Pattern: (prefix)_(digits).suffix
    match = re.search(r"^(.*)_(\d+)\.[^.]+$", base)
    if not match:
        return None, None, img_suffix

    prefix = match.group(1)
    index = int(match.group(2))

    return prefix, index, img_suffix

def show(widget):
    try:
        widget.show()
    except Exception as e:
        print("show error ", e)

def center_on_screen(widget, screen_Id: int = 0, screen_adjust=(1, 1), window_display_size=(800, 650)):
    try:
        screens = QApplication.screens()
        active_widget = QApplication.activeWindow()
        active_screen_id = QApplication.screens().index(active_widget.screen()) if active_widget else screen_Id
        if active_screen_id < len(screens):
            target_screen = screens[active_screen_id]
            screen_geometry = target_screen.availableGeometry()
            max_image_height = screen_geometry.height() - screen_adjust[0]

            if window_display_size[1] > max_image_height:
                ratio = window_display_size[0] / window_display_size[1]
                new_width = int(max_image_height * ratio)
                widget.resize(new_width, max_image_height)

            try:
                x = (screen_geometry.width() - widget.width()) // 2 + screen_geometry.left()
                y = (screen_geometry.height() - widget.height()) // 2 + screen_geometry.top() - screen_adjust[1]/2
                widget.move(x, y)
            except Exception as e:
                print("error 1  in center_on_screen :", e)
        else:
            print(f"Warning: Screen {active_screen_id} not found. Defaulting to primary screen.")
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            try:
                x = (screen_geometry.width() - widget.width()) // 2
                y = (screen_geometry.height() - widget.height()) // 2
                widget.move(x, y)
            except Exception as e:
                print("error 1  in center_on_screen :", e)
    except Exception as e:
        print("error in center_on_screen :", e)

def folder_name_consistency_analysis(folderMissionPath: str) -> bool:
    """
    Analyze the folder name for consistency with a predefined format.

    Parameters:
    - folderMissionPath (str): The file path to the folder to be analyzed.

    Returns:
    - bool: True if the folder name is consistent with the predefined format, False otherwise.

    Note:
    - The function extracts the folder name from the provided path and checks it against a predefined
      regular expression pattern to ensure it adheres to a specific format: "FLY-YYYYMMDD-HHMM-etc".
    - The date and time parts extracted from the folder name are checked for validity (i.e., whether they
      represent a valid date and time, respectively).
    - If the folder name adheres to the format and represents a valid date and time, the function returns True.
      Otherwise, it returns False.
    """
    coherent_response = False
    folder_name = os.path.basename(folderMissionPath)    # Extract the folder name from the path
    pattern = r"^FLY-(\d{8})-(\d{4})(-.*)?$"     # Define the regular expression pattern  (-.*) means all characters
    match = re.match(pattern, folder_name)       # Match the folder name with the pattern
    if match:
        date_part = match.group(1)    # Extract the date parts from the match
        time_part = match.group(2)    # Extract the time parts from the match
        try:
            # Check if the date part is a valid date
            # print(f'debug  in utils folder_name_consistency_analysis  date_part = {date_part} ')
            datetime.strptime(date_part, "%Y%m%d")
            # Check if the time part is a valid time
            if 0 <= int(time_part) <= 2359 and int(time_part[2:]) < 60:
                coherent_response = True
            else:
                print("Error in folder_name_consistency_analysis   Invalid time part in folder name.")
                pass
        except ValueError:
            print("Error in folder_name_consistency_analysis    Invalid date part in folder name.")
            pass
    else:
        print("Error in folder_name_consistency_analysis     Folder name does not match the expected pattern.")
        pass

    return coherent_response

def show_info_message(title: str, text: str, informativeText: str, icon=QMessageBox.Icon.Information):
    """
    Display an info message.
    :param title:
    :param text:
    :param informativeText:
    :param icon:
    :return:
    """
    try:
        msg_box = QMessageBox()
        msg_box.setIcon(icon)
        msg_box.setText(text)
        msg_box.setInformativeText(informativeText)
        msg_box.setWindowTitle(title)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()
    except Exception as e:
        print("error  in def show_info_message(self, title, text, informativeText, icon)", e)

def show_warning_OK_Cancel_message(title: str, text: str, informativeText: str, icon=QMessageBox.Icon.Warning):
    """
    Display an warning OK Cancel message.
    :param title:
    :param text:
    :param informativeText:
    :param icon:
    :return:
    """
    msg_box = QMessageBox()
    msg_box.setIcon(icon)
    msg_box.setText(text)
    msg_box.setInformativeText(informativeText)
    msg_box.setWindowTitle(title)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg_box.exec()

def show_error_message(message: str):
    """
    Display an error message.
    :param message:
    :return:
    """

    msgBox = QMessageBox()
    msgBox.setIcon(QMessageBox.Icon.Critical)
    msgBox.setText(message)
    msgBox.setWindowTitle("Error")
    msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
    msgBox.exec()

def image_takeoff_available_test(mission_parameters: dict, default_user_dir: Path):
    """

    :param mission_parameters:
    :param default_user_dir:
    :return:
    """
    try:
        image_takeoff_available = False
        path_image_mission = Path(default_user_dir)
        try:
            if isinstance(mission_parameters, dict) and 'File path mission' in mission_parameters:
                path_image_mission = Path(mission_parameters['File path mission'])
                if path_image_mission.exists():
                    coherent_response = folder_name_consistency_analysis(path_image_mission)
                    if coherent_response:
                        image_takeoff_available = True
        except (TypeError, KeyError) as e:
            print("Error in image_takeoff_available", e)
            pass
        return image_takeoff_available, path_image_mission
    except Exception as e:
        print("error   in image_takeoff_available", e)

# ---------------- dates ---------------------------------------

def datetimePy2datetimeJson(py_datetime: datetime) -> str:
    """
    Convert a Python datetime object (date & time ) to a string in JSON datetime format (Exif).

    Parameters:
    - py_datetime (datetime): A Python datetime object to be converted.

    Returns:
    - str: The input datetime as a string in JSON/Exif datetime format ('%Y:%m:%d %H:%M:%S').

    Note:
    - The function uses the strftime method to format the datetime in the '%Y:%m:%d %H:%M:%S' format,
      which is commonly used to represent times in JSON / EXIF.
    """
    return py_datetime.strftime('%Y:%m:%d %H:%M:%S')

def datetimeJson2datetimePy(json_str: str) -> datetime:
    """
    Convert a Python datetime object (date & time ) to a string in JSON datetime format (Exif).

    Parameters:
    - py_datetime (datetime): A Python datetime object to be converted.

    Returns:
    - str: The input datetime as a string in JSON/Exif datetime format ('%Y:%m:%d %H:%M:%S').

    Note:
    - The function uses the strftime method to format the time in the '%Y:%m:%d %H:%M:%S' format,
      which is commonly used to represent times in JSON / EXIF.
    """
    return datetime.strptime(json_str, '%Y:%m:%d %H:%M:%S')

def datePy2dateJson(py_date: datetime) -> str:
    """
    Convert a Python datetime object to a string in JSON date format.

    Parameters:
    - py_date (datetime): A Python datetime object to be converted.

    Returns:
    - str: The input date as a string in JSON date format ('%Y-%m-%d').

    Note:
    - The function uses the strftime method to format the date in the 'YYYY-MM-DD' format,
      which is commonly used to represent dates in JSON.
    - If the input is None, the function returns None.
    """
    return py_date.strftime('%Y:%m:%d')

def dateJson2datePy(json_str: str) -> date:
    """
    Convert a string representing a date in JSON format to a Python date object.

    Parameters:
    - json_str (str): A string representing a date in JSON format ('%Y-%m-%d').

    Returns:
    - date: The input string converted to a Python date object.

    Note:
    - The function uses the strptime method of the datetime class to parse the input string and
      convert it to a date object. The input string should be in 'YYYY-MM-DD' format.
    - If the input is None, the function returns None.
    """
    return datetime.strptime(json_str, '%Y:%m:%d').date()

def timePy2timeJson(py_time: time) -> str:
    """
    Convert a Python time object to a string in JSON time format.

    Parameters:
    - py_time (time): A Python time object to be converted.

    Returns:
    - str: The input time as a string in JSON time format ('%H:%M:%S').

    Note:
    - The function uses the strftime method to format the time in the 'HH:MM:SS' format,
      which is commonly used to represent times in JSON.
    """
    return py_time.strftime('%H:%M:%S')

def timeJson2timePy(json_str: str) -> time:
    """
    Convert a string representing a time in JSON format to a Python time object.

    Parameters:
    - json_str (str): A string representing a time in JSON format ('%H:%M:%S').

    Returns:
    - time: The input string converted to a Python time object.

    Example usage:
    - loaded_data = json.load(file)
    - py_time = timeJson2timePy(loaded_data["Hour"])

    Note:
    - The function uses the strptime method of the datetime class to parse the input string and
      convert it to a time object. The input string should be in 'HH:MM:SS' format.
    - If the input is None, the function returns None.
    """
    return datetime.strptime(json_str, '%H:%M:%S').time()

def extract_date_RAW_SJCam(fileName: str) -> tuple:
    """
    Extract shooting number and shooting date from a RAW or JPG file name.

    :param fileName: The file name with suffix.
    :type fileName: str
    :return: A tuple containing the shooting number (int) and shooting date (datetime).
    """
    prefix, index, suffix = parse_filename(fileName, allowed_suffix=["raw", "jpg"])
    shootingNumber, shootingDate = -9999, None
    try:
        if suffix:
            if suffix.lower() == "raw":
                if index:
                    shootingNumber = int(index + 1)
                else:
                    print(Style.RED + f'Error {fileName} incompatible' + Style.RESET)

            elif suffix.lower() == "jpg":
                if index:
                    shootingNumber = int(index)
                else:
                    print(Style.RED + f'Error {fileName} incompatible' + Style.RESET)
            else:
                shootingNumber = int(index)

            # Extract year, month, day, hour, minute, and second from the file name
            year = int(prefix[0:4])
            month = int(prefix[5:7])
            day = int(prefix[7:9])
            hour = int(prefix[10:12])
            minute = int(prefix[12:14])
            second = int(prefix[14:16])
            # Create a datetime object for the shooting date
            shootingDate = datetime(year, month, day, hour, minute, second)
            return shootingNumber, shootingDate

    except Exception as e:
        print(Style.RED + f'error in extract_date_RAW_SJCam   {fileName} incompatible.   {e}' + Style.RESET)
        return shootingNumber, shootingDate

def extract_num_DNG_DJI(fileName: str) -> tuple:
    """
    Extract shooting number and shooting date from a DNG file name.

    :param fileName: The file name with suffix.
    :type fileName: str
    :return: A tuple containing the shooting number (int) and shooting date (datetime).
    """
    prefix, index, suffix = parse_filename(fileName, allowed_suffix=["dng"])
    shootingNumber = -9999
    try:
        if suffix:
            if suffix.lower() == "dng":
                if index:
                    shootingNumber = int(index)
                else:
                    print(Style.RED + f'Error {fileName} incompatible' + Style.RESET)
            return shootingNumber

    except Exception as e:
        print(Style.RED + f'error in extract_num_DNG_DJI   {fileName} incompatible.   {e}' + Style.RESET)
        return -9999



    if fileName.split(".")[1].lower() in ["dng"]:
        temp = fileName.split(".")[0].split("_")[1]
        shootingNumber = int(temp)
        return shootingNumber

    # Return None values if the file suffix is not RAW or JPG
    return None, None

# ------------------   GPS

def gps_coordinate_to_float(gps_coordinate: str) -> float:
    """
    Convert a GPS coordinate (Exif dng DJI) in the format 'DD deg MM' SS.SS\" D' to a floating point number.
    If the direction is N or W, the value is positive. If the direction is S or E, the value is negative.

    Example usage:  coord_str = "45 deg 10' 12.74\" N"
                    decimal_coord = gps_coordinate_to_float(coord_str)
                    print(decimal_coord)   # 45.17020556
    """
    # Replacing 'deg' with space and splitting the string
    parts = gps_coordinate.replace('deg', '').split()
    if len(parts) != 4 or parts[1][-1] != '\'' or parts[2][-1] != '"' or parts[3] not in ('N', 'S', 'E', 'W'):
        raise ValueError("Invalid GPS coordinate string format")

    # Extracting degrees, minutes, seconds, and direction
    degrees = float(parts[0])
    minutes = float(parts[1][:-1])  # Removing the apostrophe '
    seconds = float(parts[2][:-1])  # Removing the double quote "
    direction = parts[3]

    # Converting to float
    decimal_coord = degrees + minutes / 60 + seconds / 3600

    # Adjusting for direction
    if direction in ['S', 'W']:
        decimal_coord = -decimal_coord

    return decimal_coord

def extract_exif(file_path: str) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract EXIF metadata from a file, either in DNG or JPEG format.

    Parameters:
    - file_path (str): The path to the file from which to extract EXIF data.

    Returns:
    - tuple[Optional[any], Optional[any], Optional[any], Optional[str], Optional[str], Optional[str], Optional[str]]:
      A tuple containing latitude, longitude, altitude, date_time, maker, model, and id_camera, respectively.
      The types of latitude, longitude, and altitude are not strictly defined because they depend on the format
      in which they are stored in the EXIF data, which may vary. The other returned values are strings or None
      if the corresponding data is not found in the EXIF data.

    Note:
    - The function can handle both DNG and JPEG file formats.
    - It extracts and returns the geographical coordinates (latitude, longitude, altitude), the date and time of
      the image capture, and information about the camera (maker, model, and id_camera) from the EXIF metadata.
    - Different methods are used to extract EXIF data from DNG and JPEG files due to their different formats.
    - The altitude returned from DNG files may be relative to the take-off point of the drone.
    """
    latitude = longitude = altitude = date_time = None
    maker = model = id_camera = None

    with open(file_path, 'rb') as f:
        if file_path.lower().endswith(".dng"):
            # Use exifread to read EXIF data from DNG files
            tags = exifread.process_file(f)
            # display_dictionary(tags, indentation="")  # Displays the dictionary to examine the available keys and see the values.

            # Extract drone and camera data
            maker = str(tags.get('Image Make', None))
            model = str(tags.get('Image Model', None))
            id_camera = str(tags.get('EXIF BodySerialNumber', None))

            # Extracts location and date/time data
            latitude = tags.get('GPS GPSLatitude', None)
            longitude = tags.get('GPS GPSLongitude', None)
            altitude = tags.get('GPS GPSAltitude', None)
            date_time = str(tags.get('Image DateTime', None))

        elif file_path.lower().endswith(".jpg"):
            # Loads JPEG file and extracts EXIF metadata
            exif_dict = piexif.load(file_path)

            # Extracts location and date/time data
            if piexif.GPSIFD.GPSLatitude in exif_dict['GPS']:
                latitude = exif_dict['GPS'][piexif.GPSIFD.GPSLatitude]

            if piexif.GPSIFD.GPSLongitude in exif_dict['GPS']:
                longitude = exif_dict['GPS'][piexif.GPSIFD.GPSLongitude]

            if piexif.GPSIFD.GPSAltitude in exif_dict['GPS']:
                altitude = exif_dict['GPS'][piexif.GPSIFD.GPSAltitude]  # Attention...Altitude relative to the take-off point!

            if piexif.ExifIFD.DateTimeOriginal in exif_dict['Exif']:
                date_time = exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal].decode('utf-8')

    return latitude, longitude, altitude, date_time, maker, model, id_camera

def convert_coordinates(latitude, longitude, altitude) -> tuple[float, float, float]:
    """
    Convert geographical coordinates to decimal format.

    Parameters:
    - latitude : Latitude in IFD tag format to be converted to decimal format.
    - longitude : Longitude in IFD tag format to be converted to decimal format.
    - altitude : Altitude in IFD tag format to be converted to decimal format.

    Returns:
    - tuple[float, float, float]: A tuple containing the latitude, longitude, and altitude
                                  in decimal format, respectively.

    Note:
    - This function relies on the helper function `ifdtag_to_decimal`, which should convert
      IFD tag formatted geographical coordinates into decimal format.
    - For the altitude, it strips brackets from the input string, converts it to a fraction,
      and then to a float in decimal format.
    """
    lat_decimal = ifdtag_angle_to_decimal(latitude)
    lon_decimal = ifdtag_angle_to_decimal(longitude)
    alt_decimal = ifdtag_altitude_to_decimal(altitude)

    return lat_decimal, lon_decimal, alt_decimal

def convert_dng_coordinates(latitude, longitude, altitude) -> tuple[float, float, float]:
    """
    """
    lat_decimal = dng_angle_to_decimal(latitude)
    lon_decimal = dng_angle_to_decimal(longitude)
    alt_decimal = ifdtag_altitude_to_decimal(altitude)

    return lat_decimal, lon_decimal, alt_decimal

def ifdtag_angle_to_decimal(ifdtag) -> float:
    """
    Convert geographical coordinates from IFD tag format to decimal format.

    Parameters:
    - ifdtag (object): An object containing the IFD tag values to be converted to decimal format.
                       The function expects the values to be accessible via the `values` attribute
                       of the input object, and to be representable as a string in the format "[a, b/c, d]".

    Returns:
    - float: The geographical coordinate in decimal format.

    Usage:
    - The function first converts the IFD tag values to a string, strips brackets, and splits
      the string into parts.
    - Each part is converted to a Fraction object if it represents a fraction (contains '/'),
      otherwise it is converted to an integer.
    - A helper function `dms_to_decimal` (which should be defined elsewhere in the code) is
      then called with the converted values to obtain the final decimal coordinate.
    """
    if ifdtag:
        str_values = str(ifdtag.values).strip("[]")
        values = [Fraction(part) if '/' in part else int(part) for part in str_values.split(", ")]
        return dms_to_decimal(values)
    else:
        return None

def dng_angle_to_decimal(angle: str) -> float:

    if angle:
        str_values = str(angle).strip("[]")
        values = [Fraction(part) if '/' in part else int(part) for part in str_values.split(", ")]
        return dms_to_decimal(values)
    else:
        return None

def dms_to_decimal(dms: list[Union[int, Fraction]]) -> float:
    """
    Convert geographical coordinates from Degrees, Minutes, Seconds (DMS) format to decimal format.

    Parameters:
    - dms (List[Union[int, Fraction]]): A list containing the degree, minute, and second values
                                       as integers or fractions.

    Returns:
    - float: The geographical coordinate in decimal format.

    Usage:
    - The function expects a list of three elements: [degrees, minutes, seconds].
    - It converts the DMS values to decimal format using the formula:
      decimal_degrees = degrees + (minutes / 60) + (seconds / 3600)
    """

    # Ensure the input list has exactly three values
    if len(dms) != 3:
        raise ValueError("Input list must contain exactly three values: [degrees, minutes, seconds].")

    degrees, minutes, seconds = dms

    # Convert DMS to decimal
    decimal_degrees = float(degrees) + float(minutes) / 60 + float(seconds) / 3600

    return decimal_degrees

def ifdtag_altitude_to_decimal(ifdtag) -> float:
    """
    Convert geographical altitude from IFD tag format to decimal format.

    Parameters:
    - ifdtag (object): An object containing the IFD tag values to be converted to decimal format.
                       The function expects the values to be accessible via the `values` attribute
                       of the input object, and to be representable as a string in the format "[a, b/c, d]".

    Returns:
    - float: The geographical altitude in decimal format.

    """
    if ifdtag:
        alt_decimal = float(Fraction(str(ifdtag).strip("[]")))
    else:
        alt_decimal = None
    return alt_decimal

def display_dictionary(dictionary: dict[str, any], indentation=""):
    """
    This function recursively prints the contents of a dictionary, handling nested
    dictionaries and lists, with indentation to reflect the nesting level.

    Parameters:
    - dictionary (dict): The dictionary to display.
    - indentation (str): A string representing the current level of indentation
                         (initially empty, increases with nesting level).

    Usage:
    - If the value associated with a key is a dictionary, the function calls itself
      recursively to print the nested dictionary, increasing the indentation.
    - If the value is a list, it iterates through the list and prints each item,
      handling nested dictionaries within the list by recursive calls, and increasing
      the indentation appropriately.
    - Otherwise, it simply prints the key-value pair.
    """
    for key, value in dictionary.items():
        # Check if the value is a dictionary
        if isinstance(value, dict):
            print(f"{indentation}{key}:")
            # Recursive call with increased indentation
            display_dictionary(value, indentation + "    ")
        # Check if the value is a list
        elif isinstance(value, list):
            print(f"{indentation}{key}:")
            for i, item in enumerate(value):
                print(f"{indentation}    Item {i}:")
                # Check if the item within the list is a dictionary
                if isinstance(item, dict):
                    # Recursive call with further increased indentation
                    display_dictionary(item, indentation + "        ")
                else:
                    print(f"{indentation}        {item}")
        # If the value is neither a dictionary nor a list, print key-value pair
        else:
            print(f"{indentation}{key}: {value}")

def display_dictionary_EXIF_jpg(exif_dict: dict[str, any], tag_type=None, indentation="", verbose=False) -> dict[str, any]:
    dic_exif_utf = {}
    for key, value in exif_dict.items():
        readable_key = key

        # Si key est un entier, essayez de le convertir en une clé lisible
        if isinstance(key, int) and tag_type:
            readable_key = piexif.TAGS[tag_type][key]["name"] if key in piexif.TAGS[tag_type] else key

        # Si la valeur est un dictionnaire, appelez la fonction récursivement avec le tag_type approprié
        if isinstance(value, dict):
            if verbose: print(f"{indentation}{readable_key}:")
            new_tag_type = tag_type  # Par défaut, conservez le tag_type actuel pour les sous-dictionnaires
            if key in ["0th", "Exif", "GPS", "1st", "Interop", "thubnail"]:
                new_tag_type = key
            dic_exif_utf[readable_key] = display_dictionary_EXIF_jpg(value, new_tag_type, indentation + "    ", verbose=verbose)
        elif isinstance(value, list):
            if verbose: print(f"{indentation}{readable_key}:")
            list_content = []
            for i, item in enumerate(value):
                if verbose: print(f"{indentation}    Item {i}:")
                if isinstance(item, dict):
                    list_content.append(display_dictionary_EXIF_jpg(item, tag_type, indentation + "        ", verbose=verbose))
                else:
                    if verbose: print(f"{indentation}        {item}")
                    list_content.append(item)
            dic_exif_utf[readable_key] = list_content
        else:
            value_print = value
            if isinstance(value, bytes):
                try:
                    # Essayez de décoder en utf-8
                    decoded_value = value.decode('utf-8')
                    # Vérifiez si la valeur décodée semble être du texte lisible
                    if all(32 <= ord(c) <= 126 for c in decoded_value):
                        value_print = decoded_value
                    else:
                        value_print = value  # Conservez la représentation binaire brute
                except UnicodeDecodeError:
                    value_print = value  # Conservez la représentation binaire brute
            if verbose: print(f"{indentation}{readable_key}: {value_print}")
            dic_exif_utf[readable_key] = value

    return dic_exif_utf

def get_filesystem_metadata(image_path: str) -> dict:
    p = Path(image_path)

    return {
        "FileName": p.name,
        "FileSize": p.stat().st_size,
        "FileCreationDate": time.ctime(p.stat().st_ctime),
        "FileLastModifiedDate": time.ctime(p.stat().st_mtime),
    }

def bytes2utf(value):
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8')
        except UnicodeDecodeError:
            # Gestion de l'erreur ou utilisation de la byte-string telle quelle
            pass
    return value

def ecriture_donnees_EXIF():
    # ceci est un exemple à étudier ....................
    import piexif

    # Créer un dictionnaire EXIF de base.
    exif_dict = {"0th": {piexif.ImageIFD.Make: b"CameraBrand",
                         piexif.ImageIFD.Model: b"CameraModel"},
                 "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2022:10:07 10:00:00"},
                 "1st": {},
                 "thumbnail": None}

    # Convertir le dictionnaire EXIF en octets.
    exif_bytes = piexif.dump(exif_dict)

    # Ecrire les données EXIF dans une image.
    piexif.insert(exif_bytes, "path_to_output_image.jpg")

def extract_exif_data(file_path: str) -> dict[str, any]:
    """
    Extract and return EXIF data from a DNG file.

    :param file_path: str, path to the DNG file.
    :return: dict[str, any], extracted EXIF data.
    """
    exif_data = {}

    # Open the image file and extract the EXIF data
    with open(file_path, 'rb') as f:
        exif_data = exifread.process_file(f)

    return exif_data

def display_exif_data(exif_data: dict[str, any], indentation="", verbose=False) -> dict[str, any]:
    """
    Recursively display and return EXIF data.

    :param exif_data: dict[str, any], the EXIF data to display.
    :param indentation: str, the current indentation level for display.
    :return: dict[str, any], a new dictionary with readable EXIF data.
    """
    dic_exif_utf = {}

    for key, value in exif_data.items():
        # Check and format value if it's bytes
        formatted_value = value.printable if hasattr(value, 'printable') else value

        # Print the key-value pair
        if verbose: print(f"{indentation}{key}: {formatted_value}")

        # Add to new dictionary
        dic_exif_utf[key] = formatted_value

    return dic_exif_utf

def format_number(number, decimal=3, car=" "):
    format_string = f"{car}{{:.{decimal}f}}" if number >= 0 else f"{{:.{decimal}f}}"
    return format_string.format(number)


# ----------------------   A priori calculation of the pitch, yaw & roll "coarse".  -----------------------------------

def motion_in_DroneAxis(listPts, mute=True):
    """
    Geographical axes:
        e_EW vector  West > East          |e_EW|=1
        e_SN vector  South > North        |e_SN|=1     e_EW . e_SN = 0  ; warning Clockwise  (e_z downwards!)
    Axe orientation  e_EW <=> West > East ,   e_SN <=> South > North
                    nord > 0°  ;  east > 90°  ;  south > 180°  ;  west > 270°

    Axes of the drone:
        e_1  vector normal to the axis of the drone       |e_1|=1
        e_2  vector of the axis of the drone (forward)    |e_2|=1  ;  e_1 . e_2 =0
        e_3 = e_1 x e_2 .        Counterclockwise ( e_3 upwards ).

    x_1  distance travelled along the e_1 axis
    x_2  distance travelled along the drone axis
    x_3  distance travelled along the vertical axis.
    """
    x_WE, y_SN = motionDrone_in_GeographicAxis(listPts, mute=mute)  # motion in geographic axis
    for i in range(len(listPts)):
        sin_Yaw = np.sin(np.deg2rad(listPts[i].yawDrone))
        cos_Yaw = np.cos(np.deg2rad(listPts[i].yawDrone))
        listPts[i].x_1 = -x_WE[i] * cos_Yaw + y_SN[i] * sin_Yaw
        listPts[i].x_2 = x_WE[i] * sin_Yaw + y_SN[i] * cos_Yaw

    motionDroneZaxis(listPts)

    return

def motionDrone_in_GeographicAxis(listPt, mute=True):
    """
    Vector decomposition:
        D = x_EW * e_EW + y_SN * e_SN
        |e_EW| = 1, |e_SN| = 1, e_EW · e_SN = 0

    Axis orientation:
        e_EW: West → East
        e_SN: South → North

               N
               ↑
               │ e_SN
               │
               │        e_EW
         W ────┼──────────────→ E
               │
               S
    """
    x_WE, y_SN = [], []
    for i in range(len(listPt)):
        if i >= len(listPt) - 1:
            distWE = float(listPt[-1].gpsUTM_X) - float(listPt[-2].gpsUTM_X)
            distSN = float(listPt[-1].gpsUTM_Y) - float(listPt[-2].gpsUTM_Y)
        else:
            distWE = float(listPt[i + 1].gpsUTM_X) - float(listPt[i].gpsUTM_X)
            distSN = float(listPt[i + 1].gpsUTM_Y) - float(listPt[i].gpsUTM_Y)

        x_WE.append(distWE)
        y_SN.append(distSN)
        if not mute:
            print('point N° ', i, '   x_WE = ', distWE, ' m    y_SN = ', distSN, ' m    distance ',
                  (distWE ** 2 + distSN ** 2) ** 0.5)

    return x_WE, y_SN

def motionDroneZaxis(listPts):
    listPts[-1].x_3 = 0.
    for i in range(0, len(listPts) - 1):
        listPts[i].x_3 = (listPts[i + 1].altGround - listPts[i].altGround) + (listPts[i + 1].altGeo - listPts[i].altGeo)

def theoreticalIrToVi(listPts, timelapse_Vis, offset=None):
    #   theoretical  Yaw
    angle = [listPts[n].rollDrone for n in range(len(listPts))]
    x = [listPts[n].x_1 for n in range(len(listPts))]
    theoreticalYaw = theoreticalAngleDeviation(listPts, angle, x, timelapse_Vis, axe=1)
    #   theoretical  Pitch
    angle = [listPts[n].pitchDrone for n in range(len(listPts))]
    x = [listPts[n].x_2 for n in range(len(listPts))]
    theoreticalPitch = theoreticalAngleDeviation(listPts, angle, x, timelapse_Vis, axe=2)
    #   Theoretical  Roll
    #   It is assumed that the "gimbal-lock" mode is used.  In other words gimbal_Yaw=drone_Yaw .
    #   Note : the gimbal’s yaw angle is not reliable when the "gimbal-lock" mode is used.
    theoreticalRoll = rollDeviation(listPts, timelapse_Vis)


    for i in range(len(listPts)):
        try:
            theoreticalYaw[i] = theoreticalYaw[i] + offset[0]
            theoreticalPitch[i] = theoreticalPitch[i] + offset[1]
            theoreticalRoll[i] = theoreticalRoll[i] + offset[2]
        except Exception as e:
            print("Error in theoreticalIrToVi:", e)
            pass
        listPts[i].yawIR2VI = theoreticalYaw[i]
        listPts[i].pitchIR2VI = theoreticalPitch[i]
        listPts[i].rollIR2VI = theoreticalRoll[i]

    return listPts, theoreticalPitch, theoreticalYaw, theoreticalRoll

def add_offset_theoretical_angles(list_pts, offset=None):
    if offset is None:
        return
    for idx in range(len(list_pts)):
        list_pts[idx].yawIR2VI += offset[0]
        list_pts[idx].pitchIR2VI += offset[1]
        list_pts[idx].rollIR2VI += offset[2]

def theoreticalAngleDeviation(listPts, angle, x, timelapse_Vis, axe=0):
    """
    u  composante du déplacement    x = dist . e_idx
    idx=1    Yaw    (le roll du drone correspond au yaw de la caméra NIR!)
    idx=2    Pitch  (attention offset de 90° pour le DJI)
    e_2  vecteur de l'axe du drone (vers l'avant)    |e_2|=1
    e_1  vecteur normal à l'axe du drone    |e_1|=1  ;  e_1 . e_2 =0 ; repère direct

    The distance between the lenses of two cameras (DJI Mavic Air 2 and SJCam M20) is CNIRCVIS_0 = 46 mm.
    This distance is not negligible if the drone is at very low altitude.
    For example during the synchronization step the drone is 2 m above the ground.
    This distance must be added to the projection of the base line on the axis of the drone (Axis 2) for the
    calculation of the pitch.
    """
    theoreticalAngle = []
    for i in range(len(listPts)):
        alpha, dt = interpolParabolicAngle(listPts, angle, i, timelapse_Vis)
        Cvi_t_Cvi_tk = interpolationCameraCenterVis(x, i, dt, timelapse_Vis)  # Algebraic !!!
        H = listPts[i].altGround
        if axe == 1:
            thetaVis = listPts[i].rollGimbal  # Roll Gimbal <=>  Yaw Camera VIS
            baseline = Cvi_t_Cvi_tk
        else:
            thetaVis = listPts[i].pitchGimbal + 90.  # Pitch Gimbal <=> Pitch Camera VIS
            baseline = Cvi_t_Cvi_tk + cf.CNIRCVIS_0

        anglePhi = np.rad2deg(np.arctan(baseline / H + np.tan(np.deg2rad(thetaVis))))
        anglePsi = anglePhi - alpha
        theoreticalAngle.append(anglePsi)

    return theoreticalAngle

def rollDeviation(listPts, timelapse_Vis):
    """
    yaw drone  <=> roll NIR camera
    yaw gimbal <=> roll VIS camera     is totally wrong if DJI "gimbal-lock" mode is used!

    In "Gimbal lock" mode the information provided by the DJI drone about the gimbal’s yaw angle is not reliable.
    We make the hypothesis (reasonable) that the gimbal is aligned on the axis of the drone.
    The roll angle of the near infrared image (NIR) is obtained by interpolation of the yaw angle of the drone.
    The "roll image" between the visible (VIS) and near infrared (NIR) images is obtained by difference between
    the yaw angle of the drone (at the moment of the VIS shooting) and the roll angle of the NIR image.
    Added to this is the roll offset caused by the misalignment of the infrared camera in relation to the drone’s longitudinal axis.

    """
    yaw_tVis = [listPts[n].yawDrone for n in range(len(listPts))]
    theoreticalRoll = []
    for i in range(len(listPts)):
        yaw_tNir, dt = interpolParabolicAngle(listPts, yaw_tVis, i, timelapse_Vis)
        rollNir2Vis = yaw_tVis[i] - yaw_tNir
        theoreticalRoll.append(rollNir2Vis)

    return theoreticalRoll

def interpolParabolicAngle(listPts, angle, i, timelapse_Vis):
    """
        Parabolic interpolation of the drone angle at the moment (t) the NIR image was taken.
        dt = t0-t with t0 : date camera VIS and  t : date camera NIR.
        If k is index of t0 = tk then t_1 = tk-1 ; t1 = tk+1 etc.
        t_1 <= t <= t1
        "Forward" interpolation if dt<0.
    """
    dt = listPts[i].timeDeviation
    try:
        t_2 = listPts[i - 2].timeLine
        t_1 = listPts[i - 1].timeLine
        t0 = listPts[i].timeLine
        t1 = listPts[i + 1].timeLine
        t2 = listPts[i + 2].timeLine
        t = t0 - dt
        if t_1 <= t <= t1:
            alpha = Parabolic(listPts, angle, i, t)
        elif t_2 <= t <= t_1:
            alpha = Parabolic(listPts, angle, i-1, t)
        elif t1 <= t <= t2:
            alpha = Parabolic(listPts, angle, i+1, t)
        else:
            alpha, dt = interpolLinearAngle(listPts, angle, i, timelapse_Vis)

    except (IndexError, ValueError):
        alpha, dt = interpolLinearAngle(listPts, angle, i, timelapse_Vis)

    return alpha, dt

def Parabolic(listPts, angle, k, t):
    t_1 = listPts[k - 1].timeLine
    t0 = listPts[k].timeLine
    t1 = listPts[k + 1].timeLine
    d_1 = (angle[k - 1] - angle[k]) / (t_1 - t0)
    d1 = (angle[k + 1] - angle[k]) / (t1 - t0)
    a = (d_1 - d1) / (t_1 - t1)
    b = d_1 - a * (t_1 + t0)
    c = angle[k] - a * t0**2 - b * t0
    alpha = a * t**2 + b * t + c
    return alpha

def interpolLinearAngle(listPts, angle, i, timelapse_Vis):
    """
    Linear interpolation of the drone angle at the moment the NIR image was taken.
    dt = tk-t with tk : date camera VIS and  t : date camera NIR.
    "Forward" interpolation if dt<0.
    """
    dt = listPts[i].timeDeviation
    if i == 1 or i == len(listPts) - 1:
        alpha = angle[i]
    elif dt < 0:
        alpha = (angle[i] * (dt / timelapse_Vis + 1) - angle[i + 1] * dt / timelapse_Vis)
    else:
        alpha = (angle[i - 1] * dt / timelapse_Vis - angle[i] * (dt / timelapse_Vis - 1))
    return alpha, dt

def interpolationCameraCenterVis(x, k, dt, timelapse_Vis):
    """
    DeltaCvis =(Cvis_t Cvis_tk) is the distance ( algebraic) between the center Cvis_t of the Vis  camera at  time t
    and the center Cvis_tk of the Vis camera at time tk. Linear interpolation of the base line is used..
    A simple rule of three is used since x is directly the distance travelled during the period of the VIS timelapse.
    TimeDeviation :   dt = (tk - t)  .
                  > tk Date of the image  VIS
                  > t  Date of nearest NIR image.
    The dates are measured on the time-line (synchronized clocks).
    x_k is the distance (Cvis(k+1)  Cvis(k)). This  distance is > 0  if drone flight forward and < 0 if backward.

    "Forward" interpolation if dt<0.

    Taking into account the possibility of a missing NIR image in the time lapse series.
    (The phenomenon is related to a recording fault on the SD card of the SJCam M20 camera.)

    """
    try:
        if dt < 0:
            if abs(dt) > timelapse_Vis:
                DeltaCvis = (x[k + 1] - x[k]) + x[k + 1] * (dt / timelapse_Vis)
            else:
                DeltaCvis = x[k] * (dt / timelapse_Vis)
        else:
            if dt > timelapse_Vis:
                DeltaCvis = (x[k - 1] - x[k - 2]) + x[k - 2] * (dt / timelapse_Vis)
            else:
                DeltaCvis = x[k - 1] * (dt / timelapse_Vis)
    except (IndexError, ValueError):
        DeltaCvis = 0

    return DeltaCvis


def interpolate_scalar_with_extrapolation(
    t_vis,
    x_vis,
    t_target,
):
    """
    Interpolation ou extrapolation linéaire d'une grandeur scalaire.

    - interpolation si t_target ∈ [t_vis[0], t_vis[-1]]
    - extrapolation linéaire sinon (bords)

    Parameters
    ----------
    t_vis : array-like (n,)
        Timeline VIS strictement croissante
    x_vis : array-like (n,)
        Valeurs VIS correspondantes
    t_target : float
        Temps cible

    Returns
    -------
    value : float
    mode : str
        'interpolation', 'extrapolation_left', 'extrapolation_right'
    """
    t_vis = np.asarray(t_vis, dtype=float)
    x_vis = np.asarray(x_vis, dtype=float)

    n = len(t_vis)
    if n < 2:
        return None, "invalid"

    # ---- extrapolation gauche
    if t_target <= t_vis[0]:
        t0, t1 = t_vis[0], t_vis[1]
        x0, x1 = x_vis[0], x_vis[1]
        mode = "extrapolation_left"

    # ---- extrapolation droite
    elif t_target >= t_vis[-1]:
        t0, t1 = t_vis[-2], t_vis[-1]
        x0, x1 = x_vis[-2], x_vis[-1]
        mode = "extrapolation_right"

    # ---- interpolation
    else:
        i1 = np.searchsorted(t_vis, t_target)
        i0 = i1 - 1
        t0, t1 = t_vis[i0], t_vis[i1]
        x0, x1 = x_vis[i0], x_vis[i1]
        mode = "interpolation"

    if t1 == t0:
        return x0, mode

    alpha = (t_target - t0) / (t1 - t0)
    value = (1.0 - alpha) * x0 + alpha * x1

    return float(value), mode


# ----------------------time line


def save_time_line_json(
        output_dir: Union[str, Path],
        *timeline_dicts: Dict[str, List[Dict]]
) -> Path:
    """
    Save multiple timelines (VIS, NIR, etc.) into a single JSON file.

    Example of usage:
        save_time_line_json(output_dir, vis_timeline, nir_timeline)

    The final JSON file will have the structure:
    {
        "VIS": [ ... ],
        "NIR": [ ... ]
    }
    """
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file: Path = output_dir / "time_line.json"

        # Merge all timeline dictionaries by spectral band key
        merged: dict[str, list[dict]] = {}
        for d in timeline_dicts:
            merged.update(d)

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=4, ensure_ascii=False)

        print(Style.GREEN + f"💾 JSON file saved: {out_file}" + Style.RESET)
    except Exception as e:
        print(f'error in (Uti)   save_time_line_json   {e}')
    return out_file

def safe_path(path: Union[str, Path]) -> Path:
    try:
        return Path(path).resolve()
    except Exception as e:
        print(f"[safe_path] Invalid path {path} : {e}")
        return Path(path)

def _format_duration(seconds: float) -> str:
    """
    Returns a human-readable string representing the duration.
    - For durations longer than 5 minutes, display in minutes with one decimal.
    - For shorter durations, display in seconds as an integer.
    Parameters
    ----------
    seconds : float    Duration in seconds.
    Returns
    -------
    str Formatted duration as a string, e.g. "3 s" or "5.2 min".
    """
    if seconds > 300:  # more than 5 minutes
        return f"{seconds / 60:.1f} min"
    else:
        return f"{seconds:.0f} s"

def choose_folder_mission(
    mission_parameters: dict,
    pref_screen_default_user_dir: str,
    AerialPhotoFolder: str,
    SynchroFolder: str
) -> Tuple[Path, bool]:
    """
    Choose the mission folder for IRDrone images.

    This function checks whether a takeoff image is available. If yes, it uses
    the folder indicated in mission_parameters['File path mission'] and checks its consistency.
    Otherwise, it prompts the user to select a mission folder manually via a dialog.

    Parameters
    ----------
    mission_parameters : dict
        Dictionary containing takeoff information including the mission file path.
    pref_screen_default_user_dir : str
        Default directory to open for folder selection dialog.
    AerialPhotoFolder : str
        Name of the folder to store aerial photos.
    SynchroFolder : str
        Name of the folder to store synchronization images.

    Returns
    -------
    Tuple[Path, bool]
        folderMissionPath: Path object pointing to the selected mission folder
        coherent_response: Boolean indicating if the folder name is consistent
    """
    try:
        image_takeoff_available, path_image_takeoff = image_takeoff_available_test(mission_parameters, pref_screen_default_user_dir)

        if image_takeoff_available:
            # --- Construct the mission folder path ---
            folderMissionPath = Path(mission_parameters['File path mission'])
            coherent_response = folder_name_consistency_analysis(folderMissionPath)

            if coherent_response:
                show_info_message(
                    "IRDrone",
                    f"Your images will be transferred to the mission folder:\n{folderMissionPath}",
                    f"They will be distributed in the folder {AerialPhotoFolder}/VIS "
                )
            else:
                coherent_response = False

            return folderMissionPath, coherent_response

        else:
            # --- Ask user to choose a mission folder ---
            show_warning_OK_Cancel_message(
                "IRDrone",
                "Choose the mission folder.",
                "It should follow the format: FLY_YearMonthDay_hourminute_[Place]",
                QMessageBox.Icon.Information
            )
            try:
                folderMissionPath = Path(QFileDialog.getExistingDirectory('Select Mission Folder', pref_screen_default_user_dir))

                if folderMissionPath.exists() and folderMissionPath != pref_screen_default_user_dir:
                    coherent_response = folder_name_consistency_analysis(folderMissionPath)
                    if not coherent_response:
                        show_warning_OK_Cancel_message(
                            "IRDrone",
                            f"You have chosen the folder:\n{folderMissionPath}\nwhich is not a Mission IRDrone folder.",
                            "Choose a compatible folder (name FLY_YYYYMMDD_hhmm_<free text>) or create a new mission using the <Create a New Mission> command."
                        )
                else:
                    show_warning_OK_Cancel_message(
                        "IRDrone",
                        f"You have chosen the folder:\n{folderMissionPath}\n",
                        "Your choice of folder is not recognized in IRDrone.\nChoose a compatible folder (name FLY_YYYYMMDD_hhmm_[Optional text])."
                    )
                    coherent_response = False

                return folderMissionPath, coherent_response

            except Exception as e:
                print("Error 1 in choose_folder_mission:", e)

    except Exception as e:
        print("Error 2 in choose_folder_mission:", e)

def choose_mission_folder_phase_2(
    parent: Optional[QWidget] = None,
    default_user_dir: Union[str, Path] = OUTPUT_FOLDER_NAME,
    verbose: bool = False
):
    """
    Open a folder selection dialog and validate the selected IRDrone mission folder.

    Returns
    -------
    (Path | None, bool)
        - Path to the selected folder (or None if cancelled)
        - coherence flag
    """

    try:


        folder = QFileDialog.getExistingDirectory(
            parent,
            "Select Mission Folder",
            str(default_user_dir),
            QFileDialog.Option.ShowDirsOnly
        )

        # User cancelled
        if not folder:
            return None, False

        folderMissionPath = Path(folder)

        if not folderMissionPath.exists():
            show_warning_OK_Cancel_message(
                "IRDrone",
                f"You selected the folder:\n{folderMissionPath}\n",
                "This folder is not recognized by IRDrone.\n"
                "Choose a compatible folder named FLY_YYYYMMDD_hhmm_[Optional text]."
            )
            return folderMissionPath, False

        coherent_answer = folder_name_consistency_analysis(folderMissionPath)

        if not coherent_answer:
            show_warning_OK_Cancel_message(
                "IRDrone",
                "Invalid mission folder name",
                f"You selected the folder:\n{folderMissionPath}\n\n"
                "The folder name does not match the expected format:\n"
                "FLY_YYYYMMDD_hhmm_<free text>"
            )
            return folderMissionPath, False

        valid_structure, error_msg = validate_mission_structure_phase_2(folderMissionPath)

        if not valid_structure:
            show_warning_OK_Cancel_message(
                "IRDrone",
                "Invalid mission folder structure",
                f"The selected mission folder is incomplete:\n\n{error_msg}\n\n"
                "This mission cannot be loaded in phase 2."
            )
            return folderMissionPath, False

        if verbose:
            print(
                Style.GREEN
                + f"The mission exists and is located at: {folderMissionPath}"
                + Style.RESET
            )

        return safe_path(folderMissionPath), True


    except Exception as e:
        print("Error in choose_mission_folder_phase_2:", e)
        import traceback
        traceback.print_exc()
        return None, False

def validate_mission_structure_phase_2(mission_path: Path) -> tuple[bool, str]:
    """
    Validate the minimal IRDrone mission folder structure for phase 2.

    Returns
    -------
    (bool, str)
        - validity flag
        - error message (empty if valid)
    """

    required_paths = {
        "AerialPhotography": mission_path / "AerialPhotography",
        "FlightAnalytics": mission_path / "FlightAnalytics",
        "VIS": mission_path / "AerialPhotography" / "VIS",
        "NIR": mission_path / "AerialPhotography" / "NIR",
        "mission_parameters.json": mission_path / "FlightAnalytics" / "mission_parameters.json",
        "VIS timeline": mission_path / "AerialPhotography" / "VIS" / "time_line.json",
        "NIR timeline": mission_path / "AerialPhotography" / "NIR" / "time_line.json",
        "VIS transfer": mission_path / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json",
        "NIR transfer": mission_path / "AerialPhotography" / "NIR" / "transfer_info_NIR_dng.json",
    }
    optional_paths = {
        "cameras": mission_path / "cameras",
        "Synchro": mission_path / "Synchro",
        "ImgIRdrone": mission_path / "ImgIRdrone",
        "mapping_MULTI": mission_path / "mapping_MULTI",
    }

    for label, path in optional_paths.items():
        if not path.exists():
            print(Style.YELLOW + f"⚠ Missing optional element: {label}\n{path}" + Style .RESET)
    for label, path in required_paths.items():
        if not path.exists():
            return False, f"Missing required element: {label}\n{path}"

    return True, ""

def copy_images(inputDir: str, imgName: str, outputDir: str) -> Optional[str]:
    """
    Copy an image file from the input directory to the output directory.

    Parameters:
    - inputDir (str): The directory from which the image file will be copied.
    - imgName (str): The name of the image file to be copied.
    - outputDir (str): The directory to which the image file will be copied.

    Returns:
    - str: A message indicating the result of the copy operation.
    """
    source = os.path.join(inputDir, imgName)     # Constructs the full path of the source file
    # Check if the source file exists
    if not os.path.isfile(source):
        return "The source file does not exist."
    # Check if the destination folder exists, create it if not
    if not os.path.isdir(outputDir):
        os.makedirs(outputDir)
    destination = os.path.join(outputDir, imgName)   # Construct the full path of the destination file
    shutil.copy(source, destination)    # Copy file
    return f"File {imgName} was successfully copied from {inputDir} to {outputDir}."

def copy_and_rename_images(input_dir: Path,
                           input_img_name: str,
                           output_dir: Path,
                           output_img_name: str,
                           verbose: bool = True
                           ) -> None:
    """
    Copy an image from input_dir/input_img_name to output_dir/output_img_name,
    only if the destination file does not already exist.

    Conditions:
        - If output file exists → do nothing.
        - If output file does NOT exist:
            * Verify that input file exists.
            * Verify that input and output extensions match.
            * Copy input -> output.

    Parameters
    ----------
    input_dir : Path
        Source directory.
    input_img_name : str
        Filename to copy.
    output_dir : Path
        Destination directory.
    output_img_name : str
        Filename after renaming.
    """

    src = input_dir / input_img_name
    dst = output_dir / output_img_name
    nothing_done = False


    # 1) Check if target exists → do nothing
    if dst.exists():
        nothing_done = True
        if verbose: print(Style.CYAN + f"Target already exists, nothing done: {dst}" + Style.RESET)

    # 2) Check if source exists
    if not src.exists():
        if verbose: print(Style.YELLOW + f"⚠️  Source file not found: {src}" + Style.RESET)
        return

    # 3) Check extension
    if src.suffix.lower() != dst.suffix.lower():
        if verbose: print(Style.YELLOW + f"⚠️  Extension mismatch: {src.suffix} != {dst.suffix}" + Style.RESET)
        return

    # 4) Copy
    try:
        if not nothing_done:
            shutil.copy2(src, dst)   # copy2 keeps metadata
            if verbose: print(Style.GREEN + f"Copied: {src} → {dst}" + Style.RESET)
    except Exception as e:
        print(Style.RED + f"ERROR copying file: {e}" + Style.RESET)

def read_exif_and_write_json(dng_path: Path, exiftool_path: str) -> dict:
    """
    Extract selected EXIF/XMP metadata from a DNG file using ExifTool
    and save a clean .exif JSON file next to the image.
    """

    try:
        # 1) Run ExifTool
        cmd = [exiftool_path, "-json", str(dng_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        metadata_list = json.loads(result.stdout)
        if not metadata_list:
            raise RuntimeError("ExifTool returned empty output")

        full_metadata = metadata_list[0]

        # 2) Keep only essential keys
        essential_keys = [
            "FileName", "Directory", "DateTimeOriginal",
            "Make", "Model", "CameraSerialNumber",
            "Orientation",
            "ExposureTime", "FNumber", "ISO", "ExposureCompensation",
            "FocalLength", "FOV", "FocalLengthIn35mmFormat",
            "HyperfocalDistance",
            "GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSPosition",
            "FlightYawDegree", "FlightPitchDegree", "FlightRollDegree",
            "GimbalYawDegree", "GimbalPitchDegree", "GimbalRollDegree",
            "DroneLatitude", "DroneLongitude", "DroneAltitudeTakeOff",
            "DroneAltitudeSeaLevel", "DroneAltitudeGround", "GroundAltitude",
            "UTM_x", "UTM_y", "UTM_zone",
        ]

        # Special handling for GPSAltitude of Drone DJI
        gps_alt = full_metadata.get("GPSAltitude")
        if gps_alt:
            alt_info = parse_and_normalize_gps_altitude(gps_alt)
            meters = round(alt_info["meters"], 3)
            full_metadata["DroneAltitudeTakeOff"] = meters
            full_metadata["GPSAltitude"] = f"{meters} m Above Take Off"

        gps_lat = full_metadata.get("GPSLatitude")
        gps_lon = full_metadata.get("GPSLongitude")
        if gps_lat and gps_lon:
            full_metadata["DroneLatitude"] = gps_coordinate_to_float(gps_lat)
            full_metadata["DroneLongitude"] = gps_coordinate_to_float(gps_lon)
            UTM_x, UTM_y, UTM_zone = geo2UTM(gps_coordinate_to_float(gps_lat), gps_coordinate_to_float(gps_lon))
            full_metadata["UTM_x"], full_metadata["UTM_y"], full_metadata["UTM_zone"] = UTM_x, UTM_y, UTM_zone
        cleaned = {k: full_metadata.get(k) for k in essential_keys if k in full_metadata}


        # 3) Write the companion .exif JSON
        out_path = dng_path.with_suffix(".exif")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        return cleaned

    except Exception as e:
        print(f"[ERROR] read_exif_and_write_json failed for {dng_path}: {e}")
        return {}

def parse_and_normalize_gps_altitude(value: str) -> dict:
    """
    Extract and normalize altitude like:
        '0.6 m'
        '0.6 m above sea level'
        '350 ft'
        '350 ft Above Take Off'
    Returns a dict with value in meters and metadata.
    """
    s = value.strip().lower()

    # Regex : capture  (nombre) (unité)
    # ex: '120.5 m', '350 ft', '12.34m', '50ft'
    match = re.search(r"([+-]?\d+(?:\.\d*)?)\s*(m|ft)\b", s)
    if not match:
        raise ValueError(f"Impossible d'extraire altitude et unité dans GPSAltitude: {value}")

    number_str, unit = match.groups()
    number = float(number_str)

    # Conversion
    meters = number if unit == "m" else number * 0.3048

    return {
        "original_value": number,
        "original_unit": unit,
        "meters": round(meters, 3),
    }

def read_exif_and_write_json_old(dng_path: Path, exiftool_path: str) -> dict:
    """
    Read EXIF/XMP metadata from a DNG file using ExifTool
    and write a small .exif JSON file next to the image.

    Returns:
        dict: cleaned metadata
    """
    try:

        out_path = dng_path.with_suffix(".exif")
        if out_path.exists():
            # print(f'File {out_path.name} already exist in {out_path.parent}.')
            pass

        # --- 1) Read metadata with ExifTool ---
        cmd = [exiftool_path, "-json", str(dng_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        metadata_list = json.loads(result.stdout)
        if not metadata_list:
            raise RuntimeError("ExifTool returned empty output")

        full_metadata = metadata_list[0]

        # --- 2) Select relevant keys (you can expand this list easily) ---
        essential_keys = [
            "FileName", "Directory", "DateTimeOriginal",
            "Make", "Model", "CameraSerialNumber",
            "Orientation",
            "ExposureTime", "FNumber", "ISO", "ExposureCompensation",
            "FocalLength", "FOV", "FocalLengthIn35mmFormat", "HyperfocalDistance",
            "GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSPosition",

            "FlightYawDegree", "FlightPitchDegree", "FlightRollDegree",  # DJI XMP
            "GimbalYawDegree", "GimbalPitchDegree", "GimbalRollDegree",
        ]

        cleaned = {k: full_metadata.get(k) for k in essential_keys if k in full_metadata}

        # --- 3) Write .exif JSON file next to the image ---
        out_path = dng_path.with_suffix(".exif")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        return cleaned

    except Exception as e:
        print(f"[ERROR] read_exif_and_write_json failed for {dng_path}: {e}")
        return {}

def change_icon(folder_path: Union[str, Path], file_path: Union[str, Path]) -> None:
    """
    Change the icon of a Windows folder by creating/updating the 'desktop.ini' file
    and marking the folder as a system folder.

    Args:
        folder_path (str | Path): Path to the target folder.
        file_path (str | Path): Path to the .ico file to use as the folder icon.

    Raises:
        FileNotFoundError: If the folder or icon file does not exist.
        PermissionError: If the folder is not writable.
        OSError: For other errors when creating or copying files.
        RuntimeError: If not running on Windows.

    Notes:
        - Works only on Windows.
        - Sets the folder attribute to 'system' so Windows recognizes the custom icon.
        - Overwrites any existing desktop.ini for the folder.
    """
    # Ensure running on Windows
    if os.name != 'nt':
        raise RuntimeError("change_icon is only supported on Windows.")

    folder_path = Path(folder_path)
    file_path = Path(file_path)

    if not folder_path.exists():
        raise FileNotFoundError(f"Target folder does not exist: {folder_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Icon file does not exist: {file_path}")

    # Check write permission by attempting to create a temporary file
    try:
        temp_file = folder_path / 'temp_permission_check.txt'
        temp_file.write_text('test')
        temp_file.unlink()
    except PermissionError:
        raise PermissionError(f"Folder is not writable: {folder_path}")

    # Create a temporary desktop.ini file
    try:
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.ini') as tmp_ini:
            tmp_ini.write('[.ShellClassInfo]\n')
            tmp_ini.write(f'IconResource={file_path},0\n')
            temp_ini_path = Path(tmp_ini.name)
    except Exception as e:
        raise OSError(f"Failed to create temporary desktop.ini: {e}")

    # Copy the temporary desktop.ini to the target folder
    try:
        shutil.copy(temp_ini_path, folder_path / 'desktop.ini')
    finally:
        temp_ini_path.unlink(missing_ok=True)

    # Mark the folder as system so Windows uses desktop.ini
    os.system(f'attrib +s "{folder_path}"')

def list_files_with_suffix(suffix: str, folder: str) -> List[Path]:
    """
    Return a sorted list of files with a given suffix in a folder.

    Args:
        suffix (str): File extension without the dot, e.g., 'dng' or 'json'.
        folder (str): Path to the folder to search in.

    Returns:
        List[Path]: Sorted list of Path objects for files matching the suffix.

    Raises:
        FileNotFoundError: If the specified folder does not exist.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    # Use glob to find files matching the suffix and sort them
    return sorted(folder_path.glob(f"*.{suffix.upper()}"))

def rename_file_VIS(input_img_name: str) -> str:
    """
    Rename a VIS image file from format 'HYPERLAPSE_0123.dng' to 'VIS_0123.dng'.

    This function extracts the numeric part of the original filename and
    creates a new filename with 'VIS_' prefix, keeping a 4-digit number
    with leading zeros.

    Args:
        input_img_name (str): Input filename, expected format 'HYPERLAPSE_XXXX.dng'.

    Returns:
        str: Renamed filename, format 'VIS_XXXX.dng'.

    Raises:
        ValueError: If the input filename does not match the expected pattern.
    """
    stem = Path(input_img_name).stem  # e.g., 'HYPERLAPSE_0123'
    try:
        num = int(stem.split("_")[1])  # Split by underscore and take the second part as number
    except (IndexError, ValueError) as e:
        raise ValueError(f"Invalid filename: '{input_img_name}'. Expected format: 'HYPERLAPSE_XXXX.dng'.") from e
    output_img_name = f"VIS_{num:04d}.dng"
    return output_img_name

def read_exiftool_metadata(path: Path) -> dict:
    """
    Read all metadata of an image using exiftool, including XMP (attitude angles).
    Return a dictionary.
    """
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-n", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data[0] if data else {}

    except subprocess.CalledProcessError as e:
        print("Exiftool error:", e.stderr)
        return {}


# =============================================================================
# RAW → DNG CONVERSION UTILITIES
# =============================================================================

def build_dng_name(raw_file: str) -> str:
    """
    Build the target DNG filename from a SJCam RAW file.

    Naming rule:
        If RAW is like '2022_0125_130446_023.RAW'
        → extract 23
        → compute new index = (23 + 1) // 2 = 12
        → return 'NIR_0012.dng'
    """
    raw_path = Path(raw_file)
    stem = raw_path.stem                # '2022_0125_130446_023'
    last_number = int(stem.split("_")[-1])   # 23

    new_index = (last_number + 1) // 2       # 12
    number_str = str(new_index).zfill(4)     # '0012'

    return f"NIR_{number_str}.dng"

def _set_exif_from_raw(dng_path: Path, raw_path: Path, exiftool_path: str, verbose: bool = False):
    """
    Set DateTimeOriginal and CreateDate in EXIF from the RAW filename using exiftool.

    Parameters
    ----------
    dng_path : Path
        Path to the DNG file.
    raw_path : Path
        Path to the original RAW file.
    exiftool_path : str
        Full path to exiftool executable.
    verbose : bool
        If True, prints status messages.
    """
    try:
        # --- Extract date/time from RAW filename ---
        stem = raw_path.stem  # '2022_0125_130446_023'
        parts = stem.split("_")
        year = int(parts[0])
        month = int(parts[1][:2])
        day = int(parts[1][2:])
        hour = int(parts[2][:2])
        minute = int(parts[2][2:4])
        second = int(parts[2][4:])
        dt = datetime(year, month, day, hour, minute, second)
        exif_dt = dt.strftime("%Y:%m:%d %H:%M:%S")

        # --- Call exiftool to set DateTimeOriginal and CreateDate ---
        cmd = [
            str(exiftool_path),
            f"-DateTimeOriginal={exif_dt}",
            f"-CreateDate={exif_dt}",
            f"-XMP:DateCreated={exif_dt}",
            str(dng_path),
            "-overwrite_original"
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if verbose:
            print(f"🕒 EXIF date updated for {dng_path.name} → {exif_dt}")

    except subprocess.CalledProcessError as e:
        print(f"⚠ Failed to insert EXIF for {dng_path.name}: {e.stderr.decode(errors='ignore')}")
    except Exception as e:
        print(f"⚠ Unexpected error for {dng_path.name}: {e}")

def _convert_single_raw_to_dng(raw_file: str,
                               exe_path: str,
                               output_folder: str,
                               nb_threads: str,
                               verbose: bool,
                               exiftool_path: str,
                               show_converter_output: bool = False) -> str:
    """
    Internal helper: converts a single RAW file to DNG using sjcam_raw2dng.
    The output DNG filename is standardized to 'NIR_XXXX.dng'.
    EXIF DateTimeOriginal and CreateDate are updated from RAW filename.

    Parameters
    ----------
    raw_file : str
        Path to the RAW file.
    exe_path : str
        Path to sjcam_raw2dng executable.
    output_folder : str
        Destination folder for the DNG file.
    nb_threads : str
        Number of threads passed to the converter ("0" = auto).
    verbose : bool
        If True, prints detailed information.

    Returns
    -------
    str
        Full path to the generated DNG file.
    """
    raw_path = Path(raw_file)
    dng_name = build_dng_name(raw_file)
    dng_output_path = Path(output_folder) / dng_name

    if dng_output_path.exists():
        if verbose:
            print(f"⏭ DNG already exists, skipping: {dng_output_path.name}")
        return str(dng_output_path)

    if verbose:
        print(f"➡ Converting: {raw_path.name}")

    # Command for conversion
    cmd = [
        str(exe_path),
        "--no-color",
        "--thumb",
        "--threads", nb_threads,
        "--output", str(output_folder),
        str(raw_path)
    ]

    # Decide where to send stdout/stderr
    if show_converter_output:
        stdout_target = None  # print to console
        stderr_target = None
    else:
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL


    subprocess.run(cmd, check=True, stdout=stdout_target, stderr=stderr_target)

    # Define original DNG path (created by sjcam_raw2dng, same stem as RAW)
    original_dng_path = Path(output_folder) / (raw_path.stem + ".dng")

    # Rename to standardized name
    if original_dng_path.exists() and original_dng_path != dng_output_path:
        original_dng_path.rename(dng_output_path)
        if verbose:
            print(f"✏ Renamed {original_dng_path.name} → {dng_output_path.name}")

    # Update EXIF from RAW filename
    _set_exif_from_raw(dng_output_path, raw_path, exiftool_path, verbose)

    return str(dng_output_path)

def convert_raw_to_dng_parallel(
        input_folder: str,
        output_folder: str,
        exe_path: str,
        nb_threads: str = "0",
        verbose: bool = False,
        max_workers: int = None,
        exiftool_path=None
) -> List[str]:
    """
    Convert all SJCam M20 .RAW files in an input folder to .DNG in parallel,
    using multiple processes to speed up conversion. Each RAW file is processed
    independently using the sjcam_raw2dng executable. Output files are renamed
    in the 'NIR_XXXX.dng' format and EXIF dates are corrected from RAW filename.

    Parameters
    ----------
    input_folder : str
        Path to the folder containing the .RAW files.
    output_folder : str
        Path to the folder where the converted DNG files will be stored.
    exe_path : str
        Full path to sjcam_raw2dng.exe.
    nb_threads : str, optional
        Number of threads passed to each converter instance ("0" = auto).
    verbose : bool, optional
        If True, prints detailed conversion information.
    max_workers : int, optional
        Maximum number of parallel processes to run.
        If None, automatically set to the number of physical CPU cores.

    Returns
    -------
    List[str]
        List of paths to the generated DNG files in output_folder.
    """
    exe = Path(exe_path)
    if not exe.exists():
        link = "https://github.com/yanburman/sjcam_raw2dng/releases"
        raise FileNotFoundError(
            f"Converter not found: {exe_path}. You can download it from: {link}"
        )

    input_folder_path = Path(input_folder)
    if not input_folder_path.exists():
        raise FileNotFoundError(f"Input folder not found: {input_folder}")

    raw_files = sorted([str(p) for p in input_folder_path.glob("*.RAW")])
    dng_files: List[str] = []

    # Auto-adjust max_workers if not provided
    if max_workers is None:
        cpu_physical = psutil.cpu_count(logical=False) or 1
        max_workers = max(1, cpu_physical)

    if verbose:
        print(f"Using max_workers={max_workers} (detected {os.cpu_count()} CPU threads)")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_raw = {
            executor.submit(_convert_single_raw_to_dng, raw, exe, output_folder, nb_threads, verbose, exiftool_path): raw
            for raw in raw_files
        }

        for future in as_completed(future_to_raw):
            try:
                dng_path = future.result()
                dng_files.append(dng_path)
            except subprocess.CalledProcessError as e:
                print(f"⚠ Conversion failed for {future_to_raw[future]}: {e}")

    return sorted(dng_files)

def read_exif_json(path_exif: Path) -> dict:
    """Load JSON content from a .exif file."""
    with open(path_exif, "r", encoding="utf-8") as f:
        return json.load(f)

def to_json_safe(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json_safe(v) for v in obj]
    return obj

def list_tempo_time_line(
        folder: Path,
        spectral_band: str = "VIS"
) -> List[Dict]:
    """
    Build and return a list of reduced EXIF dictionaries
    for VIS or NIR images inside a given folder.

    Parameters
    ----------
    folder : Path
        Folder containing images VIS_xxxx.dng + VIS_xxxx.exif
    spectral_band : str ("VIS" or "NIR")
        Spectral band used in filenames

    Returns
    -------
    List[Dict]
        A list of filtered EXIF dictionaries (one per image)
    """

    folder = Path(folder)
    bdspectr = spectral_band.upper()

    if bdspectr not in ("VIS", "NIR"):
        raise ValueError("spectral_band must be 'VIS' or 'NIR'")

    # -----------------------------------------------------
    # 1) Trouver les fichiers images concernés
    # -----------------------------------------------------
    pattern = re.compile(rf"^{bdspectr}_(\d+)\.dng$", re.IGNORECASE)

    img_files = [f for f in folder.iterdir() if pattern.match(f.name)]
    img_files.sort()

    results = []

    # ----------------------------------------------------------------
    # 2) Pour chaque image : charger son fichier compagnon .exif
    # ----------------------------------------------------------------
    def extract_reduced_exif(d: dict) -> dict:
        """Extract only the essential fields from a full EXIF dictionary."""
        keys_needed = [
            "FileName",
            "Directory",
            "DateTimeOriginal"
        ]
        return {k: d.get(k) for k in keys_needed}


    for img in img_files:
        number = pattern.match(img.name).group(1)
        exif_path = img.with_suffix(".exif")

        if not exif_path.exists():
            print(f"[WARN] Missing EXIF file for {img.name}")
            continue

        full_dict = read_exif_json(exif_path)
        reduced_dict = extract_reduced_exif(full_dict)
        results.append(reduced_dict)

    return results

def time_line_analyser_images(list_dic_exif,
                              spectral_band: Optional[str] = None,
                              img_suffix: str = ".dng",
                              verbose: bool = False
                              ) -> Dict:
    """
    Analyze image files in a folder:
      - extract the date and time from the filename
      - extract the shot number (XXX)
      - compute time differences between consecutive images
      - check the regularity of time intervals
      - estimate the nominal period (median, mode, outlier filtering)
      - display any detected "jumps"
      - adaptive filtering tolerance automatically computed (1% of median)

    Parameters
    ----------
    inputFolder : Path | str
        Path to the folder containing the image files.
    spectral_band : str | None, optional
        Image type, "VIS" or "NIR", by default None.
    img_suffix : str, optional
        File img_suffix to filter images, by default ".dng".
    verbose : bool, optional
        If True, prints detailed information during analysis, by default False.

    Returns
    -------
    dict
        Dictionary containing files, numbers, dates, deltas, time_line, and camera type.
    """

    dates: list[datetime] = []
    numeros: list[int] = []
    shootings: list[int] = []
    list_file_path = []

    # ________  récupérer ici les dates des petits fichier exif

    for idx, dic_exif in enumerate(list_dic_exif):
        date_str = dic_exif["DateTimeOriginal"]
        dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
        dates.append(dt)
        numeros.append(idx)
        shootings.append(idx)
        list_file_path.append(dic_exif["FileName"])


    dates = np.array(dates)
    numeros = np.array(numeros)

    if len(dates) > 1:
        deltas = np.diff([d.timestamp() for d in dates])
        if verbose: print(deltas)
    else:
        deltas = np.array([])

    if len(deltas) == 0:
        print(Style.YELLOW + f"⚠️ Not enough images to compute intervals." + Style.RESET)
        return {"dates": dates, "numeros": numeros, "deltas": deltas}

    print(Style.GREEN + f"🔍 {len(dates)} {img_suffix.upper()} files found" + Style.RESET)

    # --- Total sequence duration ---
    total_duration = (dates[-1] - dates[0]).total_seconds()
    print(f"⏱️ Total sequence duration : {total_duration:.3f} s ({str(dates[-1] - dates[0])})")

    # --- Method 1: Median ---
    periode_mediane = np.median(deltas)

    # --- Method 2: Mode ---
    counts = Counter(np.round(deltas, 3))
    periode_mode, freq = counts.most_common(1)[0]

    # --- Method 3: Outlier filtering ---
    tol = max(0.001, 0.01 * periode_mediane)  # 1% of median, min 1 ms
    filtered_deltas = deltas[np.abs(deltas - periode_mediane) < tol]
    if len(filtered_deltas) > 0:
        periode_filtre = np.mean(filtered_deltas)
    else:
        periode_filtre = periode_mediane
        print(Style.YELLOW + f"⚠️ No intervals within defined tolerance for filtering." + Style.RESET)

    # --- Best time-lapse estimate ---
    estims = np.array([periode_mediane, periode_mode, periode_filtre])
    periode_time_lapse = np.median(estims)
    print(Style.GREEN + f"📌 best_timelapse_estimate : {periode_time_lapse:.3f} s" + Style.RESET)

    # --- Jump detection ---
    sauts: list[tuple[int, int, float]] = []
    for i, d in enumerate(deltas):
        if not np.isclose(d, periode_mediane, atol=tol):
            sauts.append((i, i + 1, d))

    # --- True recording period accounting for detected jumps ---
    true_record_period = true_recording_period(dates, sauts, periode_time_lapse)

    # --- Construct the actual timeline ---
    time_line = build_time_line(dates, sauts, true_record_period, numeros, list_file_path, verbose=False)

    # --- Overall summary ---
    print(f"🕒 Timeline computed: {time_line[-1]:.3f} s up to the last image (n={len(time_line)})")

    dic_timeline = build_time_line_dictionnary(
        list_file_path=list_file_path,
        shootings=shootings,
        dates=dates,
        deltas=deltas,
        time_line=time_line,
        spectral_band=spectral_band
    )

    return dic_timeline

def build_time_line(dates: list[float],
                    sauts: list[tuple[int, int, float]],
                    periode_reelle: float,
                    numeros: list[int],
                    list_file_path: list[Path],
                    verbose: bool = False
                    ) -> np.ndarray:
    """
    Construct a vector of actual elapsed times since the first image,
    taking into account real jumps, apparent jumps (EXIF artifacts), and abnormal jumps.
    If verbose=True, display the timeline image by image with the type of jump.

    Parameters
    ----------
    dates : list[float]
        List of timestamps (raw image acquisition times).
    sauts : list[tuple[int, int, float]]
        List of detected jumps as tuples (index1, index2, delta_time).
    periode_reelle : float
        Nominal real period between images.
    numeros : list[int]
        List of raw image numbers for display purposes.
    verbose : bool, optional
        If True, prints detailed timeline information, by default False.

    Returns
    -------
    np.ndarray
        Array of adjusted timeline values in seconds.
    """

    n = len(dates)
    if n == 0:
        return np.array([])

    time_line = np.zeros(n, dtype=float)

    # --- 1) Classify jumps ---
    classified_jumps: list[tuple[int, int, float, str]] = []  # (idx1, idx2, delta, type)
    dict_sauts: dict[int, float] = {}

    for idx1, idx2, d_saut in sauts:
        ratio = d_saut / periode_reelle

        # Case 1: real jump (integer multiple of period)
        if np.isclose(ratio, round(ratio), atol=0.49 / periode_reelle):
            type_saut = "real"
            dict_sauts[idx1] = d_saut

        # Case 2: apparent jump (EXIF artifact)
        elif d_saut < 2 * periode_reelle:
            type_saut = "apparent"
            # not added to dict_sauts because ignored

        # Case 3: abnormal jump
        else:
            type_saut = "abnormal"
            dict_sauts[idx1] = d_saut

        classified_jumps.append((idx1, idx2, d_saut, type_saut))

    # --- 2) Display jumps (only now that type is known) ---
    if classified_jumps:
        print(Style.YELLOW + f"⚠️ {len(classified_jumps)} jumps detected :" + Style.RESET)
        for idx1, idx2, delta, type_saut in classified_jumps:
            if type_saut == "real":
                label = "real jump"
                color = Style.YELLOW
            elif type_saut == "apparent":
                label = "apparent jump"
                color = Style.GREEN
            else:
                label = "abnormal jump"
                color = Style.RED


            print(
                color
                + f"   - Between {Path(list_file_path[idx1]).name} and {Path(list_file_path[idx2]).name} : {delta:.3f} s → {label}"
                + Style.RESET
            )

    else:
        print(Style.GREEN + "✅ No jumps detected" + Style.RESET)

    # --- 3) Construct adjusted timeline ---
    if verbose:
        print("\n--- Adjusted real timeline ---")
        print(f"raw image N° : {numeros[0]:04d} | time_line {time_line[0]:.3f} s")

    for i in range(1, n):
        delta = periode_reelle  # default value
        saut_txt = ""

        if (i - 1) in dict_sauts:
            d_saut = dict_sauts[i - 1]
            ratio = d_saut / periode_reelle

            # Same classification as above
            if np.isclose(ratio, round(ratio), atol=0.49 / periode_reelle):
                delta = d_saut
                saut_txt = f" | real jump {d_saut:.3f} s"
            elif d_saut < 2 * periode_reelle:
                saut_txt = f" | apparent jump ({d_saut:.3f} s)"
            else:
                delta = d_saut
                saut_txt = f" | abnormal jump {d_saut:.3f} s"

        time_line[i] = time_line[i - 1] + delta

        if verbose:
            print(f"raw image N° : {numeros[i]:04d} | time_line {time_line[i]:.3f} s{saut_txt}")

    if verbose:
        print("---------------------------------\n")

    return time_line

def build_time_line_dictionnary(
        list_file_path: List[Path],
        shootings: List[int],
        dates: List[Union[datetime, str]],
        deltas: np.ndarray,
        time_line: np.ndarray,
        spectral_band: str = "VIS"
) -> Dict[str, List[Dict[str, Union[float, int, str]]]]:
    """
    Build a dictionary containing the timeline of an image sequence
    for a given spectral band (VIS, NIR, etc.).

    Returns a dictionary in the form:
        { spectral_band: [ {img_path, num_img, date_img, delta_img, relative_timeline}, ... ] }

    Each entry corresponds to an image and contains:
        - img_path : full path of the image
        - num_img  : image capture number
        - date_img : date in ISO format
        - delta_img: interval since previous image (s)
        - relative_timeline: cumulative time since first image (s)

    rem:  if f = C:\ ....\folder_name\hyperlapse.DNG
        Path(f).parent =  C:\ ....\folder_name
        Path(f).parent.name = folder_name
        Path(f).name  = "hyperlapse.DNG"
        Path(f).stem  = "hyperlapse"
        Path(f).suffix  = ".DNG"
        Path(f).suffix[1:] = "DNG"

    """

    data: List[Dict[str, Union[float, int, str]]] = []

    for i, f in enumerate(list_file_path):
        delta: float = float(time_line[i]) - float(time_line[i-1]) if i > 0 and i - 1 < len(deltas) else 0.0
        # Format the date as ISO string if datetime, else use string directly
        if isinstance(dates[i], datetime):
            date_str: str = dates[i].isoformat(timespec="seconds")
        else:
            date_str = str(dates[i])

        data.append({
            "img_path": str(f),
            "relative_shooting_number": int(shootings[i]),
            "date_img": date_str,
            "delta_img": round(delta, 6),
            "relative_timeline": round(float(time_line[i]), 6)
        })

    return {spectral_band: data}

def true_recording_period(
        dates: list[datetime],
        sauts: list[tuple[int, int, float]],
        periode_time_lapse: float
) -> float:
    """
    Computes the true recording period of an image sequence, taking into account detected jumps.

    Logic:
    - If jumps are present, compute the mean jump duration.
    - If the mean jump is an exact multiple of the estimated time-lapse period,
      the jumps are considered "real" (i.e., intentional or consistent with the capture rate),
      and the true recording period is set to the estimated time-lapse period.
    - Otherwise, or if no jumps are detected, the true recording period is calculated
      as the total elapsed time divided by the number of intervals (dates - 1),
      which accounts for possible small timing variations or EXIF artifacts ("apparent" jumps).

    Parameters
    ----------
    dates : list[datetime]
        List of capture times for each image in the sequence.
    sauts : list[tuple[int, int, float]]
        List of detected jumps as tuples (index1, index2, delta_time).
        These can be "real", "apparent", or "abnormal".
    periode_time_lapse : float
        Estimated nominal period between consecutive images (s).

    Returns
    -------
    float
        The true recording period in seconds.
    """
    n_intervals = len(dates) - 1
    if n_intervals <= 0:
        return 0.0

    if sauts:
        delta_jumps = np.array([d for (_, _, d) in sauts])
        mean_jump = np.mean(delta_jumps)

        # Check if the mean jump is a multiple of the estimated period
        if np.isclose(mean_jump / periode_time_lapse, round(mean_jump / periode_time_lapse), atol=0.01):
            # Jumps are exact multiples → true period = estimated period
            true_record_period = periode_time_lapse
            print(Style.GREEN + f"📌 true_recording_period (excluding jumps): {true_record_period:.3f} s" + Style.RESET)
        else:
            # True period = total duration / number of intervals
            true_record_period = (dates[-1] - dates[0]).total_seconds() / n_intervals
            print(Style.GREEN + f"📌 true_recording_period: {true_record_period:.3f} s" + Style.RESET)
    else:
        # No jumps → true period = total duration / number of intervals
        true_record_period = (dates[-1] - dates[0]).total_seconds() / n_intervals
        print(Style.GREEN + f"📌 true_recording_period: {true_record_period:.3f} s" + Style.RESET)

    return true_record_period

# ------------------------------------
#  pour phase 3
# ------------------------------------
def compute_time_shift_L2(
    time_line_VIS: Sequence[float],
    angles_unwrapped_VIS: Sequence[float],
    time_line_NIR: Sequence[float],
    angles_unwrapped_NIR: Sequence[float],
    use_median: bool = False
) -> Tuple[float, float, Dict[str, Optional[float]]]:
    """
    Estimate the temporal offset Δt such that:
        theta_VIS(t) ≈ theta_NIR(t - Δt)

    under the assumption of uniform angular velocity.
    The offset is computed analytically by L2 minimization.

    Parameters
    ----------
    time_line_VIS : sequence of float
        Time stamps of VIS images.
    angles_unwrapped_VIS : sequence of float
        Unwrapped angular measurements for VIS images.
    time_line_NIR : sequence of float
        Time stamps of NIR images.
    angles_unwrapped_NIR : sequence of float
        Unwrapped angular measurements for NIR images.
    use_median : bool, optional
        If True, use the median estimator for VIS intercept (robust to outliers).
        If False, use the mean (default: False).

    Returns
    -------
    time_shift : float
        Estimated temporal offset Δt (seconds).
    omega : float
        Estimated angular velocity (rad/s or deg/s).
    metrics : dict
        Dictionary of quality indicators:
            - n_vis
            - n_nir
            - r2_nir
            - dt_iqr
            - dt_std
            - omega_vis
            - delta_omega
            - rel_delta_omega
    """

    # --- Convert to numpy arrays ---
    t_vis = np.asarray(time_line_VIS, dtype=float)
    th_vis = np.asarray(angles_unwrapped_VIS, dtype=float)
    t_nir = np.asarray(time_line_NIR, dtype=float)
    th_nir = np.asarray(angles_unwrapped_NIR, dtype=float)

    if t_nir.size < 2:
        raise ValueError("At least two NIR points are required")

    if t_vis.size < 1:
        raise ValueError("At least one VIS point is required")

    # --- 1. Linear regression on NIR (reference) ---
    omega, b_nir = np.polyfit(t_nir, th_nir, 1)

    th_nir_fit = omega * t_nir + b_nir
    ss_res = np.sum((th_nir - th_nir_fit) ** 2)
    ss_tot = np.sum((th_nir - np.mean(th_nir)) ** 2)
    r2_nir = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

    # --- 2. VIS intercepts projected onto NIR slope ---
    b_vis_vals = th_vis - omega * t_vis

    if use_median:
        b_vis = np.median(b_vis_vals)
    else:
        b_vis = np.mean(b_vis_vals)

    # --- Individual time shifts ---
    dt_vals = (b_nir - b_vis_vals) / omega

    dt_iqr = np.percentile(dt_vals, 75) - np.percentile(dt_vals, 25)
    dt_std = np.std(dt_vals) if dt_vals.size > 1 else 0.0

    # --- 3. Optimal global time shift ---
    time_shift = (b_nir - b_vis) / omega

    # --- 4. VIS slope consistency check (optional) ---
    if t_vis.size >= 2:
        omega_vis, _ = np.polyfit(t_vis, th_vis, 1)
        delta_omega = omega_vis - omega
        rel_delta_omega = abs(delta_omega / omega)
    else:
        omega_vis = None
        delta_omega = None
        rel_delta_omega = None

    metrics = {
        "n_vis": int(t_vis.size),
        "n_nir": int(t_nir.size),
        "r2_nir": r2_nir,
        "dt_iqr": dt_iqr,
        "dt_std": dt_std,
        "omega_vis": omega_vis,
        "delta_omega": delta_omega,
        "rel_delta_omega": rel_delta_omega,
    }

    return time_shift, omega, metrics

def plot_angles_alignement_time_line(
    time: Union[Sequence[float], Sequence[Sequence[float]]],
    angles: Union[Sequence[float], Sequence[Sequence[float]]],
    title_angles: List[str],
    mode: str = "img",
    color: Union[str, List[str], None] = None,
    save_graph: bool = True,
    folder_save: Path = None,
    filename: str = "check_time_alignment.png",
) -> None:
    """
    Plot one or multiple angle curves versus their own time axes
    and save the figure to disk (GUI-safe, non-interactive).

    Parameters
    ----------
    time : sequence or sequence of sequences
        Time values (seconds).
    angles : sequence or sequence of sequences
        Angle values (degrees).
    title_angles : list of str
        Labels for each curve.
    mode : str
        "ground", "img" or "delta" to define the base label.
    color : str or list of str or None
        Color(s) for the curves.
    save_graph : bool
        If True, save the figure to disk.
    folder_save : Path
        Output directory for the figure.
    filename : str
        Name of the saved image file.
    """

    # --- Label selection ---
    if mode == "ground":
        label_base = "Ground reference angle"
    elif mode == "img":
        label_base = "Image reference angle"
    elif mode == "delta":
        label_base = "Delta angle (ground - image)"
    else:
        label_base = "Angle"

    # --- Normalize input to list of lists ---
    is_single_curve = isinstance(angles[0], (int, float, np.floating))

    if is_single_curve:
        angles_list = [angles]
        time_list = [time]
    else:
        angles_list = list(angles)
        time_list = list(time)

    if len(title_angles) != len(angles_list):
        raise ValueError("title_angles must match the number of curves.")

    # --- Figure creation (GUI-safe) ---
    fig, ax = plt.subplots(figsize=(8, 4))

    # --- Colors handling ---
    if color is None:
        colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    elif isinstance(color, list):
        colors = color
    else:
        colors = [color]

    # --- Plot curves ---
    for i, (t, y) in enumerate(zip(time_list, angles_list)):
        if len(t) != len(y):
            raise ValueError(f"Curve {i}: time and angles must have the same length.")

        ax.plot(
            t,
            y,
            marker="o",
            color=colors[i % len(colors)],
            label=f"{title_angles[i]} ({len(y)} img)"
        )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Angle (deg)")
    ax.set_title(f"Evolution of {label_base}")
    ax.legend()
    ax.grid(True)

    # --- Save and cleanup ---
    if save_graph:
        if folder_save is None:
            raise ValueError("folder_save must be specified when save_graph=True")

        folder_save.mkdir(parents=True, exist_ok=True)
        out_path = folder_save / filename
        fig.savefig(out_path, dpi=150, bbox_inches="tight")

    plt.close(fig)

def draw_aruco_overlay(img, result, md, fixed_ids):
    if img is None or result is None:
        return img

    img_out = img.copy()

    has_md = md is not None
    mid = result.get("mobile_id", None)

    has_mobile = has_md and mid in md
    has_corners = has_mobile and "corners" in md[mid]

    has_absolute_ref = (
        has_md
        and fixed_ids is not None
        and not result.get("missing_fixed", True)
        and result.get("x_ref") is not None
        and result.get("y_ref") is not None
    )

    # --- fixed markers
    if has_md and fixed_ids is not None and not result.get("missing_fixed", False):
        draw_fixed_markers(img_out, md, fixed_ids)

    # --- mobile marker
    if has_mobile:
        center = md[mid]["center"]
        draw_mobile_center(img_out, center)

    # --- image orientation
    u_img = None
    if has_mobile and has_corners:
        u_img = draw_image_orientation(
            img_out, center, md[mid]["corners"]
        )

    # --- absolute orientation
    if has_absolute_ref and u_img is not None:
        draw_absolute_orientation(
            img_out,
            center,
            u_img,
            result["x_ref"],
            result["y_ref"],
            md[mid]["corners"],
        )

    # --- legend (always)
    lines = []

    if has_mobile and result.get("angle_img") is not None:
        lines.append(f"ID {mid}  angle img = {result['angle_img']:.1f} deg")

    if has_absolute_ref and result.get("angle_abs") is not None:
        delta = (result["angle_abs"] - result["angle_img"] + 180) % 360 - 180
        lines.append(f"abs = {result['angle_abs']:.1f} deg   d = {delta:.1f} deg")
    else:
        lines.append("absolute reference: unavailable")

    scale = 2
    draw_legend(
        img_out,
        lines,
        origin=(scale * 20, scale * 40),
        font_scale=scale,
        line_spacing=scale * 30,
    )

    return img_out

def draw_legend(
    img,
    lines,
    origin=(20, 40),
    font_scale=1.,
    line_spacing=28,
    color=(255, 255, 255),
    thickness=2,
):
    """
    Draw a multi-line legend on an OpenCV image.

    Parameters
    ----------
    lines : list of str
        Lines to display.
    origin : (int, int)
        Top-left corner of the legend.
    font_scale : float
        Text scale (increase for better visibility).
    line_spacing : int
        Vertical spacing between lines (pixels).
    """
    x0, y0 = origin
    for i, txt in enumerate(lines):
        cv2.putText(
            img,
            txt,
            (x0, y0 + i * line_spacing),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

def draw_fixed_markers(img, md, fixed_ids):
    for fid in fixed_ids:
        if fid in md:
            ct = tuple(md[fid]["center"].astype(int))
            cv2.circle(img, ct, 2, (0, 0, 255), -1)

def draw_mobile_center(img, center):
    cX, cY = tuple(center.astype(int))
    cv2.drawMarker(
        img, (cX, cY),
        (0, 0, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=20,
        thickness=2,
    )

def draw_image_orientation(img, center, corners, scale=3, color=(0, 255, 0), thickness=4):
    u = ((corners[0] - corners[3]) + (corners[1] - corners[2]))
    n = np.linalg.norm(u)
    if n == 0:
        return

    u /= n
    marker_width = int(np.linalg.norm(corners[0] - corners[1]))
    line_length = scale * marker_width

    cX, cY = tuple(center.astype(int))
    endX = int(cX + u[0] * line_length)
    endY = int(cY + u[1] * line_length)

    cv2.line(img, (cX, cY), (endX, endY), color, thickness)
    return u

def draw_absolute_orientation(
    img,
    center,
    u_img,
    x_ref,
    y_ref,
    corners,
    scale=4,
    color=(0, 165, 255),
):
    ux = np.dot(u_img, x_ref)
    uy = np.dot(u_img, y_ref)
    u_abs = ux * x_ref + uy * y_ref

    marker_width = int(np.linalg.norm(corners[0] - corners[1]))
    line_length = scale * marker_width

    cX, cY = tuple(center.astype(int))
    endX = int(cX + u_abs[0] * line_length)
    endY = int(cY + u_abs[1] * line_length)

    draw_dashed_line(
        img,
        (cX, cY),
        (endX, endY),
        color,
        thickness=4,
        dash_length=15,
    )

def draw_dashed_line(img, pt1, pt2, color, thickness=1, dash_length=10):
    """
    Trace une ligne pointillée entre pt1 et pt2.
    - pt1, pt2 : tuples (x, y)
    - dash_length : longueur d’un segment (pixels)

    # Exemple d'utilisation
    cX, cY = 100, 100
    endX, endY = 300, 250
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    draw_dashed_line(img, (cX, cY), (endX, endY), (0, 255, 0), thickness=2, dash_length=15)
    cv2.imshow("Dashed line", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    """
    pt1 = np.array(pt1)
    pt2 = np.array(pt2)
    line_vec = pt2 - pt1
    line_len = np.linalg.norm(line_vec)
    line_dir = line_vec / line_len
    num_dashes = int(line_len / dash_length / 2)

    for i in range(num_dashes):
        start = pt1 + line_dir * (2 * i * dash_length)
        end = pt1 + line_dir * ((2 * i + 1) * dash_length)
        cv2.line(img, tuple(start.astype(int)), tuple(end.astype(int)), color, thickness)

def get_color_BGR(name):
    """
    Retourne la couleur BGR correspondant au nom donné.
    """
    colors = {
        "rouge":       (0, 0, 255),
        "vert":        (0, 255, 0),
        "bleu":        (255, 0, 0),
        "cyan":        (255, 255, 0),
        "magenta":     (255, 0, 255),
        "orange":      (0, 165, 255),
        "rose":        (203, 192, 255),
        "blanc":       (255, 255, 255),
        "gris":        (128, 128, 128),
        "violet":      (211, 0, 148),
        "jaune":       (0, 255, 255),
        "turquoise":   (208, 224, 64),
        "marron":      (42, 42, 165),
        "olive":       (0, 128, 128),
        "lavande":     (250, 230, 230),
        "bleu_clair":  (255, 200, 100),
        "vert_clair":  (144, 238, 144),
        "rose_foncé":  (147, 20, 80),
        "beige":       (220, 245, 245),
        "noir":        (0, 0, 0)
    }
    return colors.get(name.lower(), (0, 0, 0))  # Retourne noir si non trouvé
















