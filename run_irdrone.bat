@echo off
setlocal

set "CONDA_ROOT=%USERPROFILE%\miniforge3"
set "CONDA_BAT=%CONDA_ROOT%\condabin\conda.bat"
set "CONDA_ENV=%CONDA_ROOT%\envs\py39_clean"
set "MAIN_SCRIPT=%~dp0irdrone Interactive\IRD_Interactive_Main.py"

if not exist "%CONDA_BAT%" (
    echo ERROR: Conda was not found at "%CONDA_BAT%".
    echo Edit CONDA_ROOT in run_irdrone.bat to match your Miniforge installation.
    pause
    exit /b 1
)

if not exist "%CONDA_ENV%\python.exe" (
    echo ERROR: The py39_clean environment was not found at "%CONDA_ENV%".
    pause
    exit /b 1
)

if not exist "%MAIN_SCRIPT%" (
    echo ERROR: IRD_Interactive_Main.py was not found at "%MAIN_SCRIPT%".
    pause
    exit /b 1
)

call "%CONDA_BAT%" activate "%CONDA_ENV%"
if errorlevel 1 (
    echo ERROR: Could not activate the py39_clean environment.
    pause
    exit /b 1
)

pushd "%~dp0"
python "%MAIN_SCRIPT%" %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd

if not "%APP_EXIT_CODE%"=="0" (
    echo IRDrone exited with code %APP_EXIT_CODE%.
    pause
)

exit /b %APP_EXIT_CODE%
