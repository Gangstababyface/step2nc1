"""Solid-model analysis of straight structural members, in one mm coordinate frame.

X is member length; Y is section depth; Z is section width. The source-to-part
transform is retained for review. Unsupported machining is reported, never
silently discarded. Open CASCADE resolves STEP units and assembly placements.
"""
import math
from collections import defaultdict
from dataclasses import replace
import cadquery as cq
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopAbs import TopAbs_REVERSED
from OCP.gp import gp_Trsf
from .geometry import BBox, Vec2, Vec3
from .profiles import make_custom_profile, match_profile
from .section_detector import SectionResult

EPS = 0.002
TOL = 0.025


def _vec(v):
    return (v.x, v.y, v.z)


def _positive(v):
    v = v.normalized()
    a = _vec(v)
    return v if a[max(range(3), key=lambda i: abs(a[i]))] >= 0 else v.multiply(-1)


def _directions(shape):
    groups = []
    for edge in shape.Edges():
        if edge.geomType() != 'LINE' or edge.Length() < 1e-5:
            continue
        v = _positive(edge.endPoint() - edge.startPoint())
        for g in groups:
            if abs(g[0].dot(v)) > .999999:
                g[1] += edge.Length() ** 2
                break
        else:
            groups.append([v, edge.Length() ** 2])
    # Circular stock may have no straight seam edges (trimmed periodic faces).
    # Its cylinder axis is still an exact analytic direction.
    for face in shape.Faces():
        if face.geomType()!='CYLINDER':continue
        axis=BRepAdaptor_Surface(face.wrapped).Cylinder().Axis().Direction()
        v=_positive(cq.Vector(axis.X(),axis.Y(),axis.Z()))
        b=face.BoundingBox();extent=sum(abs(a)*s for a,s in zip(_vec(v),(b.xlen,b.ylen,b.zlen)))
        for g in groups:
            if abs(g[0].dot(v))>.999999:g[1]+=extent**2;break
        else:groups.append([v,extent**2])
    return sorted(groups, key=lambda g: -g[1])


def _transform(shape, rows):
    trsf = gp_Trsf()
    trsf.SetValues(*[n for v in rows for n in list(_vec(v)) + [0]])
    matrix = cq.Matrix(trsf)
    s = shape.transformShape(matrix)
    b = s.BoundingBox()
    offset = (b.xmin, b.ymin, b.zmin)
    s = s.translate(tuple(-v for v in offset))
    return s, [list(_vec(v)) + [-offset[i]] for i, v in enumerate(rows)] + [[0, 0, 0, 1]]


def _slice(shape, axis, value):
    origin = [0., 0., 0.]; origin[axis] = value
    normal = [0., 0., 0.]; normal[axis] = 1
    return shape.intersect(cq.Face.makePlane(basePnt=tuple(origin), dir=tuple(normal)))


def _intervals(face, axis, x, y, z, extent):
    a = [x, y, z]; b = a[:]
    a[axis] = -1; b[axis] = extent + 1
    edges = face.intersect(cq.Edge.makeLine(tuple(a), tuple(b))).Edges()
    spans = sorted((min(_vec(e.startPoint())[axis], _vec(e.endPoint())[axis]),
                    max(_vec(e.startPoint())[axis], _vec(e.endPoint())[axis])) for e in edges)
    out = []
    for lo, hi in spans:
        if hi-lo < 1e-5: continue
        if out and lo <= out[-1][1] + TOL:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else: out.append((lo, hi))
    return out


def _kind(spans, size):
    if len(spans) == 1:
        a,b = spans[0]
        if a < TOL and b > size-TOL: return 'full'
        if a < TOL or b > size-TOL: return 'edge'
        return 'middle'
    if len(spans) == 2 and spans[0][0] < TOL and spans[-1][1] > size-TOL:
        return 'pair'
    return 'other'


def _measure(shape):
    b = shape.BoundingBox(); L,d,w = b.xlen,b.ylen,b.zlen
    candidates = []
    for frac in (.5,.23,.37,.61,.77,.13,.87):
        x = L*frac
        section = _slice(shape, 0, x)
        faces = section.Faces()
        if len(faces) != 1: continue
        f = faces[0]; fb = f.BoundingBox()
        if abs(fb.ylen-d)>TOL or abs(fb.zlen-w)>TOL: continue
        iz = _intervals(f,2,x,d/2,w/2,w)
        iy = _intervals(f,1,x,d/2,w/2,d)
        kz,ky = _kind(iz,w),_kind(iy,d)
        family = {('middle','full'):'W',('edge','pair'):'C',
                  ('edge','edge'):'L',('pair','pair'):'HSS',
                  ('full','full'):'PLATE'}.get((kz,ky))
        outer=_wire_circle(f.outerWire())
        if outer:
            inners=f.innerWires()
            inner=_wire_circle(inners[0]) if len(inners)==1 else None
            # An annulus has the same midline spans as a rectangular tube.
            # Identify its analytic boundaries before accepting HSS.
            family='HSS_R' if inner and (outer[0]-inner[0]).Length<TOL else None
        elif family=='HSS':
            flats=set()
            for edge in f.outerWire().Edges():
                if edge.geomType()!='LINE':continue
                eb=edge.BoundingBox()
                if eb.ylen<TOL:
                    if abs(eb.ymin)<TOL:flats.add('bottom')
                    if abs(eb.ymin-d)<TOL:flats.add('top')
                if eb.zlen<TOL:
                    if abs(eb.zmin)<TOL:flats.add('front')
                    if abs(eb.zmin-w)<TOL:flats.add('back')
            if len(flats)!=4:family=None
        if family and family not in ('HSS','HSS_R') and f.innerWires():family=None
        if family=='HSS' and len(f.innerWires())!=1:family=None
        if family=='HSS':
            # The inner boundary must also be rectangular, not a round axial
            # bore inside a square bar with coincident midline measurements.
            flat_edges=[e for e in f.innerWires()[0].Edges() if e.geomType()=='LINE']
            if len(flat_edges)<4:family=None
        if family:
            candidates.append((f.Area(),family,x,f,iz,iy))
    if not candidates: return None
    _,family,x,f,iz,iy = max(candidates, key=lambda a:a[0])
    tf=tw=wall=0.
    if family=='W':
        tw=iz[0][1]-iz[0][0]
        fl=_intervals(f,1,x,d/2,w*.12,d)
        if len(fl)!=2: return None
        tf=((fl[0][1]-fl[0][0])+(fl[-1][1]-fl[-1][0]))/2
    elif family=='C':
        tw=iz[0][1]-iz[0][0]
        tf=((iy[0][1]-iy[0][0])+(iy[-1][1]-iy[-1][0]))/2
    elif family=='L':
        wall=((iz[0][1]-iz[0][0])+(iy[0][1]-iy[0][0]))/2
    elif family in ('HSS','HSS_R'):
        ts=[hi-lo for lo,hi in iz+iy]
        if max(ts)-min(ts) > .1: return None
        wall=sum(ts)/len(ts)
    else:
        wall=w
    return dict(family=family,x=x,face=f,iz=iz,iy=iy,d=d,w=w,L=L,tf=tf,tw=tw,wall=wall)


def analyse_section(model, override_family=None, profiles=None):
    directions=_directions(model.shape)
    if not directions: raise ValueError('No straight member axis found.')
    override=model.length_axis_override
    if override != 'auto':
        if override not in ('x','y','z'): raise ValueError('Length axis must be auto, x, y or z.')
        X=cq.Vector(*{'x':(1,0,0),'y':(0,1,0),'z':(0,0,1)}[override])
    else: X=directions[0][0]
    cross=[v for v,score in directions if abs(v.dot(X)) < 1e-6]
    for face in model.shape.Faces():
        if face.geomType()=='PLANE':
            n=_positive(face.normalAt())
            if abs(n.dot(X))<1e-6 and not any(abs(n.dot(v))>.99999 for v in cross): cross.append(n)
    if not cross:
        seed=min((cq.Vector(1,0,0),cq.Vector(0,1,0),cq.Vector(0,0,1)),key=lambda v:abs(v.dot(X)))
        cross=[(seed-X.multiply(seed.dot(X))).normalized()]
    if not cross: raise ValueError('No perpendicular section directions found; curved members are unsupported.')
    attempts=[]
    for Y in cross[:4]:
        Z=X.cross(Y).normalized()
        shape,matrix=_transform(model.shape,[X,Y,Z])
        measure=_measure(shape)
        if measure:
            # Prefer depth >= width for L/HSS and the broad face for plate.
            pref=measure['d']>=measure['w']
            attempts.append((pref,measure['face'].Area(),X,Y,Z,shape,matrix,measure))
    if not attempts:
        raise ValueError('Could not identify a constant W, C, L, HSS or plate section. Set a length-axis override or inspect the source solid.')
    _,_,X,Y,Z,shape,matrix,m=max(attempts,key=lambda a:(a[0],a[1]))
    # Put channel web at Z=0; angle heel at Y=Z=0. Reverse X as needed
    # so the transform remains a rotation, never a mirror of the source part.
    flip_z=m['family'] in ('C','L') and m['iz'][0][0] > TOL
    flip_y=m['family']=='L' and m['iy'][0][0] > TOL
    if flip_z: Z=Z.multiply(-1); X=X.multiply(-1)
    if flip_y: Y=Y.multiply(-1); X=X.multiply(-1)
    if flip_z or flip_y:
        shape,matrix=_transform(model.shape,[X,Y,Z]); m=_measure(shape)
    if override_family and override_family != m['family']:
        raise ValueError(f"Measured section is {m['family']}, not {override_family}.")
    model.normalized_shape=shape;model.section_sample=m['x']
    radius=0.
    radius_edges=[] if m['family']=='HSS_R' else ([e for wire in m['face'].innerWires() for e in wire.Edges()] if m['family']=='HSS' else m['face'].Edges())
    for e in radius_edges:
        if e.geomType()=='CIRCLE': radius=max(radius,e.radius())
    fam=m['family']
    # Keep measured dimensions even when a nominal catalog label is found.
    p=make_custom_profile(fam,d=m['d']/25.4,bf=m['w']/25.4,tf=m['tf']/25.4,
                          tw=m['tw']/25.4,t_wall=m['wall']/25.4,k=radius/25.4)
    if fam=='HSS':p.outside_radius=max((e.radius() for e in m['face'].outerWire().Edges() if e.geomType()=='CIRCLE'),default=0.)/25.4
    match=match_profile(fam,p.d,p.bf,p.tw,p.tf,p.t_wall,profiles,tol_in=.025)
    notes='Measured custom profile.'
    if match:
        p.name=match.name;notes=f'Catalog label: {match.name}; dimensions remain measured.'
    # Physical area/perimeter supply weight and paint units from DSTV p.8/11.
    p.weight_per_ft=m['face'].Area()*1e-6*7850/1.48816394
    poly=[]
    for w in m['face'].Wires():
        pts=wire_points(w,'v',axes=(2,1),ccw=True)
        poly.append([Vec2(v.x_mm/25.4,v.y_mm/25.4) for v in pts])
    return SectionResult(fam,p,0,1,m['L']/25.4,
        BBox(Vec3(0,0,0),Vec3(m['L']/25.4,m['d']/25.4,m['w']/25.4)),
        poly,notes,{'source_to_part_mm':matrix,'length_axis_source':list(_vec(X)),
                    'depth_axis_source':list(_vec(Y)),'width_axis_source':list(_vec(Z))},
        sum(e.Length() for e in m['face'].outerWire().Edges())/1000.)


def contour_area(points):
    """Signed area including circular segments; radius belongs to outgoing edge."""
    area=0.
    for a,b in zip(points,points[1:]):
        area += (a.x_mm*b.y_mm-b.x_mm*a.y_mm)/2
        if abs(a.radius_mm)>1e-9:
            chord=math.hypot(b.x_mm-a.x_mm,b.y_mm-a.y_mm)
            theta=2*math.asin(min(1,chord/(2*abs(a.radius_mm))))
            area += math.copysign(a.radius_mm*a.radius_mm*(theta-math.sin(theta))/2,a.radius_mm)
    return area


def reverse_contour(points):
    n=len(points)-1; out=[]
    for j in range(n):
        i=(-j)%n
        out.append(replace(points[i],radius_mm=-points[(i-1)%n].radius_mm))
    return out+[replace(out[0],radius_mm=0)]


def _edge_circle(edge):
    if edge.geomType() == 'CIRCLE':
        return edge.arcCenter(), edge.radius()
    if edge.geomType() == 'ELLIPSE':
        e=BRepAdaptor_Curve(edge.wrapped).Ellipse()
        if abs(e.MajorRadius()-e.MinorRadius()) < 1e-6:
            p=e.Location()
            return cq.Vector(p.X(),p.Y(),p.Z()),(e.MajorRadius()+e.MinorRadius())/2
    return None


def wire_points(wire,surface,axes=(0,1),ccw=True):
    from .feature_extractor import ContourPoint
    result=[];exp=BRepTools_WireExplorer(wire.wrapped)
    while exp.More():
        edge=cq.Edge(exp.Current());typ=edge.geomType();circle=_edge_circle(edge)
        if circle:typ='CIRCLE'
        start=cq.Vertex(exp.CurrentVertex()).Center()
        rev=(edge.startPoint()-start).Length > (edge.endPoint()-start).Length
        if (edge.startPoint()-edge.endPoint()).Length < 1e-6:
            rev=edge.wrapped.Orientation()==TopAbs_REVERSED
        if typ=='LINE':count=1
        elif typ=='CIRCLE':count=max(1,math.ceil(edge.Length()/circle[1]/math.pi-1e-8))
        else:
            raise ValueError(f'{typ} boundary cannot be represented exactly by DSTV lines/arcs.')
        def at(t):return edge.positionAt(1-t if rev else t)
        for j in range(count):
            a,b,mid=at(j/count),at((j+1)/count),at((j+.5)/count)
            aa=(_vec(a)[axes[0]],_vec(a)[axes[1]])
            radius=0.
            if typ=='CIRCLE':
                center=circle[0]
                av=(_vec(a)[axes[0]]-_vec(center)[axes[0]],_vec(a)[axes[1]]-_vec(center)[axes[1]])
                mv=(_vec(mid)[axes[0]]-_vec(center)[axes[0]],_vec(mid)[axes[1]]-_vec(center)[axes[1]])
                radius=math.copysign(circle[1],av[0]*mv[1]-av[1]*mv[0])
            result.append(ContourPoint(surface,aa[0],aa[1],radius))
        exp.Next()
    if not result: raise ValueError('Empty boundary wire.')
    result.append(replace(result[0],radius_mm=0))
    if (contour_area(result)>0)!=ccw:result=reverse_contour(result)
    return result


def _wire_circle(wire):
    edges=wire.Edges();circles=[_edge_circle(e) for e in edges]
    if not edges or not all(circles): return None
    c,r=circles[0]
    if any((cc-c).Length>TOL or abs(rr-r)>TOL for cc,rr in circles):return None
    if abs(sum(p.Length() for p in edges)-2*math.pi*r)>TOL:return None
    return c,2*r


def _surface_slices(sec):
    p=sec.profile;d,w=p.d_mm,p.bf_mm
    if sec.family=='W':
        z=(w-p.tw_mm)/2
        return [('v',2,z+EPS,z+p.tw_mm-EPS),('o',1,d-EPS,d-p.tf_mm+EPS),('u',1,EPS,p.tf_mm-EPS)]
    if sec.family=='C':
        return [('v',2,EPS,p.tw_mm-EPS),('o',1,d-EPS,d-p.tf_mm+EPS),('u',1,EPS,p.tf_mm-EPS)]
    if sec.family=='L':
        return [('v',2,EPS,p.t_wall_mm-EPS),('u',1,EPS,p.t_wall_mm-EPS)]
    if sec.family=='HSS':
        t=p.t_wall_mm
        return [('v',2,EPS,t-EPS),('h',2,w-EPS,w-t+EPS),('o',1,d-EPS,d-t+EPS),('u',1,EPS,t-EPS)]
    return [('v',2,EPS,w-EPS)]


def _same_wire(a,b,axis):
    # Wire.Length uses a composite curve adaptor which can segfault on OCC
    # section wires. Compare the projected boundaries themselves instead of
    # a bounding-box/perimeter signature that can also confuse different cuts.
    try:
        ca,cb=_wire_circle(a),_wire_circle(b)
        if ca and cb:
            coordinate=1 if axis==2 else 2
            return abs(ca[1]-cb[1])<.025 and abs(ca[0].x-cb[0].x)<.025 and abs(_vec(ca[0])[coordinate]-_vec(cb[0])[coordinate])<.025
        return _contours_equivalent([wire_points(a,'v',axes=(0,1 if axis==2 else 2))],
                                    [wire_points(b,'v',axes=(0,1 if axis==2 else 2))],tolerance=.025)
    except ValueError:return False


def _miter_flange_contour(near, far, outer, inner, end_planes):
    """Describe rectangular flange ends cut by a full-section web miter.

    AK uses the maximum material envelope, not necessarily the visible skin.
    Only straight, rectangular flanges and planes independent of Z qualify;
    partial chamfers, compound cuts and changing topology remain unsupported.
    Return both the envelope and its generating planes for slice verification.
    """
    from copy import deepcopy
    if len(near)!=1 or len(far)!=1:return None
    points=near[0]
    if len(points)!=5 or any(abs(p.radius_mm)>1e-8 for p in points):return None
    for a,b in zip(points,points[1:]):
        if min(abs(a.x_mm-b.x_mm),abs(a.y_mm-b.y_mm))>.001:return None
    current=outer+math.copysign(EPS,outer-inner)
    opposite=inner-math.copysign(EPS,outer-inner)
    thickness=abs(current-opposite)
    result=deepcopy(points);cuts=[]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        if abs(a.y_mm-b.y_mm)<.001:continue
        for origin,n in end_planes:
            if abs(n.x)<.15 or abs(n.z)>1e-8 or abs(n.y)<1e-8:continue
            if any(abs((cq.Vector(p.x_mm,outer,p.y_mm)-origin).dot(n))>.025 for p in (a,b)):continue
            def cut_x(y):return origin.x-n.y/n.x*(y-origin.y)
            # The outward normal selects the furthest material edge.
            at_current=n.x*cut_x(current)>n.x*cut_x(opposite)
            x=cut_x(current if at_current else opposite)
            result[i].x_mm=result[(i+1)%4].x_mm=x
            result[i].bevel_angle_1=math.copysign(math.degrees(math.atan(abs(n.y/n.x))),-1 if at_current else 1)
            result[i].bevel_depth_1=thickness if at_current else 0.
            cuts.append((i,origin,n))
            break
    if not cuts:return None
    result[-1]=deepcopy(result[0])
    return result,cuts


def _miter_trace(envelope,cuts,plane):
    from copy import deepcopy
    result=deepcopy(envelope)
    for i,origin,n in cuts:
        x=origin.x-n.y/n.x*(plane-origin.y)
        result[i].x_mm=result[(i+1)%4].x_mm=x
    result[-1]=deepcopy(result[0])
    return result


def _wall_check_planes(shape,axis,outer,inner):
    """Probe each interval delimited by topological vertices inside the wall."""
    lo,hi=sorted((outer,inner));levels={lo,hi}
    for vertex in shape.Vertices():
        value=_vec(vertex.Center())[axis]
        if lo<value<hi:levels.add(round(value,6))
    levels=sorted(levels)
    planes={(a+b)/2 for a,b in zip(levels,levels[1:]) if b-a>1e-6}
    planes.update(outer+(inner-outer)*f for f in (.25,.5,.75))
    if len(planes)>64:raise ValueError('too many through-thickness transitions for automatic verification')
    return sorted(planes)


def extract(model,sec):
    from .feature_extractor import FeatureSet,Hole,EndCut
    fs=FeatureSet(sec);shape=model.normalized_shape
    if shape is None: raise ValueError('Measure the section before extracting features.')
    if sec.family=='HSS_R':
        from .round_geometry import extract_round
        return extract_round(model,sec)
    # A non-planar/non-cylindrical surface needs explicit machining support.
    exotic=sorted({f.geomType() for f in shape.Faces()}-{'PLANE','CYLINDER'})
    if exotic:fs.errors.append('Unsupported surface types: '+', '.join(exotic))
    # Record signed end miters from planar end faces spanning the section.
    angles={'start':[], 'end':[]};end_planes=[];planes_by_side={'start':[],'end':[]};L=sec.length_in*25.4
    for f in shape.Faces():
        if f.geomType()!='PLANE':continue
        n=f.normalAt();b=f.BoundingBox()
        if abs(n.x)>.15 and b.ylen>=sec.profile.d_mm-.05 and b.zlen>=sec.profile.bf_mm-.05:
            side='start' if f.Center().x < L/2 else 'end'
            if not any(n.dot(nn)>.999999 and abs((f.Center()-c).dot(nn))<.025 for c,nn in planes_by_side[side]):
                planes_by_side[side].append((f.Center(),n))
            end_planes.append((f.Center(),n))
            angles[side].append((math.degrees(math.atan(n.y/n.x)),math.degrees(math.atan(n.z/n.x))))
    if any(len(planes)>1 for planes in planes_by_side.values()):
        fs.errors.append('Multiple full-section cut planes at one end need explicit machining support.')
    if angles['start']:
        fs.end_cuts.web_start_deg,fs.end_cuts.flange_start_deg=angles['start'][0]
    if angles['end']:
        fs.end_cuts.web_end_deg,fs.end_cuts.flange_end_deg=angles['end'][0]
    all_simple=True;outer_differences=[]
    stock_face=_slice(shape,0,model.section_sample).Faces()[0]
    for surface,axis,outer,inner in _surface_slices(sec):
        front=_slice(shape,axis,outer).Faces()
        back=_slice(shape,axis,inner).Faces()
        if not front:
            fs.errors.append(f'No material on face {surface}.');continue
        back_wires=[w for f in back for w in f.innerWires()]
        coordinate=1 if axis==2 else 2
        span=sec.profile.d_mm if axis==2 else sec.profile.bf_mm
        def extend(points,plane):
            if sec.family=='PLATE':return points
            args=[model.section_sample,sec.profile.d_mm/2,sec.profile.bf_mm/2]
            args[axis]=plane
            spans=_intervals(stock_face,coordinate,*args,span)
            if not spans:return points
            lo,hi=spans[0][0],spans[-1][1]
            for pt in points:
                if abs(pt.y_mm-lo)<.025:pt.y_mm=0.
                elif abs(pt.y_mm-hi)<.025:pt.y_mm=span
            return points
        def simple(points,plane):
            for a,b in zip(points,points[1:]):
                if abs(a.y_mm-b.y_mm)<.025 and (abs(a.y_mm)<.025 or abs(a.y_mm-span)<.025):continue
                if abs(a.radius_mm)>1e-8:return False
                aa=[a.x_mm,0.,0.];bb=[b.x_mm,0.,0.]
                aa[coordinate]=a.y_mm;bb[coordinate]=b.y_mm;aa[axis]=bb[axis]=plane
                if not any(abs((cq.Vector(*aa)-origin).dot(n))<.025 and abs((cq.Vector(*bb)-origin).dot(n))<.025 for origin,n in end_planes):return False
            return True
        def nominal_wall(wire):
            bounds=wire.BoundingBox()
            low,high=(bounds.ymin,bounds.ymax) if axis==2 else (bounds.zmin,bounds.zmax)
            inset=min(.01,(high-low)/4)
            for ordinate in ((low+high)/2,low+inset,high-inset):
                args=[model.section_sample,sec.profile.d_mm/2,sec.profile.bf_mm/2]
                args[coordinate]=ordinate
                extent=sec.profile.bf_mm if axis==2 else sec.profile.d_mm
                spans=_intervals(stock_face,axis,*args,extent)
                selected=[(lo,hi) for lo,hi in spans if lo-.005<=outer<=hi+.005]
                if not selected:return False
                lo,hi=selected[0]
                opposite=hi if inner>outer else lo
                expected=inner+math.copysign(EPS,inner-outer)
                if abs(opposite-expected)>.025:return False
            return True
        far_contours=[]
        for f in back:
            try:far_contours.append(extend(wire_points(f.outerWire(),surface,axes=(0,coordinate)),inner))
            except ValueError:pass
        near_contours=[]
        for face in front:
            try:
                pts=extend(wire_points(face.outerWire(),surface,axes=(0,coordinate)),outer)
                near_contours.append(pts)
                # A pure miter may use the header alone. Every non-stock edge
                # must then lie on one of the full-section end planes.
                all_simple=all_simple and simple(pts,outer)
                # Clamp kernel epsilon to theoretical section envelope.
                for pt in pts:
                    if abs(pt.x_mm)<.005:pt.x_mm=0.
                    if abs(pt.x_mm-L)<.005:pt.x_mm=L
                    if abs(pt.y_mm)<.005:pt.y_mm=0.
                fs.outer_contours.append(pts)
            except ValueError as exc:
                fs.errors.append(f'{surface} outer contour: {exc}')
            for wire in face.innerWires():
                if not nominal_wall(wire):
                    fs.errors.append(f'{surface}: stock extends beyond the nominal wall at an opening (flange/web junction or rolled corner).')
                    continue
                if not any(_same_wire(wire,b,axis) for b in back_wires):
                    fs.errors.append(f'{surface}: opening changes through wall thickness (blind, oblique or countersunk feature).')
                    continue
                circle=_wire_circle(wire)
                if circle:
                    c,dia=circle
                    fs.holes.append(Hole(surface,c.x,c.y if axis==2 else c.z,dia))
                else:
                    try:fs.inner_contours.append(wire_points(wire,surface,axes=(0,1 if axis==2 else 2),ccw=False))
                    except ValueError as exc:fs.errors.append(f'{surface} opening: {exc}')
        prepared=None
        same_outer=_contours_equivalent(near_contours,far_contours)
        if not same_outer:
            if axis==1:
                prepared=_miter_flange_contour(near_contours,far_contours,outer,inner,end_planes)
            if prepared:
                envelope,cuts=prepared
                # Verify the proposed plane against the actual solid at both
                # skins and three intermediate depths, not just the endpoints.
                for fraction in (0.,.25,.5,.75,1.):
                    plane=outer+(inner-outer)*fraction
                    try:
                        actual=[extend(wire_points(f.outerWire(),surface,axes=(0,coordinate)),plane)
                                for f in _slice(shape,axis,plane).Faces()]
                    except ValueError:
                        prepared=None;break
                    if not _contours_equivalent([_miter_trace(envelope,cuts,plane)],actual):
                        prepared=None;break
            if prepared:
                fs.outer_contours=[c for c in fs.outer_contours if c[0].surface!=surface]+[envelope]
                fs.warnings.append(f'{surface}: full-section miter encoded with AK flange bevel preparation.')
            else:outer_differences.append(surface)
        # Opposite-wall-only blind pockets must not vanish either.
        front_wires=[w for f in front for w in f.innerWires()]
        if any(not any(_same_wire(w,a,axis) for a in front_wires) for w in back_wires):
            fs.errors.append(f'{surface}: reverse-side or tapered pocket needs explicit machining data.')
        # Skin agreement alone misses enclosed cavities and internal counterbores.
        # Verify every topological depth interval, plus three wall fractions.
        try:
            for plane in _wall_check_planes(shape,axis,outer,inner):
                middle=_slice(shape,axis,plane).Faces()
                middle_wires=[w for f in middle for w in f.innerWires()]
                if len(front_wires)!=len(middle_wires) or any(not any(_same_wire(w,a,axis) for a in front_wires) for w in middle_wires):
                    fs.errors.append(f'{surface}: an opening or cavity changes inside the wall thickness.');break
                actual=[extend(wire_points(f.outerWire(),surface,axes=(0,coordinate)),plane) for f in middle]
                if same_outer:
                    valid=_contours_equivalent(near_contours,actual)
                elif prepared:
                    valid=_contours_equivalent([_miter_trace(envelope,cuts,plane)],actual)
                elif near_contours and far_contours and all(simple(c,outer) for c in near_contours) and all(simple(c,inner) for c in far_contours):
                    valid=bool(actual) and all(simple(c,plane) for c in actual)
                else:continue # already rejected by the outer-contour check
                if not valid:
                    fs.errors.append(f'{surface}: an exterior cut changes inside the wall thickness.');break
        except ValueError as exc:fs.errors.append(f'{surface}: through-thickness verification failed: {exc}')
    has_miter=any(abs(a)>.001 for a in vars(fs.end_cuts).values())
    if all_simple and has_miter:
        fs.outer_contours=[]
        fs.warnings.append('Simple end miters are described by the ST header; no redundant AK blocks.')
    elif outer_differences:
        fs.errors.append('Outer cut changes through thickness on '+', '.join(outer_differences)+': bevel/chamfer geometry needs explicit weld preparation.')
    fs.errors=list(dict.fromkeys(fs.errors))
    fs.holes.sort(key=lambda h:(h.surface,h.x_mm,h.y_mm))
    return fs


def _contours_equivalent(a,b,tolerance=.06):
    from .preview import contour_xy
    radius=max((abs(p.radius_mm) for c in a+b for p in c),default=0)
    degrees=min(2,math.degrees(2*math.acos(max(-1,1-tolerance/(4*radius))))) if radius>tolerance else 2
    aa=[contour_xy(c,max_degrees=degrees) for c in a];bb=[contour_xy(c,max_degrees=degrees) for c in b]
    if not aa or not bb:return not aa and not bb
    def directed(source,target):
        segments=[(p,q) for line in target for p,q in zip(line,line[1:])]
        def distance(p,a,b):
            dx,dy=b[0]-a[0],b[1]-a[1];length=dx*dx+dy*dy
            t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)) if length else 0
            return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
        for line in source:
            for p,q in zip(line,line[1:]):
                for point in (p,((p[0]+q[0])/2,(p[1]+q[1])/2)):
                    if min((distance(point,a,b) for a,b in segments),default=math.inf)>tolerance:return False
        return True
    return directed(aa,bb) and directed(bb,aa)
