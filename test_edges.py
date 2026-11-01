"""Analytic edge geometry, independent continuity checks, persistence and compatibility."""
import copy
import math
import tempfile
import unittest
from pathlib import Path
import edges
from core import new_design, validate, geometry, obj_text, digest
from profiles import (base_evaluator, section_profile, profile_evaluator, section_metrics,
                      apply_edge_settings, convert_section, restore_section, interpolate_section)
from store import Store


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.d=new_design();self.s=self.d['stages'][0]['rows'][1]['sections'][2]
        self.c={**edges.defaults(self.s),'enabled':True}

    def enabled(self,**changes):
        return apply_edge_settings(self.s,{**self.c,**changes})

    def test_disabled_preserves_all_legacy_coordinates(self):
        reference=section_profile(self.s,161)
        s=apply_edge_settings(self.s,{**self.c,'enabled':False})
        self.assertEqual(section_profile(s,161),reference)
        self.assertIsNone(section_metrics(s)['edge_report'])

    def test_circular_le_radius_and_shared_tips(self):
        s=self.enabled();fn=profile_evaluator(s);base=base_evaluator(self.s)
        le,te=fn(0,0),fn(0,1)
        self.assertLess(math.dist(le,base(0,0)),1e-14)
        self.assertLess(math.dist(le,fn(1,0)),1e-14)
        self.assertLess(math.dist(te,fn(1,1)),1e-14)
        e,n=edges.frame(self.s['inlet_angle']);centre=edges.add(le,edges.scale(e,self.c['le_radius']))
        for side in (0,1):
            for i in range(11):
                p=fn(side,self.c['le_join']*.35*i/10)
                self.assertAlmostEqual(math.dist(p,centre),self.c['le_radius'],places=13)

    def test_elliptical_le_equation_nose_curvature_and_orientation(self):
        s=self.enabled(le_type='ellipse',le_ratio=1.8,le_orientation=11)
        fn=profile_evaluator(s);r=self.c['le_radius'];a=r*1.8**2;b=r*1.8
        e,n=edges.frame(s['inlet_angle']+11);centre=edges.add(fn(0,0),edges.scale(e,a))
        for side in (0,1):
            for i in range(1,10):
                v=edges.sub(fn(side,self.c['le_join']*.35*i/10),centre)
                x=sum(v[j]*e[j] for j in (0,1));y=sum(v[j]*n[j] for j in (0,1))
                self.assertAlmostEqual((x/a)**2+(y/b)**2,1,places=12)
        h=1e-5;p=fn(0,0);q=fn(0,h);z=fn(1,h)
        # Circumcircle through symmetric samples estimates the actual nose curvature.
        cross=abs((q[0]-p[0])*(z[1]-p[1])-(q[1]-p[1])*(z[0]-p[0]))
        radius=math.dist(p,q)*math.dist(q,z)*math.dist(z,p)/(2*cross)
        self.assertAlmostEqual(radius/r,1,places=5)

    def test_te_interface_thickness_and_wedge_for_circle_ellipse_flat(self):
        for kind in ('circle','ellipse','flat'):
            with self.subTest(kind=kind):
                s=self.enabled(te_type=kind,te_ratio=1.7,te_wedge=24)
                fn=profile_evaluator(s);u=1 if kind=='flat' else self.c['te_join']+(1-self.c['te_join'])*.65
                self.assertAlmostEqual(math.dist(fn(0,u),fn(1,u)),self.c['te_thickness'],places=12)
                h=1e-7;v=edges.sub(fn(0,u),fn(0,u-h))
                direction=math.degrees(math.atan2(v[1],v[0]))
                self.assertAlmostEqual(direction,self.s['outlet_angle']-12,delta=.02)
                if kind=='flat':self.assertGreater(math.dist(fn(0,1),fn(1,1)),0)
                else:self.assertLess(math.dist(fn(0,1),fn(1,1)),1e-14)

    def test_g2_connections_and_g1_curvature_jumps_are_independently_measured(self):
        for mode in ('G1','G2'):
            report=section_metrics(self.enabled(continuity=mode))['edge_report']
            self.assertEqual(len(report['connections']),8)
            self.assertLess(max(c['tangent_error_deg'] for c in report['connections']),.002)
            max_jump=max(c['curvature_relative'] for c in report['connections'])
            if mode=='G2':self.assertLess(max_jump,.002)
            else:self.assertGreater(max_jump,.1)

    def test_history_restore_and_persistence(self):
        before=copy.deepcopy(self.s);s=self.enabled();self.assertEqual(self.s,before)
        restored=restore_section(s);restored.pop('profile_history');self.assertEqual(restored,before)
        self.d['stages'][0]['rows'][1]['sections'][2]=s
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'edges.sqlite3');store.save(self.d,0,None)
            self.assertEqual(store.get(self.d['id'])['design'],self.d)

    def test_distribution_and_direct_conversion_do_not_apply_edges_twice(self):
        s=self.enabled()
        distribution,error=convert_section(s,'distribution')
        self.assertTrue(distribution['edges']['enabled'])
        self.assertEqual(len(section_profile(distribution)[0]),81)
        direct,error=convert_section(s,'direct',25)
        self.assertNotIn('edges',direct)
        self.assertGreater(error['max_m'],0)
        self.assertEqual(restore_section(direct)['edges'],s['edges'])
        self.assertLess(math.dist(*[side[-1] for side in section_profile(direct)]),1e-12)

    def test_span_interpolation_matches_edge_settings_or_lofts_mixed_shapes(self):
        a=self.enabled();b=copy.deepcopy(a);a['span']=0;b['span']=1
        b['edges']['le_radius']*=1.2
        mid=interpolate_section([a,b],.5)
        self.assertAlmostEqual(mid['edges']['le_radius'],self.c['le_radius']*1.1)
        self.assertEqual(len(section_profile(mid)),2)
        b['edges']['te_type']='flat'
        mid=interpolate_section([a,b],.5)
        self.assertEqual(mid['profile']['mode'],'_loft');self.assertNotIn('edges',mid)
        self.assertEqual(len(section_profile(mid)[0]),81)

    def test_invalid_geometry_parameters_and_direct_settings_are_rejected(self):
        for key,value in [('le_radius',float('nan')),('le_ratio',True),('te_wedge',61),('le_join',.4),('te_type','sharp'),('enabled',1),('continuity','G3'),('le_radius',.005)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.enabled(**{key:value})
        direct,_=convert_section(self.s,'direct')
        with self.assertRaisesRegex(ValueError,'直接編集'):apply_edge_settings(direct,self.c)
        with self.assertRaises(ValueError):apply_edge_settings(self.s,None)

    def test_geometry_obj_and_schema_migration(self):
        self.d['stages'][0]['rows'][1]['sections'][2]=self.enabled()
        mesh=geometry(self.d)
        report=mesh['section_reports'][2]['edge_report']
        self.assertEqual(report['settings']['continuity'],'G2')
        self.assertTrue(all(len(layer['sides'][0])==81 for layer in mesh['layers']))
        obj=obj_text(self.d);self.assertIn('v ',obj);self.assertIn('f ',obj)
        vertices=[list(map(float,line.split()[1:])) for line in obj.splitlines() if line.startswith('v ')]
        for line in obj.splitlines():
            if line.startswith('f '):
                points=[vertices[int(index)-1] for index in line.split()[1:]]
                self.assertGreaterEqual(len(points),3)
                self.assertTrue(all(math.dist(a,b)>1e-12 for a,b in zip(points,points[1:]+points[:1])))
        old=new_design();old['schema_version']=4
        self.assertEqual(validate(old)['schema_version'],6)
        self.assertNotEqual(digest(old),digest(validate(old)))


if __name__=='__main__':unittest.main(verbosity=2)
