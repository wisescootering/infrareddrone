# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
#   IR_drone interactive
# ---------------------------------------------------------------------------------

import subprocess
from pathlib import Path
from typing import List
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import os.path as osp
import psutil
import piexif
from piexif import ImageIFD, ExifIFD
from datetime import datetime
import time


'''
Usage:  C:\Documents-Alain\Projet-IRdrone\Code_Python\irdrone\thirdparty\sjcam_raw2dng\sjcam_raw2dng.exe [options] file1|dir1 file2|dir2 ...

Valid options:
-h, --help          Help
-v, --version       Print version info and exit
-p, --threads <NUM> Number of threads to run. Default: 2 (0 for number of CPUS in the system)
-c, --no-color      Do not apply color calibration (for color calibration)
-m, --thumb         Add JPEG thumbnails (disabled by default to save disk space and conversion time)
-o, --output <DIR>  Output dir (must exist)
-t, --tiff          Write TIFF image to "<file>.tiff" (false by default)
-d, --dng           Write DNG image to "<file>.dng" (used by default if no output is supplied)
'''


def build_dng_name(raw_file: str) -> str:
    """
    Build the target DNG filename from a SJCam RAW file.

    Parameters
    ----------
    raw_file : str
        Path to the RAW file (e.g., '2022_0125_130446_023.RAW').

    Returns
    -------
    str
        Filename in the format 'NIR_XXXX.dng' (e.g., 'NIR_0023.dng').
    """
    raw_path = Path(raw_file)
    stem = raw_path.stem  # '2022_0125_130446_023'
    number_str = stem.split("_")[-1].zfill(4)
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



def _convert_single_raw(raw_file: str, exe_path: str, output_folder: str, nb_threads: str, verbose: bool, exiftool_path: str) -> str:
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
    subprocess.run(cmd, check=True)

    # Define original DNG path (created by sjcam_raw2dng, same stem as RAW)
    original_dng_path = Path(output_folder) / (raw_path.stem + ".dng")

    # Rename to standardized name
    if original_dng_path.exists() and original_dng_path != dng_output_path:
        original_dng_path.rename(dng_output_path)
        if verbose:
            print(f"✏ Renamed {original_dng_path.name} → {dng_output_path.name}")

    # Update EXIF from RAW filename
    # _set_exif_from_raw(dng_output_path, raw_path, verbose=verbose)
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
            executor.submit(_convert_single_raw, raw, exe, output_folder, nb_threads, verbose, exiftool_path): raw
            for raw in raw_files
        }

        for future in as_completed(future_to_raw):
            try:
                dng_path = future.result()
                dng_files.append(dng_path)
            except subprocess.CalledProcessError as e:
                print(f"⚠ Conversion failed for {future_to_raw[future]}: {e}")

    return sorted(dng_files)




if __name__ == "__main__":
    if os.name == 'nt':
        RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
        assert osp.exists(RAWTHERAPEEPATH), "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
        EXIFTOOLPATH = osp.join(osp.dirname(__file__), "..", "thirdparty", "exiftool", "exiftool.exe")
        assert osp.exists(EXIFTOOLPATH), "Requires exif tool at {} from https://exiftool.org/".format(EXIFTOOLPATH)

    else:
        RAWTHERAPEEPATH = "rawtherapee-cli"
        EXIFTOOLPATH = "exiftool"
    # Chemin vers l'exécutable

    exe_path = r"C:\Documents-Alain\Projet-IRdrone\Code_Python\irdrone\thirdparty\sjcam_raw2dng\sjcam_raw2dng.exe"
    # input_folder = r"C:\Air-Mission\FLY-20220125-1159-Blassac - Copie\Synchro"
    input_folder = r"C:\SDcard_SJCam_M20\DCIM"
    output_folder = r"C:\Air-Mission\FLY-20220125-1159-Blassac - Copie\Synchro"    #\synchro_check"
    start = time.perf_counter()
    # dng_created = convert_raw_to_dng(input_folder, output_folder, exe_path, verbose=True)
    dng_created = convert_raw_to_dng_parallel(
        input_folder=input_folder,
        output_folder=output_folder,
        exe_path=exe_path,
        nb_threads="1",
        verbose=False,
        exiftool_path=EXIFTOOLPATH,
    )
    end = time.perf_counter()
    print(f'{end - start} s   pour {len(dng_created)} fichiers')

'''
def convert_raw_to_dng(
        input_folder: str,
        output_folder: str,
        exe_path: str,
        nb_threads: str = "0",
        verbose: bool = False
) -> List[str]:
    """
    Convert all SJCam M20 .RAW files from an input folder into .DNG files,
    using the sjcam_raw2dng converter. A thumbnail is included by default.

    Parameters
    ----------
    input_folder : str
        Path to the folder containing the .RAW files.

    output_folder : str
        Path to the folder where the converted DNG files will be stored.
        The folder must already exist (the function does not create it).

    exe_path : str
        Full path to sjcam_raw2dng.exe (the RAW → DNG converter).

    nb_threads : str, optional
        Number of threads to use.
        - "0" (default): converter chooses automatically
        - "2", "4", ... : explicit thread count

    verbose : bool, optional
        If True, prints detailed information during conversion.

    Returns
    -------
    List[str]
        List of paths (strings) to the generated DNG files located
        in the output folder. Existing DNG files are not reconverted
        and are simply included in the returned list.

    Notes
    -----
    - The converter does NOT check if the DNG already exists, so the
      function performs that verification manually.
    - The "--thumb" option is automatically applied.

    Converter:  https://github.com/yanburman/sjcam_raw2dng/releases
    Usage:  C:\Documents-Alain\Projet-IRdrone\Code_Python\irdrone\thirdparty\sjcam_raw2dng\sjcam_raw2dng.exe [options] file1|dir1 file2|dir2 ...

        Valid options:
        -h, --help          Help
        -v, --version       Print version info and exit
        -p, --threads <NUM> Number of threads to run. Default: 2 (0 for number of CPUS in the system)
        -c, --no-color      Do not apply color calibration (for color calibration)
        -m, --thumb         Add JPEG thumbnails (disabled by default to save disk space and conversion time)
        -o, --output <DIR>  Output dir (must exist)
        -t, --tiff          Write TIFF image to "<file>.tiff" (false by default)
        -d, --dng           Write DNG image to "<file>.dng" (used by default if no output is supplied)
    """
    link = "https://github.com/yanburman/sjcam_raw2dng/releases"
    # Check the converter exists
    exe = Path(exe_path)
    if not exe.exists():
        raise FileNotFoundError(
            f"Converter not found: {exe_path}. "
            f"You can download it from: {link}"
        )
    # Internal helper for listing RAW files

    def list_raw_files_str(folder: str) -> List[str]:
        folder_path = Path(folder)

        if not folder_path.exists():
            raise FileNotFoundError(f"Input folder not found: {folder}")

        return [str(p) for p in sorted(folder_path.glob("*.RAW"))]

    dng_files: List[str] = []
    raw_files = list_raw_files_str(input_folder)

    for raw in raw_files:
        raw_path = Path(raw)

        # Check RAW exists
        if not raw_path.exists():
            print(f"⚠ Missing RAW file: {raw}")
            continue

        # Build destination DNG path in output folder
        dng_output_path = Path(output_folder) / (raw_path.stem + ".dng")

        # If already converted, skip
        if dng_output_path.exists():
            if verbose:
                print(f"⏭ DNG already exists, skipping: {dng_output_path.name}")
            dng_files.append(str(dng_output_path))
            continue

        if verbose:
            print(f"➡ Converting: {raw_path.name}")

        # Build command
        cmd = [
            str(exe),
            "--no-color",
            "--thumb",
            "--threads", nb_threads,
            "--output", str(output_folder),
            str(raw_path)
        ]

        # Run converter
        subprocess.run(cmd, check=True)

        # Add output path
        dng_files.append(str(dng_output_path))

    return dng_files


def list_raw_files(folder: str) -> List[Path]:
    """Retourne la liste des fichiers .RAW dans un dossier."""
    folder_path = Path(folder)

    if not folder_path.exists():
        raise FileNotFoundError(f"Dossier introuvable : {folder}")

    return sorted(folder_path.glob("*.RAW"))






'''
