import asyncio, httpx, random, time, uuid, os, hashlib

API = os.environ.get("API_BASE", "http://localhost:8000")
def idem_key(device_id, seq): return hashlib.sha256(f"{device_id}:{seq}".encode()).hexdigest()

async def post_with_retries(client, url, json=None, headers=None, N=6):
    base=0.2
    for a in range(N):
        try:
            r = await client.post(url, json=json, headers=headers, timeout=5.0)
            if r.status_code in (200,201,304) or r.status_code==409: return r
            if r.status_code==429:
                await asyncio.sleep(float(r.headers.get("Retry-After","0.5"))+random.random()*0.1); continue
        except: pass
        await asyncio.sleep(min(5.0, base*(2**a)) + random.random()*0.1)
    raise RuntimeError("max attempts")

async def device_task(i, run_s=30):
    device_id=f"bike-{i:03d}"
    async with httpx.AsyncClient() as cl:
        await cl.post(f"{API}/devices", json={"id":device_id,"name":f"Bike {i}"})
        #lat,lon=random.randint(0,19),random.randint(0,19); 
        # Center around Melbourne (-37.81, 144.96) with ±0.05° jitter
        lat = -37.8136 + random.uniform(-0.05, 0.05)
        lon = 144.9631 + random.uniform(-0.05, 0.05)
        seq=0; t0=time.time()
        while time.time()-t0 < run_s:
            seq+=1
            h={"Idempotency-Key": idem_key(device_id, seq), "X-Device-Id": device_id}
            payload={"seq":seq,"lat":lat,"lon":lon,"battery":max(0,100-seq*0.1),"lock_state":"locked"}
            await post_with_retries(cl, f"{API}/devices/{device_id}/telemetry", json=payload, headers=h)
            lat += random.uniform(-0.001, 0.001)   # ~100 m
            lon += random.uniform(-0.001, 0.001)
            if random.random()<0.05:
                ride=str(uuid.uuid4())
                await cl.post(f"{API}/devices/{device_id}/unlock", json={"user_id":"u1","ride_id":ride}, headers={"X-Device-Id":device_id})
                await cl.post(f"{API}/rides", json={"id":ride,"user_id":"u1","device_id":device_id,"start_lat":lat,"start_lon":lon}, headers={"X-Device-Id":device_id})
                dest = {
                    "lat": -37.8136 + random.uniform(-0.05, 0.05),
                    "lon": 144.9631 + random.uniform(-0.05, 0.05)
                }
                rr=await cl.post(f"{API}/route/plan", json={"from":{"lat":lat,"lon":lon},"to":dest})
                for p in rr.json().get("path",[])[:10]:
                    seq+=1
                    h={"Idempotency-Key": idem_key(device_id, seq), "X-Device-Id": device_id}
                    payload={"seq":seq,"lat":p["lat"],"lon":p["lon"],"battery":max(0,100-seq*0.1),"lock_state":"unlocked"}
                    await post_with_retries(cl, f"{API}/devices/{device_id}/telemetry", json=payload, headers=h)
                    await asyncio.sleep(0.05)
                await cl.patch(f"{API}/rides/{ride}/end", json={"end_lat":dest["lat"],"end_lon":dest["lon"]}, headers={"X-Device-Id":device_id})
                await cl.post(f"{API}/devices/{device_id}/lock", json={}, headers={"X-Device-Id":device_id})
            await asyncio.sleep(0.1)

async def main():
    N=int(os.environ.get("N_DEVICES","100")); RUN=int(os.environ.get("RUN_S","30"))
    await asyncio.gather(*(asyncio.create_task(device_task(i,RUN)) for i in range(N)))

if __name__=="__main__": asyncio.run(main())
