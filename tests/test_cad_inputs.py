"""Customer CAD input contract; generated fixtures contain no customer data."""
import io
import json
from pathlib import Path

import cadquery as cq
import pytest
from OCP.IGESControl import IGESControl_Writer
from OCP.Interface import Interface_Static

from core.cad_import import read_geometry
from core.conversion import isolated_convert
from core.diagnostics import diagnose
from core.dstv_reader import read_nc1
from core.iges import convert_iges, metrics, read_iges
from core.step_reader import load_step
from main import cli_convert, expand_inputs


def iges_bytes(shape, units='MM', solid=False, plane_mode=0):
    writer = IGESControl_Writer(units, int(solid))
    previous = Interface_Static.IVal_s('write.iges.plane.mode')
    try:
        assert Interface_Static.SetIVal_s('write.iges.plane.mode', plane_mode)
        if solid:
            assert writer.AddShape(shape.wrapped)
        else:
            for face in shape.Faces():
                assert writer.AddShape(face.wrapped)
        stream = io.BytesIO()
        assert writer.Write(stream)
        return stream.getvalue()
    finally:
        Interface_Static.SetIVal_s('write.iges.plane.mode', previous)


def plate():
    return cq.Solid.makeBox(254, 50.8, 6.35).cut(
        cq.Solid.makeCylinder(5, 10, (100, 25, -2), (0, 0, 1)))


@pytest.mark.parametrize('suffix', ['.igs', '.IGES'])
@pytest.mark.parametrize('solid', [False, True])
def test_iges_input_nc1_normalized_units_and_hole(tmp_path, suffix, solid):
    source = tmp_path / ('inch part' + suffix)
    shape = plate().rotate((0, 0, 0), (1, 2, 3), 17).translate((100, -80, 200))
    source.write_bytes(iges_bytes(shape, 'INCH', solid))
    assert b'INCH' in source.read_bytes()
    out = tmp_path / 'part.nc1'
    row = isolated_convert(source, out, material='TEST', project=True)
    assert row['status'] == 'ok', row
    result = read_nc1(out)
    assert result.features.section.length_in * 25.4 == pytest.approx(254, abs=.001)
    assert result.features.section.profile.d_mm == pytest.approx(50.8, abs=.001)
    assert result.features.section.profile.bf_mm == pytest.approx(6.35, abs=.001)
    assert len(result.features.holes) == 1
    assert result.features.holes[0].diameter_mm == pytest.approx(10, abs=.001)


def test_original_iges_is_byte_preserved_including_units_and_placement(tmp_path):
    source = tmp_path / 'SolidWorks style.IGS'
    shape = plate().translate((-21783, 175148, -30))
    original = iges_bytes(shape, 'INCH')
    source.write_bytes(original)
    out = tmp_path / 'output' / 'part.igs'
    row = isolated_convert(source, out, output_format='iges')
    assert row['status'] == 'ok', row
    assert row['encoding'] == 'source-preserved'
    assert row['source_preserved'] is True
    assert out.read_bytes() == original == source.read_bytes()
    assert row['output_geometry']['bounds_mm'] == pytest.approx(
        metrics(shape.wrapped)['bounds_mm'], abs=.001)


def test_open_surface_is_preserved_for_iges_but_never_guessed_for_nc1(tmp_path):
    shape = cq.Solid.makeBox(10, 20, 30)
    source = tmp_path / 'open.igs'
    source.write_bytes(iges_bytes(cq.Compound.makeCompound(shape.Faces()[:-1])))
    assert convert_iges(source, tmp_path / 'copy.igs')['source_preserved']
    result = isolated_convert(source, tmp_path / 'open.nc1')
    assert result['status'] == 'error'
    assert result['diagnostic']['code'] == 'OPEN_IGES'
    assert not (tmp_path / 'open.nc1').exists()


def test_iges_assembly_rejected_only_for_nc1(tmp_path):
    shape = cq.Compound.makeCompound([
        cq.Solid.makeBox(10, 20, 30), cq.Solid.makeBox(10, 20, 30).translate((100, 0, 0))])
    source = tmp_path / 'assembly.iges'
    source.write_bytes(iges_bytes(shape))
    with pytest.raises(ValueError, match='Expected one solid'):
        load_step(source)
    assert convert_iges(source, tmp_path / 'copy.igs')['source_preserved']


def test_iges_invalid_or_same_source_never_overwrites(tmp_path):
    source = tmp_path / 'invalid.igs'; source.write_bytes(b'not IGES')
    target = tmp_path / 'existing.igs'; target.write_bytes(b'keep me')
    with pytest.raises(ValueError):
        convert_iges(source, source, force=True)
    with pytest.raises(ValueError):
        convert_iges(source, target, force=True)
    assert target.read_bytes() == b'keep me'
    assert source.read_bytes() == b'not IGES'


def test_recursive_mixed_cad_batch_and_safe_iges_names(tmp_path):
    inputs = tmp_path / 'input'; inputs.mkdir()
    (inputs / 'sub').mkdir()
    cq.Solid.makeBox(100, 50, 6).exportStep(str(inputs / 'one.STP'))
    source = inputs / 'sub' / 'two.IGES'
    source.write_bytes(iges_bytes(plate(), 'INCH'))
    (inputs / 'ignore.txt').write_text('not CAD')
    assert len(expand_inputs([str(inputs)], recursive=True)) == 2
    output = tmp_path / 'output'; report = tmp_path / 'report.json'
    assert cli_convert([str(inputs)], output, recursive=True, output_format='iges', report=report) == 0
    assert (output / 'one.igs').is_file()
    assert (output / 'sub' / 'two_TubeST.igs').read_bytes() == source.read_bytes()
    assert json.loads(report.read_text())['converted'] == 2
    assert cli_convert([str(source)], output_format='iges') == 0
    assert source.with_name('two_TubeST.igs').read_bytes() == source.read_bytes()
    assert cli_convert([str(source)], output_format='iges') == 1


def test_step_unicode_filename_uses_byte_reader(tmp_path):
    source = tmp_path / '模型 part.STEP'
    plate().exportStep(str(tmp_path / 'part.step'))
    (tmp_path / 'part.step').rename(source)
    assert metrics(read_geometry(source))['bounds_mm'] == pytest.approx([0, 0, 0, 254, 50.8, 6.35])


def test_unicode_iges_input_can_open_but_nc1_headers_need_ascii(tmp_path):
    source = tmp_path / '模型 part.IGES'
    source.write_bytes(iges_bytes(plate(), 'INCH'))
    assert load_step(source)[0].shape.Volume() == pytest.approx(plate().Volume())
    result = isolated_convert(source, tmp_path / 'part.nc1', project=True)
    assert result['diagnostic']['code'] == 'HEADER_TEXT'
    assert not (tmp_path / 'part.nc1').exists()
    assert (tmp_path / 'part.step2nc.json').is_file()


def test_spline_plane_iges_is_preserved_without_approximate_nc1(tmp_path):
    source = tmp_path / 'spline-plane.igs'
    source.write_bytes(iges_bytes(plate().rotate((0,0,0),(1,2,3),17), plane_mode=1))
    copy = tmp_path / 'copy.igs'
    assert convert_iges(source, copy)['source_preserved']
    assert copy.read_bytes() == source.read_bytes()
    result = isolated_convert(source, tmp_path / 'unsupported.nc1')
    assert result['status'] == 'error'
    assert 'BSPLINE' in result['error']
    assert not (tmp_path / 'unsupported.nc1').exists()


def test_installer_has_no_customer_dependency_or_confirmation_pages():
    setup = (Path(__file__).resolve().parents[1] / 'packaging' / 'installer.iss').read_text()
    for setting in ('PrivilegesRequired=lowest', 'DisableWelcomePage=yes', 'DisableDirPage=yes',
                    'DisableProgramGroupPage=yes', 'DisableReadyPage=yes', 'DisableFinishedPage=yes'):
        assert setting in setup
    assert 'recursesubdirs' in setup
    assert 'Filename: "{app}\\STEP2NC1.exe"' in setup
    assert '[UninstallDelete]' not in setup
