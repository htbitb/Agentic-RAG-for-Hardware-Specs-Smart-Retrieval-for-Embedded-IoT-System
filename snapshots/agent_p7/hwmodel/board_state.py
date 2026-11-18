"""Board State (W2): bản sao số của bo mạch, lưu theo kiểu event-sourced.

Mỗi thay đổi là một sự kiện bất biến `events(project_id, version, ts, actor, type, payload_json)`; trạng thái = fold thuần các sự kiện
(không đọc DB, không đọc đồng hồ). `rollback(v)` là một sự kiện mới (`rolled_back`) nên lịch sử không bao giờ bị xoá.
Kiểm tra nghiệp vụ (AF, giới hạn, mức logic) KHÔNG nằm ở đây: server `board-state` kiểm trước khi ghi, DRC (drc.py) kiểm trạng thái.

Module chỉ dành cho agent (`eval.tools.freeze_hwmodel.AGENT_ONLY`): grader không import nó.
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import data

SECTIONS = ("targets", "clock", "pins", "peripherals", "devices", "nets", "requirements", "decisions", "artifacts")
EVENT_TYPES = ("target_set", "requirements_set", "pin_allocated", "pin_released", "clock_configured", "device_added", "net_connected",
               "decision_recorded", "artifact_recorded", "rolled_back")
DB_ENV = "BOARD_STATE_DB"


class VersionConflict(RuntimeError):
    """Người khác đã ghi sự kiện mới giữa lúc đọc trạng thái và lúc ghi (optimistic concurrency)."""


def default_db_path() -> Path:
    raw = os.environ.get(DB_ENV, "").strip()
    return Path(raw) if raw else data.data_dir() / "board_state.sqlite"


# ------------------------------------------------------------------------------------------------ fold thuần
def empty_state(project_id: str) -> dict:
    return {"project_id": project_id, "version": 0, "targets": [], "clock": None, "pins": {}, "peripherals": {}, "devices": [], "nets": [],
            "requirements": [], "decisions": [], "artifacts": []}


def _upsert(items: list, key: str, new: dict) -> None:
    for i, it in enumerate(items):
        if it.get(key) == new.get(key):
            items[i] = new
            return
    items.append(new)


def _refresh_clock_gates(s: dict) -> None:
    """`clock_enabled` của ngoại vi: True/False khi cấu hình clock có khai báo danh sách bật clock; None = chưa khai báo (không đoán)."""
    enabled = (s["clock"] or {}).get("enabled_peripherals")
    for name, per in s["peripherals"].items():
        per["clock_enabled"] = None if enabled is None else name in enabled


def _add_peripheral_pin(s: dict, p: dict) -> None:
    name = p.get("peripheral")
    if not name:
        return
    per = s["peripherals"].setdefault(name, {"owners": [], "signals": {}, "clock_enabled": None, "config_ref": None})
    if p["owner"] not in per["owners"]:
        per["owners"].append(p["owner"])
    per["signals"][p["pin"]] = p["signal"]
    # chủ phụ của chân dùng chung cũng dùng ngoại vi đó
    for extra in p.get("_shared_with", []):
        if extra not in per["owners"]:
            per["owners"].append(extra)


def _drop_pin_from_peripherals(s: dict, pin: str) -> None:
    for name in list(s["peripherals"]):
        per = s["peripherals"][name]
        per["signals"].pop(pin, None)
        if not per["signals"]:
            del s["peripherals"][name]
        else:
            owners = []
            for q in per["signals"]:
                rec = s["pins"].get(q)
                if rec:
                    owners += [o for o in [rec["owner"], *rec["shared_with"]] if o not in owners]
            per["owners"] = owners


def apply_event(state: dict, ev: dict, past: list | None = None) -> dict:
    """Trả về trạng thái mới (không sửa `state`). `past[i]` = trạng thái ở version i, chỉ cần cho `rolled_back`."""
    t, p, v = ev["type"], ev["payload"], ev["version"]
    if t not in EVENT_TYPES:
        raise ValueError(f"unknown event type {t!r}")
    if t == "rolled_back":
        to = p.get("to_version")
        if not isinstance(to, int) or isinstance(to, bool) or not 0 <= to < v or past is None or to >= len(past):
            raise ValueError(f"rolled_back.to_version must be an earlier version (0 <= to_version < {v}), got {to!r}")
        s = copy.deepcopy(past[to])
        s["version"] = v
        return s
    s = copy.deepcopy(state)
    s["version"] = v
    if t == "target_set":
        _upsert(s["targets"], "chip", {"chip": p["chip"], "package": p.get("package"), "vdd": p.get("vdd")})
    elif t == "requirements_set":
        for r in p["requirements"]:
            _upsert(s["requirements"], "id", copy.deepcopy(r))
    elif t == "pin_allocated":
        pin = p["pin"]
        cur = s["pins"].get(pin)
        if cur and p.get("shared") and cur["signal"] == p["signal"] and p["owner"] != cur["owner"]:
            if p["owner"] not in cur["shared_with"]:
                cur["shared_with"].append(p["owner"])
        else:
            s["pins"][pin] = {"chip": p.get("chip"), "signal": p["signal"], "af": p.get("af"), "owner": p["owner"], "mode": p.get("mode"), "shared_with": []}
        per = p.get("peripheral")
        if per:
            q = {"pin": pin, "peripheral": per, "signal": p["signal"], "owner": p["owner"], "_shared_with": s["pins"][pin]["shared_with"]}
            _add_peripheral_pin(s, q)
        _refresh_clock_gates(s)
    elif t == "pin_released":
        s["pins"].pop(p["pin"], None)
        _drop_pin_from_peripherals(s, p["pin"])
    elif t == "clock_configured":
        s["clock"] = {**copy.deepcopy(p["cfg"]), "derived": copy.deepcopy(p.get("derived", {})), "violations": copy.deepcopy(p.get("violations", []))}
        _refresh_clock_gates(s)
    elif t == "device_added":
        _upsert(s["devices"], "id", copy.deepcopy(p["device"]))
    elif t == "net_connected":
        net = copy.deepcopy(p["net"])
        for i, n in enumerate(s["nets"]):
            if (n["from"], n["to"], n["kind"]) == (net["from"], net["to"], net["kind"]):
                s["nets"][i] = net
                break
        else:
            s["nets"].append(net)
    elif t == "decision_recorded":
        _upsert(s["decisions"], "id", copy.deepcopy(p["decision"]))
    elif t == "artifact_recorded":
        _upsert(s["artifacts"], "file", copy.deepcopy(p["artifact"]))
    return s


def history(project_id: str, events: list[dict]) -> list[dict]:
    """[trạng thái ở version 0, 1, ..., n]. Sự kiện phải có version liên tiếp từ 1."""
    states = [empty_state(project_id)]
    for i, ev in enumerate(events, start=1):
        if ev["version"] != i:
            raise ValueError(f"events must have consecutive versions starting at 1: expected version {i}, got {ev['version']}")
        states.append(apply_event(states[-1], ev, states))
    return states


def fold(project_id: str, events: list[dict]) -> dict:
    return history(project_id, events)[-1]


# ------------------------------------------------------------------------------------------------ diff
_KEYS = {"targets": "chip", "devices": "id", "requirements": "id", "decisions": "id", "artifacts": "file"}


def _changed_fields(a: dict, b: dict) -> list[str]:
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def diff(a: dict, b: dict) -> list[dict]:
    """Thay đổi NỘI DUNG từ trạng thái a sang b (bỏ qua `version`, `project_id`). Mỗi phần tử: section, op (added|removed|changed), key, before/after."""
    out: list[dict] = []

    def compare(section: str, ma: dict, mb: dict) -> None:
        for k in sorted(ma.keys() | mb.keys(), key=str):
            if k not in ma:
                out.append({"section": section, "op": "added", "key": k, "after": mb[k]})
            elif k not in mb:
                out.append({"section": section, "op": "removed", "key": k, "before": ma[k]})
            elif ma[k] != mb[k]:
                out.append({"section": section, "op": "changed", "key": k, "fields": _changed_fields(ma[k], mb[k]), "before": ma[k], "after": mb[k]})

    compare("targets", {t["chip"]: t for t in a["targets"]}, {t["chip"]: t for t in b["targets"]})
    if a["clock"] != b["clock"]:
        ca, cb = a["clock"], b["clock"]
        if ca is None or cb is None:
            out.append({"section": "clock", "op": "added" if ca is None else "removed", "key": "clock", **({"after": cb} if ca is None else {"before": ca})})
        else:
            out.append({"section": "clock", "op": "changed", "key": "clock", "fields": _changed_fields(ca, cb), "before": ca, "after": cb})
    compare("pins", a["pins"], b["pins"])
    compare("peripherals", a["peripherals"], b["peripherals"])
    compare("devices", {x["id"]: x for x in a["devices"]}, {x["id"]: x for x in b["devices"]})
    net_key = lambda n: f"{n['from']} -> {n['to']} ({n['kind']})"        # noqa: E731
    compare("nets", {net_key(n): n for n in a["nets"]}, {net_key(n): n for n in b["nets"]})
    compare("requirements", {x["id"]: x for x in a["requirements"]}, {x["id"]: x for x in b["requirements"]})
    compare("decisions", {x["id"]: x for x in a["decisions"]}, {x["id"]: x for x in b["decisions"]})
    compare("artifacts", {x["file"]: x for x in a["artifacts"]}, {x["file"]: x for x in b["artifacts"]})
    return out


# ------------------------------------------------------------------------------------------------ kiểm payload trước khi ghi
def _is_str(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _check_payload(type_: str, p: dict) -> None:
    """Hình dạng tối thiểu để `apply_event` chạy được; nghiệp vụ (AF, giới hạn...) vẫn do server kiểm. Ném ValueError."""
    def need(ok: bool, what: str) -> None:
        if not ok:
            raise ValueError(f"invalid {type_} payload: {what}")

    if type_ == "target_set":
        need(_is_str(p.get("chip")), "`chip` must be a non-empty string")
        need(p.get("package") is None or isinstance(p["package"], str), "`package` must be a string or null")
        need(p.get("vdd") is None or (isinstance(p["vdd"], (int, float)) and not isinstance(p["vdd"], bool)), "`vdd` must be a number or null")
    elif type_ == "requirements_set":
        reqs = p.get("requirements")
        need(isinstance(reqs, list) and all(isinstance(r, dict) and _is_str(r.get("id")) for r in reqs), "`requirements` must be a list of objects with a string `id`")
    elif type_ == "pin_allocated":
        need(all(_is_str(p.get(k)) for k in ("pin", "signal", "owner")), "`pin`, `signal` and `owner` must be non-empty strings")
    elif type_ == "pin_released":
        need(_is_str(p.get("pin")), "`pin` must be a non-empty string")
    elif type_ == "clock_configured":
        need(isinstance(p.get("cfg"), dict), "`cfg` must be an object")
    elif type_ == "device_added":
        need(isinstance(p.get("device"), dict) and _is_str(p["device"].get("id")), "`device` must be an object with a string `id`")
    elif type_ == "net_connected":
        need(isinstance(p.get("net"), dict) and all(_is_str(p["net"].get(k)) for k in ("from", "to", "kind")), "`net` must have string `from`, `to` and `kind`")
    elif type_ == "decision_recorded":
        need(isinstance(p.get("decision"), dict) and p["decision"].get("id") is not None, "`decision` must be an object with an `id`")
    elif type_ == "artifact_recorded":
        need(isinstance(p.get("artifact"), dict) and _is_str(p["artifact"].get("file")), "`artifact` must be an object with a string `file`")


# ------------------------------------------------------------------------------------------------ lưu trữ
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  project_id TEXT NOT NULL, version INTEGER NOT NULL, ts TEXT NOT NULL, actor TEXT NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY(project_id, version));
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events
WHEN EXISTS (SELECT 1 FROM events WHERE project_id = NEW.project_id AND version = NEW.version)
BEGIN SELECT RAISE(ABORT, 'events is append-only: version already exists'); END;
"""


class EventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
        finally:
            con.close()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def head(self, project_id: str) -> int:
        con = self._connect()
        try:
            return con.execute("SELECT COALESCE(MAX(version), 0) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
        finally:
            con.close()

    @staticmethod
    def _read(con: sqlite3.Connection, project_id: str, upto: int | None = None) -> list[dict]:
        q = "SELECT version, ts, actor, type, payload_json FROM events WHERE project_id=?" + (" AND version<=?" if upto is not None else "") + " ORDER BY version"
        rows = con.execute(q, (project_id, upto) if upto is not None else (project_id,)).fetchall()
        return [{"version": v, "ts": ts, "actor": a, "type": t, "payload": json.loads(pj)} for v, ts, a, t, pj in rows]

    def events(self, project_id: str, upto: int | None = None) -> list[dict]:
        con = self._connect()
        try:
            return self._read(con, project_id, upto)
        finally:
            con.close()

    def projects(self) -> list[str]:
        con = self._connect()
        try:
            return [r[0] for r in con.execute("SELECT DISTINCT project_id FROM events ORDER BY project_id")]
        finally:
            con.close()

    def append(self, project_id: str, type_: str, payload: dict, actor: str = "agent", expected_version: int | None = None) -> int:
        """Ghi một sự kiện. Payload sai hình dạng hoặc làm `apply_event` ném (vd rolled_back tới version chưa có) bị TỪ CHỐI bằng ValueError
        và không ghi gì: log không bao giờ chứa sự kiện không phát lại được."""
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type_!r}")
        if not isinstance(payload, dict):
            raise ValueError(f"event payload must be an object, got {type(payload).__name__}")
        try:
            blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"event payload is not JSON-serialisable: {exc}") from exc
        stored = json.loads(blob)
        _check_payload(type_, stored)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            head = con.execute("SELECT COALESCE(MAX(version), 0) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            if expected_version is not None and head != expected_version:
                con.execute("ROLLBACK")
                raise VersionConflict(f"project {project_id!r} is at version {head}, writer expected {expected_version}")
            past = history(project_id, self._read(con, project_id))
            try:
                apply_event(past[-1], {"version": head + 1, "type": type_, "payload": stored}, past)
            except ValueError:
                con.execute("ROLLBACK")
                raise
            except Exception as exc:                                    # KeyError/TypeError/AttributeError do payload thiếu trường
                con.execute("ROLLBACK")
                raise ValueError(f"invalid {type_} payload: {type(exc).__name__}: {exc}") from exc
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            con.execute("INSERT INTO events(project_id, version, ts, actor, type, payload_json) VALUES (?,?,?,?,?,?)", (project_id, head + 1, ts, actor, type_, blob))
            con.execute("COMMIT")
            return head + 1
        except sqlite3.Error:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()


class Board:
    """Mặt tiền cho một project: đọc trạng thái / snapshot / diff / rollback trên EventStore."""

    def __init__(self, store: EventStore, project_id: str):
        self.store, self.project_id = store, project_id

    def head(self) -> int:
        return self.store.head(self.project_id)

    def append(self, type_: str, payload: dict, actor: str = "agent", expected_version: int | None = None) -> int:
        return self.store.append(self.project_id, type_, payload, actor=actor, expected_version=expected_version)

    def state(self, version: int | None = None) -> dict:
        events = self.store.events(self.project_id)
        states = history(self.project_id, events)
        if version is None:
            return states[-1]
        if not isinstance(version, int) or isinstance(version, bool) or not 0 <= version < len(states):
            raise ValueError(f"unknown version {version!r}: project {self.project_id!r} has versions 0..{len(states) - 1}")
        return states[version]

    snapshot = state

    def diff(self, v1: int, v2: int) -> dict:
        a, b = self.state(v1), self.state(v2)
        changes = diff(a, b)
        return {"project_id": self.project_id, "from": v1, "to": v2, "changes": changes,
                "summary": {s: sum(1 for c in changes if c["section"] == s) for s in SECTIONS if any(c["section"] == s for c in changes)}}

    def rollback(self, version: int, actor: str = "agent", reason: str = "") -> int:
        head = self.head()
        if not isinstance(version, int) or isinstance(version, bool) or not 0 <= version <= head:
            raise ValueError(f"unknown version {version!r}: project {self.project_id!r} has versions 0..{head}")
        return self.append("rolled_back", {"to_version": version, "reason": reason}, actor=actor, expected_version=head)
