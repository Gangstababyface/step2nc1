@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 goto failure
if not exist "requirements.txt" goto missing_files
if exist ".venv\Scripts\python.exe" goto install
echo Looking for 64-bit Python 3.12 or 3.11...
py -3.12 -c "import sys,tkinter; sys.exit(0 if sys.maxsize>2**32 and sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
if not errorlevel 1 goto python312
py -3.11 -c "import sys,tkinter; sys.exit(0 if sys.maxsize>2**32 and sys.version_info[:2]==(3,11) else 1)" >nul 2>&1
if not errorlevel 1 goto python311
python -c "import sys,tkinter; sys.exit(0 if sys.maxsize>2**32 and sys.version_info[:2] in [(3,11),(3,12)] else 1)" >nul 2>&1
if not errorlevel 1 goto pythonpath
echo No supported Python installation was found.
echo Install 64-bit Python 3.12 with Tcl/Tk and the Python launcher from:
echo https://www.python.org/downloads/windows/
goto failure
:python312
py -3.12 -m venv ".venv"
if errorlevel 1 goto failure
goto install
:python311
py -3.11 -m venv ".venv"
if errorlevel 1 goto failure
goto install
:pythonpath
python -m venv ".venv"
if errorlevel 1 goto failure
:install
".venv\Scripts\python.exe" -c "import sys,tkinter; sys.exit(0 if sys.maxsize>2**32 and sys.version_info[:2] in [(3,11),(3,12)] else 1)"
if errorlevel 1 goto invalid_environment
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -c "import cadquery, tkinter; print('Setup complete.')"
if errorlevel 1 goto failure
set "step2nc_exit=0"
goto finish
:invalid_environment
echo The existing .venv is damaged or uses an unsupported Python version.
echo Rename .venv to .venv-old and rerun after installing 64-bit Python 3.12 with Tcl/Tk.
goto failure
:missing_files
echo requirements.txt is missing. Extract the complete ZIP before running setup.
:failure
echo Setup failed. Keep the error text above for troubleshooting.
set "step2nc_exit=1"
:finish
popd
if /i not "%~1"=="--unattended" pause
exit /b %step2nc_exit%
