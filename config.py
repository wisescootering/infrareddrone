__version__ = 1.30

VIS_CAMERA = "DJI_RAW"
VIS_CAMERA_PIX_X = 4000
VIS_CAMERA_PIX_Y = 3000
VIS_LPIX = 1.6 * 10 ** -6            # taille dun pixel de la caméra visible. DJI Mavis Air 2  1,6 micro metre

NIR_CAMERA = "M20_RAW"

CROP = 50                # crop final à partir de l'image RawTherapee  .tif
PRE_CROP = 4             # crop de RawTherapee  à partir de l'image .DNG originale   4000x3000 -> 3992x2992  (4000 - 2* PRE_CROP)x(3000 - 2* PRE_CROP)

IRD_CAMERA_MAKER = "irdrone"
IRD_CAMERA_MODEL = "multispectral"
IRD_CAMERA_DESCRIPTION = "DJI-FC3170-Mavic_Air_2|SJCAM-M20-SJCam_M20|Kolarivision-720-nm"
IRD_CAMERA_SERIAL_NUMBER = "2022-V001"

IRD_FOV = 67.8
IRD_LENS_INFO ="27mm f/2.8"
IRD_LENS_MODEL = 720             # longueur d'onde de coupure ( en nanomètres nm) du filtre de la caméra NIR
COPYRIGHT = "Copyright"
ARTIST = "Artist"

IRD_PIX_X = 3892
IRD_PIX_Y = 2892
IRD_LPIX = 1.6 * 10 ** -6
IRD_FOCAL_FACTOR = 0.74473279
IRD_FOCAL_LENGTH = 4.6
IRD_FOCAL_LENGTH_35MM = 27
IRD_FOCAL_LENGTH_PIX = 2900

OVERLAP_X = 0.30
OVERLAP_Y = 0.75

