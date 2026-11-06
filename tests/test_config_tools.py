"""External tool lookup in config.py: environment variable, usual place, then PATH."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def make_executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class FindToolTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_environment_variable_wins(self):
        forced = make_executable(self.folder / "forced")
        usual = make_executable(self.folder / "usual")
        with mock.patch.dict(os.environ, {"MY_TOOL": str(forced)}):
            self.assertEqual(config._find_tool("MY_TOOL", [usual], ["tool"]), (str(forced), True))

    def test_environment_variable_to_a_missing_file_is_reported(self):
        usual = make_executable(self.folder / "usual")
        with mock.patch.dict(os.environ, {"MY_TOOL": str(self.folder / "nope")}):
            self.assertEqual(config._find_tool("MY_TOOL", [usual], ["tool"]),
                             (str(self.folder / "nope"), False))

    def test_usual_location_before_path(self):
        usual = make_executable(self.folder / "usual")
        on_path = self.folder / "bin"
        on_path.mkdir()
        make_executable(on_path / "tool")
        with mock.patch.dict(os.environ, {"PATH": str(on_path)}):
            os.environ.pop("MY_TOOL", None)
            self.assertEqual(config._find_tool("MY_TOOL", [usual], ["tool"]), (str(usual), True))

    def test_falls_back_to_path(self):
        on_path = self.folder / "bin"
        on_path.mkdir()
        tool = make_executable(on_path / "tool")
        with mock.patch.dict(os.environ, {"PATH": str(on_path)}):
            os.environ.pop("MY_TOOL", None)
            self.assertEqual(config._find_tool("MY_TOOL", [self.folder / "usual"], ["tool"]),
                             (str(tool), True))

    def test_not_found_keeps_the_default(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.folder)}):
            os.environ.pop("MY_TOOL", None)
            self.assertEqual(config._find_tool("MY_TOOL", [self.folder / "usual"], ["tool"]),
                             (str(self.folder / "usual"), False))


class RequireToolTest(unittest.TestCase):
    def test_missing_tool_raises_with_the_variable_name(self):
        missing = [("RawTherapee", "RAWTHERAPEEPATH", "/nope", "required", "https://rawtherapee.com")]
        with mock.patch.object(config, "missing_tools", return_value=missing):
            with self.assertRaisesRegex(FileNotFoundError, "RAWTHERAPEEPATH"):
                config.require_tool("RAWTHERAPEEPATH")
            self.assertIn("RAWTHERAPEEPATH", config.missing_tools_message())

    def test_found_tool_returns_its_path(self):
        with mock.patch.object(config, "missing_tools", return_value=[]):
            self.assertEqual(config.require_tool("EXIFTOOLPATH"), config.EXIFTOOLPATH)


if __name__ == "__main__":
    unittest.main()
