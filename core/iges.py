"""STEP to IGES trimmed-surface exchange, independent of NC1 profile/feature limits."""
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
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    volumes=[]
    for solid in body.Solids():
        props=GProp_GProps()
        BRepGProp.VolumeProperties_s(solid.wrapped,props,1e-8,True,False)
        volumes.append(props.Mass())
    result={'solids':len(body.Solids()),'faces':len(body.Faces()),
            'area_mm2':body.Area(),'volume_mm3':sum(volumes),
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


def reconstruct_solids(shape):
    """Sew readback faces for validation only; the exported file stays surfaces."""
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    # IGES trimming curves carry approximation tolerances (about 0.00032 mm
    # on the accepted diagnostic). Sew within 0.001 mm, below the 0.01 mm
    # dimensional gate, then independently check reconstructed volume.
    sewing=BRepBuilderAPI_Sewing(1e-3)
    faces=cq.Shape.cast(shape).Faces()
    for face in faces:sewing.Add(face.wrapped)
    sewing.Perform()
    stitched=cq.Shape.cast(sewing.SewedShape())
    shells=stitched.Shells()
    if not shells or sum(len(s.Faces()) for s in shells)!=len(faces):
        raise ValueError('IGES readback contains unsewn faces.')
    if any(not shell.Closed() for shell in shells):
        raise ValueError('IGES readback contains an open shell.')
    solids=[cq.Solid(ShapeFix_Solid().SolidFromShell(shell.wrapped)) for shell in shells]
    result=cq.Compound.makeCompound(solids).wrapped
    metrics(result)  # Reject invalid reconstruction.
    return result


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
    import cadquery as cq
    from OCP.Interface import Interface_Static
    writer=IGESControl_Writer('MM',0)
    # Matches the A diagnostic accepted in TubesT: individual trimmed faces,
    # B-spline planes, millimetres. Restore OCCT's process-global setting.
    previous=Interface_Static.IVal_s('write.iges.plane.mode')
    try:
        if not Interface_Static.SetIVal_s('write.iges.plane.mode',1):
            raise ValueError('IGES plane configuration failed.')
        for face in cq.Shape.cast(shape).Faces():
            if not writer.AddShape(face.wrapped):raise ValueError('IGES writer rejected a face.')
        stream=io.BytesIO()
        if not writer.Write(stream):raise ValueError('IGES writer failed.')
    finally:
        Interface_Static.SetIVal_s('write.iges.plane.mode',previous)
    data=stream.getvalue();restored=read_iges(data);after=metrics(restored)
    if before['faces']!=after['faces']:raise ValueError('IGES readback changed the face count.')
    if not math.isclose(before['area_mm2'],after['area_mm2'],rel_tol=1e-5,abs_tol=1e-3):
        raise ValueError('IGES readback changed area_mm2.')
    if any(abs(a-b)>.01 for a,b in zip(before['bounds_mm'],after['bounds_mm'])):
        raise ValueError('IGES readback changed the model bounds by more than 0.01 mm.')
    reconstructed=None
    if before['solids']:
        reconstructed=metrics(reconstruct_solids(restored))
        if before['solids']!=reconstructed['solids']:
            raise ValueError('IGES sewn readback changed the solid count.')
        if not math.isclose(before['volume_mm3'],reconstructed['volume_mm3'],rel_tol=1e-5,abs_tol=1e-3):
            raise ValueError('IGES sewn readback changed volume_mm3.')
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
            'encoding':'trimmed-surfaces','reconstructed_geometry':reconstructed,
            'warnings':['Geometry only. NC1 editor changes, manufacturing data, colors and assembly names are not exported.']}
