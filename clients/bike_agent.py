
import argparse, asyncio, time, uuid, random, httpx

async def post_telemetry(client, telem, device_id, lat, lon, state):
    idem = str(uuid.uuid4())
    payload = {"ts": int(time.time()), "lat": lat, "lon": lon, "battery": round(random.uniform(30,100),1), "speed": round(random.uniform(0,5),2), "ride_state": state}
    await client.post(f"{telem}/devices/{device_id}/telemetry", headers={"Idempotency-Key": idem}, json=payload)

async def poll_commands(client, control, device_id):
    r = await client.get(f"{control}/devices/{device_id}/commands")
    return r.json()

async def ack(client, control, cmd_id):
    await client.post(f"{control}/commands/{cmd_id}/ack", json={"status":"ok"})

async def run(device_id, telem, control, start_lat, start_lon):
    async with httpx.AsyncClient(timeout=5.0) as client:
        lat, lon = start_lat, start_lon
        state = "idle"
        while True:
            await post_telemetry(client, telem, device_id, lat, lon, state)
            cmds = await poll_commands(client, control, device_id)
            for c in cmds:
                if c.get("type") == "unlock":
                    print(device_id, "unlock received, token", c.get("unlock_token"))
                    state = "in_ride"
                    await ack(client, control, c["id"])
            if state == "in_ride":
                lat += random.uniform(-0.0008, 0.0008)
                lon += random.uniform(-0.0008, 0.0008)
            await asyncio.sleep(1.5)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="dev-101")
    ap.add_argument("--telemetry", default="http://127.0.0.1:8002")
    ap.add_argument("--control", default="http://127.0.0.1:8200")
    ap.add_argument("--lat", type=float, default=1.295)
    ap.add_argument("--lon", type=float, default=103.855)
    args = ap.parse_args()
    asyncio.run(run(args.device, args.telemetry, args.control, args.lat, args.lon))

if __name__ == "__main__":
    main()
