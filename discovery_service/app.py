
from fastapi import FastAPI, Query, HTTPException
from common.db import get_conn, init_db, nearest_bike

app = FastAPI(title="Discovery Service")
init_db()

@app.get("/discovery/nearest")
def nearest(lat: float = Query(...), lon: float = Query(...), radius: int = Query(500)):
    row = nearest_bike(get_conn(), lat, lon, radius_m=radius)
    if not row:
        raise HTTPException(status_code=404, detail="no bike in radius")
    return row
