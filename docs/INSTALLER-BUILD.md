# Windows customer installer

Version 1.3.0-rc3. The customer deliverable is STEP2NC1-Setup.exe. The source tree is not itself an installer.

The Windows workflow runs regression tests, source/frozen/installed CAD and desktop checks, compiles with Inno Setup and retains the EXE and SHA256 only after verification succeeds. The current run in GitHub Actions is the authoritative native build result.

Setup has no customer dependency downloads, administrator prompt or setup-choice/confirmation pages. The normal non-silent path is tested without clicking any wizard buttons: setup must finish automatically and open a desktop window. Desktop and Start menu shortcuts are checked. A same-version reinstall, installed workflow with Python removed from PATH, uninstall and user-created file preservation are also checked. Cross-version upgrades and organizational Windows policy remain separate qualification.

The packaged workflow includes STEP to NC1, STEP to accepted trimmed-surface IGES, inch-unit IGES input to NC1, original IGES byte preservation and both desktop IGES actions. JUnit regression evidence and JSON installation results are retained by the workflow.

No signing certificate is configured. The installer is unsigned; Windows reputation controls may show a prompt. Do not bypass security controls.
