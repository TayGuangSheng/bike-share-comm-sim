
import argparse, requests, uuid

def nearest(discovery, lat, lon, radius):
    r = requests.get(f"{discovery}/discovery/nearest", params={"lat":lat,"lon":lon,"radius":radius})
    r.raise_for_status(); return r.json()

def unlock(control, bike_id, user_id):
    idem = str(uuid.uuid4())
    r = requests.post(f"{control}/unlock", headers={"Idempotency-Key": idem}, json={"bike_id": bike_id, "user_id": user_id})
    return r.status_code, r.json()

def route(nav, origin, dest, bike_id):
    r = requests.post(f"{nav}/routes", json={"origin":origin,"dest":dest,"bike_id":bike_id})
    r.raise_for_status(); return r.json()

def eta(nav, route_id):
    r = requests.get(f"{nav}/routes/{route_id}/eta")
    r.raise_for_status(); return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discovery", default="http://127.0.0.1:8100")
    ap.add_argument("--control", default="http://127.0.0.1:8200")
    ap.add_argument("--nav", default="http://127.0.0.1:8300")
    ap.add_argument("--lat", type=float, default=1.295)
    ap.add_argument("--lon", type=float, default=103.855)
    ap.add_argument("--dest_lat", type=float, default=1.305)
    ap.add_argument("--dest_lon", type=float, default=103.865)
    ap.add_argument("--user", default="alice")
    args = ap.parse_args()

    print("Finding nearest bike...")
    nb = nearest(args.discovery, args.lat, args.lon, 800)
    print("Nearest:", nb)

    print("Requesting unlock...")
    sc, body = unlock(args.control, nb["device_id"], args.user)
    print("Unlock:", sc, body)

    print("Requesting route...")
    r = route(args.nav, {"lat": args.lat, "lon": args.lon}, {"lat": args.dest_lat, "lon": args.dest_lon}, nb["device_id"])
    print("Route:", r["route_id"], "base_eta_s", round(r["base_eta_s"],1))

    print("Checking ETA with weather...")
    e = eta(args.nav, r["route_id"])
    print("ETA_s:", round(e["eta_s"],1), "condition:", e["condition"], "factor:", e["speed_factor"])

if __name__ == "__main__":
    main()
