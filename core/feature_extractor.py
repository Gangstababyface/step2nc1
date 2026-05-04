"""Detect holes, end cuts/bevels, copes/notches, and produce a feature list
ready to feed the DSTV NC1 writer.

DSTV surface codes (the part orientation in NC1 is fixed):

    v  Vorne / Front  - the WEB, viewed from the front (drilling X-Y at fixed Z)
    o  Oben  / Top    - top flange, top surface
    u  Unten / Bottom - bottom flange, bottom surface
    h  Hinten/ Back   - back of web (rare; mostly used for L and U)

For an I-beam in NC1 part frame:
    +X = along the part length (start = 0, end = part length)
    +Y = up the depth direction (web height)
    Top flange faces look "down" the +Y axis.
    Bottom flange faces look "up" along -Y.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import BBox, Vec2, Vec3, angle_between_normals_deg
from .section_detector import SectionResult


# ------------------------------------------------------------------
# Feature data classes
# ------------------------------------------------------------------

@dataclass
class Hole:
    surface: str          # 'v', 'o', 'u', 'h'
    x_mm: float           # along part length, from start
    y_mm: float           # in-surface vertical position
    diameter_mm: float
    slotted: bool = False
    slot_length_mm: float = 0.0
    slot_angle_deg: float = 0.0   # CCW from horizontal
    note: str = ""


@dataclass
class ContourPoint:
    surface: str
    x_mm: float
    y_mm: float
    radius_mm: float = 0.0   # bulge radius for arcs


@dataclass
class Marking:
    surface: str
    x_mm: float
    y_mm: float
    angle_deg: float = 0.0
    text: str = ""


@dataclass
class EndCut:
    """Bevel / mitre at one end of the part. NC1 stores these as web-cut and
    flange-cut angles (degrees) at start and end of the part."""
    web_start_deg: float = 0.0
    web_end_deg: float = 0.0
    flange_start_deg: float = 0.0
    flange_end_deg: float = 0.0


@dataclass
class FeatureSet:
    section: SectionResult
    holes: List[Hole] = field(default_factory=list)
    outer_contour: List[ContourPoint] = field(default_factory=list)
    inner_contours: List[List[ContourPoint]] = field(default_factory=list)
    markings: List[Marking] = field(default_factory=list)
    end_cuts: EndCut = field(default_factory=EndCut)


# ------------------------------------------------------------------
# Hole extraction
# ------------------------------------------------------------------

def _surface_for_axis(family: str, hole_axis_in_part: int) -> str:
    """Return the DSTV surface letter for a hole whose axis is along the given
    part-axis index (0 = part X / length, 1 = part Y / depth, 2 = part Z / width).

    For typical structural steel, holes are perpendicular to the surface they
    pierce, so:
      I-beam: web holes have axis along Z (part width)  -> surface 'v'
              flange holes have axis along Y (depth)     -> 'o' or 'u'
      Channel/Angle: similar logic
      HSS: front/back/top/bottom
    """
    if family in ("W", "C"):
        if hole_axis_in_part == 1:
            return "o"   # top flange (could be u; we decide by Y position)
        return "v"
    if family == "L":
        return "v" if hole_axis_in_part == 1 else "h"
    if family == "HSS":
        return "v" if hole_axis_in_part == 1 else "o"
    return "v"


def extract_holes(model, sec: SectionResult) -> List[Hole]:
    """Find every CYLINDRICAL_SURFACE in the model and emit a Hole."""
    holes: List[Hole] = []
    cyls = model.cylindrical_surfaces()
    if not cyls:
        return holes

    unit_to_in = model.length_unit_mm / 25.4
    unit_to_mm = model.length_unit_mm
    length_axis = sec.length_axis
    bb = sec.bbox  # in inches
    # part frame origin: (xmin in length axis, ymin in vertical, zmin in width)
    # We map STEP coords -> part coords:
    #    part_x = (length-axis coord) - bb.min(length-axis)        (mm)
    #    part_y = (cross-vertical) - bb.min(vertical)              (mm)
    #    part_z = (cross-horizontal) - bb.min(horizontal)          (mm)

    # Choose vertical / horizontal cross-section axes
    cross_axes = [a for a in (0, 1, 2) if a != length_axis]
    # Pick vertical axis as the one with larger bbox extent (usually depth > width)
    cross_axes.sort(key=lambda a: -[bb.dx, bb.dy, bb.dz][a])
    vert_axis = cross_axes[0]
    horiz_axis = cross_axes[1]

    def to_part(p: Vec3) -> Tuple[float, float, float]:
        coords = (p.x, p.y, p.z)
        x = (coords[length_axis] - [bb.minp.x, bb.minp.y, bb.minp.z][length_axis]) * unit_to_mm
        y = (coords[vert_axis] - [bb.minp.x, bb.minp.y, bb.minp.z][vert_axis]) * unit_to_mm
        z = (coords[horiz_axis] - [bb.minp.x, bb.minp.y, bb.minp.z][horiz_axis]) * unit_to_mm
        return x, y, z

    # Group cylinders by axis line + radius so a hole that spans top+bottom
    # flange isn't double-counted.
    seen: List[Tuple[Vec3, Vec3, float]] = []

    def axis_match(a_pt, a_dir, r, b_pt, b_dir, b_r) -> bool:
        if abs(r - b_r) > 0.05 * max(r, b_r): return False
        if not a_dir.is_parallel(b_dir, tol=0.02): return False
        # closest distance between the two infinite lines
        d = a_pt - b_pt
        proj = d.dot(a_dir.normalized())
        perp = (d - a_dir.normalized() * proj).length()
        return perp < 0.05  # 0.05 source units tolerance

    MAX_HOLE_DIA_MM = 80.0   # Anything larger is likely a cope corner radius
    MIN_HOLE_DIA_MM = 5.0    # Anything smaller is likely a cosmetic fillet

    for ent, axis_pt, axis_dir, radius in cyls:
        diameter_mm_check = 2.0 * radius * unit_to_mm
        if diameter_mm_check > MAX_HOLE_DIA_MM or diameter_mm_check < MIN_HOLE_DIA_MM:
            continue
        # Find the existing group whose axis matches
        already = any(axis_match(axis_pt, axis_dir, radius, b[0], b[1], b[2])
                      for b in seen)
        if already:
            continue
        seen.append((axis_pt, axis_dir, radius))

        # Determine which part axis the hole goes through
        d = axis_dir.normalized()
        comps = (abs(d.x), abs(d.y), abs(d.z))
        hole_axis = comps.index(max(comps))  # 0/1/2

        # The hole position: project axis_pt onto the cross-section plane that
        # is perpendicular to the hole's own axis. Then convert to part frame.
        x_mm, y_mm, z_mm = to_part(axis_pt)

        # Surface determination
        # If hole axis is along the depth direction (vert_axis): top/bottom flange
        # If hole axis is along the width direction (horiz_axis): web (front/back)
        # If hole axis is along the length direction: end face hole (rare)
        if hole_axis == vert_axis:
            # Through flange. Top flange when axis_pt.vert is near max
            cross_max = [bb.maxp.x, bb.maxp.y, bb.maxp.z][vert_axis]
            cross_min = [bb.minp.x, bb.minp.y, bb.minp.z][vert_axis]
            mid = 0.5 * (cross_max + cross_min)
            apc = (axis_pt.x, axis_pt.y, axis_pt.z)[vert_axis]
            surface = "o" if apc > mid else "u"
            # On flange, NC1 Y coord runs ACROSS the flange (= horizontal axis)
            y_mm_surface = z_mm
        elif hole_axis == horiz_axis:
            surface = "v"
            y_mm_surface = y_mm
        else:
            surface = "end"
            y_mm_surface = y_mm

        if surface == "end":
            continue   # cope-corner radii or similar; user can add manually if real

        diameter_mm = 2.0 * radius * unit_to_mm
        holes.append(Hole(
            surface=surface, x_mm=x_mm, y_mm=y_mm_surface,
            diameter_mm=diameter_mm,
        ))

    # Dedupe by rounded (surface, x, y, d)
    deduped: List[Hole] = []
    seen_keys = set()
    for h in sorted(holes, key=lambda h: (h.surface, h.x_mm, h.y_mm)):
        k = (h.surface, round(h.x_mm, 1), round(h.y_mm, 1), round(h.diameter_mm, 2))
        if k in seen_keys:
            continue
        seen_keys.add(k)
        deduped.append(h)
    return deduped


# ------------------------------------------------------------------
# End cut / bevel detection
# ------------------------------------------------------------------

def detect_end_cuts(model, sec: SectionResult) -> EndCut:
    """Look at the planar faces at each end of the part and measure the
    angle between their normals and the length axis.
    """
    length_axis = sec.length_axis
    axis_vec = [Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)][length_axis]
    unit_to_in = model.length_unit_mm / 25.4
    bb = sec.bbox

    start_pos = [bb.minp.x, bb.minp.y, bb.minp.z][length_axis]
    end_pos = [bb.maxp.x, bb.maxp.y, bb.maxp.z][length_axis]

    start_angle = 0.0
    end_angle = 0.0

    for ent, origin, normal in model.planes():
        # Approximate which end of the part this plane sits on
        opos = (origin.x, origin.y, origin.z)[length_axis]
        # Angle from the length axis (we want offset from 0)
        ang = angle_between_normals_deg(normal, axis_vec)
        # Only consider faces whose normal is reasonably aligned with the length
        # direction (within ~45 deg) - those are end cuts, not webs/flanges.
        if ang > 45:
            continue
        if abs(opos - start_pos) < 0.5 / unit_to_in:
            start_angle = max(start_angle, ang)
        elif abs(opos - end_pos) < 0.5 / unit_to_in:
            end_angle = max(end_angle, ang)

    # We don't (yet) distinguish web bevel vs flange bevel - we apply the
    # same angle to both. The user can refine in the GUI.
    return EndCut(
        web_start_deg=start_angle,
        web_end_deg=end_angle,
        flange_start_deg=start_angle,
        flange_end_deg=end_angle,
    )


# ------------------------------------------------------------------
# Outer contour (cope / notch detection)
# ------------------------------------------------------------------

def detect_outer_contour(sec: SectionResult) -> List[ContourPoint]:
    """Cope / notch detection placeholder.

    A full implementation would walk the silhouette of the part along the
    length axis and emit AK contour points at every concave transition.
    This is non-trivial without a real CAD kernel and is best handled in the
    GUI where the user can confirm/adjust. For now, we return an empty list
    and the writer falls back to the rectangular outline of the section.
    """
    return []


# ------------------------------------------------------------------
# Top-level
# ------------------------------------------------------------------

def extract_features(model, sec: SectionResult) -> FeatureSet:
    fs = FeatureSet(section=sec)
    fs.holes = extract_holes(model, sec)
    fs.end_cuts = detect_end_cuts(model, sec)
    fs.outer_contour = detect_outer_contour(sec)
    return fs
