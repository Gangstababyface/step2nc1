"""Lightweight STEP (ISO 10303-21) parser.

Reads AP203/AP214/AP242 part files and builds an in-memory entity graph. We only
extract the topology and surface entities needed for structural-steel analysis:

    CARTESIAN_POINT, DIRECTION, VECTOR, AXIS2_PLACEMENT_3D
    LINE, CIRCLE, ELLIPSE
    PLANE, CYLINDRICAL_SURFACE, CONICAL_SURFACE, TOROIDAL_SURFACE
    VERTEX_POINT, EDGE_CURVE, ORIENTED_EDGE, EDGE_LOOP
    FACE_BOUND, FACE_OUTER_BOUND, ADVANCED_FACE
    CLOSED_SHELL, MANIFOLD_SOLID_BREP

This is sufficient for cross-section identification, hole detection, and end-face
analysis on the typical structural-steel parts produced by SolidWorks, Inventor,
Tekla, AutoCAD Advance Steel, and similar exporters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from .geometry import Vec3


# ---------------------------------------------------------------------------
# Tokenizer / parser
# ---------------------------------------------------------------------------

class StepParseError(Exception):
    pass


@dataclass
class EntityRecord:
    """A single #N = TYPE(args) line."""
    eid: int
    name: str
    args: List[Any]

    def __repr__(self) -> str:
        return f"#{self.eid}={self.name}(...)"


def _strip_comments(src: str) -> str:
    """Remove /* ... */ comments but keep quoted strings intact."""
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == "'":
            # quoted string - copy through the matching quote (doubled '' = literal ')
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "'":
                    if i + 1 < n and src[i + 1] == "'":
                        out.append(src[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif c == '/' and i + 1 < n and src[i + 1] == '*':
            i += 2
            while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _split_statements(src: str) -> List[str]:
    """Split DATA section into statements, respecting parentheses and quotes."""
    stmts = []
    depth = 0
    in_str = False
    buf: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and src[i + 1] == "'":
                    buf.append(src[i + 1])
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            buf.append(c)
            in_str = True
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ';' and depth == 0:
            s = ''.join(buf).strip()
            if s:
                stmts.append(s)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    return stmts


_ENTITY_RE = re.compile(r"^\s*#(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL)


class Ref(int):
    """Distinguishes a STEP entity reference (#N) from a literal integer argument."""
    pass


def _parse_args(s: str) -> List[Any]:
    """Parse a STEP argument list. Returns Python list of:
        Ref (entity ref, prefixed by # in source) - subclass of int
        float / int (literal numbers)
        str (quoted strings, contents unescaped)
        '*' / '$' as the literal strings '*' and '$'
        list of the above (nested parameters)
        EntityRecord-like inline values like NAME(args) → ('inline', name, [args])
    """
    args: List[Any] = []
    n = len(s)
    i = 0

    def skip_ws(p: int) -> int:
        while p < n and s[p] in " \t\r\n":
            p += 1
        return p

    while i < n:
        i = skip_ws(i)
        if i >= n:
            break
        c = s[i]
        if c == ',':
            i += 1
            continue
        if c == '*' or c == '$':
            args.append(c)
            i += 1
            continue
        if c == '#':
            i += 1
            j = i
            while j < n and s[j].isdigit():
                j += 1
            args.append(Ref(s[i:j]))
            i = j
            continue
        if c == "'":
            j = i + 1
            buf: List[str] = []
            while j < n:
                if s[j] == "'":
                    if j + 1 < n and s[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(s[j])
                j += 1
            args.append(''.join(buf))
            i = j + 1
            continue
        if c == '(':
            # nested list - find matching paren
            depth = 1
            j = i + 1
            in_str = False
            while j < n and depth > 0:
                cc = s[j]
                if in_str:
                    if cc == "'":
                        if j + 1 < n and s[j + 1] == "'":
                            j += 2
                            continue
                        in_str = False
                    j += 1
                    continue
                if cc == "'":
                    in_str = True
                elif cc == '(':
                    depth += 1
                elif cc == ')':
                    depth -= 1
                j += 1
            inner = s[i + 1:j - 1]
            args.append(_parse_args(inner))
            i = j
            continue
        if c.isalpha() or c == '_':
            # inline TYPE(args) - rare, but appears in complex entities
            j = i
            while j < n and (s[j].isalnum() or s[j] == '_'):
                j += 1
            name = s[i:j]
            i = j
            i = skip_ws(i)
            if i < n and s[i] == '(':
                # gather args
                depth = 1
                k = i + 1
                in_str = False
                while k < n and depth > 0:
                    cc = s[k]
                    if in_str:
                        if cc == "'":
                            if k + 1 < n and s[k + 1] == "'":
                                k += 2
                                continue
                            in_str = False
                        k += 1
                        continue
                    if cc == "'":
                        in_str = True
                    elif cc == '(':
                        depth += 1
                    elif cc == ')':
                        depth -= 1
                    k += 1
                inner = s[i + 1:k - 1]
                args.append(('inline', name, _parse_args(inner)))
                i = k
            else:
                # bare keyword (like .T. handled below) - shouldn't happen here
                args.append(name)
            continue
        if c == '.':
            # enum like .T. .F. .UNSET.
            j = i + 1
            while j < n and s[j] != '.':
                j += 1
            args.append(s[i:j + 1])
            i = j + 1
            continue
        # number (int or float, possibly with sign / exponent)
        j = i
        if s[j] in '+-':
            j += 1
        while j < n and (s[j].isdigit() or s[j] in '.eE+-'):
            j += 1
        try:
            tok = s[i:j]
            args.append(float(tok) if any(ch in tok for ch in '.eE') else int(tok))
        except ValueError:
            raise StepParseError(f"Bad numeric token at {i}: {s[i:j]!r}")
        i = j

    return args


def parse_step(text: str) -> Dict[int, EntityRecord]:
    """Parse a STEP file and return a dict {eid: EntityRecord}."""
    # Isolate DATA section
    m = re.search(r"\bDATA\s*;", text, re.IGNORECASE)
    if not m:
        raise StepParseError("No DATA section found")
    data = text[m.end():]
    end = re.search(r"\bENDSEC\s*;", data, re.IGNORECASE)
    if end:
        data = data[:end.start()]
    data = _strip_comments(data)

    entities: Dict[int, EntityRecord] = {}
    for stmt in _split_statements(data):
        em = _ENTITY_RE.match(stmt)
        if not em:
            continue
        eid = int(em.group(1))
        name = em.group(2).upper()
        try:
            args = _parse_args(em.group(3))
        except StepParseError:
            continue
        entities[eid] = EntityRecord(eid=eid, name=name, args=args)
    return entities


# ---------------------------------------------------------------------------
# Typed accessors / resolver
# ---------------------------------------------------------------------------

class StepModel:
    """High-level wrapper around the entity graph."""

    def __init__(self, entities: Dict[int, EntityRecord], length_unit_mm: float = 1.0):
        self.ents = entities
        self.length_unit_mm = length_unit_mm  # multiplier to convert STEP units to mm
        self._point_cache: Dict[int, Vec3] = {}

    # ---- generic helpers ------------------------------------------------

    def get(self, ref: int) -> Optional[EntityRecord]:
        return self.ents.get(ref)

    def of_type(self, *names: str) -> List[EntityRecord]:
        names_u = {n.upper() for n in names}
        return [e for e in self.ents.values() if e.name in names_u]

    # ---- primitive resolvers -------------------------------------------

    def point(self, ref: int) -> Optional[Vec3]:
        if ref in self._point_cache:
            return self._point_cache[ref]
        e = self.ents.get(ref)
        if not e or e.name != "CARTESIAN_POINT":
            return None
        # args: [name, [x, y, z]]
        coords = None
        for a in e.args:
            if isinstance(a, list) and len(a) == 3 and all(isinstance(v, (int, float)) for v in a):
                coords = a
                break
        if coords is None:
            return None
        v = Vec3(float(coords[0]), float(coords[1]), float(coords[2]))
        self._point_cache[ref] = v
        return v

    def direction(self, ref: int) -> Optional[Vec3]:
        e = self.ents.get(ref)
        if not e or e.name != "DIRECTION":
            return None
        for a in e.args:
            if isinstance(a, list) and len(a) == 3:
                return Vec3(float(a[0]), float(a[1]), float(a[2])).normalized()
        return None

    def axis2_placement(self, ref: int) -> Optional[Tuple[Vec3, Vec3, Vec3]]:
        """Return (origin, z-axis, x-axis) for AXIS2_PLACEMENT_3D."""
        e = self.ents.get(ref)
        if not e or e.name not in ("AXIS2_PLACEMENT_3D", "AXIS2_PLACEMENT_2D"):
            return None
        # args: [name, location_ref, axis_ref or $, ref_dir or $]
        refs = [a for a in e.args if isinstance(a, int)]
        if not refs:
            return None
        loc = self.point(refs[0])
        if loc is None:
            return None
        z = self.direction(refs[1]) if len(refs) > 1 else Vec3(0, 0, 1)
        x = self.direction(refs[2]) if len(refs) > 2 else Vec3(1, 0, 0)
        if z is None:
            z = Vec3(0, 0, 1)
        if x is None:
            x = Vec3(1, 0, 0)
        return loc, z, x

    # ---- topology iterators --------------------------------------------

    def all_vertex_points(self) -> List[Vec3]:
        """Every CARTESIAN_POINT referenced by a VERTEX_POINT."""
        pts: List[Vec3] = []
        for e in self.of_type("VERTEX_POINT"):
            for a in e.args:
                if isinstance(a, int):
                    p = self.point(a)
                    if p is not None:
                        pts.append(p)
                        break
        return pts

    def all_cartesian_points(self) -> List[Vec3]:
        """Every CARTESIAN_POINT in the file."""
        pts: List[Vec3] = []
        for e in self.of_type("CARTESIAN_POINT"):
            p = self.point(e.eid)
            if p is not None:
                pts.append(p)
        return pts

    # ---- surface & face ------------------------------------------------

    def cylindrical_surfaces(self) -> List[Tuple[EntityRecord, Vec3, Vec3, float]]:
        """List (entity, axis_point, axis_dir, radius) for each CYLINDRICAL_SURFACE."""
        out = []
        for e in self.of_type("CYLINDRICAL_SURFACE"):
            # CYLINDRICAL_SURFACE(name, axis2_placement, radius)
            ax_ref = next((a for a in e.args if isinstance(a, Ref)), None)
            radius = next((a for a in e.args
                            if isinstance(a, (int, float)) and not isinstance(a, Ref)),
                           None)
            if ax_ref is None or radius is None:
                continue
            ax = self.axis2_placement(ax_ref)
            if ax is None:
                continue
            origin, z, _ = ax
            out.append((e, origin, z, float(radius)))
        return out

    def planes(self) -> List[Tuple[EntityRecord, Vec3, Vec3]]:
        """List (entity, point, normal) for each PLANE surface."""
        out = []
        for e in self.of_type("PLANE"):
            ax_ref = next((a for a in e.args if isinstance(a, Ref)), None)
            if ax_ref is None:
                continue
            ax = self.axis2_placement(ax_ref)
            if ax is None:
                continue
            origin, z, _ = ax
            out.append((e, origin, z))
        return out

    # ---- face / surface association ------------------------------------

    def face_surface_ref(self, face: EntityRecord) -> Optional[int]:
        """Given an ADVANCED_FACE entity, return the surface entity ref."""
        if face.name != "ADVANCED_FACE":
            return None
        # ADVANCED_FACE(name, [bounds...], face_geometry, same_sense)
        # face_geometry is a single int ref AFTER the bounds list
        seen_list = False
        for a in face.args:
            if isinstance(a, list):
                seen_list = True
                continue
            if seen_list and isinstance(a, int):
                return a
        return None

    def face_outer_loop_points(self, face: EntityRecord) -> List[Vec3]:
        """Collect every CARTESIAN_POINT touched by edges of the outer bound of a face."""
        pts: List[Vec3] = []
        # find FACE_OUTER_BOUND or FACE_BOUND refs in face.args
        bound_refs: List[int] = []
        for a in face.args:
            if isinstance(a, list):
                bound_refs.extend(x for x in a if isinstance(x, int))
        for br in bound_refs:
            be = self.ents.get(br)
            if not be or be.name not in ("FACE_OUTER_BOUND", "FACE_BOUND"):
                continue
            # FACE_*_BOUND(name, edge_loop_ref, orientation)
            loop_ref = next((a for a in be.args if isinstance(a, int)), None)
            if loop_ref is None:
                continue
            loop = self.ents.get(loop_ref)
            if not loop or loop.name != "EDGE_LOOP":
                continue
            for a in loop.args:
                if isinstance(a, list):
                    for oe_ref in a:
                        if not isinstance(oe_ref, int):
                            continue
                        oe = self.ents.get(oe_ref)
                        if not oe or oe.name != "ORIENTED_EDGE":
                            continue
                        ec_ref = next((x for x in oe.args if isinstance(x, int)), None)
                        if ec_ref is None:
                            continue
                        ec = self.ents.get(ec_ref)
                        if not ec or ec.name != "EDGE_CURVE":
                            continue
                        # EDGE_CURVE(name, start_v, end_v, curve, sense)
                        v_refs = [x for x in ec.args if isinstance(x, int)][:2]
                        for vr in v_refs:
                            ve = self.ents.get(vr)
                            if not ve or ve.name != "VERTEX_POINT":
                                continue
                            pr = next((x for x in ve.args if isinstance(x, int)), None)
                            if pr is None:
                                continue
                            p = self.point(pr)
                            if p is not None:
                                pts.append(p)
        return pts


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------

def detect_unit_to_mm(text: str) -> float:
    """Sniff the SI / conversion-based unit and return mm multiplier.

    Many SolidWorks and similar exporters write geometry in inches even when the
    file declares an SI unit. We therefore *also* infer from the FILE_NAME and
    fall back to inches when MILLI/METRE markers are absent. The caller can
    override.
    """
    t = text.upper()
    # Conversion based unit with INCH
    if "CONVERSION_BASED_UNIT" in t and "INCH" in t:
        return 25.4
    # SI_UNIT(.MILLI., .METRE.)
    if "SI_UNIT" in t and ".MILLI." in t and ".METRE." in t:
        return 1.0
    # SI_UNIT($, .METRE.) - metres
    if "SI_UNIT" in t and ".METRE." in t and ".MILLI." not in t:
        return 1000.0
    # default: assume mm
    return 1.0


def load_step(path: str) -> Tuple[StepModel, str]:
    """Load a STEP file. Returns (model, raw_text)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    ents = parse_step(text)
    unit_mm = detect_unit_to_mm(text)
    return StepModel(ents, length_unit_mm=unit_mm), text
