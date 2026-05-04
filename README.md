# STEP to NC1 Converter

Convert STEP (ISO 10303-21, AP203/AP214/AP242) CAD files to DSTV NC1
files for CNC structural-steel machines (Peddinghaus, Voortman, Ficep,
Kaltenbach, etc.).

Supports beams (W, S, HP), channels (C, MC), angles (L, equal and
unequal leg), and rectangular hollow sections (HSS, square and rectangular).
Detects holes, end cuts/bevels, and provides full manual editing of
contours, copes/notches, and marking text.

## Run

No third-party packages required. Python 3.9+ with Tkinter.

```
python main.py
```

Open a STEP file with **File -> Open STEP**. The app detects the section,
length, holes, and end cuts. Edit the profile, dimensions, header data,
and individual features in the right-hand panel, then export with
**File -> Export NC1**.

For batch jobs:

```
python main.py file1.step file2.step ...
```

## What gets auto-detected

- **Section family** (W / C / L / HSS) from the cross-section polygon at
  the part end.
- **Profile match** against the AISC database in `data/aisc_profiles.json`.
  Falls back to a measured custom profile if no match is close enough.
- **Length and orientation** from the longest principal axis of the part.
- **Holes** from cylindrical surface entities. Detection assigns a
  surface code (v, o, u, h) based on the hole axis direction. Cope-corner
  fillets (axes parallel to the part length) and unrealistic diameters
  are filtered out.
- **End cuts / bevels** from the angle of planar end faces relative to
  the length axis.

## What still needs the GUI

- **Copes and notches** (AK / IK contours) - detection of arbitrary
  silhouette shapes from B-rep topology requires a full geometric
  kernel. The GUI lets you confirm or override the section and dimensions;
  the writer falls back to a rectangular outline when no contour is
  provided.
- **Markings / scribing text** (SI / PU) - not in the STEP file itself;
  enter via the **Add Marking** button.

## File layout

```
step2nc1/
├── main.py                      Entry point (GUI + CLI)
├── data/aisc_profiles.json      AISC W/C/L/HSS database
├── core/
│   ├── geometry.py              Vec3, Vec2, BBox primitives
│   ├── step_reader.py           STEP parser (no external deps)
│   ├── profiles.py              Profile dataclass + match logic
│   ├── section_detector.py      Family classification + dimension extraction
│   ├── feature_extractor.py     Hole / end-cut detection
│   └── dstv_writer.py           DSTV NC1 file output
└── gui/
    └── app.py                   Tkinter main window
```

## DSTV NC1 reference

| Block | Purpose                              |
|-------|--------------------------------------|
| ST    | Header: order, drawing, profile, length, weight, end-cut angles |
| BO    | Bores - holes, slotted holes        |
| AK    | Outer contour (per surface)          |
| IK    | Inner contour - cutouts, openings    |
| SI    | Signing - scribed text               |
| PU    | Punch / powder marks                 |
| KO    | Marking lines                        |
| KA    | Bevels / chamfers                    |
| EN    | End of file                          |

Surface codes:

| Letter | Side                              |
|--------|-----------------------------------|
| v      | Front of web (Vorne)              |
| h      | Back of web (Hinten)              |
| o      | Top flange, top face (Oben)       |
| u      | Bottom flange, bottom face (Unten)|

## Notes

The STEP parser reads only the entities needed for structural steel:
`CARTESIAN_POINT`, `DIRECTION`, `AXIS2_PLACEMENT_3D`, `LINE`, `CIRCLE`,
`PLANE`, `CYLINDRICAL_SURFACE`, `EDGE_CURVE`, `ORIENTED_EDGE`, `EDGE_LOOP`,
`ADVANCED_FACE`, `FACE_BOUND`, `FACE_OUTER_BOUND`. Spline surfaces and
free-form geometry are ignored. This is fine for typical detailing
exports from SolidWorks, Inventor, AutoCAD Advance Steel, Tekla, or
SDS/2; aluminum extrusions and curved members may need manual review.
