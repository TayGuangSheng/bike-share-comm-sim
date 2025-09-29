import os, time, json, hashlib, uuid
from flask import Flask, request, jsonify, g, make_response
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.db import get_db, init_db
from common.util import metrics, rate_limiter, weather_at, plan_route, json_log
from common.helpers import ack_token

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
init_db()

def now_iso(): return datetime.utcnow().isoformat()+"Z"

@app.before_request
def _before():
    g.t0 = time.time()
    g.trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    g.client = request.headers.get("X-Device-Id", request.remote_addr or "unknown")

@app.after_request
def _after(resp):
    ms = int((time.time()-g.t0)*1000)
    metrics.observe(request.path, ms)
    resp.headers["X-Trace-Id"] = g.trace_id
    resp.headers["Server"] = "BikeShare-Flask"
    json_log(ts=now_iso(), trace=g.trace_id, m=request.method, p=request.path,
             status=resp.status_code, ms=ms, idem=request.headers.get("Idempotency-Key"))
    return resp

@app.get("/")
def index():
    metrics.inc("requests_/")
    return jsonify({"links":{
      "health":"/healthz","metrics":"/metrics","devices":"/devices","rides":"/rides",
      "route_plan":"/route/plan","policies_geofences":"/policies/geofences",
      "policies_pricing":"/policies/pricing","weather":"/weather/current"}})

@app.get("/healthz")
def health(): metrics.inc("requests_/healthz"); return jsonify({"status":"ok","ts":now_iso()})

@app.get("/metrics")
def m(): metrics.inc("requests_/metrics"); return jsonify(metrics.snapshot())

# ---------- Devices ----------
@app.post("/devices")
def register():
    d = request.get_json(force=True) or {}
    if not {"id","name"} <= d.keys(): return jsonify({"error":"invalid"}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM devices WHERE id=?", (d["id"],))
        if cur.fetchone():
            cur.execute("UPDATE devices SET name=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (d["name"], d["id"]))
            conn.commit(); return jsonify({"status":"ok","id":d["id"]})
        cur.execute("INSERT INTO devices(id,name) VALUES(?,?)", (d["id"], d["name"]))
        conn.commit(); return jsonify({"status":"created","id":d["id"]}), 201

@app.put("/devices/<id>")
def update_device(id):
    body = request.get_json(force=True) or {}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE devices SET name=COALESCE(?,name), lock_state=COALESCE(?,lock_state), updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (body.get("name"), body.get("lock_state"), id))
        if cur.rowcount==0: return jsonify({"error":"not found"}), 404
        conn.commit(); return jsonify({"status":"ok"})

@app.get("/devices")
def list_devices():
    near = request.args.get("near"); page=int(request.args.get("page",1)); limit=int(request.args.get("limit",20))
    offset=(page-1)*limit
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("SELECT * FROM devices LIMIT ? OFFSET ?",(limit,offset))
        items = [dict(r) for r in cur.fetchall()]
    nearest=None
    if near:
        try:
            lat,lon = [float(x) for x in near.split(",")]
            if items: nearest=min(items, key=lambda d:(d.get("lat",0)-lat)**2+(d.get("lon",0)-lon)**2)
        except: pass
    next_page = page+1 if len(items)==limit else None
    return jsonify({"items":items,"nearest_device":nearest,"next_page":next_page})

@app.get("/devices/<id>")
def device_detail(id):
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("SELECT * FROM devices WHERE id=?", (id,))
        r = cur.fetchone(); 
        return (jsonify({"error":"not found"}),404) if not r else jsonify(dict(r))

@app.post("/devices/<id>/telemetry")
def telemetry(id):
    allowed, wait = rate_limiter.allow("/devices/telemetry", g.client)
    if not allowed:
        resp = jsonify({"error":"rate_limited"}); resp.status_code=429; resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    idem = request.headers.get("Idempotency-Key")
    if not idem: return jsonify({"error":"missing Idempotency-Key"}), 400
    body = request.get_json(force=True) or {}
    payload_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ack_token FROM idempotency WHERE key=?", (idem,))
        row = cur.fetchone()
        if row: return jsonify({"nack":"duplicate","ack":row["ack_token"]}), 409
        token = ack_token(body)
        cur.execute("INSERT OR REPLACE INTO idempotency(key,device_id,endpoint,seq,payload_hash,ack_token) VALUES(?,?,?,?,?,?)",
                    (idem, id, "/devices/{id}/telemetry", int(body.get("seq",0)), payload_hash, token))
        cur.execute("UPDATE devices SET lat=?,lon=?,battery=?,lock_state=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (body.get("lat"), body.get("lon"), body.get("battery"), body.get("lock_state","locked"), id))
        cur.execute("INSERT INTO telemetry(device_id,lat,lon,battery,lock_state) VALUES(?,?,?,?,?)",
                    (id, body.get("lat"), body.get("lon"), body.get("battery"), body.get("lock_state")))
        conn.commit()
    return jsonify({"ack":token}), 201

@app.post("/devices/<id>/unlock")
def unlock(id):
    allowed, wait = rate_limiter.allow("/devices/unlock", g.client)
    if not allowed:
        resp = jsonify({"error":"rate_limited"}); resp.status_code=429; resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("UPDATE devices SET lock_state='unlocked', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (id,))
        if cur.rowcount==0: return jsonify({"error":"not found"}), 404
        conn.commit()
    return jsonify({"status":"unlocked","lock_token": hashlib.sha256(f"{id}|{g.trace_id}".encode()).hexdigest()})

@app.post("/devices/<id>/lock")
def lock(id):
    allowed, wait = rate_limiter.allow("/devices/lock", g.client)
    if not allowed:
        resp = jsonify({"error":"rate_limited"}); resp.status_code=429; resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("UPDATE devices SET lock_state='locked', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (id,))
        if cur.rowcount==0: return jsonify({"error":"not found"}), 404
        conn.commit()
    return jsonify({"status":"locked"})

# ---------- Rides ----------
@app.post("/rides")
def start_ride():
    allowed, wait = rate_limiter.allow("/rides/start", g.client)
    if not allowed:
        resp = jsonify({"error":"rate_limited"}); resp.status_code=429; resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    d = request.get_json(force=True) or {}
    if not {"id","user_id","device_id","start_lat","start_lon"} <= d.keys(): return jsonify({"error":"invalid"}), 400
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("SELECT * FROM rides WHERE id=?", (d["id"],))
        r = cur.fetchone()
        if r: return jsonify({"status":"existing","ride":dict(r)})
        cur.execute("INSERT INTO rides(id,device_id,user_id,start_lat,start_lon) VALUES(?,?,?,?,?)",
            (d["id"], d["device_id"], d["user_id"], d["start_lat"], d["start_lon"]))
        cur.execute("UPDATE devices SET lock_state='unlocked' WHERE id=?", (d["device_id"],))
        conn.commit()
    return jsonify({"status":"created","id":d["id"]}), 201

@app.get("/rides/<id>")
def ride_detail(id):
    with get_db() as conn:
        cur = conn.cursor(); cur.execute("SELECT * FROM rides WHERE id=?", (id,))
        r = cur.fetchone(); return (jsonify({"error":"not found"}),404) if not r else jsonify(dict(r))

@app.patch("/rides/<id>/end")
def end_ride(id):
    allowed, wait = rate_limiter.allow("/rides/end", g.client)
    if not allowed:
        resp = jsonify({"error":"rate_limited"}); resp.status_code=429; resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    d = request.get_json(force=True) or {}
    with get_db() as conn:
        cur=conn.cursor(); cur.execute("SELECT * FROM rides WHERE id=?", (id,)); r=cur.fetchone()
        if not r: return jsonify({"error":"not found"}),404
        start={"lat":r["start_lat"],"lon":r["start_lon"]}; end={"lat":d.get("end_lat"),"lon":d.get("end_lon")}
        route = plan_route(start, end)
        cur.execute("UPDATE rides SET end_ts=strftime('%Y-%m-%dT%H:%M:%fZ','now'), end_lat=?, end_lon=?, fare=? WHERE id=?",
                    (end["lat"], end["lon"], round(route["distance_m"]/1000*0.5,2), id))
        cur.execute("UPDATE devices SET lock_state='locked' WHERE id=?", (r["device_id"],))
        conn.commit()
    return jsonify({"status":"ended","route":route})

# ---------- Routing & Weather ----------
@app.post("/route/plan")
def route_plan():
    data = request.get_json(force=True) or {}
    return jsonify(plan_route(data["from"], data["to"]))

@app.get("/weather/current")
def weather_current():
    lat = float(request.args.get("lat",0)); lon=float(request.args.get("lon",0))
    return jsonify(weather_at(lat, lon))

# ---------- Policies with ETag/304 ----------
@app.get("/policies/<name>")
def policy(name):
    if name not in ("geofences","pricing"): return jsonify({"error":"not found"}), 404
    inm = request.headers.get("If-None-Match")
    with get_db() as conn:
        cur=conn.cursor(); cur.execute("SELECT blob,etag FROM policies WHERE name=?", (name,))
        row=cur.fetchone()
        if not row: return jsonify({"error":"missing"}),404
        etag=row["etag"]
        if inm and inm==etag:
            resp = make_response("",304); resp.headers["ETag"]=etag; resp.headers["Cache-Control"]="max-age=60"; return resp
        resp = make_response(row["blob"],200); resp.mimetype="application/json"
        resp.headers["ETag"]=etag; resp.headers["Cache-Control"]="max-age=60"; return resp

@app.get("/policies/geofences")
def geos(): return policy("geofences")

@app.get("/policies/pricing")
def pricing(): return policy("pricing")

# ---------- Telemetry history (pagination) ----------
@app.get("/devices/<id>/history")
def history(id):
    page=int(request.args.get("page",1)); limit=int(request.args.get("limit",50))
    start=request.args.get("start"); end=request.args.get("end"); offset=(page-1)*limit
    q="SELECT * FROM telemetry WHERE device_id=?"; P=[id]
    if start: q+=" AND ts >= ?"; P.append(start)
    if end:   q+=" AND ts <= ?"; P.append(end)
    q+=" ORDER BY ts DESC LIMIT ? OFFSET ?"; P.extend([limit, offset])
    with get_db() as conn:
        cur=conn.cursor(); cur.execute(q, tuple(P)); rows=[dict(r) for r in cur.fetchall()]
    return jsonify({"items":rows,"next_page":(page+1 if len(rows)==limit else None)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
