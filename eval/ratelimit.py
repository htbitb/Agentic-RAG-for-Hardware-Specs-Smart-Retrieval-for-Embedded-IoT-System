"""Giới hạn tốc độ gọi LLM dùng chung giữa các luồng VÀ các tiến trình (S0 trong runner, S1/S2 trong tiến trình con).

Khoảng cách tối thiểu 60/rpm giây giữa hai lời gọi API bất kỳ, điều phối bằng flock trên một file trạng thái.
Chỉ dùng thư viện chuẩn để cả native-RAG/.venv lẫn worker S2 đều nạp được.
"""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path


class FileRateLimiter:
    def __init__(self, path, rpm: float):
        self.path = Path(path)
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0

    def acquire(self) -> None:
        if not self.interval:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            raw = os.pread(fd, 64, 0).decode().strip()
            nxt = float(raw) if raw else 0.0
            now = time.time()
            start = max(now, nxt)
            os.pwrite(fd, f"{start + self.interval:.6f}".ljust(32).encode(), 0)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        wait = start - time.time()
        if wait > 0:
            time.sleep(wait)


def from_env() -> FileRateLimiter | None:
    """Tạo limiter từ biến môi trường EVAL_LLM_RPM / EVAL_RATE_FILE (đặt bởi runner cho tiến trình con)."""
    rpm = float(os.environ.get("EVAL_LLM_RPM", "0") or 0)
    path = os.environ.get("EVAL_RATE_FILE", "")
    return FileRateLimiter(path, rpm) if rpm > 0 and path else None
