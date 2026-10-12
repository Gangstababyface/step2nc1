"""Single-solid STEP/IGES import for bounded NC1 analysis."""
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
    try:
        from .cad_import import read_geometry
        from .iges import metrics, reconstruct_solids
        shape = read_geometry(p)
        metrics(shape)
        if p.suffix.lower() in ('.igs', '.iges'):
            from OCP.ShapeCustom import ShapeCustom
            # IGES represents analytic cylinders as surfaces of revolution.
            # OCCT restores their equivalent elementary surfaces without fitting
            # splines, inventing missing cuts or changing the exchange file.
            shape = ShapeCustom.SweptToElementary_s(shape)
            metrics(shape)
        imported = cq.Shape.cast(shape)
        solids = imported.Solids()
        if p.suffix.lower() in ('.igs', '.iges') and not solids:
            # Closed surface models can be analysed without guessing missing faces.
            # Do not increase the 0.001 mm tolerance to force an open model closed.
            imported = cq.Shape.cast(reconstruct_solids(shape))
            solids = imported.Solids()
        if sum(len(s.Faces()) for s in solids) != len(imported.Faces()):
            raise ValueError('The model contains surfaces outside its solids.')
    except Exception as exc:
        raise StepParseError(f"Open CASCADE could not read {p.name}: {exc}") from exc
    if len(solids) != 1:
        raise StepParseError(f"Expected one solid structural member; found {len(solids)}. Export each part separately.")
    solid = solids[0]
    if not solid.isValid() or solid.Volume() <= 1e-6:
        raise StepParseError("The imported solid is invalid or empty. Repair the source model first.")
    return StepModel(solid, str(p.resolve()), length_axis_override=length_axis), ""
