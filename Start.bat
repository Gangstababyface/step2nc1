@echo off
setlocal
title STEP2NC1 - Startup
echo STEP2NC1 startup. Please keep this window open.
pushd "%~dp0"
if errorlevel 1 goto location_error
set "step2nc_log=%~dp0startup-log.txt"
>"%step2nc_log%" echo STEP2NC1 startup %DATE% %TIME%
if errorlevel 1 set "step2nc_log=%TEMP%\STEP2NC1-startup-log.txt"
>"%step2nc_log%" echo STEP2NC1 startup %DATE% %TIME%
echo Log: "%step2nc_log%"
if not exist "main.py" goto missing_files
if not exist "Setup-Windows.bat" goto missing_files
echo Checking Python and CAD dependencies...
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import cadquery, tkinter" >>"%step2nc_log%" 2>&1
if not errorlevel 1 goto launch
:setup
echo Installing dependencies. First setup needs internet and may take several minutes.
call Setup-Windows.bat --unattended >>"%step2nc_log%" 2>&1
if errorlevel 1 goto failed
:launch
echo Opening STEP2NC1...
".venv\Scripts\python.exe" -u main.py >>"%step2nc_log%" 2>&1
set "step2nc_exit=%ERRORLEVEL%"
if not "%step2nc_exit%"=="0" goto failed
echo STEP2NC1 has closed. If no app window appeared, send startup-log.txt.
goto finish
:missing_files
>>"%step2nc_log%" echo Application files are missing. Use Extract All on the ZIP. Keep the entire extracted folder together.
goto failed
:failed
echo.
echo STEP2NC1 could not start. Diagnostic output follows:
type "%step2nc_log%"
echo.
echo Send this log: "%step2nc_log%"
set "step2nc_exit=1"
:finish
if not defined step2nc_exit set "step2nc_exit=0"
popd
pause
exit /b %step2nc_exit%
:location_error
echo Cannot open the application folder. Extract the ZIP to a local writable folder first.
pause
exit /b 1
