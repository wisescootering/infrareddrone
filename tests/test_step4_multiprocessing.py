import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import automatic_registration
import irdrone.process as image_process


class Step4MultiprocessingTests(unittest.TestCase):
    def test_worker_count_uses_physical_cores(self):
        with patch.object(automatic_registration.psutil, "cpu_count", return_value=4) as cpu_count:
            self.assertEqual(automatic_registration.available_alignment_workers(), 4)

        cpu_count.assert_called_once_with(logical=False)

    def test_worker_count_falls_back_to_one_core(self):
        with patch.object(automatic_registration.psutil, "cpu_count", return_value=None):
            self.assertEqual(automatic_registration.available_alignment_workers(), 1)

    def test_single_worker_uses_sequential_pipeline(self):
        with patch.object(
            automatic_registration, "_process_raw_pairs_serial", return_value=["motion"]
        ) as sequential:
            result = automatic_registration.process_raw_pairs(
                [("VIS_0001.dng", "NIR_0001.dng")],
                cals={},
                max_workers=1,
            )

        self.assertEqual(result, ["motion"])
        sequential.assert_called_once()

    def test_parallel_worker_count_is_capped_by_pair_count(self):
        with tempfile.TemporaryDirectory() as output_folder:
            progress = []
            with patch(
                "automatic_registration.ProcessPoolExecutor"
            ) as executor_type:
                executor = executor_type.return_value.__enter__.return_value
                executor.submit.side_effect = (
                    lambda function, task: self._completed_future(function(task))
                )
                with patch.object(
                    automatic_registration,
                    "_process_single_pair_task",
                    side_effect=lambda task: (
                        task["index"],
                        task["pair"][0],
                        [f"motion-{task['index']}"],
                        None,
                    ),
                ):
                    result = automatic_registration.process_raw_pairs(
                        [
                            ("VIS_0001.dng", "NIR_0001.dng"),
                            ("VIS_0002.dng", "NIR_0002.dng"),
                        ],
                        cals={},
                        out_dir=output_folder,
                        max_workers=4,
                        progress_callback=lambda *args: progress.append(args),
                    )

        self.assertEqual(executor_type.call_args.kwargs["max_workers"], 2)
        self.assertEqual(result, ["motion-0", "motion-1"])
        self.assertEqual([entry[:2] for entry in progress], [(1, 2), (2, 2)])
        self.assertEqual(
            {entry[2] for entry in progress},
            {"VIS_0001.dng", "VIS_0002.dng"},
        )

    def test_parallel_waves_do_not_process_a_shared_nir_source_together(self):
        tasks = [
            {"index": 0, "pair": ("VIS_0001.dng", "NIR_shared.dng")},
            {"index": 1, "pair": ("VIS_0002.dng", "NIR_other.dng")},
            {"index": 2, "pair": ("VIS_0003.dng", "NIR_shared.dng")},
            {"index": 3, "pair": ("VIS_0004.dng", "NIR_last.dng")},
        ]

        waves = list(automatic_registration._alignment_task_waves(tasks, 2))

        self.assertEqual(
            [[task["index"] for task in wave] for wave in waves],
            [[0, 1], [2, 3]],
        )

    def test_unreadable_rawtherapee_proxy_is_regenerated(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "NIR_0001.dng"
            source.write_bytes(b"raw")
            proxy = Path(image_process.cached_tif(str(source)))
            proxy.write_bytes(b"incomplete TIFF")
            valid_image = np.zeros((2, 2, 3), dtype=np.uint16)

            def convert(command, check):
                self.assertFalse(check)
                proxy.write_bytes(b"regenerated TIFF")
                return type("Completed", (), {"returncode": 0})()

            with (
                patch(
                    "irdrone.process.cv2.imread",
                    side_effect=[None, valid_image],
                ),
                patch("irdrone.process.subprocess.run", side_effect=convert) as run,
            ):
                image, output_path = image_process.load_dng(str(source))

            self.assertEqual(output_path, str(proxy))
            self.assertEqual(image.shape, valid_image.shape)
            run.assert_called_once()

    @staticmethod
    def _completed_future(result):
        future = Future()
        future.set_result(result)
        return future

    def test_invalid_worker_count_is_rejected(self):
        for invalid_count in (0, -1, True):
            with self.subTest(invalid_count=invalid_count):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    automatic_registration.process_raw_pairs(
                        [("VIS_0001.dng", "NIR_0001.dng")],
                        cals={},
                        max_workers=invalid_count,
                    )


if __name__ == "__main__":
    unittest.main()
