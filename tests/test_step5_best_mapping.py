"""Step 5: the ODM image selection defaults to the best mapping (image overlap)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import best_mapping  # noqa: E402
import IRD_Interactive_5 as S5  # noqa: E402

S5.ODMSelectionDialog.check_engine = False      # no Docker / Docker Hub in the tests


class ODMSelectionDialogTest(unittest.TestCase):
    def test_default_is_overlap_at_75_percent(self):
        d = S5.ODMSelectionDialog()
        self.assertTrue(d.overlap_radio.isChecked())
        self.assertEqual(d.selected_overlap(), 0.75)
        self.assertFalse(d.sample_every.isEnabled())
        self.assertIn("best mapping, 75% overlap", d.description())

    def test_choice_of_step2_and_step4_is_used(self):
        with tempfile.TemporaryDirectory() as m:
            best_mapping.save_choice(Path(m), enabled=True, overlap=0.85)
            self.assertEqual(S5.ODMSelectionDialog(mission_folder=Path(m)).selected_overlap(), 0.85)
            best_mapping.save_choice(Path(m), enabled=False)
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.sample_radio.isChecked())
            self.assertIsNone(d.selected_overlap())
            self.assertIn("one image every 3", d.description())

    def test_settings_of_the_last_run_are_proposed(self):
        import json
        with tempfile.TemporaryDirectory() as m:
            best_mapping.save_choice(Path(m), enabled=True, overlap=0.85)
            os.utime(Path(m) / best_mapping.CHOICE_FILE, (1, 1))
            (Path(m) / "mapping_MULTI").mkdir()
            (Path(m) / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps({"selection_rules": {
                "maximum_absolute_dt_seconds": 0.4, "selection": "sample_every",
                "sample_every_nth_eligible_pair": 2, "footprint_overlap": None}}))
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.sample_radio.isChecked())
            self.assertEqual((d.dt_tolerance.value(), d.sample_every.value()), (0.4, 2))
            self.assertEqual(d.overlap.value(), 85)

    def test_all_the_aligned_images_ignores_the_criteria(self):
        import json
        d = S5.ODMSelectionDialog()
        d.all_radio.setChecked(True)
        self.assertFalse(d.dt_tolerance.isEnabled() or d.overlap.isEnabled() or d.sample_every.isEnabled())
        self.assertEqual((d.selected_dt_tolerance(), d.selected_sample_every(), d.selected_overlap()),
                         (6.0, 1, None))
        self.assertEqual(d.short_description(), "all the aligned images")
        d.overlap_radio.setChecked(True)                      # back: the criteria again
        self.assertTrue(d.dt_tolerance.isEnabled() and d.overlap.isEnabled())
        self.assertEqual(d.selected_sample_every(), d.sample_every.value())
        with tempfile.TemporaryDirectory() as m:             # proposed again after such a run
            best_mapping.save_choice(Path(m), enabled=True)
            os.utime(Path(m) / best_mapping.CHOICE_FILE, (1, 1))
            (Path(m) / "mapping_MULTI").mkdir()
            (Path(m) / "mapping_MULTI" / "img_best_mappping.json").write_text(json.dumps({"selection_rules": {
                "maximum_absolute_dt_seconds": 6.0, "selection": "sample_every",
                "sample_every_nth_eligible_pair": 1, "footprint_overlap": None}}))
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertTrue(d.all_radio.isChecked())
            self.assertEqual(d.selected_dt_tolerance(), 6.0)

    def test_the_window_says_a_map_built_is_kept(self):
        with tempfile.TemporaryDirectory() as m:
            self.assertFalse(hasattr(S5.ODMSelectionDialog(mission_folder=Path(m)), "previous_map_note"))
            (Path(m) / "mapping_MULTI" / "mapping_result").mkdir(parents=True)
            (Path(m) / "mapping_MULTI" / "mapping_result" / "ortho.tif").write_bytes(b"x")
            d = S5.ODMSelectionDialog(mission_folder=Path(m))
            self.assertIn("kept, renamed mapping_MULTI_<date", d.previous_map_note.text())

    def test_sample_every_can_still_be_chosen(self):
        d = S5.ODMSelectionDialog()
        d.sample_radio.setChecked(True)
        self.assertTrue(d.sample_every.isEnabled())
        self.assertFalse(d.overlap.isEnabled())
        self.assertIsNone(d.selected_overlap())

    def test_worker_passes_the_overlap_to_odm(self):
        worker = S5.ODMRunWorker(Path("/mission"), dt_tolerance_s=0.4, sample_every=2, overlap=0.8)
        with mock.patch.object(S5, "run_odm", return_value={}) as run:
            worker.run()
        self.assertEqual(run.call_args.kwargs["overlap"], 0.8)
        self.assertEqual(run.call_args.kwargs["dt_tolerance_s"], 0.4)


class SelectionMapTest(unittest.TestCase):
    """The window shows the flight with the images selected and their footprints, live."""

    def test_the_map_follows_the_choices(self):
        import json
        import flight_map as F
        from test_flight_map import make_mission
        with mock.patch.object(F.urllib.request, "urlopen", side_effect=OSError("offline")), \
                tempfile.TemporaryDirectory() as root:
            m = make_mission(Path(root), n=8)
            path = m / "AerialPhotography" / "shoot_points.json"
            data = json.loads(path.read_text())
            for k, point in enumerate(data["shoot_points"]):
                point["NIR"] = [{"rank": 1, "dt": 0.9 if k == 7 else 0.1}]     # the last one: |dt| too big
            path.write_text(json.dumps(data))
            best_mapping.save_choice(m, enabled=False)
            d = S5.ODMSelectionDialog(mission_folder=m)
            self.assertIsNotNone(d.map_view)
            self.assertTrue(d.sample_radio.isChecked())
            d.sample_every.setValue(2)
            d.update_map()                       # (the timer, without waiting)
            self.assertEqual(d._eligible, set(range(137, 144)))
            self.assertEqual(d._selected, {137, 139, 141, 143})
            self.assertEqual(sorted(d.map_model.numbers[i] for i in d.map_model.selection), [137, 139, 141, 143])
            self.assertIn("4 images selected for the map, of 7 aligned", d.map_count.text())
            d.all_radio.setChecked(True)
            d.update_map()
            self.assertEqual(d._selected, set(range(137, 145)))
            import IRD_Interactive_map as Map
            Map.tile_cache().stop()

    def test_no_map_without_positions(self):
        with tempfile.TemporaryDirectory() as m:
            self.assertIsNone(S5.ODMSelectionDialog(mission_folder=Path(m)).map_view)

class GeorefMessageTest(unittest.TestCase):
    def test_the_message_follows_the_mission_type(self):
        import IRD_Interactive_GeoRef as G
        visible, multi = S5.georef_message(True), S5.georef_message(False)
        self.assertIn("DNG", visible)
        self.assertNotIn("TIFF", visible)
        self.assertIn("IRD_0121_4.tif", multi)
        self.assertNotIn("HYPERLAPSE", multi)
        self.assertNotIn("tif", G.GEOREF_VISIBLE_FILTERS.lower())

class EngineChoiceTest(unittest.TestCase):
    """The window shows the installed OpenDroneMap, offers a newer one and the GPU."""

    LOCAL = {"image": "opendronemap/odm:latest", "version": "3.6.2", "created": "2026-08-21T13:37:27Z",
             "digests": ["sha256:old"]}
    REMOTE = {"digest": "sha256:new", "published": "2026-10-02T10:00:00Z", "size": 1, "version": "3.7.0"}

    def status(self, **changes):
        status = {"docker": "29.9", "local": self.LOCAL, "remote": self.REMOTE, "update": True,
                  "gpu": False, "gpu_reason": "no NVIDIA GPU found on this computer",
                  "local_gpu": None, "remote_gpu": None, "update_gpu": False}
        status.update(changes)
        return status

    def test_a_newer_version_is_offered_not_imposed(self):
        d = S5.ODMSelectionDialog()
        d._on_engine_status(self.status())
        self.assertIn("3.6.2", d.engine_status_label.text())
        self.assertIn("3.7.0", d.engine_status_label.text())
        self.assertFalse(d.update_check.isHidden())
        self.assertFalse(d.selected_update_image())
        d.update_check.setChecked(True)
        self.assertTrue(d.selected_update_image())
        self.assertIn("updated", d.engine_description())

    def test_up_to_date_no_update_offered(self):
        d = S5.ODMSelectionDialog()
        d._on_engine_status(self.status(update=False, remote=dict(self.REMOTE, digest="sha256:old")))
        self.assertTrue(d.update_check.isHidden())
        self.assertIn("newest version", d.engine_status_label.text())

    def test_no_gpu_disabled_with_the_reason(self):
        d = S5.ODMSelectionDialog()
        d._on_engine_status(self.status())
        self.assertFalse(d.gpu_check.isEnabled())
        self.assertFalse(d.selected_use_gpu())
        self.assertIn("no NVIDIA GPU", d.engine_status_label.text())

    def test_gpu_checked_when_docker_can_use_it(self):
        d = S5.ODMSelectionDialog()
        d._on_engine_status(self.status(gpu=True, gpu_reason="NVIDIA GPU available to Docker"))
        self.assertTrue(d.selected_use_gpu())
        # the GPU image is not downloaded yet: said, no update of the CPU image offered
        self.assertIn("GPU version", d.engine_status_label.text())
        self.assertTrue(d.update_check.isHidden())
        d.gpu_check.setChecked(False)
        self.assertFalse(d.update_check.isHidden())

    def test_docker_off(self):
        d = S5.ODMSelectionDialog()
        d._on_engine_status({"docker": None, "gpu": False, "gpu_reason": "Docker is not running"})
        self.assertIn("Docker is not running", d.engine_status_label.text())
        self.assertFalse(d.selected_use_gpu())
        self.assertFalse(d.selected_update_image())

    def test_worker_passes_gpu_and_update_to_odm(self):
        worker = S5.ODMRunWorker(Path("/mission"), use_gpu=True, update_image=True)
        with mock.patch.object(S5, "run_odm", return_value={}) as run:
            worker.run()
        self.assertTrue(run.call_args.kwargs["use_gpu"])
        self.assertTrue(run.call_args.kwargs["update_image"])


if __name__ == "__main__":
    unittest.main()
