"""Independent preliminary turbine model; SI units, no external dependencies."""
import copy
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from profiles import (section_profile, interpolate_section, validate_profile, section_metrics,
                      point_distance, curve_error, convert_section, restore_section, resample)
from aerodynamics import default_row, validate_settings, solve_rows

VERSION = '0.3.0'
CONVENTIONS = {'units': 'SI (m, s, kg, K, Pa, W)', 'axes': 'x=axial downstream, y=tangential positive rotation, z=radial',
               'angle': 'degrees from +x toward +y; rotor relative / stator absolute',
               'span': 'geometric radial fraction, hub=0 tip=1', 'rotation': '+y',
               'stacking': 'section leading-edge camber point; offsets in x and y'}

def uid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()

def new_design():
    stages = []
    for i in range(2):
        rows = []
        for kind in ('stator', 'rotor'):
            rows.append({'id': uid(), 'kind': kind, 'blade_count': 48 if kind == 'stator' else 56, 'aero':default_row(),
                         'sections': [{'id': uid(), 'span': s, 'chord': .045, 'inlet_angle': 0 if kind == 'stator' else 30,
                                       'outlet_angle': 65 if kind == 'stator' else -60, 'stagger': 32 if kind == 'stator' else -12,
                                       'thickness': .005*(1-.2*s), 'peak': .35, 'trailing': .0006,
                                       'sweep': .004*s, 'lean': .003*s} for s in (0, .25, .5, .75, 1)]})
        stages.append({'id': uid(), 'reaction': .5, 'weight': 1., 'rows': rows})
    return {'schema_version': 3, 'id': uid(), 'name': '軸流タービン試設計（仮の入力例）', 'notes': '', 'link': None,
            'analysis':{'mode':'specified_efficiency','viscosity':4.5e-5,'inlet_angle':0.},
            'conditions': {'mass_flow': 10., 'inlet_temperature': 1400., 'inlet_pressure': 1500000., 'rpm': 15000.,
                           'power': 2000000., 'cp': 1150., 'gamma': 1.33, 'stage_efficiency': .9,
                           'mean_radius': .20, 'axial_velocity': 150.},
            'geometry': {'hub_radius': .16, 'tip_radius': .24}, 'stages': stages}

def number(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f'{name}: {lo}～{hi} の有限値を指定してください。')
    return v

def identifier(v):
    try:
        return str(uuid.UUID(v))
    except (TypeError, ValueError, AttributeError):
        raise ValueError('IDはUUIDで指定してください。') from None

def validate(raw):
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw.get('schema_version') not in (1,2,3):
        raise ValueError('対応していないデータ形式です。')
    d = copy.deepcopy(raw)
    d['schema_version']=3
    d['analysis']={**{'mode':'specified_efficiency','viscosity':4.5e-5,'inlet_angle':0.},**d.get('analysis',{})}
    d['id'] = identifier(d['id'])
    if not isinstance(d['name'], str) or not 1 <= len(d['name'].strip()) <= 150:
        raise ValueError('案件名は1～150文字です。')
    if not isinstance(d.get('notes', ''), str) or len(d.get('notes', '')) > 10000:
        raise ValueError('メモは10000文字以内です。')
    limits = {'mass_flow': (.0001, 100000), 'inlet_temperature': (100, 4000), 'inlet_pressure': (100, 1e9),
              'rpm': (1, 200000), 'power': (1, 1e10), 'cp': (100, 10000), 'gamma': (1.01, 1.8),
              'stage_efficiency': (.1, 1), 'mean_radius': (.001, 20), 'axial_velocity': (1, 2000)}
    for k, bounds in limits.items():
        number(d['conditions'][k], k, *bounds)
    for k in ('hub_radius', 'tip_radius'):
        number(d['geometry'][k], k, .0001, 30)
    if d['geometry']['tip_radius'] <= d['geometry']['hub_radius']:
        raise ValueError('チップ半径はハブ半径より大きくしてください。')
    if not d['geometry']['hub_radius'] <= d['conditions']['mean_radius'] <= d['geometry']['tip_radius']:
        raise ValueError('平均半径をハブとチップの間に指定してください。')
    if not isinstance(d['stages'], list) or not 1 <= len(d['stages']) <= 12:
        raise ValueError('段数は1～12です。')
    seen = {d['id']}
    def unique_id(v):
        identifier(v)
        if v in seen:
            raise ValueError('IDが重複しています。')
        seen.add(v)
    for stage in d['stages']:
        unique_id(stage['id'])
        number(stage['reaction'], '反動度', 0, 1)
        number(stage['weight'], '仕事配分比', .001, 100)
        if len(stage['rows']) != 2 or [r['kind'] for r in stage['rows']] != ['stator', 'rotor']:
            raise ValueError('各段は静翼、動翼の順です。')
        for row in stage['rows']:
            row['aero']={**default_row(),**row.get('aero',{})}
            unique_id(row['id'])
            if type(row['blade_count']) is not int:
                raise ValueError('翼枚数は整数です。')
            number(row['blade_count'], '翼枚数', 3, 500)
            sections = row['sections']
            if not 2 <= len(sections) <= 21:
                raise ValueError('設計断面は2～21枚です。')
            spans = [s['span'] for s in sections]
            if spans[0] != 0 or spans[-1] != 1 or any(b <= a for a, b in zip(spans, spans[1:])):
                raise ValueError('断面は0～1の昇順とし、両端を含めてください。')
            for s in sections:
                unique_id(s['id'])
                for k, lo, hi in [('span', 0, 1), ('chord', .001, 2), ('thickness', .00001, .5),
                                  ('peak', .1, .8), ('trailing', .00001, .1), ('sweep', -2, 2), ('lean', -2, 2),
                                  ('inlet_angle', -75, 75), ('outlet_angle', -75, 75), ('stagger', -70, 70)]:
                    number(s[k], k, lo, hi)
                if s['thickness'] >= s['chord']*.4 or s['trailing'] > s['thickness']:
                    raise ValueError('厚みは軸方向コードの40%未満、後縁厚みは最大厚み以下にしてください。')
                validate_profile(s)
            if row.get('pressure_side', 'unspecified') not in ('unspecified','A','B'):
                raise ValueError('圧力面の想定が不正です。')
    if d.get('link') is not None:
        link = d['link']
        if not isinstance(link, dict):
            raise ValueError('紐付けデータが不正です。')
        for k in ('project_id', 'component_id'):
            identifier(link[k])
        if type(link['source_revision']) is not int or link['source_revision'] < 1:
            raise ValueError('入力元revisionが不正です。')
        if digest(link['source_snapshot']) != link['source_hash']:
            raise ValueError('入力元スナップショットのハッシュが一致しません。')
        project = link['source_snapshot']
        if project['id'] != link['project_id'] or not any(c['id'] == link['component_id'] and c['kind'] == 'turbine' for c in project['components']):
            raise ValueError('紐付け先のタービン部品が一致しません。')
    # Reject non-JSON values anywhere, including notes / source data.
    validate_settings(d)
    digest(d)
    return d

def link_bundle(bundle, component_id):
    if bundle.get('format') != 'gas-turbine-manager' or bundle.get('bundle_version') != 1:
        raise ValueError('設計情報管理のJSON交換ファイルを指定してください。')
    project = bundle['project']
    component = next((c for c in project['components'] if c['id'] == component_id and c['kind'] == 'turbine'), None)
    if component is None:
        raise ValueError('タービン部品を選択してください。')
    return {'project_id': project['id'], 'component_id': component_id, 'project_name': project['name'],
            'component_name': component['name'], 'source_revision': bundle['revision'],
            'source_snapshot': copy.deepcopy(project), 'source_hash': digest(project)}

def orientation(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def crosses(a, b, c, d):
    return orientation(a,b,c)*orientation(a,b,d) < -1e-20 and orientation(c,d,a)*orientation(c,d,b) < -1e-20

def geometry(d, stage_index=0, row_index=1):
    row = d['stages'][stage_index]['rows'][row_index]
    hub, tip = d['geometry']['hub_radius'], d['geometry']['tip_radius']
    layers, warnings = [], []
    spans=sorted(set([j/16 for j in range(17)]+[s['span'] for s in row['sections']]))
    for span in spans:
        s = interpolate_section(row['sections'], span)
        sides = section_profile(s)
        radius = hub+(tip-hub)*span
        layers.append({'span': span, 'radius': radius, 'sides': sides})
        poly = sides[0]+list(reversed(sides[1]))
        # Proper intersection check; excludes the shared leading edge.
        if any(crosses(poly[a], poly[(a+1)%len(poly)], poly[b], poly[(b+1)%len(poly)])
               for a in range(len(poly)) for b in range(a+2, len(poly)) if (a,b) != (0,len(poly)-1)):
            warnings.append(f'{span*100:.0f}%: 翼断面に自己交差があります。')
        pitch = 2*math.pi*radius/row['blade_count']
        edges = list(zip(poly, poly[1:]+poly[:1]))
        # Sampled polygon against one adjacent periodic copy.
        shifted = [[x,y+pitch] for x,y in poly]
        other = list(zip(shifted, shifted[1:]+shifted[:1]))
        if any(crosses(a,b,c,e) for a,b in edges for c,e in other):
            warnings.append(f'{span*100:.0f}%: 隣接翼との交差を検出しました。')
            gap=0.
        else:
            short=sides[0][::2]+list(reversed(sides[1][::2]))
            adj=[[x,y+pitch] for x,y in short]
            gap=min(min(point_distance(p,a,b) for p in short for a,b in zip(adj,adj[1:]+adj[:1])),
                    min(point_distance(p,a,b) for p in adj for a,b in zip(short,short[1:]+short[:1])))
        layers[-1]['minimum_passage_gap_m']=gap
    reports=[section_metrics(s) for s in row['sections']]
    for section,report in zip(row['sections'],reports):
        if section.get('profile',{}).get('mode')=='direct' and report['nose_tangent_error_deg'] is not None and report['nose_tangent_error_deg']>5:
            warnings.append(f"{report['span']*100:.0f}%: 前縁の接線差が5°を超えています（離散評価）。")
    return {'layers': layers, 'warnings': warnings, 'blade_count': row['blade_count'], 'conventions': CONVENTIONS,
            'section_reports':reports,'pressure_side':row.get('pressure_side','unspecified'),
            'notice': '圧力面・負圧面は設計上の想定です。翼間隙間は折線近似の幾何指標で、有効スロートではありません。CAD面の品質保証ではありません。'}

def solve(raw):
    d = validate(raw)
    if d['analysis']['mode']=='row_models':
        results=solve_rows(d)
        for stage in d['stages']:
            for row in stage['rows']:
                binding=row['aero'].get('geometry_binding')
                if binding and binding.get('hash')!=aero_geometry_hash(d,row):
                    results['warnings'].append('形状から転記した翼列入力の参照形状が変更されています。金属角・コードを再確認してください。')
                    results['applicability']='outside'
                    report=next(r for r in results['blade_rows'] if r['row_id']==row['id'])
                    report['applicability']='outside'
                    report['warnings'].append('転記後の参照形状が変更されています。')
        return {'module_id':'axial_turbine_designer','module_version':VERSION,'schema_version':3,
                'run_id':uid(),'started_at':now(),'completed_at':now(),'status':'computed',
                'validation':'not_experimentally_validated','analysis_mode':'row_models',
                'input_snapshot':d,'input_hash':digest(d),'link':d.get('link'),'conventions':CONVENTIONS,**results}
    c = d['conditions']
    cp, g = c['cp'], c['gamma']
    gas_r = cp*(g-1)/g
    u = c['rpm']*2*math.pi/60*c['mean_radius']
    ca, mass = c['axial_velocity'], c['mass_flow']
    total_work = c['power']/mass
    total_weight = sum(s['weight'] for s in d['stages'])
    t0, p0 = c['inlet_temperature'], c['inlet_pressure']
    result, warnings = [], ['指定した段効率・定比熱の非冷却モデルです。実験損失相関・チョーク流量解法は未実装です。',
                             '翼形状は独立した形状案です。形状変更による損失・効率の変化は本計算に反映されません。']
    for i, stage in enumerate(d['stages']):
        dh = total_work*stage['weight']/total_weight
        r = stage['reaction']
        ct1, ct2 = u*(1-r)+dh/(2*u), u*(1-r)-dh/(2*u)
        tin, pin = t0, p0
        factor = 1-dh/(c['stage_efficiency']*cp*tin)
        if factor <= 0:
            raise ValueError(f'第{i+1}段: 要求仕事が過大で出口圧力を計算できません。')
        t0 = tin-dh/cp
        p0 = pin*factor**(g/(g-1))
        def state(tt, pt, ct):
            speed2 = ca*ca+ct*ct
            ts = tt-speed2/(2*cp)
            if ts <= 0:
                raise ValueError(f'第{i+1}段: 静温が0 K以下です。回転数・負荷・軸流速度を見直してください。')
            ps = pt*(ts/tt)**(g/(g-1))
            rho = ps/(gas_r*ts)
            area = mass/(rho*ca)
            height = area/(2*math.pi*c['mean_radius'])
            return {'temperature': ts, 'pressure': ps, 'mach': math.sqrt(speed2/(g*gas_r*ts)),
                    'relative_mach': math.hypot(ca,ct-u)/math.sqrt(g*gas_r*ts), 'area': area, 'height': height,
                    'mass_residual': rho*ca*area-mass}
        a, b = state(tin,pin,ct1), state(t0,p0,ct2)
        for label, state_ in [('動翼入口', a), ('動翼出口', b)]:
            if max(state_['mach'],state_['relative_mach']) >= 1:
                warnings.append(f'第{i+1}段 {label}: Mach数が1以上。チョーク・衝撃波の詳細解析が必要です。')
            if state_['height'] >= 2*c['mean_radius']:
                raise ValueError(f'第{i+1}段: 必要流路高さが直径以上です。平均半径・流量・速度を見直してください。')
        fixed_area = math.pi*(d['geometry']['tip_radius']**2-d['geometry']['hub_radius']**2)
        if abs(fixed_area/b['area']-1) > .05:
            warnings.append(f'第{i+1}段出口: 指定形状の環状面積と流量から求めた必要面積が5%以上異なります。')
        result.append({'stage_id': stage['id'], 'stage': i+1, 'work': dh, 'u': u, 'phi': ca/u, 'psi': dh/u**2,
                       'reaction': r, 'ct1': ct1, 'ct2': ct2,
                       'alpha1': math.degrees(math.atan2(ct1,ca)), 'alpha2': math.degrees(math.atan2(ct2,ca)),
                       'beta1': math.degrees(math.atan2(ct1-u,ca)), 'beta2': math.degrees(math.atan2(ct2-u,ca)),
                       't0_in': tin, 'p0_in': pin, 't0_out': t0, 'p0_out': p0, 'inlet': a, 'outlet': b,
                       'euler_residual': u*(ct1-ct2)-dh, 'energy_residual': cp*(tin-t0)-dh})
    efficiency = total_work/(cp*c['inlet_temperature']*(1-(p0/c['inlet_pressure'])**((g-1)/g)))
    return {'module_id': 'axial_turbine_designer', 'module_version': VERSION, 'schema_version': 3, 'analysis_mode':'specified_efficiency',
            'run_id': uid(), 'started_at': now(), 'completed_at': now(), 'status': 'computed', 'validation': 'not_experimentally_validated',
            'input_snapshot': d, 'input_hash': digest(d), 'link': d.get('link'), 'conventions': CONVENTIONS,
            'summary': {'power': mass*sum(s['work'] for s in result), 'torque': c['power']/(c['rpm']*2*math.pi/60),
                        'pressure_ratio': c['inlet_pressure']/p0, 'efficiency_tt': efficiency, 'outlet_temperature': t0, 'outlet_pressure': p0},
            'stages': result, 'warnings': warnings}


def aero_geometry_hash(d,row):
    return digest({'sections':row['sections'],'blade_count':row['blade_count'],'geometry':d['geometry'],
                   'mean_radius':d['conditions']['mean_radius']})


def aero_from_shape(d,stage_index,row_index):
    row=d['stages'][stage_index]['rows'][row_index]
    hub,tip=d['geometry']['hub_radius'],d['geometry']['tip_radius']
    span=(d['conditions']['mean_radius']-hub)/(tip-hub)
    exact=next((s for s in row['sections'] if abs(s['span']-span)<1e-10),None)
    s=copy.deepcopy(exact) if exact is not None else interpolate_section(row['sections'],span)
    mode=s.get('profile',{}).get('mode','basic')
    if mode not in ('basic','distribution'):
        raise ValueError('平均半径位置の断面が直接編集または座標補間です。1D用の金属角・コードを手動指定してください。')
    a=copy.deepcopy(row['aero'])
    a.update(inlet_metal_angle=s['profile']['angles'][0][1] if mode=='distribution' else s['inlet_angle'],
             outlet_metal_angle=s['profile']['angles'][-1][1] if mode=='distribution' else s['outlet_angle'],
             axial_chord=s['chord'],source=f'形状の幾何スパン {span:.6g} における {mode} 中心線の角度と軸方向コード。スロート面積比は別途指定。',
             geometry_binding={'hash':aero_geometry_hash(d,row),'span':span})
    return a

def obj_text(d, stage_index=0, row_index=1):
    mesh = geometry(d,stage_index,row_index)
    lines = ['# Axial turbine blade; SI metres; x=axial, y/z=annulus Cartesian', '# preliminary geometry, not a manufacturing solid']
    n = len(mesh['layers'][0]['sides'][0])
    width = 2*n
    for layer in mesh['layers']:
        radius = layer['radius']
        for x,y in layer['sides'][0]+list(reversed(layer['sides'][1])):
            theta = y/radius
            lines.append(f'v {x:.10g} {radius*math.sin(theta):.10g} {radius*math.cos(theta):.10g}')
    for j in range(len(mesh['layers'])-1):
        for k in range(width):
            a,b=j*width+k+1,j*width+(k+1)%width+1
            lines.append(f'f {a} {b} {b+width} {a+width}')
    return '\n'.join(lines)+'\n'
