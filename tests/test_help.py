import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "irdrone_wizard"))

import IRD_Interactive_help as Help


class HelpTests(unittest.TestCase):
    def test_opens_the_committed_light_manual(self):
        self.assertEqual(Help.HELP_PDF, ROOT / "help" / "irdrone_help_light.pdf")
        self.assertTrue(Help.HELP_PDF.is_file())

    def test_url_points_to_label_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            aux = Path(temporary) / "irdrone_help_light.aux"
            aux.write_text("\\newlabel{ch:step4}{{4}{21}{Step 4}{chapter.4}{}}\n", encoding="utf-8")
            url = Help.help_url("ch:step4", Help.HELP_PDF, aux)
        self.assertTrue(url.endswith("irdrone_help_light.pdf#page=22"), url)

    def test_falls_back_to_default_application(self):
        with patch.object(Help, "_open_with_acrobat", return_value=False), \
                patch.object(Help.webbrowser, "open", return_value=False), \
                patch.object(Help, "open_with_default_app", return_value=True) as opener:
            self.assertTrue(Help.show_help("ch:step1"))
        opener.assert_called_once_with(Help.HELP_PDF)


if __name__ == "__main__":
    unittest.main()
