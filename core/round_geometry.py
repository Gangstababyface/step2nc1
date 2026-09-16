"""Exact straight round-pipe stock with square or planar mitered ends.

Saddles, bores and non-planar cuts need unrolled contour/axis treatment and are
kept as reviewable rejected drafts; they must never masquerade as rectangular HSS.
"""
import math
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from .feature_extractor import FeatureSet


def extract_round(model,sec):
    fs=FeatureSet(sec);p=sec.profile;radius=p.d_mm/2
    planes=[]
    for face in model.normalized_shape.Faces():
        kind=face.geomType()
        if kind=='CYLINDER':
            cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder()
            axis=cylinder.Axis().Direction();origin=cylinder.Location()
            coaxial=(abs(abs(axis.X())-1)<1e-7 and
                     math.hypot(origin.Y()-radius,origin.Z()-radius)<.025)
            stock_radius=min(abs(cylinder.Radius()-r) for r in (radius,radius-p.t_wall_mm))<.025
            if not (coaxial and stock_radius):
                fs.errors.append('Round pipe: bores or saddle cuts need an unrolled machining contour and are not yet exportable.')
        elif kind=='PLANE':
            origin=face.Center();normal=face.normalAt()
            if abs(normal.x)<.15:
                fs.errors.append('Round pipe: longitudinal slots or near-axial cuts are not yet exportable.')
                continue
            if not any(normal.dot(n)>.999999 and abs((origin-c).dot(n))<.025 for c,n in planes):
                planes.append((origin,normal))
        else:
            fs.errors.append(f'Round pipe: {kind.lower()} cut surface needs unrolled contour support.')
    start=[(c,n) for c,n in planes if n.x<0];end=[(c,n) for c,n in planes if n.x>0]
    if len(start)!=1 or len(end)!=1:
        fs.errors.append('Round pipe: expected one planar cut at each end. Stepped or coped ends need unrolled contour support.')
    if not fs.errors:
        for side,group in [('start',start),('end',end)]:
            _,n=group[0]
            setattr(fs.end_cuts,'web_'+side+'_deg',math.degrees(math.atan(n.y/n.x)))
            setattr(fs.end_cuts,'flange_'+side+'_deg',math.degrees(math.atan(n.z/n.x)))
        fs.warnings.append('Round pipe: square/planar ends are encoded in the ST header. No unrolled AK contour is needed.')
    fs.errors=list(dict.fromkeys(fs.errors))
    return fs
