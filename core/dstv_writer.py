"""DSTV NC, 8th edition (2003), pp.7-18. Deterministic ASCII output."""
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from .validation import validate_features
from .version import VERSION

@dataclass
class NC1Header:
    order_number: str = ''
    drawing_number: str = ''
    phase_number: str = '1'
    piece_number: str = '1'
    steel_quality: str = ''
    quantity: int = 1
    profile_name: str = ''
    profile_code: str = ''
    code_text: str = ''
    text_info_1: str = ''
    text_info_2: str = ''
    text_info_3: str = ''
    text_info_4: str = ''
    saw_length_mm: float = None
    paint_per_m: float = None
    weight_per_m: float = None


def atomic_write(path,text,encoding='ascii',overwrite=True):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding=encoding,newline='\n') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        if overwrite:
            os.replace(temp,path)
        elif os.name=='nt':
            os.rename(temp,path)
        else:
            os.link(temp,path)
            os.unlink(temp)
    except BaseException:
        try:os.unlink(temp)
        except OSError:pass
        raise


def _n(n):
    if abs(n)<.0005:n=0.
    return f'{n:.3f}'


def render_nc1(fs,header=None):
    header=header or NC1Header()
    validate_features(fs,header)
    s=fs.section;p=s.profile
    d,b,tf,tw=p.d_mm,p.bf_mm,p.tf_mm,p.tw_mm
    weight=p.kg_per_m if header.weight_per_m is None else header.weight_per_m
    paint=s.paint_per_m if header.paint_per_m is None else header.paint_per_m
    if s.family in ('L','HSS','HSS_R'):tf=tw=p.t_wall_mm
    if s.family=='PLATE':
        b=tf=0.;tw=p.bf_mm
        weight=p.bf_mm*7.85;paint=2.0 # kg/m2 and m2/m2 for plate
    length=_n(s.length_in*25.4)
    if header.saw_length_mm is not None:length+=' '+_n(header.saw_length_mm)
    values=[header.order_number,header.drawing_number,header.phase_number,header.piece_number,
            header.steel_quality,str(header.quantity),header.profile_name or p.name,
            header.profile_code or p.dstv_code,length,*map(_n,(d,b,tf,tw,p.k_mm,weight,paint)),
            *map(_n,vars(fs.end_cuts).values()),header.text_info_1,header.text_info_2,header.text_info_3,header.text_info_4]
    lines=['ST','**DSTV-NC-VERSION-8-SENDER-SYSTEM=STEP2NC1',
           '**DSTV-NC-VERSION-8-SENDER-SYSTEM-RELEASE='+VERSION,
           '**DSTV-NC-VERSION-8-EINZELTEILNR=POSITIONNUMBER',
           '**DSTV-NC-VERSION-8-POSITIONIERUNG=PRO-JOB']
    lines += [c for c in fs.comments if c.startswith('**') and 'SENDER-SYSTEM' not in c]
    lines += ['  '+v for v in values]
    if p.outside_radius:lines.append('**DSTV-NC-VERSION-8-AUSSENRADIUS='+_n(p.outside_radius*25.4))
    if fs.holes:
        lines.append('BO')
        for h in fs.holes:
            import math
            x,y=h.x_mm,h.y_mm
            if h.slotted:
                b=h.slot_width_mm or max(0.,h.slot_length_mm-h.diameter_mm)
                a=math.radians(h.slot_angle_deg);ht=h.slot_height_mm
                x-=(b*math.cos(a)-ht*math.sin(a))/2
                y-=(b*math.sin(a)+ht*math.cos(a))/2
            line=f'  {h.surface} {_n(x)}{h.reference} {_n(y)}{h.operation} {_n(h.diameter_mm)} {_n(h.depth_mm)}'
            if h.slotted:
                # DSTV b/h are centre spacings, not the overall slot envelope.
                b=h.slot_width_mm or max(0.,h.slot_length_mm-h.diameter_mm)
                line+=f'l {_n(b)} {_n(h.slot_height_mm)} {_n(h.slot_angle_deg)}'
            lines.append(line)
    groups=[('AK',c) for c in fs.all_outer_contours()]+[('IK',c) for c in fs.inner_contours]+[('PU',c) for c in fs.powder_contours]+[('KO',c) for c in fs.scribe_contours]
    for code,contour in groups:
        lines.append(code)
        for i,c in enumerate(contour):
            face=c.surface if i==0 else ' '
            line=f'  {face} {_n(c.x_mm)}{c.reference} {_n(c.y_mm)}{c.modifier} {_n(c.radius_mm)}'
            if code in ('AK','IK'):line+=' '+' '.join(_n(getattr(c,k)) for k in ('bevel_angle_1','bevel_depth_1','bevel_angle_2','bevel_depth_2'))
            lines.append(line)
    for m in fs.markings:
        if m.text:
            lines += ['SI',f'  {m.surface} {_n(m.x_mm)}{m.reference} {_n(m.y_mm)} {_n(m.angle_deg)} {_n(m.height_mm)}{m.mode} {m.text}']
        else:
            lines += ['BO',f'  {m.surface} {_n(m.x_mm)}{m.reference} {_n(m.y_mm)}m 0.000 0.000']
    for code,rows in fs.extra_blocks:
        lines.append(code);lines.extend(rows)
    lines.append('EN')
    text='\n'.join(lines)+'\n';text.encode('ascii')
    return text


def write_nc1(fs,out_path,header=None,source_file='',overwrite=True):
    text=render_nc1(fs,header)
    atomic_write(out_path,text,overwrite=overwrite)
    return text


def default_header_from_filename(fn):
    import re
    base=Path(fn).stem
    m=re.search(r'\s*[xX](\d+)$',base)
    qty=int(m.group(1)) if m and int(m.group(1))>0 else 1
    mark=base[:m.start()].strip() if m else base
    return NC1Header(order_number='',drawing_number=mark,piece_number=mark,quantity=qty,
                     text_info_1='Source: '+Path(fn).name)
