import time, hashlib, json
def ack_token(payload: dict) -> str:
    s = json.dumps(payload, sort_keys=True, separators=(",",":"))
    return hashlib.sha256(f"{s}|{int(time.time()*1000)}".encode()).hexdigest()
