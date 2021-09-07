# coding: utf-8
import irdrone.process as pr
import irdrone.utils as ut
import irdrone.imagepipe as ipipe
import numpy as np
import cv2
import  matplotlib.pyplot as plt

# class WarpAffine(ipipe.ProcessBlock):
#     def apply(self, im, tx, ty, geometricscale=None, **kwargs):
#         if tx== 0 and ty==0:
#             return im
#         if geometricscale is None: geometricscale = 1.
#         _tx = geometricscale*tx
#         _ty = geometricscale*ty
#         #geometricscale is used for thumbnails smaller size preview. when processing at full scale, use None or 1.
#         trans = np.array([
#             [1., 0., _tx],
#             [0., 1., _ty],
#         ])
#         im = cv2.warpAffine(im, trans, (im.shape[1], im.shape[0]))
#         return im


def get_intrinsic_matrix(shape, focal_length=100,):
    K = focal_length*np.eye(3)
    K[:-1, -1] = np.array([shape[1]/2.,shape[0]/2.])
    K[-1,-1] = 1.
    return K


def dji_focal_length():
    diag_35mm_film = np.sqrt(24.**2+36.**2)
    equivalent_focal = 24.
    diag_fov = np.rad2deg(2.*np.arctan(diag_35mm_film/2./equivalent_focal))
    print("Equivalent 35mm focal %dmm FOV %.1f°"%(equivalent_focal, diag_fov))
    # inch_to_mm = 2.54*10
    # sensor_diag_announced = 1./2.3 * inch_to_mm
    sensor_size_mm = np.array([6.16, 4.62]) #6.17 mm x 3.47 mm
    sensor_resolution = np.array([4000.,3000.]) # 12 Mpix
    diag_sensor = np.sqrt(sensor_size_mm[0]**2+sensor_size_mm[1]**2)
    print("sensor diagonal %.1fmm"%(diag_sensor))
    pixel_pitch = sensor_size_mm[0]/sensor_resolution[0] #1.54 micron
    print("Pixel pitch %.2f1µm"%(pixel_pitch*1E3))
    true_focal_length = equivalent_focal/36*sensor_size_mm[0]
    print("Real focal length %f mm"%true_focal_length)  # 4.27046 mm https://forum.dji.com/thread-150164-1-1.html
    focal_length_pixels = true_focal_length/pixel_pitch
    print("Focal in pixels %.2f"%(focal_length_pixels))
    return focal_length_pixels


class WarpRotateTranslate(ipipe.ProcessBlock):
    def apply(self, im, yaw, pitch, roll, extra_roll, zoom, focal_length, tx, ty, geometricscale=None, focal_length_camera=dji_focal_length(), **kwargs):
        # @TODO: CRITICAL SAVING TO FULL RESOLUTION IMAGE DOES NOT PROVIDE THE SAME RESULTS AS THUMBNAIL
        if geometricscale is None: geometricscale = 1.
        # PIXELS ARE 4x bigger on the preview -> geometricscale=0.24 , fpix = f / pixel pitch -> bigger pixels, smaller fpix
        K = get_intrinsic_matrix(im.shape, focal_length=focal_length_camera*geometricscale*focal_length)
        K_inv = np.linalg.inv(K)
        K_virtual = get_intrinsic_matrix(im.shape, focal_length=focal_length_camera*geometricscale*focal_length*(zoom/100.))
        rvec = np.deg2rad(np.array([pitch, yaw, roll+extra_roll]))
        R = cv2.Rodrigues(rvec)[0]
        H = np.dot(np.dot(K_virtual, R), K_inv)
        middle =  np.array([[im.shape[1]/2.,im.shape[0]/2., 1.]]).T
        center_proj = np.dot(H, middle)
        center_proj = center_proj[:2,0]/center_proj[-1, 0]
        freeze_center = np.eye(3)
        freeze_center[:-1, -1] = -center_proj + np.array([im.shape[1]/2.,im.shape[0]/2.])
        freeze_center[0, -1] += tx*im.shape[1] # perceived
        freeze_center[1, -1] += ty*im.shape[0] # perceived
        H = np.dot(freeze_center, H)
        out = cv2.warpPerspective(im, H, (im.shape[1], im.shape[0]))
        return out


class Transparency(ipipe.ProcessBlock):
    def apply(self, im1, im2, alpha, **kwargs):
        if alpha<=0:
            return (1-np.abs(alpha))*im1 + np.abs(alpha) * 2.*np.abs(im1-im2)*(im1>0) + (im1==0)*im2
        else:
            return (alpha * im1) + (im1==0)*im2 + (1-alpha)*(im1>0)*im2


def manual_registration(imgl, params=None):
    """
    Register 2 images manually
    Warning: images need to have same size
    """
    alpha = Transparency("Alpha", inputs=[0,2], vrange=(-1., 1., 1.))
    angles_amplitude = (-20.,20, 0.)
    rotate3d = WarpRotateTranslate(
        "Rotate",
        slidersName=["YAW", "PITCH", "ROLL", "BIG_ROLL", "ZOOM", "FOCAL", "TX", "TY"],
        inputs=[0,],
        outputs=[0,],
        vrange=[
            angles_amplitude, angles_amplitude,angles_amplitude,
            (-180., 180, 0.),
            (20, 100., 100.),
            (0., 20., 1.),
            (-1., 1.),
            (-1., 1.)]
    )
    imgl[1] = ut.match_histograms(imgl[1], imgl[0])
    ipi = ipipe.ImagePipe(imgl, sliders=[rotate3d, alpha])
    if params is not None:
        ipi.set(**params)
    ipi.gui()


def google_maps_example():
    """Register drone image with google map screenshot
    Example with a coarse solution
    """
    imglist = [
        pr.loadimage(ut.imagepath(imgname="DJI_0623_Distorsion.jpg", dirname="samples"))[0],
        pr.loadimage(ut.imagepath(imgname="Google_Maps.jpg", dirname="samples"))[0],
    ]
    params = {
        "Rotate":[-0.080000,5.240000,-13.200000,93.600000,63.360000,0.998000,-0.052000,-0.080000],
        "Alpha":[1.000000],
    }
    # params = None
    manual_registration(imglist, params=params)


if __name__ == "__main__":
    google_maps_example()
