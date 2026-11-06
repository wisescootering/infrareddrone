@echo off
rem Find the Python to use for IRDrone and set the variable PYTHON.
rem Used with "call" by irdrone_wizard.bat, the other bat_helpers scripts and
rem help\*.bat, so that they all pick the same Python. No setlocal on purpose:
rem PYTHON and the conda activation must stay visible to the caller.
rem
rem Python is searched in this order:
rem   1. IRDRONE_PYTHON          full path to a python.exe (set it to force one)
rem   2. .venv\Scripts\python.exe at the repository root
rem   3. the conda environment IRDRONE_CONDA_ENV (default py39_clean, the name in
rem      environment.yml) in %USERPROFILE%\miniforge3, miniconda3 or anaconda3,
rem      activated first
rem   4. python found on the PATH
rem Exit code 1 (after printing why) when none is found.

set "IRDRONE_ROOT=%~dp0.."
if not defined IRDRONE_CONDA_ENV set "IRDRONE_CONDA_ENV=py39_clean"
set "PYTHON="

rem goto rather than ( ... ) blocks: a ")" in a path, as in "Program Files (x86)",
rem would end the block early.
if defined IRDRONE_PYTHON goto use_irdrone_python
if exist "%IRDRONE_ROOT%\.venv\Scripts\python.exe" goto use_venv

for %%D in (miniforge3 miniconda3 anaconda3) do (
    if exist "%USERPROFILE%\%%D\envs\%IRDRONE_CONDA_ENV%\python.exe" (
        set "IRDRONE_CONDA_ROOT=%USERPROFILE%\%%D"
        goto use_conda
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=python"
    echo WARNING: no .venv or conda environment "%IRDRONE_CONDA_ENV%" found, using python from the PATH.
    exit /b 0
)

echo ERROR: no Python environment found for IRDrone.
echo Run bat_helpers\install.bat to create .venv, or set IRDRONE_PYTHON
echo to the full path of the python.exe to use.
exit /b 1

:use_irdrone_python
set "PYTHON=%IRDRONE_PYTHON%"
exit /b 0

:use_venv
set "PYTHON=%IRDRONE_ROOT%\.venv\Scripts\python.exe"
exit /b 0

:use_conda
rem Activating the environment puts its DLL folders (GDAL, Qt...) on the PATH.
call "%IRDRONE_CONDA_ROOT%\condabin\conda.bat" activate "%IRDRONE_CONDA_ROOT%\envs\%IRDRONE_CONDA_ENV%"
if errorlevel 1 (
    echo ERROR: Could not activate the conda environment "%IRDRONE_CONDA_ENV%".
    exit /b 1
)
set "PYTHON=python"
exit /b 0
