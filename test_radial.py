import copy
import math
import tempfile
import unittest
from pathlib import Path
from core import new_design, solve, solve_meanline, validate, digest, aero_from_shape
from radial import station_solution, station_sources, angle_candidates
from store import Store


def example():
    d=new_design();d['radial']['enabled']=True
    return d


class StationTests(unittest.TestCase):
    def setUp(self):
        self.d=example()
        self.base=solve_meanline(self.d)
        self.source=station_sources(self.d,self.base)[1]

    def test_uniform_zero_swirl_known_mass_velocity(self):
        d=self.d;c=d['conditions'];cp,g=c['cp'],c['gamma'];rg=cp*(g-1)/g
        ca=150.;tt=c['inlet_temperature'];pt=c['inlet_pressure'];ts=tt-ca**2/(2*cp)
        ps=pt*(ts/tt)**(g/(g-1));rho=ps/(rg*ts)
        area=math.pi*(d['geometry']['tip_radius']**2-d['geometry']['hub_radius']**2)
        c['mass_flow']=area*rho*ca
        source=station_sources(d,self.base)[0]
        result=station_solution(source,c,d['geometry'],d['radial'])
        self.assertAlmostEqual(result['reference_axial_velocity'],ca,places=7)
        self.assertAlmostEqual(result['mass_flow'],c['mass_flow'],places=7)
        for p in result['points']:
            self.assertAlmostEqual(p['pressure'],ps,places=5)
            self.assertEqual(p['swirl_velocity'],0)

    def test_free_vortex_angular_momentum_axial_velocity_entropy(self):
        r=station_solution(self.source,self.d['conditions'],self.d['geometry'],self.d['radial'])
        c=self.d['conditions'];rg=c['cp']*(c['gamma']-1)/c['gamma']
        for p in r['points']:
            self.assertAlmostEqual(p['radius']*p['swirl_velocity'],c['mean_radius']*self.source['ct_mean'],places=10)
            self.assertAlmostEqual(p['axial_velocity'],r['reference_axial_velocity'],places=10)
            entropy=c['cp']*math.log(p['total_temperature']/self.source['t0'])-rg*math.log(p['total_pressure']/self.source['p0'])
            self.assertAlmostEqual(entropy,0,places=10)
        self.assertLess(abs(r['mass_residual']),1e-8)
        self.assertLess(r['pressure_balance_relative'],.001)

    def test_grid_dependence_of_pressure_balance_and_mass_solution(self):
        results=[]
        for n in (17,33,65,129):
            settings={**self.d['radial'],'points':n}
            results.append(station_solution(self.source,self.d['conditions'],self.d['geometry'],settings))
        errors=[r['pressure_balance_relative'] for r in results]
        self.assertTrue(all(b<a/3 for a,b in zip(errors,errors[1:])),errors)
        ca=[r['reference_axial_velocity'] for r in results]
        self.assertLess(abs(ca[2]-ca[3]),abs(ca[0]-ca[1])/10)

    def test_constant_swirl_logarithmic_case(self):
        source={**self.source,'ct_mean':40.,'cumulative_work':0.}
        settings={**self.d['radial'],'exponent':0.,'flow_mode':'meanline_anchor'}
        r=station_solution(source,self.d['conditions'],self.d['geometry'],settings)
        for p in r['points']:
            expected=self.d['conditions']['axial_velocity']**2-2*40**2*math.log(p['radius']/self.d['conditions']['mean_radius'])
            self.assertAlmostEqual(p['axial_velocity']**2,expected,places=8)
            self.assertEqual(p['swirl_velocity'],40.)

    def test_exponent_near_zero_is_stable(self):
        source={**self.source,'ct_mean':40.,'cumulative_work':1000.}
        settings={**self.d['radial'],'exponent':0.,'flow_mode':'meanline_anchor'}
        a=station_solution(source,self.d['conditions'],self.d['geometry'],settings)
        b=station_solution(source,self.d['conditions'],self.d['geometry'],{**settings,'exponent':1e-12})
        for pa,pb in zip(a['points'],b['points']):self.assertAlmostEqual(pa['axial_velocity'],pb['axial_velocity'],places=7)

    def test_mass_outside_subsonic_branch_is_rejected(self):
        c={**self.d['conditions'],'mass_flow':1e5}
        with self.assertRaisesRegex(ValueError,'亜音速解の範囲'):
            station_solution(self.source,c,self.d['geometry'],self.d['radial'])


class RadialIntegrationTests(unittest.TestCase):
    def setUp(self):self.d=example()

    def test_all_planes_mass_euler_and_free_vortex_stage_power(self):
        result=solve(self.d);report=result['radial']
        self.assertEqual(report['status'],'computed')
        self.assertEqual(len(report['stations']),5)
        for s in report['stations']:
            self.assertLess(abs(s['mass_residual']),1e-8)
            self.assertEqual(s['points'][0]['mass_fraction'],0)
            self.assertEqual(s['points'][-1]['mass_fraction'],1)
        for stage,mean in zip(report['stages'],result['stages']):
            self.assertAlmostEqual(stage['mass_weighted_power'],mean['work']*self.d['conditions']['mass_flow'],places=3)
            self.assertLess(stage['streamtube_energy_relative'],1e-9)
            for p in stage['points']:
                self.assertAlmostEqual(p['work'],mean['work'],places=7)
                self.assertLess(abs(p['euler_residual']),1e-7)

    def test_nonfree_vortex_streamtube_inconsistency_is_exposed(self):
        self.d['conditions']['power']=100000.
        self.d['geometry'].update(hub_radius=.18,tip_radius=.22)
        self.d['radial'].update(exponent=1.,flow_mode='meanline_anchor')
        result=solve(self.d)['radial']
        self.assertEqual(result['status'],'computed',result.get('error'))
        self.assertEqual(result['applicability'],'outside')
        self.assertTrue(any(s['streamtube_energy_relative']>.001 for s in result['stages']))

    def test_failed_radial_keeps_1d_and_can_be_saved(self):
        self.d['radial']['exponent']=1.
        result=solve(self.d)
        self.assertEqual(result['radial']['status'],'failed')
        self.assertEqual(result['status'],'computed_1d_radial_failed')
        self.assertEqual(result['summary']['power'],2000000)
        self.assertIn('亜音速解の範囲',result['radial']['error'])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'radial.sqlite3');store.save(self.d,0,result)
            self.assertEqual(store.get(self.d['id'])['result']['radial']['status'],'failed')

    def test_disabled_radial_preserves_1d_calculation(self):
        self.d['radial']['enabled']=False
        result=solve(self.d)
        self.assertNotIn('radial',result)
        self.assertEqual(result['summary'],solve_meanline(self.d)['summary'])

    def test_angle_candidates_assumptions_and_no_geometry_mutation(self):
        original=copy.deepcopy(self.d)
        result=solve(self.d)
        first=angle_candidates(self.d,result['radial'],0,1)
        self.d['radial']['design_incidence']=2.;self.d['radial']['design_deviation']=-1.
        second=angle_candidates(self.d,result['radial'],0,1)
        self.assertEqual(len(first),5)
        for a,b in zip(first,second):
            self.assertAlmostEqual(b['inlet_metal_candidate'],a['inlet_metal_candidate']-2)
            self.assertAlmostEqual(b['outlet_metal_candidate'],a['outlet_metal_candidate']+1)
        self.assertEqual(self.d['stages'],original['stages'])

    def test_model_can_use_blade_row_loss_results(self):
        self.d['analysis']['mode']='row_models'
        for i,stage in enumerate(self.d['stages']):
            for j,row in enumerate(stage['rows']):
                row['aero']=aero_from_shape(self.d,i,j);row['aero']['throat_ratio']=.4
        result=solve(self.d)
        self.assertEqual(result['radial']['status'],'computed',result['radial'].get('error'))
        self.assertAlmostEqual(result['radial']['stations'][1]['p0'],result['blade_rows'][0]['frame_total_pressure_out'])

    def test_radial_result_persistence_and_hash(self):
        result=solve(self.d)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'radial.sqlite3');store.save(self.d,0,result)
            loaded=store.get(self.d['id'])
        self.assertEqual(loaded['result']['radial'],result['radial'])
        self.d['radial']['points']=65
        self.assertNotEqual(digest(self.d),result['input_hash'])

    def test_validation_and_old_schema_migration(self):
        for key,value in [('points',32),('exponent',1.2),('exponent',float('nan')),('enabled',1),('flow_mode','other')]:
            d=copy.deepcopy(self.d);d['radial'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate(d)
        old=copy.deepcopy(self.d);old['schema_version']=3;old.pop('radial')
        migrated=validate(old)
        self.assertFalse(migrated['radial']['enabled'])
        self.assertEqual(migrated['schema_version'],4)


if __name__=='__main__':unittest.main(verbosity=2)
