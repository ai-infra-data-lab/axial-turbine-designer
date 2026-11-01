"""Local SQLite documents with revision checks and immutable history."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from core import validate, now, digest

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS designs(id TEXT PRIMARY KEY, name TEXT, revision INTEGER, document TEXT, result TEXT, updated_at TEXT); CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, design_id TEXT, revision INTEGER, document TEXT, result TEXT, saved_at TEXT);')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,name,revision,updated_at FROM designs ORDER BY updated_at DESC')]

    def get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM designs WHERE id=?', (key,)).fetchone()
        if row is None:
            raise LookupError('保存済み案件がありません。')
        design=validate(json.loads(row['document']))
        result=json.loads(row['result']) if row['result'] else None
        if result and result.get('input_hash')!=digest(design):
            result=None
        return {'design':design, 'revision':row['revision'], 'result':result}

    def save(self, raw, revision, result=None):
        d = validate(raw)
        if type(revision) is not int or revision < 0:
            raise ValueError('保存revisionが不正です。')
        if result is not None and (result.get('input_hash') != digest(d) or result.get('input_snapshot') != d):
            raise ValueError('結果と入力が一致しません。再計算してください。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM designs WHERE id=?', (d['id'],)).fetchone()
            if (row['revision'] if row else 0) != revision:
                raise Conflict('他の画面で更新されています。再読込して確認してください。')
            rev, stamp = revision+1, now()
            doc = json.dumps(d, ensure_ascii=False, allow_nan=False)
            res = json.dumps(result, ensure_ascii=False, allow_nan=False) if result else None
            db.execute('INSERT OR REPLACE INTO designs VALUES(?,?,?,?,?,?)', (d['id'], d['name'], rev, doc, res, stamp))
            db.execute('INSERT INTO history(design_id,revision,document,result,saved_at) VALUES(?,?,?,?,?)', (d['id'],rev,doc,res,stamp))
        return self.get(d['id'])
