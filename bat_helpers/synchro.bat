@echo off
rem Compute the VIS / NIR time synchronization from the ArUco target images.
rem Python is chosen by bat_helpers\find_python.bat (see that file).
setlocal
cd /d "%~dp0.."
call bat_helpers\find_python.bat
if errorlevel 1 goto end
"%PYTHON%" synchronization/synchro_by_aruco.py --clean-proxy
:end
pause
