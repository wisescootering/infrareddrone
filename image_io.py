# -*- coding: utf-8 -*-
"""cv2.imread / cv2.imwrite that accept any characters in the path.

On Windows OpenCV opens files through the ANSI API: a path with an accent
("G:\\Démo Florine\\...") makes cv2.imread return None and cv2.imwrite return
False without an error. Python opens the file (Unicode API) and OpenCV only
decodes / encodes the bytes. Same signatures and return values as OpenCV.
"""

from pathlib import Path

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    """Like cv2.imread: the image, or None if it cannot be read."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path, image, params=None) -> bool:
    """Like cv2.imwrite: True if the image was written."""
    extension = Path(path).suffix
    ok, encoded = cv2.imencode(extension, image, params if params is not None else [])
    if not ok:
        return False
    encoded.tofile(str(path))
    return True
