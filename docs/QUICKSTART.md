# STEP2NC1 quick start

Version 1.3.0-rc2 — release candidate. Complete the checks in RELEASE-GATES.md before customer distribution or production use.

## Install and open

Open `STEP2NC1-Setup.exe` and click **Install**. The installer contains the Python runtime and CAD libraries. It installs for your Windows user, creates Start menu and desktop shortcuts, and opens STEP2NC1 when finished. Installation and normal operation do not need dependency downloads.

Open STEP2NC1 from its shortcut on subsequent runs. Windows Settings → Apps → STEP2NC1 → Uninstall removes the program. Saved projects and recovery data are retained.

Open one STEP part. Confirm stock designation, dimensions, quantity, grade, orientation and every face preview. Read any analysis issues. Save a `.step2nc.json` project to preserve edits, then export NC1 when validation passes. Import the NC1 in the receiving software and compare with original CAD before cutting.

## Export STEP geometry for IGES/IGS import

Click **STEP to IGES**. Select one or more original STEP models and choose the output folder. Open the resulting `.igs` file using the receiving program's IGES/IGS filter. Review the results dialog for any failed models.

This is an export of the original STEP geometry. It uses trimmed surfaces, matching the diagnostic format accepted in TubesT. Shapes outside NC1's supported scope may be converted when surface readback and solid reconstruction checks pass. Invalid periodic surfaces or faces that cannot form closed source solids are rejected. Edits made in the NC1 editor are not included. Color, assembly names and fabrication metadata are not preserved. Confirm dimensions and part orientation in the receiving program.

## Batch work

Select Batch, choose STEP files and an output directory, then enter the material grade for the entire batch. Leave it blank only if the grade is deliberately unspecified. Review the results dialog and open drafts for flagged files. Existing NC1 files are retained. Cancellation stops the current worker and remaining queue; completed files remain available. The JSON report records requested and processed counts.

## Recovery and help

Unsaved work is checkpointed approximately every 30 seconds. Recovery preserves unfinished form text. Save projects normally; changes after the last checkpoint can be lost during an interruption. On reopening, use the recovery prompt or Recover draft. Multiple active windows keep separate recovery files.

Use Support report to save a local diagnostic ZIP. It contains application logs and runtime information; it does not automatically attach your CAD. Review it before sending it to your support contact. No automatic upload occurs.

Installation verification is performed during release builds. Customer troubleshooting starts with the Support report button. Receiving CAM and physical machining acceptance are separate checks.

The console companion accepts commands such as:

```bat
STEP2NC1-cli.exe "part.step" --material A36 --project
STEP2NC1-cli.exe "C:\Jobs\STEP" --recursive -o "C:\Jobs\NC1" --material A992 --project --report batch.json
STEP2NC1-cli.exe doctor --gui --output installation-check.json
```

Do not run STEP2NC1-cli.exe's internal worker mode directly.
