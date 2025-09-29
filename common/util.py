import hashlib, json, time, math, threading, math
from collections import defaultdict, deque

def compute_etag(obj) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, separators=(",",":"))
    return hashlib.sha256(s.encode()).hexdigest()

# ---- Token-bucket rate limiter (per route+client) ----
class TokenBucket:
    def __init__(self, capacity, refill_rate):
        self.capacity = capacity; self.tokens = capacity
        self.refill_rate = refill_rate; self.t = time.monotonic()
        self.lock = threading.Lock()
    def consume(self, n=1):
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.refill_rate)
            self.t = now
            if self.tokens >= n:
                self.tokens -= n; return True, 0
            need = n - self.tokens; wait = need / self.refill_rate if self.refill_rate>0 else 1
            return False, max(0.05, wait)

class RateLimiter:
    def __init__(self, cap=20, refill=10.0):
        self.cap, self.refill = cap, refill
        self.buckets = defaultdict(lambda: TokenBucket(cap, refill))
    def allow(self, route, client):
        return self.buckets[f"{route}:{client}"].consume(1)

rate_limiter = RateLimiter()

# ---- In-memory metrics with percentile snapshots ----
class Metrics:
    def __init__(self):
        self.counters = defaultdict(int)
        self.latencies = defaultdict(lambda: deque(maxlen=10000))
        self.lock = threading.Lock()
    def inc(self, k): 
        with self.lock: self.counters[k]+=1
    def observe(self, route, ms):
        with self.lock: self.latencies[route].append(ms)
    def snapshot(self):
        snap = {}
        with self.lock:
            for r, L in self.latencies.items():
                if not L: continue
                arr = sorted(L)
                def pct(p): 
                    i = min(len(arr)-1, max(0, int(math.ceil(p*(len(arr)-1)))))
                    return arr[i]
                snap[r] = {"count":len(arr),"p50":pct(0.50),"p95":pct(0.95),"p99":pct(0.99)}
        return {"counters": dict(self.counters), "latency": snap}
metrics = Metrics()

# ---- Simple simulated weather ----
def weather_at(lat, lon, ts=None):
    if ts is None: ts = time.time()
    hour = (ts % 86400)/3600.0
    if 6 <= hour < 12:  return {"condition":"clear","wind":3.0,"rain_mm_h":0.0,"speed_factor":1.0}
    if 12<= hour < 18:  return {"condition":"windy","wind":8.0,"rain_mm_h":0.0,"speed_factor":0.9}
    return {"condition":"rain","wind":4.0,"rain_mm_h":5.0,"speed_factor":0.75}

# ---- Grid route (Manhattan) & ETA ----
# add near existing dijkstra() code
def edge_weight(u, v):
    for neigh, w in graph.get(u, []):
        if neigh == v: return w
    for neigh, w in graph.get(v, []):
        if neigh == u: return w
    return 0

def plan_route(fr, to):
    s = nearest_node(fr["lat"], fr["lon"])
    g = nearest_node(to["lat"], to["lon"])
    total_cost, path_nodes = dijkstra(s, g)

    # polyline
    path = [{"lat": coords[n][0], "lon": coords[n][1]} for n in path_nodes]

    # per-segment steps with travel time (seconds) and fake distance (~100 m)
    steps = []
    segment_times = []
    dist_per_edge = 100
    for a, b in zip(path_nodes, path_nodes[1:]):
        t = edge_weight(a, b)
        segment_times.append(t)
        steps.append({
            "from": {"lat": coords[a][0], "lon": coords[a][1]},
            "to":   {"lat": coords[b][0], "lon": coords[b][1]},
            "time_s": t,
            "distance_m": dist_per_edge
        })

    return {
        "path": path,
        "steps": steps,
        "segment_times_s": segment_times,
        "distance_m": dist_per_edge * max(0, len(path_nodes)-1),
        "base_eta_s": total_cost,
        "weather_eta_s": 0,
        "total_eta_s": total_cost
    }


def json_log(**kw):
    import sys
    print(json.dumps(kw, separators=(",",":")), flush=True)
