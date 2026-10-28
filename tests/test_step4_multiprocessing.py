import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import automatic_registration


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
