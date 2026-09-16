"""Section measurements; the CAD backend keeps one millimetre part frame."""
from dataclasses import dataclass, field
from typing import List
from .geometry import BBox, Vec2
from .profiles import Profile

@dataclass
class SectionResult:
    family: str
    profile: Profile
    length_axis: int
    length_dir_sign: int
    length_in: float
    bbox: BBox
    cross_polys: List[List[Vec2]] = field(default_factory=list)
    notes: str = ""
    frame: dict = field(default_factory=dict)
    paint_per_m: float = 0.0


def detect_section(model, override_family=None, profiles=None):
    from .cad_geometry import analyse_section
    return analyse_section(model, override_family, profiles)
