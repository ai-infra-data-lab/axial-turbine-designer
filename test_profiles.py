"""Independent numerical and persistence checks for profile editing."""
import copy
import math
import json
import tempfile
import unittest
from pathlib import Path
from core import new_design, validate, geometry, solve, digest
from profiles import (basis, bspline, pchip, resample, convert_section, restore_section,
                      section_profile, interpolate_section, section_metrics, curvature, curve_error, validate_profile)
from store import Store


class CurveMathTests(unittest.TestCase):
    def test_bspline_partition_affine_and_endpoints(self):
        points=[[i*.01,2*i*.01+3] for i in range(17)]
        for u in [0,.01,.13,.5,.99,1]:
            weights=basis(17,u)
            self.assertAlmostEqual(sum(weights),1,places=12)
            self.assertTrue(all(x>=0 for x in weights))
            x,y=bspline(points,u)
            self.assertAlmostEqual(y,2*x+3,places=12)
        self.assertEqual(bspline(points,0),points[0])
        self.assertEqual(bspline(points,1),points[-1])

    def test_pchip_knots_monotonicity_and_no_overshoot(self):
        points=[[0,0],[.2,.8],[.7,.9],[1,1]]
        for x,y in points:self.assertAlmostEqual(pchip(points,x),y)
        ys=[pchip(points,i/100) for i in range(101)]
        self.assertTrue(all(b>=a for a,b in zip(ys,ys[1:])))
        self.assertTrue(all(0<=y<=1 for y in ys))

    def test_circle_curvature_and_resampling(self):
        radius=.2
        points=[[radius*math.cos(i*.01),radius*math.sin(i*.01)] for i in range(101)]
        for k in curvature(points):self.assertAlmostEqual(k,1/radius,places=8)
        line=resample([[0,0],[.1,0],[1,0]],11)
        for i,p in enumerate(line):self.assertAlmostEqual(p[0],i/10)
        self.assertAlmostEqual(curve_error([line,line],[line,line])['max_m'],0)


class ProfileEditingTests(unittest.TestCase):
    def setUp(self):
        self.d=new_design()
        self.s=self.d['stages'][0]['rows'][1]['sections'][0]

    def test_distribution_constant_angle_and_thickness(self):
        s=copy.deepcopy(self.s)
        s['profile']={'mode':'distribution','angles':[[0,20],[.5,20],[1,20]],
                      'thicknesses':[[0,0],[.5,.004],[1,.0005]]}
        validate_profile(s)
        a,b=section_profile(s,101)
        for i in [0,25,50,100]:
            mid=[(x+y)/2 for x,y in zip(a[i],b[i])]
            self.assertAlmostEqual(mid[1]-s['lean'],(mid[0]-s['sweep'])*math.tan(math.radians(20)),places=12)
        self.assertAlmostEqual(math.dist(a[50],b[50]),.004)
        self.assertAlmostEqual(math.dist(a[-1],b[-1]),.0005)
        self.assertAlmostEqual(section_metrics(s)['stagger_deg'],20,places=10)

    def test_conversion_error_and_exact_restore(self):
        distribution,error=convert_section(self.s,'distribution')
        self.assertLess(error['max_m'],.0001)
        direct,error=convert_section(distribution,'direct',25)
        self.assertLess(error['max_m'],.001)
        self.assertEqual(len(direct['profile_history']),2)
        self.assertEqual(direct['profile']['side_a'][0],direct['profile']['side_b'][0])
        self.assertAlmostEqual(section_metrics(direct)['nose_tangent_error_deg'],0,places=6)
        first=restore_section(direct)
        self.assertEqual(first,distribution)
        original=restore_section(first)
        original.pop('profile_history')
        self.assertEqual(original,self.s)

    def test_direct_edit_changes_only_selected_face(self):
        direct,_=convert_section(self.s,'direct')
        before=section_profile(direct)
        direct['profile']['side_a'][8][1]+=.001
        after=section_profile(direct)
        self.assertEqual(before[1],after[1])
        self.assertNotEqual(before[0],after[0])
        self.assertGreater(curve_error(before,after)['max_m'],0)
        with self.assertRaises(ValueError):convert_section(direct,'distribution')

    def test_restore_keeps_current_span_identity(self):
        direct,_=convert_section(self.s,'direct')
        direct['span']=.12
        restored=restore_section(direct)
        self.assertEqual(restored['id'],self.s['id'])
        self.assertEqual(restored['span'],.12)

    def test_mixed_span_loft_has_consistent_surface_correspondence(self):
        a,_=convert_section(self.s,'distribution')
        b,_=convert_section(a,'direct')
        b['span']=1
        middle=interpolate_section([a,b],.5)
        aa=[resample(s,81) for s in section_profile(a,161)]
        bb=[resample(s,81) for s in section_profile(b,161)]
        mm=section_profile(middle)
        for k in (0,1):
            for i in (0,20,50,80):
                for j in (0,1):self.assertAlmostEqual(mm[k][i][j],(aa[k][i][j]+bb[k][i][j])/2)

    def test_invalid_curves_and_archives_rejected(self):
        valid,_=convert_section(self.s,'distribution')
        for mutate in [lambda s:s['profile']['angles'][1].__setitem__(0,0),
                       lambda s:s['profile']['angles'][1].__setitem__(1,90),
                       lambda s:s['profile']['thicknesses'][1].__setitem__(1,-.1),
                       lambda s:s['profile_history'][0]['source'].__setitem__('peak',0)]:
            s=copy.deepcopy(valid);mutate(s)
            with self.assertRaises(ValueError):validate_profile(s)
        direct,_=convert_section(self.s,'direct')
        direct['profile']['side_b'][0][0]+=.001
        with self.assertRaises(ValueError):validate_profile(direct)

    def test_legacy_design_and_advanced_roundtrip(self):
        legacy=copy.deepcopy(self.d)
        legacy['schema_version']=1
        self.assertEqual(validate(legacy),self.d)
        self.d['stages'][0]['rows'][1]['sections'][0],_=convert_section(self.s,'direct')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'profiles.sqlite3')
            store.save(self.d,0,solve(self.d))
            loaded=store.get(self.d['id'])
            self.assertEqual(loaded['design'],self.d)
            self.assertEqual(loaded['result']['input_snapshot'],self.d)
        mesh=geometry(self.d)
        self.assertTrue(all(l['minimum_passage_gap_m']>=0 for l in mesh['layers']))
        self.assertEqual(len(mesh['section_reports']),5)

    def test_passage_gap_for_straight_symmetric_blades(self):
        row=self.d['stages'][0]['rows'][1]
        for s in row['sections']:
            s.update(inlet_angle=0,outlet_angle=0,stagger=0,thickness=.005,sweep=0,lean=0)
        mesh=geometry(self.d)
        for layer in mesh['layers']:
            expected=2*math.pi*layer['radius']/row['blade_count']-.005
            self.assertAlmostEqual(layer['minimum_passage_gap_m'],expected,places=9)

    def test_legacy_load_migrates_without_writing_original(self):
        legacy=copy.deepcopy(self.d)
        legacy['schema_version']=1
        result=solve(self.d)
        result['input_snapshot']=legacy
        result['input_hash']=digest(legacy)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'legacy.sqlite3')
            store.save(self.d,0)
            with store.connect() as db:
                db.execute('UPDATE designs SET document=?,result=? WHERE id=?',
                           (json.dumps(legacy),json.dumps(result),legacy['id']))
            loaded=store.get(legacy['id'])
            self.assertEqual(loaded['design']['schema_version'],3)
            self.assertIsNone(loaded['result'])
            with store.connect() as db:
                original=json.loads(db.execute('SELECT document FROM designs').fetchone()[0])
            self.assertEqual(original,legacy)


if __name__=='__main__':unittest.main(verbosity=2)
