@echo off
setlocal
title STEP2NC1 - Installation check
echo STEP2NC1 installation check. Please keep this window open.
pushd "%~dp0"
if errorlevel 1 goto location_error
set "step2nc_log=%~dp0validation-log.txt"
>"%step2nc_log%" echo STEP2NC1 installation check %DATE% %TIME%
if errorlevel 1 set "step2nc_log=%TEMP%\STEP2NC1-validation-log.txt"
>"%step2nc_log%" echo STEP2NC1 installation check %DATE% %TIME%
echo Log: "%step2nc_log%"
if exist "STEP2NC1-cli.exe" goto packaged
if not exist "main.py" goto missing_files
if not exist "Setup-Windows.bat" goto missing_files
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import cadquery, tkinter" >>"%step2nc_log%" 2>&1
if not errorlevel 1 goto source
:setup
echo Installing dependencies. First setup needs internet and may take several minutes.
call Setup-Windows.bat --unattended >>"%step2nc_log%" 2>&1
if errorlevel 1 goto failed
:source
echo Running conversion and desktop checks. A test window may open briefly.
".venv\Scripts\python.exe" -u main.py doctor --gui --output installation-check.json >>"%step2nc_log%" 2>&1
set "step2nc_exit=%ERRORLEVEL%"
goto results
:packaged
echo Running packaged application checks. A test window may open briefly.
"STEP2NC1-cli.exe" doctor --gui --output installation-check.json >>"%step2nc_log%" 2>&1
set "step2nc_exit=%ERRORLEVEL%"
goto results
:missing_files
>>"%step2nc_log%" echo Application files are missing. Use Extract All on the ZIP and keep the entire folder together.
:failed
set "step2nc_exit=1"
:results
type "%step2nc_log%"
echo.
echo Check exit code: %step2nc_exit%
echo Send validation-log.txt and installation-check.json if it was generated in this run.
echo Log location: "%step2nc_log%"
popd
pause
exit /b %step2nc_exit%
:location_error
echo Cannot open the application folder. Extract the ZIP to a local writable folder first.
pause
exit /b 1
