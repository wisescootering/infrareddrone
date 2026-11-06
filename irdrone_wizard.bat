@echo off
rem Launch the IRDrone wizard (irdrone_wizard\IRD_Interactive_Main.py) on Windows.
rem Linux / macOS: use irdrone_wizard.sh instead.
rem
rem Python is searched in this order:
rem   1. IRDRONE_PYTHON          full path to a python.exe (set it to force one)
rem   2. .venv\Scripts\python.exe next to this file
rem   3. the conda environment IRDRONE_CONDA_ENV (default py39_clean) in
rem      %USERPROFILE%\miniforge3, miniconda3 or anaconda3, activated first
rem   4. python found on the PATH
setlocal

set "ROOT=%~dp0"
set "MAIN_SCRIPT=%ROOT%irdrone_wizard\IRD_Interactive_Main.py"
if not defined IRDRONE_CONDA_ENV set "IRDRONE_CONDA_ENV=py39_clean"

if not exist "%MAIN_SCRIPT%" (
    echo ERROR: IRD_Interactive_Main.py was not found at "%MAIN_SCRIPT%".
    pause
    exit /b 1
)

if defined IRDRONE_PYTHON goto use_irdrone_python
if exist "%ROOT%.venv\Scripts\python.exe" goto use_venv

for %%D in (miniforge3 miniconda3 anaconda3) do (
    if exist "%USERPROFILE%\%%D\envs\%IRDRONE_CONDA_ENV%\python.exe" (
        set "CONDA_ROOT=%USERPROFILE%\%%D"
        goto use_conda
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=python"
    echo WARNING: no .venv or conda environment "%IRDRONE_CONDA_ENV%" found, using python from the PATH.
    goto run
)

echo ERROR: no Python environment found for IRDrone.
echo Create the conda environment (bat_helpers\install.bat), or set IRDRONE_PYTHON
echo to the full path of the python.exe to use.
pause
exit /b 1

:use_irdrone_python
set "PYTHON=%IRDRONE_PYTHON%"
goto run

:use_venv
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
goto run

:use_conda
rem Activating the environment puts its DLL folders (GDAL, Qt...) on the PATH.
call "%CONDA_ROOT%\condabin\conda.bat" activate "%CONDA_ROOT%\envs\%IRDRONE_CONDA_ENV%"
if errorlevel 1 (
    echo ERROR: Could not activate the conda environment "%IRDRONE_CONDA_ENV%".
    pause
    exit /b 1
)
set "PYTHON=python"
goto run

:run
pushd "%ROOT%"
"%PYTHON%" "%MAIN_SCRIPT%" %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd

if not "%APP_EXIT_CODE%"=="0" (
    echo IRDrone exited with code %APP_EXIT_CODE%.
    pause
)

exit /b %APP_EXIT_CODE%
