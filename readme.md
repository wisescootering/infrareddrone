# Aerial drone photography project

# General information
* Author : Balthazar Neveu , Alain Neveu

# Application for botanists
### Set up

*For practical reasons*, only **windows is supported** as of now.
* [install.bat](install.bat) will set up the right python environment for you.
* you have to install *raw therapee* software at the default windows location.

### Overview
* Drone visible camera (DJI Mavic Air 2) is used to shoots RAW images
* An action camera with a wide FOV (SJCAM M20) which IR filter has been removed is attached under the drone.
* Before flying a temporal synchronization procedure has to be performed to sync the 2 cameras clocks. It consists in making the drone spin above a QR code chart. Then  use the [synchro_by_aruco.py](synchro_by_aruco.py) program to manually find the synchronization delay.
* Then the recommended way to capture your data is to go fly with both cameras shooting in timelapse modes. 
* Once finished, offload your SD cards from IR & Visible cameras into the same folder, create an excel based on a given template. Synchronization delta has to be provided in this excel for the system to work correctly.
* Data can be processed by [Debut_IRdrone_process_Alain.py](`Debut_IRdrone_process_Alain.py`) to select a given excel file or by using command line interface [automatic_registration.py](automatic_registration.py) 

## Data processing description
## Pre-processing
  * SJCam M20 .RAW files are first converted to DNG using the following program [sjcam_raw2dng](https://github.com/yanburman/sjcam_raw2dng)
  * SJCAM .DNG & DJI .DNG files are processed using Raw Therapee to **linear demosaicked RGB 16bits** TIF files.
  * Lens Shading is automatically corrected while loading the TIF files.
## Alignment
* We first undistort the DJI visible image and undisort the infrared fisheye. In case of wind, the misalignment between both cameras can be of up to 20°s. 
  Roll of the drone leads to camera yaw, Pitch of the drone leads to camera pitch. Camera roll misalignment is usually zero because of the gimbal lock when the camera points towards the ground. 
  Hopefully, the fisheye has a much wider field of view than the DJI visible camera, therefore we're able to align the NIR image onto the visible image.
* Alignment is first performed by a "coarse alignment" to compensate coarsely camera misalignment yaw (well approximated by an horizontal translation)
  and camera misalignment pitch (well approximated by a vertical translation). 
  * We first undistort the SJcam NIR fisheye and match magnification factor with the DJI camera.
    The virtual NIR undistorted camera has the same focal length as the DJI camera but a much wider field of view. 
    If there's no misalignment, the center window of the SJcam image shall overlap the visible image
  * The first step of the coarse search is performed at very low resolution first
    * with a brute force approach (searching for the X Y tranlation which minimizes a certain cost function between the visible image and a moving window in the NIR image)
    * The translation approximates the underlying yaw/pitch camera rotation which we can simply recover. It allows to warp the NIR image onto a finer scale.
* Alignment refinement is then performed on the coarsely aligned NIR image. 
  * A pyramidal approach is chosen.
  * At each level of the pyramid, we estimate a vector field of displacements (split the images into 5x5 patches for instance and search for the best displacement)
  * This local vector field is sort of regularized by a global motion model fit (homography) which allows to refine the yaw, pitch & roll angles.
  * When going to  a finer scale, we warp the image according to the global homography estimated at the previous level. This allows to reduce the search horizon.
  
## Post-processing
* Once the alignment model has been found, the NIR image is warped (only once) on the Visible image.
* Several color representation of the merge of NIR & Visible images can be computed such as NDVI or VIR.
* **Important note : color calibration shall be tackled at some point**, it may not be too difficult though.


  
## Semi-automatic fallback
While reviewing the data, there may still be some issues in alignment.
Unfortunately multispectral alignment is an ill-posed problem and sometimes the automatic system fails.
There's still a way to save your images.
  * There's a .bat file next to the results which allows you to re-run manually the images which failed. 
  * It will open a GUI where you can simply pick the yaw, pitch & roll
    to replace the coarse alignment & make the images overlap. 
    This will guide the automatic system to a manual initial guess which will eventually lead to an accurate automatic alignment.
  * If synchronization does not seem correct (or there was big wind), you can try your luck with another image by uncommenting the right line in the .bat .

## Exploiting data in third-partiy software
* Putting a timelapse into a software like Hugin allows to stictch these images.
* Putting a timelapse into [VisualSFM](http://ccwu.me/vsfm/) allows to create a 3D map out of these images 
  just like you'd do with your drone images
* Putting these data in [Pix4DFields](https://www.pix4d.com/product/pix4dfields) is possible
  * you need to copy GPS exif data from the DJI source back to the resulting jpg images.
    Utilities are provided to copy the right exif. Use at your own risk.
  ```
  vir_img = pr.Image(vir_file)
  vis_img = pr.Image(img_pth)
  vir_img.gps = vis_img.gps
  vir_img.gps["altitude"] += initial_altitude # usually DJI drone will assume starting at 0
  exif_dict_minimal = np.load("minimum_exif_dji.npy", allow_pickle=True).item()
  vir_img.save(vir_file[:-4]+"_with_exif.jpg"), exif=exif_dict_minimal)
  ```
  * When launching Pix4DFields, the DJI camera won't be supported by default. You need to import a [custom camera file](https://support.pix4d.com/hc/en-us/articles/360035481811-What-to-do-when-a-camera-is-not-supported-in-Pix4Dfields).
  Luckily, we created one for the DJI Mavic Air 2.

## Synchronization procedure
* Aruco (=QR code) chart can be downloaded [here](https://drive.google.com/file/d/1rMB6LjY2Mi3gQDq5Mr6PrtMRRrahtkRC/view?usp=sharing) and has to be printed to A4 or A3 paper
* [full procedure description is available here](https://drive.google.com/drive/folders/1Uk-eWBwteD2reOCdT0kngCWgcddz4C5s?usp=sharing).

## Camera calibration
* Officially supported cameras (camera calibrations are pre-stored in the calibration/mycamera folder)
  * DJI RAW
  * SJcam M20 RAW

---------------------------------
### Sample test
Sample is broken - *JPG not supported anymore*

2 ways to run the sample
* simply use `customApplication.py` to run a file browser which will allow you to select your excel file, then search [SampleMission/FlightPath.xslx](SampleMission/FlightPath.xslx) .

* Use `customApplication.py --excel SampleMission/FlightPath.xlsx`

## Content
2 cameras are used:
* drone visible camera
* IR camera

`Camera type`: type is located in th exif, open file details and search camera model
`Timelapse`: provides the interval between each photo in seconds
`deltatime`: provides an offset between the two cameras timestamps.
In the sample folder, you'll find image examples, deltatime is ~ 15 seconds.



------
* **Refer to the [calibration documents](https://drive.google.com/drive/folders/1wm4mNICmo9koOwB6QRJn871etPJu7mk0?usp=sharing)**


## Supporting other cameras
### Geometric calibrations
* when using a new camera:
  * to get a planar checkerboard, either print or display on your computer screen  [Generator "8x11"](https://calib.io/pages/camera-calibration-pattern-generator)
  * shoot about 30 images of the checkerboard in various camera orientations (refer to [openCV Zhang's camera calibration](https://docs.opencv.org/master/dc/dbb/tutorial_py_calibration.html)
  * put all images in `calibration/mynewcamera`
  * `calibnewcam = irdrone.utils.cameracalibration(camera="mynewcamera", checkerboardsize=(10,7))` will take care of camera calibration
* camera calibration is located  [irdrone.calibration](irdrone/cameracalibration.py)  for more details to calibrate your new camera


### Shading calibration


# Testing
```pytest irdrone\test.py```

# Image processing and visualization features
## Demo content
Run [demo.py](demo.py) to test the image processing features.

### I/O management
* [irdrone.process](irdrone/process.py) contains helpers
  * load images from disk
  * compare images in a side by side or grid fashion
  
```
import irdrone.process as pr
import irdrone.utils   as ut
pr.show(
    [
        [(ut.testimage(xsize=200, ysize=200, sat=sat ), "color rectangle %.1f"%sat) for sat in [0.1, 0.5]],
        [(ut.testimage(xsize=300, ysize=200, sat=sat), "wide %.1f"%sat) for sat in [0.3, 0.5, 1.]]
    ],
    suptitle="Comparison grid"
)
```


# Image processing pipeline
[irdrone.imagepipe.Imagepipe](irdrone/imagepipe.py) class is designed to build a simple image processing pipeline
* multiple inputs support
* configured through parameters which can be tuned with GUI sliders
* use the `.gui()` method to launch interactive tuning
* when the GUI is launched, you can use 
    * `S` to save the current image at full resolution
    * `I` to print the current tuning parameters values
    * `Q` to close the window
    * `R` to reset the parameters

Simple language is used to describe the sequence of processings.
### Example
```
imgl = [utils.testimage(xsize=720, ysize=720),]
ipBasicLinPipe = imagepipe.ImagePipe(
    imgl,
    sliders=[imagepipe.BRIGHTNESS, imagepipe.WB, imagepipe.GAMMA],
).gui()
```

Will create an image processing pipeline where first, 
* all channels can first be amplified through the brightness slider.
* then white balance can be applied (separate multiplications on blue and red channels)
* and finally a gamma tone curve is applied

```puml
@startuml 
Image_1->Image_0 : initalization [float conversion]
Image_0->Image_0: BRIGHTNESS
Image_0->Image_0: WB
Image_0->Image_0: GAMMA
Image_0->Output : output [8 bit conversion]
@enduml
```

### Multi-image processing
```
TRANSLATION2 = Translation("T_IMAGE2", slidersName=["TX im2", "TY im2"], inputs=[2,], outputs=[2,], vrange=(-50.,50.,0.))
imgl = [utils.testimage(xsize=720, ysize=720, sat=sat) for sat in [1., 0.]]
ip = ImagePipe(imgl, sliders=[WB, TRANSLATION2, ALPHA, GAMMA]).gui()
```
* `imagelist[0]` is used for recursive processing.
* Take a careful look at the instanciation of `TRANSLATION2` , `inputs=[2,], outputs=[2,]` are given in order to select 
  which images to apply the processingBlock to and where to redirect the output.
  

```puml
@startuml 
Image_1->Image_0: initialization [float conversion]
Image_0<-Image_0: WB
Image_2->Image_2: TRANSLATION2
Image_0<-Image_0: x (alpha) x Image0
Image_0<-Image_2: + (1-alpha) x Image2
Image_0->Image_0 : GAMMA
Image_0 -> Output : output [8 bit]
@enduml
```

# Legacy registration approach
## Image registration code
* Images from the drone are nearly distorsion-less
* Images from the fisheye IR camera have a much wider field of view and distorsions

Image registration works in the following manner:
* undistort IR image
* computes feature (*SIFT*) points on 2 thumbnails (800x600) of visible & undistorted IR image in grey levels
* matches features points (*Flann*)
* estimates homography between the two set of matched points
* allows for full resolution (not thumbnail) warp of the IR image onto the visible full resolution image.

## What changed?
Unfortunately this simple approach did not work correctly for multispectral alignment.
We switched to raw format to be able to use the linearity for correct IR - Visible color comparisons.