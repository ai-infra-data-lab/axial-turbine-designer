import copy
import json
import math
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from core import new_design, validate, solve, section_profile, interpolate_section, geometry, obj_text, link_bundle, digest, uid
from store import Store, Conflict
from server import make_server

class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.d = new_design()

    def test_work_energy_and_reaction(self):
        result = solve(self.d)
        c = self.d['conditions']
        self.assertAlmostEqual(result['summary']['power'],c['power'])
        self.assertAlmostEqual(result['summary']['outlet_temperature'],c['inlet_temperature']-c['power']/(c['mass_flow']*c['cp']))
        for row in result['stages']:
            self.assertAlmostEqual(row['euler_residual'],0,places=8)
            self.assertAlmostEqual(row['energy_residual'],0,places=8)
            reaction=(row['inlet']['temperature']-row['outlet']['temperature'])*c['cp']/row['work']
            self.assertAlmostEqual(reaction,row['reaction'],places=10)
            self.assertAlmostEqual(row['outlet']['mass_residual'],0,places=10)

    def test_isentropic_limit(self):
        self.d['conditions']['stage_efficiency']=1
        self.assertAlmostEqual(solve(self.d)['summary']['efficiency_tt'],1,places=12)

    def test_stage_work_distribution(self):
        self.d['stages'][0]['weight']=3
        r=solve(self.d)['stages']
        self.assertAlmostEqual(r[0]['work']/r[1]['work'],3)

    def test_infeasible_work_rejected(self):
        self.d['conditions']['power']=1e9
        with self.assertRaises(ValueError):
            solve(self.d)

    def test_invalid_numbers_and_geometry_rejected(self):
        for v in [float('nan'),float('inf'),True,None,-2]:
            d=copy.deepcopy(self.d)
            d['conditions']['mass_flow']=v
            with self.subTest(v=v),self.assertRaises(ValueError):
                validate(d)
        self.d['geometry']['tip_radius']=.1
        with self.assertRaises(ValueError):
            validate(self.d)

    def test_input_snapshot_detached_and_hash_changes(self):
        r=solve(self.d)
        self.d['conditions']['power']+=100
        self.assertNotEqual(r['input_hash'],digest(self.d))
        self.assertEqual(r['input_hash'],digest(r['input_snapshot']))

class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.d=new_design()
        self.sections=self.d['stages'][0]['rows'][1]['sections']

    def test_profile_thickness_and_endpoints(self):
        s=self.sections[0]
        a,b=section_profile(s,101)
        self.assertEqual(a[0],b[0])
        peak=35
        self.assertAlmostEqual(math.dist(a[peak],b[peak]),s['thickness'])
        self.assertAlmostEqual(math.dist(a[-1],b[-1]),s['trailing'])
        midpoint=[(a[-1][j]+b[-1][j])/2 for j in (0,1)]
        self.assertAlmostEqual(midpoint[0],s['chord']+s['sweep'])
        self.assertAlmostEqual(midpoint[1],s['chord']*math.tan(math.radians(s['stagger']))+s['lean'])

    def test_span_interpolation_and_offsets(self):
        s=interpolate_section(self.sections,.125)
        self.assertAlmostEqual(s['sweep'],.0005)
        self.assertAlmostEqual(s['thickness'],sum(x['thickness'] for x in self.sections[:2])/2)
        self.assertEqual(interpolate_section(self.sections,1)['span'],1)

    def test_default_mesh_and_obj(self):
        g=geometry(self.d)
        self.assertFalse(g['warnings'])
        self.assertEqual(len(g['layers']),17)
        self.assertEqual(g['layers'][0]['radius'],.16)
        self.assertEqual(g['layers'][-1]['radius'],.24)
        obj=obj_text(self.d)
        self.assertEqual(sum(l.startswith('v ') for l in obj.splitlines()),17*162)
        self.assertEqual(sum(l.startswith('f ') for l in obj.splitlines()),16*162)

    def test_overcrowded_blades_warn(self):
        self.d['stages'][0]['rows'][1]['blade_count']=500
        self.assertTrue(any('隣接翼' in w for w in geometry(self.d)['warnings']))

    def test_duplicate_spans_and_ids_rejected(self):
        self.sections[1]['span']=0
        with self.assertRaises(ValueError):validate(self.d)
        self.sections[1]['span']=.25
        self.sections[1]['id']=self.sections[0]['id']
        with self.assertRaises(ValueError):validate(self.d)

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite3')
        self.d=new_design()

    def tearDown(self):self.tmp.cleanup()

    def test_save_reload_history_and_conflict(self):
        first=self.store.save(self.d,0,solve(self.d))
        self.assertEqual(first['revision'],1)
        self.assertEqual(self.store.get(self.d['id'])['design'],self.d)
        self.d['name']='改訂'
        self.store.save(self.d,1)
        self.assertIsNone(self.store.get(self.d['id'])['result'])
        with self.assertRaises(Conflict):self.store.save(self.d,1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0],2)

    def test_stale_result_cannot_be_saved(self):
        r=solve(self.d)
        self.d['stages'][0]['rows'][0]['sections'][0]['stagger']+=1
        with self.assertRaises(ValueError):self.store.save(self.d,0,r)

    def test_link_roundtrip_and_tamper(self):
        p={'id':uid(),'name':'テスト案件','components':[{'id':uid(),'name':'タービン','kind':'turbine'}]}
        b={'format':'gas-turbine-manager','bundle_version':1,'revision':3,'project':p}
        self.d['link']=link_bundle(b,p['components'][0]['id'])
        self.store.save(self.d,0)
        self.assertEqual(self.store.get(self.d['id'])['design']['link']['source_revision'],3)
        self.d['link']['source_snapshot']['name']='改ざん'
        with self.assertRaises(ValueError):validate(self.d)

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.server=make_server(0,Path(cls.tmp.name)/'api.sqlite3')
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.bootstrap=json.load(urllib.request.urlopen(cls.url+'/api/bootstrap'))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()

    def post(self,path,data,**headers):
        req=urllib.request.Request(self.url+path,json.dumps(data).encode(),{'Content-Type':'application/json','X-Local-Token':self.bootstrap['token'],**headers})
        return json.load(urllib.request.urlopen(req))

    def test_static_ui_and_no_path_traversal(self):
        with urllib.request.urlopen(self.url+'/') as r:
            self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])
            self.assertIn('翼形状',r.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(self.url+'/../core.py')
        self.assertEqual(e.exception.code,404)

    def test_api_run_save_reload_export_geometry(self):
        d=new_design()
        r=self.post('/api/run',{'design':d})
        self.assertEqual(r['input_hash'],digest(d))
        saved=self.post('/api/save',{'design':d,'revision':0,'include_result':True})
        self.assertEqual(saved['revision'],1)
        loaded=json.load(urllib.request.urlopen(self.url+'/api/design?id='+d['id']))
        self.assertEqual(loaded['result']['input_snapshot'],d)
        self.assertIn('v ',self.post('/api/obj',{'design':d})['text'])
        self.assertEqual(len(self.post('/api/preview',{'design':d})['layers']),17)

    def test_origin_token_and_host_guards(self):
        for headers in [{'Origin':'https://example.com'},{'X-Local-Token':'bad'},{'Host':'example.com'}]:
            with self.subTest(headers=headers),self.assertRaises(urllib.error.HTTPError) as e:
                self.post('/api/run',{'design':new_design()},**headers)
            self.assertEqual(e.exception.code,403)

    def test_import_discards_external_result(self):
        d=new_design()
        r=self.post('/api/import',{'format':'axial-turbine-designer','bundle_version':1,'design':d,'result':{'summary':'forged'}})
        self.assertEqual(r['design'],d)
        self.assertIsNone(r['result'])

if __name__=='__main__':unittest.main(verbosity=2)
