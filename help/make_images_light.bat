@echo off
REM Met a jour help\images_light (images reduites) a partir de help\images.
REM Un raccourci de ce fichier peut etre place sur le bureau.
setlocal
cd /d "%~dp0"

call ..\bat_helpers\find_python.bat
if errorlevel 1 goto end
set "PY=%PYTHON%"

"%PY%" make_images_light.py %*
echo.
:end
pause
