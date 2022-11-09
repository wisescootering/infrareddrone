import sys
import os.path as osp
sys.path.append(osp.join(osp.dirname(__file__), ".."))
import irdrone.process as pr
import irdrone.utils as ut
import interactive.imagepipe as ipipe
import numpy as np


def imagecompdemo():
    pr.show(
        [
            [(ut.testimage(xsize=200, ysize=300, sat=sat ), "color rectangle %.1f"%sat) for sat in [0.1, 0.5]],
            [(ut.testimage(xsize=300, ysize=200, sat=sat) , "wide %.1f"%sat) for sat in [0.3, 0.5, 1.]]
        ],
        suptitle="Comparison grid"
    )


def blendingdemo():
    '''
    DEMO OF A BLENDING BETWEEN 2 IMAGES
    '''
    imgl = [ut.testimage(xsize=720, ysize=720, sat=sat).astype(np.float64) for sat in [1., 0.]]
    TRANSLATION2 = ipipe.Translation("T2", slidersName=["TX 2", "TY 2"], inputs=[2,], outputs=[2,], vrange=(-50.,50.))
    ipipe.ImagePipe(imgl, sliders=[ipipe.WB, TRANSLATION2, ipipe.ALPHA, ipipe.GAMMA]).gui()


def spectrumfusiondemo():
    '''
    FUSION OF 2 DIFFERENT SPRECTRUMS IMAGES
    '''
    TRANSLATION2 = ipipe.Translation("T2", slidersName=["TX 2", "TY 2"], inputs=[2,], outputs=[2,], vrange=(-50.,50.))
    GLIN2 = ipipe.GammaFixed("LINEARIZATION_IMG2", slidersName=[], inputs=[2,], outputs=[2,]);GLIN2.setGamma(1./2.2)
    ip = ipipe.ImagePipe(
        [
            pr.loadimage(ut.imagepath(imgname="*Full*"))[0],
            pr.loadimage(ut.imagepath(imgname="*IR760*"))[0],
        ],
        sliders=[ipipe.GLIN, ipipe.BRIGHTNESS, ipipe.WB, GLIN2, TRANSLATION2, ipipe.ADD, ipipe.GAMM, ipipe.GAMMA]
    )
    ip.gui()


def fuseIRandFullSpectrum():
    """
    Example of IR and Full spectrum fusion to try to reconstruct visible image
    Show an example of forced parameters:
    - You can play with the tuning sliders, press I to show the dictionary in the terminal
    - Then force this parameters at the initialization of the ImagePipe (**forcedParams)
    This allows to save your tuning ... usefull for GUI-less processing
    :return:
    """
    AWB = ipipe.AWB("Auto white balance", slidersName=[])
    ADD = ipipe.Add("ADD", inputs=[0,2], vrange=(-2., 0., 0.))
    CM2 = ipipe.ColorMix("ColorMix", inputs=[2,], outputs=[2,], slidersName=["Bleu", "Vert", "Rouge"], vrange=(0.,1.,1.))

    forcedParams = {
        "ColorMix":[0.34,0.25,0.5],
        "ADD":[-1.0],
        # "GAMMA":[-0.020000],
        "BRIGHTNESS":[0.620000],
    }
    ip = ipipe.ImagePipe(
        [
            pr.loadimage(ut.imagepath(imgname="*Full*",  dirname="samples2"))[0].astype(np.float64),
            pr.loadimage(ut.imagepath(imgname="*IR760*", dirname="samples2"))[0].astype(np.float64),
        ],
        sliders=[CM2, ADD, AWB, ipipe.WB, ipipe.GAMMA, ipipe.BRIGHTNESS],
        floatpipe=False,
        **forcedParams
    )
    ip.gui()

if __name__ == "__main__":
    fuseIRandFullSpectrum()
    imagecompdemo()
    blendingdemo()
    spectrumfusiondemo()

