import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "irdrone_wizard"))

import numpy as np

import IRD_Interactive_ArUco as Aru

_RESULT = {"angle_abs": 10.0, "angle_img": 20.0, "delta_abs_img": 10.0}


class CheckImageWriteTests(unittest.TestCase):
    """process_aruco_images writes each check image once, and only when drawn."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = Path(self.tmp.name) / "mission"
        (self.mission / "VIS").mkdir(parents=True)
        (Path(self.tmp.name) / "Synchro").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, marker_data_ID):
        written, sent = [], []
        img = np.zeros((10, 10, 3), np.uint8)
        with mock.patch.object(Aru, "read_transfer_info", return_value=(None, 0, 1, ["a.jpg", "b.jpg"])), \
                mock.patch.object(Aru, "load_relative_time_line", return_value={}), \
                mock.patch.object(Aru, "extract_relative_time_line", return_value=0.0), \
                mock.patch.object(Aru, "read_aruco_cache", return_value=None), \
                mock.patch.object(Aru.cv2, "imread", return_value=img), \
                mock.patch.object(Aru.cv2, "imwrite", side_effect=lambda p, *a: written.append(Path(p).name)), \
                mock.patch.object(Aru, "draw_aruco_overlay", return_value=img), \
                mock.patch.object(Aru, "detect_mobile_marker_absolute",
                                  side_effect=lambda **kw: (dict(_RESULT), None, marker_data_ID)):
            Aru.process_aruco_images(
                folderMissionPath=self.mission,
                name_folder="VIS",
                spectral_band="VIS",
                suffix_image="jpg",
                save_check_detection_img=True,
                multi_thread=False,
                check_image_callback=sent.append,
            )
        return written, [Path(p).name for p in sent]

    def test_each_check_image_written_once_and_sent(self):
        written, sent = self._run(marker_data_ID={0: {}})
        self.assertEqual(written, ["a_aruco.jpg", "b_aruco.jpg"])
        self.assertEqual(sent, ["a_aruco.jpg", "b_aruco.jpg"])

    def test_no_markers_writes_and_sends_nothing(self):
        written, sent = self._run(marker_data_ID=None)
        self.assertEqual(written, [])
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
