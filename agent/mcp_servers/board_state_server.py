"""board-state MCP Server (W2, quyền `state-mutating` cho tool ghi, `read-only` cho tool chỉ đọc): "thế giới" có trạng thái của agent.

Bản sao số của bo mạch lưu event-sourced theo `project_id` (SQLite, env BOARD_STATE_DB; project mặc định env BOARD_STATE_PROJECT hoặc "default").
Phản hồi luôn là DỮ LIỆU CÓ CẤU TRÚC: `{"ok": true, ...}` hoặc `{"ok": false, "error": {"code", "message", ...}}` — lỗi có mã và, khi có, PHƯƠNG ÁN THAY THẾ
lấy từ bảng AF / giới hạn của P1. Quy ước ghi: *cấp phát chân* và *kết nối* vi phạm ràng buộc cứng bị TỪ CHỐI (không ghi sự kiện, `recorded: false`);
*cấu hình clock* được ghi kèm danh sách vi phạm (để DRC-CLK-01 và cổng `finish` thấy cho tới khi sửa).
P3 chưa đăng ký server này vào ToolHub của agent (S2D là snapshot P1); P4 sẽ làm.
"""
import functools
import json
import math
import os
import re

import config

os.environ.setdefault("HWMODEL_DATA_DIR", str(config.HW_DB.parent))
os.environ.setdefault("BOARD_STATE_DB", str(config.BOARD_STATE_DB))

from hwmodel import board_state as bsm                                      # noqa: E402
from hwmodel import drc                                                       # noqa: E402
from mcp_servers import create_mcp                                           # noqa: E402
from mcp_servers.hw_queries import HwStore                                   # noqa: E402

mcp = create_mcp("board-state")
ACTOR = "agent"
REQ_STATUSES = ("pending", "satisfied", "waived")
DECISION_BY = ("agent", "human")
_HW: HwStore | None = None
_STORES: dict = {}


# ------------------------------------------------------------------------------------------------ nền
def _cat() -> drc.Catalog:
    global _HW
    if _HW is None:
        _HW = HwStore()
    return drc.Catalog(_HW)


class _Refuse(Exception):
    """Lỗi cấu trúc phát hiện sâu trong hàm phụ trợ; `_tool` đổi nó thành phản hồi `{"ok": false, ...}`."""

    def __init__(self, err: dict):
        super().__init__(err["error"]["message"])
        self.err = err


def _tool(fn):
    """Đăng ký MCP tool; mọi lỗi dự kiến là DỮ LIỆU (`ok: false`), không phải ngoại lệ."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _Refuse as exc:
            return exc.err
    return mcp.tool()(wrapper)


def _err(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def _board(project_id: str | None) -> bsm.Board:
    if project_id is not None and project_id != "" and (not isinstance(project_id, str) or not project_id.strip()):
        raise _Refuse(_err("INVALID_PROJECT_ID", f"project_id must be a non-blank string (or omitted), got {project_id!r}"))
    path = str(bsm.default_db_path())
    if path not in _STORES:
        _STORES[path] = bsm.EventStore(path)
    pid = (project_id or os.environ.get("BOARD_STATE_PROJECT") or "default").strip() or "default"
    return bsm.Board(_STORES[path], pid)


def _json_arg(value, kind: type, what: str):
    """Tham số có thể là đối tượng hoặc chuỗi JSON (LLM hay gửi chuỗi). Trả (giá trị, None) hoặc (None, lỗi)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            return None, f"{what} is not valid JSON: {exc}"
    if not isinstance(value, kind):
        return None, f"{what} must be a {kind.__name__}, got {type(value).__name__}"
    return value, None


def _append(board: bsm.Board, type_: str, payload: dict, expected: int) -> int | dict:
    try:
        return board.append(type_, payload, actor=os.environ.get("BOARD_STATE_ACTOR", ACTOR), expected_version=expected)
    except bsm.VersionConflict as exc:
        return _err("VERSION_CONFLICT", str(exc) + " - read the state again and retry")


def _target(state: dict, chip: str | None = None) -> dict | None:
    if chip:
        return next((t for t in state["targets"] if t["chip"] == chip), None)
    return state["targets"][0] if state["targets"] else None


def _resolve_pin(state: dict, pin: str):
    """'PA8' hoặc '<chip>.PA8' -> (target, tên chân)."""
    head, dot, rest = pin.partition(".")
    if dot and any(head.lower() == t["chip"].lower() for t in state["targets"]):
        return next(t for t in state["targets"] if head.lower() == t["chip"].lower()), rest
    return _target(state), pin


# ------------------------------------------------------------------------------------------------ đọc
@_tool
def get_board_state(section: str | None = None, version: int | None = None, project_id: str | None = None) -> dict:
    """Read the Board State of the project (the digital twin of the board): targets, clock (+derived frequencies), pins (signal, AF, owner), peripherals, devices, nets, requirements, decisions, artifacts. `section` returns only one part; `version` returns the snapshot at that version (default: latest). The state is the fold of an append-only event log, so every earlier version stays readable."""
    b = _board(project_id)
    head = b.head()
    try:
        st = b.state(version)
    except ValueError as exc:
        return _err("NO_SUCH_VERSION", str(exc), head=head)
    out = {"ok": True, "project_id": b.project_id, "version": st["version"], "head": head}
    if section is None:
        return {**out, "state": st}
    if section not in bsm.SECTIONS:
        return _err("NO_SUCH_SECTION", f"unknown section {section!r}", sections=list(bsm.SECTIONS))
    return {**out, "section": section, "data": st[section]}


@_tool
def get_power_budget(mode: str, project_id: str | None = None) -> dict:
    """Total supply current (uA) in a power mode (e.g. 'sleep', 'active', 'hibernation') against the budget from a `power` requirement ({type: 'power', mode, budget_ua}). Device currents come from add_device (`i_ua_by_mode[mode]`, or `i_typ_ua` for 'active'); the MCU current is used ONLY when exactly one database row matches the mode. Missing figures give status 'unknown' (never 'ok'); status 'exceeded' means the known part alone is already above the budget."""
    if not isinstance(mode, str) or not mode.strip():
        return _err("INVALID_ARGUMENT", "mode must be a non-empty string such as 'sleep' or 'active'")
    st = _board(project_id).state()
    return {"ok": True, **drc.power_budget(st, mode.strip(), _cat())}


@_tool
def run_drc(project_id: str | None = None) -> dict:
    """Run all design rules on the current Board State: DRC-PIN-01 (one owner per pin, declared shared buses allowed), DRC-PIN-02 (signal in the pin's alternate-function table, pin in the package), DRC-PIN-03 (no output on input-only pins), DRC-CLK-01 (derived clock frequencies within limits), DRC-CLK-02 (used peripherals have their RCC clock enabled), DRC-ELEC-01 (logic levels across voltage domains, 5 V on non-FT pins), DRC-PWR-01 (current budget per mode), DRC-REQ-01 (requirements satisfied or waived with a reason). Returns violations with codes (severity error | warning | unknown) and alternatives; `ok` is true only without errors, `complete` only without unknowns."""
    b = _board(project_id)
    return drc.run_drc(b.state(), _cat())


@_tool
def diff(v1: int, v2: int, project_id: str | None = None) -> dict:
    """Difference between two versions of the Board State: added / removed / changed entries per section (targets, clock, pins, peripherals, devices, nets, requirements, decisions, artifacts) with before/after values."""
    b = _board(project_id)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (v1, v2)):
        return _err("INVALID_ARGUMENT", f"v1 and v2 must be integer versions, got {v1!r} and {v2!r}", head=b.head())
    try:
        return {"ok": True, **b.diff(v1, v2)}
    except ValueError as exc:
        return _err("NO_SUCH_VERSION" if isinstance(v1, int) and isinstance(v2, int) else "INVALID_ARGUMENT", str(exc), head=b.head())


# ------------------------------------------------------------------------------------------------ ghi
@_tool
def set_target(chip: str, package: str | None, vdd: float, project_id: str | None = None) -> dict:
    """Declare the MCU of the design: chip (stm32g474, esp32, nrf52840), package (e.g. LQFP64; used to offer only pins that exist in it) and supply voltage VDD. Warns (does not refuse) when VDD is outside the recommended operating range of the datasheet or the package is unknown. A second call for the same chip replaces its entry."""
    cat = _cat()
    c = cat.chip(chip)
    if c is None:
        return _err("UNKNOWN_CHIP", f"unknown chip {chip!r}", chips=cat.hw._chips)
    if not _num(vdd) or not 0 < vdd <= 60:
        return _err("INVALID_TARGET", f"vdd must be a finite number of volts in (0, 60], got {vdd!r}")
    if package is not None and (not isinstance(package, str) or not package.strip()):
        return _err("INVALID_TARGET", f"package must be a non-empty string or null, got {package!r}")
    warnings = []
    rows = [dict(r) for r in cat.hw.conn.execute(
        "SELECT * FROM electrical_limits WHERE chip=? AND field_type='supply_voltage' AND category IN ('recommended_operating','absolute_max') ORDER BY id", (c,))]
    rec = next((r for r in rows if r["category"] == "recommended_operating"), None)
    ab = next((r for r in rows if r["category"] == "absolute_max"), None)
    if rec and rec["min"] not in (None, "") and rec["max"] not in (None, ""):
        lo, hi = float(rec["min"]), float(rec["max"])
        if not lo - 1e-9 <= vdd <= hi + 1e-9:
            w = {"code": "VDD_OUT_OF_RANGE", "vdd": vdd, "min": lo, "max": hi, "evidence": {"doc": rec["doc"], "page": rec["page"]},
                 "message": f"VDD = {vdd:g} V is outside the recommended operating range {lo:g}-{hi:g} V ({rec['doc']} p.{rec['page']})"}
            if ab and ab["max"] not in (None, "") and vdd > float(ab["max"]):
                w["above_absolute_max"] = float(ab["max"])
                w["message"] += f"; it is above the absolute maximum {float(ab['max']):g} V (p.{ab['page']}): the part can be damaged"
            warnings.append(w)
    known = sorted({k for (pk,) in cat.hw.conn.execute("SELECT packages FROM pins WHERE chip=? AND packages IS NOT NULL", (c,)) for k in json.loads(pk)})
    if package is not None and known and package not in known:
        warnings.append({"code": "UNKNOWN_PACKAGE", "package": package, "known_packages": known,
                         "message": f"package {package!r} is not in the pin tables of {c}; pin availability cannot be checked"})
    b = _board(project_id)
    st = b.state()
    v = _append(b, "target_set", {"chip": c, "package": package, "vdd": float(vdd)}, st["version"])
    if isinstance(v, dict):
        return v
    return {"ok": True, "version": v, "target": {"chip": c, "package": package, "vdd": float(vdd)}, "warnings": warnings}


def _timer_contradictions(state: dict) -> list[dict]:
    """Các kênh của một timer dùng chung PSC/ARR => các yêu cầu PWM trên cùng timer phải cùng tần số."""
    by_timer: dict[str, list[dict]] = {}
    for r in state["requirements"]:
        if r.get("type") != "pwm" or not drc._finite(r.get("freq_hz")) or r["freq_hz"] <= 0:
            continue
        sig = r.get("signal") or next((p["signal"] for p in state["pins"].values() if drc._claimant(p["owner"], [r["id"]]) == r["id"] and re.match(r"TIM\d+_CH", p["signal"])), None)
        m = re.match(r"(TIM\d+)_CH\d", sig or "")
        if m:
            by_timer.setdefault(m.group(1), []).append(r)
    out = []
    for timer, rs in sorted(by_timer.items()):
        for i, a in enumerate(rs):
            for c in rs[i + 1:]:
                tol = max(*(r["tol_pct"] if drc._finite(r.get("tol_pct")) else 1.0 for r in (a, c))) / 100.0
                if abs(a["freq_hz"] - c["freq_hz"]) > tol * max(a["freq_hz"], c["freq_hz"]):
                    out.append({"code": f"TIMER_SHARED:{timer}", "requirements": [a["id"], c["id"]],
                                "message": f"{a['id']} ({a['freq_hz']:g} Hz) and {c['id']} ({c['freq_hz']:g} Hz) use channels of {timer}, which share one counter (PSC/ARR): "
                                           f"one PWM frequency per timer; use another timer for one of them"})
    return out


@_tool
def set_requirements(requirements: list[dict] | str, project_id: str | None = None) -> dict:
    """Record structured requirements (the spec), upserting by `id`. Each item needs `id` and `type` (pwm, i2c, uart, spi, adc, dac, can, gpio_out, gpio_in, clock, power, other); optional `status` (pending | satisfied | waived; default pending), `evidence` (e.g. 'sim#12'), `waiver_reason`, `shared` (true when this requirement deliberately shares a pin with another on a declared bus such as I2C, so the pin is not reported as a conflict), and type-specific keys such as pin (string)/pins (list of strings)/signal/freq_hz/duty_pct/tol_pct, instance with scl_pin/sda_pin/tx_pin/rx_pin, and for power both `mode` and a positive `budget_ua`. Field types are checked: names are strings, numbers are finite (no NaN/Infinity/booleans); if ANY item is invalid the whole call is refused (INVALID_REQUIREMENT with the list of problems) and nothing is recorded. Returns all requirements and the contradictions found (two requirements claiming one pin: PIN_CONFLICT:<pin>; PWM channels of one timer with different frequencies: TIMER_SHARED:<timer>)."""
    reqs, bad = _json_arg(requirements, list, "requirements")
    if bad:
        return _err("INVALID_REQUIREMENT", bad)
    problems = []
    for i, r in enumerate(reqs):
        label = r["id"] if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"].strip() else f"#{i}"
        problems += [f"{label}: {p}" for p in drc.validate_requirement(r)]
        if isinstance(r, dict) and not isinstance(r.get("status", "pending"), str) or isinstance(r, dict) and r.get("status", "pending") not in REQ_STATUSES:
            problems.append(f"{label}: `status` must be one of {list(REQ_STATUSES)}, got {r.get('status')!r}")
    if problems:
        return _err("INVALID_REQUIREMENT", "requirements refused, nothing recorded: " + "; ".join(problems[:6]) + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""),
                    problems=problems)
    reqs = [{**r, "id": r["id"].strip(), "status": r.get("status", "pending")} for r in reqs]
    b = _board(project_id)
    st = b.state()
    v = _append(b, "requirements_set", {"requirements": reqs}, st["version"])
    if isinstance(v, dict):
        return v
    new = b.state()
    cat = _cat()
    contradictions = [{"code": i["code"], "message": i["message"], "claims": i.get("claims")} for i in drc.rule_pin_01(new, cat)
                      if any(c["claimant"] in {r["id"] for r in new["requirements"]} for c in i.get("claims", []))] + _timer_contradictions(new)
    return {"ok": True, "version": v, "requirements": new["requirements"], "contradictions": contradictions}


def _default_mode(signal: str, input_only: bool = False) -> str | None:
    """Chế độ mặc định theo tín hiệu. Tín hiệu có hướng vào (RX, MISO...) là AF_IN, không phải AF_PP; chưa biết hướng trên chân chỉ-nhập thì để None
    (DRC-PIN-03 báo `unknown`) thay vì gán AF_PP rồi báo lỗi oan."""
    if signal in ("GPIO_OUT",):
        return "output"
    if signal in ("GPIO_IN",):
        return "input"
    if re.search(r"_(SCL|SDA)$", signal):
        return "AF_OD"
    if re.match(r"(ADC|DAC|COMP|OPAMP)\d*_", signal):
        return "ANALOG"
    direction = drc.signal_direction(signal)
    if direction == "in":
        return "AF_IN"
    return None if direction is None and input_only else "AF_PP"


@_tool
def allocate_pin(pin: str, signal: str, owner: str, mode: str | None = None, shared: bool = False, project_id: str | None = None) -> dict:
    """Assign a pin to a signal (e.g. PA8 -> TIM1_CH1) for an owner (requirement id plus a label, e.g. 'R1-motor-pwm'). Checks the pin exists in the target's package, the signal is in the pin's alternate-function table (GPIO, GPIO_IN, GPIO_OUT are always valid), the pin is not input-only for an output function, and the pin is free. Refusals are structured: CONFLICT (current owner + free pins that carry the requested signal), NO_SUCH_AF (pins that carry the signal), INPUT_ONLY, NO_SUCH_PIN, PIN_NOT_IN_PACKAGE, NO_TARGET, SHARED_NOT_BUS, SIGNAL_ALREADY_ROUTED (the same peripheral signal is already on another pin of an STM32: release_pin that one first); nothing is recorded on refusal. `shared=true` lets several owners share a pin only for a declared bus signal (I2C/SPI/CAN). Warnings: PERIPHERAL_SHARED (a timer's channels share one frequency), PIN_FLAG:strapping|flash. `mode`: output | input | AF_PP | AF_OD | AF_IN | ANALOG (default from the signal: receive-type signals such as USART RX get AF_IN; re-allocating the same pin with a different explicit mode is refused, release_pin first)."""
    if not all(isinstance(x, str) and x.strip() for x in (pin, signal, owner)):
        return _err("INVALID_ARGUMENT", "pin, signal and owner must be non-empty strings")
    b = _board(project_id)
    st = b.state()
    cat = _cat()
    tgt, pname = _resolve_pin(st, pin.strip())
    if tgt is None:
        return _err("NO_TARGET", "no target chip is set: call set_target first")
    chip, package = tgt["chip"], tgt.get("package")
    sig = signal.strip().upper()
    owner = owner.strip()
    rec = cat.pin(chip, pname)
    if rec is None:
        return _err("NO_SUCH_PIN", f"{chip} has no pin {pname!r}", suggestions=cat.hw.query_pin_alternate_function(chip, pname).get("suggestions", []))
    pid = rec["pin"]
    alternatives = lambda: cat.alternatives(chip, sig, package, taken=st["pins"])           # noqa: E731
    if cat.in_package(rec, package) is False:
        return _err("PIN_NOT_IN_PACKAGE", f"{pid} is not bonded out in package {package}", pin=pid, package=package, alternatives=alternatives())
    hit = cat.signal_af(chip, rec, sig)
    if hit is None:
        carriers = cat.hw.find_pins_for_signal(chip, sig, limit=200).get("matches", [])
        carriers = [m for m in carriers if (m.get("function") or "").upper() == sig]
        listing = []
        for m in carriers:
            r2 = cat.pin(chip, m["pin"])
            listing.append({"pin": m["pin"], "af": m["af"], "in_package": None if r2 is None else cat.in_package(r2, package), "free": m["pin"] not in st["pins"]})
        alts = alternatives()
        return _err("NO_SUCH_AF", drc._alt_message(chip, sig, pid, alts), pin=pid, signal=sig, alternatives=alts, pins_with_signal=listing,
                    evidence={"doc": rec.get("doc"), "page": rec.get("page")})
    kind, af = hit
    direction = drc.signal_direction(sig, mode)
    if rec.get("input_only") and direction in ("out", "inout"):
        if kind == "af":
            alts = [a for a in alternatives() if not (cat.pin(chip, a["pin"]) or {}).get("input_only")]
        else:
            alts = _output_capable_pins(cat, chip, package, st)
        return _err("INPUT_ONLY", f"{pid} is input-only (no output driver): it cannot carry the output function {sig}", pin=pid, signal=sig, alternatives=alts,
                    evidence=[{"doc": f["doc"], "page": f["page"], "quote": f["quote"]} for f in rec.get("flags", []) if f["kind"] == "input_only"])
    if shared and not drc.BUS_SIGNAL.match(sig):
        return _err("SHARED_NOT_BUS", f"{sig} is not a bus signal (I2C/SPI/CAN/1-Wire): only declared buses may be shared by several owners", pin=pid, signal=sig)
    cur = st["pins"].get(pid)
    if cur:
        owners = [cur["owner"], *cur["shared_with"]]
        if cur["signal"] == sig and owner in owners and (mode is None or mode == cur.get("mode")):
            return {"ok": True, "unchanged": True, "version": st["version"], "pin": pid, "signal": sig, "af": cur["af"], "owner": owner, "warnings": []}
        if not (shared and cur["signal"] == sig):
            hint = " (same owner: release_pin first to change its function)" if owner in owners else ""
            return _err("CONFLICT", f"{pid} is already allocated to {cur['owner']} as {cur['signal']}{hint}", pin=pid,
                        current={"signal": cur["signal"], "owner": cur["owner"], "af": cur["af"]}, requested={"signal": sig, "owner": owner},
                        alternatives=alternatives(), evidence={"doc": rec.get("doc"), "page": rec.get("page")})
    if sig not in drc.GENERIC_SIGNALS and not cat.flexible_routing(chip):
        elsewhere = next(((q, r) for q, r in st["pins"].items() if q != pid and r["signal"] == sig and r.get("chip") in (None, chip)), None)
        if elsewhere:
            q, r = elsewhere
            return _err("SIGNAL_ALREADY_ROUTED", f"{sig} is already routed to {q} (owner {r['owner']}): one peripheral signal drives one pin; release_pin {q} first to move it to {pid}",
                        pin=pid, signal=sig, current={"pin": q, "owner": r["owner"], "af": r["af"]}, requested={"pin": pid, "owner": owner})
    per = next((f.get("peripheral") for f in rec.get("functions", []) if (f.get("function") or "").upper() == sig), None)
    warnings = []
    others = [o for o in (st["peripherals"].get(per, {}).get("owners", []) if per else []) if o != owner]
    if others:
        timer = bool(per and per.startswith("TIM"))
        warnings.append({"code": "PERIPHERAL_SHARED", "peripheral": per, "owners": others,
                         "message": f"{per} is already used by {', '.join(others)}" + (": its channels share one counter (PSC/ARR), so they must use the same PWM frequency"
                                                                                    if timer else ": check that one instance can serve both functions")})
    for f in rec.get("flags", []):
        if f["kind"] in ("strapping", "flash"):
            warnings.append({"code": f"PIN_FLAG:{f['kind']}", "pin": pid, "message": f["note"], "evidence": {"doc": f["doc"], "page": f["page"]}})
    use_mode = mode or _default_mode(sig, bool(rec.get("input_only")))
    v = _append(b, "pin_allocated", {"pin": pid, "chip": chip, "signal": sig, "af": af, "peripheral": per if kind == "af" else None, "owner": owner,
                                      "mode": use_mode, "shared": bool(shared)}, st["version"])
    if isinstance(v, dict):
        return v
    pk = (rec.get("packages") or {}).get(package) if package else None
    return {"ok": True, "version": v, "pin": pid, "signal": sig, "af": af, "peripheral": per if kind == "af" else None, "owner": owner, "mode": use_mode,
            **({"package_pin": pk} if pk and pk != "-" else {}), "warnings": warnings}


def _output_capable_pins(cat: drc.Catalog, chip: str, package: str | None, state: dict, limit: int = 12) -> list[dict]:
    out = []
    for (pid,) in cat.hw.conn.execute("SELECT pin FROM pins WHERE chip=? AND COALESCE(input_only,0)=0 ORDER BY rowid", (chip,)):
        rec = cat.pin(chip, pid)
        if pid in state["pins"] or rec is None or cat.in_package(rec, package) is False:
            continue
        out.append({"pin": pid, "free": True})
        if len(out) >= limit:
            break
    return out


@_tool
def release_pin(pin: str, project_id: str | None = None) -> dict:
    """Free a previously allocated pin (and drop it from its peripheral). Returns NOT_ALLOCATED if the pin has no allocation."""
    if not isinstance(pin, str) or not pin.strip():
        return _err("INVALID_ARGUMENT", "pin must be a non-empty string")
    b = _board(project_id)
    st = b.state()
    tgt, pname = _resolve_pin(st, pin.strip())
    rec = _cat().pin(tgt["chip"], pname) if tgt else None
    pid = rec["pin"] if rec else pname
    if pid not in st["pins"]:
        return _err("NOT_ALLOCATED", f"{pid} is not allocated", pin=pid)
    cur = st["pins"][pid]
    v = _append(b, "pin_released", {"pin": pid}, st["version"])
    return v if isinstance(v, dict) else {"ok": True, "version": v, "pin": pid, "released": {"signal": cur["signal"], "owner": cur["owner"]}}


@_tool
def set_clock_config(cfg: dict | str, project_id: str | None = None) -> dict:
    """Configure the STM32G474 clock tree and get the derived frequencies and limit violations. cfg: {source: 'HSI16'|'HSE'|'PLL', hse_hz (required when HSE is used), pll: {source?: 'HSI16'|'HSE', m: 1-16, n: 8-127, r: 2|4|6|8}, ahb_div: 1|2|4|8|16|64|128|256|512, apb1_div / apb2_div: 1|2|4|8|16, voltage_range: 'range1_boost' (default) | 'range1_normal' | 'range2', flash_latency (default: the minimum that covers HCLK), enabled_peripherals: ['GPIOA','TIM1',...] (RCC clock enables, used by DRC-CLK-02)}. Returns derived sysclk/hclk/pclk1/pclk2/timer clocks (x2 rule applied) and violations such as CLOCK_LIMIT:SYSCLK, CLOCK_LIMIT:VCO, CLOCK_LIMIT:PLL_IN, CLOCK_LIMIT:HSE, CLOCK_LIMIT:FLASH_WS. The configuration is recorded together with its violations (ok=false) so DRC-CLK-01 keeps reporting until it is fixed."""
    c, bad = _json_arg(cfg, dict, "cfg")
    if bad:
        return _err("INVALID_CLOCK_CONFIG", bad)
    try:
        ev = drc.evaluate_clock_config(c, _cat().hw)
    except drc.ClockConfigError as exc:
        return _err("INVALID_CLOCK_CONFIG", str(exc))
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:             # lưới an toàn: cấu hình lạ không được làm sập tool
        return _err("INVALID_CLOCK_CONFIG", f"the clock configuration could not be evaluated ({type(exc).__name__}: {exc})")
    b = _board(project_id)
    st = b.state()
    if not st["targets"]:
        return _err("NO_TARGET", "no target chip is set: call set_target first")
    if drc._clock_target(st) is None:
        return _err("UNSUPPORTED_CHIP", "the clock-tree model covers STM32G474 only (D21)", targets=[t["chip"] for t in st["targets"]])
    v = _append(b, "clock_configured", {"cfg": ev["cfg"], "derived": ev["derived"], "violations": ev["violations"]}, st["version"])
    if isinstance(v, dict):
        return v
    return {"ok": not ev["violations"], "recorded": True, "version": v, "cfg": ev["cfg"], "derived": ev["derived"], "violations": ev["violations"],
            "assumptions": ev["assumptions"]}


def _num(x) -> bool:
    return drc._finite(x)


@_tool
def add_device(id: str, part: str, vdd: float, interface: str, i_typ_ua: float | None = None, io_vdd: float | None = None, vih_min: float | None = None,
               vil_max: float | None = None, voh_min: float | None = None, vol_max: float | None = None, vin_max: float | None = None,
               i_ua_by_mode: dict | None = None, io_vdd_by_pin: dict | None = None, project_id: str | None = None) -> dict:
    """Add (or update, by id) an external device: id (e.g. 'U2'), part ('BME280'), vdd (supply, V), interface ('I2C', 'SPI', 'digital', 'level_shifter'...), typical current `i_typ_ua` (uA) and/or `i_ua_by_mode` ({'sleep': 0.1, 'active': 3.6}). Logic levels for connect/DRC-ELEC-01: io_vdd (I/O rail if different from vdd), io_vdd_by_pin ({'B1': 1.8} for a level shifter whose sides sit on different rails), vih_min, vil_max, voh_min, vol_max, vin_max (absolute input maximum) in volts. Missing thresholds are ASSUMED CMOS (0.7/0.3 x VDDIO, VOH >= VDDIO-0.4 V, VOL <= 0.4 V, input max VDDIO+0.3 V) and the assumption is reported by connect/run_drc: give the datasheet values when you have them."""
    if not isinstance(id, str) or not id.strip() or "." in id:
        return _err("INVALID_DEVICE", "id must be a non-empty string without '.'")
    if not isinstance(part, str) or not part.strip() or not isinstance(interface, str) or not interface.strip():
        return _err("INVALID_DEVICE", "part and interface must be non-empty strings")
    if not _num(vdd) or not 0 < vdd <= 60:
        return _err("INVALID_DEVICE", f"vdd must be a finite number of volts in (0, 60], got {vdd!r}")
    optional = {"i_typ_ua": i_typ_ua, "io_vdd": io_vdd, "vih_min": vih_min, "vil_max": vil_max, "voh_min": voh_min, "vol_max": vol_max, "vin_max": vin_max}
    for k, val in optional.items():
        if val is None:
            continue
        if not _num(val):
            return _err("INVALID_DEVICE", f"{k} must be a finite number, got {val!r}")
        if (k == "i_typ_ua" and val < 0) or (k in ("io_vdd", "vin_max") and not 0 < val <= 60) or (k in ("vih_min", "vil_max", "voh_min", "vol_max") and not 0 <= val <= 60):
            return _err("INVALID_DEVICE", f"{k} = {val!r} is outside its physical range (current >= 0 uA, supply/limits 0-60 V, vin_max and io_vdd > 0 V)")
    for k, val in (("i_ua_by_mode", i_ua_by_mode), ("io_vdd_by_pin", io_vdd_by_pin)):
        if val is None:
            continue
        if not isinstance(val, dict) or not all(_num(x) for x in val.values()):
            return _err("INVALID_DEVICE", f"{k} must be an object of finite numbers")
        if (k == "i_ua_by_mode" and any(x < 0 for x in val.values())) or (k == "io_vdd_by_pin" and any(not 0 < x <= 60 for x in val.values())):
            return _err("INVALID_DEVICE", f"{k} has a value outside its physical range (current >= 0 uA, rail 0-60 V)")
    dev = {"id": id.strip(), "part": part.strip(), "vdd": float(vdd), "interface": interface.strip(),
           **{k: float(val) for k, val in optional.items() if val is not None},
           **({"i_ua_by_mode": {k: float(x) for k, x in i_ua_by_mode.items()}} if i_ua_by_mode else {}),
           **({"io_vdd_by_pin": {k: float(x) for k, x in io_vdd_by_pin.items()}} if io_vdd_by_pin else {})}
    b = _board(project_id)
    st = b.state()
    clash = next((d["id"] for d in st["devices"] if d["id"] != dev["id"] and d["id"].lower() == dev["id"].lower()), None)
    if clash:
        return _err("INVALID_DEVICE", f"id {dev['id']!r} differs only by case from the existing device {clash!r}: use that exact id to update it, or choose another id")
    if dev["id"].lower() in {t["chip"].lower() for t in st["targets"]} | {str(c).lower() for c in _cat().hw._chips}:
        return _err("INVALID_DEVICE", f"id {dev['id']!r} is a chip name: endpoints '<id>.<pin>' would be ambiguous with the MCU; choose another id (e.g. 'U1')")
    v = _append(b, "device_added", {"device": dev}, st["version"])
    return v if isinstance(v, dict) else {"ok": True, "version": v, "device": dev}


_SUGGESTIONS = {
    "LEVEL_MISMATCH": lambda lo, hi: [
        {"action": "add_level_shifter", "between_rails_v": [lo, hi], "note": "insert a level shifter (bidirectional / open-drain capable for I2C) between the two voltage domains, then connect through it"},
        {"action": "change_supply", "note": f"if the device allows it, power its I/O (VDDIO) from the MCU rail instead of {lo:g} V"}],
    "ADC_RANGE": lambda lo, hi: [
        {"action": "attenuate_before_adc", "between_rails_v": [lo, hi], "note": "scale the signal down (resistor divider / op-amp buffer) so it stays within VSSA..VREF+ (<= VDDA)"},
        {"action": "use_non_adc_pin", "note": "if the signal is only digital, connect it with kind='digital' to a 5 V tolerant pin instead"}],
    "NOT_5V_TOLERANT": lambda lo, hi: [
        {"action": "use_5v_tolerant_pin", "note": "route the signal to a pin whose I/O structure is FT (5 V tolerant) in the datasheet pin table"},
        {"action": "add_level_shifter_or_divider", "between_rails_v": [lo, hi], "note": "reduce the 5 V swing with a resistor divider (analog/input only) or a level shifter"}]}


@_tool
def connect(from_ref: str, to_ref: str, kind: str, project_id: str | None = None) -> dict:
    """Connect two endpoints and check the logic levels (reuses the datasheet VIH/VIL/VOH/VOL tables and the pin's FT/TT input limit). Endpoints: '<chip>.<pin>' for an MCU pin (e.g. 'stm32g474.PC8') or '<device id>.<pin>' for a declared device (e.g. 'U2.SDA'). kind: 'digital' (from drives to), 'bidirectional' (alias 'i2c', 'open_drain'; both directions are checked) or 'analog' (overvoltage only). A passing connection is recorded; a failing one is REFUSED with LEVEL_MISMATCH:<low>V-<high>V or NOT_5V_TOLERANT:<pin> plus suggestions (level shifter, 5 V tolerant pin), an analog signal above the ADC input range of an ADC-capable pin with ADC_RANGE:<pin>, an unknown endpoint with UNKNOWN_ENDPOINT, and a check the database cannot make (no input maximum for the pin, VDDA/VREF+ not declared) with LEVEL_DATA_UNKNOWN - never a pass. Thresholds a device does not declare are assumed and listed under level_check.assumptions."""
    if not isinstance(kind, str) or kind not in drc._KINDS:
        return _err("INVALID_KIND", f"kind must be one of {sorted(drc._KINDS)}, got {kind!r}")
    if not all(isinstance(x, str) and "." in x for x in (from_ref, to_ref)):
        return {**_err("UNKNOWN_ENDPOINT", "endpoints look like '<chip>.<pin>' or '<device id>.<pin>'"), "recorded": False}
    b = _board(project_id)
    st = b.state()
    net = {"from": from_ref.strip(), "to": to_ref.strip(), "kind": kind}
    ev = drc.evaluate_net(net, st, _cat())
    summary = {"status": ev["status"], "assumptions": ev["assumptions"], "checks": ev["checks"], "notes": ev["notes"]}
    if ev["status"] == "UNKNOWN":
        issue = ev["issues"][0]
        endpoint = issue["code"].startswith(("NET_ENDPOINT_UNKNOWN", "NET_KIND_UNKNOWN"))
        return {**_err("UNKNOWN_ENDPOINT" if endpoint else "LEVEL_DATA_UNKNOWN", issue["message"], endpoint_code=issue["code"]), "recorded": False, "level_check": summary}
    if ev["status"] == "FAIL":
        issue = ev["issues"][0]
        rails = sorted(e["rail"] for e in (drc.endpoint_levels(net["from"], st, _cat())[0], drc.endpoint_levels(net["to"], st, _cat())[0]) if e)
        family = issue["code"].split(":", 1)[0]
        return {**_err(issue["code"], issue["message"], direction=issue["direction"], all_issues=[i["code"] for i in ev["issues"]],
                       suggestions=_SUGGESTIONS[family](rails[0], rails[-1])), "recorded": False, "level_check": summary}
    v = _append(b, "net_connected", {"net": {**net, "level_check": {"status": "PASS", "assumptions": ev["assumptions"]}}}, st["version"])
    return v if isinstance(v, dict) else {"ok": True, "recorded": True, "version": v, "net": net, "level_check": summary}


@_tool
def record_decision(question: str, options: list[str] | str, chosen: str, by: str = "agent", rationale: str = "", project_id: str | None = None) -> dict:
    """Record a design decision and its reason (e.g. which pin to use for I2C3_SCL and why). `options` lists the alternatives considered, `chosen` must be one of them, `by` is 'agent' or 'human'. The decision gets an id D1, D2... and stays in the project memory, so later turns (and a human reviewer) can see why the design is the way it is."""
    opts, bad = _json_arg(options, list, "options")
    if bad or not isinstance(question, str) or not question.strip() or not opts or chosen not in opts or by not in DECISION_BY or not isinstance(rationale, str):
        return _err("INVALID_DECISION", bad or f"need a non-empty question, a non-empty options list that contains `chosen`, and by in {list(DECISION_BY)}")
    b = _board(project_id)
    st = b.state()
    n = max([int(m.group(1)) for d in st["decisions"] if (m := re.fullmatch(r"D(\d+)", str(d.get("id"))))] or [0]) + 1
    dec = {"id": f"D{n}", "question": question.strip(), "options": opts, "chosen": chosen, "by": by, "rationale": rationale.strip()}
    v = _append(b, "decision_recorded", {"decision": dec}, st["version"])
    return v if isinstance(v, dict) else {"ok": True, "version": v, "decision": dec}


@_tool
def rollback(version: int, project_id: str | None = None) -> dict:
    """Restore the Board State to an earlier version. The rollback is itself a NEW event (history is never deleted), so the state before the rollback can still be read with get_board_state(version=...). Returns the new version and the changes the rollback made."""
    b = _board(project_id)
    head = b.head()
    if isinstance(version, bool) or not isinstance(version, int):
        return _err("INVALID_ARGUMENT", f"version must be an integer, got {version!r}")
    before = b.state()
    try:
        new = b.rollback(version, actor=os.environ.get("BOARD_STATE_ACTOR", ACTOR), reason="rollback requested through the board-state server")
    except ValueError as exc:
        return _err("NO_SUCH_VERSION", str(exc), head=head)
    except bsm.VersionConflict as exc:
        return _err("VERSION_CONFLICT", str(exc))
    return {"ok": True, "version": new, "restored_from": version, "changes": bsm.diff(before, b.state())}


if __name__ == "__main__":
    mcp.run()
