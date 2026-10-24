"""Tiến trình con giao tiếp JSONL (một dòng JSON mỗi thông điệp) với timeout, dùng cho adapter S1 và S2."""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path


class ProcessCrash(Exception):
    pass


class ProcessTimeout(Exception):
    pass


class JsonlProcess:
    def __init__(self, cmd, env: dict, cwd: str | Path | None = None, log_path: str | Path | None = None):
        self.cmd, self.env, self.cwd, self.log_path = list(cmd), env, cwd, log_path
        self._proc: subprocess.Popen | None = None
        self._buf = b""

    @property
    def pid(self):
        return self._proc.pid if self._proc else None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        self.kill()
        log = subprocess.DEVNULL
        if self.log_path:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            log = open(self.log_path, "ab")
        self._proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0,
                                      cwd=str(self.cwd) if self.cwd else None, env=self.env)
        self._buf = b""

    def kill(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass

    def close_stdin(self) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass

    def write(self, obj: dict) -> None:
        try:
            self._proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        except (BrokenPipeError, OSError, AttributeError):
            raise ProcessCrash()

    def readline(self, timeout: float) -> str:
        fd = self._proc.stdout.fileno()
        deadline = time.time() + timeout
        while b"\n" not in self._buf:
            left = deadline - time.time()
            if left <= 0:
                raise ProcessTimeout()
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                if self._proc.poll() is not None:
                    raise ProcessCrash()
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise ProcessCrash()
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", "replace")

    def request(self, obj: dict, timeout: float) -> dict:
        if not self.alive():
            raise ProcessCrash()
        self.write(obj)
        try:
            return json.loads(self.readline(timeout))
        except json.JSONDecodeError:
            raise ProcessCrash()
