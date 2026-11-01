"""Simple cylindrical radial-equilibrium station analysis; not a throughflow CFD.

NASA SP-290 vol.1, chapter 3 radial equilibrium / vortex velocity diagrams.
Uniform entropy on each axial station, power-law absolute swirl, zero radial
velocity. Rotor total enthalpy variation follows the cylindrical Euler work.
Streamtube energy consistency is checked separately, rather than assumed.
"""
import math

SOURCE='https://ntrs.nasa.gov/citations/19720019035'


def defaults():
    return {'enabled':False,'exponent':-1.,'points':33,'flow_mode':'match_mass',
            'design_incidence':0.,'design_deviation':0.}


def validate_settings(settings):
    if not isinstance(settings,dict) or type(settings.get('enabled')) is not bool:
        raise ValueError('半径方向解析の設定が不正です。')
    if type(settings.get('points')) is not int or settings['points'] not in (17,33,65,129):
        raise ValueError('半径方向の点数は17/33/65/129です。')
    if settings.get('flow_mode') not in ('match_mass','meanline_anchor'):
        raise ValueError('半径方向の流量境界条件が不正です。')
    for key,lo,hi in [('exponent',-1,1),('design_incidence',-15,15),('design_deviation',-15,15)]:
        v=settings.get(key)
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'半径方向解析の {key} が範囲外です。')


def simpson(values,spacing):
    if len(values)<3 or len(values)%2!=1:raise ValueError('Simpson積分には奇数個の点が必要です。')
    return spacing/3*(values[0]+values[-1]+4*sum(values[1:-1:2])+2*sum(values[2:-1:2]))


def gradient(values,spacing):
    return [(3*(values[1]-values[0])-(values[2]-values[1]))/(2*spacing)]+[(b-a)/(2*spacing) for a,b in zip(values,values[2:])]+[(3*(values[-1]-values[-2])-(values[-2]-values[-3]))/(2*spacing)]


def linear_interpolate(points,key,x,xkey='radius'):
    if x<=points[0][xkey]:return points[0][key]
    if x>=points[-1][xkey]:return points[-1][key]
    for a,b in zip(points,points[1:]):
        if a[xkey]<=x<=b[xkey]:
            w=(x-a[xkey])/(b[xkey]-a[xkey])
            return a[key]*(1-w)+b[key]*w
    raise ValueError('補間位置が範囲外です。')


def cumulative_mass(points,spacing):
    # Monotone trapezoidal CDF for streamline mapping, independent of Simpson total.
    flux=[2*math.pi*p['radius']*p['density']*p['axial_velocity'] for p in points]
    values=[0.]
    for a,b in zip(flux,flux[1:]):values.append(values[-1]+(a+b)*spacing/2)
    return [v/values[-1] for v in values]


def station_solution(source,conditions,geometry,settings):
    cp,g=conditions['cp'],conditions['gamma'];rg=cp*(g-1)/g
    hub,tip=geometry['hub_radius'],geometry['tip_radius'];rm=conditions['mean_radius']
    n=settings['exponent'];count=settings['points'];dr=(tip-hub)/(count-1)
    omega=conditions['rpm']*2*math.pi/60
    tt_m,pt_m,ct_m=source['t0'],source['p0'],source['ct_mean']
    work=source['cumulative_work']

    def geometry_at(r):
        logx=math.log(r/rm)
        ct=ct_m*math.exp(n*logx)
        dh=-work*math.expm1((n+1)*logx)
        tt=tt_m+dh/cp
        if tt<=0:raise ValueError('半径方向の全温が0 K以下です。旋回則・負荷・半径範囲を見直してください。')
        swirl_shift=-2*ct_m**2*logx if n==0 else -(n+1)/n*ct_m**2*math.expm1(2*n*logx)
        return ct,tt,2*dh+swirl_shift

    radii=[hub+i*dr for i in range(count)]
    geometry_values=[geometry_at(r) for r in radii]
    dense_r=[hub+(tip-hub)*i/256 for i in range(257)]
    dense=[geometry_at(r) for r in dense_r]
    lower=max(0.,max(-shift for ct,tt,shift in dense))
    limits=[]
    for r,(ct,tt,shift) in zip(dense_r,dense):
        limits.append(2*g*rg*tt/(g+1)-ct*ct-shift)
        if source['rotor_frame']:
            limits.append(2/(g+1)*(g*rg*tt-(ct-omega*r)**2-(g-1)/2*ct*ct)-shift)
    upper=min(limits)
    if upper<=lower+1e-8:raise ValueError('全スパンで正の軸流速度かつ亜音速となる解の範囲がありません。')

    def evaluate(ca_squared,positions,values):
        out=[]
        for r,(ct,tt,shift) in zip(positions,values):
            ca2=ca_squared+shift
            if ca2<=0:raise ValueError('軸流速度二乗が0以下です。逆流領域は本モデルでは扱いません。')
            ca=math.sqrt(ca2);ts=tt-(ca2+ct*ct)/(2*cp)
            if ts<=0:raise ValueError('半径方向の静温が0 K以下です。')
            pt=pt_m*(tt/tt_m)**(g/(g-1))
            ps=pt_m*(ts/tt_m)**(g/(g-1))
            rho=ps/(rg*ts);sound=math.sqrt(g*rg*ts);u=omega*r
            out.append({'radius':r,'span':(r-hub)/(tip-hub),'blade_speed':u,'axial_velocity':ca,'swirl_velocity':ct,
                        'temperature':ts,'pressure':ps,'total_temperature':tt,'total_pressure':pt,'density':rho,
                        'alpha':math.degrees(math.atan2(ct,ca)),'beta':math.degrees(math.atan2(ct-u,ca)),
                        'mach':math.hypot(ca,ct)/sound,'relative_mach':math.hypot(ca,ct-u)/sound})
        return out

    def mass_at(value):
        points=evaluate(value,radii,geometry_values)
        return simpson([2*math.pi*p['radius']*p['density']*p['axial_velocity'] for p in points],dr)

    lo=lower+max(1e-8,(upper-lower)*1e-12)
    hi=upper-max(1e-8,(upper-lower)*1e-8)
    if hi<=lo:raise ValueError('亜音速解の探索区間が小さすぎます。')
    bracket=[mass_at(lo),mass_at(hi)];target=conditions['mass_flow'];iterations=0
    if settings['flow_mode']=='match_mass':
        if not bracket[0]<=target<=bracket[1]:
            raise ValueError(f'指定流量 {target:.6g} kg/s は亜音速解の範囲 {bracket[0]:.6g}～{bracket[1]:.6g} kg/s 外です。')
        for i in range(90):
            value=(lo+hi)/2;mass=mass_at(value);iterations=i+1
            if abs(mass-target)<=max(1e-9,target*1e-10):break
            if mass<target:lo=value
            else:hi=value
        else:raise ValueError('半径方向の流量合わせが収束しませんでした。')
    else:
        value=conditions['axial_velocity']**2
        if not lower<value<upper:raise ValueError('1Dの軸流速度を固定すると全スパンの亜音速条件を満たせません。')
    points=evaluate(value,radii,geometry_values)
    checks=evaluate(value,dense_r,dense)
    if max(p['mach'] for p in checks)>=1 or source['rotor_frame'] and max(p['relative_mach'] for p in checks)>=1:
        raise ValueError('細分点の確認で音速以上の流れを検出しました。')
    mass=mass_at(value)
    dp=gradient([p['pressure'] for p in points],dr)
    forces=[p['density']*p['swirl_velocity']**2/p['radius'] for p in points]
    residuals=[a-b for a,b in zip(dp,forces)]
    scale=max(1.,max(abs(f) for f in forces))
    fractions=cumulative_mass(points,dr)
    for p,residual,fraction in zip(points,residuals,fractions):
        p.update(radial_pressure_residual=residual,mass_fraction=fraction)
    warnings=[]
    if abs(mass-target)/target>.001:warnings.append('環状流路の流量と指定流量が0.1%以上異なります。')
    reference_ca=math.sqrt(value)
    if abs(reference_ca/conditions['axial_velocity']-1)>.05:
        warnings.append('平均半径の軸流速度が元の1D値と5%以上異なります。1D損失・偏差との再連成は行っていません。')
    if max(abs(v) for v in residuals)/scale>.01:
        warnings.append('圧力平衡の差分残差が正規化値1%を超えています。半径方向の点数を増やして分割依存性を確認してください。')
    return {**source,'points':points,'mass_flow':mass,'target_mass_flow':target,'mass_residual':mass-target,
            'reference_axial_velocity':reference_ca,'mass_iterations':iterations,'subsonic_mass_interval':bracket,
            'pressure_balance_max_Pa_per_m':max(abs(v) for v in residuals),'pressure_balance_relative':max(abs(v) for v in residuals)/scale,
            'max_mach':max(p['mach'] for p in checks),'max_relative_mach':max(p['relative_mach'] for p in checks),
            'validation_points':257,'warnings':warnings}


def station_sources(d,base):
    c=d['conditions'];sources=[]
    entry_angle=d['analysis']['inlet_angle'] if base['analysis_mode']=='row_models' else 0.
    sources.append({'id':'inlet','label':'タービン入口','stage':0,'kind':'inlet','row_id':None,
                    't0':c['inlet_temperature'],'p0':c['inlet_pressure'],
                    'ct_mean':c['axial_velocity']*math.tan(math.radians(entry_angle)),'cumulative_work':0.,'rotor_frame':False})
    cumulative=0.
    for stage,result in zip(d['stages'],base['stages']):
        p0_stator=result['p0_in']
        if base['analysis_mode']=='row_models':
            p0_stator=next(row['frame_total_pressure_out'] for row in base['blade_rows'] if row['row_id']==stage['rows'][0]['id'])
        sources.append({'id':stage['rows'][0]['id'],'row_id':stage['rows'][0]['id'],'label':f'第{result["stage"]}段 静翼出口',
                        'stage':result['stage'],'kind':'stator','t0':result['t0_in'],'p0':p0_stator,
                        'ct_mean':result['ct1'],'cumulative_work':cumulative,'rotor_frame':True})
        cumulative+=result['work']
        sources.append({'id':stage['rows'][1]['id'],'row_id':stage['rows'][1]['id'],'label':f'第{result["stage"]}段 動翼出口',
                        'stage':result['stage'],'kind':'rotor','t0':result['t0_out'],'p0':result['p0_out'],
                        'ct_mean':result['ct2'],'cumulative_work':cumulative,'rotor_frame':True})
    return sources


def analyze(d,base):
    settings=d['radial'];validate_settings(settings)
    report={'status':'computed','model':'simple_cylindrical_radial_equilibrium','source':SOURCE,'settings':settings,
            'stations':[],'stages':[],'warnings':['各断面のエントロピーを半径方向に一定とする簡易径方向平衡です。流線曲率・半径速度・半径方向の損失分布は未評価です。',
                                                '旋回分布は1Dの平均旋回を基準に指定します。翼断面形状から旋回則を予測するものではありません。'],
            'applicability':'within_app_limits'}
    if base.get('applicability')=='outside' or any(max(s['inlet']['mach'],s['inlet']['relative_mach'],s['outlet']['mach'],s['outlet']['relative_mach'])>=1 for s in base['stages']):
        report['warnings'].append('基準の1D計算に適用条件外の状態があります。径方向への展開でその精度が改善されたとは扱いません。')
        report['applicability']='outside'
    try:
        from meridional import reference_cylinder
        if d.get('meridional',{}).get('enabled') and not reference_cylinder(d):
            raise ValueError('可変子午面と半径方向解析の連成は未対応です。基準の円筒流路を使うか、子午面を無効にしてください。')
        for source in station_sources(d,base):
            try:station=station_solution(source,d['conditions'],d['geometry'],settings)
            except ValueError as e:raise ValueError(f'{source["label"]}: {e}') from None
            report['stations'].append(station)
            report['warnings'].extend(f'{source["label"]}: {w}' for w in station['warnings'])
            if station['warnings']:report['applicability']='outside'
        cp=d['conditions']['cp'];omega=d['conditions']['rpm']*2*math.pi/60
        for i,base_stage in enumerate(base['stages']):
            inlet,outlet=report['stations'][1+2*i:3+2*i]
            values=[];tube_errors=[]
            angular_points=[{**p,'angular_momentum':p['radius']*p['swirl_velocity']} for p in inlet['points']]
            for a,b in zip(inlet['points'],outlet['points']):
                work=omega*b['radius']*(a['swirl_velocity']-b['swirl_velocity'])
                thermal=cp*(a['total_temperature']-b['total_temperature'])
                reaction=cp*(a['temperature']-b['temperature'])/work if abs(work)>1e-10 else None
                q=b['mass_fraction'];r_in=linear_interpolate(inlet['points'],'radius',q,'mass_fraction')
                tt_in=linear_interpolate(inlet['points'],'total_temperature',q,'mass_fraction')
                # Interpolate angular momentum directly to preserve a free vortex exactly.
                angular_in=linear_interpolate(angular_points,'angular_momentum',q,'mass_fraction')
                tube_euler=omega*(angular_in-b['radius']*b['swirl_velocity'])
                tube_thermal=cp*(tt_in-b['total_temperature'])
                tube_error=tube_thermal-tube_euler;tube_errors.append(tube_error)
                values.append({'radius':b['radius'],'span':b['span'],'reaction':reaction,'work':work,
                               'loading_coefficient':work/b['blade_speed']**2,'euler_residual':thermal-work,
                               'streamtube_energy_residual':tube_error,'streamtube_inlet_radius':r_in})
            dr=(d['geometry']['tip_radius']-d['geometry']['hub_radius'])/(settings['points']-1)
            power=simpson([2*math.pi*b['radius']*b['density']*b['axial_velocity']*v['work'] for b,v in zip(outlet['points'],values)],dr)
            tube_relative=max(abs(v) for v in tube_errors)/max(abs(base_stage['work']),1.)
            if tube_relative>.001:
                report['warnings'].append(f'第{i+1}段: 質量流管に沿うエネルギー整合誤差が0.1%超です。非自由渦の分布は比較用として扱ってください。')
                report['applicability']='outside'
            if any(v['reaction'] is None or not 0<=v['reaction']<=1 for v in values):
                report['warnings'].append(f'第{i+1}段: スパン内に反動度0～1外または評価不能の位置があります。');report['applicability']='outside'
            report['stages'].append({'stage':i+1,'stage_id':base_stage['stage_id'],'points':values,
                                     'mass_weighted_power':power,'source_1d_power':d['conditions']['mass_flow']*base_stage['work'],
                                     'max_streamtube_energy_residual':max(abs(v) for v in tube_errors),
                                     'streamtube_energy_relative':tube_relative})
    except (ValueError,OverflowError,ZeroDivisionError) as e:
        report.update(status='failed',applicability='outside',error=str(e))
    return report


def angle_candidates(d,report,stage_index,row_index):
    if report.get('status')!='computed':return []
    # Station sequence: turbine inlet, stator exit, rotor exit, ...
    row=d['stages'][stage_index]['rows'][row_index]
    before=report['stations'][2*stage_index+row_index]
    after=report['stations'][2*stage_index+row_index+1]
    key='alpha' if row_index==0 else 'beta'
    out=[]
    for section in row['sections']:
        radius=d['geometry']['hub_radius']+section['span']*(d['geometry']['tip_radius']-d['geometry']['hub_radius'])
        incoming=linear_interpolate(before['points'],key,radius)
        outgoing=linear_interpolate(after['points'],key,radius)
        inlet=incoming-d['radial']['design_incidence'];exit_angle=outgoing-d['radial']['design_deviation']
        out.append({'section_id':section['id'],'span':section['span'],'inlet_flow_angle':incoming,'outlet_flow_angle':outgoing,
                    'inlet_metal_candidate':inlet,'outlet_metal_candidate':exit_angle,
                    'within_editor_limits':abs(inlet)<=75 and abs(exit_angle)<=75})
    return out
