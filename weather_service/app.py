
from fastapi import FastAPI, Query
import time

app = FastAPI(title="Weather Service")

CONDITIONS = [
    ("clear", 1.0),
    ("windy", 0.9),
    ("rain", 0.8),
    ("heavy_rain", 0.7)
]

@app.get("/weather")
def weather(lat: float = Query(...), lon: float = Query(...)):
    period = 15*60
    t = int(time.time()) % (period*len(CONDITIONS))
    idx = t // period
    cond, factor = CONDITIONS[idx]
    return {"condition": cond, "speed_factor": factor}
