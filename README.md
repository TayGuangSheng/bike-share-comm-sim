
# Bike Share Communications Simulation (One Laptop)

Simulates a bike-share system with multiple REST microservices:
- **Telemetry** (devices post telemetry, policies with ETag/304)
- **Discovery** (find nearest idle bike by latest telemetry)
- **Control/Unlock** (create unlock command, bikes poll and ACK)
- **Navigation** (grid graph routing + ETA; queries Weather)
- **Weather** (time-varying conditions affecting speed)

All services are FastAPI apps (run on different ports). Clients simulate user flow and bike device.

## 0) Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -c "from common.db import init_db; init_db(); print('db ready')"
```

## 1) Run services (five terminals or split panes)
```bash
# Terminal A: Telemetry on 8002
uvicorn telemetry_service.app:app --port 8002

# Terminal B: Discovery on 8100
uvicorn discovery_service.app:app --port 8100

# Terminal C: Control on 8200
uvicorn control_service.app:app --port 8200

# Terminal D: Navigation on 8300
uvicorn navigation_service.app:app --port 8300

# Terminal E: Weather on 8400
uvicorn weather_service.app:app --port 8400
```

## 2) Start a bike agent (simulated device posting telemetry + polling commands)
```bash
python clients/bike_agent.py --device dev-101 --telemetry http://127.0.0.1:8002 --control http://127.0.0.1:8200
# Open more terminals for dev-102, dev-103, ... if you want multiple bikes
```

## 3) Run end-to-end user flow (nearest → unlock → route → ETA)
```bash
python clients/user_flow.py --discovery http://127.0.0.1:8100 --control http://127.0.0.1:8200 --nav http://127.0.0.1:8300   --lat 1.295 --lon 103.855 --dest_lat 1.305 --dest_lon 103.865
```

### What should happen
- **Discovery** returns the nearest idle bike (`dev-101` if running).
- **Control** creates an unlock command (uses Idempotency-Key for reliability).
- **Bike agent** polls and ACKs the command; begins moving (changes lat/lon).
- **Navigation** computes route on the grid; **ETA** reflects **Weather** (speed factor 1.0 → 0.7 over time).

## 4) Inspect HTTP with Wireshark
- Capture on loopback interface; filter `http`.
- Check `Idempotency-Key` headers on `/unlock` and `/devices/{id}/telemetry`.
- Re-run `GET /routes/{id}/eta` to see changing weather factor.

## 5) Simulate bad networks (Linux only)
```bash
./scripts/netem.sh add 150ms 3%
# re-run flows; expect longer unlock time and ETA responses
./scripts/netem.sh show
./scripts/netem.sh delete
```

## Notes
- DB file lives at `data/app.db`.
- Extend schema or services as needed for your experiments.
- All endpoints are simple, explainable, and instrumentable for your report.
