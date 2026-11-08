"""Step 1 new mission: images found on the SD cards, mission parameters with the
keys of the classic form, mission folder created."""
import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mission_setup as MS  # noqa: E402

# Keys written by the classic form (Window_create_file_structure.update_mission_parameters)
CLASSIC_KEYS = {
    "File path mission", "original File path take-off", "original name image take-off", "name image take-off",
    "suffix image take-off", "path mission image take-off", "Body serial number", "Date Exif", "Date", "Time",
    "Location", "Description", "GPS coordinate", "GPS N-S", "GPS lat", "GPS E-W", "GPS lon", "GPS alti",
    "GPS drone alti", "Pilot", "Pilot ID", "camera VIS maker", "camera VIS ID", "camera VIS timelapse",
    "camera VIS deltatime", "img VIS ext", "camera NIR maker", "camera NIR ID", "camera NIR timelapse",
    "camera NIR deltatime", "original img NIR ext", "camera NIR filter maker", "camera NIR filter band",
    "synchro", "output", "visible", "nir", "AerialPhotography folder", "FlightAnalytics folder",
    "ImgIRdrone folder", "Synchro folder", "ODM folder", "cameras folder",
}


def light(path="/card/DCIM/100MEDIA/HYPERLAPSE_0007.DNG"):
    return {
        "File path": path, "original name image take-off": "HYPERLAPSE_0007.DNG",
        "name image take-off": "VIS_0007.dng", "suffix image take-off": "dng",
        "Maker": "DJI", "Model": "FC3170", "Body serial number": "1TC", "Date Exif": "2022:01:25 11:59:49",
        "GPS N-S": "N", "GPS E-W": "E", "GPS lat": 45.16954, "GPS lon": 3.40004, "GPS alti": 0.0,
        "GPS drone alti": 0.6, "Location": "",
    }


class CardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def touch(self, rel, t=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10)
        if t is not None:
            os.utime(p, (t, t))
        return p

    def test_cards_with_dcim_give_visible_and_infrared_folders(self):
        for k in (1, 2, 10):
            self.touch(f"dji/DCIM/100MEDIA/HYPERLAPSE_{k:04d}.DNG")
        self.touch("dji/DCIM/100MEDIA/DJI_0001.JPG")
        for k in (1, 3):
            self.touch(f"sj/DCIM/2022_0125_130413_00{k}.RAW")
        self.touch("system/Users/photo.dng")          # no DCIM: not read
        found = MS.find_card_images([(self.root / "dji", "DJI"), (self.root / "sj", "SJCAM"),
                                     (self.root / "system", "C:")])
        by_band = {c.band: c for c in found}
        self.assertEqual(set(by_band), {"VIS", "NIR"})
        vis = by_band["VIS"].summary
        self.assertEqual([p.name for p in vis.files],
                         ["HYPERLAPSE_0001.DNG", "HYPERLAPSE_0002.DNG", "HYPERLAPSE_0010.DNG"])
        self.assertEqual(MS.takeoff_image(vis).name, "HYPERLAPSE_0001.DNG")
        self.assertEqual(by_band["NIR"].summary.count, 2)

    def test_clock_gap_from_file_times(self):
        t0 = time.mktime((2022, 1, 25, 11, 59, 0, 0, 0, -1))
        self.touch("v/a_0001.dng", t0)
        self.touch("n/b_001.raw", t0 + 3900)
        gap = MS.clock_gap(MS.summarize(self.root / "v", MS.VIS_SUFFIXES),
                           MS.summarize(self.root / "n", MS.NIR_SUFFIXES))
        self.assertAlmostEqual(gap, 3900)

    def test_describe(self):
        self.assertEqual(MS.summarize(self.root, MS.VIS_SUFFIXES).describe(), "no image")
        self.assertEqual(MS.human_size(5.9 * 1024 ** 3), "5.9 GB")


class ParametersTests(unittest.TestCase):
    def test_same_keys_as_the_classic_form(self):
        params = MS.build_mission_parameters(light(), {"location": "Blassac"}, Path("/work"))
        self.assertEqual(set(params), CLASSIC_KEYS)
        self.assertEqual(params["File path mission"], "/work/FLY-20220125-1159-Blassac")
        self.assertEqual(params["Date Exif"], "2022:01:25 11:59:49")
        self.assertEqual(params["path mission image take-off"],
                         str(Path("/work/FLY-20220125-1159-Blassac/AerialPhotography/VIS/VIS_0007.dng")))
        self.assertEqual(params["img VIS ext"], "DNG")
        self.assertEqual(params["camera NIR filter band"], 810)

    def test_address_keys_only_when_known(self):
        lt = MS.add_location(light(), {"z": 536.7, "ville": "Blassac", "pays": "France", "region": None})
        params = MS.build_mission_parameters(lt, {"location": lt["Location"]}, Path("/work"))
        self.assertEqual(params["Country"], "France")
        self.assertNotIn("Region", params)
        self.assertEqual(params["GPS alti"], 536.7)

    def test_folder_name_is_safe(self):
        when = dt.datetime(2022, 1, 25, 11, 59)
        self.assertEqual(MS.mission_folder_name(when, "Le Puy/Velay: été"), "FLY-20220125-1159-Le Puy-Velay- été")
        self.assertEqual(MS.mission_folder_name(when, "  "), "FLY-20220125-1159")

    def test_saved_form_values_keep_their_types(self):
        form = MS.form_from_settings({"pilot": "Florine", "nir_timelapse": "4", "filter_band": "bad"})
        self.assertEqual((form["pilot"], form["nir_timelapse"], form["filter_band"]), ("Florine", 4, 810))


class CreateMissionTests(unittest.TestCase):
    def test_tree_parameters_takeoff_and_transfer_info(self):
        tmp = Path(tempfile.mkdtemp())
        card = tmp / "card" / "HYPERLAPSE_0007.DNG"
        card.parent.mkdir()
        card.write_bytes(b"dng")
        params = MS.build_mission_parameters(light(str(card)), {"location": "Blassac"}, tmp / "work")
        base = MS.create_mission(params)
        for sub in MS.MISSION_FOLDERS:
            self.assertTrue((base / sub).is_dir(), sub)
        self.assertEqual(json.loads((base / "FlightAnalytics" / "mission_parameters.json").read_text())["Location"],
                         "Blassac")
        self.assertTrue((base / "AerialPhotography" / "VIS" / "VIS_0007.dng").is_file())
        info = json.loads((base / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").read_text())
        self.assertEqual(info["tkoff"]["listCopiedImages"], ["VIS_0007.dng"])
        # created again (Step 1 run twice): the existing selection is kept
        info["fly"]["listCopiedImages"] = ["VIS_0100.dng"]
        (base / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps(info))
        MS.create_mission(params)
        again = json.loads((base / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").read_text())
        self.assertEqual(again["fly"]["listCopiedImages"], ["VIS_0100.dng"])


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_next_needs_both_cameras(self):
        import IRD_Interactive_new_mission as NM
        tmp = Path(tempfile.mkdtemp())
        (tmp / "card" / "DCIM").mkdir(parents=True)
        (tmp / "card" / "DCIM" / "HYPERLAPSE_0001.DNG").write_bytes(b"x")
        with mock.patch.object(NM, "mounted_volumes", return_value=[(str(tmp / "card"), "CARD")]):
            d = NM.NewMissionDialog(tmp / "work", scan=False)
            d.scan_cards()
        self.assertEqual(d.vis.count, 1)
        self.assertFalse(d.btn_next.isEnabled())       # no infrared yet
        (tmp / "card" / "DCIM" / "SJ").mkdir()
        (tmp / "card" / "DCIM" / "SJ" / "2022_0125_130413_001.RAW").write_bytes(b"x")
        with mock.patch.object(NM, "mounted_volumes", return_value=[(str(tmp / "card"), "CARD")]):
            d.scan_cards()
        self.assertTrue(d.btn_next.isEnabled())
        d.done(0)

    def test_a_card_inserted_later_is_found_by_itself(self):
        import IRD_Interactive_new_mission as NM
        tmp = Path(tempfile.mkdtemp())
        card = tmp / "card"
        with mock.patch.object(NM, "mounted_volumes", return_value=[]):
            d = NM.NewMissionDialog(tmp / "work", scan=True)
            self.app.processEvents()                      # first scan: nothing
        self.assertTrue(d.card_poll.isActive())
        (card / "DCIM" / "SJ").mkdir(parents=True)
        (card / "DCIM" / "HYPERLAPSE_0001.DNG").write_bytes(b"x")
        (card / "DCIM" / "SJ" / "2022_0125_130413_001.RAW").write_bytes(b"x")
        with mock.patch.object(NM, "mounted_volumes", return_value=[(str(card), "CARD")]):
            d._poll_cards()                               # what the timer does
        self.assertEqual((d.vis.count, d.nir.count), (1, 1))
        self.assertFalse(d.card_poll.isActive())          # both found: no more polling
        d.done(0)

    def test_previews_take_off_and_in_flight(self):
        s = MS.summarize(Path(tempfile.mkdtemp()), [".raw"])
        self.assertIsNone(MS.nir_preview_jpeg(s, 5))
        self.assertEqual(MS.flight_index(251), 167)
        self.assertEqual(MS.flight_index(1), 0)


if __name__ == "__main__":
    unittest.main()


class MissionDetailsTest(unittest.TestCase):
    """Step 1 done: details edited in mission_parameters.json, nothing else."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Blassac"
        (self.folder / "FlightAnalytics").mkdir(parents=True)
        self.params = {"File path mission": str(self.folder), "Location": "Blassac", "Description": "",
                       "Pilot": "Alain", "camera VIS timelapse": 2, "camera NIR filter band": 810,
                       "GPS lat": 45.1, "name image take-off": "VIS_0001.dng"}
        MS.mission_parameters_path(self.folder).write_text(json.dumps(self.params))

    def test_form_has_defaults_for_missing_keys(self):
        form = MS.details_form(self.params)
        self.assertEqual((form["pilot"], form["vis_timelapse"]), ("Alain", 2))
        self.assertEqual(form["nir_timelapse"], MS.DEFAULT_FORM["nir_timelapse"])

    def test_only_details_change_and_a_backup_is_kept(self):
        form = MS.details_form(self.params)
        form.update(description="Vineyard", filter_band=720, location="Blassac / haut")
        changed = MS.update_mission_details(self.folder, form)
        self.assertIn("Description", changed)
        saved = json.loads(MS.mission_parameters_path(self.folder).read_text())
        self.assertEqual(saved["Description"], "Vineyard")
        self.assertEqual(saved["camera NIR filter band"], 720)
        self.assertEqual(saved["Location"], "Blassac - haut")
        self.assertEqual(saved["GPS lat"], 45.1)                       # untouched
        self.assertEqual(saved["File path mission"], str(self.folder))
        self.assertTrue((self.folder / "FlightAnalytics" / "mission_parameters.json.bak").is_file())

    def test_nothing_changed_nothing_written(self):
        before = MS.mission_parameters_path(self.folder).read_text()
        form = {k: v for k, v in MS.details_form(self.params).items()
                if MS.EDITABLE_DETAILS[k][0] in self.params}
        self.assertEqual(MS.update_mission_details(self.folder, form), [])
        self.assertEqual(MS.mission_parameters_path(self.folder).read_text(), before)

    def test_dialog_saves(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import IRD_Interactive_mission_details as D
        d = D.MissionDetailsDialog(self.folder)
        d.f_description.setText("Plot 12")
        d.btn_save.click()
        self.assertIn("Description", d.changed)
        self.assertEqual(MS.read_mission_parameters(self.folder)["Description"], "Plot 12")


class NirPreviewTest(unittest.TestCase):
    def folder(self, names):
        d = Path(tempfile.mkdtemp())
        for n in names:
            (d / n).write_bytes(b"x")
        return MS.summarize(d, [".raw"])

    def test_sjcam_m20_jpeg_under_the_next_name(self):
        s = self.folder(["2022_0125_130413_001.RAW", "2022_0125_130415_002.JPG",
                         "2022_0125_130416_003.RAW", "2022_0125_130418_004.JPG"])
        self.assertEqual(MS.nir_preview_jpeg(s).name, "2022_0125_130415_002.JPG")

    def test_jpeg_under_the_same_name_first(self):
        s = self.folder(["NIR_0001.RAW", "NIR_0001.JPG", "NIR_0000.JPG"])
        self.assertEqual(MS.nir_preview_jpeg(s).name, "NIR_0001.JPG")

    def test_no_jpeg(self):
        self.assertIsNone(MS.nir_preview_jpeg(self.folder(["a.RAW"])))
