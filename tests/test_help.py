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
        with patch.object(Help, "online", return_value=False), \
                patch.object(Help, "_open_with_acrobat", return_value=False), \
                patch.object(Help.webbrowser, "open", return_value=False), \
                patch.object(Help, "open_with_default_app", return_value=True) as opener:
            self.assertTrue(Help.show_help("ch:step1"))
        opener.assert_called_once_with(Help.HELP_PDF)



class OnlineHelpTests(unittest.TestCase):
    def setUp(self):
        Help._online_cache.update(at=-1e9, value=False)

    def test_contextual_help_opens_the_web_manual_at_the_label(self):
        with patch.object(Help, "online", return_value=True), \
                patch.object(Help.webbrowser, "open", return_value=True) as browser:
            self.assertTrue(Help.show_help("btn:step4_stop"))
        browser.assert_called_once_with("https://wisescootering.github.io/infrareddrone/manual/#btn:step4_stop")

    def test_whole_manual_is_the_pdf_built_by_github_actions(self):
        with patch.object(Help, "online", return_value=True), \
                patch.object(Help.webbrowser, "open", return_value=True) as browser:
            self.assertTrue(Help.show_manual())
        browser.assert_called_once_with(Help.PDF_URL)
        self.assertIn("releases/download/help-latest/", Help.PDF_URL)

    def test_offline_uses_the_local_pdf(self):
        with patch.object(Help.socket, "create_connection", side_effect=OSError("offline")), \
                patch.object(Help, "show_local_pdf", return_value=True) as local:
            self.assertTrue(Help.show_help("btn:step4_stop"))
            self.assertTrue(Help.show_manual())
        self.assertEqual([c.args[0] for c in local.call_args_list], ["btn:step4_stop", None])

    def test_forced_offline(self):
        with patch.dict(Help.os.environ, {"IRDRONE_HELP_OFFLINE": "1"}), \
                patch.object(Help.socket, "create_connection") as connect:
            self.assertFalse(Help.online())
        connect.assert_not_called()

    def test_reachability_is_checked_once_a_minute(self):
        with patch.dict(Help.os.environ, {"IRDRONE_HELP_OFFLINE": ""}), \
                patch.object(Help.socket, "create_connection") as connect:
            self.assertTrue(Help.online())
            self.assertTrue(Help.online())
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
