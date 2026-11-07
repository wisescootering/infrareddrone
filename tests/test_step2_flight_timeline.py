"""Step 2 flight timeline: automatic detection of the synchronisation and
survey phases (pure functions, no image needed)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import flight_timeline as FT  # noqa: E402


def turntable(t, start=20.0, reverse=80.0, stop=120.0, w=-6.0, offset=0.0):
    """Marker angle (deg, wrapped) of a turntable that starts, reverses, stops."""
    t = np.asarray(t, dtype=float)
    a = np.where(t < start, 0.0,
                 np.where(t < reverse, w * (t - start),
                          np.where(t < stop, w * (reverse - start) - w * (t - reverse),
                                   w * (reverse - start) - w * (stop - reverse))))
    return FT.wrap180(a + offset)


class HoverAndSurveyTests(unittest.TestCase):
    def test_low_hover_stops_at_the_climb(self):
        alts = [0.6] * 40 + [0.7, 3.9, 8.0, 20.0] + [100.0] * 20
        self.assertEqual(FT.low_hover_window(alts), FT.Window(0, 40))

    def test_low_hover_ignores_a_single_spike(self):
        alts = [0.6] * 10 + [5.0] + [0.6] * 10 + [30.0, 50.0]
        self.assertEqual(FT.low_hover_window(alts), FT.Window(0, 20))

    def test_low_hover_without_altitude(self):
        self.assertIsNone(FT.low_hover_window([None] * 5))

    def test_survey_is_the_longest_plateau(self):
        alts = [0.6] * 30 + list(np.linspace(1, 100, 15)) + [116.0] * 50 + [60.0] * 5 + [116.0] * 10
        w = FT.survey_window(alts)
        self.assertEqual((w.first, w.last), (45, 94))

    def test_survey_bridges_one_frame_drop(self):
        alts = [0.0] * 5 + [100.0] * 10 + [80.0] + [100.0] * 10
        w = FT.survey_window(alts)
        self.assertEqual((w.first, w.last), (5, 25))

    def test_take_off_from_a_summit_and_fly_down(self):
        # altitudes relative to take-off are negative: hover, descent, survey 80 m below
        alts = [0.5] * 30 + list(np.linspace(-4, -78, 10)) + [-80.0] * 40 + [-40.0, 0.4]
        self.assertEqual(FT.low_hover_window(alts), FT.Window(0, 29))
        w = FT.survey_window(alts)
        self.assertEqual((w.first, w.last), (39, 79))

    def test_no_survey_when_never_left_the_ground(self):
        self.assertIsNone(FT.survey_window([0.5] * 50))


class RotationSegmentTests(unittest.TestCase):
    def test_start_reversal_and_stop_split_the_segments(self):
        t = np.arange(0, 140, 2.0)
        # turning from t=20 to 81 then back until 121: the reversal and the stop
        # happen between two frames, the steps across them are too slow
        segs = FT.rotation_segments(t, list(turntable(t, reverse=81.0, stop=121.0)))
        self.assertEqual([(s.first, s.last) for s in segs], [(10, 40), (41, 60)])

    def test_missing_detections_break_the_segment(self):
        t = np.arange(0, 60, 2.0)
        angles = list(FT.wrap180(-6.0 * t))
        angles[10] = None
        segs = FT.rotation_segments(t, angles)
        self.assertEqual([(s.first, s.last) for s in segs], [(0, 9), (11, 29)])

    def test_still_target_gives_no_segment(self):
        t = np.arange(0, 30, 3.0)
        self.assertEqual(FT.rotation_segments(t, [2.0, -1.0, 1.0, 0.5, 0.0, 1.0, -0.5, 0.2, 0.0, 1.0]), [])


class CoarseShiftTests(unittest.TestCase):
    def test_shift_found_from_the_rotation_events(self):
        # NIR camera started 31 s before VIS, 3 s period, mounted 4 deg apart
        t_vis = np.arange(0, 150, 2.02)
        t_nir = np.arange(0, 200, 3.0)
        a_vis = turntable(t_vis)
        a_nir = turntable(t_nir - 31.0, offset=4.0)
        shift, rms = FT.coarse_time_shift(t_vis, list(a_vis), t_nir, list(a_nir))
        self.assertAlmostEqual(shift, -31.0, delta=0.3)
        self.assertLess(rms, 2.0)

    def test_no_shift_without_enough_detections(self):
        self.assertEqual(FT.coarse_time_shift([0, 1], [0, 1], [0, 1, 2], [0, 1, 2]), (None, None))

    def test_matching_segments_pick_the_same_turn(self):
        t_vis = np.arange(0, 150, 2.0)
        t_nir = np.arange(0, 200, 3.0)
        vis = FT.BandAnalysis("VIS", [FT.Frame(f"VIS_{i+1:04d}.dng", i + 1, t, marker_angle=float(a))
                                      for i, (t, a) in enumerate(zip(t_vis, turntable(t_vis)))])
        nir = FT.BandAnalysis("NIR", [FT.Frame(f"NIR_{i+1:04d}.dng", i + 1, t, marker_angle=float(a))
                                      for i, (t, a) in enumerate(zip(t_nir, turntable(t_nir - 31.0)))])
        vis.segments = FT.rotation_segments(vis.times, [f.marker_angle for f in vis.frames])
        nir.segments = FT.rotation_segments(nir.times, [f.marker_angle for f in nir.frames])
        wv, wn = FT.match_segments(vis, nir, -31.0)
        # both on the first turn (20 s to 80 s on the VIS time line)
        self.assertLess(vis.times[wv.last], 81)
        self.assertLess(nir.times[wn.last] - 31.0, 81)
        self.assertGreater(nir.times[wn.first] - 31.0, 19)
        # without the shift: same direction, closest duration
        wv2, wn2 = FT.match_segments(vis, nir, None)
        self.assertEqual(wv2, wv)
        self.assertEqual(wn2, wn)


class DerivedWindowTests(unittest.TestCase):
    def test_nir_survey_brackets_the_vis_survey(self):
        t_vis = np.arange(0, 500, 2.0)
        t_nir = np.arange(0, 540, 3.0)
        w = FT.derived_window(t_vis, FT.Window(130, 249), t_nir, -31.0)
        # VIS 260..498 s -> NIR time 291..529 s -> frames 97..176, plus one each side
        self.assertEqual((w.first, w.last), (96, 177))

    def test_no_shift_no_window(self):
        self.assertIsNone(FT.derived_window(np.arange(3.0), FT.Window(0, 1), np.arange(3.0), None))


class SavingTests(unittest.TestCase):
    def setUp(self):
        self.mission = Path(tempfile.mkdtemp()) / "FLY-20220125-1159-Test"
        for band, n, period in (("VIS", 20, 2.0), ("NIR", 15, 3.0)):
            folder = self.mission / "AerialPhotography" / band
            folder.mkdir(parents=True)
            items = []
            for i in range(n):
                name = f"{band}_{i + 1:04d}.dng"
                (folder / name).write_bytes(b"")
                (folder / name).with_suffix(".exif").write_text(json.dumps(
                    {"DroneAltitudeTakeOff": 0.6} if band == "VIS" else {}))
                items.append({"img_path": name, "relative_timeline": i * period})
            (folder / "time_line.json").write_text(json.dumps({band: items}))
        # Step 1 writes the VIS take-off section with the SD card name
        (self.mission / "AerialPhotography" / "VIS" / "transfer_info_VIS_dng.json").write_text(json.dumps({
            "tkoff": {"outputFolder": "x", "original name": "HYPERLAPSE_0001.DNG",
                      "idMin": 1, "idMax": 1, "listCopiedImages": ["VIS_0001.dng"]}}))

    def test_list_frames_reads_time_and_altitude(self):
        frames = FT.list_frames(self.mission, "VIS")
        self.assertEqual(len(frames), 20)
        self.assertEqual(frames[3].t, 6.0)
        self.assertEqual(frames[3].alt, 0.6)
        self.assertEqual(frames[3].number, 4)

    def test_transfer_info_keeps_step1_takeoff_and_steps_read_it(self):
        frames = FT.list_frames(self.mission, "VIS")
        path = FT.write_transfer_info(self.mission, "VIS", frames, FT.Window(2, 5), FT.Window(10, 19))
        data = json.loads(path.read_text())
        self.assertEqual(data["tkoff"]["original name"], "HYPERLAPSE_0001.DNG")
        self.assertEqual(data["sync"]["idMin"], 3)
        self.assertEqual(data["sync"]["idMax"], 6)
        self.assertEqual(data["sync"]["listCopiedImages"], ["VIS_0003.dng", "VIS_0004.dng", "VIS_0005.dng", "VIS_0006.dng"])
        self.assertEqual(data["fly"]["listCopiedImages"][0], "VIS_0011.dng")
        # Step 3 reads it through read_transfer_info
        import IRD_Interactive_ArUco as Aru
        _, id_min, id_max, names = Aru.read_transfer_info(self.mission / "AerialPhotography", "VIS", "dng", "sync")
        self.assertEqual((id_min, id_max, len(names)), (3, 6, 4))

    def test_nir_takeoff_defaults_to_first_frame(self):
        frames = FT.list_frames(self.mission, "NIR")
        data = json.loads(FT.write_transfer_info(self.mission, "NIR", frames, FT.Window(1, 4), None).read_text())
        self.assertEqual(data["tkoff"]["listCopiedImages"], ["NIR_0001.dng"])
        self.assertEqual(data["fly"]["listCopiedImages"], [])

    def test_nir_survey_updated_after_step3(self):
        vis = FT.list_frames(self.mission, "VIS")
        nir = FT.list_frames(self.mission, "NIR")
        FT.write_transfer_info(self.mission, "VIS", vis, FT.Window(0, 3), FT.Window(10, 19))   # 20..38 s
        FT.write_transfer_info(self.mission, "NIR", nir, FT.Window(0, 3), None)
        path = FT.update_nir_survey_from_vis(self.mission, time_shift=-6.0)   # NIR 26..44 s
        fly = json.loads(path.read_text())["fly"]
        # NIR frames at 27..42 s (9..14) plus one each side, clipped to the last frame
        self.assertEqual((fly["idMin"], fly["idMax"]), (9, 15))


if __name__ == "__main__":
    unittest.main()
