param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path $Installer).Path
$step2ncTestRoot = Join-Path $env:TEMP ('STEP2NC1 installer test ' + [guid]::NewGuid().ToString('N'))
$step2ncApp = Join-Path $step2ncTestRoot 'Installed App'
$step2ncEvidence = Join-Path $PSScriptRoot '../installer-evidence'
New-Item -ItemType Directory -Force $step2ncTestRoot,$step2ncEvidence | Out-Null
$step2ncEvidence = (Resolve-Path $step2ncEvidence).Path
function Invoke-Setup([string]$LogName) {
    $step2ncLog = Join-Path $step2ncEvidence $LogName
    $p = Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',"/DIR=`"$step2ncApp`"", "/LOG=`"$step2ncLog`"") -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Installer failed with code $($p.ExitCode). See $step2ncLog" }
}
# Avoid changing an existing operator installation. This check is intended for CI.
$step2ncExisting = Join-Path $env:LOCALAPPDATA 'Programs/STEP2NC1'
if (Test-Path $step2ncExisting) { throw 'Run installer verification on a clean test account. An existing installation was found.' }
try {
    Invoke-Setup 'install.log'
    if (-not (Test-Path "$step2ncApp/STEP2NC1.exe")) { throw 'Installed GUI executable is missing.' }
    if (-not (Test-Path "$step2ncApp/STEP2NC1-cli.exe")) { throw 'Installed CAD worker is missing.' }
    # Ensure a same-version upgrade preserves files the application did not install.
    'User data must survive upgrade and uninstall.' | Set-Content "$step2ncApp/user-project-preservation.txt"
    Invoke-Setup 'upgrade.log'
    if (-not (Test-Path "$step2ncApp/user-project-preservation.txt")) { throw 'Upgrade removed user data.' }
    $step2ncOldPath = $env:PATH
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        & "$step2ncApp/STEP2NC1-cli.exe" doctor --gui --output "$step2ncEvidence/installed-check.json"
        if ($LASTEXITCODE -ne 0) { throw 'Installed application verification failed without Python on PATH.' }
        $check = Get-Content "$step2ncEvidence/installed-check.json" -Raw | ConvertFrom-Json
        if ($check.status -ne 'passed') { throw 'Installed application did not pass every check.' }
    } finally { $env:PATH = $step2ncOldPath }
    $p = Start-Process -FilePath "$step2ncApp/unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$step2ncEvidence/uninstall.log`"") -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw 'Uninstall failed.' }
    if (Test-Path "$step2ncApp/STEP2NC1.exe") { throw 'Uninstall left the application executable.' }
    if (-not (Test-Path "$step2ncApp/user-project-preservation.txt")) { throw 'Uninstall removed user data.' }
    @{ status='passed'; install=$true; upgrade=$true; installed_without_python_on_path=$true; uninstall=$true; user_file_preserved=$true } | ConvertTo-Json | Set-Content "$step2ncEvidence/installer-check.json"
} finally {
    # Only remove this test's uniquely named temporary directory after successful removal.
    if (-not (Test-Path "$step2ncApp/STEP2NC1.exe")) { Remove-Item $step2ncTestRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
