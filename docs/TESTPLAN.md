# Baseline
1) Start FastAPI on :8000; curl /healthz.
2) Run simulator: `API_BASE=http://localhost:8000 N_DEVICES=50 RUN_S=10 python sim/device_sim.py`
3) Verify /devices and /devices/{id}.

# Concurrency sweep
Run loadgen with CONC=10,50,100,200 (TOTAL=5000). Compute p50/p95/p99 from CSVs.

# Impairments
`./scripts/netem.sh add 100ms 10%` → start 100 devices (60s). Observe:
- client retries (exponential backoff + jitter),
- 409 duplicates for retried Idempotency-Key,
- successful eventual ACKs.

# ETag bandwidth
Call /policies/pricing twice; compare bytes (with vs without 304).

# WSGI vs ASGI
Repeat sweeps on :5000 vs :8000; compare latency distributions + throughput.
