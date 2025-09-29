# Comms-First Micromobility (Bike-Share) REST System

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start ONE backend (A/B later):
export PYTHONPATH=.
uvicorn backend_fastapi.app:app --host 0.0.0.0 --port 8000 --reload
# OR
python backend_flask/app.py   # (or gunicorn -w 4 -b :5000 backend_flask.app:app)

# Simulate devices / generate load
API_BASE=http://localhost:8000 N_DEVICES=300 RUN_S=60 python sim/device_sim.py
CONC=200 TOTAL=5000 CSV=latencies.csv python sim/loadgen.py

# Frontend
cd frontend && npm install && npm run dev
```
