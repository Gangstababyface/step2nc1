"""Preview geometry shared by GUI and SVG reports (all arcs are sampled)."""
import math


def contour_xy(points,max_degrees=6):
    points=[p for p in points if not p.modifier]
    if not points:return []
    out=[]
    for a,b in zip(points,points[1:]):
        out.append((a.x_mm,a.y_mm))
        dx,dy=b.x_mm-a.x_mm,b.y_mm-a.y_mm;chord=math.hypot(dx,dy)
        r=abs(a.radius_mm)
        if r<1e-9 or chord<1e-9 or chord>2*r+.03:continue
        sign=1 if a.radius_mm>0 else -1
        height=math.sqrt(max(0,r*r-chord*chord/4))
        cx=(a.x_mm+b.x_mm)/2-sign*dy/chord*height
        cy=(a.y_mm+b.y_mm)/2+sign*dx/chord*height
        angle=math.atan2(a.y_mm-cy,a.x_mm-cx)
        sweep=sign*2*math.asin(min(1,chord/(2*r)))
        n=max(1,math.ceil(abs(sweep)/math.radians(max_degrees)))
        for i in range(1,n):out.append((cx+r*math.cos(angle+sweep*i/n),cy+r*math.sin(angle+sweep*i/n)))
    out.append((points[-1].x_mm,points[-1].y_mm));return out


def slot_xy(h,n=16):
    a=math.radians(h.slot_angle_deg);c,s=math.cos(a),math.sin(a)
    gap=h.slot_width_mm or max(0,h.slot_length_mm-h.diameter_mm);height=h.slot_height_mm;r=h.diameter_mm/2
    result=[]
    for cx,cy,start in ((gap/2,-height/2,-math.pi/2),(gap/2,height/2,0),(-gap/2,height/2,math.pi/2),(-gap/2,-height/2,math.pi)):
        for i in range(n//2+1):
            angle=start+math.pi/2*i/(n//2)
            x=cx+r*math.cos(angle);y=cy+r*math.sin(angle)
            result.append((h.x_mm+x*c-y*s,h.y_mm+x*s+y*c))
    return result+[result[0]]
