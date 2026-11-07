"""QGIS style (.qml) written for the contour lines of the maps."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "irdrone_wizard"))
import IRD_Interactive_GeoRef as GeoRef  # noqa: E402

# style: (font size of the 10 m labels, font size of the 1 m labels)
FONT_SIZES = {"IGN": ("12", "9"), "SOFT": ("10", "8")}


@pytest.mark.parametrize("style", sorted(FONT_SIZES))
def test_major_and_minor_labels_use_their_own_font_size(tmp_path, style):
    qml = tmp_path / "contours.qml"
    GeoRef.generate_qml_style_qgis(qml, style=style, label_on_line=True)
    rules = ET.parse(qml).getroot().find("labeling").find("rules")
    sizes = {rule.get("key"): rule.find("settings/text-style").get("fontSize") for rule in rules}
    assert (sizes["label_10m"], sizes["label_1m"]) == FONT_SIZES[style]
