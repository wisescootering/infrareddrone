# -*- coding: utf-8 -*-
"""Read image metadata with ExifTool, whatever the characters of the path.

On Windows, ExifTool receives its command line in the ANSI code page and
prints file names it cannot represent as "?": a folder named "Démo Florine"
came back as "D?mo Florine" in the ``Directory`` tag, and every path rebuilt
from it pointed nowhere. Here the file name goes through a UTF-8 argument
file read on stdin (``-@ -``) with ``-charset filename=utf8``, the output is
decoded as UTF-8, and ``FileName`` / ``Directory`` are replaced by the path
Python already knows, so they are always exact.

Kept free of heavy imports: used by the wizard and the processing scripts.
"""

import json
import subprocess
from pathlib import Path

# Options for ExifTool to read and write file names in UTF-8 (Windows).
UTF8_FILENAME_OPTIONS = ("-charset", "filename=utf8")


def read_exiftool_json(exiftool_path, image_path, *options) -> dict:
    """Metadata of ``image_path`` as returned by ``exiftool -json [options]``.

    Raises RuntimeError when ExifTool fails or returns nothing.
    """
    image_path = Path(image_path)
    arguments = ["-json", *options, str(image_path)]
    result = subprocess.run(
        [str(exiftool_path), *UTF8_FILENAME_OPTIONS, "-@", "-"],
        input="\n".join(arguments) + "\n",
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ExifTool could not read metadata from {image_path}: "
            f"{result.stderr.strip()}"
        )
    metadata_list = json.loads(result.stdout) if result.stdout.strip() else []
    if not metadata_list or not isinstance(metadata_list[0], dict):
        raise RuntimeError(f"ExifTool returned no metadata for {image_path}")
    metadata = metadata_list[0]
    metadata["FileName"] = image_path.name
    metadata["Directory"] = str(image_path.parent)
    return metadata
