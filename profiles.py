"""Blade section distributions, cubic B-spline surfaces and geometric diagnostics.

All lengths are metres. Geometry is independent of the aerodynamic solver.
"""
import copy
import math
import uuid
from datetime import datetime, timezone

FIELDS = ('span', 'chord', 'inlet_angle', 'outlet_angle', 'stagger', 'thickness', 'peak', 'trailing', 'sweep', 'lean')


def finite(value, lo, hi):
    return type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi


def validate_profile(section):
    limits={'span':(0,1),'chord':(.001,2),'inlet_angle':(-75,75),'outlet_angle':(-75,75),
            'stagger':(-70,70),'thickness':(.00001,.5),'peak':(.1,.8),'trailing':(.00001,.1),
            'sweep':(-2,2),'lean':(-2,2)}
    if any(not finite(section.get(k),*v) for k,v in limits.items()) or section['thickness']>=section['chord']*.4 or section['trailing']>section['thickness']:
        raise ValueError('翼断面または変換前形状の基本値が不正です。')
    p = section.get('profile')
    if p is not None:
        if not isinstance(p, dict) or p.get('mode') not in ('distribution', 'direct'):
            raise ValueError('翼断面の編集方式が不正です。')
        if p['mode'] == 'distribution':
            for key, lo, hi in [('angles', -75, 75), ('thicknesses', 0, section['chord']*.4)]:
                points = p.get(key)
                if not isinstance(points, list) or not 3 <= len(points) <= 41:
                    raise ValueError('分布曲線は3～41個の点で定義してください。')
                if any(not isinstance(v, list) or len(v) != 2 or not finite(v[0], 0, 1) or not finite(v[1], lo, hi) for v in points):
                    raise ValueError('分布曲線の位置・値が範囲外です。')
                if points[0][0] != 0 or points[-1][0] != 1 or any(b[0] <= a[0] for a, b in zip(points, points[1:])):
                    raise ValueError('分布点は0～1の昇順とし、両端を含めてください。')
            if p['thicknesses'][0][1] != 0 or any(v[1] <= 0 for v in p['thicknesses'][1:]):
                raise ValueError('前縁厚みは0、前縁以外の厚みは正にしてください。')
        else:
            for key in ('side_a', 'side_b'):
                points = p.get(key)
                if not isinstance(points, list) or not 6 <= len(points) <= 25:
                    raise ValueError('各面のB-spline制御点は6～25個です。')
                if any(not isinstance(v, list) or len(v) != 2 or any(not finite(x, -5, 5) for x in v) for v in points):
                    raise ValueError('面の制御点は有限の座標[m]で指定してください。')
            if len(p['side_a']) != len(p['side_b']):
                raise ValueError('両面の制御点数を揃えてください。')
            if math.dist(p['side_a'][0], p['side_b'][0]) > 1e-10:
                raise ValueError('両面の前縁始点を共有してください。')
            if type(p.get('lock_nose_tangent',True)) is not bool:
                raise ValueError('前縁接線の連動設定が不正です。')
            aa,bb=p['side_a'],p['side_b']
            if (aa[-1][0]+bb[-1][0])/2 <= aa[0][0]+1e-6:
                raise ValueError('後縁中心は前縁より下流に配置してください。')
            if p.get('lock_nose_tangent',True):
                va=[aa[1][j]-aa[0][j] for j in (0,1)]
                vb=[bb[1][j]-bb[0][j] for j in (0,1)]
                den=math.hypot(*va)*math.hypot(*vb)
                if den<1e-20 or sum(x*y for x,y in zip(va,vb))>=0 or abs(va[0]*vb[1]-va[1]*vb[0])>den*1e-7:
                    raise ValueError('前縁接線の連動が有効な場合は両ハンドルを逆向きに揃えてください。')
    history = section.get('profile_history', [])
    if not isinstance(history, list) or len(history) > 8:
        raise ValueError('変換前形状の履歴は最大8件です。')
    # Validate archived shapes too, without recursive archives.
    for item in history:
        if not isinstance(item, dict) or not isinstance(item.get('source'),dict) or 'profile_history' in item['source']:
            raise ValueError('変換履歴が不正です。')
        archived = item['source']
        validate_profile(archived)
        error=item.get('conversion_error',{})
        if any(not finite(error.get(k),0,100) for k in ('max_m','rms_m')):
            raise ValueError('変換誤差の記録が不正です。')


def legacy_camber(s, u):
    m0, m1, end = [math.tan(math.radians(s[k])) for k in ('inlet_angle', 'outlet_angle', 'stagger')]
    y = s['chord']*((u**3-2*u*u+u)*m0+(-2*u**3+3*u*u)*end+(u**3-u*u)*m1)
    slope = (3*u*u-4*u+1)*m0+(-6*u*u+6*u)*end+(3*u*u-2*u)*m1
    return y, slope


def legacy_thickness(s, u):
    if u <= s['peak']:
        return s['thickness']*math.sqrt(max(0, 1-(1-u/s['peak'])**2))
    t = (u-s['peak'])/(1-s['peak'])
    return s['trailing']+(s['thickness']-s['trailing'])*(1-3*t*t+2*t**3)


def pchip(points, x):
    """Shape preserving cubic Hermite interpolation (Fritsch/Butland slopes)."""
    xs, ys = zip(*points)
    h = [b-a for a, b in zip(xs, xs[1:])]
    delta = [(b-a)/w for a, b, w in zip(ys, ys[1:], h)]
    m = [0.]*len(xs)
    for i in range(1, len(xs)-1):
        if delta[i-1]*delta[i] > 0:
            w1, w2 = 2*h[i]+h[i-1], h[i]+2*h[i-1]
            m[i] = (w1+w2)/(w1/delta[i-1]+w2/delta[i])
    def endpoint(h0, h1, d0, d1):
        value = ((2*h0+h1)*d0-h0*d1)/(h0+h1)
        if value*d0 <= 0:
            return 0.
        return math.copysign(min(abs(value),3*abs(d0)),value) if d0*d1 < 0 else value
    m[0] = endpoint(h[0],h[1],delta[0],delta[1])
    m[-1] = endpoint(h[-1],h[-2],delta[-1],delta[-2])
    i = next((j for j in range(len(h)) if x <= xs[j+1]), len(h)-1)
    t = max(0., min(1., (x-xs[i])/h[i]))
    return (2*t**3-3*t*t+1)*ys[i]+(t**3-2*t*t+t)*h[i]*m[i]+(-2*t**3+3*t*t)*ys[i+1]+(t**3-t*t)*h[i]*m[i+1]


def knots(count):
    return [0.]*4+[i/(count-3) for i in range(1,count-3)]+[1.]*4


def basis(count, u):
    if u >= 1:
        return [0.]*(count-1)+[1.]
    k = knots(count)
    values = [float(k[i] <= u < k[i+1]) for i in range(len(k)-1)]
    for degree in range(1,4):
        out=[]
        for i in range(len(values)-1):
            a, b = k[i+degree]-k[i], k[i+degree+1]-k[i+1]
            out.append(((u-k[i])/a*values[i] if a else 0)+((k[i+degree+1]-u)/b*values[i+1] if b else 0))
        values=out
    return values


def bspline(points, u):
    weights = basis(len(points),u)
    return [sum(w*p[j] for w,p in zip(weights,points)) for j in (0,1)]


def resample(points, n):
    distances=[0.]
    for a,b in zip(points,points[1:]):
        distances.append(distances[-1]+math.dist(a,b))
    if distances[-1] < 1e-12:
        raise ValueError('長さが0の翼面は生成できません。')
    out=[]
    j=0
    for i in range(n):
        target=distances[-1]*i/(n-1)
        while j < len(points)-2 and distances[j+1] < target:
            j+=1
        w=(target-distances[j])/max(distances[j+1]-distances[j],1e-30)
        out.append([a*(1-w)+b*w for a,b in zip(points[j],points[j+1])])
    return out


def linear_solve(matrix, rhs):
    a=[row[:]+[v] for row,v in zip(matrix,rhs)]
    n=len(rhs)
    for i in range(n):
        j=max(range(i,n),key=lambda j:abs(a[j][i]))
        a[i],a[j]=a[j],a[i]
        if abs(a[i][i]) < 1e-14:
            raise ValueError('曲線近似を解けません。制御点数を変更してください。')
        v=a[i][i]
        a[i]=[x/v for x in a[i]]
        for j in range(n):
            if j!=i:
                f=a[j][i]
                a[j]=[x-f*y for x,y in zip(a[j],a[i])]
    return [row[-1] for row in a]


def fit_bspline(points, count=17):
    samples=resample(points,201)
    weights=[basis(count,i/200) for i in range(201)]
    matrix=[[sum(w[i]*w[j] for w in weights) for j in range(1,count-1)] for i in range(1,count-1)]
    coordinates=[]
    for dim in (0,1):
        residual=[p[dim]-w[0]*points[0][dim]-w[-1]*points[-1][dim] for p,w in zip(samples,weights)]
        rhs=[sum(w[i]*r for w,r in zip(weights,residual)) for i in range(1,count-1)]
        coordinates.append([points[0][dim]]+linear_solve(matrix,rhs)+[points[-1][dim]])
    return [list(p) for p in zip(*coordinates)]


def section_profile(s, n=81):
    p=s.get('profile',{})
    if p.get('mode') == 'direct':
        return [[ [x+s['sweep'],y+s['lean']] for x,y in [bspline(p[key],i/(n-1)) for i in range(n)]] for key in ('side_a','side_b')]
    if p.get('mode') == '_loft':
        return copy.deepcopy(p['samples'])
    sides=[[],[]]
    integral=[0.]
    if p.get('mode') == 'distribution':
        slopes=[math.tan(math.radians(pchip(p['angles'],i/400))) for i in range(401)]
        for a,b in zip(slopes,slopes[1:]):
            integral.append(integral[-1]+(a+b)*s['chord']/800)
        thick_points=[[math.sqrt(x),t] for x,t in p['thicknesses']]
    for i in range(n):
        u=i/(n-1)
        if p.get('mode') == 'distribution':
            q=u*400
            j=min(399,int(q))
            y=integral[j]*(1-(q-j))+integral[j+1]*(q-j)
            slope=math.tan(math.radians(pchip(p['angles'],u)))
            thickness=pchip(thick_points,math.sqrt(u))
        else:
            y,slope=legacy_camber(s,u)
            thickness=legacy_thickness(s,u)
        norm=math.hypot(1,slope)
        for sign,side in zip((1,-1),sides):
            side.append([s['chord']*u-sign*thickness*slope/(2*norm)+s['sweep'],y+sign*thickness/(2*norm)+s['lean']])
    return sides


def interpolate_section(sections, span):
    for a,b in zip(sections,sections[1:]):
        if a['span'] <= span <= b['span']:
            if span==a['span']:return copy.deepcopy(a)
            if span==b['span']:return copy.deepcopy(b)
            w=(span-a['span'])/(b['span']-a['span'])
            s={k:a[k]*(1-w)+b[k]*w for k in FIELDS}
            if a.get('profile') or b.get('profile'):
                aa=[resample(side,81) for side in section_profile(a,161)]
                bb=[resample(side,81) for side in section_profile(b,161)]
                s['profile']={'mode':'_loft','samples':[[[x*(1-w)+y*w for x,y in zip(p,q)] for p,q in zip(sa,sb)] for sa,sb in zip(aa,bb)]}
            return s
    raise ValueError('スパンが範囲外です。')


def point_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(dx*dx+dy*dy,1e-30)))
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def curve_error(source,target):
    distances=[]
    for aa,bb in zip(source,target):
        for a,b in ((aa,bb),(bb,aa)):
            distances.extend(min(point_distance(p,x,y) for x,y in zip(b,b[1:])) for p in a)
    return {'max_m':max(distances),'rms_m':math.sqrt(sum(x*x for x in distances)/len(distances)),
            'method':'symmetric sampled point-to-polyline distance; not exact Hausdorff'}


def to_distribution(s):
    if s.get('profile',{}).get('mode') == 'direct':
        raise ValueError('直接編集から分布方式への自動再近似には対応していません。変換前形状へ戻してください。')
    if s.get('profile',{}).get('mode') == 'distribution':
        return copy.deepcopy(s)
    out=copy.deepcopy(s)
    us=sorted(set([0.,s['peak'],1.]+[(i/16)**2 for i in range(1,16)]))
    out['profile']={'mode':'distribution','angles':[[u,math.degrees(math.atan(legacy_camber(s,u)[1]))] for u in us],
                    'thicknesses':[[u,legacy_thickness(s,u)] for u in us]}
    if any(abs(v[1])>75 for v in out['profile']['angles']):
        raise ValueError('中心線の途中の角度が±75°を超えています。基本形状を見直してください。')
    return out


def convert_section(s, target, count=17):
    if target not in ('distribution','direct'):
        raise ValueError('変換先が不正です。')
    source=section_profile(s,161)
    if target=='distribution':
        out=to_distribution(s)
    else:
        if s.get('profile',{}).get('mode')=='direct':
            raise ValueError('すでに両面直接編集です。')
        out=copy.deepcopy(s)
        sides=[[[x-s['sweep'],y-s['lean']] for x,y in side] for side in source]
        aa,bb=[fit_bspline(side,count) for side in sides]
        # Shared nose, opposing tangents. Preserve separate handle lengths.
        nose=aa[0]
        v=[aa[1][j]-nose[j]-(bb[1][j]-nose[j]) for j in (0,1)]
        length=math.hypot(*v)
        if length>1e-12:
            for sign,side in ((1,aa),(-1,bb)):
                h=math.dist(side[0],side[1])
                side[1]=[nose[j]+sign*h*v[j]/length for j in (0,1)]
        out['profile']={'mode':'direct','side_a':aa,'side_b':bb,'lock_nose_tangent':True}
    original={k:copy.deepcopy(v) for k,v in s.items() if k!='profile_history'}
    error=curve_error(source,section_profile(out,161))
    history=s.get('profile_history',[])
    out['profile_history']=(copy.deepcopy(history)+[{'id':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),
                                                    'source':original,'target_mode':target,'conversion_error':error}])[-8:]
    validate_profile(out)
    return out,error


def restore_section(s):
    history=s.get('profile_history',[])
    if not history:raise ValueError('変換前形状がありません。')
    out=copy.deepcopy(history[-1]['source'])
    out['id']=s['id']
    out['span']=s['span']
    out['profile_history']=copy.deepcopy(history[:-1])
    return out


def curvature(points):
    out=[]
    for a,b,c in zip(points,points[1:],points[2:]):
        den=math.dist(a,b)*math.dist(b,c)*math.dist(c,a)
        cross=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        out.append(2*cross/den if den>1e-20 else 0.)
    return out


def section_metrics(s, sides=None):
    a,b=sides or section_profile(s)
    ka,kb=curvature(a),curvature(b)
    le=[(x+y)/2 for x,y in zip(a[0],b[0])]
    te=[(x+y)/2 for x,y in zip(a[-1],b[-1])]
    axial_chord=te[0]-le[0]
    # Exclude leading/trailing 5% of axial chord from the thickness proxy.
    local_a=[p for p in a if .05*axial_chord < p[0]-le[0] < .95*axial_chord]
    local_b=[p for p in b if .05*axial_chord < p[0]-le[0] < .95*axial_chord]
    minimum=None
    if len(local_a)>1 and len(local_b)>1:
        minimum=min(point_distance(p,x,y) for p in local_a for x,y in zip(local_b,local_b[1:]))
    av=[a[1][i]-a[0][i] for i in (0,1)]
    bv=[b[1][i]-b[0][i] for i in (0,1)]
    den=math.hypot(*av)*math.hypot(*bv)
    tangent_error=math.degrees(math.atan2(abs(av[0]*bv[1]-av[1]*bv[0]),-sum(x*y for x,y in zip(av,bv)))) if den>1e-20 else None
    p=s.get('profile',{})
    if p.get('mode')=='direct':
        av=[p['side_a'][1][i]-p['side_a'][0][i] for i in (0,1)]
        bv=[p['side_b'][1][i]-p['side_b'][0][i] for i in (0,1)]
        den=math.hypot(*av)*math.hypot(*bv)
        tangent_error=math.degrees(math.atan2(abs(av[0]*bv[1]-av[1]*bv[0]),-sum(x*y for x,y in zip(av,bv)))) if den>1e-20 else None
    return {'span':s['span'],'leading_gap_m':math.dist(a[0],b[0]),'trailing_gap_m':math.dist(a[-1],b[-1]),
            'axial_chord_m':axial_chord,'nose_tangent_method':'B-spline endpoint derivative' if p.get('mode')=='direct' else 'sampled segments',
            'nose_tangent_error_deg':tangent_error,'minimum_surface_distance_m':minimum,
            'stagger_deg':math.degrees(math.atan2(te[1]-le[1],te[0]-le[0])),
            'max_abs_curvature_per_m':max(abs(x) for x in ka+kb),'curvature_a':ka,'curvature_b':kb,
            'max_pair_distance_m':max(math.dist(x,y) for x,y in zip(a,b)),
            'thickness_note':'sampled nearest surface distance in 5–95% axial chord; not normal wall thickness'}
