"""STEP export API, geometry conventions, and optional native round trip."""
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cad_export import CadUnavailable, blade_payload, export_step, fillet_options
from core import geometry, new_design
from edges import defaults as edge_defaults
import meridional
from server import make_server


class CadTests(unittest.TestCase):
    def test_fillet_options_restrict_the_rotor_to_hub_and_reject_invalid_sizes(self):
        hub = {'radius_mm': .5, 'wall_mm': 3}
        tip = {'radius_mm': .25, 'wall_mm': 2}
        self.assertEqual(fillet_options({'hub': hub, 'tip': tip}, 'stator'), {'hub': hub, 'tip': tip})
        with self.assertRaisesRegex(ValueError, '動翼'):
            fillet_options({'tip': tip}, 'rotor')
        for entry in (None, {'radius_mm': True, 'wall_mm': 3}, {'radius_mm': .5, 'wall_mm': 0},
                      {'radius_mm': float('inf'), 'wall_mm': 3}, {'radius_mm': .5}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                fillet_options({'hub': entry}, 'rotor')

    def test_fillet_payload_uses_applied_endwall_profiles(self):
        design = new_design()
        data = design['meridional']
        data['enabled'] = True
        for side in ('hub', 'casing'):
            (x0, r0), (x1, _) = data[side]
            data[side] = [[x0, r0], [(x0 + x1) / 2, r0 + .003], [x1, r0 + .001]]
        options = {'hub': {'radius_mm': .5, 'wall_mm': 3}, 'tip': {'radius_mm': .25, 'wall_mm': 2}}
        payload = blade_payload(design, 0, 0, options)
        plain = blade_payload(design, 0, 0)
        self.assertEqual(payload['points_mm'], plain['points_mm'])
        self.assertNotIn('fillets', plain)
        for side, curve in zip(('hub', 'tip'), meridional.curves(design), strict=True):
            wall = payload['fillets'][side]
            self.assertEqual(wall['radius_mm'], options[side]['radius_mm'])
            self.assertGreater(wall['overlap_span'], 0.)
            for segment in wall['wall_profile']:
                self.assertEqual(len(segment), 4)
                x, radius = (sum(w * point[j] for w, point in zip((1, 3, 3, 1), segment)) / 8
                             for j in range(2))
                self.assertAlmostEqual(radius, 1000 * curve.jet(x / 1000)[0], places=8)

    def test_payload_matches_applied_wall_coordinates_and_preserves_input(self):
        design = new_design()
        design['meridional']['enabled'] = True
        design['meridional']['casing'][-1][1] += .01
        old = copy.deepcopy(design)
        payload = blade_payload(design, 1, 0)
        preview = geometry(design, 1, 0)
        self.assertEqual(payload['spans'], [layer['span'] for layer in preview['layers']])
        self.assertEqual(payload['points_mm'][0][0][0],
                         [x * 1000 for x in preview['layers'][0]['world_sides'][0][0]])
        self.assertGreater(payload['points_mm'][0][0][0][0], 0)
        self.assertEqual(design, old)

    def test_step_api_returns_binary_download_and_handles_cad_unavailable(self):
        with TemporaryDirectory() as tmp, make_server(0, Path(tmp)/'cases.sqlite3') as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                bootstrap = json.load(urlopen(url+'/api/bootstrap', timeout=5))
                body = json.dumps({'design':bootstrap['design'], 'stage_index':1, 'row_index':0}).encode()
                headers = {
                    'Content-Type':'application/json', 'X-Local-Token':bootstrap['token'],
                }
                post = Request(url+'/api/step', body, headers)
                raw = b'ISO-10303-21;'
                with patch('server.export_step', return_value=raw) as mocked:
                    with urlopen(post, timeout=5) as response:
                        self.assertEqual(response.headers['Content-Type'], 'model/step')
                        self.assertIn('axial-stage-02-stator.step', response.headers['Content-Disposition'])
                        self.assertEqual(response.read(), raw)
                    self.assertEqual(mocked.call_args.args[1:], (1, 0))
                    options = {'tip': {'radius_mm': .25, 'wall_mm': 3}}
                    stator = Request(url+'/api/step', json.dumps({
                        'design':bootstrap['design'], 'stage_index':0, 'row_index':0, 'fillets':options,
                    }).encode(), headers)
                    with urlopen(stator, timeout=5) as response:
                        self.assertIn('axial-stage-01-stator-fillet.step', response.headers['Content-Disposition'])
                    self.assertEqual(mocked.call_args.kwargs['fillets'], options)
                    rotor = Request(url+'/api/step', json.dumps({
                        'design':bootstrap['design'], 'stage_index':0, 'row_index':1, 'fillets':options,
                    }).encode(), headers)
                    with self.assertRaises(HTTPError) as failed:
                        urlopen(rotor, timeout=5)
                    self.assertEqual(failed.exception.code, 400)
                    self.assertEqual(mocked.call_count, 2)
                with patch('server.export_step', side_effect=CadUnavailable('CAD環境エラー')):
                    with self.assertRaises(HTTPError) as failed:
                        urlopen(post, timeout=5)
                    self.assertEqual(failed.exception.code, 503)
                    self.assertEqual(json.load(failed.exception)['error'], 'CAD環境エラー')
                rejected = Request(url+'/api/step', body, {'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as unauthorized:
                    urlopen(rejected, timeout=5)
                self.assertEqual(unauthorized.exception.code, 403)
                self.assertEqual(json.load(urlopen(url+'/api/bootstrap', timeout=5))['saved'], [])
            finally:
                server.shutdown()
                thread.join()


@unittest.skipUnless(os.environ.get('AXIAL_NATIVE_CAD_TEST') == '1', 'Opt in with an installed CAD runtime')
class NativeCadTests(unittest.TestCase):
    def assert_step_solid(self, data):
        self.assertTrue(data.startswith(b'ISO-10303-21;'))
        self.assertIn(b'MANIFOLD_SOLID_BREP', data)
        self.assertIn(b'.MILLI.,.METRE.', data)

    def test_rotor_and_mapped_stator_round_trip(self):
        stator = new_design()
        stator['meridional']['enabled'] = True
        stator['meridional']['casing'][-1][1] += .01
        for design, stage, row in ((new_design(), 0, 1), (stator, 1, 0)):
            with self.subTest(stage=stage, row=row):
                self.assert_step_solid(export_step(design, stage, row))

    def test_rotor_hub_and_stator_tip_fillet_round_trip(self):
        design = new_design()
        for section in design['stages'][0]['rows'][0]['sections']:
            section['edges'] = dict(edge_defaults(section), enabled=True)
        for row, side in ((1, 'hub'), (0, 'tip')):
            with self.subTest(side=side):
                self.assert_step_solid(export_step(design, 0, row, {side: {'radius_mm': .25, 'wall_mm': 3}}))

    def test_stator_fillet_on_both_applied_endwalls_round_trip(self):
        design = new_design()
        for section in design['stages'][0]['rows'][0]['sections']:
            section['edges'] = dict(edge_defaults(section), enabled=True)
        walls = design['meridional']
        walls['enabled'] = True
        for side in ('hub', 'casing'):
            (x0, r), (x1, _) = walls[side]
            walls[side] = [[x0, r], [(x0 + x1) / 2, r + .003], [x1, r + .001]]
        self.assert_step_solid(export_step(design, 0, 0, {
            'hub': {'radius_mm': .5, 'wall_mm': 3},
            'tip': {'radius_mm': .25, 'wall_mm': 3},
        }))
