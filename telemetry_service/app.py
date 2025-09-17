
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
import time, json, hashlib, os
from common.db import get_conn, init_db, upsert_device, check_idempotency, record_idempotency, insert_telemetry, list_devices, get_device_history, get_policy

app = FastAPI(title="Telemetry Service")
init_db()

def ack_token(payload: dict) -> str:
    j = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(j.encode()).hexdigest()

@app.get("/healthz")
async def healthz():
    return {"status":"ok","ts":int(time.time())}

@app.post("/devices")
async def register_device(req: Request):
    data = await req.json()
    device_id = data.get("id")
    name = data.get("name", device_id)
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing id")
    with get_conn() as conn:
        upsert_device(conn, device_id, name)
    return JSONResponse({"id": device_id, "name": name}, status_code=201)

@app.get("/devices")
async def list_devices_ep(status: str | None = None, page: int = 1, limit: int = 50):
    offset = (page - 1) * limit
    rows = list_devices(get_conn(), status=status, limit=limit, offset=offset)
    return [dict(r) for r in rows]

@app.post("/devices/{device_id}/telemetry")
async def post_telemetry(device_id: str, req: Request):
    idem = req.headers.get("Idempotency-Key")
    if not idem:
        raise HTTPException(status_code=400, detail="missing Idempotency-Key")
    with get_conn() as conn:
        if check_idempotency(conn, idem):
            return JSONResponse({"status": "duplicate", "key": idem}, status_code=409)
        payload = await req.json()
        payload.setdefault("ts", int(time.time()))
        payload.setdefault("ride_state", "idle")
        payload["unique_key"] = idem
        insert_telemetry(conn, device_id, payload)
        record_idempotency(conn, idem, resource=f"telemetry:{device_id}", status="committed")
    token = ack_token({"device_id": device_id, "key": idem})
    return JSONResponse({"ack": token}, status_code=201)

@app.get("/devices/{device_id}/history")
async def device_history(device_id: str, start: int | None = None, end: int | None = None, page: int = 1, limit: int = 100):
    offset = (page - 1) * limit
    rows = get_device_history(get_conn(), device_id, start=start, end=end, limit=limit, offset=offset)
    return [dict(r) for r in rows]

def _conditional_json(name, inm):
    row = get_policy(get_conn(), name)
    if not row: return JSONResponse({"error":"not found"}, status_code=404)
    body, etag = row["body"], row["etag"]
    if inm and inm == etag:
        return Response(status_code=304)
    resp = Response(content=body, media_type="application/json")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "max-age=60"
    return resp

@app.get("/policies/geofences")
async def geofences(if_none_match: str | None = None):
    return _conditional_json("geofences", if_none_match)

@app.get("/policies/pricing")
async def pricing(if_none_match: str | None = None):
    return _conditional_json("pricing", if_none_match)
