# Supported geometry

STEP2NC1 converts individual straight solids to millimetre DSTV NC1. Supported stock families are W/I, U/C, L, rectangular or square HSS, plate, and round pipe (RO). Measured dimensions take priority over the limited bundled catalog. Review the production stock designation and grade.

| Geometry | Automatic conversion scope |
|---|---|
| Straight plate, W/I, C/U, L and rectangular HSS | Constant supported section; exact lines and circular arcs |
| Normal holes and slots | Unchanged opening through the relevant nominal wall; each wall represented separately |
| Copes and cutouts | Exact supported face contours; wall-interior checks must pass |
| End miters | Supported planar end cuts; selected web-miter/cope combinations with rectangular flange contours and validated signed AK bevels |
| Round pipe | Concentric circular stock; square ends or one planar end cut per end; ST miter header |
| Imported NC1 | Supported blocks retained and editable; unknown machining blocks prevent modified export |

Assemblies, curved members, solid round rod, lipped/custom sections, splines and freeform machining are outside automatic scope. Round pipe bores, saddles and stepped ends are rejected. Blind pockets, hidden wall cavities, changing openings, flange/web junction bores and cuts in rolled corners may be rejected even when a face outline looks simple. Such rejection preserves the missing machining issue for review.

A timeout or kernel failure is a processing failure, not a determination that the section is unsupported. Keep the original STEP and diagnostic report for investigation. Length-axis overrides select an original STEP coordinate axis; they do not repair unsupported geometry.

The normalized part starts at X=0. Faces v/h use section depth; o/u use width. RO uses face v over circumference πD. Header miter previews show the stock envelope. Symmetric sections can have equivalent alternate orientations; compare with the receiving system.

DSTV+ export creates an explicit ordered BA/PI manifest. It is not a nesting optimizer. It requires compatible stock, grade and dimensions and currently rejects nonzero miter headers. Confirm kerf and trim accounting in the receiving system.
