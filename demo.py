import irdrone.process as pr
import irdrone.utils as ut
import irdrone.imagepipe as ipipe


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
    imgl = [ut.testimage(xsize=720, ysize=720, sat=sat) for sat in [1., 0.]]
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
            pr.loadimage(ut.imagepath(imgname="*Full*") , numpyMode=False)[0],
            pr.loadimage(ut.imagepath(imgname="*IR760*"), numpyMode=False)[0],
        ],
        sliders=[ipipe.GLIN, ipipe.BRIGHTNESS, ipipe.WB, GLIN2, TRANSLATION2, ipipe.ADD, ipipe.GAMM, ipipe.GAMMA]
    )
    ip.gui()

if __name__ == "__main__":
    imagecompdemo()
    blendingdemo()
    spectrumfusiondemo()

