"""Lightweight 3D geometry primitives. Pure-Python, no numpy dependency required."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, o: "Vec3") -> "Vec3":
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o: "Vec3") -> "Vec3":
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __mul__(self, s: float) -> "Vec3":
        return Vec3(self.x * s, self.y * s, self.z * s)

    __rmul__ = __mul__

    def __neg__(self) -> "Vec3":
        return Vec3(-self.x, -self.y, -self.z)

    def dot(self, o: "Vec3") -> float:
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o: "Vec3") -> "Vec3":
        return Vec3(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> "Vec3":
        L = self.length()
        if L < 1e-12:
            return Vec3(0.0, 0.0, 0.0)
        return Vec3(self.x / L, self.y / L, self.z / L)

    def is_parallel(self, o: "Vec3", tol: float = 1e-6) -> bool:
        a = self.normalized()
        b = o.normalized()
        return abs(abs(a.dot(b)) - 1.0) < tol

    def angle_to(self, o: "Vec3") -> float:
        a, b = self.normalized(), o.normalized()
        d = max(-1.0, min(1.0, a.dot(b)))
        return math.degrees(math.acos(d))


X_AXIS = Vec3(1.0, 0.0, 0.0)
Y_AXIS = Vec3(0.0, 1.0, 0.0)
Z_AXIS = Vec3(0.0, 0.0, 1.0)
ORIGIN = Vec3(0.0, 0.0, 0.0)


@dataclass
class BBox:
    """Axis-aligned bounding box."""
    minp: Vec3 = field(default_factory=lambda: Vec3(math.inf, math.inf, math.inf))
    maxp: Vec3 = field(default_factory=lambda: Vec3(-math.inf, -math.inf, -math.inf))

    def expand(self, p: Vec3) -> None:
        self.minp = Vec3(min(self.minp.x, p.x), min(self.minp.y, p.y), min(self.minp.z, p.z))
        self.maxp = Vec3(max(self.maxp.x, p.x), max(self.maxp.y, p.y), max(self.maxp.z, p.z))

    def size(self) -> Vec3:
        return self.maxp - self.minp

    def center(self) -> Vec3:
        return Vec3(
            0.5 * (self.minp.x + self.maxp.x),
            0.5 * (self.minp.y + self.maxp.y),
            0.5 * (self.minp.z + self.maxp.z),
        )

    @property
    def dx(self) -> float: return self.maxp.x - self.minp.x

    @property
    def dy(self) -> float: return self.maxp.y - self.minp.y

    @property
    def dz(self) -> float: return self.maxp.z - self.minp.z

    def longest_axis(self) -> int:
        s = self.size()
        if s.x >= s.y and s.x >= s.z: return 0
        if s.y >= s.x and s.y >= s.z: return 1
        return 2

    @classmethod
    def from_points(cls, pts: Iterable[Vec3]) -> "BBox":
        b = cls()
        for p in pts:
            b.expand(p)
        return b


@dataclass
class Plane:
    """Plane defined by a point and outward normal."""
    point: Vec3
    normal: Vec3

    def signed_distance(self, p: Vec3) -> float:
        return (p - self.point).dot(self.normal.normalized())


@dataclass
class CylSurface:
    """A cylindrical surface (used to identify holes)."""
    axis_point: Vec3   # any point on the axis
    axis_dir: Vec3     # unit direction
    radius: float

    def axis_t(self, p: Vec3) -> float:
        """Parameter along the axis at the projection of p."""
        return (p - self.axis_point).dot(self.axis_dir.normalized())

    def project(self, p: Vec3) -> Vec3:
        d = self.axis_dir.normalized()
        return self.axis_point + d * self.axis_t(p)


# ---------- 2D helpers used for cross-section analysis ----------

@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def __sub__(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x - o.x, self.y - o.y)

    def __add__(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x + o.x, self.y + o.y)

    def length(self) -> float:
        return math.hypot(self.x, self.y)


def project_to_plane(p: Vec3, length_axis: int) -> Vec2:
    """Project a 3D point onto the cross-section plane perpendicular to length_axis."""
    if length_axis == 0:
        return Vec2(p.y, p.z)
    if length_axis == 1:
        return Vec2(p.x, p.z)
    return Vec2(p.x, p.y)


def angle_between_normals_deg(n1: Vec3, n2: Vec3) -> float:
    """Smallest angle between two normals (0 to 90)."""
    a = n1.normalized()
    b = n2.normalized()
    d = abs(a.dot(b))
    d = max(-1.0, min(1.0, d))
    return math.degrees(math.acos(d))


def in_to_mm(v: float) -> float:
    return v * 25.4


def mm_to_in(v: float) -> float:
    return v / 25.4
