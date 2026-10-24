"""Checkpoint SQLite của runtime v3: trạng thái mới nhất của mỗi run + phiên (lịch sử các lượt, kế hoạch) theo project_id.

Ghi sau MỖI bước (`save`); `resume` chỉ cần bản mới nhất. Tệp là SQLite thường (đường dẫn qua env AGENT_CHECKPOINT_DB), bền qua kill tiến trình.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from agent.runtime.state import TERMINAL, WAITING, AgentState


class CheckpointStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, project_id TEXT, turn INTEGER, status TEXT, updated REAL, state TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS sessions(project_id TEXT PRIMARY KEY, history TEXT, plan TEXT, updated REAL)")
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self.con.close()

    # ------------------------------------------------------------------ run
    def save(self, state: AgentState) -> None:
        with self._lock:
            self.con.execute("INSERT OR REPLACE INTO runs(run_id, project_id, turn, status, updated, state) VALUES(?,?,?,?,?,?)",
                             (state.run_id, state.project_id, state.turn, state.status, time.time(), state.to_json()))

    def load(self, run_id: str) -> AgentState | None:
        with self._lock:
            row = self.con.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return AgentState.from_json(row[0]) if row else None

    def unfinished_runs(self) -> list[str]:
        """Run bị dừng giữa chừng (kill): không phải run đã xong và không phải run đang chờ người trả lời (xem `waiting_runs`)."""
        skip = (*TERMINAL, *WAITING)
        marks = ",".join("?" * len(skip))
        with self._lock:
            rows = self.con.execute(f"SELECT run_id FROM runs WHERE status NOT IN ({marks}) ORDER BY updated", skip).fetchall()
        return [r[0] for r in rows]

    def waiting_runs(self, project_id: str | None = None) -> list[str]:
        """Run đang INTERRUPTED (chờ `resume(run_id, interrupt_id, decision, payload)`)."""
        with self._lock:
            rows = self.con.execute("SELECT run_id FROM runs WHERE status='INTERRUPTED' AND (? IS NULL OR project_id=?) ORDER BY updated", (project_id, project_id)).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------ phiên (nhiều lượt trên cùng project_id)
    def session(self, project_id: str) -> dict:
        with self._lock:
            row = self.con.execute("SELECT history, plan FROM sessions WHERE project_id=?", (project_id,)).fetchone()
        return {"history": json.loads(row[0]), "plan": json.loads(row[1])} if row else {"history": [], "plan": []}

    def save_session(self, project_id: str, history: list, plan: list) -> None:
        with self._lock:
            self.con.execute("INSERT OR REPLACE INTO sessions(project_id, history, plan, updated) VALUES(?,?,?,?)",
                             (project_id, json.dumps(history, ensure_ascii=False, default=str), json.dumps(plan, ensure_ascii=False), time.time()))

    def next_turn(self, project_id: str) -> int:
        return len(self.session(project_id)["history"])
