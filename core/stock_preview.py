"""Display stock end planes from DSTV header angles (not machining toolpaths)."""
import math


def face_span(section,face):
    p=section.profile
    if section.family=='HSS_R':return math.pi*p.d_mm
    return p.d_mm if face in ('v','h') else p.bf_mm


def end_outline(section,cuts,face):
    if any(not math.isfinite(a) or abs(a)>=90 for a in vars(cuts).values()):return []
    p=section.profile;d,w,L=p.d_mm,p.bf_mm,section.length_in*25.4
    span=face_span(section,face)
    if section.family=='HSS_R':
        if face!='v':return []
        ordinates=[span*i/96 for i in range(97)]
        def coordinates(s):
            theta=s/(d/2)
            return d/2+d/2*math.sin(theta),d/2-d/2*math.cos(theta)
    else:
        ordinates=[0,span]
        def coordinates(s):
            if face in ('o','u'):return (d if face=='o' else 0),s
            z=(w-p.tw_mm)/2 if section.family=='W' and face=='v' else (w if face=='h' else 0)
            return s,z
    def support(a,b):
        if section.family=='HSS_R':
            center=d/2*(a+b);radius=d/2*math.hypot(a,b)
            return center-radius,center+radius
        if section.family=='HSS':
            r=p.outside_radius*25.4
            if r:
                center=(a*d+b*w)/2
                reach=abs(a)*(d/2-r)+abs(b)*(w/2-r)+r*math.hypot(a,b)
                return center-reach,center+reach
        if section.cross_polys:
            values=[a*v.y*25.4+b*v.x*25.4 for poly in section.cross_polys for v in poly]
        elif section.family=='L':
            t=p.t_wall_mm
            values=[a*y+b*z for y,z in [(0,0),(0,w),(t,w),(t,t),(d,t),(d,0)]]
        else:values=[a*y+b*z for y,z in [(0,0),(0,w),(d,w),(d,0)]]
        return min(values),max(values)
    lines=[]
    for side in ('start','end'):
        a=math.tan(math.radians(getattr(cuts,'web_'+side+'_deg')))
        b=math.tan(math.radians(getattr(cuts,'flange_'+side+'_deg')))
        lo,hi=support(a,b);offset=hi if side=='start' else L+lo
        line=[]
        for s in ordinates:
            y,z=coordinates(s);line.append((offset-a*y-b*z,s))
        lines.append(line)
    return lines[0]+list(reversed(lines[1]))+[lines[0][0]]
