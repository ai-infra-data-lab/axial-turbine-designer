"""Bounded, subsonic blade-row prediction. Constant radius and axial velocity.

Soderberg-type correlation: Bahr Ennil et al. 2016, equations 12–14,
with explicitly selected hydraulic-diameter Reynolds convention. Not full KO.
No third-party source code is incorporated.
"""
import math

SOURCES = {
    'loss': 'https://doi.org/10.1016/j.applthermaleng.2016.03.077',
    'loss_equations': 'Bahr Ennil et al. (2016), equations 1, 6, 12–14; literal stator coefficient 0.075',
    'reynolds_convention': 'Re_Dh = rho V Dh / mu; Dh = 2 opening height / (opening + height); explicit app convention',
    'deviation': 'https://turbo-sim.github.io/turboflow/_modules/turboflow/axial_turbine/deviation_model.html',
    'deviation_note': 'AM low-speed fit / Aungier low-speed increment, interpolated to user-specified critical exit Mach; no choking solver',
}


def default_row():
    return {'loss_model':'soderberg_2016', 'deviation_model':'ainley_mathieson',
            'inlet_metal_angle':None,'outlet_metal_angle':None,'axial_chord':None,
            'throat_ratio':None,'specified_y':None,'specified_deviation':0.,'critical_mach':1.,
            'source':'','geometry_binding':None}


def finite(v,lo,hi):
    return type(v) in (int,float) and math.isfinite(v) and lo<=v<=hi


def validate_settings(d):
    settings=d.get('analysis',{})
    if not isinstance(settings,dict) or settings.get('mode','specified_efficiency') not in ('specified_efficiency','row_models'):
        raise ValueError('1D計算方式が不正です。')
    for key,bounds,default in [('viscosity',(1e-7,.01),4.5e-5),('inlet_angle',(-75,75),0.)]:
        if not finite(settings.get(key,default),*bounds):raise ValueError(f'{key} が範囲外です。')
    for stage in d['stages']:
        for row in stage['rows']:
            a=row.get('aero',{})
            if not isinstance(a,dict):raise ValueError('翼列モデルの設定が不正です。')
            if a.get('loss_model','soderberg_2016') not in ('soderberg_2016','specified_y'):
                raise ValueError('損失モデルが不正です。')
            if a.get('deviation_model','ainley_mathieson') not in ('ainley_mathieson','aungier','metal_offset'):
                raise ValueError('流出角偏差モデルが不正です。')
            for key,lo,hi in [('inlet_metal_angle',-75,75),('outlet_metal_angle',-75,75),('axial_chord',.001,2),
                              ('throat_ratio',.05,.99),('specified_y',0,5),('specified_deviation',-20,20),('critical_mach',.6,1)]:
                v=a.get(key)
                if v is not None and not finite(v,lo,hi):raise ValueError(f'翼列の {key} が範囲外です。')
                if key in ('critical_mach','specified_deviation') and key in a and v is None:raise ValueError(f'{key} を設定してください。')
            binding=a.get('geometry_binding')
            if binding is not None and (not isinstance(binding,dict) or not isinstance(binding.get('hash'),str) or len(binding['hash'])!=64):
                raise ValueError('形状転記の参照ハッシュが不正です。')
            if not isinstance(a.get('source',''),str) or len(a.get('source',''))>2000:raise ValueError('モデル入力の出典は2000文字以内です。')


def deviation_angle(model,ratio,mach,critical,metal,offset=0.):
    """Signed angles measured from axial direction; deviation = flow - metal."""
    if model=='metal_offset':
        return {'angle':metal+offset,'gauge_angle':None,'gauge_deviation':None}
    if ratio is None:raise ValueError('偏差モデルにはスロート面積比を指定してください。')
    gauge=math.degrees(math.acos(ratio))
    if metal==0:raise ValueError('流出角の符号を定めるため、出口金属角を0°以外で指定してください。')
    x=max(0.,min(1.,(mach-.5)/(critical-.5)))
    if model=='ainley_mathieson':
        delta0=gauge-(35.+45./39.*(gauge-40.))
        delta=delta0*(1-x)
    elif model=='aungier':
        tangent_gauge=90-gauge
        argument=ratio*(1+(1-ratio)*(tangent_gauge/90)**2)
        if argument>1:raise ValueError('Aungier偏差式の定義域外です。')
        # The incremental deviation subtracts tangent_gauge. The prose docs omit this term.
        delta0=math.degrees(math.asin(argument))-tangent_gauge
        delta=delta0*(1-10*x**3+15*x**4-6*x**5)
    else:raise ValueError('未対応の偏差モデルです。')
    sign=1 if metal>0 else -1
    return {'angle':sign*(gauge-delta),'gauge_angle':sign*gauge,'gauge_deviation':-sign*delta}


def soderberg_2016(turning,chord,height,reynolds,kind):
    """2016 printed energy-loss fraction referenced to isentropic exit KE."""
    nominal=.04+.06*(turning/100.)**2
    aspect_constant=.993 if kind=='stator' else .975
    value=(1e5/reynolds)**.25*((1+nominal)*(aspect_constant+.075*chord/height)-1)
    if not 0<=value<1:
        raise ValueError('Soderberg型の損失係数が0～1の範囲外です。モデルの適用条件を見直してください。')
    return value


def row_state(tt,pt_in,ca,u,ct_in,a,kind,c,geom):
    cp,g=c['cp'],c['gamma']
    rg=cp*(g-1)/g
    speed_in=math.hypot(ca,ct_in-(u if kind=='rotor' else 0))
    ts_in=tt-(ca*ca+ct_in*ct_in)/(2*cp)
    if ts_in<=0:raise ValueError('翼列入口の静温が0 K以下です。')
    ps_in=pt_in*(ts_in/tt)**(g/(g-1))
    tt_frame=ts_in+speed_in**2/(2*cp)
    pt_frame=ps_in*(tt_frame/ts_in)**(g/(g-1))
    in_angle=math.degrees(math.atan2(ct_in-(u if kind=='rotor' else 0),ca))
    inlet_mach=speed_in/math.sqrt(g*rg*ts_in)
    if inlet_mach>=1:raise ValueError('翼列入口が音速以上です。本モデルは亜音速専用です。')
    metal=a['outlet_metal_angle']
    angle=metal
    angle_iterations=0
    for iteration in range(150):
        speed=ca/math.cos(math.radians(angle))
        ts=tt_frame-speed*speed/(2*cp)
        if ts<=0:raise ValueError('翼列出口の静温が0 K以下です。流出角・回転数・軸流速度を見直してください。')
        mach=speed/math.sqrt(g*rg*ts)
        delta=deviation_angle(a['deviation_model'],a['throat_ratio'],mach,a['critical_mach'],metal,a['specified_deviation'])
        target=delta['angle']
        if abs(target)>=85:raise ValueError('流出角が軸方向から±85°以上です。')
        if abs(target-angle)<1e-9:
            angle_iterations=iteration+1
            break
        angle=.5*(angle+target)
    else:raise ValueError('流出角とMach数の反復が収束しませんでした。')
    if mach>=1:raise ValueError('翼列出口が音速以上です。本モデルは亜音速専用で、チョークは解きません。')
    f=(tt_frame/ts)**(g/(g-1))
    pitch=2*math.pi*c['mean_radius']/geom['blade_count']
    height=geom['height']
    opening=a['throat_ratio']*pitch if a['throat_ratio'] is not None else None
    dhyd=2*opening*height/(opening+height) if opening is not None else None
    turning=abs(in_angle-angle)
    ps=pt_frame/f
    pressure_iterations=0
    loss=0.
    for iteration in range(200):
        rho=ps/(rg*ts)
        reynolds=rho*speed*dhyd/geom['viscosity'] if dhyd is not None else None
        if a['loss_model']=='soderberg_2016':
            if reynolds is None:raise ValueError('Soderberg型モデルにはスロート面積比が必要です。')
            loss=soderberg_2016(turning,a['axial_chord'],height,reynolds,kind)
            # zeta = (h - h_is) / (V_is^2/2); V_is^2 = V^2/(1-zeta).
            t_is=ts-loss/(1-loss)*speed**2/(2*cp)
            if t_is<=0:raise ValueError('損失から求める等エントロピー静温が0 K以下です。')
            target=pt_frame*(t_is/tt_frame)**(g/(g-1))
        else:
            loss=a['specified_y']
            target=pt_frame/(f+loss*(f-1))
        if abs(target-ps)/max(ps,1)<1e-10:
            ps=target;pressure_iterations=iteration+1;break
        ps=.5*(ps+target)
    else:raise ValueError('損失・密度・Reynolds数の反復が収束しませんでした。')
    rho=ps/(rg*ts)
    reynolds=rho*speed*dhyd/geom['viscosity'] if dhyd is not None else None
    pt_frame_out=ps*f
    y=(pt_frame-pt_frame_out)/(pt_frame_out-ps)
    ds=-rg*math.log(pt_frame_out/pt_frame)
    ct_frame=ca*math.tan(math.radians(angle))
    ct=ct_frame+(u if kind=='rotor' else 0)
    tt_out=ts+(ca*ca+ct*ct)/(2*cp)
    pt_out=ps*(tt_out/ts)**(g/(g-1))
    area=c['mass_flow']/(rho*ca)
    warnings=[]
    incidence=in_angle-a['inlet_metal_angle']
    if abs(incidence)>5:warnings.append('入射角が±5°を超えます。入射損失の補正は未実装で、設計点近似の適用範囲外です。')
    if a['loss_model']=='soderberg_2016':
        if turning>120:warnings.append('転向角が120°を超えます。Soderberg型の想定範囲外です。')
        if reynolds<1e4 or reynolds>1e7:warnings.append('Re_Dhが本アプリの確認範囲1e4～1e7外です。')
        if mach>.8:warnings.append('出口Mach数が0.8を超えます。圧縮性・衝撃波損失を含まない簡易相関の範囲外です。')
    gauge_abs=math.degrees(math.acos(a['throat_ratio'])) if a['throat_ratio'] is not None else None
    if a['deviation_model']=='ainley_mathieson' and not 40<=gauge_abs<=70:
        warnings.append('AM偏差のゲージ角が本アプリの使用範囲40～70°外です。')
    if a['deviation_model']!='metal_offset' and mach>=a['critical_mach']:
        warnings.append('指定した臨界参照Mach数に達しています。チョーク流量・超音速流れは未評価です。')
    state={'temperature':ts,'pressure':ps,'mach':math.hypot(ca,ct)/math.sqrt(g*rg*ts),
           'relative_mach':math.hypot(ca,ct-u)/math.sqrt(g*rg*ts),'area':area,
           'height':area/(2*math.pi*c['mean_radius']),'mass_residual':rho*ca*area-c['mass_flow']}
    report={'kind':kind,'frame':'relative' if kind=='rotor' else 'absolute','inlet_angle':in_angle,
            'metal_in':a['inlet_metal_angle'],'metal_out':metal,'flow_out':angle,'incidence':incidence,
            'deviation':angle-metal,'gauge_angle':delta['gauge_angle'],'gauge_deviation':delta['gauge_deviation'],
            'loss_model':a['loss_model'],'deviation_model':a['deviation_model'],'loss_coefficient':loss,
            'loss_definition':'zeta_ideal_exit_kinetic_energy' if a['loss_model']=='soderberg_2016' else 'Y=(pt_in-pt_out)/(pt_out-p_out)',
            'Y':y,'reynolds_Dh':reynolds,'hydraulic_diameter':dhyd,'frame_mach_out':mach,'frame_mach_in':inlet_mach,
            'frame_total_pressure_in':pt_frame,'frame_total_pressure_out':pt_frame_out,
            'entropy_generation':ds,'frame_total_temperature_residual':ts+speed*speed/(2*cp)-tt_frame,
            'angle_residual_deg':angle-delta['angle'],
            'angle_iterations':angle_iterations,'pressure_iterations':pressure_iterations,
            'source':a['source'],'warnings':warnings,'applicability':'outside' if warnings else 'within_app_limits'}
    return {'tt':tt_out,'pt':pt_out,'ct':ct,'state':state,'report':report}


def solve_rows(d):
    c=d['conditions'];analysis=d['analysis'];cp,g=c['cp'],c['gamma'];rg=cp*(g-1)/g
    ca=c['axial_velocity'];u=c['rpm']*2*math.pi/60*c['mean_radius']
    tt,pt=c['inlet_temperature'],c['inlet_pressure']
    ct=ca*math.tan(math.radians(analysis['inlet_angle']))
    height=d['geometry']['tip_radius']-d['geometry']['hub_radius']
    rows=[];stages=[];outside=False;warnings=['非冷却・定比熱・一定平均径／軸流速度の亜音速モデルです。チョーク、入射損失、翼端漏れ、冷却損失は未実装です。',
                               'Soderberg型はコード・翼高さ・転向・Reからの集約損失です。翼面曲率・厚み・後縁・隙間ごとの損失は未評価です。',
                               '流量から必要面積を逆算します。固定流路の流量・背圧を同時に解く性能解析ではありません。']
    for i,stage in enumerate(d['stages']):
        stage_tt,stage_pt=tt,pt
        sr=[]
        for row in stage['rows']:
            a={**default_row(),**row.get('aero',{})}
            for key in ('inlet_metal_angle','outlet_metal_angle'):
                if a[key] is None:raise ValueError(f'第{i+1}段 {row["kind"]}: {key} を入力してください。')
            if a['loss_model']=='soderberg_2016' and (a['axial_chord'] is None or a['throat_ratio'] is None):
                raise ValueError(f'第{i+1}段 {row["kind"]}: コードとスロート面積比を入力してください。')
            if a['loss_model']=='specified_y' and a['specified_y'] is None:raise ValueError('指定Yを入力してください。未設定は0に置き換えません。')
            out=row_state(tt,pt,ca,u,ct,a,row['kind'],c,{'blade_count':row['blade_count'],'height':height,'viscosity':analysis['viscosity']})
            report={**out['report'],'stage':i+1,'row_id':row['id']}
            rows.append(report);sr.append(out)
            warnings.extend(f'第{i+1}段 {row["kind"]}: {w}' for w in report['warnings'])
            tt,pt,ct=out['tt'],out['pt'],out['ct']
        stator,rotor=sr
        dh=cp*(stage_tt-tt)
        if dh<=0:raise ValueError(f'第{i+1}段の仕事が正になりません。流出角・回転数を見直してください。')
        a,b=stator['state'],rotor['state']
        if b['height']>=2*c['mean_radius']:raise ValueError('必要翼高さが平均直径以上です。')
        reaction=cp*(a['temperature']-b['temperature'])/dh
        if not 0<=reaction<=1:
            warnings.append(f'第{i+1}段: 計算反動度が0～1外です。');outside=True
        area_geom=math.pi*(d['geometry']['tip_radius']**2-d['geometry']['hub_radius']**2)
        if abs(area_geom/b['area']-1)>.05:
            warnings.append(f'第{i+1}段: 必要出口面積と指定形状の面積が5%以上異なります。');outside=True
        stages.append({'stage_id':stage['id'],'stage':i+1,'work':dh,'u':u,'phi':ca/u,'psi':dh/u**2,'reaction':reaction,
                       'ct1':stator['ct'],'ct2':rotor['ct'],'alpha1':math.degrees(math.atan2(stator['ct'],ca)),
                       'alpha2':math.degrees(math.atan2(rotor['ct'],ca)),'beta1':math.degrees(math.atan2(stator['ct']-u,ca)),
                       'beta2':rotor['report']['flow_out'],'t0_in':stage_tt,'p0_in':stage_pt,'t0_out':tt,'p0_out':pt,
                       'inlet':a,'outlet':b,'euler_residual':u*(stator['ct']-rotor['ct'])-dh,
                       'energy_residual':cp*(stage_tt-tt)-u*(stator['ct']-rotor['ct']),
                       'efficiency_tt':dh/(cp*stage_tt*(1-(pt/stage_pt)**((g-1)/g)))})
    work=cp*(c['inlet_temperature']-tt)
    if pt>=c['inlet_pressure']:raise ValueError('全体の出口全圧が入口全圧以上です。')
    power=c['mass_flow']*work
    return {'summary':{'power':power,'torque':power/(c['rpm']*2*math.pi/60),
                       'pressure_ratio':c['inlet_pressure']/pt,'efficiency_tt':work/(cp*c['inlet_temperature']*(1-(pt/c['inlet_pressure'])**((g-1)/g))),
                       'outlet_temperature':tt,'outlet_pressure':pt,'target_power':c['power'],'power_difference':power-c['power']},
            'stages':stages,'blade_rows':rows,'warnings':warnings,'sources':SOURCES,
            'applicability':'outside' if outside or any(r['applicability']=='outside' for r in rows) else 'within_app_limits'}
