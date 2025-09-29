import sqlite3, os, json, hashlib
from contextlib import contextmanager

DB_PATH = os.environ.get("BIKESHARE_DB", os.path.join(os.path.dirname(__file__), "..", "db.sqlite3"))

def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-20000;")
    return conn

@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = connect()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS devices(
      id TEXT PRIMARY KEY, name TEXT NOT NULL,
      lock_state TEXT NOT NULL DEFAULT 'locked',
      lat REAL DEFAULT 0, lon REAL DEFAULT 0,
      battery REAL DEFAULT 100,
      updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE IF NOT EXISTS telemetry(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      device_id TEXT NOT NULL,
      ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      lat REAL, lon REAL, battery REAL, lock_state TEXT,
      FOREIGN KEY(device_id) REFERENCES devices(id)
    );
    CREATE TABLE IF NOT EXISTS rides(
      id TEXT PRIMARY KEY, device_id TEXT NOT NULL, user_id TEXT NOT NULL,
      start_ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      end_ts TEXT, start_lat REAL, start_lon REAL, end_lat REAL, end_lon REAL, fare REAL DEFAULT 0,
      FOREIGN KEY(device_id) REFERENCES devices(id)
    );
    CREATE TABLE IF NOT EXISTS idempotency(
      key TEXT PRIMARY KEY, device_id TEXT, endpoint TEXT, seq INTEGER,
      ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), payload_hash TEXT, ack_token TEXT
    );
    CREATE TABLE IF NOT EXISTS policies(
      name TEXT PRIMARY KEY, blob TEXT NOT NULL, etag TEXT NOT NULL,
      updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    """)
    # seed default policies if empty
    cur.execute("SELECT COUNT(*) c FROM policies")
    if cur.fetchone()["c"] == 0:
        geofences = {"type":"FeatureCollection","features":[
          {"type":"Feature","properties":{"name":"Downtown no-park"},
           "geometry":{"type":"Polygon","coordinates":[[[0,0],[0,5],[5,5],[5,0],[0,0]]]}}
        ]}
        pricing = {"base":1.0,"per_min":0.2,"surge_zones":[{"center":[10,10],"radius":2,"multiplier":1.5}]}
        for name, blob in [("geofences", geofences), ("pricing", pricing)]:
            s = json.dumps(blob, sort_keys=True)
            etag = hashlib.sha256(s.encode()).hexdigest()
            cur.execute("INSERT INTO policies(name, blob, etag) VALUES(?,?,?)", (name, s, etag))
    conn.commit(); conn.close()
