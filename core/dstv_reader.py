"""Read DSTV NC1 for inspection and editing, including legacy attached tokens.

Original text is retained in Document; inspect mode never changes input files.
Unknown blocks are retained verbatim. Geometry-affecting unsupported blocks
prevent modified export, while remaining readable for diagnosis.
"""
import re
import math
from dataclasses import dataclass
from pathlib import Path
from .dstv_writer import NC1Header
from .feature_extractor import FeatureSet,Hole,Marking,ContourPoint,EndCut
from .profiles import Profile
from .section_detector import SectionResult
from .geometry import BBox,Vec3

TOKEN=re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?|[A-Za-z]')
NUMBER=re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?')

@dataclass
class Document:
    header: NC1Header
    features: FeatureSet
    raw_text: str
    blocks: list


def _float(s):
    return float(s.replace(',','.'))


def read_nc1(path):
    raw=Path(path).read_bytes()
    try:text=raw.decode('ascii')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    return parse_nc1(text)


def parse_nc1(text):
    blocks=[];comments=[];code=None;rows=[]
    for line in text.splitlines():
        if line.startswith('**'):
            comments.append(line)
            if 'FERTIGUNGSART=' in line:
                # Keep manufacturing constraints bound to their original row.
                rows.append(line)
            continue
        if re.fullmatch(r'[A-Z][A-Z0-9]',line.strip()) and not line.startswith(' '):
            if code:blocks.append((code,rows))
            code=line.strip();rows=[]
        else:
            if code:rows.append(line)
            elif line.strip():raise ValueError('Data precedes ST block.')
    if code:blocks.append((code,rows))
    if not blocks or blocks[0][0]!='ST' or blocks[-1][0]!='EN':raise ValueError('NC1 must start with ST and end with EN.')
    if sum(c=='ST' for c,r in blocks)!=1:raise ValueError('Expected one part per NC1 file.')
    h=blocks[0][1]
    while len(h)>24 and not h[-1].strip():h.pop()
    if len(h)!=24:raise ValueError(f'ST requires 24 header records, found {len(h)}.')
    h=[s.strip() for s in h]
    dims=re.split(r'\s*,\s*|\s+',h[8]);length=_float(dims[0]);d,b,tf,tw,k,weight,paint=map(_float,h[9:16])
    family={'I':'W','U':'C','L':'L','M':'HSS','RO':'HSS_R','B':'PLATE'}.get(h[7],h[7])
    header=NC1Header(h[0],h[1],h[2],h[3],h[4],int(h[5]),h[6],h[7],
                     text_info_1=h[20],text_info_2=h[21],text_info_3=h[22],text_info_4=h[23],
                     saw_length_mm=_float(dims[1]) if len(dims)>1 else None,paint_per_m=paint,weight_per_m=weight)
    if family=='PLATE':b=tw
    p=Profile(h[6],family,d/25.4,b/25.4,tf/25.4,tw/25.4,
              tw/25.4 if family in ('L','HSS','HSS_R','PLATE') else 0,k/25.4,weight/1.48816394,h[7])
    for comment in comments:
        if comment.startswith('**DSTV-NC-VERSION-8-AUSSENRADIUS='):p.outside_radius=float(comment.split('=',1)[1])/25.4
    sec=SectionResult(family,p,0,1,length/25.4,BBox(Vec3(0,0,0),Vec3(length/25.4,d/25.4,b/25.4)),notes='Imported NC1.',paint_per_m=paint)
    fs=FeatureSet(sec,end_cuts=EndCut(*map(_float,h[16:20])),comments=comments)
    for code,rows in blocks[1:]:
        if code=='EN':continue
        if code not in ('BO','AK','IK','PU','KO','SI'):
            fs.extra_blocks.append((code,rows));fs.errors.append(f'{code} block is preserved but not editable/exportable by this version.');continue
        face='';ref='u';contour=[]
        for line in rows:
            if not line.strip():continue
            if line.startswith('**'):
                fs.errors.append('Row-specific manufacturing constraint: use the original NC1; modified export is unsupported.');continue
            ts=TOKEN.findall(line)
            if not ts:continue
            if ts[0] in ('v','h','o','u'):face=ts.pop(0)
            if not face:raise ValueError(f'{code}: missing face.')
            x=float(ts.pop(0))
            if ts and ts[0] in ('u','o','s'):ref=ts.pop(0)
            y=float(ts.pop(0))
            if code=='BO':
                op=ts.pop(0) if ts and ts[0] in ('g','l','m','s') else ''
                dia=float(ts.pop(0));depth=float(ts.pop(0)) if ts and NUMBER.fullmatch(ts[0]) else 0
                slot=bool(ts and ts[0]=='l');width=height=angle=0.
                if slot:
                    ts.pop(0);width,height,angle=map(float,ts[:3])
                    a=math.radians(angle);x+=(width*math.cos(a)-height*math.sin(a))/2;y+=(width*math.sin(a)+height*math.cos(a))/2
                fs.holes.append(Hole(face,x,y,dia,slot,width+dia,angle,depth_mm=depth,operation=op,reference=ref,slot_width_mm=width,slot_height_mm=height))
            elif code=='SI':
                # Numeric scanner stops after height, preserving arbitrary text exactly.
                match=re.match(r'^\s*[vouh]?\s*('+NUMBER.pattern+r')\s*[uos]?\s*('+NUMBER.pattern+r')\s+('+NUMBER.pattern+r')\s+('+NUMBER.pattern+r')([rz]?)\s*(.*)$',line)
                if not match:raise ValueError(f'Malformed SI: {line}')
                fs.markings.append(Marking(face,x,y,float(match[3]),match[6],float(match[4]),ref,match[5]))
            else:
                modifier=ts.pop(0) if ts and ts[0] in ('t','w') else ''
                vals=list(map(float,ts));vals += [0.]*(5-len(vals))
                contour.append(ContourPoint(face,x,y,vals[0],ref,modifier,*vals[1:5]))
        if contour:
            dest={'AK':fs.outer_contours,'IK':fs.inner_contours,'PU':fs.powder_contours,'KO':fs.scribe_contours}[code]
            dest.append(contour)
    return Document(header,fs,text,blocks)
