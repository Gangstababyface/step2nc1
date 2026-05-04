@echo off
REM One-shot Git setup for the step2nc1 project.
REM Run this once from C:\Users\Dank\steptonc1\step2nc1 on each PC.
REM Requires Git for Windows: https://git-scm.com/download/win

setlocal
cd /d "%~dp0"

REM Remove any broken partial .git folder
if exist ".git" (
    echo Removing partial .git folder...
    rmdir /s /q .git
)

git init -b main
git config user.email "dustmohr@gmail.com"
git config user.name "Dustin"
git add -A
git commit -m "Initial commit: STEP to DSTV NC1 converter"

echo.
echo ============================================================
echo  Local repo created. To sync between PCs, choose one option:
echo.
echo  Option A: GitHub
echo    1. Create a new private repo at https://github.com/new
echo    2. git remote add origin https://github.com/USER/REPO.git
echo    3. git push -u origin main
echo.
echo  Option B: USB / network drive
echo    git clone --bare . D:\path\to\drive\step2nc1.git
echo    On other PC: git clone D:\path\to\drive\step2nc1.git
echo.
echo  Option C: OneDrive / Dropbox
echo    Just put the whole step2nc1 folder in your synced folder.
echo    No Git needed.
echo ============================================================
endlocal
pause
