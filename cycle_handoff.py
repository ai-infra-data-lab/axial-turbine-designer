"""Create editable turbine designs and compare design-point stage work allocations."""
import copy
import math

import meridional
from core import new_design, number, solve, subsonic_axial_velocity, uid


def evaluate(case, setup):
    inputs = case['input']
    result = case['result']
    inlet = result['stations'][3]
    source = {'run_id':case['run_id'], 'input_hash':case['input_hash'], 'context':inputs['context']}
    cases = {}
    for name, weights in setup['allocations'].items():
        if not isinstance(weights, list) or not 1 <= len(weights) <= 12:
            raise ValueError('仕事配分の要素数は1〜12段です。')
        design = new_design()
        design.update(name=name, cycle_source=source)
        row_template = design['stages'][0]
        design['stages'] = []
        for weight in weights:
            stage = copy.deepcopy(row_template)
            stage.update(id=uid(), weight=weight)
            for row in stage['rows']:
                row['id'] = uid()
                for section in row['sections']:
                    section['id'] = uid()
            design['stages'].append(stage)
        design['conditions'].update(
            mass_flow=inlet['mass_flow_kg_s'], inlet_temperature=inlet['total_temperature_k'],
            inlet_pressure=inlet['total_pressure_pa'], rpm=inputs['parameters']['shaft_speed_rpm'],
            power=result['metrics']['turbine_gas_power_w'], cp=inlet['cp_j_kg_k'], gamma=inlet['gamma'],
            stage_efficiency=inputs['parameters']['turbine_efficiency'],
        )
        design['geometry'] = {key: setup[key] for key in ('hub_radius','tip_radius')}
        design['conditions']['mean_radius'] = (setup['hub_radius']+setup['tip_radius'])/2
        design['meridional'] = meridional.defaults(design)
        mer = design['meridional']
        mer['enabled'] = True
        mer['casing'][-1][1] = setup['turbine_exit_tip_radius']
        design['analysis']['meridional_area'] = True
        report = solve(design)
        last = report['stages'][-1]
        outlet = last['outlet']
        cond = design['conditions']
        diffuser = setup['exhaust_diffuser']
        ratio = number(diffuser['pressure_retention'], '排気ディフューザー全圧残存比', .001, 1.)
        area_ratio = number(diffuser['area_ratio'], '排気ディフューザー面積比', 1., 20.)
        pt = last['p0_out']*ratio
        tt = last['t0_out']
        area = outlet['area']*area_ratio
        # Similar annular expansion with conservation of mean angular momentum.
        ct = last['ct2']/math.sqrt(area_ratio)
        ca = subsonic_axial_velocity(cond['mass_flow'], area, tt, pt, ct, cond['cp'], cond['gamma'])
        static_temp = tt-(ca**2+ct**2)/(2*cond['cp'])
        ps = pt*(static_temp/tt)**(cond['gamma']/(cond['gamma']-1))
        stations = {'TB-IN':{'flow':{'total_pressure_pa':inlet['total_pressure_pa'],
                                     'total_temperature_k':inlet['total_temperature_k'],
                                     'mass_flow_kg_s':inlet['mass_flow_kg_s']}}}
        for row in report['meridional']['layout']:
            index = row['stage']
            stage = report['stages'][index-1]
            role = 'ROT' if row['kind']=='rotor' else 'NGV'
            for suffix, coordinate, state in (('LE','reference_le',stage['inlet']),
                                              ('TE','reference_te',stage['outlet'])):
                stations[f'TB-{index:02d}-{role}-{suffix}'] = {
                    'x_m':row[coordinate], 'flow':state if role=='ROT' else None}
                if role == 'ROT':
                    stations[f'TB-{index:02d}-{role}-{suffix}']['flow'] = {
                        **state, 'total_temperature_k':stage['t0_in' if suffix=='LE' else 't0_out'],
                        'total_pressure_pa':stage['p0_in' if suffix=='LE' else 'p0_out']}
        stations['TB-EXD-IN'] = {'flow':{'pressure':outlet['pressure'], 'total_pressure_pa':last['p0_out'],
                                        'total_temperature_k':tt, 'area':outlet['area']}}
        stations['TB-OUT'] = stations['TB-EXD-IN']
        stations['TB-EXD-OUT'] = {'flow':{'pressure':ps, 'total_pressure_pa':pt,'total_temperature_k':tt,
                                         'area':area,'axial_velocity':ca}}
        cases[name] = {'design':design,'analysis':report,'stations':stations,
                       'diffuser_static_recovery_pa':ps-outlet['pressure']}
    if not cases:
        raise ValueError('比較する仕事配分案を指定してください。')
    return {'format':'axial-turbine-cycle-handoff','schema_version':1,'source_cycle':source,'cases':cases}
