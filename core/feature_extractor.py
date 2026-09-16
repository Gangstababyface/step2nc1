"""Editable manufacturing features. All feature coordinates are millimetres."""
from dataclasses import dataclass, field
from typing import List
from .section_detector import SectionResult

@dataclass
class Hole:
    surface: str
    x_mm: float
    y_mm: float
    diameter_mm: float
    slotted: bool = False
    slot_length_mm: float = 0.0  # overall tip-to-tip length
    slot_angle_deg: float = 0.0
    note: str = ""
    depth_mm: float = 0.0
    operation: str = ""         # blank=through, m=point mark, g/l=thread, s=countersink
    reference: str = "u"
    slot_width_mm: float = 0.0  # imported DSTV b/h (centre spacing), if provided
    slot_height_mm: float = 0.0

@dataclass
class ContourPoint:
    surface: str
    x_mm: float
    y_mm: float
    radius_mm: float = 0.0     # signed radius of outgoing arc
    reference: str = "u"
    modifier: str = ""         # t/w legacy notch accessory
    bevel_angle_1: float = 0.0
    bevel_depth_1: float = 0.0
    bevel_angle_2: float = 0.0
    bevel_depth_2: float = 0.0

@dataclass
class Marking:
    surface: str
    x_mm: float
    y_mm: float
    angle_deg: float = 0.0
    text: str = ""
    height_mm: float = 10.0
    reference: str = "u"
    mode: str = ""

@dataclass
class EndCut:
    web_start_deg: float = 0.0
    web_end_deg: float = 0.0
    flange_start_deg: float = 0.0
    flange_end_deg: float = 0.0

@dataclass
class FeatureSet:
    section: SectionResult
    holes: List[Hole] = field(default_factory=list)
    outer_contour: List[ContourPoint] = field(default_factory=list) # legacy single contour
    inner_contours: List[List[ContourPoint]] = field(default_factory=list)
    markings: List[Marking] = field(default_factory=list)
    end_cuts: EndCut = field(default_factory=EndCut)
    outer_contours: List[List[ContourPoint]] = field(default_factory=list)
    powder_contours: List[List[ContourPoint]] = field(default_factory=list)
    scribe_contours: List[List[ContourPoint]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)
    extra_blocks: list = field(default_factory=list)

    def all_outer_contours(self):
        return ([self.outer_contour] if self.outer_contour else []) + self.outer_contours


def extract_features(model, sec):
    from .cad_geometry import extract
    return extract(model, sec)
