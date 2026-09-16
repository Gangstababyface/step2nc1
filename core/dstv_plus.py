"""DSTV+ 3.1 BA/PI export for an explicitly ordered list of straight parts.

This is a nesting manifest writer, not a nesting optimizer. Profiles and grades
must agree; the manifest rejects overflow instead of shortening required trims.
"""
from dataclasses import dataclass,field,replace
import os
from pathlib import Path
import math
import re
from .dstv_reader import read_nc1
from .dstv_writer import atomic_write
from .validation import text_value,finite

@dataclass
class NestPart:
    file: str
    quantity: int = 1
    rotation: str = ''
    lot: str = ''
    batch: str = ''
    load: str = ''

@dataclass
class Nest:
    name: str
    run: str
    stock_length_mm: float
    parts: list
    machine: int = 1
    bars: int = 1
    kerf_mm: float = 3.0
    front_trim_mm: float = 0.0
    end_trim_mm: float = 0.0
    filler_mm: float = 0.0
    remainder: str = 'h'
    process: str = 's'
    info: list = field(default_factory=lambda:['','','',''])


def _identifier(s,length,label,optional=False):
    if optional and not s:return
    if not isinstance(s,str) or len(s)>length or not re.fullmatch(r'[A-Z0-9_-]+',s):
        raise ValueError(f'{label}: use up to {length} uppercase letters, digits, hyphen or underscore.')


def render_ba(nest,base_dir='.'):
    _identifier(nest.name,16,'Nest name');_identifier(nest.run,40,'Run')
    if not isinstance(nest.machine,int) or not 1<=nest.machine<=9:raise ValueError('Machine must be 1-9.')
    if not isinstance(nest.bars,int) or nest.bars<1:raise ValueError('Bars must be a positive integer.')
    if nest.remainder not in ('v','h','n') or nest.process not in ('s','f','v','u','h','o'):raise ValueError('Invalid processing direction.')
    for name in ('stock_length_mm','kerf_mm','front_trim_mm','end_trim_mm','filler_mm'):
        value=getattr(nest,name);finite(value,name)
        if value<0:raise ValueError(f'{name} cannot be negative.')
    if not nest.parts or nest.stock_length_mm<=0:raise ValueError('Specify stock length and at least one part.')
    docs=[];pi=[];total=0.;qty=0
    for raw in nest.parts:
        part=NestPart(**raw) if isinstance(raw,dict) else raw
        if not isinstance(part.quantity,int) or part.quantity<1:raise ValueError('Part quantity must be a positive integer.')
        if part.rotation not in ('','x','y','z'):raise ValueError('Rotation must be blank, x, y or z.')
        path=Path(base_dir)/part.file;doc=read_nc1(path);h=doc.header;s=doc.features.section
        if any(abs(a)>.001 for a in vars(doc.features.end_cuts).values()):raise ValueError('BA length accounting currently supports square-ended parts only.')
        if docs:
            ref=docs[0];p=s.profile;r=ref.features.section.profile
            if h.steel_quality!=ref.header.steel_quality or p.dstv_code!=r.dstv_code or p.name!=r.name or any(abs(getattr(p,k)-getattr(r,k))>.001 for k in ('d','bf','tf','tw','t_wall')):
                raise ValueError('All nested parts must use the same profile, dimensions and material.')
        docs.append(doc);total+=(s.length_in*25.4)*part.quantity;qty+=part.quantity
        path_text=str(Path(part.file).parent)
        if path_text=='.':path_text=''
        elif not path_text.endswith(('\\','/')):path_text+='\\'
        filename=Path(part.file).name
        text_value(path_text,'Part path',80);text_value(filename,'Part filename',22)
        for label,value in [('lot',part.lot),('batch',part.batch),('load',part.load)]:_identifier(value,16,label,True)
        # Existing NC1 is authoritative. Optional duplicated metadata is blank.
        fields=[path_text,filename,'','','','',str(part.quantity),part.rotation,'','','',part.lot,part.batch,part.load]
        if any(';' in v for v in fields):raise ValueError('Semicolons are not allowed inside BA fields.')
        pi.append('  '+';'.join(fields))
    # Conservative: one cutoff per finished part, plus explicit front/end trims.
    used=total+qty*nest.kerf_mm+nest.front_trim_mm+nest.end_trim_mm+nest.filler_mm
    if used>nest.stock_length_mm+.001:raise ValueError(f'Nest requires {used:.3f} mm; stock has {nest.stock_length_mm:.3f} mm.')
    d=docs[0];h=d.header;p=d.features.section.profile
    text_value(p.name,'Profile name',16);text_value(h.steel_quality,'Steel quality',16)
    info=list(nest.info)
    if len(info)!=4:raise ValueError('Exactly four info lines are required.')
    for i in info:text_value(i,'Info line')
    tf=p.tf_mm;tw=p.tw_mm
    if p.family in ('L','HSS','HSS_R'):tf=tw=p.t_wall_mm
    b=p.bf_mm
    if p.family=='PLATE':b=tf=0;tw=p.bf_mm
    vals=[nest.name,nest.run,str(nest.machine),h.steel_quality,str(nest.bars),p.name,p.dstv_code,
          f'{nest.stock_length_mm:.3f}',*[f'{n:.3f}' for n in (p.d_mm,b,tf,tw,p.k_mm,p.kg_per_m)],
          *info,f'{nest.kerf_mm:.3f}',f'{nest.filler_mm:.3f}',f'{nest.remainder};{nest.front_trim_mm:.3f};{nest.end_trim_mm:.3f};{nest.process}']
    text='BA\n'+'\n'.join('  '+v for v in vals)+'\nPI\n'+'\n'.join(pi)+'\n'
    text.encode('ascii')
    return text,{'used_mm':used,'remainder_mm':nest.stock_length_mm-used,'parts_per_bar':qty,'bars':nest.bars}


def write_ba(nest,path,base_dir='.'):
    parts=[]
    for raw in nest.parts:
        part=NestPart(**raw) if isinstance(raw,dict) else raw
        target=(Path(base_dir)/part.file).resolve()
        parts.append(replace(part,file=os.path.relpath(target,Path(path).parent.resolve())))
    adjusted=replace(nest,parts=parts)
    text,summary=render_ba(adjusted,Path(path).parent.resolve());atomic_write(path,text);return summary
