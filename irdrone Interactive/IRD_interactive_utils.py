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
from datetime import datetime, date
import time
from typing import Optional, Union
from pathlib import Path
from fractions import Fraction
import re
import numpy as np

# -------------------- Exif Library -------------------------------
import piexif
import exifread
from PIL import Image
import rawpy
# -----------------------PyQt6 Library ----------------------------
from PyQt6.QtWidgets import QMessageBox, QApplication
# -----------------------------------------------------------------

sys.path.append(osp.join(osp.dirname(__file__), ".."))
from typing import List, Optional
import config as cf
# ------------------------------------------------------------------


class Prefrence_Screen:

    def __init__(self):
        super().__init__()
        self.current_directory = os.getcwd()
        # print("TEST  Current Directory:", self.current_directory)
        self.directory = os.path.abspath('/')
        # print("TEST  directory", self.directory)
        self.default_app_dir = os.path.join(self.directory, "Program Files", "IRdrone")
        self.default_user_dir = os.path.join(self.directory, "Air-Mission")
        self.verbose = True
        # setting to manage multiple screens
        self.defaultScreenID: int = 1  # Set to 0 for screen 1, 1 for screen 2, and so on
        self.screenAdjust = [0, 40]  # 40 for taskbar and
        self.windowDisplaySize = (800, 640)
        self.AerialPhotoFolder: str = "AerialPhotography"  # folder of images taken by VIS and NIR cameras
        self.AnalyticFolder: str = "FlightAnalytics"  # technical folder containing information on the mission
        self.ImgIRdroneFolder: str = "ImgIRdrone"  # folder of images processed by IRDrone
        self.SynchroFolder: str = "Synchro"  # folder for images from the camera synchronization phase
        self.MappingFolder: str = "mapping_MULTI"  # folder for image assembly with Open Drone Map
        self.CameraFolder: str = "cameras"  # here the “s” of cameras is obligatory. Used by ODM
        self.background_color = "white"
        self.txt_color = "black"


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

    :param fileName: The file name with extension.
    :type fileName: str
    :return: A tuple containing the shooting number (int) and shooting date (datetime).
    """
    # Check if the file extension is RAW or JPG (case-insensitive)
    if fileName.split(".")[1].lower() in ["raw", "jpg"]:
        if fileName.split(".")[1].lower() == "raw":
            # Calculate shooting number for RAW files
            shootingNumber = int(int(fileName[17:20]) / 2 + 0.5)
        else:
            # Calculate shooting number for JPG files
            shootingNumber = int(int(fileName[17:20]) / 2)
        # Extract year, month, day, hour, minute, and second from the file name
        year = int(fileName[0:4])
        month = int(fileName[5:7])
        day = int(fileName[7:9])
        hour = int(fileName[10:12])
        minute = int(fileName[12:14])
        second = int(fileName[14:16])
        # Create a datetime object for the shooting date
        shootingDate = datetime(year, month, day, hour, minute, second)
        # Return the shooting number and shooting date as a tuple
        return shootingNumber, shootingDate


def extract_num_DNG_DJI(fileName: str) -> tuple:
    """
    Extract shooting number and shooting date from a DNG file name.

    :param fileName: The file name with extension.
    :type fileName: str
    :return: A tuple containing the shooting number (int) and shooting date (datetime).
    """
    # Check if the file extension is DNG (case-insensitive)
    if fileName.split(".")[1].lower() in ["dng"]:
        temp = fileName.split(".")[0].split("_")[1]
        shootingNumber = int(temp)
        return shootingNumber

    # Return None values if the file extension is not RAW or JPG
    return None, None


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
            datetime.strptime(date_part, "%Y%m%d")
            # Check if the time part is a valid time
            if 0 <= int(time_part) <= 2359 and int(time_part[2:]) < 60:
                coherent_response = True
            else:
                # print("Invalid time part in folder name.")
                pass
        except ValueError:
            # print("Invalid date part in folder name.")
            pass
    else:
        # print("Folder name does not match the expected pattern.")
        pass

    return coherent_response


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
    - The altitude returned from JPEG files may be relative to the take-off point of the drone.
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


def find_value_in_dic(dictionary: dict[str, any], key_searched: str) -> Optional[any]:
    """
    This function recursively searches for a key in a nested dictionary structure and
    returns the associated value if the key is found.

    Parameters:
    - dictionary (dict[any, any]): The dictionary in which to search for the key.
    - key_searched (str): The key to search for in the dictionary.

    Returns:
    - Optional[any]: The value associated with the key_searched if it is found;
                     otherwise, None.

    Usage:
    - The function iteratively searches through the keys of the input dictionary.
    - If the current key matches the key_searched, the corresponding value is returned.
    - If the associated value is a dictionary, the function calls itself recursively
      to search within this nested dictionary, and returns the result if a match is found.
    - If the associated value is a list, the function iterates through each item in the
      list. If an item is a dictionary, the function calls itself recursively to search
      within this nested dictionary, and returns the result if a match is found.
    - If the key is not found, the function returns None.
    """
    for key, value in dictionary.items():
        # Check if the current key matches the key_searched
        if key == key_searched:
            return value
        # Check if the value is a dictionary
        elif isinstance(value, dict):
            results = find_value_in_dic(value, key_searched)
            if results is not None:
                return results
        # Check if the value is a list
        elif isinstance(value, list):
            for item in value:
                # Check if the item within the list is a dictionary
                if isinstance(item, dict):
                    results = find_value_in_dic(item, key_searched)
                    if results is not None:
                        return results


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
    metadata = {}
    metadata["FileName"] = os.path.basename(image_path)
    metadata["FileSize"] = os.path.getsize(image_path)
    metadata["FileCreationDate"] = time.ctime(os.path.getctime(image_path))
    metadata["FileLastModifiedDate"] = time.ctime(os.path.getmtime(image_path))
    return metadata


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


def image_takeoff_available_test(dic_takeoff: dict, default_user_dir: Path):
    """

    :param dic_takeoff:
    :param default_user_dir:
    :return:
    """
    try:
        image_takeoff_available = False
        path_image_mission = Path(default_user_dir)
        try:
            if isinstance(dic_takeoff, dict) and 'File path mission' in dic_takeoff:
                path_image_mission = Path(dic_takeoff['File path mission'])
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



def format_number(number, decimal=3, car=" "):
    format_string = f"{car}{{:.{decimal}f}}" if number >= 0 else f"{{:.{decimal}f}}"
    return format_string.format(number)


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
        vector   D = x_EW e_EW + y_SN e_SN       |e_EW|=1, |e_SN|=1, e_EW.e_SN=0
        Axe orientation  e_EW <=> West > East ,   e_SN <=> South > North

            N  e_SN
              |
        W ----E ----> E  e_WE
              |
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
        except:
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

    except:
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
    except:
        DeltaCvis = 0

    return DeltaCvis













