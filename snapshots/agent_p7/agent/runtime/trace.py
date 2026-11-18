"""Trace chuẩn hoá của runtime v2 (plan/P4_interfaces.md §4): tiện ích rút gọn dữ liệu cho sự kiện + ghi JSONL."""
from __future__ import annotations

import json
from pathlib import Path


def clip(obj, n: int = 400) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + " ..."


def compact_effect(e: dict) -> dict:
    keep = ("kind", "pin", "signal", "timer", "channel", "pwm_hz", "duty_pct", "instance", "baud", "scl_hz", "scl_pin", "sda_pin", "tx_pin", "rx_pin", "active", "reason", "modeled")
    return {k: e[k] for k in keep if k in e and e[k] is not None}


def write_jsonl(trace_dir, run_id: str, events: list[dict]) -> Path:
    path = Path(trace_dir) / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in events), encoding="utf-8")
    return path
