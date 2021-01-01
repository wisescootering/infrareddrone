"""
Multi image processing pipe including tuning GUI
"""
import cv2
import numpy as np
import os

CONTROLWINDOW = "Press S to save / I to display tuning parameters / Q to quit"


class ProcessBlock():
    """
    Image processing single block is defined by the `apply` function to process multiple images
    """
    def __init__(self, name, slidersName=None, vrange=(-1.,1.), inputs=[0,], outputs = [0,]):
        assert isinstance(vrange, tuple) or  isinstance(vrange, list)
        self.name = name
        if slidersName is None: slidersName = [name,]
        assert isinstance(slidersName, list)
        self.slidersName = slidersName
        self.values = [0]*len(self.slidersName)
        self.defaultvalue=0.
        if len(vrange)==2: self.vrange = vrange
        elif len(vrange)==3: self.vrange = vrange[0:2]; self.defaultvalue=vrange[2]
        self.inputs  = inputs
        self.outputs = outputs

    def __repr__(self):
        descr  = "%s\n"%self.name
        if not (self.inputs==[0,] and self.outputs==[0,]):
            descr+= "(" + (",".join(["%d"%it for it in self.inputs]))+ ")"
            descr+= "->" + "(" +",".join(["%d"%it for it in self.outputs]) + ")\n"
        for idx, sname in enumerate(self.slidersName):
            descr+= "\t%s=%.3f"%(sname,self.values[idx])
        descr += "\n"
        return descr

    def apply(self, *imgs, **kwargs):
        """
        :param imgs: img0, img1, img2, value1 , value2 , value3 ....
            - (img0 is the result from the previous step)
            - indexes of images processed is defined by `self.inputs`
            - indexes of output images to be overwritten processed are defined by `self.outputs`
            - Use self.inputs = [0,] , self.outputs = [0,] to apply a simple sequential procesing
            - Use self.inputs = [1,2] , self.outputs = [0,] to apply a blending processing between image  1 & 2
            - then follow the parameters to be applied  `self.values` depicted by `self.slidersName`
        :param kwargs: geometricscale=None
        :return: output1, output2 ...
        """
        return imgs[0]


class Brightness(ProcessBlock):
    def apply(self, im, coeff, **kwargs):
        im*=1.+coeff
        return im


class Gamma(ProcessBlock):
    def apply(self, im, coeff, **kwargs):
        im = im**(1.+coeff)
        return im


class GammaFixed(ProcessBlock):
    gamma = 2.2
    
    def setGamma(self, gamma):
        self.gamma = gamma

    def apply(self, im, **kwargs):
        im = im**(self.gamma)
        return im


class Wb(ProcessBlock):
    def apply(self, im, coeffblue, coeffred, **kwargs):
        im[:,:,0] *= 1.+coeffblue
        im[:,:,2] *= 1.+coeffred
        return im


class Translation(ProcessBlock):
    def apply(self, im, tx, ty, geometricscale=None, **kwargs):
        if tx== 0 and ty==0:
            return im
        if geometricscale is None: geometricscale = 1.
        #geometricscale is used for thumbnails smaller size preview. when processing at full scale, use None or 1.
        trans = np.array([
            [1., 0., geometricscale*tx],
            [0., 1., geometricscale*ty],
        ])
        im = cv2.warpAffine(im, trans, (im.shape[1], im.shape[0]))
        return im


class Blend(ProcessBlock):
    def apply(self, im1, im2, alpha, **kwargs):
        return alpha * im1 + (1. - alpha) * im2


class Add(ProcessBlock):
    def apply(self, im1, im2, alpha, **kwargs):
        return im1 + alpha*im2


BRIGHTNESS = Brightness("BRIGHTNESS")
WB = Wb("WB", slidersName=["WB blue", "WB red"],  vrange=(-1.,3., 0.))
TRANSLATION = Translation("TRANSLATION", slidersName=["TX", "TY"], vrange=(-500,500))
ALPHA = Blend("ALPHA", inputs=[0,2], vrange=(0.,1., 1.))
ADD = Add("ADD", inputs=[0,2], vrange=(-1., 1., 0.))
GAMMA = Gamma("GAMMA", vrange=(-0.2, 0.2, 0.))
GLIN = GammaFixed("GINV", slidersName=[]); GLIN.setGamma(1./2.2)
GAMM = GammaFixed("GAMM", slidersName=[]); GAMM.setGamma(2.2)


class ImagePipe():
    """
    Pipe various ProcessBlock to perform basic multiple image processing
    """

    def __init__(self, imlist, rescale=None, sliders = [WB, GAMMA, BRIGHTNESS, TRANSLATION], winname=CONTROLWINDOW):
        """


        :param imlist: list of BGR (cv2 fashioned) arrays
        """
        self.winname = winname
        self.imlist  = imlist
        self.sliders = sliders
        if rescale is None: rescale = 720./(1.*imlist[0].shape[0])
        self.imglistThumbs = list(map(lambda x:cv2.resize(x, (0, 0), fx=rescale, fy=rescale), imlist))
        self.geometricscale = rescale

    def engine(self, imglst, geometricscale=None):
        result = [1.*imglst[0]]+imglst
        for prc in self.sliders:
            out = prc.apply(*[result[idi] for idi in prc.inputs]+prc.values, geometricscale=geometricscale)
            if isinstance(out, list):
                for i, ido in enumerate(prc.outputs):
                    result[ido] = out[i]
            else: #Simpler manner of defining a process fuction (do not return a list)
                for _i, ido in enumerate(prc.outputs):
                    result[ido] = out
        return result[0].clip(0,255).astype(np.uint8)

    def save(self):
        """
        Save full resolution image
        """
        print("saving full resolution image...")
        result_full = self.engine(self.imlist, geometricscale=None)
        idx = 1
        while (idx < 100):
            out_jpg = "_saved_image_%04d.jpg"%idx
            if not os.path.isfile(out_jpg):
                cv2.imwrite(out_jpg, result_full)
                print("saved image %s" % out_jpg)
                break
            else:
                idx+=1

    def resetsliders(self, sliderslength=100.):
        """
        Creat sliders at their initial values
        """
        def nothing(x):
            pass
        for pa in self.sliders:
            for paName in pa.slidersName:
                defaultval =int( (pa.defaultvalue - pa.vrange[0])/(pa.vrange[1]-pa.vrange[0])  * sliderslength)
                cv2.createTrackbar(paName, self.winname, defaultval, int(sliderslength),nothing)

    def gui(self, sliderslength=100.):
        """
        Create a cv2 GUI to interactively visualize the imagePipe when changing tuning sliders for each processBlock
        """

        cv2.namedWindow(self.winname)
        self.resetsliders()
        while True:
            for idx, pa in enumerate(self.sliders):
                for idy, paName in enumerate(pa.slidersName):
                    normedvalue = cv2.getTrackbarPos(paName, self.winname)/sliderslength
                    self.sliders[idx].values[idy] = normedvalue*(pa.vrange[1] - pa.vrange[0]) + pa.vrange[0]
            result = self.engine(self.imglistThumbs, geometricscale=self.geometricscale)
            cv2.imshow(self.winname, result)
            k = cv2.waitKey(1) & 0xFF
            if k == ord('s'): self.save()
            elif k == ord('i'): print(self.__repr__())
            elif k == ord("q"): break
            elif k == ord("r"): self.resetsliders()
        cv2.destroyAllWindows()

    def set(self, **params):
        """
        Force parameters (Hint: Use I key to print the current values of tuning sliders)
        :param params:
        :return:
        """
        for pa in self.sliders:
            if pa.name in params.keys():
                pa.values = params[pa.name]

    def __repr__(self):
        ret = "\n{\n"
        for sl in self.sliders:
            ret += "\"%s\""%sl.name + ":[" + ",".join(map(lambda x:"%f"%x , sl.values)) + "],\n"
        ret += "}"
        return ret


if __name__ == "__main__":
    import utils
    # DEMO OF A BLENDING BETWEEN 2 IMAGES
    imgl = [utils.testimage(xsize=720, ysize=720, sat=sat) for sat in [1., 0.]]
    TRANSLATION2 = Translation("TIMAGE2", slidersName=["TX 2", "TY 2"], inputs=[2,], outputs=[2,], vrange=(-50.,50.,0.))
    ip = ImagePipe(imgl, sliders=[WB, TRANSLATION2, ALPHA, GAMMA])
    ip.gui()

    # FUSION OF 2 DIFFERENT SPRECTRUMS
    import process
    GLIN2 = GammaFixed("LINEARIZATION_IMG2", slidersName=[], inputs=[2,], outputs=[2,]);GLIN2.setGamma(1./2.2)
    ip = ImagePipe(
        [
            process.loadimage(utils.imagepath(imgname="*Full*") , numpyMode=False)[0],
            process.loadimage(utils.imagepath(imgname="*IR760*"), numpyMode=False)[0],
        ],
        sliders=[GLIN, BRIGHTNESS, WB, GLIN2, TRANSLATION2, ADD, GAMM, GAMMA]
    )
    ip.gui()