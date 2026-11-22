"""Meridional geometry, mapping and explicit solver scope checks."""
import copy
import math
import tempfile
import unittest
from pathlib import Path
from core import new_design,validate,geometry,obj_text,solve,digest,set_row_te,meridional_geometry_hash
from profiles import convert_section,restore_section
from meridional import Curve,minimum_gap,report
from store import Store


def variable_design():
    d=new_design();m=d['meridional'];m['enabled']=True
    m['hub'][-1][1]=.18;m['casing'][-1][1]=.27
    return d


class MeridionalTests(unittest.TestCase):
    def test_area_mode_uses_geometry_and_continuity(self):
        from core import new_design, solve
        design = new_design()
        design['meridional']['enabled'] = True
        design['meridional']['casing'][-1][1] += .03
        design['analysis']['meridional_area'] = True
        report = solve(design)
        self.assertEqual(report['analysis_scope'], 'meridional_area_meanline')
        speeds = []
        for row in report['stages']:
            for section in ('inlet','outlet'):
                self.assertLess(abs(row[section]['mass_residual']), 1e-8)
                speeds.append(row[section]['axial_velocity'])
        self.assertNotAlmostEqual(speeds[0],speeds[-1])
        self.assertTrue(all(abs(row['relative_difference']) < 1e-9 for row in report['meridional']['comparisons']))

    def test_straight_curve_derivatives_area_and_height(self):
        curve=Curve([[0,.2],[.4,.24]])
        for x in (0,.1,.2,.4):
            value,slope,second,third=curve.jet(x)
            self.assertAlmostEqual(value,.2+.1*x)
            self.assertAlmostEqual(slope,.1);self.assertAlmostEqual(second,0)
        with self.assertRaises(ValueError):curve.jet(.5)
        d=new_design();sample=report(d)['samples'][30]
        self.assertAlmostEqual(sample['area'],math.pi*(.24**2-.16**2))
        self.assertAlmostEqual(sample['height'],.08)
        self.assertEqual(sample['hub_curvature'],0)

    def test_pchip_interpolation_monotonicity_and_first_derivative(self):
        points=[[0,.16],[.05,.17],[.17,.19],[.25,.195]];curve=Curve(points)
        values=[curve.jet(.25*i/1000)[0] for i in range(1001)]
        self.assertTrue(all(a<=b for a,b in zip(values,values[1:])))
        for x,r in points:self.assertAlmostEqual(curve.jet(x)[0],r)
        for x,_ in points[1:-1]:
            self.assertAlmostEqual(curve.jet(x,left=True)[1],curve.jet(x)[1],places=10)

    def test_interior_crossing_with_positive_control_point_gaps_is_rejected(self):
        d=new_design();m=d['meridional'];xs=[0,.1,.2,.3]
        h=[.11105412503648016,.11186790475578486,.13373405426075285,.14158336835148666]
        c=[.11241101100046795,.11217568942016964,.1338254300704149,.14256979690673313]
        m['hub']=[list(v) for v in zip(xs,h)];m['casing']=[list(v) for v in zip(xs,c)]
        self.assertTrue(all(a<b for a,b in zip(h,c)))
        self.assertLess(minimum_gap(Curve(m['hub']),Curve(m['casing'])),0)
        with self.assertRaisesRegex(ValueError,'交差'):validate(d)

    def test_wall_domain_layout_ids_order_and_bad_values_are_rejected(self):
        for action in ('domain','ids','order','nan','duplicate','crossing'):
            d=variable_design();m=d['meridional'];ids=list(m['placements'])
            if action=='domain':m['placements'][ids[-1]]=10
            if action=='ids':m['placements']['unknown']=m['placements'].pop(ids[-1])
            if action=='order':m['placements'][ids[1]]=m['placements'][ids[0]]
            if action=='nan':m['hub'][0][1]=float('nan')
            if action=='duplicate':m['hub'].insert(1,m['hub'][0].copy())
            if action=='crossing':m['hub'][-1][1]=.3
            with self.subTest(action=action),self.assertRaises(ValueError):validate(d)

    def test_surface_mapping_uses_local_axial_wall_radius_at_every_point(self):
        d=variable_design();g=geometry(d);m=d['meridional'];origin=m['placements'][d['stages'][0]['rows'][1]['id']]
        a,b=m['hub'][0][0],m['hub'][-1][0]
        for layer in g['layers']:
            for local,world in zip(layer['sides'],layer['world_sides']):
                for (x,y),(wx,wy,wz) in zip(local,world):
                    self.assertAlmostEqual(wx,x+origin)
                    w=(wx-a)/(b-a);rh=.16+.02*w;rt=.24+.03*w
                    r=rh+layer['span']*(rt-rh)
                    self.assertAlmostEqual(math.hypot(wy,wz),r,places=12)
                    self.assertAlmostEqual(math.atan2(wy,wz)*r,y,places=12)
        self.assertEqual(g['input_hash'],digest(d));self.assertEqual(g['meridional_hash'],meridional_geometry_hash(d))
        d['stages'][0]['rows'][1]['sections'][0]['chord']+=.001
        self.assertNotEqual(g['meridional_hash'],meridional_geometry_hash(d))

    def test_obj_uses_mapped_surface_coordinates(self):
        d=variable_design();g=geometry(d);obj=obj_text(d)
        points=[list(map(float,line.split()[1:])) for line in obj.splitlines() if line.startswith('v ')]
        expected=g['layers'][0]['world_sides'][0][0]
        for a,b in zip(points[0],expected):self.assertAlmostEqual(a,b,places=9)
        self.assertGreater(points[0][0],0)

    def test_disabled_layout_preserves_cylindrical_geometry_and_1d(self):
        d=new_design();before=geometry(d);base=solve(d)['summary']
        d['meridional']['hub'][-1][1]=.18
        self.assertEqual(geometry(d)['layers'],before['layers'])
        self.assertEqual(solve(d)['summary'],base)
        self.assertNotIn('meridional',solve(d))

    def test_reference_area_comparison_preserves_1d_and_exposes_scope(self):
        d=variable_design();reference=copy.deepcopy(d);reference['meridional']['enabled']=False
        result=solve(d)
        self.assertEqual(result['summary'],solve(reference)['summary'])
        self.assertEqual(result['analysis_scope'],'reference_meanline_only')
        self.assertEqual(len(result['meridional']['comparisons']),4)
        self.assertEqual(result['meridional']['input_hash'],digest(d))
        p=result['meridional']['comparisons'][0]
        self.assertAlmostEqual(p['relative_difference'],p['area']/p['required_area']-1)

    def test_variable_meridional_blocks_radial_but_reference_cylinder_allows_it(self):
        d=variable_design();d['radial']['enabled']=True
        result=solve(d)
        self.assertEqual(result['status'],'computed_1d_radial_failed')
        self.assertIn('未対応',result['radial']['error'])
        d['meridional']['hub'][-1][1]=.16;d['meridional']['casing'][-1][1]=.24
        self.assertEqual(solve(d)['radial']['status'],'computed')

    def test_explicit_te_change_archives_shape_without_modifying_other_rows(self):
        d=variable_design();original=copy.deepcopy(d);p=report(d)['layout'][1]
        updated=set_row_te(d,0,1,p['reference_te']+.003)
        self.assertEqual(d,original)
        self.assertAlmostEqual(report(updated)['layout'][1]['reference_te'],p['reference_te']+.003)
        self.assertEqual(updated['stages'][1],original['stages'][1])
        for section,before in zip(updated['stages'][0]['rows'][1]['sections'],d['stages'][0]['rows'][1]['sections']):
            self.assertEqual(section['thickness'],before['thickness'])
            restored=restore_section(section);restored.pop('profile_history');self.assertEqual(restored,before)

    def test_te_change_rejects_direct_profiles(self):
        d=variable_design();row=d['stages'][0]['rows'][1]
        row['sections'][0],_=convert_section(row['sections'][0],'direct')
        with self.assertRaisesRegex(ValueError,'直接編集'):set_row_te(d,0,1,.11)

    def test_layout_overlap_warning_persistence_and_old_schema_migration(self):
        d=variable_design();ids=list(d['meridional']['placements']);d['meridional']['placements'][ids[1]]=.01
        validate(d);self.assertTrue(any('重なり' in w or '重なります' in w for w in report(d)['warnings']))
        result=solve(d)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'meridional.sqlite3');store.save(d,0,result)
            self.assertEqual(store.get(d['id'])['result']['meridional'],result['meridional'])
        old=new_design();old['schema_version']=5;old.pop('meridional')
        migrated=validate(old)
        self.assertEqual(migrated['schema_version'],6);self.assertFalse(migrated['meridional']['enabled'])
        self.assertNotIn('meridional',old)


if __name__=='__main__':unittest.main(verbosity=2)
