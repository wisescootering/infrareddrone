__version__ = 1.30

#  Expert User Settings ! -------------------------------------------------------------------------------------
NIR_CAMERA = "M20_RAW"  # Format of the original near infrared image
VIS_CAMERA = "DJI_RAW"  # Format of the original visible image
CROP = 50       # Final crop after alignment  3992 x 2992 -> 3892 x 2892   (3892 - 2* PRE_CROP)x(2892 - 2* PRE_CROP)
PRE_CROP = 4    # RawTherapee cropping from the original . DNG image   4000 x 3000 -> 3992 x 2992  (4000 - 2* PRE_CROP)x(3000 - 2* PRE_CROP)
VIS_CAMERA_PIX_X = 4000     # Image size (width).  Visible camera (DJI)
VIS_CAMERA_PIX_Y = 3000     # Image size (height). Visible camera (DJI)
VIS_LPIX = 1.6 * 10 ** -6   # Visible camera pixel size. DJI Mavic Air 2.   (1.6 micro meter)
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


# User Settings --------------------------------------------------------------------------------------
NIR_FILTER_MAKER = 'Kolarivision'  #
NIR_FILTER_MODEL = 720             # cut wavelength ( in nanometers nm) of the NIR camera filter
COPYRIGHT = "Copyright"
ARTIST = "Artist"

