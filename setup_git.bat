@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
    echo Install Git for Windows before running this optional helper.
    pause
    exit /b 1
)
if exist ".git" (
    echo A Git repository already exists. Its history has been retained.
    pause
    exit /b 0
)
git init -b main
if errorlevel 1 (
    pause
    exit /b 1
)
echo Repository initialized. Configure your Git identity, review changes, then commit.
echo No files were deleted and no remote repository was changed.
pause
