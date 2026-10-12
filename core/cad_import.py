"""CAD exchange readers. Units and source placement are retained in millimetres."""
import io
from pathlib import Path

CAD_EXTENSIONS = ('.step', '.stp', '.igs', '.iges')
CAD_FILETYPES = [('STEP / IGES', '*.step *.stp *.STEP *.STP *.igs *.iges *.IGS *.IGES')]


def read_geometry(path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix not in CAD_EXTENSIONS:
        raise ValueError('Choose a .step, .stp, .igs or .iges file.')
    if suffix in ('.igs', '.iges'):
        from .iges import read_iges
        return read_iges(path.read_bytes())
    reader = STEPControl_Reader()
    # Reading bytes avoids OCCT filename encoding problems on Windows.
    if reader.ReadStream('source.step', io.BytesIO(path.read_bytes())) != IFSelect_RetDone:
        raise ValueError('STEP file could not be read.')
    reader.SetSystemLengthUnit(1.0)
    if reader.TransferRoots() == 0:
        raise ValueError('STEP contains no transferable geometry.')
    return reader.OneShape()
