@echo off
rem Launch the IRDrone wizard (irdrone_wizard\IRD_Interactive_Main.py) on Windows.
rem Linux / macOS: use irdrone_wizard.sh instead.
rem Python is chosen by bat_helpers\find_python.bat (IRDRONE_PYTHON, .venv,
rem conda environment IRDRONE_CONDA_ENV = py39_clean by default, then the PATH).
setlocal

set "ROOT=%~dp0"
set "MAIN_SCRIPT=%ROOT%irdrone_wizard\IRD_Interactive_Main.py"

if not exist "%MAIN_SCRIPT%" (
    echo ERROR: IRD_Interactive_Main.py was not found at "%MAIN_SCRIPT%".
    pause
    exit /b 1
)

call "%ROOT%bat_helpers\find_python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

pushd "%ROOT%"
"%PYTHON%" "%MAIN_SCRIPT%" %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd

if not "%APP_EXIT_CODE%"=="0" (
    echo IRDrone exited with code %APP_EXIT_CODE%.
    pause
)

exit /b %APP_EXIT_CODE%
