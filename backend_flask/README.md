# Backend A (Flask + Gunicorn)
- HTTP/1.1 REST, JSON, explicit headers (X-Trace-Id, Idempotency-Key, ETag, Retry-After).
- Token-bucket rate limiting (writes) → 429.
- ARQ with idempotency table → 409 NACK for duplicates.
- ETag + 304 on /policies/*.
