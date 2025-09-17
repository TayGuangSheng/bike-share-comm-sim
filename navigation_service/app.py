
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import csv, os, math, heapq, json, time, uuid, httpx
from common.db import get_conn, init_db, save_route, get_route

app = FastAPI(title="Navigation Service")
init_db()

NODES = {}
NEI = {}

def load_graph():
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    with open(os.path.join(base, "city_nodes.csv")) as f:
        r = csv.DictReader(f)
        for row in r:
            NODES[row["id"]] = (float(row["lat"]), float(row["lon"]))
    with open(os.path.join(base, "city_edges.csv")) as f:
        r = csv.DictReader(f)
        for row in r:
            a, b = row["src"], row["dst"]
            NEI.setdefault(a, []).append(b)
            NEI.setdefault(b, []).append(a)

def haversine(a, b):
    R=6371000.0
    lat1,lon1 = math.radians(a[0]), math.radians(a[1])
    lat2,lon2 = math.radians(b[0]), math.radians(b[1])
    dlat=lat2-lat1; dlon=lon2-lon1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(h))

def nearest_node(lat, lon):
    best, bid = None, None
    for nid, (la,lo) in NODES.items():
        d = haversine((lat,lon),(la,lo))
        if best is None or d < best:
            best, bid = d, nid
    return bid

def shortest_path(o_nid, d_nid):
    dist = {o_nid: 0.0}
    prev = {}
    pq = [(0.0, o_nid)]
    seen = set()
    while pq:
        d,u = heapq.heappop(pq)
        if u in seen: continue
        seen.add(u)
        if u == d_nid: break
        for v in NEI.get(u, []):
            w = haversine(NODES[u], NODES[v])
            nd = d + w
            if nd < dist.get(v, 1e30):
                dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v))
    if d_nid not in dist: return None, None
    path = []
    cur = d_nid
    while cur != o_nid:
        path.append(cur); cur = prev[cur]
    path.append(o_nid); path.reverse()
    return path, dist[d_nid]

async def get_weather(lat, lon):
    url = os.environ.get("WEATHER_URL", "http://127.0.0.1:8400/weather")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url, params={"lat": lat, "lon": lon})
            return r.json()
    except Exception:
        return {"condition":"clear","speed_factor":1.0}

@app.on_event("startup")
def _start():
    load_graph()

@app.post("/routes")
async def create_route(req: Request):
    body = await req.json()
    origin = body.get("origin"); dest = body.get("dest"); bike_id = body.get("bike_id","bike-demo")
    if not origin or not dest:
        raise HTTPException(status_code=400, detail="missing origin/dest")
    o = (origin["lat"], origin["lon"]); d = (dest["lat"], dest["lon"])
    on = nearest_node(*o); dn = nearest_node(*d)
    path, length_m = shortest_path(on, dn)
    if not path:
        raise HTTPException(status_code=400, detail="no path")
    base_eta = length_m / 4.0  # 4 m/s
    steps = [{"node": nid, "lat": NODES[nid][0], "lon": NODES[nid][1]} for nid in path]
    rid = str(uuid.uuid4())
    with get_conn() as conn:
        save_route(conn, rid, bike_id, o, d, steps, base_eta)
    return JSONResponse({"route_id": rid, "length_m": length_m, "base_eta_s": base_eta, "steps": steps}, status_code=201)

@app.get("/routes/{rid}")
def get_route_steps_ep(rid: str):
    row = get_route(get_conn(), rid)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {"route_id": rid, "steps": json.loads(row["steps"]), "base_eta_s": row["base_eta_s"]}

@app.get("/routes/{rid}/eta")
async def route_eta(rid: str):
    row = get_route(get_conn(), rid)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    steps = json.loads(row["steps"])
    mid = steps[len(steps)//2]
    wx = await get_weather(mid["lat"], mid["lon"])
    factor = float(wx.get("speed_factor", 1.0))
    eta = float(row["base_eta_s"]) / max(0.1, factor)
    return {"eta_s": eta, "condition": wx.get("condition","clear"), "speed_factor": factor}
