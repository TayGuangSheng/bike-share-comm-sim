
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import time, uuid, json, os, hmac, hashlib
from common.db import get_conn, init_db, create_command, fetch_pending_commands, ack_command, check_idempotency, record_idempotency

SECRET = os.environ.get("CTRL_SECRET", "dev-secret")

def make_unlock_token(bike_id, user_id, ts):
    msg = f"{bike_id}:{user_id}:{ts}".encode()
    sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return f"{ts}.{sig[:16]}"

app = FastAPI(title="Control Service")
init_db()

@app.post("/unlock")
async def unlock(req: Request):
    idem = req.headers.get("Idempotency-Key")
    if not idem:
        raise HTTPException(status_code=400, detail="missing Idempotency-Key")
    body = await req.json()
    bike_id = body.get("bike_id")
    user_id = body.get("user_id","user-demo")
    if not bike_id:
        raise HTTPException(status_code=400, detail="missing bike_id")
    with get_conn() as conn:
        if check_idempotency(conn, idem):
            return JSONResponse({"status":"duplicate","key":idem}, status_code=409)
        ts = int(time.time())
        token = make_unlock_token(bike_id, user_id, ts)
        cmd_id = str(uuid.uuid4())
        payload = {"type":"unlock", "unlock_token": token, "expiry_s": 60}
        create_command(conn, cmd_id, bike_id, user_id, "unlock", payload)
        record_idempotency(conn, idem, resource=f"unlock:{bike_id}:{user_id}", status="created")
    return JSONResponse({"command_id": cmd_id, "unlock_token": token, "expiry_s": 60}, status_code=201)

@app.get("/devices/{bike_id}/commands")
def poll_commands(bike_id: str, since: int | None = None):
    rows = fetch_pending_commands(get_conn(), bike_id, since_ts=since, mark_delivered=True)
    out = []
    for r in rows:
        p = json.loads(r["payload"]) if r["payload"] else {}
        out.append({"id": r["id"], "type": r["type"], **p})
    return out

@app.post("/commands/{cmd_id}/ack")
async def ack(cmd_id: str, req: Request):
    data = await req.json()
    status = data.get("status","ok")
    with get_conn() as conn:
        ack_command(conn, cmd_id, ok=(status=="ok"))
    return {"ok": True, "id": cmd_id}
