"""Monitoring & audit logging (R6 / AT4). Append-only JSONL, secrets redacted."""
import json
import re
import threading
import time
import uuid

import config

_lock = threading.Lock()
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|(?i:api[_-]?key)\s*[=:]\s*\S+)")


def redact(obj):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return json.loads(_SECRET.sub("[REDACTED]", s))


def log(event: str, **details) -> str:
    rec = {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **redact(details)}
    with _lock, open(config.AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec["id"]


def tail(n: int = 50) -> list[dict]:
    if not config.AUDIT_LOG.exists():
        return []
    lines = config.AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except json.JSONDecodeError:  # line still being written by another thread
            continue
    return out
