"""STEP import through Open CASCADE (CadQuery). Units/placements are handled by OCC."""
from dataclasses import dataclass
from pathlib import Path

class StepParseError(ValueError):
    pass

@dataclass
class StepModel:
    shape: object
    path: str
    length_unit_mm: float = 1.0
    normalized_shape: object = None
    length_axis_override: str = "auto"
    section_sample: float = 0.0


def load_step(path, length_axis="auto"):
    try:
        import cadquery as cq
    except ImportError as exc:
        raise StepParseError("CAD engine missing. Run: python -m pip install -r requirements.txt") from exc
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.suffix.lower() not in (".step", ".stp"):
        raise StepParseError("Choose a .step or .stp file")
    try:
        imported = cq.importers.importStep(str(p))
        solids = imported.solids().vals()
    except Exception as exc:
        raise StepParseError(f"Open CASCADE could not read {p.name}: {exc}") from exc
    if len(solids) != 1:
        raise StepParseError(f"Expected one solid structural member; found {len(solids)}. Export each part separately.")
    solid = solids[0]
    if not solid.isValid() or solid.Volume() <= 1e-6:
        raise StepParseError("The imported solid is invalid or empty. Repair the source model first.")
    return StepModel(solid, str(p.resolve()), length_axis_override=length_axis), ""
