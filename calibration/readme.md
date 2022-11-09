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


## 📽️ Supporting other cameras
Here are a few words on how to re-calibrate new cameras.  Beware that the code won't run easily for new formats as there may be a bunch of things to modify to support new cameras/drones. Feel free to reach out to balthazarneveu@gmail.com in case you're interested in using this project.

### 📐 Geometric calibrations
* when using a new camera:
  * to get a planar checkerboard, either print or display on your computer screen  [Generator "8x11"](https://calib.io/pages/camera-calibration-pattern-generator)
  * shoot about 30 images of the checkerboard in various camera orientations (refer to [openCV Zhang's camera calibration](https://docs.opencv.org/master/dc/dbb/tutorial_py_calibration.html)
  * put all images in `calibration/mynewcamera`
  * `calibnewcam = irdrone.utils.cameracalibration(camera="mynewcamera", checkerboardsize=(10,7))` will take care of camera calibration
* camera calibration is located  [cameracalibration](/calibration/cameracalibration.py)  for more details to calibrate your new camera


### 🌑 Shading calibration
The [shading calibration script](/calibration/cameravignetting.py) is not publicly supported.
A white chart shall be shot to calibrate lens shading (luminance and color).

![Adjust the knobs manually to fit the profile](/illustrations/shading_profiles_fit.png).

To calibrate the radial shading of a fisheye, we use polar projections (on the left) and extract radial profiles.  ![](./illustrations/shading_profiles.png)

DJI Mavic Air 2 has some color shading (seen as a pink spot in the middle) which can't be fully compensated for. We compensate the slight luminance lens shading though (**on the left, corners aren't darker**).
![lens shading on DJI](/illustrations/shading_correction.png)

![lens shading correction on SJcam](/illustrations/shading_correction_sjcam.png)