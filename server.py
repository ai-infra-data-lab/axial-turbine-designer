"""Loopback-only local UI. No network dependencies or manager DB access."""
import argparse
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from core import (new_design, validate, solve, geometry, obj_text, link_bundle, VERSION,
                  section_profile, section_metrics, curve_error, convert_section, restore_section,
                  interpolate_section, uid, aero_from_shape)
from profiles import fit_bspline
from store import Store, Conflict

ROOT = Path(__file__).resolve().parent
LIMIT = 8*1024*1024

def make_server(port=8782, data_path=None):
    store = Store(data_path or ROOT/'data'/'designs.sqlite3')
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, value, code=200, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, mutation=False):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != urlsplit(origin).netloc:
                raise PermissionError('127.0.0.1 のURLから開いてください。')
            if self.headers.get('Origin') not in (None, origin):
                raise PermissionError('別サイトからのアクセスは許可されていません。')
            if mutation and not secrets.compare_digest(self.headers.get('X-Local-Token',''),token):
                raise PermissionError('画面を再読込してください。')

        def dispatch(self, mutation=False):
            try:
                self.guard(mutation)
                path = urlsplit(self.path).path
                if not mutation:
                    if path == '/api/bootstrap':
                        return self.send({'token':token,'version':VERSION,'design':new_design(),'saved':store.list()})
                    if path == '/api/design':
                        return self.send(store.get(parse_qs(urlsplit(self.path).query).get('id',[''])[0]))
                    files = {'/':'index.html','/app.js':'app.js','/editor.js':'editor.js','/aero.js':'aero.js','/style.css':'style.css'}
                    if path in files:
                        ct = 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8' if path.endswith('.css') else 'text/html; charset=utf-8'
                        return self.send((ROOT/'static'/files[path]).read_bytes(),content_type=ct)
                    raise LookupError('ページがありません。')
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('JSONを指定してください。')
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= LIMIT:
                    raise ValueError('JSONは8 MB以内です。')
                data = json.loads(self.rfile.read(length))
                if path == '/api/link':
                    return self.send({'link':link_bundle(data['bundle'],data['component_id'])})
                if path == '/api/import':
                    if data.get('format') != 'axial-turbine-designer' or data.get('bundle_version') not in (1,2,3):
                        raise ValueError('軸流タービン設計のJSONを指定してください。')
                    return self.send({'design':validate(data['design']), 'result':None, 'revision':0})
                d = validate(data['design'])
                si, ri = data.get('stage_index',0), data.get('row_index',1)
                if type(si) is not int or type(ri) is not int or not 0 <= si < len(d['stages']) or ri not in (0,1):
                    raise ValueError('翼列の指定が不正です。')
                if path=='/api/aero-from-shape':
                    return self.send({'aero':aero_from_shape(d,si,ri)})
                if path in ('/api/section','/api/convert','/api/restore'):
                    sections=d['stages'][si]['rows'][ri]['sections']
                    section=next((s for s in sections if s['id']==data.get('section_id')),None)
                    if section is None:raise ValueError('編集する断面を選択してください。')
                    error=None
                    if path=='/api/convert':
                        count=data.get('control_count',17)
                        if type(count) is not int or not 6<=count<=25:raise ValueError('制御点数は6～25です。')
                        section,error=convert_section(section,data['target'],count)
                    if path=='/api/restore':section=restore_section(section)
                    sides=section_profile(section,161)
                    history=section.get('profile_history',[])
                    reference=section_profile(history[-1]['source'],161) if history else None
                    return self.send({'section':section,'sides':sides,'reference_sides':reference,
                                      'metrics':section_metrics(section,sides),'conversion_error':error,
                                      'current_error':curve_error(reference,sides) if reference else None})
                if path=='/api/add-section':
                    span=data['span']
                    if not isinstance(span,(int,float)) or not 0<span<1:raise ValueError('中間スパンを指定してください。')
                    row=d['stages'][si]['rows'][ri]
                    if len(row['sections'])>=21 or any(abs(s['span']-span)<1e-8 for s in row['sections']):
                        raise ValueError('断面数またはスパンが不正です。')
                    section=interpolate_section(row['sections'],span)
                    section['id']=uid()
                    if section.get('profile',{}).get('mode')=='_loft':
                        sides=[[[x-section['sweep'],y-section['lean']] for x,y in side] for side in section_profile(section)]
                        section['profile']={'mode':'direct','side_a':fit_bspline(sides[0]),'side_b':fit_bspline(sides[1]),'lock_nose_tangent':False}
                        section['profile_history']=[]
                    return self.send({'section':section})
                if path == '/api/preview':
                    return self.send(geometry(d,si,ri))
                if path == '/api/run':
                    return self.send(solve(d))
                if path == '/api/save':
                    # Client cannot persist forged numerical results.
                    return self.send(store.save(d,data['revision'],solve(d) if data.get('include_result') else None))
                if path == '/api/obj':
                    return self.send({'text':obj_text(d,si,ri)})
                raise LookupError('APIがありません。')
            except Conflict as e:
                self.send({'error':str(e)},409)
            except PermissionError as e:
                self.send({'error':str(e)},403)
            except LookupError as e:
                self.send({'error':str(e)},404)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as e:
                self.send({'error':str(e)},400)
            except Exception:
                self.send({'error':'処理に失敗しました。入力または保存先を確認してください。'},500)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8782)
    parser.add_argument('--open',action='store_true',help='起動後に既定のブラウザーを開く')
    args = parser.parse_args()
    server = make_server(args.port)
    print(f'Axial Turbine Designer {VERSION}: http://127.0.0.1:{server.server_port}',flush=True)
    if args.open:
        import threading
        import webbrowser
        threading.Timer(.7,lambda:webbrowser.open(f'http://127.0.0.1:{server.server_port}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
