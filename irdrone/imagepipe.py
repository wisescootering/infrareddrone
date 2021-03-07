"""
Multi image processing pipe including tuning GUI
"""
import cv2
import numpy as np
import os.path as osp
import copy
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider #PYPLOT BACKEND

CONTROLWINDOW = "Press S to save / I to display tuning parameters / Q to quit"


class ProcessBlock:
    """
    Images are assumed RGB
    Image processing single block is defined by the `apply` function to process multiple images
    mode : [IMAGE in , IMAGE out] or [SIGNAL in, SIGNAL out ] etc...
    """
    IMAGE, SIGNAL = "image", "signal"
    def __init__(self, name, slidersName=None, vrange=(-1., 1.), inputs=[0, ], outputs=[0, ], mode=[IMAGE, IMAGE]):
        assert isinstance(vrange, tuple) or isinstance(vrange, list)
        self.name = name
        if slidersName is None: slidersName = [name, ]
        assert isinstance(slidersName, list)
        self.slidersName = slidersName
        # self.values = [0] * len(self.slidersName)
        self.defaultvalue = []
        self.vrange = []
        if isinstance(vrange, tuple):
            if len(slidersName)==1:vrange=[vrange,]
            else: vrange=[vrange,]*len(slidersName) #REPLICATE
        for vr in vrange:
            if len(vr) == 2:
                self.vrange.append(vr)
                self.defaultvalue.append(0.)
            elif len(vr) == 3:
                self.vrange.append(vr[0:2])
                self.defaultvalue.append(vr[2])


        self.values = copy.deepcopy(self.defaultvalue)
        self.inputs = inputs
        self.outputs = outputs
        self.mode = mode

    def __repr__(self):
        descr = "%s\n" % self.name
        if not (self.inputs == [0, ] and self.outputs == [0, ]):
            descr += "(" + (",".join(["%d" % it for it in self.inputs])) + ")"
            descr += "->" + "(" + ",".join(["%d" % it for it in self.outputs]) + ")\n"
        for idx, sname in enumerate(self.slidersName):
            descr += "\t%s=%.3f" % (sname, self.values[idx])
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



class Signal:
    def __init__(self, x, y, color=None, label=None, xlim=None, ylim=None, xlabel=None, ylabel=None):
        self.x = x
        self.y = y
        if self.x is None and self.y is not None:
            self.x = np.arange(len(y))
        if color is None: color = ""
        self.color = color
        # if label is None: label =""
        self.label  = label
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.xlim   = xlim
        self.ylim   = ylim
    def concat(self, siglist):
        self.x = [sig.x for sig in siglist]
        self.y = [sig.y for sig in siglist]
        self.color = [sig.color for sig in siglist]
        self.label = [sig.label for sig in siglist]
    def append(self, newsig):
        if self.xlim is not None and newsig.xlim is not None:
            self.xlim[0] = min(self.xlim[0], newsig.xlim[0])
            self.xlim[1] = max(self.xlim[1], newsig.xlim[1])
        if self.ylim is not None and newsig.ylim is not None:
            self.ylim[0] = min(self.ylim[0], newsig.ylim[0])
            self.ylim[1] = max(self.ylim[1], newsig.ylim[1])
        self.x = self.x+ newsig.x
        self.y = self.y+ newsig.y
        self.color = self.color+ newsig.color
        self.label = self.label + newsig.label
    def prepend(self, newsig):
        if self.xlim is not None and newsig.xlim is not None:
            self.xlim[0] = min(self.xlim[0], newsig.xlim[0])
            self.xlim[1] = max(self.xlim[1], newsig.xlim[1])
        if self.ylim is not None and newsig.ylim is not None:
            self.ylim[0] = min(self.ylim[0], newsig.ylim[0])
            self.ylim[1] = max(self.ylim[1], newsig.ylim[1])
        self.x = newsig.x + self.x
        self.y = newsig.y + self.y
        self.color = newsig.color + self.color
        self.label = newsig.label + self.label


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
        im[:,:,2] *= 1.+coeffblue
        im[:,:,0] *= 1.+coeffred
        return im


class BnW(ProcessBlock):
    def apply(self, im, **kwargs):
        avg =  1./3.*(1.*im[:,:,0]+1.*im[:,:,1]+1.*im[:,:,2])
        for i in range(im.shape[-1]):
            im[:,:,i] = avg
        return im


class AWB(ProcessBlock):
    def apply(self, im, **kwargs):
        avg = np.average(im, axis=(0,1))
        im[:,:,0] *= (avg[1]/avg[0])
        im[:,:,2] *= (avg[1]/avg[2])
        return im



class Equalizer(ProcessBlock):
    def apply(self, im, **kwargs):
        im = np.clip(im, 0., 255.)
        mi, ma = np.min(im), np.max(im)
        # print(mi, ma)
        im = 255.*(im - mi)/ (ma-mi)
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


class ColorMix(ProcessBlock):
    def apply(self, im, coeffblue, coeffgreen, coeffred, **kwargs):
        im[:,:,0] *= coeffred
        im[:,:,1] *= coeffgreen
        im[:,:,2] *= coeffblue
        return im


BRIGHTNESS = Brightness("BRIGHTNESS")
WB = Wb("WB", slidersName=["WB blue", "WB red"],  vrange=(-1.,3., 0.))
TRANSLATION = Translation("TRANSLATION", slidersName=["TX", "TY"], vrange=(-500,500))
ALPHA = Blend("ALPHA", inputs=[0,2], vrange=(0.,1., 1.))
ADD = Add("ADD", inputs=[0,2], vrange=(-1., 1., 0.))
GAMMA = Gamma("GAMMA", vrange=(-0.2, 0.2, 0.))
GLIN = GammaFixed("GINV", slidersName=[]); GLIN.setGamma(1./2.2)
GAMM = GammaFixed("GAMM", slidersName=[]); GAMM.setGamma(2.2)
EQ   = Equalizer("EQUALIZER", slidersName=[])


class ImagePipe:
    """
    Pipe various ProcessBlock to perform basic multiple image processing
    2 backends: openCV and matplotlib pyplot
    Matplolib backend by default has nice tuning slider values
    It is possible to use the ImagePipe in a headless mode to process images without GUI ... use the save method.
    """
    def __init__(self, imlist, rescale=None, sliders=[ProcessBlock("identity", slidersName=[])], winname=CONTROLWINDOW, backendcv=False, floatpipe=True, **params):
        """
        :param imlist: list of RGB (not cv2 fashioned) arrays
        """
        self.backendcv = backendcv
        self.winname = winname
        self.imlist = imlist
        self.sliders = sliders
        self.signalOut = False

        if self.sliders[-1].mode[1] == ProcessBlock.SIGNAL:
            self.signalOut = True
        self.signalIn = False
        if self.sliders[-1].mode[0] == ProcessBlock.SIGNAL:
            self.signalIn = True
        if not self.signalIn:
            if rescale is None: rescale = 720. / (1. * imlist[0].shape[0])
            self.imglistThumbs = list(map(lambda x: cv2.resize(x, (0, 0), fx=rescale, fy=rescale), self.imlist))
        else:
            self.imglistThumbs = self.imlist
        self.geometricscale = rescale
        self.set(**params)
        self.floatpipe=floatpipe
        self.slidersplot = None
        self.floatColorBar()

    def floatColorBar(self, colorBar ='gray',minColorBar=0, maxColorBar=1):
        self.colorBar = colorBar
        self.minColorBar = minColorBar
        self.maxColorBar = maxColorBar

    def engine(self, imglst, geometricscale=None):
        if not self.signalIn and self.floatpipe: result = [1. * imglst[0]] + list(map(lambda x: x.astype(np.float), imglst))
        else: result = [imglst[0]] + imglst
        for prc in self.sliders:
            out = prc.apply(*[result[idi] for idi in prc.inputs] + prc.values, geometricscale=geometricscale)
            if isinstance(out, list):
                for i, ido in enumerate(prc.outputs):
                    result[ido] = out[i]
            else:  # Simpler manner of defining a process function (do not return a list)
                for _i, ido in enumerate(prc.outputs):
                    result[ido] = out
        if not self.signalOut:
            if self.backendcv:
                return cv2.cvtColor(np.clip(result[0], 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR) if self.floatpipe \
                    else cv2.cvtColor(result[0], cv2.COLOR_RGB2BGR)
            else:
                return np.clip(result[0], 0, 255).astype(np.uint8) if self.floatpipe else result[0]
        else:
            return result[0]

    def save(self, name=None):
        """
        Save full resolution image
        """
        print("saving full resolution image...")
        result_full = self.getbuffer()
        if name is not None:
            if len(result_full.shape)<3:
                plt.imsave(name, result_full, vmin=self.minColorBar, vmax=self.maxColorBar, cmap=self.colorBar)
            else:
                try:
                    cv2.imwrite(name, result_full if self.backendcv else cv2.cvtColor(result_full, cv2.COLOR_RGB2BGR))
                except:
                    plt.imsave(name, result_full, vmin=self.minColorBar, vmax=self.maxColorBar, cmap=self.colorBar)
        else:
            idx = 1
            while (idx < 100):
                out_jpg = "_saved_image_%04d.jpg" % idx
                if not osp.isfile(out_jpg):
                    cv2.imwrite(out_jpg, result_full if self.backendcv else cv2.cvtColor(result_full, cv2.COLOR_RGB2BGR))
                    print("saved image %s" % out_jpg)
                    break
                else:
                    idx += 1

    def getbuffer(self):
        """
        Useful for standalone python acess without gui or disk write
        """
        return self.engine(self.imlist, geometricscale=None)

    def resetsliders(self, sliderslength=100., forcereset=False, addslider=True):
        """
        Create sliders at their initial values
        """
        def nothing(x):
            pass

        u = 0
        if addslider:
            self.axes, self.slidersplot = [], []
        for pa in self.sliders:
            for idx, paName in enumerate(pa.slidersName):
                if forcereset:
                    dfval = pa.defaultvalue[idx]
                else:
                    dfval = pa.values[idx]
                if addslider:
                    if self.backendcv:
                        defaultval = int((dfval - pa.vrange[idx][0]) / (pa.vrange[idx][1] - pa.vrange[idx][0]) * sliderslength)
                        cv2.createTrackbar(paName, self.winname, defaultval, int(sliderslength), nothing)
                    else:
                        defaultval = dfval
                        axcolor = 'lightgoldenrodyellow'
                        self.axes.append(plt.axes([0.25, 0.1+u*0.04, 0.65, 0.03], facecolor=axcolor))
                        self.slidersplot.append(
                            Slider(
                                self.axes[u], paName.replace(" ", "_"),
                                pa.vrange[idx][0],
                                pa.vrange[idx][1],
                                valinit=defaultval,
                                valstep=( pa.vrange[idx][1]-pa.vrange[idx][0])/100.)
                        )
                        u += 1
                else:
                    if self.slidersplot is not None:
                        self.slidersplot[u].reset()
                        u += 1



    def set(self, **params):
        """
        Force parameters (Hint: Use I key to print the current values of tuning sliders)
        :param params:
        :return:
        """
        for pa in self.sliders:
            if pa.name in params.keys():
                pa.values = params[pa.name]
            else:
                for idx, paName in enumerate(pa.slidersName):
                    pa.values[idx] = pa.defaultvalue[idx]

    def update(self, val):
        u = 0
        for pa in self.sliders:
            for idx, paName in enumerate(pa.slidersName):
                pa.values[idx] =self.slidersplot[u].val
                u+=1
        result = self.engine(self.imglistThumbs, geometricscale=self.geometricscale)
        if self.signalOut:
            if result is not None:  # result can be None in case you only want to plot input signals
                if isinstance(result.y, list):
                    linidx = 0
                    for idx in range(len(result.y)):
                        self.sigplot[idx].set_xdata(result.x[idx])
                        self.sigplot[idx].set_ydata(result.y[idx])
                        if result.label[idx] is not None:
                            self.legend.get_texts()[linidx].set_text(result.label[idx])
                            linidx+=1
                else:
                    self.sigplot.set_xdata(result.x)
                    self.sigplot.set_ydata(result.y)
                    if result.label is not None:
                        self.legend.get_texts()[0].set_text(result.label)
        else:
            self.implot.set_data(result)

    def press(self, event):
        if event.key == 'r':
            self.resetsliders(forcereset=True, addslider=False)
        elif event.key == 's' or event.key == 'w':
            self.save()
        elif event.key == 'i':
            print(self.__repr__())


    def gui(self, sliderslength=100.,):
        """
        Create a cv2 or pyplot GUI
        to interactively visualize the imagePipe when changing tuning sliders for each processBlock
        """
        if self.backendcv:
            cv2.namedWindow(self.winname)
        else:
            self.fig, ax = plt.subplots()
            plt.gcf().canvas.set_window_title(self.winname)
            totalSliders = int(np.array([len(pa.slidersName) for pa in self.sliders]).sum())
            # RESIZE ONLY TO ADD SLIDERS IF NECESSARY : USEFUL FOR INPUT PLOTS WITHOUT INTERACTIVE SLIDERS
            if totalSliders > 0: plt.subplots_adjust(left=0. if not self.signalOut else 0.1, bottom=0.4)
            self.resetsliders(addslider=False)
            result = self.engine(self.imglistThumbs, geometricscale=self.geometricscale)
            if self.signalIn:
                for sig in self.imlist:
                    if sig is not None:
                        ax.plot(sig.x, sig.y, sig.color, label=sig.label)
                        if sig.xlabel is not None: plt.xlabel(sig.xlabel)
                        if sig.ylabel is not None: plt.ylabel(sig.ylabel)
                        if sig.xlim is not None: plt.xlim(sig.xlim)
                        if sig.ylim is not None: plt.ylim(sig.ylim)
            if self.signalOut:
                self.sigplot = []
                if result is not None:
                    if isinstance(result.y, list):
                        for idx in range(len(result.y)):
                            splt, = ax.plot(
                                result.x[idx], result.y[idx],
                                result.color[idx], label=result.label[idx]
                            )
                            self.sigplot.append(splt)
                    else:
                        self.sigplot,  = ax.plot(result.x, result.y, result.color, label=result.label)

            if self.signalIn or self.signalOut:
                plt.grid(True)
                self.legend = plt.legend()
                if result is not None:
                    if result.xlabel is not None: plt.xlabel(result.xlabel)
                    if result.ylabel is not None: plt.ylabel(result.ylabel)
                    if result.xlim   is not None: plt.xlim(result.xlim)
                    if result.ylim   is not None: plt.ylim(result.ylim)
            else:
                plt.axis("off")
                if len(result.shape)<3:
                    self.implot = ax.imshow(result, cmap= self.colorBar , vmin=self.minColorBar,vmax=self.maxColorBar)
                    plt.colorbar(self.implot, ax=ax)
                else:
                    self.implot = ax.imshow(result)
                ax.margins(x=0)
        self.resetsliders(addslider=True, forcereset=False)


        if self.backendcv:
            while True:
                for idx, pa in enumerate(self.sliders):
                    for idy, paName in enumerate(pa.slidersName):
                        normedvalue = cv2.getTrackbarPos(paName, self.winname) / sliderslength
                        self.sliders[idx].values[idy] = normedvalue * (pa.vrange[idy][1] - pa.vrange[idy][0]) + pa.vrange[idy][0]
                result = self.engine(self.imglistThumbs, geometricscale=self.geometricscale)
                cv2.imshow(self.winname, result)
                k = cv2.waitKey(1) & 0xFF
                if k == ord('s'):
                    self.save()
                elif k == ord('i'):
                    print(self.__repr__())
                elif k == ord("q"):
                    break
                elif k == ord("r"):
                    self.resetsliders(forcereset=True)
            cv2.destroyAllWindows()
        else:
            for slid in self.slidersplot:
                slid.on_changed(self.update)
            self.fig.canvas.mpl_connect('key_press_event', self.press)

            plt.show()

    def __repr__(self):
        ret = "\n{\n"
        for sl in self.sliders:
            ret += "\"%s\"" % sl.name + ":[" + ",".join(map(lambda x: "%f" % x, sl.values)) + "],\n"
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
            process.loadimage(utils.imagepath(imgname="*Full*"))[0],
            process.loadimage(utils.imagepath(imgname="*IR760*"))[0],
        ],
        sliders=[GLIN, BRIGHTNESS, WB, GLIN2, TRANSLATION2, ADD, GAMM, GAMMA]
    )
    ip.gui()