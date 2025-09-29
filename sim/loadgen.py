import asyncio, httpx, time, csv, os, uuid

API = os.environ.get("API_BASE", "http://localhost:8000")

async def ping(client):
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{API}/healthz", timeout=5.0)
        dt = (time.perf_counter() - t0) * 1000
        return {
            "trace_id": str(uuid.uuid4()),
            "method": "GET",
            "path": "/healthz",
            "status": r.status_code,
            "latency_ms": int(dt)
        }
    except Exception:
        dt = (time.perf_counter() - t0) * 1000
        return {
            "trace_id": str(uuid.uuid4()),
            "method": "GET",
            "path": "/healthz",
            "status": "timeout",
            "latency_ms": int(dt)
        }

async def run(conc=50, total=500):
    out = []
    sem = asyncio.Semaphore(conc)
    async with httpx.AsyncClient() as c:
        async def one():
            async with sem:
                out.append(await ping(c))
        await asyncio.gather(*[asyncio.create_task(one()) for _ in range(total)])
    return out

def main():
    conc = int(os.environ.get("CONC", "100"))
    total = int(os.environ.get("TOTAL", "1000"))
    rows = asyncio.run(run(conc, total))
    path = os.environ.get("CSV", "latencies.csv")
    if rows:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {path} ({len(rows)} rows)")
    else:
        print("No rows collected!")

if __name__ == "__main__":
    main()
