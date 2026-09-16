import json
from pathlib import Path
import cadquery as cq
import pytest
from core.iges import convert_iges,read_iges,metrics
from core.conversion import isolated_convert


def shape_for(kind):
    if kind=='pocket':
        return cq.Solid.makeBox(100,60,10).cut(cq.Solid.makeCylinder(8,5,(40,25,7)))
    if kind=='curved':
        return cq.Solid.makeTorus(60,8)
    if kind=='saddle':
        tube=cq.Solid.makeCylinder(25,180).cut(cq.Solid.makeCylinder(21,180))
        return tube.cut(cq.Solid.makeCylinder(30,100,(-50,0,180),(1,0,0)))
    return cq.Compound.makeCompound([cq.Solid.makeBox(10,20,30),cq.Solid.makeBox(7,9,11).translate((100,50,-20))])


@pytest.mark.parametrize('kind',['pocket','curved','saddle','assembly'])
def test_iges_roundtrip_geometry(tmp_path,kind):
    shape=shape_for(kind).rotate((0,0,0),(1,2,3),27).translate((123,-456,789))
    source=tmp_path/'part.step';shape.exportStep(str(source));out=tmp_path/'part.igs'
    row=convert_iges(source,out)
    assert row['readback']=='passed'
    restored=cq.Shape.cast(read_iges(out.read_bytes()))
    assert len(restored.Solids())==len(shape.Solids())
    # Independent geometric comparison, not only volume/bounds equality.
    assert shape.cut(restored).Volume()<.01
    assert restored.cut(shape).Volume()<.01


def test_iges_atomic_no_overwrite_and_invalid_source(tmp_path):
    src=tmp_path/'bad.step';src.write_text('not STEP')
    out=tmp_path/'part.iges';out.write_bytes(b'original')
    with pytest.raises(FileExistsError):convert_iges(src,out)
    with pytest.raises(ValueError):convert_iges(src,out,force=True)
    assert out.read_bytes()==b'original'


def test_iges_worker_unicode_paths_and_inch_units(tmp_path):
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone
    src=tmp_path/'part.step';writer=STEPControl_Writer()
    Interface_Static.SetCVal_s('write.step.unit','INCH')
    try:
        writer.Transfer(cq.Solid.makeBox(1,2,3).wrapped,STEPControl_AsIs)
        assert writer.Write(str(src))==IFSelect_RetDone
    finally:Interface_Static.SetCVal_s('write.step.unit','MM')
    assert 'INCH' in src.read_text()
    unicode_source=tmp_path/'模型 part.step';src.rename(unicode_source)
    out=tmp_path/'模型 part.igs'
    row=isolated_convert(unicode_source,out,output_format='iges')
    assert row['status']=='ok',row
    assert row['output_geometry']['bounds_mm']==pytest.approx([0,0,0,25.4,50.8,76.2],abs=.001)


def test_iges_cli_preserves_hierarchy(tmp_path):
    from main import cli_convert
    source=tmp_path/'input'/'sub';source.mkdir(parents=True)
    cq.Solid.makeBox(12,23,34).exportStep(str(source/'part.step'))
    out=tmp_path/'output';report=tmp_path/'report.json'
    assert cli_convert([str(source.parent)],str(out),recursive=True,output_format='iges',report=report)==0
    assert (out/'sub/part.igs').exists()
    data=json.loads(report.read_text());assert data['format']=='iges' and data['converted']==1
    assert not list(out.rglob('*.nc1'))
