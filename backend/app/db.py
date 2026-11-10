from contextlib import contextmanager
import atexit
from threading import Lock
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from . import config
from .config import DATABASE_URL

_pool = None
_pool_lock = Lock()

def get_pool():
    """Lazy, process-local pool: imports and unit tests don't connect to PostgreSQL."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                DATABASE_URL, min_size=config.DB_POOL_MIN, max_size=config.DB_POOL_MAX,
                timeout=config.DB_POOL_TIMEOUT, max_waiting=config.DB_POOL_MAX_WAITING,
                kwargs={'row_factory': dict_row, 'connect_timeout': 5}, open=False,
            )
            _pool.open()
        return _pool

def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None

atexit.register(close_pool)

@contextmanager
def connect():
    # Commits on success, rolls back on failure, returns connection to the pool.
    with get_pool().connection() as conn:
        yield conn

def changed(cur):
    cur.execute('UPDATE system_state SET version=version+1 WHERE id=1')

def log(cur, incident_id, kind, body):
    cur.execute('INSERT INTO incident_events(incident_id,kind,body) VALUES (%s,%s,%s)',
                (incident_id, kind, body))

def create_incident(cur, trip_id, kind, severity, summary, evidence):
    # All incident writers take trip then incident locks, including the SOS path.
    cur.execute('SELECT id FROM trips WHERE id=%s FOR UPDATE', (trip_id,))
    cur.execute("SELECT * FROM incidents WHERE trip_id=%s AND kind=%s AND status='OPEN' FOR UPDATE",
                (trip_id, kind))
    old = cur.fetchone()
    incident_id = old['id'] if old else uuid4()
    if old:
        cur.execute('UPDATE incidents SET severity=GREATEST(severity,%s), summary=%s, evidence=%s, updated_at=now() WHERE id=%s',
                    (severity, summary, Jsonb(evidence), incident_id))
        if severity > old['severity']:
            cur.execute("UPDATE proposals SET status='CANCELLED' WHERE incident_id=%s AND status='PENDING'", (incident_id,))
            cur.execute('UPDATE incidents SET needs_plan=true WHERE id=%s', (incident_id,))
    else:
        cur.execute('INSERT INTO incidents(id,trip_id,kind,severity,summary,evidence) VALUES (%s,%s,%s,%s,%s,%s)',
                    (incident_id, trip_id, kind, severity, summary, Jsonb(evidence)))
    log(cur, incident_id, 'signal', summary)
    cur.execute('UPDATE trips SET version=version+1 WHERE id=%s', (trip_id,))
    return incident_id

def migrate():
    """Bootstrap plus ordered, transactional SQL migrations under one database lock."""
    from pathlib import Path
    import hashlib
    directory = Path(__file__).resolve().parents[1]
    with connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(730014)')
        conn.execute((directory / 'schema.sql').read_text(encoding='utf-8'))
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        for path in sorted((directory / 'migrations').glob('*.sql')):
            sql = path.read_text(encoding='utf-8')
            digest = hashlib.sha256(sql.encode()).hexdigest()
            existing = conn.execute('SELECT checksum FROM schema_migrations WHERE version=%s', (path.name,)).fetchone()
            if existing:
                if existing['checksum'] != digest:
                    raise RuntimeError(f'Applied migration changed: {path.name}; create a new migration instead')
                continue
            conn.execute(sql)
            conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)', (path.name, digest))

if __name__ == '__main__':
    try:
        migrate()
        print('Schema and migrations ready')
    finally:
        close_pool()
