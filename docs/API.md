### Health
`GET /healthz` → `{"status":"ok","ts": "...Z"}`

### Register device (idempotent)
`POST /devices {"id":"bike-001","name":"Bike 001"}` → 201 Created (first) / 200 OK (repeat)

### Telemetry (ARQ with Idempotency-Key)
`POST /devices/bike-001/telemetry` headers: `Idempotency-Key: <hash>` body: `{"seq":1,"lat":10,"lon":10,"battery":95,"lock_state":"locked"}`
→ 201 `{"ack":"...token..."}`; repeating same key → 409 `{"nack":"duplicate","ack":"...same..."}`

### Policies with ETag/304
1. `GET /policies/geofences` → `ETag: <hash>`
2. `GET /policies/geofences` with `If-None-Match: <hash>` → 304

### Rate limiting (writes)
Exceed bucket → 429 + `Retry-After: <seconds>`.

### Pagination
`GET /devices/bike-001/history?limit=5&page=1` → `{items:[...], next_page:2}`
