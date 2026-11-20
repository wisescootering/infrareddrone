@echo off
rem IRDrone diagnostic report: a zip describing the installation (Python,
rem packages, external tools) and, for a mission, checking its
rem synchronisation images. Send the zip to the IRDrone developers.
rem
rem Double-click: installation only. Drop a mission folder (FLY-...) on this
rem file, or give it as argument: the mission is checked too (not modified).
rem Same as the button "Create a diagnostic report..." of the wizard options.
setlocal

set "ROOT=%~dp0"
call "%ROOT%bat_helpers\find_python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

rem UTF-8 console: accented folder names are printed as they are
chcp 65001 >nul
pushd "%ROOT%"
"%PYTHON%" "%ROOT%diagnostic.py" %*
set "CODE=%ERRORLEVEL%"
popd
echo.
pause
exit /b %CODE%
