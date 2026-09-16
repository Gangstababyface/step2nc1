"""Validation shared by GUI, CLI and exporters."""
import math

class ValidationError(ValueError):
    pass


def finite(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValidationError(f'{label} must be a finite number.')


def text_value(value,label,maxlen=80):
    if not isinstance(value,str) or len(value)>maxlen:
        raise ValidationError(f'{label} must be text up to {maxlen} characters.')
    if any(ord(c)<32 or ord(c)>126 for c in value):
        raise ValidationError(f'{label} must be single-line ASCII text (DSTV requirement).')


def validate_features(fs,header=None):
    errors=list(fs.errors)
    def check():
        s=fs.section;p=s.profile
        for key in ('d','bf','tf','tw','t_wall','k','weight_per_ft','outside_radius'):
            value=getattr(p,key);finite(value,key)
            if value<0:raise ValidationError(f'{key} cannot be negative.')
        finite(s.paint_per_m,'Paint per metre')
        if s.paint_per_m<0:raise ValidationError('Paint surface cannot be negative.')
        if fs.extra_blocks:raise ValidationError('Additional NC1 blocks are inspect-only in this version.')
        for c in fs.comments:text_value(c,'Comment',1024)
        finite(s.length_in,'Length')
        if s.length_in<=0 or p.d<=0 or p.bf<=0:raise ValidationError('Length, depth and width must be positive.')
        if s.family not in ('W','C','L','HSS','HSS_R','PLATE'):raise ValidationError('Unsupported profile family.')
        if s.family=='HSS_R':
            if abs(p.d-p.bf)>.001 or not (0<p.t_wall<p.d/2):raise ValidationError('Round pipe needs equal outside diameters and a wall thinner than its radius.')
        if s.family in ('W','C') and not (0<p.tf<p.d/2 and 0<p.tw<p.bf):raise ValidationError('Invalid web/flange thickness.')
        if s.family in ('L','HSS') and not (0<p.t_wall<min(p.d,p.bf)/(2 if s.family=='HSS' else 1)):raise ValidationError('Invalid wall thickness.')
        def pos(obj,label):
            if obj.surface not in 'vouh' or len(obj.surface)!=1:raise ValidationError(f'{label}: invalid face.')
            if s.family=='HSS_R' and obj.surface!='v':raise ValidationError('Round pipe uses the unrolled face v only.')
            finite(obj.x_mm,label+' X');finite(obj.y_mm,label+' Y')
            width=p.d_mm if obj.surface in ('v','h') else p.bf_mm
            if s.family=='HSS_R':width=math.pi*p.d_mm
            if not (-.05<=obj.x_mm<=s.length_in*25.4+.05 and -.05<=obj.y_mm<=width+.05):
                raise ValidationError(f'{label} is outside the part envelope: {obj.surface} ({obj.x_mm:.3f}, {obj.y_mm:.3f}).')
            if obj.reference not in ('','u','o','s'):raise ValidationError('Invalid dimension reference.')
        for h in fs.holes:
            pos(h,'Hole');finite(h.diameter_mm,'Hole diameter');finite(h.depth_mm,'Hole depth')
            if h.diameter_mm<0 or (h.diameter_mm==0 and h.operation!='m'):raise ValidationError('Hole diameter must be positive (point marks use zero).')
            if h.operation not in ('','m','s','g','l'):raise ValidationError('Unknown hole operation.')
            if h.depth_mm<0:raise ValidationError('Hole depth cannot be negative.')
            for k in ('slot_length_mm','slot_angle_deg','slot_width_mm','slot_height_mm'):finite(getattr(h,k),k)
            if h.slotted and h.slot_length_mm<h.diameter_mm and not (h.slot_width_mm or h.slot_height_mm):raise ValidationError('Slot overall length must be at least its diameter.')
        groups=[('AK',c) for c in fs.all_outer_contours()]+[('IK',c) for c in fs.inner_contours]+[('PU',c) for c in fs.powder_contours]+[('KO',c) for c in fs.scribe_contours]
        for code,c in groups:
            if len(c)<(3 if code in ('AK','IK') else 2):raise ValidationError(f'{code}: too few contour points.')
            if len({v.surface for v in c})!=1:raise ValidationError(f'{code}: one face is required per contour.')
            if code in ('AK','IK') and math.hypot(c[0].x_mm-c[-1].x_mm,c[0].y_mm-c[-1].y_mm)>.025:raise ValidationError(f'{code}: contour must be closed.')
            for i,v in enumerate(c):
                pos(v,code+' point')
                for k in ('radius_mm','bevel_angle_1','bevel_depth_1','bevel_angle_2','bevel_depth_2'):finite(getattr(v,k),k)
                if v.modifier not in ('','t','w'):raise ValidationError('Unknown contour modifier.')
                if i<len(c)-1 and v.radius_mm and not (v.modifier or c[i+1].modifier):
                    distance=math.hypot(c[i+1].x_mm-v.x_mm,c[i+1].y_mm-v.y_mm)
                    if distance>2*abs(v.radius_mm)+.03:raise ValidationError('Arc radius is smaller than half its chord.')
        for m in fs.markings:
            pos(m,'Text');finite(m.height_mm,'Text height');finite(m.angle_deg,'Text angle')
            if m.height_mm<=0:raise ValidationError('Text height must be positive.')
            text_value(m.text,'Marking text')
            if m.mode not in ('','r','z'):raise ValidationError('Invalid text transform mode.')
        for name,value in vars(fs.end_cuts).items():
            finite(value,name)
            if abs(value)>=90:raise ValidationError('Miter angles must be between -90 and 90 degrees.')
        if header:
            for key,value in vars(header).items():
                if isinstance(value,str):text_value(value,key)
            if not isinstance(header.quantity,int) or isinstance(header.quantity,bool) or header.quantity<1:raise ValidationError('Quantity must be a positive integer.')
            if header.profile_code and header.profile_code!=p.dstv_code:raise ValidationError('Header profile code disagrees with the section family.')
            for k in ('paint_per_m','weight_per_m'):
                if getattr(header,k) is not None:
                    finite(getattr(header,k),k)
                    if getattr(header,k)<0:raise ValidationError(k+' cannot be negative.')
            if header.saw_length_mm is not None:
                finite(header.saw_length_mm,'Saw length')
                if header.saw_length_mm<=0:raise ValidationError('Saw length must be positive.')
    try:check()
    except ValidationError as exc:errors.append(str(exc))
    if errors:raise ValidationError('\n'.join(dict.fromkeys(errors)))
    return list(fs.warnings)
