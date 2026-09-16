# Customer release gates

Current version: 1.3.0-rc2. **Release candidate. Do not label this build production-ready.**

The 1.0/1.1 converter could classify circular pipe as rectangular HSS. Regenerate
round-stock outputs with the corrected converter. Do not use those earlier
round-stock exports as machining input.

| Gate | Required evidence | Current state |
|---|---|---|
| Geometry and file integrity | Passing regression suite and per-file archive/readback reports | 61 regression tests; current surface sample audit recorded separately; final archive/readback reports in VALIDATION.md |
| Customer recovery and cancellation | Passing recovery, cancellation and support-bundle tests | Core tests passed; rc1 Windows desktop integration passed; rc2 rechecked by CI |
| Windows source application | `Validate-Windows.bat` produces a passing `installation-check.json` | rc1 Windows source check passed; rc2 CI required |
| Packaged Windows application | `Build-Windows.ps1` passes both source and frozen-app checks | rc1 installer passed; rc2 pipeline runs source, frozen and installed checks |
| Visual review | Review the desktop at 100%, 150% and 200% scaling. Confirm dialogs fit and face previews/miters are legible | Pending |
| Receiving software | Import representative W, C, L, rectangular HSS, plate and supported round-pipe outputs. Confirm stock, orientation, cuts, holes, bevels and quantities against CAD | Pending |
| Physical acceptance | Select representative approved jobs. Confirm machine setup and resulting dimensions using the receiving system's normal process | Pending |

A rejected file must remain an explicit rejection. It is not acceptable to omit
unsupported geometry to improve conversion statistics. A timeout is not proof
of unsupported geometry. Unknown material grades and stock designations must be
reviewed by the operator.

Windows builds use PyInstaller's supported native build flow. PyInstaller does
not cross-compile Windows applications from Linux. See the
[official manual](https://pyinstaller.org/) and
[spec-file documentation](https://pyinstaller.org/en/stable/spec-files.html).

## Developer source verification

1. Extract the candidate source ZIP on a Windows workstation with 64-bit Python 3.12 and Tcl/Tk.
2. Run `Validate-Windows.bat`. Keep `installation-check.json`; all checks, including Desktop workflow, must say passed.
3. Run `Build-Windows.ps1` in PowerShell. Keep `source-installation-check.json`, `dist/STEP2NC1/installation-check.json` and the dependency list. A failed build must not be distributed.
4. Install `dist/installer/STEP2NC1-Setup.exe` on a clean customer-like Windows machine without Python. Confirm shortcuts, application launch, uninstall and target display scaling. Customers receive this installer, not the source validation scripts.
5. For receiving CAM acceptance, record the original STEP hash, NC1 hash, stock, orientation, dimensions, hole coordinates/diameters, end cuts and quantities for each representative supported family. Resolve differences before a physical trial.
6. Retain the approved receiving-system settings and measured physical acceptance results with the release records.

Send back the generated installation JSON and any failing source model or support report to continue diagnosis. The local support ZIP is never sent automatically.

## Customer installer gate

Only `STEP2NC1-Setup.exe` is the customer setup deliverable. Build-Windows.ps1 bundles the runtime, compiles packaging/installer.iss with Inno Setup, and runs a per-user install/upgrade/uninstall test. Installed CAD and desktop checks run with Python removed from PATH. The setup creates shortcuts and launches the application after installation. No customer dependency download is required.

The release build also needs review of the signed/unsigned status under the customer's Windows policy. No signing certificate is configured here; an unsigned build may show a Windows reputation prompt. Do not instruct customers to disable security controls.

References: [Inno Setup privileges](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm), [compiler](https://jrsoftware.org/ishelp/topic_compilercmdline.htm), and [setup command line](https://jrsoftware.org/ishelp/topic_setupcmdline.htm).

IGES gate: the previous B-rep encoding passed internal checks but was rejected by the user's TubesT. Both replacement surface diagnostic variants imported successfully; variant A is now the default. This is acceptance for one part only. Test coverage includes Boolean difference comparisons for rotated/translated pockets, curved solids, saddle cuts and multiple solids. IGES native Windows checks are required for this version; additional receiving TubesT parts still require acceptance.
