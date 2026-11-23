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
        hub, casing = meridional.curves(design)
        for row in report['meridional']['layout']:
            index = row['stage']
            stage = report['stages'][index-1]
            role = 'ROT' if row['kind']=='rotor' else 'NGV'
            for suffix, coordinate, state in (('LE','reference_le',stage['inlet']),
                                              ('TE','reference_te',stage['outlet'])):
                x = row[coordinate]
                flow = None
                if role == 'NGV':
                    # This meanline model assigns the stage's total-pressure drop
                    # to the rotor. Across the stator only the velocity changes.
                    stator_area = math.pi * (casing.jet(x)[0]**2 - hub.jet(x)[0]**2)
                    tangential = (report['stages'][index-2]['ct2'] if index > 1 else 0.) if suffix == 'LE' else stage['ct1']
                    stator_tt, stator_pt = stage['t0_in'], stage['p0_in']
                    try:
                        axial = subsonic_axial_velocity(cond['mass_flow'], stator_area, stator_tt, stator_pt,
                                                         tangential, cond['cp'], cond['gamma'])
                    except ValueError:
                        pass  # Keep the geometry station available without a valid subsonic state.
                    else:
                        ts = stator_tt - (axial**2 + tangential**2)/(2 * cond['cp'])
                        flow = {'pressure':stator_pt * (ts / stator_tt)**(cond['gamma']/(cond['gamma']-1)),
                                'temperature':ts, 'total_pressure_pa':stator_pt, 'total_temperature_k':stator_tt,
                                'area':stator_area, 'axial_velocity':axial, 'tangential_velocity':tangential,
                                'mass_flow_kg_s':cond['mass_flow']}
                stations[f'TB-{index:02d}-{role}-{suffix}'] = {
                    'x_m':x, 'flow':flow}
                if role == 'ROT':
                    stations[f'TB-{index:02d}-{role}-{suffix}']['flow'] = {
                        **state, 'total_temperature_k':stage['t0_in' if suffix=='LE' else 't0_out'],
                        'total_pressure_pa':stage['p0_in' if suffix=='LE' else 'p0_out'],
                        'mass_flow_kg_s':cond['mass_flow']}
        stations['TB-EXD-IN'] = {'flow':{'pressure':outlet['pressure'], 'total_pressure_pa':last['p0_out'],
                                        'total_temperature_k':tt, 'area':outlet['area']}}
        stations['TB-OUT'] = stations['TB-EXD-IN']
        stations['TB-EXD-OUT'] = {'flow':{'pressure':ps, 'total_pressure_pa':pt,'total_temperature_k':tt,
                                         'area':area,'axial_velocity':ca}}
        cases[name] = {'design':design,'analysis':report,'stations':stations,
                       'diffuser_static_recovery_pa':ps-outlet['pressure'],
                       'exhaust_diffuser':{'inlet_area_m2':outlet['area'],'outlet_area_m2':area,
                                           'total_pressure_loss_pa':last['p0_out']-pt,
                                           'inlet_static_pressure_pa':outlet['pressure'],
                                           'outlet_static_pressure_pa':ps}}
    if not cases:
        raise ValueError('比較する仕事配分案を指定してください。')
    return {'format':'axial-turbine-cycle-handoff','schema_version':1,'source_cycle':source,'cases':cases}
