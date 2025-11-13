# -*- coding: utf-8 -*-
# pylint: disable=C0103, C0301, W0703
# --------------------------------------------------------------------------------
#   IR_drone interactive
#   geo data
#   29/10/2023   V002   *
# ---------------------------------------------------------------------------------

"""
Created on 2023-12-02 00:35:10

@authors: balthazar/alain
"""

import numpy as np
import math
import re
import json
import os
import time
from typing import Optional, Any, List, Tuple, Dict

# ------------- geophysics Library --------------------------------
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from requests import Session
import requests
# -------------- IRDrone Library ------------------------------------
import IRD_interactive_utils as Uti


# ========================================
# =          Utilities for  GPS          =
# ========================================

def data_sig(coordinates: tuple[float, float]) -> Optional[dict[str, any]]:
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
        extract_geoTag(dic_geo, bypass=True)                   # extracts geocoding data (OpenStreetMap API)

    except Exception as e:
        print("error", e)

    return dic_geo


def extract_alti_IGN(coordinates: list[tuple[float, float]], interpolation: int = 0, bypass=False) -> dict[str, list[dict]]:
    """
    Calculate the altitude of a single or list of points based on its GPS latitude and longitude coordinates.
    Use get_altitudes module which takes a list of coordinates as input

    :param coordinates:  [(latitude, longitude)]    a list of tuples containing a single element here.
    :param interpolation:
    :return:
    """

    lat_lon_alti = get_altitudes(coordinates, verbose=True, bypass=False)
    dico_coordinates_IGN = {'elevations': lat_lon_alti}


    if 'elevations' in dico_coordinates_IGN and isinstance(dico_coordinates_IGN['elevations'], list) and len(dico_coordinates_IGN['elevations']) > 0:
        # print(f'DEBUG 02  {dico_coordinates_IGN}')
        return dico_coordinates_IGN['elevations'][0]
    else:
        # Gérez le cas où 'elevations' n'est pas une liste ou est vide
        print(f'DEBUG  \'elevations\' n\'est pas une liste ou est vide')
        return {'elevations': {'lon': coordinates[0][1], 'lat': coordinates[0][0], 'z': 0., 'acc': 0.}}


# =============================================================
# Altitude Retrieval Module
# =============================================================
# This section retrieves elevation data for a list of GPS coordinates (latitude, longitude).
# It first queries the IGN (Institut Géographique National, France) API, and if unavailable
# or if some coordinates fall outside French territory, it automatically falls back to the
# OpenTopoData global API.
#
# APIs used:
#     - IGN : https://data.geopf.fr/altimetrie/
#     - OpenTopoData : https://www.opentopodata.org/
#
# If both APIs fail for some coordinates, altitudes are set to 0 with a tag 'unavailable'.
#
# Main functions:
#     1️⃣ get_altitudes_IGN(coordinates, ...)       → Query IGN API
#     2️⃣ get_altitudes_OpenTopo(coordinates, ...)  → Query OpenTopoData API
#     3️⃣ get_altitudes(coordinates, ...)           → Combined fallback procedure (IGN → OpenTopo)
#
# Example:
#         coordinates = [
#         (48.3904, -4.48607),    # Brest (France)
#         (41.9028, 12.4964),     # Rome (Italy, outside IGN)
#         (41.92723, 8.73462),    # Ajaccio (France, Corsica)
#         ]
#     altitudes = get_altitudes(coordinates)
#     dico_coordinates_IGN = {'elevations': altitudes}
# Results:
#   altitudes = [{'lon': -4.48607, 'lat': 48.3904, 'z': 47.38, 'acc': 'IGN'},
#                {'lon': 12.4964, 'lat': 41.9028, 'z': 59.0, 'acc': 'OpenTopoData'},
#                {'lon': 8.73462, 'lat': 41.92723, 'z': 30.73, 'acc': 'IGN'}
#                ]
#   dico_coordinates_IGN = {'elevations': [{'lon': -4.48607, 'lat': 48.3904, 'z': 47.38, 'acc': 'IGN'},
#                                          {'lon': 12.4964, 'lat': 41.9028, 'z': 59.0, 'acc': 'OpenTopoData'},
#                                          {'lon': 8.73462, 'lat': 41.92723, 'z': 30.73, 'acc': 'IGN'}
#                                         ]
#                           }
#
#  =============================================================

# ------------------------------------------------------------
# 1️⃣  IGN API
# ------------------------------------------------------------
def get_altitudes_IGN(points, pause=0.3, batch_size=100, max_tries: int = 3, resource="ign_rge_alti_par_territoires", verbose=False):
    """
    Query the IGN (France) elevation API for a list of GPS coordinates.

    Parameters
    ----------
    points : list[tuple[float, float]]
        List of (latitude, longitude) coordinates.
    pause : float, optional
        Time delay (in seconds) between consecutive requests to avoid HTTP 429 errors.
        Default = 0.3.
    batch_size : int, optional
        Number of coordinates per batch request. Default = 100.
    resource : str, optional
        IGN data source identifier (default: 'ign_rge_alti_par_territoires').
        Other options include:
            - 'ign_rge_alti_wld'
            - 'ign_lidar_hd_mnx_multi_wld' (high-resolution LiDAR)
    verbose : bool, optional
        If True, prints diagnostic messages.

    Returns
    -------
    list[dict]
        List of dictionaries, each containing:
            {
                "lat": float,       # Latitude
                "lon": float,       # Longitude
                "z": float,         # Altitude in meters (-99999.00 if unavailable)
                "acc": str          # Accuracy or source tag ('IGN', 'unavailable', etc.)
            }

    Notes
    -----
    - Up to max_tries attempts are made per batch if the IGN API is temporarily unavailable.
    - If all attempts fail, altitudes are set to -99999.00.
    - Points outside French coverage may return z = -99999.00.
    """

    results = []
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        lats = "|".join(str(lat) for lat, lon in batch)
        lons = "|".join(str(lon) for lat, lon in batch)
        url = (
            "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
            f"?lon={lons}&lat={lats}&resource={resource}"
            "&delimiter=|&indent=false&measures=false&zonly=false"
        )
        # To simulate an unavailable URL, uncomment:
        # url = "https://data.geopf.fr/altimetrie_bad/"

        success = False
        for attempt in range(max_tries):  # Three attempts
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    results.extend(response.json().get("elevations", []))
                    for r in results:
                        r['acc'] = "IGN"
                        if r['z'] == -99999.00:
                            r['acc'] = "unavailable"
                    success = True
                    break
                elif response.status_code == 429:
                    retry = int(response.headers.get("retry-after", 5))
                    print(f"⚠️ Too many IGN requests, waiting {retry}s...")
                    time.sleep(retry)
                elif response.status_code == 405:
                    print(f"⚠️ Attempt {attempt+1}/{max_tries} failed. Invalid IGN URL:\n {url}")
                else:
                    print(f"❌ HTTP Error IGN {response.status_code}: {response.text}")
            except requests.RequestException as e:
                print(f"⚠️ Attempt {attempt+1}/{max_tries} failed (IGN): {e}")
                time.sleep(2)

        if not success:
            print(f"⚠ IGN unavailable for this batch, altitudes set to -99999.00")
            results.extend([
                {"lat": lat, "lon": lon, "z": -99999.00, "acc": "IGN_error"}
                for lat, lon in batch
            ])

        time.sleep(pause)
    return results


# ------------------------------------------------------------
# 2️⃣  OpenTopoData API
# ------------------------------------------------------------
def get_altitudes_OpenTopo(points, pause=0.3, batch_size=100, max_tries: int = 3, dataset="aster30m", verbose=False):
    """
    Query the OpenTopoData API for elevation data (global coverage).

    Parameters
    ----------
    points : list[tuple[float, float]]
        List of (latitude, longitude) coordinates.
    pause : float, optional
        Time delay (in seconds) between consecutive requests. Default = 0.3.
    batch_size : int, optional
        Number of coordinates per batch request. Default = 100.
    dataset : str, optional
        Dataset name (default: 'aster30m').
        Common options include:
            - 'aster30m'
            - 'srtm90m'
            - 'mapzen'
    verbose : bool, optional
        If True, prints detailed information about API calls.

    Returns
    -------
    list[dict]
        List of dictionaries, each containing:
            {
                "lat": float,
                "lon": float,
                "z": float,     # Altitude in meters (0 if unavailable)
                "acc": str      # 'OpenTopoData' or 'unavailable'
            }

    Notes
    -----
    - Up to max_tries attempts are made per batch.
    - If the service is unavailable, all altitudes in the batch are set to 0.
    """

    results = []
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        locations = "|".join(f"{lat},{lon}" for lat, lon in batch)
        url = f"https://api.opentopodata.org/v1/{dataset}?locations={locations}"
        # To simulate an unavailable URL, uncomment:
        # url = "https://api.opentopodata.bad"

        success = False
        for attempt in range(max_tries):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "results" in data:
                        for r in data["results"]:
                            results.append({
                                "lat": r["location"]["lat"],
                                "lon": r["location"]["lng"],
                                "z": r.get("elevation", 0),
                                "acc": "OpenTopoData"
                            })
                        success = True
                        break
                    else:
                        print("⚠️ OpenTopo response missing 'results'")
                else:
                    print(f"❌ HTTP Error OpenTopo {response.status_code}")
            except requests.RequestException as e:
                print(f"⚠️ Attempt {attempt+1}/{max_tries} failed (OpenTopo): {e}")
                time.sleep(2)

        if not success:
            print("⚠ OpenTopo unavailable, altitudes set to 0 m")
            results.extend([
                {"lat": lat, "lon": lon, "z": 0, "acc": "unavailable"}
                for lat, lon in batch
            ])

        time.sleep(pause)
    return results


# ------------------------------------------------------------
# 3️⃣  Combined procedure: IGN → OpenTopo fallback
# ------------------------------------------------------------
def get_altitudes(coordinates, verbose=False, bypass=False):
    """
    Combined elevation retrieval using IGN (France) first, then OpenTopoData fallback.

    Parameters
    ----------
    coordinates : list[tuple[float, float]]
        List of (latitude, longitude) coordinates.
    verbose : bool, optional
        If True, prints step-by-step progress information.

    Returns
    -------
    list[dict]
        Final list of latitude, longitude,  altitude and acc data for all points, combining both sources as needed.
        {'lat': float, 'lon': float, 'z': float, 'acc': string }

    Behavior
    --------
    1. Query IGN API for all points.
    2. If IGN completely fails → switch to OpenTopoData for all points.
    3. If some points have z = -99999.00 (outside France) → requery those with OpenTopoData.
    4. If OpenTopoData also fails → set z = 0 and acc = 'unavailable'.
    """

    if bypass:
        dico_coordinates_GPS = force_sea_Level(coordinates)
        print("Ground level set to zero (bypass)")
        return dico_coordinates_GPS

    if verbose:
        print("🌍 Step 1: querying IGN...")
    dico_coordinates_GPS = get_altitudes_IGN(coordinates)

    # Check if IGN completely failed
    if all(p["z"] == -99999.00 for p in dico_coordinates_GPS):
        if verbose:
            print("⚠️ IGN unavailable. Switching completely to OpenTopoData...")
        dico_coordinates_GPS = get_altitudes_OpenTopo(coordinates)
        return dico_coordinates_GPS

    # Points with z = -99999 (outside France)
    missing_points = [(p["lat"], p["lon"]) for p in dico_coordinates_GPS if p["z"] == -99999.00]
    if missing_points:
        if verbose:
            print(f"⚠️ {len(missing_points)} points outside France detected. Querying OpenTopoData...")
        topo_data = get_altitudes_OpenTopo(missing_points)
        topo_dict = {(p["lat"], p["lon"]): p for p in topo_data}

        # Replace missing points only
        for p in dico_coordinates_GPS:
            if p["z"] == -99999.00:
                key = (p["lat"], p["lon"])
                if key in topo_dict:
                    p.update(topo_dict[key])
                else:
                    p.update({"z": 0, "acc": "unavailable"})

    return dico_coordinates_GPS


def extract_alti_IGN_From_API(coordinates: List[Tuple[float, float]], bypass: bool = False, verbose: bool = False) -> Optional[Dict[str, Optional[float]]]:
    dico_coordinates_GPS = get_altitudes(coordinates, verbose=True, bypass=False)
    dic_geo = {'elevations': dico_coordinates_GPS}   # enhanced dictionary
    return dic_geo


def altitude_IGN(coordGPS: list[float], interpolation=0, bypass=False):
    """
    recupère la liste des altitudes géographiques (IGN) à partir d'une liste de coordonnées coordGPS
    :param coordGPS:       liste de coordennées GPS [(lat,long),....]
    :param interpolation   non utilisé
    :param bypass:     si True extract_alti_IGN_From_API renvoie z=0. sans interroger l'API
    :return: altitude

    exemple :

    coordGPS = [
                (48.3904, -4.48607),    # Brest (France)
                (41.9028, 12.4964),     # Rome (Italy, outside IGN)
                (41.92723, 8.73462),    # Ajaccio (France, Corsica)
                ]

    dico_coordinates_IGN = {'elevations': [{'lon': -4.48607, 'lat': 48.3904, 'z': 47.38, 'acc': 'IGN'},
                                          {'lon': 12.4964, 'lat': 41.9028, 'z': 59.0, 'acc': 'OpenTopoData'},
                                          {'lon': 8.73462, 'lat': 41.92723, 'z': 30.73, 'acc': 'IGN'}
                                         ]
                           }
    altitude = [47.38, 59.0, 30.73]

    """
    altitude = []
    dico_coordinates_IGN = extract_alti_IGN_From_API(coordGPS, verbose=False, bypass=bypass)
    try:
        for pt_coord in dico_coordinates_IGN['elevations']:
            altitude.append(pt_coord['z'])
    except Exception as e:
        print("error in altitude_trk ", e)

    return altitude


def force_sea_Level(coordinates, hlevel: float = 0.):
    dico_coordinates_IGN = {'elevations': []}
    for i in range(len(coordinates)):
        dic_pt = {'lon': coordinates[i][1],
                  'lat': coordinates[i][0],
                  'z': hlevel,
                  'acc': 'force_sea_Level'}
        dico_coordinates_IGN['elevations'].append(dic_pt)
    return dico_coordinates_IGN


def extract_geoTag(dic_geo: dict[str, Any],
                   max_retries: int = 3,
                   verbose: bool = True,
                   bypass: bool = False,
                   bypass_data: Optional[dict[str, Any]] = None
                   ) -> dict[str, Optional[Any]]:
    """
    Enrichit un dictionnaire avec des informations géographiques via l'API Nominatim.
    Effectue plusieurs tentatives en cas d'échec de connexion.

    Paramètres
    ----------
    dic_geo : dict
        Dictionnaire contenant au minimum les clés 'lat' et 'lon'.
    max_retries : int, optionnel
        Nombre maximal de tentatives en cas d'échec (défaut = 3).
    verbose : bool, optionnel
        Si True, affiche des informations de diagnostic.

    Retour
    ------
    dict
        Le dictionnaire d'origine enrichi avec les clés :
        ['road', 'lieu_dit', 'ville', 'code_postal', 'dept', 'region', 'pays'].
        Si la géolocalisation échoue, ces clés sont présentes mais valent None.
        :type dic_geo:
    """
    print(f'DEBUG extract geoTag   bypass = {bypass}')
    # Clés à toujours garantir dans le dictionnaire de sortie
    fields = ['road', 'lieu_dit', 'ville', 'code_postal', 'dept', 'region', 'pays']
    for f in fields:
        dic_geo.setdefault(f, None)

    # Vérification des coordonnées
    if 'lat' not in dic_geo or 'lon' not in dic_geo:
        if verbose:
            print("⚠️ Pas de coordonnées GPS valides dans dic_geo.")
        return dic_geo

    lat, lon = dic_geo['lat'], dic_geo['lon']

    # Mode bypass : retourne des valeurs factices/simulées sans appeler l'API
    if bypass:
        if verbose:
            print("ℹ️ bypass activé : pas d'appel réseau pour la géolocalisation.")
        if bypass_data:
            # On remplit uniquement les clés attendues depuis bypass_data
            for k in fields:
                dic_geo[k] = bypass_data.get(k, dic_geo.get(k))
        else:
            # Génération simple de valeurs plausibles/indicatives
            dic_geo['road'] = dic_geo.get('road') or f"Route near {lat:.4f},{lon:.4f}"
            dic_geo['lieu_dit'] = dic_geo.get('lieu_dit') or None
            # Ville approximative si fournie, sinon "Unknown" + hash court
            dic_geo['ville'] = dic_geo.get('ville') or f"LOC_{abs(hash((lat, lon))) % 1000}"
            dic_geo['code_postal'] = dic_geo.get('code_postal') or None
            dic_geo['dept'] = dic_geo.get('dept') or None
            dic_geo['region'] = dic_geo.get('region') or None
            dic_geo['pays'] = dic_geo.get('pays') or None
        return dic_geo


    # Initialisation du géocodeur avec une session HTTPS vérifiée
    geolocator = Nominatim(user_agent="IRdrone")
    session = Session()
    session.verify = True
    geolocator.adapter.session = session

    # Boucle de tentatives
    for attempt in range(1, max_retries + 1):
        try:
            location = geolocator.reverse((lat, lon), language='fr', timeout=5)
            if location and location.raw and 'address' in location.raw:
                address = location.raw['address']

                dic_geo['road'] = address.get('road')
                dic_geo['lieu_dit'] = (
                    address.get('hamlet')
                    or address.get('farm')
                    or address.get('isolated_dwelling')
                    or address.get('locality')
                    or address.get('city_block')
                    or address.get('district')
                )
                dic_geo['ville'] = (
                    address.get('village')
                    or address.get('city')
                    or address.get('municipality')
                    or address.get('town')
                )
                dic_geo['code_postal'] = address.get('postcode')
                dic_geo['dept'] = address.get('county')
                dic_geo['region'] = address.get('state')
                dic_geo['pays'] = address.get('country')

                if verbose:
                    print(f"✅ Géolocalisation réussie (tentative {attempt}) : {dic_geo['ville'] or '?'}")
                return dic_geo

            else:
                if verbose:
                    print(f"⚠️ Aucune donnée d'adresse renvoyée (tentative {attempt}).")

        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            if verbose:
                print(f"⏳ Tentative {attempt}/{max_retries} : échec ({e}). Nouvelle tentative dans {attempt} s...")
            time.sleep(attempt)  # pause progressive

        except Exception as e:
            if verbose:
                print(f"❌ Erreur inattendue (tentative {attempt}) : {e}")
            time.sleep(attempt)

    # Si toutes les tentatives échouent
    if verbose:
        print(f"🚫 Impossible d'obtenir la géolocalisation après {max_retries} tentatives.")
    dic_geo.setdefault('road', dic_geo.get('road') or None)
    dic_geo.setdefault('lieu_dit', dic_geo.get('lieu_dit') or None)
    dic_geo.setdefault('ville', dic_geo.get('ville') or None)
    dic_geo.setdefault('code_postal', dic_geo.get('code_postal') or None)
    dic_geo.setdefault('dept', dic_geo.get('dept') or None)
    dic_geo.setdefault('region', dic_geo.get('region') or None)
    dic_geo.setdefault('pays', dic_geo.get('pays') or None)

    return dic_geo



def extract_geoTag_old(dic_geo: dict[str, any]) -> dict[str, Optional[any]]:
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
                lat = dic_geo['lat']
                lon = dic_geo['lon']

                location = geolocator.reverse((lat, lon), language='fr')
                print(f'{geolocator.api} OK timeout :{geolocator.timeout}')
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


def dstUTM(lat1, lon1, lat2, lon2):
    """
    param lat1: latitude  point P1  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon1: longitude point P1  dd.ddddddd   ( < 0 si W  > 0 si E )
    param lat2: latitude  point P2  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon2: longitude point P2  dd.ddddddd   ( < 0 si W  > 0 si E )

    return:  dstUTM  Euclidean distance between P1 and P2  in m

    x1: Point P1  UTM coordinate W-E
    y1: Point P1  UTM coordinate S-N
    x2: Point P2  UTM coordinate W-E
    y2: Point P2  UTM coordinate S-N

    Calculation of the distance between two points P1 and P2 on the earth surface.
    We assume that the earth is an ellipsoid  (WGS84).
    A compliant transverse Mercator projection is used. (UTM means Universal Transverse Mercator projection)
    Points are identified by their geocentric coordinates latitude,longitude (input).
    Geocentric coordinates are converted to UTM coordinates x,y.
    The transverse projection of Mercator is a conformal map.
    Conformal map is a function that locally preserves angles, but not necessarily lengths.
    In other words, it's therefore easy to determine the direction between two points
    relative to the geographic north.
    In the (x,y) plan we can use the Euclidean distance.
    The approximation is excellent in each UTM zone.
    """
    x1, y1, zoneUTM1 = geo2UTM(lat1, lon1)
    x2, y2, zoneUTM1 = geo2UTM(lat2, lon2)
    dstUtm = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
    return dstUtm


def capUTM(lat1, lon1, lat2, lon2):
    """
    param lat1: latitude  point P1  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon1: longitude point P1  dd.ddddddd   ( < 0 si W  > 0 si E )
    param lat2: latitude  point P2  dd.ddddddd   ( < 0 si S  > 0 si N )
    param lon2: longitude point P2  dd.ddddddd   ( < 0 si W  > 0 si E )

    return:    capUTM  heading between P1 and P2 from the geographic north

    x1: Point P1  UTM coordinate W-E
    y1: Point P1  UTM coordinate S-N
    x2: Point P2  UTM coordinate W-E
    y2: Point P2  UTM coordinate S-N
    """
    x1, y1, zoneUTM1 = geo2UTM(lat1, lon1)
    x2, y2, zoneUTM1 = geo2UTM(lat2, lon2)
    cap = 0.
    if y1 == y2:
        if x1 > x2:
            cap = 270.
        else:
            cap = 90.
    else:
        if (y2 - y1) > 0 and (x2 - x1) >= 0:  # cadran N°1  N / E
            cap = np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) < 0 <= (x2 - x1):  # cadran N°2  E / S
            cap = 180 - np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) < 0 and (x2 - x1) <= 0:  # cadran N°3  S / W
            cap = 180. + np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        elif (y2 - y1) > 0 >= (x2 - x1):  # cadran N°4  W / N
            cap = 360. - np.abs(np.rad2deg(np.arctan((x2 - x1) / (y2 - y1))))
        else:
            pass
    return cap


def geo2UTM(lat, lon):
    """
    param lat: latitude  point P  dd.ddddddd   (<0 si S  >0 si N )
    param lon: longitude point P  dd.ddddddd   (<0 si W  >0 si E )
    return: xUTM, yUTM  UTM coordinates in m

    Conversion of geocentric coordinates to UTM coordinates.
    They are accurate to around a millimeter within 3000 km of the central meridian.
    https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system

    Values for test
                lat = 5°50'51"     lon= 45°09'33"
                lat= 5.8475 °      lon= 45.1591667°
                fuseau 31  [0°, 6°]   lamb0=3°
                lamb-lamb0= 0.0496983 rad
                AA= 0.0350442107
                BB= 1.00169
                C= 0.0033510263
                T= 1.01117395
                S= 0.784340804
                xUTM= 723.80393 km  yUTM= 5004.57704 km
                xUTM= 723803.93 m   yUTM= 5004577.04 m
    """
    a = 6378137.000  # equatorial radius in meter
    f = 1. / 298.257223563
    K0 = 0.9996

    zoneUTM = math.floor((lon + 180.) / 6.) + 1  # N° zone UTM
    phi = np.deg2rad(lat)  # convert Degrees to Radians
    if phi >= 0.:
        N0 = 0
    else:
        N0 = 10000000.

    lamb = np.deg2rad(lon)
    lamb0 = np.deg2rad((zoneUTM - 30) * 6. - 3.)  # longitude of the center of the UTM zone
    E0 = 500000  # in meter
    n = f / (2 - f)
    A = (a / (1. + n)) * (1. + 1. / 4 * n ** 2 + 1. / 64 * n ** 4)
    t = np.sinh(np.arctanh(np.sin(phi))
                - (2. * np.sqrt(n) / (1. + n)) * np.arctanh((2. * np.sqrt(n) / (1. + n)) * np.sin(phi))
                )
    zeta = np.arctan(t / np.cos(lamb - lamb0))
    eta = np.arctanh(np.sin(lamb - lamb0) / np.sqrt(1. + t ** 2))

    x0 = E0 + K0 * A * eta
    x1 = (1. / 2 * n - 2. / 3 * n ** 2 + 5. / 16 * n ** 3) * np.cos(2 * zeta) * np.sinh(2 * eta)
    x2 = (13. / 48 * n ** 2 - 3. / 5 * n ** 3) * np.cos(4 * zeta) * np.sinh(4 * eta)
    x3 = (61. / 240 * n ** 3) * np.cos(6 * zeta) * np.sinh(6 * eta)
    y0 = N0 + K0 * A * zeta
    y1 = (1. / 2 * n - 2. / 3 * n ** 2 + 5. / 16 * n ** 3) * np.sin(2 * zeta) * np.cosh(2 * eta)
    y2 = (13. / 48 * n ** 2 - 3. / 5 * n ** 3) * np.sin(4 * zeta) * np.cosh(4 * eta)
    y3 = (61. / 240 * n ** 3) * np.sin(6 * zeta) * np.cosh(6 * eta)

    xUTM = round(x0 + K0 * A * (x1 + x2 + x3), 3)    # mm
    yUTM = round(y0 + K0 * A * (y1 + y2 + y3), 3)    # mm

    return xUTM, yUTM, zoneUTM


def UTM2geo(xUTM, yUTM, zoneUTM):
    """
    param:  xUTM     in m
    param:  yUTM     in m
    param:  zoneUTM
    return:  lat    Latitude in DD.ddddd°
    return:  lon    Longitude in DD.ddddd°


    These formulae are truncated version of Transverse Mercator:
    flattening series, which were originally derived by Johann Heinrich Louis Krüger in 1912.
    They are accurate to around a millimeter within 3000 km of the central meridian.
    https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system

     phi <=>  long
     lamb <=> lat
    """
    a = 6378137.000  # equatorial radius in m
    f = 1. / 298.257223563
    K0 = 0.9996
    N0 = 0  #
    E0 = 500000  # in meter
    n = f / (2 - f)
    A = (a / (1. + n)) * (1. + 1. / 4 * n ** 2 + 1. / 64 * n ** 4 + 1. / 256 * n ** 6)
    #
    zeta0 = (yUTM - N0) / (K0 * A)
    eta0 = (xUTM - E0) / (K0 * A)

    zeta1 = (1. / 2 * n - 2. / 3 * n ** 2 + 37. / 96 * n ** 3) * np.sin(2 * zeta0) * np.cosh(2 * eta0)
    eta1 = (1. / 2 * n - 2. / 3 * n ** 2 + 37. / 96 * n ** 3) * np.cos(2 * zeta0) * np.sinh(2 * eta0)
    zeta2 = (1. / 48 * n ** 2 + 1. / 15 * n ** 3) * np.sin(4 * zeta0) * np.cosh(4 * eta0)
    eta2 = (1. / 48 * n ** 2 + 1. / 15 * n ** 3) * np.cos(4 * zeta0) * np.sinh(4 * eta0)
    zeta3 = (17. / 480 * n ** 3) * np.sin(6 * zeta0) * np.cosh(6 * eta0)
    eta3 = (17. / 480 * n ** 3) * np.cos(6 * zeta0) * np.sinh(6 * eta0)

    zeta = zeta0 - (zeta1 + zeta2 + zeta3)
    eta = eta0 - (eta1 + eta2 + eta3)

    phi0 = np.arcsin(np.sin(zeta) / np.cosh(eta))
    phi1 = (2. * n - 2. / 3 * n ** 2 - 2. * n ** 3) * np.sin(2 * phi0)
    phi2 = (7. / 3 * n ** 2 - 8. / 5 * n ** 3) * np.sin(4 * phi0)
    phi3 = (56. / 15 * n ** 3) * np.sin(6 * phi0)
    phi = phi0 + phi1 + phi2 + phi3

    lamb0 = np.deg2rad(zoneUTM * 6 - 183)
    lamb = lamb0 + np.arctan(np.sinh(eta) / np.cos(zeta))

    lat = np.rad2deg(phi)
    lon = np.rad2deg(lamb)
    return lat, lon


def segmentUTM(lat1, lon1, lat2, lon2):
    dstUtm = round(dstUTM(lat1, lon1, lat2, lon2), 4)
    capUtm = round(capUTM(lat1, lon1, lat2, lon2), 4)
    return dstUtm, capUtm


def GPSdms2GPSdd(coord):
    """
    :param coord:   (dd,mm,ss.ssss)

    :return: coordDD    dd.dddddddd           float

    Conversion from dd° mm' ss.sssss"   en dd.dddddddd
    """
    coordDD = coord[0] + coord[1] / 60 + coord[2] / 3600
    return coordDD


def calcul_distance(latLongZ: list[[float, float, float]]):
    """
    Calculates the distance and cape between GPS points on a path (trk).
    :param  latLongZ:   list of GPS coordinates of points P0,P1,P2,P3    [...,(lat,long,z),...]

    :return: distP0P1  distance between point Pi and point Pi+1 (in meters)
            capP0P1    cape between point Pi and point Pi+1 (in degrees)
    """
    distP0P1 = []
    capP0P1 = []
    nPt = len(latLongZ)
    for ind in range(nPt - 1):
        distP0P1.append(dstUTM(latLongZ[ind][0], latLongZ[ind][1], latLongZ[ind + 1][0], latLongZ[ind + 1][1]))
        capP0P1.append(capUTM(latLongZ[ind][0], latLongZ[ind][1], latLongZ[ind + 1][0], latLongZ[ind + 1][1]))
    distP0P1.append(0)  # no distance or cape to the next point for landing point!
    capP0P1.append(0)   # we set the value arbitrarily to 0
    return distP0P1, capP0P1


def cumul_Dist(coordLatLongZ):
    """
    param:  coordLatLongZ   liste de coordonnées GPS  [...,(lat, long,z), ...]

    return:  dst   liste des distances cumulées
    """
    cumulDist = []
    sumDist = 0
    distP0P1, capP0P1 = calcul_distance(coordLatLongZ)
    for i in range(len(coordLatLongZ)):
        cumulDist.append(sumDist)
        sumDist = sumDist + distP0P1[i]
    return cumulDist


def convertGPSExif_dms2GPSdd(repSign, coord):
    """
    :param repSign: {'E','W','S','N'}          str
    :param coord:   (dd,dd,ss.ssss)
    :return: coordDD    dd.dddddddd           float

         Conversion from dd° mm' ss.sssss"   en dd.dddddddd
    """
    if repSign == "W" or repSign == "S":
        signe = -1.
    else:
        signe = 1.
    coordDD = signe * (coord[0] + (coord[1] / 60) + (coord[2] / 3600))
    return coordDD


def printGPS(gpsLatitude, gpsLongitude, gpsAltitude):
    stringgpsLong = "%s %d° %d\' %.6f\" " % (gpsLongitude[0], gpsLongitude[1], gpsLongitude[2], gpsLongitude[3])
    stringgpsLat = "%s %d° %d\' %.6f\" " % (gpsLatitude[0], gpsLatitude[1], gpsLatitude[2], gpsLatitude[3])
    stringgpsAlt = "%.2f" % gpsAltitude
    print("  Longitude :", stringgpsLong, " |  Latitude :", stringgpsLat, " | Altitude : ", stringgpsAlt, " m")
    return


def writeGPX(listPts, dirNameVol, dateEtude, mute=True):
    """
    :param listImgMatch:
    :param dirNameVol:
    :param dateEtude:
    :param mute:
    :return:
        Construction d'un fichier gpx contenant le tracé du plan de vol
        Il y a au début une tres grosse étiquette !!
    """
    print('------ Write Garmin .gpx file')
    #  mise en forme de la date pour le format gpx Garmin
    if dateEtude.month < 10:
        monthGpx = str('0' + str(dateEtude.month))
    else:
        monthGpx = str(dateEtude.month)
    if dateEtude.day < 10:
        dayGpx = str('0' + str(dateEtude.day))
    else:
        dayGpx = str(dateEtude.day)

    dateGpx = '%i-%s-%sT00:00:00Z' % (dateEtude.year, monthGpx, dayGpx)

    #     mise en forme des coordonnées GPS pour le format gpx
    #     Il faut aussi calculer la zone GPS  définie par le domaine [maxLat,minLat]x[maxLon,minLon]
    pointTrk, maxLat, minLat, maxLon, minLon = formatCoordGPSforGpx(listPts)

    # affectation du nom du fichier  et d'une description
    nameTrkGPS = "IRdrone-%s-%s-%i" % (dayGpx, monthGpx, dateEtude.year)
    descriptionTrkGPS = str('IRdrone v01.1   Trace GPS du vol %s-%s-%i' % (dayGpx, monthGpx, dateEtude.year))

    fichierGpx = "<?xml version=\"1.0\" encoding=\"utf-8\"?>" \
                 "<gpx creator=\"IRdrone v01.1\" " \
                 "version=\"1.1\" " \
                 "xsi:schemaLocation=\"http://www.topografix.com/GPX/1/1 \" "

    fichierGpx = "{0}xmlns=\"http://www.topografix.com/GPX/1/1\" xmlns:xsi=\"" \
                 "http://www.w3.org/2001/XMLSchema-instance\" xmlns:wptx1=\"" \
                 "http://www.garmin.com/xmlschemas/WaypointExtension/v1\" xmlns:gpxtrx=\"" \
                 "http://www.garmin.com/xmlschemas/GpxExtensions/v3\" xmlns:gpxtpx=\"" \
                 "http://www.garmin.com/xmlschemas/TrackPointExtension/v1\" xmlns:gpxx=\"" \
                 "http://www.garmin.com/xmlschemas/GpxExtensions/v3\" xmlns:trp=\"" \
                 "http://www.garmin.com/xmlschemas/TripExtensions/v1\" xmlns:adv=\"" \
                 "http://www.garmin.com/xmlschemas/AdventuresExtensions/v1\" xmlns:prs=\"" \
                 "http://www.garmin.com/xmlschemas/PressureExtension/v1\" xmlns:tmd=\"" \
                 "http://www.garmin.com/xmlschemas/TripMetaDataExtensions/v1\" xmlns:vptm=\"" \
                 "http://www.garmin.com/xmlschemas/ViaPointTransportationModeExtensions/v1\" xmlns:ctx=\"" \
                 "http://www.garmin.com/xmlschemas/CreationTimeExtension/v1\" xmlns:gpxacc=\"" \
                 "http://www.garmin.com/xmlschemas/AccelerationExtension/v1\" xmlns:gpxpx=\"" \
                 "http://www.garmin.com/xmlschemas/PowerExtension/v1\" xmlns:vidx1=\"" \
                 "http://www.garmin.com/xmlschemas/VideoExtension/v1\">".format(fichierGpx)

    """
        Couleur du trait :   Red,Green,Blue,Yellow,Gray, et DarkRed, DarkGreen etc

        Attention format des dates   2021-02-11T19:00:00Z
    """

    fichierGpx = fichierGpx + "\n<metadata>\n" \
                                "<link href=\"http://www.garmin.com\">\n" \
                                "<text>Garmin International</text>\n" \
                                "</link>\n" \
                                "<time>" + dateGpx + "</time>\n" \
                                "<bounds maxlat=\"" + str(maxLat) + "\" maxlon=\"" + str(minLat) + "\" minlat=\"" + str(maxLon) + "\" minlon=\"" + str(minLon) + "\" />\n" \
                              "</metadata>\n" \
                              "<trk>\n" \
                                "<name>" + nameTrkGPS + "</name>\n" \
                                "<desc>" + descriptionTrkGPS + "</desc>\n" \
                                "<extensions>\n" \
                                     "<gpxx:TrackExtension>\n" \
                                        "<gpxx:DisplayColor>Red</gpxx:DisplayColor>\n" \
                                     "</gpxx:TrackExtension>\n" \
                                "</extensions>\n" \
                                "<trkseg>"

    for k in range(len(listPts)):
        fichierGpx = fichierGpx + pointTrk[k]

    fichierGpx = fichierGpx + "\n</trkseg>\n" \
                              "</trk>\n" \
                              "</gpx>"

    if not mute: print(fichierGpx)

    dirpath = '%s\\TrkGpx-%s-%s-%i.gpx' % (dirNameVol, dayGpx, monthGpx, dateEtude.year)

    if not mute: print('Ecriture du fichier gpx %s' % dirpath)
    if not os.path.isdir(dirNameVol):
        os.mkdir(dirNameVol)
    with open(dirpath, "w") as fichier:
        fichier.write(fichierGpx)

    return


def formatCoordGPSforGpx(listPts):
    """
    :param listImgMatch: list of images pairs
    :return: pointTrk  list of GPS coordinates (str)    (format gpx Garmin)
             sample      '<trkpt 45.05022 3.89567 >
                          <ele>110.5</ele>
                          </trkpt>'
            maxLat, minLat, maxLon, minLon
    """
    coordGPSgpxLat, coordGPSgpxLon, coordGPSgpxAlt, pointTrk = [], [], [], []
    for k in range(len(listPts)):
        lat = listPts[k].gpsLat
        long = listPts[k].gpsLon
        alti = listPts[k].altGeo + listPts[k].altGround
        coordGPSgpxLat.append(lat)
        coordGPSgpxLon.append(long)
        coordGPSgpxAlt.append(alti)
        pointTrk.append("\n<trkpt lat=\"%s\" lon=\"%s\">\n<ele>%s</ele>\n</trkpt>" % (lat, long, alti))
    maxLat = max(coordGPSgpxLat)
    minLat = min(coordGPSgpxLat)
    maxLon = max(coordGPSgpxLon)
    minLon = min(coordGPSgpxLon)

    return pointTrk, maxLat, minLat, maxLon, minLon


def extract_geotag_AVR(dic_geo: dict[str, any]):
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
            road = Uti.find_value_in_dic(location_AVR, 'road')
            label_road = Uti.find_value_in_dic(location_AVR, 'label').split(",")[0]
            lieu_dit = Uti.find_value_in_dic(location_AVR, 'district')
            if label_road != lieu_dit:
                road = label_road
            else:
                road = None
            dic_geo['road'] = road
            dic_geo['lieu_dit'] = lieu_dit
            dic_geo['ville'] = Uti.find_value_in_dic(location_AVR, 'level8')
            dic_geo['code_postal'] = Uti.find_value_in_dic(location_AVR, 'postcode')
            dic_geo['dept'] = Uti.find_value_in_dic(location_AVR, 'level6')
            dic_geo['region'] = Uti.find_value_in_dic(location_AVR, 'level4')
            dic_geo['pays'] = Uti.find_value_in_dic(location_AVR, 'level3')


        except AttributeError as e:
            print(f"Pas de coordonnées GPS pour ce point.")
            dic_geo['road'], dic_geo['lieu_dit'], dic_geo['ville'], dic_geo['code_postal'], dic_geo['dept'], dic_geo['region'], dic_geo['pays'] = None, None, None, None, None, None, None

    except Exception as e:
        print("error", e,)


