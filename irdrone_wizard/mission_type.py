# -*- coding: utf-8 -*-
"""
Type of a mission, chosen in Step 1:

    multispectral   the drone (visible, DNG) and the SJCam (infrared, RAW):
                    synchronised, aligned, mapped in four bands (red, green, blue, NIR)
    visible         the drone images only (DNG): no synchronisation (Step 3 is
                    not needed), the images are developed instead of aligned and
                    mapped in three bands (red, green, blue)

Stored in FlightAnalytics/mission_parameters.json under "mission type". A mission
without the key (every mission created before visible only missions existed)
is multispectral. No Qt here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

KEY = "mission type"
MULTISPECTRAL = "multispectral"
VISIBLE = "visible"
TYPES = (MULTISPECTRAL, VISIBLE)
LABELS = {MULTISPECTRAL: "Multispectral (visible + infrared)", VISIBLE: "Visible only (drone DNG)"}
# Steps a mission type does not need: shown as such on the step rail and jumped over
SKIPPED_STEPS = {MULTISPECTRAL: frozenset(), VISIBLE: frozenset({3})}
# Bands of the images given to OpenDroneMap (ImgIRdrone/imgMultispectral/IRD_XXXX_<n>.tif)
BAND_NAMES = {MULTISPECTRAL: ("red", "green", "blue", "nir"), VISIBLE: ("red", "green", "blue")}


def of_parameters(params: Optional[dict]) -> str:
    """Type of the mission described by mission_parameters (multispectral by default)."""
    value = (params or {}).get(KEY) if isinstance(params, dict) else None
    return value if value in TYPES else MULTISPECTRAL


def of_folder(folder) -> str:
    """Type of the mission in folder (multispectral when it cannot be read)."""
    if folder is None:
        return MULTISPECTRAL
    try:
        with open(Path(folder) / "FlightAnalytics" / "mission_parameters.json", encoding="utf-8") as f:
            return of_parameters(json.load(f))
    except (OSError, ValueError):
        return MULTISPECTRAL


def is_visible(mission) -> bool:
    """mission: its folder, or its mission_parameters dict."""
    kind = of_parameters(mission) if isinstance(mission, dict) else of_folder(mission)
    return kind == VISIBLE


def skipped_steps(mission) -> frozenset:
    """Steps the mission does not need (mission: folder or mission_parameters)."""
    kind = of_parameters(mission) if isinstance(mission, dict) else of_folder(mission)
    return SKIPPED_STEPS[kind]


def band_names(mission) -> tuple:
    """Bands given to OpenDroneMap (mission: folder or mission_parameters)."""
    kind = of_parameters(mission) if isinstance(mission, dict) else of_folder(mission)
    return BAND_NAMES[kind]
