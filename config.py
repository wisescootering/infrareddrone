from pathlib import Path
import os
__version__ = 1.30

#  Expert User Settings ! -------------------------------------------------------------------------------------
NIR_CAMERA = "M20_RAW"  # Format of the original near infrared image
VIS_CAMERA = "DJI_RAW"  # Format of the original visible image
CROP = 50       # Final crop after alignment  3992 x 2992 -> 3892 x 2892   (3892 - 2* PRE_CROP)x(2892 - 2* PRE_CROP)
PRE_CROP = 4    # RawTherapee cropping from the original . DNG image   4000 x 3000 -> 3992 x 2992  (4000 - 2* PRE_CROP)x(3000 - 2* PRE_CROP)
VIS_CAMERA_PIX_X = 4000     # Image size (width).  Visible camera (DJI)
VIS_CAMERA_PIX_Y = 3000     # Image size (height). Visible camera (DJI)
VIS_LPIX = 1.6 * 10 ** -6   # Visible camera pixel size. DJI Mavic Air 2.   (1.6 micron meter)
VIS_CAMERA_F_MAX = 2.8  # Maximum aperture
IRD_CAMERA_MAKER = "irdrone"
IRD_CAMERA_MODEL = "multispectral"
IRD_CAMERA_DESCRIPTION = "DJI-FC3170-Mavic_Air_2|SJCAM-M20-SJCam_M20|Kolarivision-720-nm"
IRD_CAMERA_SERIAL_NUMBER = "2022-V001"
IRD_PIX_X = VIS_CAMERA_PIX_X - 2*CROP - 2*PRE_CROP  # Image size (width).  Output from the alignment process
IRD_PIX_Y = VIS_CAMERA_PIX_Y - 2*CROP - 2*PRE_CROP  # Image size (height). Output from the alignment process
IRD_LPIX = VIS_LPIX
IRD_FOCAL_FACTOR = 0.75     # Default value
IRD_FOCAL_LENGTH = 4.6     # Default value
IRD_FOCAL_LENGTH_35MM = 27     # Default value
IRD_FOCAL_LENGTH_PIX = 2898     # Default value
IRD_LENS_INFO = '%s mm f/%s' % (str(round(IRD_FOCAL_LENGTH_35MM, 0)), str(round(VIS_CAMERA_F_MAX,1)))
OVERLAP_X = 0.30    #
OVERLAP_Y = 0.75    # Image Overlay for mapping   [0.50 ; 0.90]
CNIRCVIS_0 = 0.046  # Distance between the lenses of two cameras (DJI Mavic Air 2 and SJCam M20) = 46 mm.


# User Settings --------------------------------------------------------------------------------------
NIR_FILTER_MAKER = 'OpticsConcept'  #
NIR_FILTER_MODEL = 830             # cut wavelength ( in nanometers nm) of the NIR camera filter
COPYRIGHT = "Copyright"
ARTIST = "Artist"

# Default folders
OUTPUT_FOLDER_NAME = os.environ.get("IRDRONE_WORKING_DIR", r"C://Air-Mission")
OUTPUT_FOLDER_NAME = Path(OUTPUT_FOLDER_NAME)


# ------------------------------------------------------
# ExifTool path detection (Windows / Linux / macOS)
# ------------------------------------------------------
if os.name == 'nt':
    EXIFTOOLPATH = os.path.join(
        os.path.dirname(__file__),
        "..", "thirdparty", "exiftool", "exiftool.exe"
    )
else:
    EXIFTOOLPATH = os.environ.get("EXIFTOOLPATH", "/usr/bin/exiftool")
    assert Path(EXIFTOOLPATH).exists(), "Use environment variable EXIFTOOLPATH to set the exiftool path."
assert Path(EXIFTOOLPATH).exists()
if os.name == 'nt' and not os.path.exists(EXIFTOOLPATH):
    print(f"[WARNING] ExifTool not found at {EXIFTOOLPATH}")


# ------------------------------------------------------
# SJCam RAW→DNG converter path
# ------------------------------------------------------
if os.name == 'nt':
    SJCONVERTERPATH = os.path.join(
        os.path.dirname(__file__),
        "..", "thirdparty", "sjcam_raw2dng", "sjcam_raw2dng.exe"
    )
else:
    SJCONVERTERPATH = os.environ.get("SJCONVERTERPATH", "sjcam_raw2dng")
if os.name == 'nt' and not os.path.exists(SJCONVERTERPATH):
    print(f"[WARNING] SJCam RAW converter not found at {SJCONVERTERPATH}")

# ------------------------------------------------------
#     RAWTHERAPEEPATH    convert dng  to tif 16:8 bits  jpg  png ...
# ------------------------------------------------------

if os.name == 'nt':
    RAWTHERAPEEPATH = r"C:\Program Files\RawTherapee\5.8\rawtherapee-cli.exe"
    assert os.path.exists(RAWTHERAPEEPATH), \
        "Please install raw therapee first http://www.rawtherapee.com/downloads/5.8/ \nshall be installed:{}".format(RAWTHERAPEEPATH)
else:
    RAWTHERAPEEPATH = "rawtherapee-cli" # For docker
    RAWTHERAPEEPATH = os.environ.get("RAWTHERAPEEPATH", "/usr/bin/rawtherapee-cli")