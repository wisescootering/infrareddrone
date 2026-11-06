@echo off
rem Process the mission described by config.json (file dialog) and prepare the ODM outputs.
rem Python is chosen by bat_helpers\find_python.bat (see that file).
setlocal
cd /d "%~dp0.."
call bat_helpers\find_python.bat
if errorlevel 1 goto end
"%PYTHON%" run.py --clean-proxy --odm-multispectral --selection best-mapping
:end
pause
