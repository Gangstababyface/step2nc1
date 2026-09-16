import math
from pathlib import Path
import pytest
import cadquery as cq
from core.step_reader import load_step,StepParseError,StepModel
from core.section_detector import detect_section
from core.feature_extractor import extract_features,Hole,Marking,ContourPoint
from core.dstv_writer import render_nc1,NC1Header,write_nc1,default_header_from_filename
from core.dstv_reader import parse_nc1
from core.project import save_project,load_project
from core.validation import ValidationError


def prism(points,length=1000):
    plane=cq.Plane(origin=(0,0,0),xDir=(0,1,0),normal=(1,0,0))
    return cq.Workplane(plane).polyline(points).close().extrude(length).val()


def beam(length=1000):
    d,w,tf,tw=200,100,10,6
    return prism([(0,0),(0,w),(tf,w),(tf,53),(190,53),(190,w),(d,w),(d,0),(190,0),(190,47),(tf,47),(tf,0)],length)


def tube(length=1000):
    return cq.Solid.makeBox(length,100,60).cut(cq.Solid.makeBox(length+2,88,48,(-1,6,6)))


def angle(length=1000):
    return prism([(0,0),(0,60),(6,60),(6,6),(100,6),(100,0)],length)


def analyze(shape):
    m=StepModel(shape,'fixture.step');s=detect_section(m);return extract_features(m,s)

@pytest.mark.parametrize('shape,family,d,w,t',[
    (beam(),'W',200,100,0),(tube(),'HSS',100,60,6),(angle(),'L',100,60,6),
    (prism([(0,0),(0,75),(10,75),(10,6),(190,6),(190,75),(200,75),(200,0)]),'C',200,75,0),
    (cq.Solid.makeBox(1000,100,8),'PLATE',100,8,8)])
def test_section_families(shape,family,d,w,t):
    f=analyze(shape);p=f.section.profile
    assert f.section.family==family
    assert (p.d_mm,p.bf_mm,p.t_wall_mm)==pytest.approx((d,w,t),abs=.001)
    assert not f.errors
    assert parse_nc1(render_nc1(f)).features.section.family==family


def test_web_and_both_flanges_not_deduplicated():
    s=beam().cut(cq.Solid.makeCylinder(10,120,(250,100,-10),(0,0,1)))
    s=s.cut(cq.Solid.makeCylinder(8,220,(400,-10,30),(0,1,0)))
    f=analyze(s)
    assert len(f.holes)==3
    assert {(h.surface,round(h.diameter_mm)) for h in f.holes}=={('v',20),('o',16),('u',16)}
    assert sorted(h.x_mm for h in f.holes)==pytest.approx([250,400,400])


def test_tube_front_back_bore_remain_separate():
    s=tube().cut(cq.Solid.makeCylinder(4,80,(250,30,-10),(0,0,1)))
    f=analyze(s)
    assert {h.surface for h in f.holes}=={'v','h'}
    assert len(f.holes)==2
    assert all(abs(h.diameter_mm-8)<.001 for h in f.holes)


def test_diameter_filters_removed():
    s=cq.Solid.makeBox(1000,200,10)
    for x,r in [(100,1.5),(500,50)]:s=s.cut(cq.Solid.makeCylinder(r,20,(x,100,-5),(0,0,1)))
    f=analyze(s);assert sorted(h.diameter_mm for h in f.holes)==pytest.approx([3,100])


def test_rotated_translated_units(tmp_path):
    s=angle().cut(cq.Solid.makeCylinder(5,20,(250,50,-5),(0,0,1)))
    s=s.rotate((0,0,0),(1,2,3),37).translate((10000,-4000,9000))
    p=tmp_path/'rotated.step';s.exportStep(str(p))
    m,_=load_step(p);sec=detect_section(m);f=extract_features(m,sec)
    assert sec.length_in*25.4==pytest.approx(1000,abs=.001)
    assert len(f.holes)==1
    assert f.holes[0].diameter_mm==pytest.approx(10,abs=.001)
    assert f.holes[0].x_mm==pytest.approx(250,abs=.001)
    assert f.holes[0].y_mm==pytest.approx(50,abs=.001)


def test_inch_step_import(tmp_path):
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    p=tmp_path/'inch.step'
    writer=STEPControl_Writer();old=Interface_Static.CVal_s('write.step.unit')
    try:
        Interface_Static.SetCVal_s('write.step.unit','INCH')
        writer.Transfer(beam().scale(1/25.4).wrapped,STEPControl_AsIs);writer.Write(str(p))
    finally:Interface_Static.SetCVal_s('write.step.unit',old or 'MM')
    assert 'INCH' in p.read_text()
    m,_=load_step(p);f=extract_features(m,detect_section(m))
    assert f.section.length_in*25.4==pytest.approx(1000,abs=.001)
    assert f.section.profile.d_mm==pytest.approx(200,abs=.001)


def test_cope_and_slot_are_real_contours():
    s=beam().cut(cq.Solid.makeBox(100,50,120,(0,160,-10)))
    slot=cq.Solid.makeBox(40,20,20,(300,90,40)).fuse(cq.Solid.makeCylinder(10,20,(300,100,40),(0,0,1))).fuse(cq.Solid.makeCylinder(10,20,(340,100,40),(0,0,1)))
    f=analyze(s.cut(slot))
    assert not f.errors
    assert any(len(c)>5 for c in f.outer_contours if c[0].surface=='v')
    assert any(min(p.x_mm for p in c)==pytest.approx(100,abs=.01) for c in f.outer_contours if c[0].surface=='o')
    assert len(f.inner_contours)==1
    from core.cad_geometry import contour_area
    assert sum(bool(p.radius_mm) for p in f.inner_contours[0])>=2
    assert abs(contour_area(f.inner_contours[0]))==pytest.approx(40*20+math.pi*10**2,abs=.001)


def test_blind_hole_blocks_export():
    s=cq.Solid.makeBox(1000,100,10).cut(cq.Solid.makeCylinder(5,4,(100,40,0),(0,0,1)))
    f=analyze(s)
    assert f.errors
    with pytest.raises(ValidationError):render_nc1(f)


def test_assembly_rejected(tmp_path):
    s=cq.Compound.makeCompound([beam(),beam().translate((0,300,0))]);p=tmp_path/'assembly.step';s.exportStep(str(p))
    with pytest.raises(StepParseError,match='found 2'):load_step(p)


def test_wall_header_and_paint_units():
    f=analyze(tube());d=parse_nc1(render_nc1(f))
    assert d.header.profile_code=='M'
    assert d.features.section.profile.tw_mm==pytest.approx(6)
    assert d.features.section.profile.tf_mm==pytest.approx(6)
    assert d.header.paint_per_m==pytest.approx(.320)
    long=analyze(tube(2000));assert parse_nc1(render_nc1(long)).header.paint_per_m==d.header.paint_per_m


def test_marking_and_slot_format():
    f=analyze(beam());f.markings=[Marking('v',100,100,90,'PART 42',12)]
    f.holes=[Hole('v',300,100,20,True,60,30)]
    text=render_nc1(f);d=parse_nc1(text)
    assert d.features.markings[0].text=='PART 42'
    assert d.features.markings[0].height_mm==12
    assert d.features.holes[0].slot_width_mm==40
    assert d.features.holes[0].slot_height_mm==0
    assert d.features.holes[0].x_mm==pytest.approx(300,abs=.001)
    assert d.features.holes[0].y_mm==pytest.approx(100,abs=.001)


def test_blank_mark_is_bo_not_powder_contour():
    f=analyze(beam());f.markings=[Marking('v',100,100)]
    text=render_nc1(f);assert '\nPU\n' not in text
    assert parse_nc1(text).features.holes[0].operation=='m'


def test_project_roundtrip_all_features(tmp_path):
    f=analyze(beam());f.markings=[Marking('v',10,20,text='A')];h=NC1Header(quantity=3,steel_quality='A992')
    p=tmp_path/'part.step2nc.json';save_project(p,f,h,'source.step');g,j,source=load_project(p)
    assert as_dict(f)==as_dict(g);assert j==h;assert source==str(tmp_path/'source.step')

def as_dict(obj):
    from dataclasses import asdict
    return asdict(obj)

@pytest.mark.parametrize('value',[math.nan,math.inf,-math.inf])
def test_nonfinite_no_file(tmp_path,value):
    f=analyze(beam());f.holes=[Hole('v',value,40,10)]
    p=tmp_path/'a.nc1'
    with pytest.raises(ValidationError):write_nc1(f,p)
    assert not p.exists()


def test_quantity_and_ascii_validation():
    f=analyze(beam())
    with pytest.raises(ValidationError):render_nc1(f,NC1Header(quantity=0))
    with pytest.raises(ValidationError):render_nc1(f,NC1Header(steel_quality='A992\nEN'))
    assert default_header_from_filename('9BA39x3.step').quantity==3
    assert default_header_from_filename('ab121 X22.step').piece_number=='ab121'


def test_comma_saw_length():
    f=analyze(beam());text=render_nc1(f,NC1Header(saw_length_mm=1050))
    text=text.replace('1000.000 1050.000','1000.000 , 1050.000')
    assert parse_nc1(text).header.saw_length_mm==1050


def test_export_failure_keeps_existing_file(tmp_path):
    f=analyze(beam());p=tmp_path/'old.nc1';p.write_text('original')
    f.holes=[Hole('v',2000,40,10)]
    with pytest.raises(ValidationError):write_nc1(f,p)
    assert p.read_text()=='original'


def test_partial_thickness_bevel_not_silently_flattened():
    s=cq.Solid.makeBox(1000,100,10)
    # A 45-degree weld chamfer along the upper half of one end.
    cutter=cq.Workplane(cq.Plane(origin=(0,-1,0),xDir=(1,0,0),normal=(0,-1,0))).polyline([(0,5),(5,10),(0,10)]).close().extrude(-102).val()
    f=analyze(s.cut(cutter))
    assert f.errors
    with pytest.raises(ValidationError):render_nc1(f)


def test_round_corner_tube_uses_full_nominal_faces():
    s=cq.Workplane('XY').box(1000,100,60,centered=False).edges('|X').fillet(12).val()
    inside=cq.Workplane('XY').box(1002,88,48,centered=False).edges('|X').fillet(6).val().translate((-1,6,6))
    f=analyze(s.cut(inside))
    assert not f.errors
    for c in f.outer_contours:
        span=100 if c[0].surface in ('v','h') else 60
        assert min(p.y_mm for p in c)==pytest.approx(0)
        assert max(p.y_mm for p in c)==pytest.approx(span)


def test_header_only_simple_miter():
    s=beam()
    # Start cut x = y * 0.25. Kept material is to the right of the plane.
    cutter=cq.Workplane('XY',origin=(0,0,-1)).polyline([(-1,-1),(0,-1),(51,204),(-1,204)]).close().extrude(102).val()
    f=analyze(s.cut(cutter))
    assert not f.errors
    assert abs(f.end_cuts.web_start_deg)>10
    assert not f.outer_contours
    assert parse_nc1(render_nc1(f)).features.end_cuts.web_start_deg==pytest.approx(f.end_cuts.web_start_deg,abs=.001)


def test_hss_inner_and_outer_radii_differ():
    s=cq.Workplane('XY').box(1000,100,60,centered=False).edges('|X').fillet(12).val()
    inside=cq.Workplane('XY').box(1002,88,48,centered=False).edges('|X').fillet(6).val().translate((-1,6,6))
    f=analyze(s.cut(inside));d=parse_nc1(render_nc1(f))
    assert d.features.section.profile.k_mm==pytest.approx(6)
    assert d.features.section.profile.outside_radius*25.4==pytest.approx(12)


@pytest.mark.parametrize('end',[False,True])
@pytest.mark.parametrize('falling',[False,True])
def test_miter_with_cope_uses_external_flange_envelope(end,falling):
    # Independently specified cut x = y/4 (or 50-y/4), mirrored for an end cut.
    # Coping the opposite end prevents header-only miter simplification.
    def boundary(y):
        x=50-y/4 if falling else y/4
        return 1000-x if end else x
    outside=1001 if end else -1
    cutter=cq.Workplane('XY',origin=(0,0,-1)).polyline([
        (outside,-1),(boundary(-1),-1),(boundary(201),201),(outside,201)
    ]).close().extrude(102).val()
    cope=cq.Solid.makeBox(100,40,102,(0 if end else 900,160,-1))
    f=analyze(beam().cut(cutter).cut(cope))
    assert not f.errors
    assert len(f.outer_contours)==3
    restored=parse_nc1(render_nc1(f)).features
    for surface,ys in [('o',(200,190)),('u',(0,10))]:
        contour=next(c for c in restored.outer_contours if c[0].surface==surface)
        bevels=[p for p in contour[:-1] if p.bevel_angle_1]
        assert len(bevels)==1
        p=bevels[0]
        external=(max if end else min)(boundary(y) for y in ys)
        assert p.x_mm==pytest.approx(external,abs=.001)
        external_on_current=abs(external-boundary(ys[0]))<1e-8
        expected_angle=math.degrees(math.atan(.25))*(-1 if external_on_current else 1)
        assert p.bevel_angle_1==pytest.approx(expected_angle,abs=.001)
        assert p.bevel_depth_1==pytest.approx(10 if external_on_current else 0,abs=.001)
        # Reconstruct the two physical skin edges from the serialized bevel.
        offset=10*math.tan(math.radians(abs(p.bevel_angle_1)))
        recessed=external+(-offset if end else offset)
        assert sorted([external,recessed])==pytest.approx(sorted(boundary(y) for y in ys),abs=.001)


@pytest.mark.parametrize('through',[False,True])
@pytest.mark.parametrize('depth,height',[(1.5,3),(.7,.1)])
def test_hidden_wall_cavity_is_not_lost(through,depth,height):
    s=cq.Solid.makeBox(200,50,6)
    if through:s=s.cut(cq.Solid.makeCylinder(5,10,(50,25,-2),(0,0,1)))
    s=s.cut(cq.Solid.makeCylinder(10,height,(50,25,depth),(0,0,1)))
    f=analyze(s)
    assert f.errors
    with pytest.raises(ValidationError,match='inside the wall thickness'):render_nc1(f)


def test_hidden_end_pocket_is_not_lost():
    s=cq.Solid.makeBox(200,50,6).cut(cq.Solid.makeBox(5,10,.1,(0,20,.7)))
    f=analyze(s)
    assert f.errors
    with pytest.raises(ValidationError,match='inside the wall thickness'):render_nc1(f)


def test_blind_bore_at_angle_junction_is_not_a_through_web_hole():
    s=angle().cut(cq.Solid.makeCylinder(1,8,(250,3,-1),(0,0,1)))
    f=analyze(s)
    assert f.errors
    with pytest.raises(ValidationError,match='stock extends beyond the nominal wall'):render_nc1(f)


def test_square_bar_with_round_axial_bore_is_not_rectangular_hss():
    s=cq.Solid.makeBox(1000,100,100).cut(cq.Solid.makeCylinder(40,1002,(-1,50,50),(1,0,0)))
    with pytest.raises(ValueError,match='Could not identify'):analyze(s)
