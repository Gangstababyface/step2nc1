# STEP2NC1 — 1.3.0-rc1

A Windows-friendly desktop editor and command-line converter for individual,
straight structural members. Uses Open CASCADE through CadQuery for STEP units,
placements, solid topology, and exact line/circular-arc geometry.

**Release candidate:** automated Linux checks are supplied; Windows desktop, packaged
application, receiving CAM and physical acceptance remain pending. See
[release gates](docs/RELEASE-GATES.md) before distribution. Regenerate any round-stock
outputs from older versions; the round-section classifier has been corrected.

## STEP to IGES

Use **STEP to IGES** in the toolbar, choose one or more original STEP files, then choose an output folder. The result is `.igs` geometry suitable for testing with the IGES/IGS importer in the supplied TubesT dialog. This operation does not depend on the NC1 profile detector and preserves the source model position and scale. The current NC1 editor's changes are not applied.

Export uses IGES B-rep mode in millimetres. Every result is reopened and checked for valid geometry, solid count, bounds, area and volume before publication. Original colors, assembly names, fabrication metadata and machining instructions are not preserved. The receiving TubesT importer still needs an acceptance check; an internal readback does not establish compatibility with every CAD importer.

```bat
STEP2NC1-cli.exe "part.step" --format iges -o "C:\Jobs\IGES"
STEP2NC1-cli.exe "C:\Jobs\STEP" --recursive --format iges -o "C:\Jobs\IGES" --report iges-report.json
```

Supported outputs are NC1 and IGES. SAT, IFC, STEPX and proprietary TubesT/Tekla/PCD/Excel imports are not claimed as exports. They require their own format specifications, SDKs or importer-specific templates.

## Customer installation

The customer deliverable is **STEP2NC1-Setup.exe**. Open it, click Install, then use the desktop or Start menu shortcut. It contains the Python runtime, Tk and CAD dependencies. Customers do not install Python, run pip, or use batch scripts. It supports per-user installation, in-place updates and uninstall through Windows Settings.

The installer must be built and verified on Windows. The source ZIP is a developer package, not the customer installer. The Windows workflow creates an installer artifact only after regression, frozen-app and install/upgrade/uninstall checks pass. Do not rename a source ZIP or batch file to EXE.

## Developer source setup on Windows

1. Extract this entire ZIP to a writable folder.
2. Install **64-bit Python 3.11 or 3.12** from [python.org](https://www.python.org/downloads/windows/), including the Python launcher and Tcl/Tk.
3. Double-click **Start.bat**. First launch installs the pinned CAD dependency into a local `.venv`; this needs an internet connection. Later use is offline.
4. Open a STEP file. Review the profile, quantity, grade, faces and diagnostics.
5. Use **Save project** to preserve edits, and **Export NC1** to create the file.

This package contains the complete source and launch scripts, not a standalone
Windows executable. The validation environment is Linux; see `docs/VALIDATION.md`
for exactly what was tested.

## If a batch file does nothing

Use **Extract All** first. Run `Start.bat` to open the editor, or
`Validate-Windows.bat` to test the installation. The console now stays open
after completion and failures. Startup writes `startup-log.txt`; verification
writes `validation-log.txt` and, if Python starts successfully,
`installation-check.json`. The printed log path is authoritative; if the app
folder is not writable, the text log goes to your Windows temporary folder.
Send the log from the failed run for diagnosis.

Setup accepts 64-bit Python 3.11/3.12 with Tcl/Tk through either the `py` launcher
or a supported `python` on PATH. This package still requires Python; it is not
a prebuilt standalone executable.

## Implemented workflow

- Import one STEP solid; normalize translated/rotated geometry to a consistent
  millimetre part frame. The original-to-part transform is retained.
- Measure W/I beams, U channels, L angles, rectangular/square HSS, flat plate and round pipe. Round pipe supports square
  ends or a single planar miter at each end; bores, saddles and stepped ends are rejected.
- Preserve measured dimensions; use a catalog label only when dimensions,
  including thickness, match. The bundled catalog is limited, not a complete
  certified AISC database. Confirm the production stock designation yourself.
- Detect through-holes separately on each physical wall. A bore through both
  tube walls produces two operations. Small and large holes are not filtered by
  arbitrary diameter limits.
- Extract AK outer contours, IK slots/cutouts, and cope radii from solid sections.
  Circular arcs remain arcs. No spline-to-polyline approximation is performed.
- Detect simple end miters and web miters combined with copes when the flange
  contours remain rectangular. The latter include signed AK bevel angles and
  depths, verified against surface and interior slices through each flange.
  Complex bevels, pockets, oblique holes and unsupported
  surfaces stop export with a diagnostic instead of disappearing from the file.
- Edit holes, slot dimensions, contours, bevel data, text, point marks, scribe
  paths and powder paths. View each face, zoom and pan.
- Read existing NC1 files, including attached dimension references, tangent-notch
  accessories, SI text heights, optional saw length and legacy blank records.
- Save/reopen `.step2nc.json` projects with every editable feature and diagnostic.
- Cancel a running conversion without closing the editor. Unsaved drafts, including
  unfinished form text, are checkpointed every 30 seconds and offered for recovery
  after an interrupted session. Active windows retain their own drafts.
- Export a local support ZIP with diagnostics and runtime versions. Source CAD is
  not included automatically; review the report before sharing it.
- Batch conversion asks for material explicitly and presents per-file results with
  actions and editable drafts where available. It continues after failed files. CAD runs in a separate process
  with a timeout, so a kernel crash cannot terminate the editor or entire batch.
- Export ordered DSTV+ 3.1 BA/PI manifests with stock-length and profile checks.

**Material grade is not inferred from geometry.** Enter it in the editor or use
`--material`. Quantity defaults to a trailing `X<number>` filename suffix,
otherwise 1. Verify the inferred quantity before production.

## Command line

```bat
.venv\Scripts\python main.py "part.step" --material A36 --project
.venv\Scripts\python main.py "C:\Jobs\STEP" --recursive -o "C:\Jobs\NC1" --material A992 --project --report batch.json
.venv\Scripts\python main.py inspect "C:\Jobs\NC1\*.nc1" --report inspection.json
.venv\Scripts\python main.py nest examples\nest.json -o examples\nest.ba
```

`Convert.bat` accepts the same arguments and supports dragging STEP files onto it.
Directory input retains its subdirectory structure under the output folder.
An existing NC1 is retained unless `--force` is specified. Exit status is nonzero
if any requested file fails. `--length-axis x|y|z` selects an axis in the original
STEP coordinate frame; default is automatic. `--project` saves reviewable drafts
even when extracted geometry blocks NC1 export.

On Linux/macOS, create a virtual environment, install `requirements.txt`, then
run `python main.py`. Tkinter must be installed by the OS/Python distribution.
The CLI does not require a graphical display.

## Coordinates and editing

Internal X is length, Y is section depth and Z is section width. The normalized
member begins at X=0. `v/h` use depth as their second coordinate; `o/u` use width.
The desktop preview displays the actual NC1 coordinates in millimetres and the
header miter envelope. Round pipe uses face `v` unrolled over circumference πD.

| Face | Location in the normalized solid |
|---|---|
| v | Front / low-Z wall; front web for W/C |
| h | Back / high-Z wall for HSS |
| o | Top / high-Y flange or wall |
| u | Bottom / low-Y flange or wall; angle horizontal leg |

Channel webs and angle heels are oriented consistently. Equivalent symmetric
members can have more than one valid orientation; review the saved transform
and face previews when comparing with a detailing system's orientation.

In the contour editor, each row contains `X Y radius` followed optionally by four
bevel values. Radius belongs to the outgoing segment; positive is counterclockwise.
Beveled AK contours show the maximum material envelope, which may differ from
the visible face edge. A positive bevel angle cuts the current face; a negative
angle cuts the opposite face. Bevel depth is the intersection height measured
from the opposite face, as defined in DSTV p.18.
AK and IK must close by repeating the first coordinate. `t/w` accessory records
from imported DSTV files are retained. Hole/slot X and Y in the editor are the
centre of the feature; native BO slot reference points are translated on import
and export. Selecting a different catalog profile changes dimensions, not feature
coordinates. Saving a project preserves changes; exporting NC1 does not replace
the project save.

## Supported scope and limits

This is a converter/editor for the supported straight section families, not a
universal STEP machining postprocessor. Curved members, solid round rod, special
or lipped sections, assemblies, and free-form surfaces are not automatically
converted. Round-pipe bores, saddles and stepped ends are also outside scope.
Hidden cavities, counterbores and flange/web junction bores are checked through
the nominal wall thickness. Hole features must pass through the relevant wall with unchanged
geometry. Partial-depth weld chamfers, compound cuts with copes, and machining in rolled corner
regions may require a dedicated postprocessor and are reported as unsupported.

The NC1 reader can inspect additional blocks, but it does not rewrite machining
that the editor does not understand. Unknown blocks and row-specific manufacturing
constraints are retained in the project and block modified NC1 export. Validation
checks dimensions, finite values, contour closure, arc feasibility, face extents
and ASCII text; it does not certify toolpaths, fixture clearance or machine setup.

**Review generated NC1 in the receiving machine software before cutting.** No
physical machine or vendor postprocessor was available for controller acceptance
testing. The supplied reference NC1 files are format tests, not matching geometric
ground truth for the supplied STEP files.

## DSTV+

`nest` uses an explicit ordered JSON list; it does not optimize nesting. It rejects
mixed profile/dimension/grade lists and nonzero miter headers. Stock accounting is
conservative: sum of part lengths + one kerf per part + front/end trims + one filler
allowance per bar. Confirm these allowances with the receiving nesting system.
Existing NC1 files remain authoritative for part data. BA references resolve from
the exported BA's directory. The parts themselves must travel with the manifest.

## Tests and development

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\validate_samples.py "C:\Jobs\STEP" "C:\Jobs\Audit" --workers 2
```

Run `Validate-Windows.bat` on Windows for an end-to-end installation check,
including opening/editing/saving/exporting in the desktop. It creates
`installation-check.json`. A headless check is available with
`python main.py doctor --output installation-check.json`; this does not pass the
desktop gate.

To build a standalone Windows package, run `Build-Windows.ps1` in PowerShell on
Windows with 64-bit Python 3.12 installed. The build runs regression tests and
both source and packaged desktop checks before creating the ZIP. The workflow in
`.github/workflows/windows-build.yml` runs the same build in Windows CI. These
checks have not been executed on Windows for this candidate.

See `docs/VALIDATION.md` for supplied-file outcomes and `docs/CHANGES.md` for the
implementation changes. `validation/` contains machine-readable audit reports.
`converted_samples/` includes successful conversions and reviewable draft projects
from the 34 directly supplied STEP files; the original STEP geometry is included
beside each draft for reference.

## References

Format decisions follow the supplied **DSTV 8th corrected edition (November 2003)**,
particularly pp.7-18, and **DSTV+ v3.1 (26 July 2007)**. KA is a bending block; weld
preparations belong to contour records. PU/KO are paths; point marks use BO `m`.
Implementation uses the [CadQuery documentation](https://cadquery.readthedocs.io/en/latest/).
