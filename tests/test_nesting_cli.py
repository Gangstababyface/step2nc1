import json
from pathlib import Path
import pytest
from core.dstv_plus import Nest,NestPart,render_ba
from core.dstv_writer import write_nc1,NC1Header
from core.conversion import isolated_convert
from test_conversion import analyze,beam


def test_ba_fields_and_stock_accounting(tmp_path):
    write_nc1(analyze(beam()),tmp_path/'PART.nc1',NC1Header(steel_quality='A992'))
    n=Nest('TEST','RUN1',2500,[NestPart('PART.nc1',2)],kerf_mm=3,front_trim_mm=10,end_trim_mm=20)
    text,summary=render_ba(n,tmp_path);lines=text.splitlines()
    assert lines[0]=='BA';assert lines[22]=='PI'
    assert len(lines[23].strip().split(';'))==14
    assert summary['used_mm']==2036
    n.stock_length_mm=2000
    with pytest.raises(ValueError,match='requires'):render_ba(n,tmp_path)


def test_mixed_nest_material_rejected(tmp_path):
    for name,grade in [('A','A36'),('B','A992')]:write_nc1(analyze(beam()),tmp_path/(name+'.nc1'),NC1Header(steel_quality=grade))
    with pytest.raises(ValueError,match='same profile'):render_ba(Nest('T','R',3000,[NestPart('A.nc1'),NestPart('B.nc1')]),tmp_path)


def test_isolated_worker_and_no_overwrite(tmp_path):
    source=tmp_path/'a.step';beam().exportStep(str(source));out=tmp_path/'a.nc1'
    assert isolated_convert(source,out,project=True)['status']=='ok'
    assert out.with_suffix('.step2nc.json').exists()
    previous=out.read_bytes()
    result=isolated_convert(source,out)
    assert result['status']=='error';assert out.read_bytes()==previous


def test_bad_input_does_not_kill_worker(tmp_path):
    source=tmp_path/'bad.step';source.write_text('invalid STEP file')
    result=isolated_convert(source,tmp_path/'bad.nc1')
    assert result['status']=='error'
    assert not (tmp_path/'bad.nc1').exists()
