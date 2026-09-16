$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Build the Windows application on Windows.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.12 first.' }
}
$step2ncPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $step2ncPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $step2ncPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed. No release was built.' }
& $step2ncPython main.py doctor --gui --output source-installation-check.json
if ($LASTEXITCODE -ne 0) { throw 'Source desktop verification failed.' }
& $step2ncPython -m PyInstaller --noconfirm --clean packaging/windows.spec
if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed.' }
Copy-Item docs/QUICKSTART.md -Destination dist/STEP2NC1/README.md
New-Item -ItemType Directory -Force dist/STEP2NC1/docs | Out-Null
Copy-Item docs/QUICKSTART.md,docs/SUPPORTED-GEOMETRY.md,docs/RELEASE-GATES.md -Destination dist/STEP2NC1/docs/
Copy-Item examples -Destination dist/STEP2NC1/ -Recurse -Force
& $step2ncPython -m pip freeze | Set-Content -Encoding utf8 dist/STEP2NC1/build-dependencies.txt
& .\dist\STEP2NC1\STEP2NC1-cli.exe doctor --gui --output dist/STEP2NC1/installation-check.json
if ($LASTEXITCODE -ne 0) { throw 'Packaged application verification failed. Do not distribute this build.' }
Compress-Archive -Path dist/STEP2NC1 -DestinationPath dist/STEP2NC1-Windows.zip -Force
$step2ncIscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($step2ncIscc) { $step2ncIsccPath = $step2ncIscc.Source }
else { $step2ncIsccPath = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
if (-not (Test-Path $step2ncIsccPath)) { throw 'Build machine requires Inno Setup 6. Customers do not need it.' }
$step2ncVersion = (& $step2ncPython -c 'from core.version import VERSION; print(VERSION)').Trim()
& $step2ncIsccPath "/DAppVersion=$step2ncVersion" packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
& ./scripts/Test-WindowsInstaller.ps1 -Installer dist/installer/STEP2NC1-Setup.exe
if (-not $?) { throw 'Installer verification failed.' }
Get-FileHash dist/installer/STEP2NC1-Setup.exe -Algorithm SHA256 | Format-List | Out-File dist/installer/SHA256.txt
Write-Host 'Installer checks passed. Customer artifact: dist/installer/STEP2NC1-Setup.exe'
Write-Host 'Review docs/RELEASE-GATES.md before customer distribution.' 
