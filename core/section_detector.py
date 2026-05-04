"""Identify section family (W/C/L/HSS) and dimensions from STEP geometry.

Strategy:
  1. Find the longest principal axis of the bounding box - that's the length.
  2. Find planar faces whose surface normal is parallel to the length axis;
     these are end faces (or end-of-cope faces).
  3. Pick the end face nearest to the part's start (smallest length-axis
     position) - its outer boundary loop IS the cross-section polygon.
  4. Classify the polygon by the number of vertices and their layout:
        I  : 12 vertices (W/S/HP)
        C  : 8 vertices on one side
        L  : 6 vertices forming an L
        HSS: 4 outer + 4 inner vertices (rectangular tube)
  5. Extract dimensions directly from the polygon.

If no clean end face is found, we fall back to the convex hull of all vertex
points projected to the cross-section plane and let the user override.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .geometry import BBox, Vec2, Vec3, project_to_plane
from .profiles import Profile, load_profiles, make_custom_profile, match_profile


@dataclass
class SectionResult:
    family: str           # 'W', 'C', 'L', 'HSS'
    profile: Profile
    length_axis: int      # 0=X, 1=Y, 2=Z
    length_dir_sign: int  # +1 if part runs in +axis from origin, -1 otherwise
    length_in: float      # part length (inches)
    bbox: BBox            # full bbox in inches
    cross_polys: List[List[Vec2]] = field(default_factory=list)  # outer + inner cross-section loops
    notes: str = ""


# ------------------------------------------------------------------
# End-face cross section extraction
# ------------------------------------------------------------------

def _faces_perpendicular_to_axis(model, length_axis: int, tol_deg: float = 5.0):
    """Return list of (face_entity, plane_point, plane_normal, surface_ref) for
    every ADVANCED_FACE whose underlying PLANE normal is parallel to the
    length axis.
    """
    axis_vec = [Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)][length_axis]
    out = []
    for face in model.of_type("ADVANCED_FACE"):
        surf_ref = model.face_surface_ref(face)
        if surf_ref is None:
            continue
        surf = model.ents.get(surf_ref)
        if not surf or surf.name != "PLANE":
            continue
        ax_ref = next((a for a in surf.args if isinstance(a, int)), None)
        if ax_ref is None:
            continue
        ax = model.axis2_placement(ax_ref)
        if ax is None:
            continue
        origin, normal, _ = ax
        if normal.is_parallel(axis_vec, tol=0.05):
            out.append((face, origin, normal))
    return out


def _face_loops_2d(model, face, length_axis: int) -> Tuple[List[Vec2], List[List[Vec2]]]:
    """Return (outer_loop, inner_loops) as 2D polygons.

    Outer loop comes from FACE_OUTER_BOUND; inner loops come from FACE_BOUND
    entries (which represent holes / openings in the face).
    """
    outer: List[Vec2] = []
    inners: List[List[Vec2]] = []
    bound_refs: List[int] = []
    for a in face.args:
        if isinstance(a, list):
            bound_refs.extend(x for x in a if isinstance(x, int))
    unit_to_in = model.length_unit_mm / 25.4
    for br in bound_refs:
        be = model.ents.get(br)
        if not be:
            continue
        is_outer = (be.name == "FACE_OUTER_BOUND")
        if be.name not in ("FACE_OUTER_BOUND", "FACE_BOUND"):
            continue
        loop_ref = next((a for a in be.args if isinstance(a, int)), None)
        if loop_ref is None:
            continue
        loop = model.ents.get(loop_ref)
        if not loop or loop.name != "EDGE_LOOP":
            continue
        pts2: List[Vec2] = []
        for a in loop.args:
            if not isinstance(a, list):
                continue
            for oe_ref in a:
                if not isinstance(oe_ref, int):
                    continue
                oe = model.ents.get(oe_ref)
                if not oe or oe.name != "ORIENTED_EDGE":
                    continue
                ec_ref = next((x for x in oe.args if isinstance(x, int)), None)
                if ec_ref is None:
                    continue
                ec = model.ents.get(ec_ref)
                if not ec or ec.name != "EDGE_CURVE":
                    continue
                v_refs = [x for x in ec.args if isinstance(x, int)][:2]
                # use the START vertex; sequential edges share endpoints so this
                # gives a clean polygon traversal.
                if not v_refs:
                    continue
                ve = model.ents.get(v_refs[0])
                if not ve or ve.name != "VERTEX_POINT":
                    continue
                pr = next((x for x in ve.args if isinstance(x, int)), None)
                if pr is None:
                    continue
                p = model.point(pr)
                if p is None:
                    continue
                p_in = Vec3(p.x * unit_to_in, p.y * unit_to_in, p.z * unit_to_in)
                pts2.append(project_to_plane(p_in, length_axis))
        # de-duplicate consecutive points within tolerance
        cleaned: List[Vec2] = []
        for q in pts2:
            if cleaned and (q - cleaned[-1]).length() < 1e-4:
                continue
            cleaned.append(q)
        if len(cleaned) >= 3:
            if is_outer or not outer:
                if is_outer:
                    outer = cleaned
                else:
                    if not outer:
                        outer = cleaned
                    else:
                        inners.append(cleaned)
            else:
                inners.append(cleaned)
    return outer, inners


def _polygon_bbox(poly: List[Vec2]) -> Tuple[float, float, float, float]:
    xs = [p.x for p in poly]; ys = [p.y for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_area(poly: List[Vec2]) -> float:
    n = len(poly)
    if n < 3: return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = poly[i].x, poly[i].y
        x2, y2 = poly[(i + 1) % n].x, poly[(i + 1) % n].y
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _classify_polygon(outer: List[Vec2], inners: List[List[Vec2]]) -> str:
    """Decide section family from the outer/inner loops of the cross section."""
    n = len(outer)
    # HSS: outer rect + 1 inner rect
    if inners and len(inners) == 1 and 4 <= len(inners[0]) <= 12 and 4 <= n <= 12:
        return "HSS"
    # I-beam: 12 vertices, no inners, symmetric across both axes
    if 10 <= n <= 14 and not inners:
        return "W"
    # Channel: 8 vertices, asymmetric L/R
    if 6 <= n <= 10 and not inners:
        # could be C or L
        x0, y0, x1, y1 = _polygon_bbox(outer)
        # Compute centroid x relative to bbox center
        cx = sum(p.x for p in outer) / n
        cy = sum(p.y for p in outer) / n
        bb_cx = 0.5 * (x0 + x1)
        bb_cy = 0.5 * (y0 + y1)
        # area ratio of the polygon to its bbox
        area_ratio = _polygon_area(outer) / max((x1 - x0) * (y1 - y0), 1e-9)
        if area_ratio < 0.45:
            return "L"
        if abs(cx - bb_cx) > 0.15 * (x1 - x0) or abs(cy - bb_cy) > 0.15 * (y1 - y0):
            return "C"
        return "W"  # default
    # Plate / rectangle
    if n == 4 and not inners:
        return "PLATE"
    return ""


def _extract_dims(family: str, outer: List[Vec2], inners: List[List[Vec2]]
                  ) -> Tuple[float, float, float, float, float]:
    """Return (depth, width, tf, tw, t_wall) inches from polygon."""
    if not outer:
        return 0, 0, 0, 0, 0
    x0, y0, x1, y1 = _polygon_bbox(outer)
    width = x1 - x0
    depth = y1 - y0
    tf = tw = 0.0
    t_wall = 0.0
    if family == "W":
        # web thickness: smallest run of x at constant y near the centroid
        # Group vertices by approximate Y; find pair of narrow x range in middle
        # Easier: web thickness = horizontal distance between the two vertices
        # at the middle Y band.
        ys = sorted(set(round(p.y, 4) for p in outer))
        if len(ys) >= 4:
            # middle band ys[1] and ys[-2] are the inner top of bottom flange
            # and inner bottom of top flange; vertices on those rows include
            # the web inner corners.
            mid_y_top = ys[-2]; mid_y_bot = ys[1]
            tf = (y1 - mid_y_top)
            tf2 = (mid_y_bot - y0)
            tf = (tf + tf2) / 2.0
            mid_pts = [p for p in outer if abs(p.y - mid_y_top) < 1e-3 or abs(p.y - mid_y_bot) < 1e-3]
            if mid_pts:
                xs = sorted({round(p.x, 4) for p in mid_pts})
                # Web width should be the gap between two clusters of x
                # i.e. abs(min |x - 0|) * 2 if symmetric about y-axis
                if len(xs) >= 4:
                    inner_xs = [x for x in xs if abs(x - (x0 + x1) / 2) < width * 0.3]
                    if len(inner_xs) >= 2:
                        tw = max(inner_xs) - min(inner_xs)
        if tw == 0:
            tw = width * 0.05
        if tf == 0:
            tf = depth * 0.06
    elif family == "C":
        # Top and bottom rows give flange thickness, web is along one side
        ys = sorted(set(round(p.y, 4) for p in outer))
        if len(ys) >= 4:
            tf = ((y1 - ys[-2]) + (ys[1] - y0)) / 2.0
        xs = sorted(set(round(p.x, 4) for p in outer))
        if len(xs) >= 3:
            # web = thickness on the closed side
            tw = min(xs[1] - xs[0], xs[-1] - xs[-2])
        if tw == 0: tw = width * 0.1
        if tf == 0: tf = depth * 0.07
    elif family == "L":
        # Two perpendicular legs - thickness is the smaller dim of either leg
        xs = sorted(set(round(p.x, 4) for p in outer))
        ys = sorted(set(round(p.y, 4) for p in outer))
        # Heel at (min x, min y); horizontal leg extends in x, vertical in y.
        if len(xs) >= 3:
            t_wall = xs[1] - xs[0]
        if len(ys) >= 3:
            t_wall = max(t_wall, ys[1] - y0)
        if t_wall == 0:
            t_wall = min(width, depth) * 0.1
    elif family == "HSS":
        if inners:
            ix0, iy0, ix1, iy1 = _polygon_bbox(inners[0])
            tw_x = ((ix0 - x0) + (x1 - ix1)) / 2.0
            tw_y = ((iy0 - y0) + (y1 - iy1)) / 2.0
            t_wall = (tw_x + tw_y) / 2.0
        else:
            t_wall = min(width, depth) * 0.1
    elif family == "PLATE":
        t_wall = min(width, depth)
    return depth, width, tf, tw, t_wall


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def _cross_section_from_extreme_vertices(pts_in: List[Vec3], length_axis: int,
                                          tol_in: float = 0.005) -> List[Vec2]:
    """Take all vertex points whose length-axis coord is at the absolute MIN
    of the bbox. Project to 2D and order around the centroid.
    """
    if not pts_in:
        return []
    coord = lambda p: (p.x, p.y, p.z)[length_axis]
    zmin = min(coord(p) for p in pts_in)
    chosen: List[Vec3] = []
    for tol in (tol_in, tol_in * 4, tol_in * 16, tol_in * 64):
        chosen = [p for p in pts_in if abs(coord(p) - zmin) < tol]
        if len(chosen) >= 4:
            break
    pts2 = [project_to_plane(p, length_axis) for p in chosen]
    cleaned: List[Vec2] = []
    for q in pts2:
        if not any((q - c).length() < 0.01 for c in cleaned):
            cleaned.append(q)
    if len(cleaned) < 3:
        return []
    import math
    cx = sum(p.x for p in cleaned) / len(cleaned)
    cy = sum(p.y for p in cleaned) / len(cleaned)
    cleaned.sort(key=lambda p: math.atan2(p.y - cy, p.x - cx))
    return cleaned


def _largest_perpendicular_face(model, length_axis: int, prefer_end: str = 'min'):
    """Return (face, position_in, area, n_pts) for the largest planar face
    perpendicular to length axis at the extreme position (min or max).
    """
    candidates = _faces_perpendicular_to_axis(model, length_axis)
    if not candidates:
        return None
    unit_to_in = model.length_unit_mm / 25.4
    scored = []
    for face, origin, normal in candidates:
        outer_, _ = _face_loops_2d(model, face, length_axis)
        if not outer_:
            continue
        x0, y0, x1, y1 = _polygon_bbox(outer_)
        area = (x1 - x0) * (y1 - y0)
        pos = (origin.x, origin.y, origin.z)[length_axis] * unit_to_in
        scored.append((face, pos, area, len(outer_)))
    if not scored:
        return None
    if prefer_end == 'min':
        ext_pos = min(s[1] for s in scored)
    else:
        ext_pos = max(s[1] for s in scored)
    near_end = [s for s in scored if abs(s[1] - ext_pos) < 0.05]
    near_end.sort(key=lambda s: -s[2])
    return near_end[0] if near_end else None


def detect_section(model, override_family: Optional[str] = None,
                   profiles: Optional[List[Profile]] = None) -> SectionResult:
    """Analyse a StepModel and return a SectionResult."""
    pts = model.all_vertex_points()
    if not pts:
        pts = model.all_cartesian_points()
    if not pts:
        raise RuntimeError("No geometry points found in STEP file")

    unit_to_in = model.length_unit_mm / 25.4
    pts_in = [Vec3(p.x * unit_to_in, p.y * unit_to_in, p.z * unit_to_in) for p in pts]
    bb = BBox.from_points(pts_in)

    # Try every axis as candidate length axis. The right axis yields a clean
    # cross-section polygon (lots of vertices for I/C/L) on its perpendicular
    # end face, while the wrong axis just gives a rectangle.
    best_score = -1
    length_axis = bb.longest_axis()
    outer: List[Vec2] = []
    inners: List[List[Vec2]] = []
    for ax in (0, 1, 2):
        face_info = _largest_perpendicular_face(model, ax, prefer_end='min')
        if face_info is None:
            continue
        cand_outer, cand_inners = _face_loops_2d(model, face_info[0], ax)
        if not cand_outer:
            continue
        x0 = min(p.x for p in cand_outer); x1 = max(p.x for p in cand_outer)
        y0 = min(p.y for p in cand_outer); y1 = max(p.y for p in cand_outer)
        w, h = x1 - x0, y1 - y0
        if min(w, h) < 0.05:
            continue
        # Score = vertex count + bonus for inner loops, minus aspect-ratio penalty
        ar = max(w, h) / max(min(w, h), 1e-6)
        score = len(cand_outer) + 2 * len(cand_inners) - (4 if ar > 12 else 0)
        # Slight bonus to the longest-bbox axis to break ties
        if ax == bb.longest_axis():
            score += 0.5
        if score > best_score:
            best_score = score
            length_axis = ax
            outer = cand_outer
            inners = cand_inners

    # Strategy 2 (fallback): vertices at the extreme of the chosen axis
    extreme_poly = _cross_section_from_extreme_vertices(pts_in, length_axis)
    if len(extreme_poly) > len(outer):
        outer = extreme_poly
        inners = []

    length_dir_sign = 1
    length_in = (bb.dx, bb.dy, bb.dz)[length_axis]

    family = override_family or _classify_polygon(outer, inners) or "W"
    if not outer:
        bb_min = project_to_plane(bb.minp, length_axis)
        bb_max = project_to_plane(bb.maxp, length_axis)
        outer = [
            Vec2(bb_min.x, bb_min.y),
            Vec2(bb_max.x, bb_min.y),
            Vec2(bb_max.x, bb_max.y),
            Vec2(bb_min.x, bb_max.y),
        ]

    depth_in, width_in, tf, tw, t_wall = _extract_dims(family, outer, inners)
    if family in ("W", "C") and depth_in < width_in:
        depth_in, width_in = width_in, depth_in
        tf, tw = tw, tf

    profile = match_profile(family, depth_in, width_in,
                            web_in=tw, flange_in=tf, wall_in=t_wall,
                            profiles=profiles)
    if profile is None:
        profile = make_custom_profile(family, d=depth_in, bf=width_in,
                                       tf=tf, tw=tw, t_wall=t_wall)
        notes = f"No exact AISC match (measured d={depth_in:.2f}\", bf={width_in:.2f}\")."
    else:
        notes = (f"Matched {profile.name} ("
                 f"\u0394d={profile.d - depth_in:+.3f}\", "
                 f"\u0394bf={profile.bf - width_in:+.3f}\")")

    cross_polys = [outer] + inners
    return SectionResult(
        family=family, profile=profile,
        length_axis=length_axis, length_dir_sign=1,
        length_in=(bb.dx, bb.dy, bb.dz)[length_axis],
        bbox=bb,
        cross_polys=cross_polys, notes=notes,
    )
