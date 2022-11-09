# -*- coding: utf-8 -*-
import irdrone.process as process
import irdrone.utils as utils
import os
import numpy as np
import matplotlib.pyplot as plt
import interactive.imagepipe as imagepipe
DISPLAY = False


def test_imagepath():
    """
    Check that samples files exist
    """
    allimgs = utils.imagepath(imgname="*")
    assert all(map(lambda x: os.path.exists(x), allimgs))


def test_loadimage():
    """
    Test image loading from disk and image path.
    """
    sampleimage = utils.imagepath()
    img = process.loadimage(sampleimage)
    assert img[0].shape == (3024, 4032, 3)
    sampleimages = utils.imagepath(imgname=["*Full*", "*IR760*"])
    imglist = process.loadimage(sampleimages)
    assert len(imglist)


def test_show(block=False, display=DISPLAY):
    """
    Single image display
    """
    process.show(
        (utils.testimage(xsize=100, ysize=100, sat=1.), "color wheel"),
        block=block
    )
    if not block and display:
        plt.show()
    plt.close()


def test_show_compare_row(block=False, display=DISPLAY):
    """
    Horizontal side by side display
    """
    process.show(
        [(utils.testimage(xsize=int(sat**2*200), ysize=int(sat*200), sat=sat ), "color wheel %.1f"%sat)
            for sat in [0.1, 0.5, 0.8, 1.]
        ],
        compare=False,
        suptitle="Comparison of several color wheels of several sizes",
        block=block
    )
    if not block and display:
        plt.show()
    plt.close()


def test_show_compare_grid(block=False,  display=DISPLAY):
    """
    grid of images display
    """
    process.show(
        process.loadimage(utils.imagepath(imgname=["*Full*", "*IR760*"])),
        title=["Full spectrum", "IR760"],
        suptitle="Comparison sample images",
        block=block
    )
    comparisonArray = [
        [(utils.testimage(xsize=100, ysize=100, sat=sat), "saturation %.1f"%sat) for sat in [0., 0.3  , 0.4]],
        [(utils.testimage(xsize=150, ysize=100, sat=sat), "saturation %.1f"%sat) for sat in [0.5, 0.75, 1. ]],
    ]
    process.show(comparisonArray, block=block)
    process.show(comparisonArray, compare=False, block=block, suptitle="no comparisons")

    comparisonArrayNoTitle = [[im[0] for im in imx] for imx in comparisonArray]
    process.show(comparisonArrayNoTitle, compare=True, block=block, suptitle="color wheel samples NO TITLES")
    if not block and display:
        plt.show()


def test_show_compare_grid_image_class(block=False,  display=DISPLAY):
    """
    grid of images display using image class
    """
    process.show(
        [
            [process.Image(impth, name=os.path.basename(impth)[:12]) for impth in utils.imagepath(imgname=["*Full*", "*IR760*"])],
            [process.Image(impth, name="") for impth in utils.imagepath(imgname=["*Full*", "*IR760*"])][::-1],
        ],
        suptitle="Comparison using Image Class images",
        block=block
    )
    if not block and display:
        plt.show()


def test_applycm(block=False,  display=DISPLAY):
    """
    Application of a color matrix
    """
    img = utils.testimage(xsize=200, ysize=200, sat=0.7)
    imgWB = process.applycolormatrix(img, cm = [0.8, 1., 0.9])
    imgBrighter = process.applycolormatrix(img, cm = 1.5)
    imgDarker = process.applycolormatrix(img, cm = 0.5)
    permutRB = np.array([
        [0., 0., 1.],
        [0., 1., 0.],
        [1., 0., 0.],
    ])
    imgPermut = process.applycolormatrix(img, cm = permutRB)
    vibrant = np.array([
        [1., 0.2 , 0.2 ],
        [0. , 1. , 0.2 ],
        [0. , 0. , 1.  ],
    ])
    imgVibrant = process.applycolormatrix(img, cm = vibrant)
    process.show(
        [
            [(img, "Original"), (imgWB, "WB applied"), (imgBrighter, "brighter image")],
            [(imgPermut, "permutation R <-> B"), (imgVibrant, "more vibrant"), (imgDarker, "darker image")],
        ],
        block=block,
    )
    if not block and display:
        plt.show()


def test_imagepipe(display=DISPLAY):
    ipBasicPipe = imagepipe.ImagePipe(
        [utils.testimage(xsize=400, ysize=400),],
        winname="Basic single image processing",
        rescale=2.
    )
    if display:
        ipBasicPipe.gui()

    forcedparams = {
        "WB":[0.121569,0.219608],
        "GAMMA":[0.105882],
        "BRIGHTNESS":[-0.137255],
        "TRANSLATION":[-372.000000,-377.000000],
    }
    ipBasicPipe.set(**forcedparams)
    ipBasicPipe.save()



import copy
def test_signalplot():
    class Amplify(imagepipe.ProcessBlock):
        def apply(self, sig, ampli, **kwargs):
            out = copy.deepcopy(sig)
            out.y = sig.y*ampli
            return out


    class Addition(imagepipe.ProcessBlock):
        def apply(self, sig1, sig2, **kwargs):
            out = copy.deepcopy(sig1)
            out.y = sig1.y + sig2.y
            out.label = sig1.label + " + " +sig2.label
            out.color = "g.-"
            return out

    AMPLI = Amplify(
        "Amplification",
        vrange=[
            (0.5, 3., 1.),
        ],
        mode = [imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    )

    ADDI = Addition(
        "Addition", slidersName=[],
        inputs = [0,2], outputs = [0, ],
        mode = [imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    )


    x  = 2.*np.arange(100)/100.
    sigList = [
        imagepipe.Signal(x, x, "-b", "base signal"),
        imagepipe.Signal(x, np.sin(x), "-r", "sinus")
    ]
    ip = imagepipe.ImagePipe(
        sigList,
        sliders=[AMPLI, ADDI])
    ip.gui()

    ipBasicLinPipe = imagepipe.ImagePipe(
        [utils.testimage(xsize=400, ysize=400),],
        sliders=[imagepipe.GLIN, imagepipe.BRIGHTNESS, imagepipe.WB, imagepipe.GAMM],
        winname="Basic LINEAR DOMAIN single image processing",
        rescale=2.
    )
    ipBasicLinPipe.gui()