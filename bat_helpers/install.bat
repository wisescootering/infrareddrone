cd ..
call conda env create --file environment.yml python=3.9
pause
@ECHO OFF
SETLOCAL
if exist "C:\Program Files\Mozilla Firefox\firefox.exe" start "Firefox!" "C:\Program Files\Mozilla Firefox\firefox.exe" "https://rawtherapee.com/shared/builds/windows/RawTherapee_5.8.exe"
echo Firefox started Download https://rawtherapee.com/shared/builds/windows/RawTherapee_5.8.exe .
pause


if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" start "Edge!" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"  "https://rawtherapee.com/shared/builds/windows/RawTherapee_5.8.exe"
echo Edge started
pause
GOTO :EOF