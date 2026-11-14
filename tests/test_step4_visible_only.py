"""Step 4 of a visible only mission: the visible images are developed (colour,
lens distortion, crop) instead of aligned, into the same review JPEG and the
red, green, blue bands of the multispectral export."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import IRD_Interactive_4 as S4  # noqa: E402
import mission_type as MT  # noqa: E402
import run_after_preprocessing as RAP  # noqa: E402
from config import EXIFTOOLPATH, missing_tools  # noqa: E402

TOOLS_FOUND = not {variable for _, variable, *_ in missing_tools()} & {"EXIFTOOLPATH", "RAWTHERAPEEPATH"}


def visible_mission(points=60, step=3.0):
    m = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Visible"
    (m / "AerialPhotography" / "VIS").mkdir(parents=True)
    (m / "FlightAnalytics").mkdir()
    (m / "FlightAnalytics" / "mission_parameters.json").write_text(
        json.dumps({"File path mission": str(m), MT.KEY: MT.VISIBLE}))
    shoot_points = [
        {"VIS": {"FileName": f"VIS_{n:04d}.dng", "Directory": str(m / "AerialPhotography" / "VIS"),
                 "DroneLatitude": 45.0 + n * step / 111195.0, "DroneLongitude": 3.0,
                 "DroneAltitudeGround": 100.0, "GimbalYawDegree": 0.0},
         "NIR": []}
        for n in range(1, points + 1)
    ]
    (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps({"shoot_points": shoot_points}))
    (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
        {"fly": {"listCopiedImages": [p["VIS"]["FileName"] for p in shoot_points[10:]]}}))
    return m


class DialogTest(unittest.TestCase):
    def test_every_survey_image_can_be_developed(self):
        d = S4.DialogImageProcessing({"File path mission": str(visible_mission())})
        self.assertTrue(d.visible_only)
        self.assertIn("Development", d.windowTitle())
        self.assertEqual((d.start_image_number.value(), d.end_image_number.value()), (11, 60))
        d.all_images_radio.setChecked(True)
        self.assertEqual(d.best_mapping_selection(), (50, 50))     # nothing to synchronise: all of them
        self.assertIn("All 50 survey images will be developed", d.best_mapping_count.text())
        d.best_mapping_radio.setChecked(True)
        self.assertLess(d.best_mapping_selection()[0], 50)
        self.assertEqual(d.run_button.text(), "Run development")
        with mock.patch.object(d.process, "start") as start:
            d._start_processing()
        arguments = start.call_args[0][1]
        self.assertIn("--visible-only", arguments)
        self.assertNotIn("--ndvi", arguments)

    def test_shoot_points_written_when_missing(self):
        m = visible_mission()
        (m / "AerialPhotography" / "shoot_points.json").unlink()
        sidecar = {"FileName": "VIS_0001.dng", "Directory": str(m / "AerialPhotography" / "VIS")}
        (m / "AerialPhotography" / "VIS" / "VIS_0001.dng").write_bytes(b"")
        (m / "AerialPhotography" / "VIS" / "VIS_0001.exif").write_text(json.dumps(sidecar))
        (m / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(
            {"fly": {"listCopiedImages": ["VIS_0001.dng"]}}))
        d = S4.DialogImageProcessing({"File path mission": str(m)})
        self.assertEqual(d.pair_count, 1)


class InventoryTest(unittest.TestCase):
    def test_only_complete_band_triplets_and_flags_kept(self):
        folder = Path(tempfile.mkdtemp())
        for number in ("0100", "0101"):
            (folder / f"IRD_{number}_1.exif").write_text("{}")
            for band in (1, 2, 3) if number == "0100" else (1, 2):
                (folder / f"IRD_{number}_{band}.tif").write_bytes(b"")
        data = {"pairing_method": "visible_only", "shoot_points": [
            {"VIS": {"FileName": "VIS_0100.dng"}, "NIR": []}, {"VIS": {"FileName": "VIS_0101.dng"}, "NIR": []}]}
        previous = {"shoot_points": [{"FileName": "VIS_0100.dng", "failed": True, "note": "blurred"}]}
        summary = RAP.build_developed_shoot_points(data, folder, previous)
        self.assertEqual(summary["pairing_method"], "visible_only")
        self.assertEqual(summary["shoot_points"],
                         [{"FileName": "VIS_0100.dng", "failed": True, "note": "blurred", "dt": 0.0}])


@unittest.skipUnless(TOOLS_FOUND, "RawTherapee and ExifTool needed")
class DevelopTest(unittest.TestCase):
    def test_sample_developed_by_the_command_line(self):
        m = visible_mission(points=1)
        vis = m / "AerialPhotography" / "VIS"
        shutil.copy(ROOT / "samples" / "_visible.DNG", vis / "VIS_0001.dng")
        points = json.loads((m / "AerialPhotography" / "shoot_points.json").read_text())
        points["shoot_points"][0]["VIS"].update({
            "UTM_x": 500000.0, "UTM_y": 4980000.0, "UTM_zone": 31, "GroundAltitude": 500.0,
            "DroneAltitudeSeaLevel": 600.0, "FlightYawDegree": 0.0, "FlightPitchDegree": 0.0,
            "FlightRollDegree": 0.0})
        (m / "AerialPhotography" / "shoot_points.json").write_text(json.dumps(points))
        result = subprocess.run(
            [sys.executable, str(ROOT / "run_after_preprocessing.py"), "-i", str(m), "--workers", "1",
             "--progress"], capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("STEP4_PROGRESS 1 1 VIS_0001.dng", result.stdout)
        out = m / "ImgIRdrone"
        self.assertTrue((out / "VIS_0001.jpg").is_file())
        bands = sorted(p.name for p in (out / "imgMultispectral").iterdir())
        self.assertEqual(bands, ["IRD_0001_1.exif", "IRD_0001_1.tif", "IRD_0001_2.tif", "IRD_0001_3.tif"])
        self.assertFalse(list(out.glob("VIR_*")))
        inventory = json.loads((out / "shoot_points.json").read_text())
        self.assertEqual(inventory["shoot_points"], [{"FileName": "VIS_0001.dng", "dt": 0.0, "failed": False}])
        self.assertTrue((m / "mapping_MULTI" / "camera" / "camera_IRdrone.json").is_file())
        tags = subprocess.run([str(EXIFTOOLPATH), "-s3", "-BandName", "-ImageWidth",
                               str(out / "imgMultispectral" / "IRD_0001_3.tif")],
                              capture_output=True, text=True).stdout.split()
        self.assertEqual(tags, ["Blue", "3892"])


if __name__ == "__main__":
    unittest.main()
