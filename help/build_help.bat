@echo off
REM Met a jour images_light puis compile les deux PDF :
REM   irdrone_help.pdf        : version imprimable (images haute resolution)
REM   irdrone_help_light.pdf  : version legere pour l'aide du logiciel (images_light)
setlocal
cd /d "%~dp0"

set "PY=C:\Users\Alain\miniforge3\envs\py39_clean\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" make_images_light.py

echo === Version imprimable ===
pdflatex -interaction=nonstopmode irdrone_help.tex >nul
pdflatex -interaction=nonstopmode irdrone_help.tex | findstr /b "! Output"

echo === Version legere ===
pdflatex -interaction=nonstopmode -jobname=irdrone_help_light "\def\IRDlight{1}\input{irdrone_help.tex}" >nul
pdflatex -interaction=nonstopmode -jobname=irdrone_help_light "\def\IRDlight{1}\input{irdrone_help.tex}" | findstr /b "! Output"

echo.
pause
