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

from cad_export import CadUnavailable, blade_payload, export_step
from core import geometry, new_design
from server import make_server


class CadTests(unittest.TestCase):
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
                post = Request(url+'/api/step', body, {
                    'Content-Type':'application/json', 'X-Local-Token':bootstrap['token'],
                })
                raw = b'ISO-10303-21;'
                with patch('server.export_step', return_value=raw) as mocked:
                    with urlopen(post, timeout=5) as response:
                        self.assertEqual(response.headers['Content-Type'], 'model/step')
                        self.assertIn('axial-stage-02-stator.step', response.headers['Content-Disposition'])
                        self.assertEqual(response.read(), raw)
                    self.assertEqual(mocked.call_args.args[1:], (1, 0))
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
    def test_rotor_and_mapped_stator_round_trip(self):
        stator = new_design()
        stator['meridional']['enabled'] = True
        stator['meridional']['casing'][-1][1] += .01
        for design, stage, row in ((new_design(), 0, 1), (stator, 1, 0)):
            with self.subTest(stage=stage, row=row):
                data = export_step(design, stage, row)
                self.assertTrue(data.startswith(b'ISO-10303-21;'))
                self.assertIn(b'MANIFOLD_SOLID_BREP', data)
                self.assertIn(b'.MILLI.,.METRE.', data)
