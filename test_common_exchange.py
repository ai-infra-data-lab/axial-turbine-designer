import copy
import math
import unittest
from core import new_design,geometry,digest
from common_exchange import export_geometry
from turbomachinery_common import loads,dumps,source_point,cartesian


class ExchangeTests(unittest.TestCase):
    def test_native_points_roundtrip_and_no_design_mutation(self):
        d=new_design();before=copy.deepcopy(d);mesh=geometry(d);doc=export_geometry(d)
        self.assertEqual(d,before);self.assertEqual(doc['source']['snapshot_hash'],digest(d))
        self.assertEqual(loads(dumps(doc)),doc);self.assertEqual(doc['source']['rotation_sign'],-1)
        for layer in mesh['layers']:
            curves=[c for c in doc['rows'][0]['curves'] if c['span']==layer['span']]
            for side,curve in zip(layer['sides'],curves):
                for (x,y),p in zip(side,curve['points']):
                    a,r,t=source_point('turbine_x_m_phi',p)
                    self.assertAlmostEqual(a,x);self.assertAlmostEqual(r,layer['radius']);self.assertAlmostEqual(t*r,y)

    def test_variable_meridional_export_matches_world_xyz_with_proper_rotation(self):
        d=new_design();d['meridional']['enabled']=True;d['meridional']['casing'][-1][1]=.27
        mesh=geometry(d);doc=export_geometry(d)
        for layer in mesh['layers']:
            curves=[c for c in doc['rows'][0]['curves'] if c['span']==layer['span']]
            for world,curve in zip(layer['world_sides'],curves):
                for (x,y,z),p in zip(world,curve['points']):
                    for actual,expected in zip(cartesian(p),[-z,y,x]):self.assertAlmostEqual(actual,expected,places=12)
        self.assertEqual({c['role'] for c in curves},{'A','B'})
        self.assertEqual({c['group'] for c in doc['rows'][0]['curves']},{'main','hub','casing'})

    def test_stator_selection_and_invalid_selection(self):
        d=new_design();doc=export_geometry(d,1,0)
        self.assertEqual(doc['rows'][0]['id'],d['stages'][1]['rows'][0]['id'])
        self.assertEqual(doc['rows'][0]['kind'],'stationary')
        with self.assertRaises(ValueError):export_geometry(d,0,True)


if __name__=='__main__':unittest.main()
