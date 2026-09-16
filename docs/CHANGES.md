# Changes — 1.3.0-rc1

Added STEP to IGES B-rep export through the desktop and CLI, independent of NC1 section restrictions. Preserves model coordinates and converts STEP units to millimetres. Supports batch conversion, cancellation and protected atomic output publication. Reopens every export and checks solid count, area, volume and bounds. Adds tests for curved parts, saddle cuts, pockets, multiple solids, inch units, Unicode paths and output preservation. Windows source/frozen/installed checks now exercise IGES and the desktop IGES action.

IGES exports original STEP geometry. NC1 editor changes, colors, assembly labels and machining metadata are not transferred. TubesT importer acceptance has not been run here.

# Changes — 1.2.0-rc3

## Conversion correctness

- Detect analytic cylinder axes and classify concentric pipe before rectangular HSS. Add explicit RO support for square or singly mitered pipe ends. Reject unsupported pipe machining.
- Replace the wire-length comparison that triggered native CAD crashes with projected contour comparisons, including analytic circle comparisons.
- Check wall interiors at topology transitions and regular slices to detect hidden cavities, counterbores and changing contours. Check actual stock around each opening to reject junction bores extending beyond the nominal wall.
- Preserve exact circular arcs, supported cope contours and signed AK bevel preparation. Reject multiple distinct end planes when a single header cut cannot represent them.
- Publish CLI outputs atomically without replacing an existing destination unless force is explicitly enabled, including competing writers.

## Customer workflow

- Cancellable and reaped isolated CAD workers; stable failure codes and next actions; native crash diagnostics retained for support.
- Thirty-second recovery checkpoints retain raw, unfinished form fields. OS locks keep active windows' drafts separate.
- Local support reports with runtime information and logs, without automatic CAD inclusion or uploading.
- Batch-specific material entry, per-file results and reviewable drafts; editor controls disabled while analysis runs.
- True header-miter envelopes in the preview, unrolled round-pipe view and invalid-dimension handling.

## Installation and release evidence

- End-to-end doctor command and Validate-Windows.bat, with an explicit desktop check option.
- Dual executable PyInstaller configuration, Windows build script and Windows CI workflow. Packaging requires regression, source GUI and frozen GUI checks to pass.
- Complete fresh audits of both archives, direct samples, per-file source hashes and independent NC1 serialization readback. See VALIDATION.md for exact outcomes.

This candidate supersedes the previous 1.0/1.1 source and audit outputs. In particular, older round-stock exports must be regenerated. Windows, receiving software and physical acceptance remain distinct release gates.

## Windows launcher follow-up

Startup and validation now show progress, retain the console and capture diagnostic logs. Missing extracted files are reported explicitly. Setup accepts supported Python on PATH when the py launcher is absent, checks runtime architecture/Tcl/Tk, and avoids hidden pause prompts when called by another script. Batch files use Windows CRLF line endings. These launcher changes have not been executed on Windows in the Linux validation environment. Geometry is unchanged.

## Customer installer packaging

Added an Inno Setup per-user installer that bundles the frozen runtime, creates desktop and Start menu shortcuts and launches the application after installation. The Windows build now compiles STEP2NC1-Setup.exe and requires install, upgrade, installed-GUI/CAD and uninstall verification. The installed check removes external Python from PATH and checks preservation of user-created files. Customer distributions omit batch launchers. The workflow is ready for a Windows runner; no setup executable has yet been built or verified.
