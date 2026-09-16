"""Versioned, portable project state. No pickle or executable content."""
import json
from dataclasses import asdict
from pathlib import Path
from .dstv_writer import NC1Header,atomic_write
from .feature_extractor import FeatureSet,Hole,ContourPoint,Marking,EndCut
from .section_detector import SectionResult
from .profiles import Profile
from .geometry import BBox,Vec2,Vec3

SCHEMA=1


def project_data(fs,header,source=''):
    return {'schema':'step2nc1-project','version':SCHEMA,'source':str(source),
            'header':asdict(header),'features':asdict(fs)}


def save_project(path,fs,header,source=''):
    text=json.dumps(project_data(fs,header,source),ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    atomic_write(path,text,'utf-8')


def load_project(path):
    data=json.loads(Path(path).read_text('utf-8'))
    if data.get('schema')!='step2nc1-project' or data.get('version')!=SCHEMA:
        raise ValueError('Unsupported project schema/version.')
    f=dict(data['features']);s=dict(f.pop('section'));s['profile']=Profile(**s['profile'])
    s['bbox']=BBox(Vec3(**s['bbox']['minp']),Vec3(**s['bbox']['maxp']))
    s['cross_polys']=[[Vec2(**p) for p in poly] for poly in s.get('cross_polys',[])]
    f['holes']=[Hole(**v) for v in f.get('holes',[])]
    f['markings']=[Marking(**v) for v in f.get('markings',[])]
    f['outer_contour']=[ContourPoint(**v) for v in f.get('outer_contour',[])]
    for name in ('outer_contours','inner_contours','powder_contours','scribe_contours'):
        f[name]=[[ContourPoint(**v) for v in contour] for contour in f.get(name,[])]
    f['end_cuts']=EndCut(**f.get('end_cuts',{}))
    fs=FeatureSet(SectionResult(**s),**f)
    source=data.get('source','')
    if source and not Path(source).is_absolute():source=str((Path(path).resolve().parent/source).resolve())
    return fs,NC1Header(**data['header']),source
