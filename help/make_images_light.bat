@echo off
REM Met a jour help\images_light (images reduites) a partir de help\images.
REM Un raccourci de ce fichier peut etre place sur le bureau.
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Alain\miniforge3\envs\py39_clean\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" make_images_light.py %*
echo.
pause
