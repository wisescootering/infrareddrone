import process
import utils
import os
import numpy as np
import matplotlib.pyplot as plt

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