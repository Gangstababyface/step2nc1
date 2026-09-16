@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    call Setup-Windows.bat --unattended
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
if "%~1"=="" (
    echo Drag STEP files onto Convert.bat, or run Convert.bat with CLI arguments.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
pause
