# 🎮 CODE STUFF - Interactive image processing and visualization features

Along with the irdrone project comes a few useful tool, especially the interactive image processing GUI which makes complex pipelines easily tunable.

## Demo content
Run [interactive/demo.py](/interactive/demo.py) to test the image processing features.

### I/O management
* [irdrone.process](/irdrone/process.py) contains helpers
  * load images from disk
  * compare images in a side by side or grid fashion
  
```
import interactive.process as pr
import interactive.utils   as ut
pr.show(
    [
        [(ut.testimage(xsize=200, ysize=200, sat=sat ), "color rectangle %.1f"%sat) for sat in [0.1, 0.5]],
        [(ut.testimage(xsize=300, ysize=200, sat=sat), "wide %.1f"%sat) for sat in [0.3, 0.5, 1.]]
    ],
    suptitle="Comparison grid"
)
```


## 🧱 Image processing pipeline

[interactive.imagepipe.Imagepipe](/interactive/imagepipe.py) class is designed to build a simple image processing pipeline
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


![Single image interactive pipe with sliders](../illustrations/interactive_pipe.png)


### Multi-image processing
```
TRANSLATION2 = Translation("T_IMAGE2", slidersName=["TX im2", "TY im2"], inputs=[2,], outputs=[2,], vrange=(-50.,50.,0.))
imgl = [utils.testimage(xsize=720, ysize=720, sat=sat) for sat in [1., 0.]]
ip = ImagePipe(imgl, sliders=[WB, TRANSLATION2, ALPHA, GAMMA]).gui()
```
* `imagelist[0]` is used for recursive processing.
* Take a careful look at the instanciation of `TRANSLATION2` , `inputs=[2,], outputs=[2,]` are given in order to select 
  which images to apply the processingBlock to and where to redirect the output.
  

![Multi image interactive pipe with sliders](../illustrations/interactive_pipe_multiimages.png)


-------------------------
## 🧪 Testing

-------------------------
```pytest test.py```

coverage is very weak. code quality has a lot of discrepancies. sorry about that, if you're interested in contributing, making a linux version or whatever you'd like, feel free to reach out in the issues section.