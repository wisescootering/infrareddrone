"""Gimbal / flight angles read from the ExifTool output of a DJI image."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from irdrone.process import get_gimbal_info  # noqa: E402

# Excerpt of `exiftool DJI_0001.DNG` with ExifTool >= 12.7x, which also decodes the
# "Gimbal Degree" / "Flight Degree" maker notes (three angles in 1/10 degree).
EXIFTOOL_OUTPUT = """\
Camera Model Name               : FC3170
Gimbal Roll Degree              : +0.00
Gimbal Yaw Degree               : +70.20
Gimbal Pitch Degree             : -89.90
Flight Roll Degree              : -5.30
Flight Yaw Degree               : +43.90
Flight Pitch Degree             : +2.70
Gimbal Degree                   : 702,-899,0
Flight Degree                   : 439,27,-53
"""


class GimbalInfoTest(unittest.TestCase):
    def test_reads_angles_and_ignores_combined_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "DJI_0001.DNG"
            image.write_bytes(b"")
            result = subprocess.CompletedProcess([], 0, stdout=EXIFTOOL_OUTPUT, stderr="")
            with mock.patch("irdrone.process.subprocess.run", return_value=result):
                info = get_gimbal_info(image)
            self.assertEqual(info, {
                "Gimbal Roll": 0.0, "Gimbal Yaw": 70.2, "Gimbal Pitch": -89.9,
                "Flight Roll": -5.3, "Flight Yaw": 43.9, "Flight Pitch": 2.7,
            })
            # Cached next to the image for the next call.
            self.assertTrue(image.with_suffix(".exif").is_file())


if __name__ == "__main__":
    unittest.main()
