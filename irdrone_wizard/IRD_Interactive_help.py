# -*- coding: utf-8 -*-
"""
Contextual help for IRDrone.

The user manual is written in LaTeX (``help/irdrone_help.tex``) and compiled by
``help/build_help.bat`` into two PDFs: ``help/irdrone_help_light.pdf`` (low-resolution
images, committed, opened by the software) and ``help/irdrone_help.pdf`` (printable,
too large for GitHub, used only when the light version is missing). Every chapter and
every button section of the manual has a LaTeX label (``ch:step1``,
``btn:step4_run_alignment``, ...). During compilation LaTeX writes the page of each
label in the ``.aux`` file next to the PDF. The help buttons call :func:`show_help`
with a label: the PDF is opened at the page of that label.

Online first
------------
When the documentation website can be reached, the help is read online and is
always the latest one (in English):

* :func:`show_help` (``?`` buttons, F1 on a button) opens the
  web manual at the anchor of the label: ``https://wisescootering.github.io/infrareddrone/manual/#btn:step4_stop``.
  The web page is generated from ``help/irdrone_help_en.tex`` by ``website/manual.py``:
  every LaTeX label is an anchor of the page.
* :func:`show_manual` (``?`` of the main window) opens the PDF built by the "Build help PDF"
  GitHub Actions workflow (rolling ``help-latest`` release).

Offline (or with ``IRDRONE_HELP_OFFLINE=1``), both open the local PDF as below.

Usage
-----
    import IRD_Interactive_help as Help
    Help.show_help("ch:step2")
    Help.show_manual()

Buttons are documented with :func:`attach_help` (tooltip + F1 help).

Notes
-----
* The page is passed with the ``#page=N`` fragment, understood by the PDF viewer
  of the web browsers (Edge, Chrome, Firefox) and by Acrobat. If the PDF is opened
  with a viewer that ignores it, the document opens on its first page.
* Without the ``.aux`` file, or with an unknown label, the PDF opens on page 1.
"""

import os
import re
import socket
import time
import webbrowser
from pathlib import Path
from typing import Dict, Optional

HELP_DIR = Path(__file__).resolve().parent.parent / "help"
HELP_PDF_LIGHT = HELP_DIR / "irdrone_help_light.pdf"
HELP_PDF_FULL = HELP_DIR / "irdrone_help.pdf"
# Light version first (the one shipped with the software), printable one as fallback.
HELP_PDF = HELP_PDF_LIGHT if HELP_PDF_LIGHT.exists() or not HELP_PDF_FULL.exists() else HELP_PDF_FULL
# Both versions share the same layout: either .aux gives the right pages.
HELP_AUX = next(
    (aux for aux in (HELP_PDF.with_suffix(".aux"),
                     HELP_PDF_LIGHT.with_suffix(".aux"),
                     HELP_PDF_FULL.with_suffix(".aux")) if aux.exists()),
    HELP_PDF.with_suffix(".aux"),
)

# Online help (GitHub Pages site and the PDF built by GitHub Actions)
SITE_HOST = "wisescootering.github.io"
MANUAL_URL = f"https://{SITE_HOST}/infrareddrone/manual/"
PDF_URL = "https://github.com/wisescootering/infrareddrone/releases/download/help-latest/irdrone_help_en.pdf"
ONLINE_TIMEOUT_S = 1.5
_online_cache = {"at": -1e9, "value": False}


def online(timeout: float = ONLINE_TIMEOUT_S, max_age: float = 60.0) -> bool:
    """True if the documentation website can be reached (checked at most once a minute).

    ``IRDRONE_HELP_OFFLINE=1`` forces the local PDF.
    """
    if os.environ.get("IRDRONE_HELP_OFFLINE", "").strip() not in ("", "0"):
        return False
    now = time.monotonic()
    if now - _online_cache["at"] > max_age:
        try:
            with socket.create_connection((SITE_HOST, 443), timeout=timeout):
                value = True
        except OSError:
            value = False
        _online_cache.update(at=now, value=value)
    return _online_cache["value"]


def manual_url(label: Optional[str] = None) -> str:
    """Web manual, at the anchor of ``label`` (every LaTeX label is an anchor of the page)."""
    return f"{MANUAL_URL}#{label}" if label else MANUAL_URL


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
    if online():
        try:
            if webbrowser.open(manual_url(label)):
                return True
        except Exception:
            pass  # the local PDF below
    return show_local_pdf(label, parent)


def show_manual(parent=None) -> bool:
    """Open the whole manual: the PDF built by GitHub Actions, or the local PDF offline."""
    if online():
        try:
            if webbrowser.open(PDF_URL):
                return True
        except Exception:
            pass
    return show_local_pdf(None, parent)


def show_local_pdf(label: Optional[str] = None, parent=None) -> bool:
    """Open the PDF shipped with the software, at the page of ``label`` when known."""
    if not HELP_PDF.exists():
        _warn(parent, f"The user manual was not found:\n{HELP_PDF}\n\n"
                      "Compile it with help/build_help.bat.")
        return False
    page = read_label_pages().get(label) if label else None
    try:
        if page and _open_with_acrobat(HELP_PDF, page):
            return True
        url = help_url(label)
        if webbrowser.open(url):
            return True
        return open_with_default_app(HELP_PDF)  # no page positioning with this fallback
    except Exception as exc:
        _warn(parent, f"Unable to open the user manual:\n{exc}")
        return False


def open_with_default_app(path) -> bool:
    """Open a file with the application associated to it (Windows, Linux, macOS).

    Returns False if no opener is available (no ``xdg-open`` on Linux).
    """
    if hasattr(os, "startfile"):  # Windows
        os.startfile(str(path))
        return True
    import shutil
    import subprocess
    import sys
    opener = shutil.which("open" if sys.platform == "darwin" else "xdg-open")
    if opener is None:
        return False
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


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


HELP_PROPERTY = "irdrone_help"     # Qt property holding the manual label of a widget
_f1_filter = None


def attach_help(widget, label: str, tooltip: str = "", parent=None) -> None:
    """
    Add a tooltip and the F1 help to a widget.

    F1 pressed while the mouse is over the widget (or while it has the keyboard
    focus) opens the manual at the section linked to ``label``.

    Parameters
    ----------
    widget : QWidget
        Button (or check box, ...) to document.
    label : str
        LaTeX label of the manual section (e.g. ``"btn:review_redo"``).
    tooltip : str, optional
        One-sentence description. A reminder of the F1 help is appended.
    parent : QWidget, optional
        Kept for compatibility (the message box of a failure goes to the active window).
    """
    if tooltip:
        widget.setToolTip(f"{tooltip}\n(F1: help on this button)")
    widget.setProperty(HELP_PROPERTY, label)
    install_f1_help()


def help_label_for(widget) -> Optional[str]:
    """Manual label of ``widget`` or of its closest parent in the same window, None if none."""
    while widget is not None:
        label = widget.property(HELP_PROPERTY)
        if label:
            return str(label)
        if widget.isWindow():
            return None
        widget = widget.parentWidget()
    return None


def help_on_f1() -> None:
    """
    F1: the manual at the widget under the mouse, else at the widget with the
    keyboard focus, else what the ``?`` button of the active window opens.
    """
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication

    window = QApplication.activeModalWidget() or QApplication.activeWindow()
    hovered = QApplication.widgetAt(QCursor.pos())
    label = None
    if hovered is not None and (window is None or hovered.window() is window):
        label = help_label_for(hovered)
    if label is None:
        label = help_label_for(QApplication.focusWidget())
    if label is not None:
        show_help(label, parent=window)
        return
    for name in ("btn_help", "help_button"):          # the ? button of the window
        button = getattr(window, name, None)
        if button is not None and button.isEnabled():
            button.click()
            return
    show_manual(parent=window)


def install_f1_help() -> None:
    """Install, once, the application-wide F1 key of the contextual help."""
    global _f1_filter
    if _f1_filter is not None:
        return
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeySequence, QShortcut
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    # A QShortcut, not an event filter on the application: a Python filter makes PyQt wrap every
    # QObject that receives an event, also the ones being destroyed, which crashed (segmentation fault).
    _f1_filter = QShortcut(QKeySequence(Qt.Key.Key_F1), app)
    _f1_filter.setContext(Qt.ShortcutContext.ApplicationShortcut)
    _f1_filter.setAutoRepeat(False)
    _f1_filter.activated.connect(help_on_f1)


def _warn(parent, message: str) -> None:
    """Show a warning box (printed on the console if Qt is not available)."""
    try:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "IRDrone help", message)
    except Exception:
        print(message)
