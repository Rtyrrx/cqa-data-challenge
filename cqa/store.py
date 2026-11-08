import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}_{uuid4().hex}'


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS entities (
                kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (kind,id)
            );
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL
            );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, kind, id, db=None):
        if db is None:
            with self.connect() as connection:
                return self.get(kind, id, connection)
        row = db.execute('SELECT payload FROM entities WHERE kind=? AND id=?', (kind,id)).fetchone()
        if row is None:
            raise KeyError(f'{kind} not found: {id}')
        return json.loads(row['payload'])

    def all(self, kind):
        with self.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM entities WHERE kind=? ORDER BY rowid', (kind,))]

    def put(self, kind, id, payload, db=None):
        if db is None:
            with self.connect() as connection:
                self.put(kind, id, payload, connection)
            return
        db.execute('INSERT INTO entities(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload', (kind,id,dump(payload)))

    def log_usage(self, provider, model, input_tokens, output_tokens):
        with self.connect() as db:
            db.execute('INSERT INTO usage(created_at,provider,model,input_tokens,output_tokens) VALUES(?,?,?,?,?)', (now(),provider,model,input_tokens,output_tokens))

    def usage(self):
        with self.connect() as db:
            rows = db.execute("SELECT provider,model,SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,COUNT(*) AS calls FROM usage WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours') GROUP BY provider,model").fetchall()
            return [dict(r) for r in rows]
