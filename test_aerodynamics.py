import copy
import math
import tempfile
import unittest
from pathlib import Path
from core import new_design, solve, validate, aero_from_shape
from aerodynamics import deviation_angle, soderberg_2016
from store import Store


def example():
    d=new_design();d['analysis']['mode']='row_models'
    for i,stage in enumerate(d['stages']):
        for j,row in enumerate(stage['rows']):
            row['aero']=aero_from_shape(d,i,j)
            row['aero']['throat_ratio']=.4
    return d


class CorrelationTests(unittest.TestCase):
    def test_printed_soderberg_reference_point(self):
        # Direct arithmetic of the adopted 2016 eqs12–14: zeta*=.1, c/H=1, Re=1e5.
        self.assertAlmostEqual(soderberg_2016(100,1,1,1e5,'stator'),.1748,places=12)
        self.assertAlmostEqual(soderberg_2016(100,1,1,1e5,'rotor'),.155,places=12)
        self.assertAlmostEqual(soderberg_2016(100,1,1,16e5,'rotor'),.155/2,places=12)

    def test_am_low_speed_reference_and_signed_angles(self):
        ratio=math.cos(math.radians(60))
        positive=deviation_angle('ainley_mathieson',ratio,.2,1,60)
        self.assertAlmostEqual(positive['angle'],35+45/39*20)
        negative=deviation_angle('ainley_mathieson',ratio,.2,1,-60)
        self.assertAlmostEqual(positive['angle'],-negative['angle'])
        self.assertAlmostEqual(deviation_angle('ainley_mathieson',ratio,.75,1,60)['angle'],(positive['angle']+60)/2)
        self.assertAlmostEqual(deviation_angle('ainley_mathieson',ratio,1,1,60)['angle'],60)

    def test_aungier_increment_and_smooth_limits(self):
        ratio=.5
        tangent_gauge=30.
        increment=math.degrees(math.asin(.5*(1+.5/9)))-30
        low=deviation_angle('aungier',ratio,.2,1,60)['angle']
        self.assertAlmostEqual(low,60-increment)
        self.assertAlmostEqual(deviation_angle('aungier',ratio,.75,1,60)['angle'],60-increment/2)
        for transition in (.5,1.):
            a=deviation_angle('aungier',ratio,transition-1e-7,1,60)['angle']
            b=deviation_angle('aungier',ratio,transition+1e-7,1,60)['angle']
            self.assertAlmostEqual(a,b,places=9)


class RowModelTests(unittest.TestCase):
    def setUp(self):self.d=example()

    def test_row_conservation_entropy_and_convergence(self):
        r=solve(self.d)
        self.assertEqual(len(r['blade_rows']),4)
        for row in r['blade_rows']:
            self.assertGreater(row['Y'],0)
            self.assertGreater(row['entropy_generation'],0)
            self.assertLess(row['frame_total_pressure_out'],row['frame_total_pressure_in'])
            self.assertLess(abs(row['angle_residual_deg']),1e-8)
            self.assertLess(abs(row['frame_total_temperature_residual']),1e-8)
            self.assertGreater(row['pressure_iterations'],0)
        for stage in r['stages']:
            self.assertAlmostEqual(stage['euler_residual'],0,places=7)
            self.assertAlmostEqual(stage['outlet']['mass_residual'],0,places=10)
        self.assertTrue(0<r['summary']['efficiency_tt']<1)
        self.assertAlmostEqual(r['summary']['power'],self.d['conditions']['mass_flow']*sum(s['work'] for s in r['stages']))

    def test_zero_loss_isentropic_limit_and_relative_frame(self):
        for stage in self.d['stages']:
            for row in stage['rows']:row['aero'].update(loss_model='specified_y',specified_y=0)
        r=solve(self.d)
        self.assertAlmostEqual(r['summary']['efficiency_tt'],1,places=12)
        for row in r['blade_rows']:
            self.assertAlmostEqual(row['entropy_generation'],0,places=10)
            self.assertAlmostEqual(row['Y'],0,places=10)
            self.assertEqual(row['frame'],'relative' if row['kind']=='rotor' else 'absolute')

    def test_loss_changes_pressure_not_prescribed_kinematics(self):
        for stage in self.d['stages']:
            for row in stage['rows']:row['aero'].update(loss_model='specified_y',specified_y=.01)
        low=solve(self.d)
        for stage in self.d['stages']:
            for row in stage['rows']:row['aero']['specified_y']=.2
        high=solve(self.d)
        self.assertLess(high['summary']['outlet_pressure'],low['summary']['outlet_pressure'])
        self.assertLess(high['summary']['efficiency_tt'],low['summary']['efficiency_tt'])
        self.assertAlmostEqual(high['summary']['power'],low['summary']['power'])
        for row in high['blade_rows']:self.assertAlmostEqual(row['Y'],.2,places=8)

    def test_deviation_changes_velocity_work_and_ignores_design_constraints(self):
        a=solve(self.d)
        self.d['stages'][0]['rows'][1]['aero'].update(deviation_model='metal_offset',specified_deviation=2)
        b=solve(self.d)
        self.assertNotAlmostEqual(a['summary']['power'],b['summary']['power'])
        self.d['conditions']['stage_efficiency']=.5
        self.d['conditions']['power']=1e7
        self.d['stages'][0]['reaction']=.1
        self.d['stages'][0]['weight']=10
        c=solve(self.d)
        self.assertAlmostEqual(b['summary']['power'],c['summary']['power'])
        self.assertNotEqual(c['summary']['power_difference'],b['summary']['power_difference'])

    def test_shape_binding_invalidation_and_direct_shape_refusal(self):
        self.d['stages'][0]['rows'][0]['sections'][0]['stagger']+=1
        r=solve(self.d)
        self.assertEqual(r['applicability'],'outside')
        self.assertTrue(any('参照形状' in w for w in r['warnings']))
        from profiles import convert_section
        row=self.d['stages'][0]['rows'][0]
        row['sections'][2],_=convert_section(row['sections'][2],'direct')
        with self.assertRaises(ValueError):aero_from_shape(self.d,0,0)

    def test_unset_values_do_not_become_zero(self):
        for key in ('inlet_metal_angle','outlet_metal_angle','throat_ratio','axial_chord'):
            d=copy.deepcopy(self.d);d['stages'][0]['rows'][0]['aero'][key]=None
            with self.subTest(key=key),self.assertRaises(ValueError):solve(d)
        a=self.d['stages'][0]['rows'][0]['aero'];a.update(loss_model='specified_y',specified_y=None)
        with self.assertRaises(ValueError):solve(self.d)

    def test_outside_incidence_and_sonic_rejection(self):
        r=solve(self.d)
        self.assertTrue(any(row['applicability']=='outside' for row in r['blade_rows']))
        self.d['conditions']['axial_velocity']=800
        with self.assertRaises(ValueError):solve(self.d)

    def test_save_reload_keeps_models_and_provenance(self):
        r=solve(self.d)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'aero.sqlite3');store.save(self.d,0,r)
            loaded=store.get(self.d['id'])
        self.assertEqual(loaded['design'],self.d)
        self.assertEqual(loaded['result']['blade_rows'],r['blade_rows'])
        self.assertIn('loss',loaded['result']['sources'])

    def test_validation(self):
        for key,value in [('throat_ratio',1.2),('critical_mach',.5),('specified_y',-1),('outlet_metal_angle',float('nan'))]:
            d=copy.deepcopy(self.d);d['stages'][0]['rows'][0]['aero'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate(d)

    def test_distribution_angles_transfer_at_mean_span_with_roundoff(self):
        from profiles import convert_section
        row=self.d['stages'][0]['rows'][0]
        row['sections'][2],_=convert_section(row['sections'][2],'distribution')
        self.d['conditions']['mean_radius']=.2+1e-15
        result=aero_from_shape(self.d,0,0)
        self.assertAlmostEqual(result['inlet_metal_angle'],row['sections'][2]['profile']['angles'][0][1])
        self.assertIn('distribution',result['source'])


if __name__=='__main__':unittest.main(verbosity=2)
