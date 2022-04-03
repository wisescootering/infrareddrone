import sys
import os.path as osp
sys.path.append(osp.join(osp.dirname(__file__), ".."))
import irdrone.utils as ut
from automatic_registration import process_raw_pairs
import os.path as osp
import os
osp = os.path

DJI_SJCAM_CAL = dict(
    refcalib=ut.cameracalibration(camera="DJI_RAW"),
    movingcalib=ut.cameracalibration(camera="M20_RAW")
)


def demo_raw_real_application(folder_database=osp.join(osp.dirname(__file__), "..", "FlightDatabase"), manual=False, debug=False):
    data_link = "https://drive.google.com/drive/folders/1UJGvq8gWpkkgtAd6cRbNiQIRyabcjPIf?usp=sharing"
    assert osp.isdir(folder_database), "please download {} and put all images in {}".format(data_link, folder_database)
    # -------------------------------------------------------------------------------------------------------- Visargent

    img_pairs = [
        ["DJI_0612.DNG", "2021_0505_083056_111.RAW"],
        ["DJI_0613.DNG", "2021_0505_083132_135.RAW"],
        ["DJI_0615.DNG", "2021_0505_083217_165.RAW"]
    ]
    folder = osp.join(folder_database, "FLY-20210505_Visargent", "AerialPhotography")
    # @TODO: FIX WHEN DJI GEOMETRIC CALIBRATION IS FIXED
    pairs_paths = [[osp.join(folder, vis.replace(".RAW", "_PL4_DIST.tif")), osp.join(folder, nir)]
                   for vis, nir in img_pairs]
    process_raw_pairs(pairs_paths, cals=DJI_SJCAM_CAL, manual=manual, debug=debug, debug_folder=folder_database)
    # ----------------------------------------------------------------------------------------------------------- Vivans
    img_pairs = [
        ["DJI_0618.DNG", "2021_0505_130901_067.RAW"],  # NOT WORKING IN AUTO! -> NEEDS MANUAL
        # ["DJI_0623.DNG", "2021_0505_131131_167.RAW"],
        # ["DJI_0624.DNG", "2021_0505_131155_183.RAW"]
        # ["DJI_0624.DNG", "2021_0505_131131_167.RAW"]
    ]
    folder = osp.join(folder_database, "FLY-20210505_Vivans", "AerialPhotography")
    # @TODO: FIX WHEN DJI GEOMETRIC CALIBRATION IS FIXED
    pairs_paths = [[osp.join(folder, vis.replace(".RAW", "_PL4_DIST.tif")), osp.join(folder, nir)]
                   for vis, nir in img_pairs]
    process_raw_pairs(pairs_paths, cals=DJI_SJCAM_CAL, manual=manual, debug=debug, debug_folder=folder_database)


def demo_raw(folder=osp.join(osp.dirname(__file__), r"Hyperlapse 06_09_2021_sync"), manual=False):
    """
    Scan the folder for pairs of raw with the same name.
    Assume that RAW from SJCAM M20 and DNG from DJI have the same file name
    """
    data_link = "https://drive.google.com/drive/folders/1IrF55tDYV6YwHm0gUTRc7T3WTnbwbPxk?usp=sharing"
    assert osp.isdir(folder), "please download {} and put all images in {}".format(data_link, folder)
    out_dir = osp.join(folder, "debug")
    if not osp.isdir(out_dir):
        import os
        os.mkdir(out_dir)
    import glob
    # img_pairs = [(vis_pth, vis_pth.replace("DNG", "RAW")) for vis_pth in sorted(glob.glob(osp.join(folder, "*DNG")))]
    # @TODO: FIX WHEN DJI GEOMETRIC CALIBRATION IS FIXED
    img_pairs = [(vis_pth.replace(".DNG", "_PL4_DIST.tif"), vis_pth.replace(".DNG", ".RAW")) for vis_pth in sorted(
        glob.glob(osp.join(folder, "*DNG")))]
    process_raw_pairs(img_pairs, cals=DJI_SJCAM_CAL, manual=manual)


if __name__ == '__main__':
    demo_raw_real_application()