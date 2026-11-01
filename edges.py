"""Analytic edge arcs and geometric G1/G2 blends, SI metres and degrees.

Independent geometry only; this module does not predict aerodynamic performance.
"""
import math


def defaults(section):
    return dict(enabled=False, le_type='circle', le_radius=section['chord']*.015,
                le_ratio=1.5, le_orientation=0., le_join=.15,
                te_type='circle', te_thickness=section['trailing'], te_ratio=1.5,
                te_wedge=12., te_join=.85, continuity='G2')


def validate(section):
    if 'edges' not in section:return
    value=section.get('edges')
    if not isinstance(value,dict) or type(value.get('enabled')) is not bool:
        raise ValueError('LE/TEの有効設定が不正です。')
    expected=defaults(section)
    if set(value)!=set(expected):raise ValueError('LE/TE設定の項目が不正です。')
    if value['le_type'] not in ('circle','ellipse') or value['te_type'] not in ('circle','ellipse','flat') or value['continuity'] not in ('G1','G2'):
        raise ValueError('LE/TEの形状・連続条件が不正です。')
    limits={'le_radius':(1e-6,section['chord']*.1),'le_ratio':(.3,4),
            'le_orientation':(-30,30),'le_join':(.05,.35),
            'te_thickness':(1e-5,section['chord']*.15),'te_ratio':(.3,4),
            'te_wedge':(0,60),'te_join':(.65,.95)}
    for key,(lo,hi) in limits.items():
        x=value[key]
        if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:
            raise ValueError(f'LE/TE {key}: {lo}～{hi} の有限値を指定してください。')
    if not value['enabled']:return
    if section.get('profile',{}).get('mode')=='direct':
        raise ValueError('両面直接編集ではLE/TE専用設定を有効にできません。')
    q=value['le_ratio'] if value['le_type']=='ellipse' else 1.
    if value['le_radius']*q*q>=.8*section['chord']*value['le_join']:
        raise ValueError('LEの楕円が接続領域に対して大きすぎます。半径・楕円比・接続位置を見直してください。')
    q=value['te_ratio'] if value['te_type']=='ellipse' else 1.
    phi=math.atan2(1.,q*math.tan(math.radians(value['te_wedge']/2)))
    a=q*value['te_thickness']/(2*math.sin(phi))
    if value['te_type']!='flat' and a*(1-math.cos(phi))>=.8*section['chord']*(1-value['te_join']):
        raise ValueError('TEの円弧が接続領域に対して大きすぎます。厚み・楕円比・接続位置を見直してください。')


def add(a,b):return [a[i]+b[i] for i in (0,1)]
def scale(a,k):return [x*k for x in a]
def sub(a,b):return [a[i]-b[i] for i in (0,1)]


def frame(angle):
    t=math.radians(angle);return [math.cos(t),math.sin(t)],[-math.sin(t),math.cos(t)]


def blend(start,end,mode):
    """Hermite polynomial, positions and derivatives with respect to t in [0,1]."""
    coefficients=[]
    for j in (0,1):
        p,v,a=[x[j] for x in start];q,w,b=[x[j] for x in end]
        if mode=='G1':coefficients.append([p,v,3*(q-p)-2*v-w,2*(p-q)+v+w])
        else:
            c=a/2;A=q-p-v-c;B=w-v-2*c;C=b-2*c
            coefficients.append([p,v,c,10*A-4*B+C/2,-15*A+7*B-C,6*A-3*B+C/2])
    def point(t):return [sum(c*t**i for i,c in enumerate(axis)) for axis in coefficients]
    return point


def jet(point,u,span,direction=1):
    h=1e-5;p=[point(u+direction*h*i) for i in range(4)]
    v=[direction*(-3*p[0][j]+4*p[1][j]-p[2][j])/(2*h) for j in (0,1)]
    a=[(2*p[0][j]-5*p[1][j]+4*p[2][j]-p[3][j])/(h*h) for j in (0,1)]
    return p[0],scale(v,span),scale(a,span*span)


def build(section,base):
    """Return point(side,u) and join definitions. Nominal LE/TE anchors are retained."""
    c=section['edges'];chord=section['chord'];le=c['le_join'];te=c['te_join']
    arc_end=le*.35;cap_start=te+(1-te)*.65
    angles=section.get('profile',{}).get('angles')
    inlet=angles[0][1] if angles else section['inlet_angle']
    outlet=angles[-1][1] if angles else section['outlet_angle']
    e,n=frame(inlet+c['le_orientation']);et,nt=frame(outlet)
    nose=scale(add(base(0,0),base(1,0)),.5);tail=scale(add(base(0,1),base(1,1)),.5)
    ratio=c['le_ratio'] if c['le_type']=='ellipse' else 1.
    b=c['le_radius']*ratio;a=b*ratio;centre=add(nose,scale(e,a))
    q=c['te_ratio'] if c['te_type']=='ellipse' else 1.
    phi=math.atan2(1.,q*math.tan(math.radians(c['te_wedge']/2)))
    bt=c['te_thickness']/(2*math.sin(phi));at=q*bt;ct=add(tail,scale(et,-at))
    branches=[]
    for side,sign in ((0,1),(1,-1)):
        def le_arc(t,sign=sign):
            theta=t*math.pi/2
            return add(centre,add(scale(e,-a*math.cos(theta)),scale(n,sign*b*math.sin(theta))))
        shoulder=le_arc(1);target=base(side,le)
        h=min(math.dist(shoulder,target)/a*.6,1.)
        le_curve=blend((shoulder,scale(e,a*h),scale(n,-sign*b*h*h)),
                       jet(lambda u:base(side,u),le,le-arc_end),c['continuity'])
        if c['te_type']=='flat':
            end=add(tail,scale(nt,sign*c['te_thickness']/2))
            direction=add(scale(et,math.cos(math.radians(c['te_wedge']/2))),scale(nt,-sign*math.sin(math.radians(c['te_wedge']/2))))
            te_curve=blend(jet(lambda u:base(side,u),te,1-te,-1),
                           (end,scale(direction,math.dist(base(side,te),end)),[0.,0.]),c['continuity'])
            cap=None
        else:
            def cap(t,sign=sign):
                theta=phi*(1-t)
                return add(ct,add(scale(et,at*math.cos(theta)),scale(nt,sign*bt*math.sin(theta))))
            end=cap(0);h=min(math.dist(base(side,te),end)/max(at,bt)*.6,1.)
            v=scale(add(scale(et,at*math.sin(phi)),scale(nt,-sign*bt*math.cos(phi))),h)
            acc=scale(add(scale(et,-at*math.cos(phi)),scale(nt,-sign*bt*math.sin(phi))),h*h)
            te_curve=blend(jet(lambda u:base(side,u),te,cap_start-te,-1),(end,v,acc),c['continuity'])
        branches.append((le_arc,le_curve,te_curve,cap))
    def point(side,u):
        la,lb,tb,cap=branches[side]
        if u<arc_end:return la(u/arc_end)
        if u<le:return lb((u-arc_end)/(le-arc_end))
        if u<=te:return base(side,u)
        if cap is None:return tb((u-te)/(1-te))
        if u<cap_start:return tb((u-te)/(cap_start-te))
        return cap((u-cap_start)/(1-cap_start))
    joins=[('LE arc/blend',arc_end),('LE blend/body',le),('TE body/blend',te)]
    if c['te_type']!='flat':joins.append(('TE blend/arc',cap_start))
    return point,joins


def diagnostics(point,joins):
    """Independent one-sided finite differences; geometric rather than parametric continuity."""
    records=[];h=1e-5
    def endpoint(side,u,sign):
        p=[point(side,u+sign*h*i) for i in range(4)]
        v=[sign*(-3*p[0][j]+4*p[1][j]-p[2][j])/(2*h) for j in (0,1)]
        a=[(2*p[0][j]-5*p[1][j]+4*p[2][j]-p[3][j])/(h*h) for j in (0,1)]
        speed=math.hypot(*v)
        k=(v[0]*a[1]-v[1]*a[0])/max(speed**3,1e-30)
        return v,k
    for label,u in joins:
        for side in (0,1):
            va,ka=endpoint(side,u,-1);vb,kb=endpoint(side,u,1)
            angle=math.degrees(math.atan2(abs(va[0]*vb[1]-va[1]*vb[0]),sum(x*y for x,y in zip(va,vb))))
            records.append(dict(join=label,side='A' if side==0 else 'B',parameter=u,
                                tangent_error_deg=angle,curvature_left=ka,curvature_right=kb,
                                curvature_jump_per_m=abs(ka-kb),curvature_relative=abs(ka-kb)/max(abs(ka),abs(kb),1.)))
    return records
