# --------------------------------------------------------------------------------
#   IR_drone interactive
#   General utility
#   7/10/2023   V001   *
# ---------------------------------------------------------------------------------


import os
import json
from datetime import datetime, date
from typing import Any, Dict, Optional, Tuple, List,  Union
from pathlib import Path
from fractions import Fraction
import time
# ------------- geophysics Library --------------------------------
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from requests import Session
import requests
import re
# -------------------- Exif Library -------------------------------
import piexif
import exifread
from PIL import Image
import rawpy


# -----------------------PyQt6 Library ----------------------------
from PyQt6.QtWidgets import QMessageBox, QApplication


class Prefrence_Screen:

    def __init__(self):
        super().__init__()
        self.current_directory = os.getcwd()
        # print("TEST  Current Directory:", self.current_directory)
        self.directory = os.path.abspath('/')
        # print("TEST  directory", self.directory)
        self.default_app_dir = os.path.join(self.directory, "Program Files", "IRdrone")
        self.default_user_dir = os.path.join(self.directory, "Air-Mission")
        # setting to manage multiple screens
        self.defaultScreenID = 1  # Set to 0 for screen 1, 1 for screen 2, and so on
        self.screenAdjust = [0, 40]  # 40 for taskbar and
        self.windowDisplaySize = (800, 640)


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
    return py_date.strftime('%Y-%m-%d')


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
    return datetime.strptime(json_str, '%Y-%m-%d').date()


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


def show(widget):
    try:
        widget.show()
    except Exception as e:
        print("show error ", e)


def center_on_screen(widget, screen_Id=0, screen_adjust=(1, 1), window_display_size=(800, 650)):
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


def data_sig(coordinates: Tuple[float, float]) -> Optional[Dict[str, Any]]:
    """
    Retrieve geographic and geocoding information for given coordinates.

    Parameters:
    - coordinates (Tuple[float, float]): A tuple containing latitude and longitude.

    Returns:
    - Optional[Dict[str, Any]]: A dictionary containing geographic and geocoding information, or
      None if an error occurs or if information cannot be retrieved.

    Note:
    - The function uses two helper functions, extract_alti_IGN and extract_geoTag, to retrieve
      geographic altitude from the IGN API and geocoding information from the OpenStreetMap API,
      respectively.
    - Retrieved information is stored in the dictionary dic_geo, which is returned.
    - If an error occurs, an error message is printed and the function returns None.
    """
    dic_geo = []
    try:
        dic_geo = extract_alti_IGN(coordinates)   # extracts the geographic altitude of the location (IGN API)
        extract_geoTag(dic_geo)                   # extracts geocoding data (OpenStreetMap API)

    except Exception as e:
        print("error", e)

    return dic_geo


def extract_alti_IGN(coordinates: List[float]) -> Optional[Dict[str, Optional[float]]]:
    """
    Retrieve altitude information for a given coordinate using the IGN API.

    Parameters:
    - coordinates (List[float]): A list containing the latitude and longitude for which to retrieve altitude information.

    Returns:
    - Optional[Dict[str, Optional[float]]]: A dictionary containing latitude ('lat'), longitude ('lon'), and altitude ('alti').
      If the IGN API fails to provide information, None is returned.

    Note:
    - The function constructs an API URL using the input coordinates and sends a request to the IGN API.
    - The API's response is expected to be a JSON object which is parsed and from which altitude information is extracted and returned in a dictionary.
    - If the API request fails or if other errors occur, an error message is printed and the function returns None.
    """
    for _ in range(3):  # Trois tentatives
        try:
            IGN_api_key = "essentiels"
            formatted_latitude = ""
            formatted_longitude = ""


            latitude, longitude = coordinates[0], coordinates[1]
            formatted_latitude += str(latitude) + '|'
            formatted_longitude += str(longitude) + '|'

            formatted_latitude = re.sub(r'\|$', '', formatted_latitude)
            formatted_longitude = re.sub(r'\|$', '', formatted_longitude)

            api_url = f"https://wxs.ign.fr/{IGN_api_key}/alti/rest/elevation.json?" \
                      f"lon={formatted_longitude}&lat={formatted_latitude}&zonly=false"

            dico_coordinates_IGN = json.loads(requests.get(api_url).text)

            for dic_IGN in dico_coordinates_IGN['elevations']:
                dic_geo = {'lat': dic_IGN.get('lat'),
                           'lon': dic_IGN.get('lon'),
                           'alti': dic_IGN.get('z')
                           }
            return dic_geo

        except Exception as e:
            print(f"Error while trying {_ + 1}: {str(e)}")
            time.sleep(1)  # Wait 1 second before next attempt

    print("error. IGN API server is unavailable", e)
    return None


def extract_geoTag(dic_geo: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """
    Enrich input dictionary with geolocation information using the Nominatim API.

    Parameters:
    - dic_geo (Dict[str, Any]): A dictionary containing at least 'lat' and 'lon' keys
                                for latitude and longitude, respectively.

    Returns:
    - Dict[str, Optional[Any]]: The input dictionary enriched with additional keys for
                                'road', 'lieu_dit', 'ville', 'code_postal', 'dept',
                                'region', and 'pays'. If the geocoding API fails to
                                provide some information, corresponding keys may be
                                absent or set to None in the returned dictionary.

    Note:
    - The function uses the Nominatim API to reverse geocode 'lat' and 'lon' from the
      input dictionary to extract address information in French ('fr').
    - Extracted information is added to the input dictionary which is then returned.
    - If the API fails to respond in time, an error message is printed and the
      function proceeds. If no geocoding information can be retrieved, an error
      message is printed and keys for address information are set to None in the
      returned dictionary.
    """
    try:
        try:
            try:
                geolocator = Nominatim(user_agent="IRdrone")
                session = Session()
                session.verify = True
                geolocator.adapter.session = session
                lat = dic_geo.get('lat')
                lon = dic_geo.get('lon')

                location = geolocator.reverse((lat, lon), language='fr')
                address = location.raw['address']

                dic_geo['road'] = address.get('road')
                dic_geo['lieu_dit'] = address.get('hamlet') or address.get('farm') or address.get('isolated_dwelling') or address.get('locality') or address.get('city_block') or address.get('districr')
                dic_geo['ville'] = address.get('village') or address.get('city') or address.get('municipality') or address.get('town')
                dic_geo['code_postal'] = address.get('postcode')
                dic_geo['dept'] = address.get('county')
                dic_geo['region'] = address.get('state')
                dic_geo['pays'] = address.get('country')

                return dic_geo

            except GeocoderTimedOut:
                print(f"Geocoding service not responding for coordinates {dic_geo['lat']}, {dic_geo['lon']}. Merci de réessayer plus tard.")
        except AttributeError as e:
            print(f"No GPS coordinates for this point.")
            dic_geo['road'], dic_geo['lieu_dit'], dic_geo['ville'], dic_geo['code_postal'], dic_geo['dept'], dic_geo['region'], dic_geo['pays'] = None, None, None, None, None, None, None
    except Exception as e:
        print("Erreur", e,)


def extract_exif(file_path: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract EXIF metadata from a file, either in DNG or JPEG format.

    Parameters:
    - file_path (str): The path to the file from which to extract EXIF data.

    Returns:
    - Tuple[Optional[Any], Optional[Any], Optional[Any], Optional[str], Optional[str], Optional[str], Optional[str]]:
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


def convert_coordinates(latitude, longitude, altitude) -> Tuple[float, float, float]:
    """
    Convert geographical coordinates to decimal format.

    Parameters:
    - latitude : Latitude in IFD tag format to be converted to decimal format.
    - longitude : Longitude in IFD tag format to be converted to decimal format.
    - altitude : Altitude in IFD tag format to be converted to decimal format.

    Returns:
    - Tuple[float, float, float]: A tuple containing the latitude, longitude, and altitude
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

def convert_dng_coordinates(latitude, longitude, altitude) -> Tuple[float, float, float]:
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


def dms_to_decimal(dms: List[Union[int, Fraction]]) -> float:
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


def find_value_in_dic(dictionary: Dict[str, Any], key_searched: str) -> Optional[Any]:
    """
    This function recursively searches for a key in a nested dictionary structure and
    returns the associated value if the key is found.

    Parameters:
    - dictionary (Dict[Any, Any]): The dictionary in which to search for the key.
    - key_searched (str): The key to search for in the dictionary.

    Returns:
    - Optional[Any]: The value associated with the key_searched if it is found;
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


def display_dictionary(dictionary: Dict[str, Any], indentation=""):
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


def extract_geotag_AVR(dic_geo: Dict[str, Any]):
    # direct query of OSM without using the geopy library
    try:
        try:
            geolocator = Nominatim(user_agent="IRdrone")

            session = Session()
            session.verify = True
            geolocator.adapter.session = session
            latitude_AVR, longitude_AVR = dic_geo.get('lat'), dic_geo.get('lon')

            api_OSM = f"https://nominatim.openstreetmap.org/reverse?format=geocodejson&lat={latitude_AVR}&lon={longitude_AVR}"
            location_AVR = json.loads(requests.get(api_OSM).text)
            road = find_value_in_dic(location_AVR, 'road')
            label_road = find_value_in_dic(location_AVR, 'label').split(",")[0]
            lieu_dit = find_value_in_dic(location_AVR, 'district')
            if label_road != lieu_dit:
                road = label_road
            else:
                road = None
            dic_geo['road'] = road
            dic_geo['lieu_dit'] = lieu_dit
            dic_geo['ville'] = find_value_in_dic(location_AVR, 'level8')
            dic_geo['code_postal'] = find_value_in_dic(location_AVR, 'postcode')
            dic_geo['dept'] = find_value_in_dic(location_AVR, 'level6')
            dic_geo['region'] = find_value_in_dic(location_AVR, 'level4')
            dic_geo['pays'] = find_value_in_dic(location_AVR, 'level3')


        except AttributeError as e:
            print(f"Pas de coordonnées GPS pour ce point.")
            dic_geo['road'], dic_geo['lieu_dit'], dic_geo['ville'], dic_geo['code_postal'], dic_geo['dept'], dic_geo['region'], dic_geo['pays'] = None, None, None, None, None, None, None

    except Exception as e:
        print("error", e,)


def display_dictionary_EXIF_jpg(exif_dict: Dict[str, Any], tag_type=None, indentation="", verbose=False) -> Dict[str, Any]:
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



def extract_exif_data(file_path: str) -> Dict[str, Any]:
    """
    Extract and return EXIF data from a DNG file.

    :param file_path: str, path to the DNG file.
    :return: Dict[str, Any], extracted EXIF data.
    """
    exif_data = {}

    # Open the image file and extract the EXIF data
    with open(file_path, 'rb') as f:
        exif_data = exifread.process_file(f)

    return exif_data


def display_exif_data(exif_data: Dict[str, Any], indentation="", verbose=False) -> Dict[str, Any]:
    """
    Recursively display and return EXIF data.

    :param exif_data: Dict[str, Any], the EXIF data to display.
    :param indentation: str, the current indentation level for display.
    :return: Dict[str, Any], a new dictionary with readable EXIF data.
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

"""
import libxmp

def extract_xmp_data(file_path: str) -> libxmp.XMPMeta:

        # Extract XMP data from an image file.
    
        #:param file_path: str, path to the image file.
        #:return: libxmp.XMPMeta, extracted XMP data.

 
    with open(file_path, 'rb') as f:
        xmp_file = libxmp.files.XMPFiles(file_path=file_path, open_forupdate=False)
        xmp = xmp_file.get_xmp()
        return xmp


def display_xmp_data(xmp: libxmp.XMPMeta) -> None:

    #Display XMP data.

    #:param xmp: libxmp.XMPMeta, the XMP data to display.

    for schema in xmp:
        print(f"Schema namespace: {schema.namespace}")
        for prop in schema:
            print(f"  Property: {prop.name}")
            print(f"    Value: {prop.value}")
            
"""






