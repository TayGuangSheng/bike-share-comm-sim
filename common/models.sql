
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  name TEXT,
  status TEXT DEFAULT 'idle',
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  lat REAL,
  lon REAL,
  battery REAL,
  speed REAL,
  ride_state TEXT,
  unique_key TEXT,
  FOREIGN KEY(device_id) REFERENCES devices(id)
);

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  resource TEXT,
  status TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS policies (
  name TEXT PRIMARY KEY,
  body TEXT,
  etag TEXT
);

CREATE TABLE IF NOT EXISTS commands (
  id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  user_id TEXT,
  type TEXT NOT NULL,
  payload TEXT,
  status TEXT DEFAULT 'created',
  created_at INTEGER,
  delivered_at INTEGER,
  acked_at INTEGER
);

CREATE TABLE IF NOT EXISTS routes (
  id TEXT PRIMARY KEY,
  bike_id TEXT,
  origin_lat REAL,
  origin_lon REAL,
  dest_lat REAL,
  dest_lon REAL,
  steps TEXT,
  base_eta_s REAL,
  created_at INTEGER
);
