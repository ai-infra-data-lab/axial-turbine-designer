"""Independent meridional geometry and layout. SI units; no flow solver."""
import bisect
import math
from profiles import section_profile, interpolate_section


def rows(d):
    return [(si,ri,row) for si,stage in enumerate(d['stages']) for ri,row in enumerate(stage['rows'])]


def local_bounds(row):
    values=[p[0] for s in row['sections'] for side in section_profile(s,161) for p in side]
    return min(values),max(values)


def defaults(d):
    placements={};cursor=0.;lo=0.;hi=0.
    for _,_,row in rows(d):
        a,b=local_bounds(row);origin=cursor-a;placements[row['id']]=origin
        lo=min(lo,origin,cursor);hi=max(hi,origin+b);cursor=origin+b+.01
    return {'enabled':False,'interpolation':'pchip',
            'hub':[[lo-.02,d['geometry']['hub_radius']],[hi+.02,d['geometry']['hub_radius']]],
            'casing':[[lo-.02,d['geometry']['tip_radius']],[hi+.02,d['geometry']['tip_radius']]],
            'placements':placements}


def finite(x,lo,hi):return type(x) in (int,float) and math.isfinite(x) and lo<=x<=hi


class Curve:
    """Shape-preserving Hermite cubic with analytic first/second derivatives."""
    def __init__(self,points,mode='pchip'):
        self.points=points;self.x=[p[0] for p in points]
        h=[b[0]-a[0] for a,b in zip(points,points[1:])]
        delta=[(b[1]-a[1])/v for a,b,v in zip(points,points[1:],h)]
        slopes=[delta[0]]*len(points)
        if len(points)>2:
            for i in range(1,len(points)-1):
                w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1]
                slopes[i]=(w1+w2)/(w1/delta[i-1]+w2/delta[i]) if delta[i-1]*delta[i]>0 else 0.
            def end(a,b,da,db):
                v=((2*a+b)*da-a*db)/(a+b)
                return 0. if v*da<=0 else math.copysign(min(abs(v),3*abs(da)),v) if da*db<0 else v
            slopes[0]=end(h[0],h[1],delta[0],delta[1])
            slopes[-1]=end(h[-1],h[-2],delta[-1],delta[-2])
        self.coefficients=[]
        for i,dx in enumerate(h):
            p=points[i][1];v=slopes[i];w=slopes[i+1];m=delta[i]
            self.coefficients.append((p,m,0.,0.) if mode=='linear' else (p,v,(3*m-2*v-w)/dx,(v+w-2*m)/(dx*dx)))

    def jet(self,x,left=False):
        if x<self.x[0]-1e-10 or x>self.x[-1]+1e-10:raise ValueError('翼形状・配置が子午面の軸方向範囲外です。曲線の定義範囲を広げてください。')
        x=max(self.x[0],min(self.x[-1],x))
        i=max(0,min(len(self.coefficients)-1,(bisect.bisect_left(self.x,x) if left else bisect.bisect_right(self.x,x))-1))
        t=x-self.x[i];a,b,c,e=self.coefficients[i]
        return a+b*t+c*t*t+e*t**3,b+2*c*t+3*e*t*t,2*c+6*e*t,6*e


def roots(a,b,c):
    if abs(a)<1e-20:return [-c/b] if abs(b)>1e-20 else []
    disc=b*b-4*a*c
    if disc<0:return []
    q=-.5*(b+math.copysign(math.sqrt(disc),b))
    return [q/a,c/q] if abs(q)>1e-30 else [-b/(2*a)]


def minimum_gap(hub,casing):
    knots=sorted(set(hub.x+casing.x));minimum=float('inf')
    for a,b in zip(knots,knots[1:]):
        h=hub.jet(a);c=casing.jet(a);coeff=[c[i]-h[i] for i in range(4)]
        candidates=[0.,b-a]+[t for t in roots(coeff[3]/2,coeff[2],coeff[1]) if 0<t<b-a]
        minimum=min(minimum,min(coeff[0]+coeff[1]*t+coeff[2]*t*t/2+coeff[3]*t**3/6 for t in candidates))
    return minimum


def validate(d):
    m=d['meridional']
    if not isinstance(m,dict) or set(m)!={'enabled','interpolation','hub','casing','placements'} or type(m.get('enabled')) is not bool or m.get('interpolation') not in ('linear','pchip'):
        raise ValueError('子午面の設定形式が不正です。')
    for name in ('hub','casing'):
        points=m[name]
        if not isinstance(points,list) or not 2<=len(points)<=41 or any(not isinstance(p,list) or len(p)!=2 or not finite(p[0],-20,20) or not finite(p[1],.0001,30) for p in points):
            raise ValueError('子午面の点列は2～41点、xは±20 m、半径は0.0001～30 mです。')
        if any(b[0]-a[0]<1e-5 for a,b in zip(points,points[1:])):raise ValueError('子午面のxは1e-5 m以上の間隔で昇順にしてください。')
    if any(abs(m['hub'][i][0]-m['casing'][i][0])>1e-10 for i in (0,-1)):raise ValueError('ハブ・ケーシング曲線の軸方向始点と終点を揃えてください。')
    hub,casing=curves(d)
    if minimum_gap(hub,casing)<=1e-6:raise ValueError('子午面のハブ・ケーシングが交差するか、流路高さが1e-6 m以下です。')
    placements=m['placements']
    if not isinstance(placements,dict) or len(placements)>24 or any(not isinstance(k,str) or not finite(v,-20,20) for k,v in placements.items()):raise ValueError('翼列配置の形式が不正です。')
    if not m['enabled']:return
    row_list=rows(d)
    if set(placements)!={row['id'] for _,_,row in row_list}:raise ValueError('子午面の翼列IDが現在の段構成と一致しません。配置を更新してください。')
    leading=[]
    for _,_,row in row_list:
        sides=section_profile(interpolate_section(row['sections'],.5),81)
        leading.append(placements[row['id']]+sum(side[0][0] for side in sides)/2)
    if any(b<=a for a,b in zip(leading,leading[1:])):raise ValueError('翼列の参照LEは静翼・動翼の順で下流へ配置してください。')
    for _,_,row in row_list:
        a,b=local_bounds(row);origin=placements[row['id']]
        for x in (origin,origin+a,origin+b):hub.jet(x)


def curves(d):
    m=d['meridional'];return Curve(m['hub'],m['interpolation']),Curve(m['casing'],m['interpolation'])


def reference_cylinder(d):
    m=d['meridional']
    return all(abs(p[1]-d['geometry']['hub_radius'])<1e-12 for p in m['hub']) and all(abs(p[1]-d['geometry']['tip_radius'])<1e-12 for p in m['casing'])


def map_sides(d,row,span,sides,wall_curves=None):
    hub,casing=wall_curves or curves(d);origin=d['meridional']['placements'][row['id']]
    output=[]
    for side in sides:
        points=[]
        for x,y in side:
            x+=origin;rh=hub.jet(x)[0];rt=casing.jet(x)[0];r=rh+span*(rt-rh)
            points.append([x,r*math.sin(y/r),r*math.cos(y/r)])
        output.append(points)
    return output


def report(d,result=None):
    m=d['meridional'];hub,casing=curves(d);xs=sorted(set(hub.x+casing.x+[hub.x[0]+(hub.x[-1]-hub.x[0])*i/100 for i in range(101)]))
    samples=[]
    for x in xs:
        h=hub.jet(x);c=casing.jet(x)
        hk=None if m['interpolation']=='linear' and x in hub.x[1:-1] else h[2]/(1+h[1]**2)**1.5
        ck=None if m['interpolation']=='linear' and x in casing.x[1:-1] else c[2]/(1+c[1]**2)**1.5
        samples.append({'x':x,'hub_radius':h[0],'casing_radius':c[0],'height':c[0]-h[0],
                        'mean_radius':(h[0]+c[0])/2,'area':math.pi*(c[0]**2-h[0]**2),
                        'hub_angle':math.degrees(math.atan(h[1])),'casing_angle':math.degrees(math.atan(c[1])),
                        'hub_curvature':hk,'casing_curvature':ck})
    layout=[];warnings=[];previous=None
    for si,ri,row in rows(d):
        if row['id'] not in m['placements']:continue
        origin=m['placements'][row['id']];a,b=local_bounds(row)
        section=interpolate_section(row['sections'],.5);sides=section_profile(section,161)
        le=origin+sum(side[0][0] for side in sides)/2;te=origin+sum(side[-1][0] for side in sides)/2
        gap=origin+a-previous if previous is not None else None;previous=origin+b
        if gap is not None and gap<0:warnings.append(f'第{si+1}段 {row["kind"]}: 前の翼列と軸方向包絡が重なります（スパンを含む近似判定）。')
        layout.append({'row_id':row['id'],'stage':si+1,'kind':row['kind'],'origin':origin,'reference_le':le,'reference_te':te,
                       'reference_axial_chord':te-le,'minimum_x':origin+a,'maximum_x':origin+b,'gap_before':gap})
    comparisons=[]
    if result and m['enabled']:
        for stage in result['stages']:
            row=d['stages'][stage['stage']-1]['rows'][1];placement=next(p for p in layout if p['row_id']==row['id'])
            for key,xkey in [('inlet','reference_le'),('outlet','reference_te')]:
                x=placement[xkey];rh=hub.jet(x)[0];rt=casing.jet(x)[0];area=math.pi*(rt*rt-rh*rh);required=stage[key]['area']
                comparisons.append({'stage':stage['stage'],'row_id':row['id'],'station':key,'x':x,'area':area,'required_area':required,'relative_difference':area/required-1})
        if any(abs(v['relative_difference'])>.05 for v in comparisons):warnings.append('設計子午面と参考1Dの必要面積に5%超の差があります。')
        if any(not p['hub_radius']<d['conditions']['mean_radius']<p['casing_radius'] for p in samples):warnings.append('基準平均半径が設計流路の外にある区間があります。参考1Dと実形状の対応を見直してください。')
        if d['analysis'].get('meridional_area'):
            warnings.append('設計子午面の動翼前後縁面積から軸流速度を求めています。半径方向平衡と翼列損失は連成していません。')
        else:
            warnings.append('1Dは一定の基準半径・軸流速度による参考計算です。設計子午面で流量・流線曲率を解いていません。')
    if m['interpolation']=='linear':warnings.append('直線補間の点列接続には角があり、その位置の曲率は評価できません。')
    else:warnings.append('PCHIPは接線連続です。点列の接続位置で曲率が連続する保証はありません。')
    return {'enabled':m['enabled'],'samples':samples,'layout':layout,'comparisons':comparisons,
            'minimum_height':minimum_gap(hub,casing),'warnings':warnings,'scope':'geometry_and_reference_area_comparison'}
