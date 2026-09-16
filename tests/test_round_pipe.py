import math
import cadquery as cq
import pytest
from core.step_reader import StepModel
from core.section_detector import detect_section
from core.feature_extractor import extract_features
from core.dstv_writer import render_nc1
from core.dstv_reader import parse_nc1
from core.validation import ValidationError


def pipe():
    return cq.Solid.makeCylinder(50,1000,(0,50,50),(1,0,0)).cut(cq.Solid.makeCylinder(44,1002,(-1,50,50),(1,0,0)))


def analyze(shape):
    model=StepModel(shape,'pipe.step');sec=detect_section(model)
    return extract_features(model,sec)


def test_pipe_never_classified_as_rectangular_hss():
    fs=analyze(pipe())
    assert fs.section.family=='HSS_R'
    assert not fs.errors
    doc=parse_nc1(render_nc1(fs))
    assert doc.header.profile_code=='RO'
    p=doc.features.section.profile
    assert (p.d_mm,p.bf_mm,p.tf_mm,p.tw_mm,p.t_wall_mm)==pytest.approx((100,100,6,6,6))
    assert fs.section.paint_per_m==pytest.approx(math.pi*.1)
    assert fs.section.profile.kg_per_m==pytest.approx(math.pi*(50**2-44**2)*.00785)


@pytest.mark.parametrize('rotate',[False,True])
def test_pipe_miter_analytic_plane(rotate):
    # Remove x < y/4. The complete annular stock remains beyond x=25.
    cutter=cq.Workplane('XY',origin=(0,0,-1)).polyline([(-1,-1),(-.25,-1),(25.25,101),(-1,101)]).close().extrude(102).val()
    s=pipe().cut(cutter)
    if rotate:s=s.rotate((0,0,0),(1,2,3),37).translate((200,100,-50))
    fs=analyze(s)
    assert not fs.errors
    assert fs.section.family=='HSS_R'
    cuts=vars(fs.end_cuts)
    # Rotation may change the reference azimuth. The resultant slope is fixed.
    slope=math.sqrt(sum(math.tan(math.radians(a))**2 for a in cuts.values()))
    assert slope==pytest.approx(.25,abs=.00001)
    assert not fs.outer_contours


def test_pipe_bore_is_explicitly_rejected():
    fs=analyze(pipe().cut(cq.Solid.makeCylinder(10,120,(250,-10,50),(0,1,0))))
    assert fs.section.family=='HSS_R'
    assert fs.errors
    with pytest.raises(ValidationError,match='Round pipe'):render_nc1(fs)
