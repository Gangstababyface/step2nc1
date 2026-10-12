param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path $Installer).Path
$step2ncTestRoot = Join-Path $env:TEMP ('STEP2NC1 installer test ' + [guid]::NewGuid().ToString('N'))
$step2ncApp = Join-Path $step2ncTestRoot 'Installed App'
$step2ncEvidence = Join-Path $PSScriptRoot '../installer-evidence'
New-Item -ItemType Directory -Force $step2ncTestRoot,$step2ncEvidence | Out-Null
$step2ncEvidence = (Resolve-Path $step2ncEvidence).Path
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class Step2NC1Paths {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern uint GetLongPathName(string path, StringBuilder buffer, uint size);
}
'@
function Get-LongPath([string]$Path) {
    $buffer = New-Object System.Text.StringBuilder 32768
    $length = [Step2NC1Paths]::GetLongPathName($Path, $buffer, 32768)
    if ($length -eq 0 -or $length -ge 32768) { throw "Could not resolve the Windows path: $Path" }
    return $buffer.ToString()
}
function Invoke-Setup([string]$LogName, [bool]$Interactive = $false) {
    $step2ncLog = Join-Path $step2ncEvidence $LogName
    $step2ncArgs = @('/NORESTART',"/DIR=`"$step2ncApp`"", "/LOG=`"$step2ncLog`"")
    if (-not $Interactive) { $step2ncArgs += @('/VERYSILENT','/SUPPRESSMSGBOXES') }
    $p = Start-Process -FilePath $Installer -ArgumentList $step2ncArgs -PassThru
    if (-not $p.WaitForExit(90000)) { $p.Kill(); throw 'Setup did not finish automatically within 90 seconds.' }
    if ($p.ExitCode -ne 0) { throw "Installer failed with code $($p.ExitCode). See $step2ncLog" }
}
# Avoid changing an existing operator installation. This check is intended for CI.
$step2ncExisting = Join-Path $env:LOCALAPPDATA 'Programs/STEP2NC1'
if (Test-Path $step2ncExisting) { throw 'Run installer verification on a clean test account. An existing installation was found.' }
try {
    # Exercise the actual customer path: no silent flag and no button automation.
    # Setup must finish and launch a real desktop window without Python on PATH.
    $step2ncInitialPath = $env:PATH
    try {
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        Invoke-Setup 'install.log' $true
        $step2ncDeadline = (Get-Date).AddSeconds(30)
        $step2ncWindow = $null
        do {
            $step2ncWindow = Get-Process -Name STEP2NC1 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq "$step2ncApp\STEP2NC1.exe" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
            if (-not $step2ncWindow) { Start-Sleep -Milliseconds 200 }
        } while (-not $step2ncWindow -and (Get-Date) -lt $step2ncDeadline)
        if (-not $step2ncWindow) { throw 'One-click setup did not automatically open the desktop application.' }
        $step2ncWindow.CloseMainWindow() | Out-Null
        if (-not $step2ncWindow.WaitForExit(15000)) { throw 'The auto-launched desktop could not close normally.' }
    } finally { $env:PATH = $step2ncInitialPath }
    if (-not (Test-Path "$step2ncApp/STEP2NC1.exe")) { throw 'Installed GUI executable is missing.' }
    if (-not (Test-Path "$step2ncApp/STEP2NC1-cli.exe")) { throw 'Installed CAD worker is missing.' }
    $step2ncShell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))) {
        $link = Join-Path $folder 'STEP2NC1.lnk'
        if (-not (Test-Path $link)) { throw "Customer shortcut is missing: $link" }
        $target = $step2ncShell.CreateShortcut($link).TargetPath
        # Shell links may expand RUNNER~1 while TEMP still contains the 8.3 alias.
        # Compare the actual Windows long paths, not their original spellings.
        if ((Get-LongPath $target) -ne (Get-LongPath "$step2ncApp\STEP2NC1.exe")) { throw "Customer shortcut targets the wrong application: $target" }
    }
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
    @{ status='passed'; install=$true; one_click_non_silent=$true; automatic_gui_launch=$true; shortcuts=$true; upgrade=$true; installed_without_python_on_path=$true; uninstall=$true; user_file_preserved=$true } | ConvertTo-Json | Set-Content "$step2ncEvidence/installer-check.json"
} finally {
    # Only remove this test's uniquely named temporary directory after successful removal.
    if (-not (Test-Path "$step2ncApp/STEP2NC1.exe")) { Remove-Item $step2ncTestRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
