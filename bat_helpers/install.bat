@echo off
rem Set up IRDrone on Windows in a virtual environment at .venv\ (the one
rem irdrone_wizard.bat picks up first). Same as setup.sh on Linux / macOS.
rem
rem Uses uv when it is installed (fast, downloads the Python version itself:
rem https://docs.astral.sh/uv/), otherwise the "py" launcher or python + venv + pip.
rem Run it again to update the environment; delete .venv to start from scratch.
rem
rem Environment variables:
rem   IRDRONE_PYTHON_VERSION   Python version (default 3.12)
setlocal

set "ROOT=%~dp0.."
set "VENV=%ROOT%\.venv"
set "VENV_PYTHON=%VENV%\Scripts\python.exe"
set "REQUIREMENTS=%ROOT%\requirements.txt"
if not defined IRDRONE_PYTHON_VERSION set "IRDRONE_PYTHON_VERSION=3.12"

where uv >nul 2>nul
if errorlevel 1 goto use_pip

echo Using uv
if not exist "%VENV_PYTHON%" (
    uv venv --python %IRDRONE_PYTHON_VERSION% "%VENV%" || goto failed
)
uv pip install --python "%VENV_PYTHON%" -r "%REQUIREMENTS%" || goto failed
goto check

:use_pip
echo uv not found, using python -m venv + pip
echo (install uv for a faster setup: https://docs.astral.sh/uv/)
if exist "%VENV_PYTHON%" goto pip_install
where py >nul 2>nul
if not errorlevel 1 (
    py -%IRDRONE_PYTHON_VERSION% -m venv "%VENV%" || goto failed
    goto pip_install
)
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found. Install uv or Python from https://www.python.org
    goto failed
)
python -m venv "%VENV%" || goto failed

:pip_install
"%VENV_PYTHON%" -m pip install --upgrade pip || goto failed
"%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%" || goto failed

:check
echo.
echo Checking the installation...
"%VENV_PYTHON%" -c "import numpy, scipy, matplotlib, cv2, skimage, numba, pandas, openpyxl, piexif, exifread, rawpy, rasterio, geopy, requests, psutil, qrcode, tkinter, PyQt6.QtWidgets; print('Python packages OK')" || goto failed
pushd "%ROOT%"
"%VENV_PYTHON%" -c "import config; print(config.missing_tools_message() or 'External tools OK')"
popd
echo.
echo Done. Launch the wizard with irdrone_wizard.bat
if not defined CI pause
exit /b 0

:failed
echo.
echo ERROR: the installation failed, see the messages above.
if not defined CI pause
exit /b 1
