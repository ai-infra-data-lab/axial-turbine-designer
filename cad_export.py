"""Keep the optional native CAD runtime outside the web server process."""
from importlib.util import find_spec
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from core import geometry, world_sides
import meridional


ROOT = Path(__file__).resolve().parent


class CadUnavailable(RuntimeError):
    pass


def cad_python():
    override = os.environ.get('AXIAL_TURBINE_CAD_PYTHON')
    if override:
        candidate = Path(override)
        if not candidate.is_absolute() or not candidate.is_file():
            raise CadUnavailable('AXIAL_TURBINE_CAD_PYTHON にCAD用Pythonの有効な絶対パスを指定してください。')
        return candidate
    suffix = Path('Scripts/python.exe') if sys.platform == 'win32' else Path('bin/python')
    dedicated = ROOT/'.venv-cad'/suffix
    if dedicated.is_file():
        return dedicated
    if find_spec('OCP') is not None:
        return Path(sys.executable)
    shared = ROOT.parent/'centrifugal_blade_designer'/'.venv-cad'/suffix
    if shared.is_file():
        return shared
    raise CadUnavailable('CAD環境がありません。READMEのSTEP出力に従って、CAD用のPython環境を設定してください。')


def fillet_options(raw, kind):
    if raw is None:
        return {}
    if not isinstance(raw, dict) or raw.keys() - {'hub', 'tip'}:
        raise ValueError('フィレットはハブ側とチップ側を指定してください。')
    if kind == 'rotor' and 'tip' in raw:
        raise ValueError('動翼のフィレットはハブ側に指定してください。')
    for side, values in raw.items():
        side_label = 'ハブ側' if side == 'hub' else 'チップ側'
        for key, label in (('radius_mm', '半径'), ('wall_mm', '接合部の厚さ')):
            value = values.get(key) if isinstance(values, dict) else None
            if type(value) not in (int, float) or not 0.001 <= value <= 30000:
                raise ValueError(f'{side_label}の{label}は0.001～30000 mmで指定してください。')
        shape = values.get('shape', 'circle')
        if shape not in ('circle', 'ellipse'):
            raise ValueError(f'{side_label}のフィレット形状は円弧または楕円を指定してください。')
        if shape == 'ellipse':
            ratio = values.get('radial_ratio')
            if type(ratio) not in (int, float) or not .25 <= ratio <= 4 or ratio == 1:
                raise ValueError(f'{side_label}の楕円の半径方向比は0.25以上1未満、または1より大きく4以下で指定してください。')
    return {side: raw[side] for side in ('hub', 'tip') if side in raw}


def wall_profile(design, side, end_points, radius, thickness):
    xs = [p[0] / 1000 for face in end_points for p in face]
    margin = max(3 * radius + 1, 3) / 1000
    lower, upper = min(xs) - margin, max(xs) + margin
    if design['meridional']['enabled']:
        wall = meridional.curves(design)[0 if side == 'hub' else 1]
        lower, upper = max(lower, wall.x[0]), min(upper, wall.x[-1])
        if min(xs) - lower <= radius / 1000 or upper - max(xs) <= radius / 1000:
            raise ValueError('フィレットを作る軸方向の余裕が足りません。子午面の定義範囲を広げてください。')
    else:
        r = design['geometry']['hub_radius' if side == 'hub' else 'tip_radius']
        wall = meridional.Curve([(lower, r), (upper, r)])
    knots = [lower, *(x for x in wall.x if lower < x < upper), upper]
    segments = []
    for a, b in zip(knots, knots[1:]):
        ra, da, _, _ = wall.jet(a)
        rb, db, _, _ = wall.jet(b, left=True)
        dx = (b - a) / 3
        poles = [(a, ra), (b, rb)]
        if not (math.isclose(da, (rb - ra) / (b - a), abs_tol=1e-10)
                and math.isclose(db, da, abs_tol=1e-10)):
            poles[1:1] = [(a + dx, ra + da * dx), (b - dx, rb - db * dx)]
        segments.append([[x * 1000, r * 1000] for x, r in poles])
    if side == 'hub' and thickness >= min(segment[i][1] for segment in segments for i in (0, -1)):
        raise ValueError('ハブ側接合部の厚さは接合位置のハブ半径より小さくしてください。')
    return segments


def blade_payload(design, stage_index, row_index, fillets=None):
    row = design['stages'][stage_index]['rows'][row_index]
    options = fillet_options(fillets, row['kind'])
    blade = geometry(design, stage_index, row_index)
    for warning in blade['warnings']:
        if '翼断面に自己交差' in warning:
            raise ValueError(f'{warning} 断面を修正してからSTEP出力してください。')
    payload = {
        'spans': [layer['span'] for layer in blade['layers']],
        'points_mm': [[[[value * 1000 for value in point] for point in side] for side in world_sides(layer)]
                      for layer in blade['layers']],
    }
    if options:
        sections = row['sections']
        payload['arc_length_samples'] = any(s.get('profile') or s.get('edges', {}).get('enabled') for s in sections)
        payload['smooth_nose'] = all((s.get('profile') or {}).get('lock_nose_tangent', True) for s in sections)
        payload['smooth_tail'] = all(s.get('edges', {}).get('enabled') and s['edges']['te_type'] != 'flat'
                                     for s in sections)
        layers = blade['layers']
        height = (layers[-1]['radius'] - layers[0]['radius']) * 1000
        payload['fillets'] = {
            side: {
                'radius_mm': values['radius_mm'],
                'wall_mm': values['wall_mm'],
                'radial_ratio': values['radial_ratio'] if values.get('shape') == 'ellipse' else 1.,
                'wall_profile': wall_profile(design, side, payload['points_mm'][0 if side == 'hub' else -1],
                                             values['radius_mm'], values['wall_mm']),
                'overlap_span': min(values['wall_mm'] * .4, 1.) / height,
            }
            for side, values in options.items()
        }
        if any(values['radial_ratio'] != 1 for values in payload['fillets'].values()):
            middle = payload['spans'].index(.5)
            payload['fillet_radial_yz'] = payload['points_mm'][middle][0][0][1:]
    return payload


def export_step(design, stage_index, row_index, fillets=None):
    payload = blade_payload(design, stage_index, row_index, fillets)
    executable = cad_python()
    with TemporaryDirectory(prefix='axial-blade-step-') as tmp:
        job = Path(tmp)
        (job/'blade.json').write_text(json.dumps(payload, allow_nan=False), encoding='utf-8')
        try:
            worker = subprocess.run(
                [str(executable), str(ROOT/'cad_worker.py'), '.'], cwd=job, capture_output=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=600,
                env={**os.environ, 'OPENBLAS_NUM_THREADS':'1', 'OMP_NUM_THREADS':'1'},
            )
        except subprocess.TimeoutExpired:
            raise ValueError('STEPの生成と再読込が制限時間内に完了しませんでした。') from None
        except OSError:
            raise CadUnavailable('CAD用Pythonを起動できませんでした。READMEの設定を確認してください。') from None
        error_file = job/'error.txt'
        if worker.returncode:
            if error_file.is_file():
                raise ValueError(error_file.read_text(encoding='utf-8'))
            if b'ModuleNotFoundError' in worker.stderr or b'ImportError' in worker.stderr:
                raise CadUnavailable('CAD用PythonにOpen CASCADEまたは数値計算の依存関係を読み込めませんでした。')
            raise ValueError('CAD処理が終了しました。翼断面とCAD環境を確認してください。')
        output = job/'blade.step'
        if not output.is_file():
            raise ValueError('検証済みのSTEPファイルを取得できませんでした。')
        step = output.read_bytes()
        if not step.startswith(b'ISO-10303-21;'):
            raise ValueError('検証済みのSTEPファイルを取得できませんでした。')
        return step
