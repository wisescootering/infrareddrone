@echo off
rem Align VIS / NIR image pairs chosen in a file dialog.
rem Python is chosen by bat_helpers\find_python.bat (see that file).
setlocal
cd /d "%~dp0.."
call bat_helpers\find_python.bat
if errorlevel 1 goto end
"%PYTHON%" automatic_registration.py --manual
:end
pause
