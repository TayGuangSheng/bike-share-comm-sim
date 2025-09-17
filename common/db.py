
import sqlite3, os, time, json, hashlib, math

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))
DB_PATH = os.path.abspath(DB_PATH)

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    with get_conn() as conn, open(os.path.join(os.path.dirname(__file__), "models.sql"), "r") as f:
        conn.executescript(f.read())
    seed_policies()

def seed_policies():
    with get_conn() as conn:
        geofences = {"zones": [{"id": "CBD", "polygon": [[1.29,103.85],[1.29,103.86],[1.30,103.86],[1.30,103.85]]}]}
        pricing = {"zones": [{"id":"CBD","multiplier":1.5},{"id":"SUB","multiplier":1.0}]}
        for name, body in [("geofences", geofences), ("pricing", pricing)]:
            j = json.dumps(body, sort_keys=True)
            etag = hashlib.sha256(j.encode()).hexdigest()
            conn.execute("INSERT OR REPLACE INTO policies(name, body, etag) VALUES(?,?,?)", (name, j, etag))
        conn.commit()

def upsert_device(conn, device_id, name):
    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO devices(id, name, created_at) VALUES(?,?,?)", (device_id, name, now))
    conn.execute("UPDATE devices SET name=? WHERE id=?", (name, device_id))

def record_idempotency(conn, key, resource, status):
    now = int(time.time())
    conn.execute("INSERT OR REPLACE INTO idempotency(key, resource, status, created_at) VALUES(?,?,?,?)",
                 (key, resource, status, now))

def check_idempotency(conn, key):
    cur = conn.execute("SELECT key, resource, status FROM idempotency WHERE key=?", (key,))
    return cur.fetchone()

def insert_telemetry(conn, device_id, row):
    conn.execute(
        "INSERT INTO telemetry(device_id, ts, lat, lon, battery, speed, ride_state, unique_key) VALUES(?,?,?,?,?,?,?,?)",
        (device_id, row['ts'], row.get('lat'), row.get('lon'), row.get('battery'), row.get('speed'), row.get('ride_state'), row.get('unique_key'))
    )

def list_devices(conn, status=None, limit=50, offset=0):
    if status:
        sql = "SELECT * FROM devices WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args = (status, limit, offset)
    else:
        sql = "SELECT * FROM devices ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args = (limit, offset)
    return conn.execute(sql, args).fetchall()

def get_device_history(conn, device_id, start=None, end=None, limit=100, offset=0):
    where, args = ["device_id=?"], [device_id]
    if start: where.append("ts >= ?"); args.append(start)
    if end: where.append("ts <= ?"); args.append(end)
    sql = f"SELECT * FROM telemetry WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return conn.execute(sql, args).fetchall()

def get_policy(conn, name):
    return conn.execute("SELECT body, etag FROM policies WHERE name=?", (name,)).fetchone()

def latest_locations(conn, only_idle=False, limit=1000):
    sql = '''
    SELECT t.device_id, t.ts, t.lat, t.lon, t.ride_state
    FROM telemetry t
    JOIN (SELECT device_id, MAX(ts) AS mx FROM telemetry GROUP BY device_id) m
      ON t.device_id = m.device_id AND t.ts = m.mx
    ORDER BY t.ts DESC LIMIT ?
    '''
    rows = conn.execute(sql, (limit,)).fetchall()
    if only_idle:
        rows = [r for r in rows if (r["ride_state"] or "idle") == "idle"]
    return rows

def nearest_bike(conn, lat, lon, radius_m=500):
    R=6371000.0
    def hav(a,b):
        lat1,lon1,lat2,lon2 = map(math.radians, [a[0],a[1],b[0],b[1]])
        dlat=lat2-lat1; dlon=lon2-lon1
        h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        return 2*R*math.asin(math.sqrt(h))
    best=None; chosen=None
    rows = latest_locations(conn, only_idle=True, limit=5000)
    for r in rows:
        if r["lat"] is None or r["lon"] is None: 
            continue
        d = hav((lat,lon),(r["lat"],r["lon"]))
        if d <= radius_m and (best is None or d < best):
            best = d; chosen = r
    if chosen:
        return {"device_id": chosen["device_id"], "dist_m": best, "ts": chosen["ts"], "bike_lat": chosen["lat"], "bike_lon": chosen["lon"]}
    return None

def create_command(conn, cmd_id, device_id, user_id, typ, payload):
    now = int(time.time())
    conn.execute("INSERT OR REPLACE INTO commands(id, device_id, user_id, type, payload, status, created_at) VALUES(?,?,?,?,?,?,?)",
                 (cmd_id, device_id, user_id, typ, json.dumps(payload, sort_keys=True), "created", now))

def fetch_pending_commands(conn, device_id, since_ts=None, mark_delivered=True):
    if since_ts:
        cur = conn.execute("SELECT * FROM commands WHERE device_id=? AND status='created' AND created_at >= ?", (device_id, since_ts))
    else:
        cur = conn.execute("SELECT * FROM commands WHERE device_id=? AND status='created'", (device_id,))
    rows = cur.fetchall()
    if mark_delivered and rows:
        now = int(time.time())
        ids = [r["id"] for r in rows]
        conn.executemany("UPDATE commands SET status='delivered', delivered_at=? WHERE id=?", [(now, i) for i in ids])
    return rows

def ack_command(conn, cmd_id, ok=True):
    now = int(time.time())
    conn.execute("UPDATE commands SET status='acked', acked_at=? WHERE id=?", (now, cmd_id))

def save_route(conn, route_id, bike_id, origin, dest, steps, base_eta_s):
    now = int(time.time())
    conn.execute("INSERT OR REPLACE INTO routes(id, bike_id, origin_lat, origin_lon, dest_lat, dest_lon, steps, base_eta_s, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (route_id, bike_id, origin[0], origin[1], dest[0], dest[1], json.dumps(steps), float(base_eta_s), now))

def get_route(conn, route_id):
    cur = conn.execute("SELECT * FROM routes WHERE id=?", (route_id,))
    return cur.fetchone()

if __name__ == "__main__":
    init_db()
    print("DB initialized at", DB_PATH)
