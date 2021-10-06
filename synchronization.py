import irdrone.process as pr
import irdrone.utils as ut
import numpy as np
import os
osp = os.path
import platform
from datetime import datetime, timedelta


def synchronize_data(
        folder = r"D:\FLY-20210906-Blassac-05ms\AerialPhotography",
        delta=timedelta(seconds=171),
        replace_dji=(".DNG", "_PL4_DIST.tif"),
        debug=False,
    ):
    """Synchronize DNG and RAW files"""
    # @TODO: synchronize properly by fitting a linear model a.t +b for each sequence and using it to pick the best delta
    dates_pkl = osp.join(folder, "dates_dji")
    img_list_dji = ut.imagepath(imgname="*.DNG", dirname=folder)
    if osp.isfile(dates_pkl+".npy"):
        dates_dji = np.load(dates_pkl+".npy", allow_pickle=True)
    else:
        img_instances = [pr.Image(img) for img in img_list_dji]
        dates_dji = [im.date for im in img_instances]
        np.save(dates_pkl, dates_dji, allow_pickle=True)

    img_list_sjcam = ut.imagepath(imgname="*.RAW", dirname=folder)
    if platform.system() == 'Windows':
        dates_sjcam = [datetime.fromtimestamp(os.path.getmtime(img)) for img in img_list_sjcam]
    img_list_sjcam_sync = []
    sync_pairs = []
    for ind, dat_dji in enumerate(dates_dji):
        deltas = np.array([(dat_dji + delta - dat).total_seconds() for dat in dates_sjcam])
        best_match = np.argmin(np.fabs(deltas))
        if debug:
            date_matched = dates_sjcam[int(best_match)]
            print(img_list_sjcam[int(best_match)], img_list_dji[ind], date_matched)
            print(best_match, date_matched, dat_dji)
            print("DJI VALID", datetime.fromtimestamp(os.path.getmtime(img_list_dji[ind])))
        img_list_sjcam_sync.append(img_list_sjcam[int(best_match)])
        sync_pairs.append(
            (
            img_list_dji[ind] if replace_dji is None else img_list_dji[ind].replace(replace_dji[0], replace_dji[1]),
            img_list_sjcam[int(best_match)]
            )
        )
    return sync_pairs


if __name__ == '__main__':
    sync_pairs = synchronize_data(folder = r"D:\FLY-20210906-Blassac-05ms\AerialPhotography", replace_dji=(".DNG", "_PL4_DIST.tif"))