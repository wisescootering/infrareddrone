import os
import sys
from typing import Optional, Union, Tuple, Iterable
from pathlib import Path
import shutil

# -------------- IRDrone Library -------------------------------------
import IRD_Interactive_utils as Uti

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


    # 1) Check if target exists → do nothing
    if dst.exists():
        if verbose: print(Uti.Style.CYAN + f"Target already exists, nothing done: {dst}" + Uti.Style.RESET)

    # 2) Check if source exists
    if not src.exists():
        if verbose: print(Uti.Style.YELLOW + f"⚠️  Source file not found: {src}" + Uti.Style.RESET)
        return

    # 3) Check extension
    if src.suffix.lower() != dst.suffix.lower():
        if verbose: print(Uti.Style.YELLOW + f"⚠️  Extension mismatch: {src.suffix} != {dst.suffix}" + Uti.Style.RESET)
        return

    # 4) Copy
    try:
        shutil.copy2(src, dst)   # copy2 keeps metadata
        print(f"Copied: {src} → {dst}")
    except Exception as e:
        print(f"ERROR copying file: {e}")


# --------------------------------------------------------------
# Utilisation
# --------------------------------------------------------------


if __name__ == "__main__":

    folderMissionPath = Path(r"C:\Air-Mission\FLY-20220125-1159-Blassac")
    name_folder = "Synchro"

    inputDir = Path(r"C:\SDcard_SJCam_M20\DCIM")
    inputImgName = "2022_0125_130413_001.dng"   # 2022_0125_130415_004.JPG"
    outputDir = Path(folderMissionPath)
    outputImgName = "NIR_002.dng"

    copy_and_rename_images(inputDir, inputImgName, outputDir, outputImgName)

    currentSpectralBand = "VIS"
    num_img = 12
    imgFileName = Path(outputImgName)  # Path(outputDir / outputImgName)

    print(f"{currentSpectralBand}_{num_img:03d}{imgFileName.suffix}")

    exit(2026)
