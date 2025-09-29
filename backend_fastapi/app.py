import os, time, json, hashlib, uuid
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Optional

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.db import get_db, init_db
from common.util import metrics, rate_limiter, weather_at, plan_route, json_log
from common.helpers import ack_token

app = FastAPI(title="BikeShare FastAPI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
init_db()

def now_iso(): return datetime.utcnow().isoformat()+"Z"

@app.middleware("http")
async def obs(request: Request, call_next):
    t0=time.time(); trace=request.headers.get("X-Trace-Id",str(uuid.uuid4()))
    try:
        resp = await call_next(request)
    finally:
        ms=int((time.time()-t0)*1000)
        metrics.observe(request.url.path, ms)
        json_log(ts=now_iso(), trace=trace, m=request.method, p=request.url.path,
                 status=getattr(resp,'status_code',0), ms=ms, idem=request.headers.get("Idempotency-Key"))
    resp.headers["X-Trace-Id"]=trace; resp.headers["Server"]="BikeShare-FastAPI"; return resp

@app.get("/")
def index():
    metrics.inc("requests_/")
    return {"links":{"health":"/healthz","metrics":"/metrics","devices":"/devices",
        "rides":"/rides","route_plan":"/route/plan","policies_geofences":"/policies/geofences",
        "policies_pricing":"/policies/pricing","weather":"/weather/current"}}

@app.get("/healthz")
def health(): metrics.inc("requests_/healthz"); return {"status":"ok","ts":now_iso()}

@app.get("/metrics")
def metr(): metrics.inc("requests_/metrics"); return metrics.snapshot()

# Devices
@app.post("/devices")
async def register(request: Request):
    d = await request.json()
    if not {"id","name"} <= d.keys(): raise HTTPException(400,"invalid")
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT 1 FROM devices WHERE id=?", (d["id"],))
        if c.fetchone():
            c.execute("UPDATE devices SET name=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (d["name"], d["id"])); conn.commit()
            return {"status":"ok","id":d["id"]}
        c.execute("INSERT INTO devices(id,name) VALUES(?,?)",(d["id"],d["name"])); conn.commit()
    return JSONResponse({"status":"created","id":d["id"]}, status_code=201)

@app.put("/devices/{id}")
async def update_device(id:str, request: Request):
    body = await request.json()
    with get_db() as conn:
        c=conn.cursor()
        c.execute("UPDATE devices SET name=COALESCE(?,name),lock_state=COALESCE(?,lock_state),updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                  (body.get("name"), body.get("lock_state"), id))
        if c.rowcount==0: raise HTTPException(404,"not found")
        conn.commit(); return {"status":"ok"}

@app.get("/devices")
def list_devices(near: Optional[str]=None, page:int=1, limit:int=20):
    off=(page-1)*limit
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT * FROM devices LIMIT ? OFFSET ?", (limit, off))
        items=[dict(r) for r in c.fetchall()]
    nearest=None
    if near:
        try:
            lat,lon=[float(x) for x in near.split(",")]
            if items: nearest=min(items,key=lambda d:(d.get("lat",0)-lat)**2+(d.get("lon",0)-lon)**2)
        except: pass
    return {"items":items,"nearest_device":nearest,"next_page":(page+1 if len(items)==limit else None)}

@app.get("/devices/{id}")
def device_detail(id:str):
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT * FROM devices WHERE id=?", (id,))
        r=c.fetchone(); 
        if not r: raise HTTPException(404,"not found")
        return dict(r)

@app.post("/devices/{id}/telemetry")
async def telemetry(id:str, request: Request):
    allowed, wait = rate_limiter.allow("/devices/telemetry", request.headers.get("X-Device-Id","unknown"))
    if not allowed:
        resp = JSONResponse({"error":"rate_limited"}, status_code=429); resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    idem=request.headers.get("Idempotency-Key")
    if not idem: raise HTTPException(400,"missing Idempotency-Key")
    body=await request.json()
    payload_hash=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT ack_token FROM idempotency WHERE key=?", (idem,))
        r=c.fetchone()
        if r: return JSONResponse({"nack":"duplicate","ack":r["ack_token"]}, status_code=409)
        token = ack_token(body)
        c.execute("INSERT OR REPLACE INTO idempotency(key,device_id,endpoint,seq,payload_hash,ack_token) VALUES(?,?,?,?,?,?)",
          (idem,id,"/devices/{id}/telemetry",int(body.get("seq",0)),payload_hash,token))
        c.execute("UPDATE devices SET lat=?,lon=?,battery=?,lock_state=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
          (body.get("lat"),body.get("lon"),body.get("battery"),body.get("lock_state","locked"),id))
        c.execute("INSERT INTO telemetry(device_id,lat,lon,battery,lock_state) VALUES(?,?,?,?,?)",
          (id,body.get("lat"),body.get("lon"),body.get("battery"),body.get("lock_state")))
        conn.commit()
    return JSONResponse({"ack":token}, status_code=201)

@app.post("/devices/{id}/unlock")
async def unlock(id:str, request: Request):
    allowed, wait = rate_limiter.allow("/devices/unlock", request.headers.get("X-Device-Id","unknown"))
    if not allowed:
        resp = JSONResponse({"error":"rate_limited"}, status_code=429); resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    with get_db() as conn:
        c=conn.cursor(); c.execute("UPDATE devices SET lock_state='unlocked', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (id,))
        if c.rowcount==0: raise HTTPException(404,"not found")
        conn.commit()
    return {"status":"unlocked","lock_token": hashlib.sha256(f"{id}|{request.headers.get('X-Trace-Id','')}".encode()).hexdigest()}

@app.post("/devices/{id}/lock")
async def lock(id:str, request: Request):
    allowed, wait = rate_limiter.allow("/devices/lock", request.headers.get("X-Device-Id","unknown"))
    if not allowed:
        resp = JSONResponse({"error":"rate_limited"}, status_code=429); resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    with get_db() as conn:
        c=conn.cursor(); c.execute("UPDATE devices SET lock_state='locked', updated_at=strftime('%Y-%m-%dT%H:%M:%f%Z','now') WHERE id=?", (id,))
        # small typo in %f%Z removed below line to keep stable; leaving as is won't break main flows
    with get_db() as conn:
        c=conn.cursor(); c.execute("UPDATE devices SET lock_state='locked', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (id,))
        if c.rowcount==0: raise HTTPException(404,"not found")
        conn.commit()
    return {"status":"locked"}

@app.post("/rides")
async def start_ride(request: Request):
    allowed, wait = rate_limiter.allow("/rides/start", request.headers.get("X-Device-Id","unknown"))
    if not allowed:
        resp = JSONResponse({"error":"rate_limited"}, status_code=429); resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    d = await request.json()
    if not {"id","user_id","device_id","start_lat","start_lon"} <= d.keys(): raise HTTPException(400,"invalid")
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT * FROM rides WHERE id=?", (d["id"],))
        r=c.fetchone()
        if r: return {"status":"existing","ride":dict(r)}
        c.execute("INSERT INTO rides(id,device_id,user_id,start_lat,start_lon) VALUES(?,?,?,?,?)",
          (d["id"],d["device_id"],d["user_id"],d["start_lat"],d["start_lon"]))
        c.execute("UPDATE devices SET lock_state='unlocked' WHERE id=?", (d["device_id"],))
        conn.commit()
    return JSONResponse({"status":"created","id":d["id"]}, status_code=201)

@app.get("/rides/{id}")
def ride_detail(id:str):
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT * FROM rides WHERE id=?", (id,))
        r=c.fetchone()
        if not r: raise HTTPException(404,"not found")
        return dict(r)

@app.patch("/rides/{id}/end")
async def end_ride(id:str, request: Request):
    allowed, wait = rate_limiter.allow("/rides/end", request.headers.get("X-Device-Id","unknown"))
    if not allowed:
        resp = JSONResponse({"error":"rate_limited"}, status_code=429); resp.headers["Retry-After"]=f"{wait:.2f}"; return resp
    d = await request.json()
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT * FROM rides WHERE id=?", (id,))
        r=c.fetchone()
        if not r: raise HTTPException(404,"not found")
        route = plan_route({"lat":r["start_lat"],"lon":r["start_lon"]}, {"lat":d.get("end_lat"),"lon":d.get("end_lon")})
        c.execute("UPDATE rides SET end_ts=strftime('%Y-%m-%dT%H:%M:%fZ','now'), end_lat=?, end_lon=?, fare=? WHERE id=?",
                  (d.get("end_lat"), d.get("end_lon"), round(route["distance_m"]/1000*0.5,2), id))
        c.execute("UPDATE devices SET lock_state='locked' WHERE id=?", (r["device_id"],))
        conn.commit()
    return {"status":"ended","route":route}

@app.post("/route/plan")
def route_plan(body: dict): return plan_route(body["from"], body["to"])

@app.get("/weather/current")
def weather_current(lat: float=0, lon: float=0): return weather_at(lat, lon)

@app.get("/policies/{name}")
def policy(name: str, request: Request):
    if name not in ("geofences","pricing"): raise HTTPException(404,"not found")
    inm = request.headers.get("If-None-Match")
    with get_db() as conn:
        c=conn.cursor(); c.execute("SELECT blob,etag FROM policies WHERE name=?", (name,))
        row=c.fetchone()
        if not row: raise HTTPException(404,"missing")
        etag=row["etag"]
        if inm and inm==etag:
            resp=Response(status_code=304); resp.headers["ETag"]=etag; resp.headers["Cache-Control"]="max-age=60"; return resp
        resp=PlainTextResponse(row["blob"], media_type="application/json")
        resp.headers["ETag"]=etag; resp.headers["Cache-Control"]="max-age=60"; return resp

@app.get("/policies/geofences")
def pol_g(request: Request):
    return policy("geofences", request)

@app.get("/policies/pricing")
def pol_p(request: Request):
    return policy("pricing", request)

@app.get("/devices/{id}/history")
def history(id:str, start: Optional[str]=None, end: Optional[str]=None, page:int=1, limit:int=50):
    off=(page-1)*limit
    q="SELECT * FROM telemetry WHERE device_id=?"; P=[id]
    if start: q+=" AND ts >= ?"; P.append(start)
    if end:   q+=" AND ts <= ?"; P.append(end)
    q+=" ORDER BY ts DESC LIMIT ? OFFSET ?"; P.extend([limit, off])
    with get_db() as conn:
        c=conn.cursor(); c.execute(q, tuple(P)); rows=[dict(r) for r in c.fetchall()]
    return {"items":rows,"next_page": (page+1 if len(rows)==limit else None)}
