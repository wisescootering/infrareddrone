import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import IRD_Interactive_archive as arc


def touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_mission(root: Path) -> Path:
    m = root / "FLY-20220125-1159-Test"
    touch(m / "desktop.ini")
    touch(m / "FlightAnalytics" / "mission_parameters.json", "{}")
    touch(m / "FlightAnalytics" / "other.txt")
    touch(m / "cameras" / "cam.json")
    touch(m / "mapping_MULTI" / "mapping_result" / "ortho.tif")
    touch(m / "mapping_MULTI - Copie" / "x.tif")
    touch(m / "dev_leftover.txt")
    a = m / "AerialPhotography"
    touch(a / "shoot_points.json", "{}")
    touch(a / "desktop.ini")
    touch(a / "junk.txt")
    for band, ext in (("VIS", "DNG"), ("NIR", "dng")):
        touch(a / band / f"{band}_0001.{ext}")
        touch(a / band / f"{band}_0001.exif")
        touch(a / band / f"{band}_0001_RawTherapee.tif")
        touch(a / band / "time_line.json", "{}")
        touch(a / band / f"transfer_info_{band}_dng.json", "{}")
    i = m / "ImgIRdrone"
    for name in ("VIS_0001.jpg", "VIR_0001_local.jpg", "VIS_0001_motion_model.npy",
                 "NDVI_0001_local.jpg", "shoot_points.json",
                 "shoot_points_failed_summary.json"):
        touch(i / name)
    for name in ("VIR_0001_global.jpg", "VIS_0001_motion_model.json", "VIS_0001_REDO.bat",
                 "NIR_0001_global.jpg"):
        touch(i / name)
    touch(i / "imgMultispectral" / "IRD_0001_1.tif", "0123456789")
    touch(i / "VIS_0001_align_traces_manual" / "t.png")
    s = m / "Synchro"
    for name in ("check_time_alignment.png", "check_time_before_alignment.png", "desktop.ini"):
        touch(s / name)
    touch(s / "VIS" / "a.dng")
    touch(s / "Check_ARUCO" / "b.png")
    return m


def names(folder: Path):
    return {p.name for p in folder.iterdir()}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = make_mission(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_changes_nothing(self):
        before = sorted(str(p) for p in self.mission.rglob("*"))
        plan = arc.build_plan(self.mission)
        self.assertEqual(plan.blockers, [])
        self.assertGreater(len(plan.delete_items), 0)
        self.assertEqual(before, sorted(str(p) for p in self.mission.rglob("*")))

    def test_execute_keeps_only_essentials(self):
        plan = arc.build_plan(self.mission)
        arc.execute_archive(plan, log=lambda m: None)
        m = self.mission
        icon = {arc.ICON_NAME} if arc.ICON_SOURCE.is_file() and os.name == "nt" else set()
        self.assertEqual(
            names(m),
            {"desktop.ini", "FlightAnalytics", "cameras", "mapping_MULTI", "AerialPhotography",
             "ImgIRdrone", "Synchro", arc.MANIFEST_NAME, arc.LOG_NAME} | icon,
        )
        self.assertEqual(names(m / "AerialPhotography"),
                         {"VIS", "NIR", "shoot_points.json", "desktop.ini"})
        self.assertEqual(names(m / "AerialPhotography" / "VIS"),
                         {"VIS_0001.DNG", "VIS_0001.exif", "time_line.json",
                          "transfer_info_VIS_dng.json"})
        self.assertEqual(names(m / "AerialPhotography" / "NIR"),
                         {"NIR_0001.dng", "NIR_0001.exif", "time_line.json",
                          "transfer_info_NIR_dng.json"})
        self.assertEqual(
            names(m / "ImgIRdrone"),
            {"VIS_0001.jpg", "VIR_0001_local.jpg", "VIS_0001_motion_model.npy",
             "NDVI_0001_local.jpg", "shoot_points.json", "shoot_points_failed_summary.json"},
        )
        self.assertEqual(names(m / "Synchro"),
                         {"check_time_alignment.png", "check_time_before_alignment.png",
                          "desktop.ini"})
        self.assertTrue((m / "FlightAnalytics" / "other.txt").is_file())
        self.assertTrue((m / "mapping_MULTI" / "mapping_result" / "ortho.tif").is_file())

    def test_previous_maps_set_aside_by_step5_are_kept(self):
        old = self.mission / "mapping_MULTI_20261110_171700" / "mapping_result"
        old.mkdir(parents=True)
        (old / "ortho.tif").write_bytes(b"x")
        arc.execute_archive(arc.build_plan(self.mission), log=lambda m: None)
        self.assertTrue((old / "ortho.tif").is_file())

    def test_manifest_and_already_archived(self):
        plan = arc.build_plan(self.mission)
        manifest = arc.execute_archive(plan, log=lambda m: None)
        self.assertEqual(manifest["status"], "completed")
        again = arc.build_plan(self.mission)
        self.assertTrue(again.already_archived)
        self.assertTrue(again.blockers)

    def test_missing_required_file_blocks(self):
        (self.mission / "ImgIRdrone" / "shoot_points.json").unlink()
        (self.mission / "AerialPhotography" / "VIS" / "time_line.json").unlink()
        plan = arc.build_plan(self.mission)
        self.assertEqual(len(plan.blockers), 2)
        with self.assertRaises(RuntimeError):
            arc.execute_archive(plan, log=lambda m: None)

    def test_not_a_mission_folder_blocks(self):
        other = Path(self.tmp.name) / "not_a_mission"
        touch(other / "file.txt")
        plan = arc.build_plan(other)
        self.assertTrue(plan.blockers)
        self.assertTrue((other / "file.txt").exists())

    def test_missing_optional_folders_not_created(self):
        import shutil
        shutil.rmtree(self.mission / "mapping_MULTI")
        shutil.rmtree(self.mission / "Synchro")
        plan = arc.build_plan(self.mission)
        self.assertEqual(plan.blockers, [])
        arc.execute_archive(plan, log=lambda m: None)
        self.assertFalse((self.mission / "mapping_MULTI").exists())
        self.assertFalse((self.mission / "Synchro").exists())

    def test_progress_reaches_total(self):
        plan = arc.build_plan(self.mission)
        calls = []
        arc.execute_archive(plan, log=lambda m: None, progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls[-1][0], calls[-1][1])


if __name__ == "__main__":
    unittest.main()
