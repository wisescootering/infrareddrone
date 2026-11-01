# -*- coding: utf-8 -*-
"""
Contextual help for IRDrone.

The user manual is written in LaTeX (``help/irdrone_help.tex``) and compiled to
``help/irdrone_help.pdf``. Every chapter and every button section of the manual has
a LaTeX label (``ch:step1``, ``btn:step4_run_alignment``, ...). During compilation
LaTeX writes the page of each label in ``help/irdrone_help.aux``. The help buttons
call :func:`show_help` with a label: the PDF is opened at the page of that label.

Usage
-----
    import IRD_Interactive_help as Help
    Help.show_help("ch:step2")

Notes
-----
* The page is passed with the ``#page=N`` fragment, understood by the PDF viewer
  of the web browsers (Edge, Chrome, Firefox) and by Acrobat. If the PDF is opened
  with a viewer that ignores it, the document opens on its first page.
* Without the ``.aux`` file, or with an unknown label, the PDF opens on page 1.
"""

import os
import re
import webbrowser
from pathlib import Path
from typing import Dict, Optional

HELP_DIR = Path(__file__).resolve().parent.parent / "help"
HELP_PDF = HELP_DIR / "irdrone_help.pdf"
HELP_AUX = HELP_DIR / "irdrone_help.aux"

# The title page (\maketitle) is numbered 0 by LaTeX: the physical page of the PDF viewer
# is the printed page + 1. Set to 0 if the title page is removed from the manual.
PAGE_OFFSET = 1

# \newlabel{<label>}{{<number>}{<page>}{...}...}
_LABEL_PATTERN = re.compile(r"\\newlabel\{([^}]+)\}\{\{[^}]*\}\{(\d+)\}")


def read_label_pages(aux_path: Path = HELP_AUX) -> Dict[str, int]:
    """
    Read the page of every LaTeX label from the ``.aux`` file of the manual.

    Parameters
    ----------
    aux_path : Path, optional
        Path of the ``.aux`` file written by LaTeX.

    Returns
    -------
    Dict[str, int]
        Mapping ``label -> page number`` (empty if the file is missing).
    """
    try:
        text = Path(aux_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {label: int(page) + PAGE_OFFSET for label, page in _LABEL_PATTERN.findall(text)}


def help_url(label: Optional[str] = None,
             pdf_path: Path = HELP_PDF,
             aux_path: Path = HELP_AUX) -> str:
    """
    Build the URL of the manual, positioned on the page of ``label``.

    Parameters
    ----------
    label : str, optional
        LaTeX label (e.g. ``"ch:step1"``). None or unknown: first page.
    pdf_path : Path, optional
        Path of the compiled manual.
    aux_path : Path, optional
        Path of the ``.aux`` file written by LaTeX.

    Returns
    -------
    str
        ``file:///...irdrone_help.pdf#page=N``
    """
    url = Path(pdf_path).resolve().as_uri()
    page = read_label_pages(aux_path).get(label) if label else None
    return f"{url}#page={page}" if page else url


def show_help(label: Optional[str] = None, parent=None) -> bool:
    """
    Open the user manual at the section linked to ``label``.

    Parameters
    ----------
    label : str, optional
        LaTeX label of the chapter or button section (e.g. ``"btn:step4_run_alignment"``).
    parent : QWidget, optional
        Parent of the message box shown if the manual cannot be opened.

    Returns
    -------
    bool
        True if the manual has been opened, False otherwise.
    """
    if not HELP_PDF.exists():
        _warn(parent, f"The user manual was not found:\n{HELP_PDF}\n\n"
                      "Compile help/irdrone_help.tex with pdflatex (twice).")
        return False
    page = read_label_pages().get(label) if label else None
    try:
        if page and _open_with_acrobat(HELP_PDF, page):
            return True
        url = help_url(label)
        if webbrowser.open(url):
            return True
        os.startfile(str(HELP_PDF))  # no page positioning with this fallback
        return True
    except Exception as exc:
        _warn(parent, f"Unable to open the user manual:\n{exc}")
        return False


def _default_pdf_viewer() -> Optional[str]:
    """
    Return the executable registered as the default PDF viewer (Windows only).

    Returns
    -------
    str or None
        Path of the executable, None if it cannot be determined.
    """
    try:
        import winreg
        try:
            key = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                   r"\FileExts\.pdf\UserChoice")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                prog_id = winreg.QueryValueEx(k, "ProgId")[0]
        except OSError:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".pdf") as k:
                prog_id = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            prog_id + r"\shell\open\command") as k:
            command = winreg.QueryValueEx(k, "")[0]
        match = re.match(r'\s*"([^"]+)"|\s*(\S+)', command)
        return (match.group(1) or match.group(2)) if match else None
    except Exception:
        return None


def _open_with_acrobat(pdf_path: Path, page: int) -> bool:
    """
    Open the PDF at ``page`` if the default viewer is Adobe Acrobat/Reader.

    Acrobat ignores the ``#page=N`` URL fragment, but accepts ``/A page=N`` on its
    command line.

    Returns
    -------
    bool
        True if Acrobat was started, False if it is not the default viewer.
    """
    exe = _default_pdf_viewer()
    if not exe or os.path.basename(exe).lower() not in ("acrobat.exe", "acrord32.exe"):
        return False
    import subprocess
    subprocess.Popen([exe, "/A", f"page={page}", str(pdf_path)])
    return True


def _warn(parent, message: str) -> None:
    """Show a warning box (printed on the console if Qt is not available)."""
    try:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "IRDrone help", message)
    except Exception:
        print(message)
