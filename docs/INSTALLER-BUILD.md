# Installer build status

The customer deliverable is STEP2NC1-Setup.exe. The local changes provide its installer definition and Windows build/verification workflow. They are not a compiled EXE.

Local validation: 53 regression tests passed. Workflow YAML structure and installer configuration invariants checked. Native Windows compilation and install/upgrade/uninstall checks have not run.

The user authorized uploading application source to codex/windows-customer-installer in Gangstababyface/step2nc1 and running the Windows build. Customer CAD, original reference archives, per-file reports and converted customer samples are excluded from the repository update. Build status is recorded by the Windows workflow.

Build-Windows.ps1 creates the frozen application and compiles packaging/installer.iss with Inno Setup. scripts/Test-WindowsInstaller.ps1 verifies a clean per-user installation, same-version upgrade, full installed CAD and GUI operation with Python removed from PATH, uninstall and preservation of user-created data. The GitHub workflow retains the EXE only after these checks pass. The build account needs Python and Inno Setup. Customers need neither.

The installer is not code-signed yet. Windows reputation policy must be checked before customer distribution. No customer should be asked to disable security controls.
