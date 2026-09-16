# Validation report

STEP2NC1 1.2.0-rc3. Tested 2026-09-16 on Linux, Python 3.12, CadQuery 2.7.0.
Automated regression suite: **53 passed**, no failures, errors or skips.

| Dataset | Tested | Exported | Flagged | NC1 readback passed |
|---|---:|---:|---:|---:|
| Direct | 34 | 28 | 6 | 28 |
| Z | 246 | 161 | 85 | 161 |
| R | 634 | 131 | 503 | 131 |

All 880 STEP/STP entries in Z and R and all 34 direct STEP uploads were tested afresh at a 120-second per-file limit. Duplicate models at different paths count as separate entries. Every source has a verified SHA-256; output names were checked for collisions. Other archive formats and executables were not run.

Exported means geometry extraction and internal validation passed. NC1 readback then compared stock dimensions, quantity, grade, hole faces/coordinates/diameters, contour vertices/radii/bevel fields and miter angles with saved project data within 0.002 mm/degrees. This checks serialization; it is not a full geometric equivalence proof or receiving-controller acceptance. The reference NC1 files are not paired geometric ground truth.

Unsupported parts remain explicit rejections. A timeout or CAD process failure is not proof of unsupported geometry. See the per-file diagnostics. Material grades remain blank because no grades were supplied; quantities follow the filename suffix rule. Review both before use.

## Failure categories

| Category | Direct | Z | R |
|---|---:|---:|---:|
| Invalid header metadata | 0 | 0 | 12 |
| Invalid or unreadable solid | 0 | 0 | 12 |
| Multiple or missing solids | 0 | 3 | 17 |
| Timed out | 0 | 0 | 6 |
| Unsupported machining geometry | 1 | 49 | 27 |
| Unsupported round-pipe machining | 0 | 24 | 414 |
| Unsupported section or orientation | 5 | 9 | 15 |

## Release limits

Linux installation verification passed the real STEP → isolated worker → NC1 → project readback workflow. Desktop modules compile. Live GUI verification was not available: the environment blocked display-server sockets. Windows source launch, native packaging, frozen desktop behavior, high-DPI visual review, receiving CAM and physical acceptance remain pending. See RELEASE-GATES.md.

`validation/` contains the complete current per-file reports, regression evidence, installation check and Python source hashes. `converted_samples/` contains only freshly generated direct-sample outputs, drafts where available and original direct STEP files. The separate archive-test-results ZIP contains fresh successful R/Z exports and all per-file results.
