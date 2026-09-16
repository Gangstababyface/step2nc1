"""STEP to IGES B-rep exchange, independent of NC1 profile/feature limits."""
import io
import math
import os
from pathlib import Path
import tempfile


def metrics(shape):
    import cadquery as cq
    from OCP.BRepCheck import BRepCheck_Analyzer
    if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError('Invalid or empty CAD shape.')
    body=cq.Shape.cast(shape)
    if not body.Faces():raise ValueError('The model contains no faces to export.')
    box=body.BoundingBox()
    result={'solids':len(body.Solids()),'faces':len(body.Faces()),
            'area_mm2':body.Area(),'volume_mm3':sum(s.Volume() for s in body.Solids()),
            'bounds_mm':[box.xmin,box.ymin,box.zmin,box.xmax,box.ymax,box.zmax]}
    if not all(math.isfinite(v) for v in [result['area_mm2'],result['volume_mm3'],*result['bounds_mm']]):
        raise ValueError('The model has non-finite geometry measurements.')
    return result


def read_iges(data):
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    reader=IGESControl_Reader()
    # OCCT 7.8 IGES reader does not implement the inherited ReadStream method.
    with tempfile.TemporaryDirectory(prefix='step2nc1-iges-') as directory:
        path=Path(directory)/'model.igs';path.write_bytes(data)
        if reader.ReadFile(str(path))!=IFSelect_RetDone or reader.TransferRoots()==0:
            raise ValueError('IGES readback failed.')
    return reader.OneShape()


def convert_iges(path,out,force=False):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IGESControl import IGESControl_Writer
    from OCP.IFSelect import IFSelect_RetDone
    path=Path(path);out=Path(out)
    if path.suffix.lower() not in ('.step','.stp'):raise ValueError('IGES conversion requires a STEP source file.')
    if out.suffix.lower() not in ('.igs','.iges'):raise ValueError('IGES output must use .igs or .iges.')
    if path.resolve()==out.resolve():raise ValueError('Output cannot replace the source.')
    if out.exists() and not force:raise FileExistsError(f'{out} exists; use --force to replace it.')
    reader=STEPControl_Reader()
    if reader.ReadStream('source.step',io.BytesIO(path.read_bytes()))!=IFSelect_RetDone:
        raise ValueError('STEP file could not be read.')
    reader.SetSystemLengthUnit(1.0)  # millimetres; STEP source units are converted during transfer
    if reader.TransferRoots()==0:raise ValueError('STEP contains no transferable geometry.')
    shape=reader.OneShape();before=metrics(shape)
    writer=IGESControl_Writer('MM',1)  # IGES boundary-representation mode, including solids
    if not writer.AddShape(shape):raise ValueError('IGES writer rejected the model.')
    stream=io.BytesIO()
    if not writer.Write(stream):raise ValueError('IGES writer failed.')
    data=stream.getvalue();after=metrics(read_iges(data))
    if before['solids']!=after['solids']:raise ValueError('IGES readback changed the solid count.')
    for field in ('area_mm2','volume_mm3'):
        if not math.isclose(before[field],after[field],rel_tol=1e-5,abs_tol=1e-3):
            raise ValueError(f'IGES readback changed {field}.')
    if any(abs(a-b)>.01 for a,b in zip(before['bounds_mm'],after['bounds_mm'])):
        raise ValueError('IGES readback changed the model bounds by more than 0.01 mm.')
    out.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+out.name+'.',suffix='.tmp',dir=out.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(data);handle.flush();os.fsync(handle.fileno())
        if force:os.replace(temp,out)
        elif os.name=='nt':os.rename(temp,out)
        else:os.link(temp,out);os.unlink(temp)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return {'source':str(path),'output':str(out),'status':'ok','format':'iges',
            'source_geometry':before,'output_geometry':after,'readback':'passed',
            'warnings':['Geometry only. NC1 editor changes, manufacturing data, colors and assembly names are not exported.']}
