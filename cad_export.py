"""Keep the optional native CAD runtime outside the web server process."""
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from core import geometry, world_sides


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


def blade_payload(design, stage_index, row_index):
    blade = geometry(design, stage_index, row_index)
    for warning in blade['warnings']:
        if '翼断面に自己交差' in warning:
            raise ValueError(f'{warning} 断面を修正してからSTEP出力してください。')
    return {
        'spans': [layer['span'] for layer in blade['layers']],
        'points_mm': [[[[value * 1000 for value in point] for point in side] for side in world_sides(layer)]
                      for layer in blade['layers']],
    }


def export_step(design, stage_index, row_index):
    executable = cad_python()
    payload = blade_payload(design, stage_index, row_index)
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
