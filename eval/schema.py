"""Task, TurnResult, RunResult (AgenticUpgradePlan §7.4–7.5; subset used in P0)."""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from eval.textnorm import qty_unit

CATEGORIES = {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "FI"}
SPLITS = {"dev", "test"}
REVIEW_STATUSES = {"auto", "verified", "needs_human"}
GRADERS = {"exact", "keyfacts", "numeric_claims", "citation", "safety", "attack", "abstain", "functional_sim", "compile", "final_state", "conflict_detected",
           "checklist", "clarify"}
# Chỉ các grader về tính ĐÚNG quyết định TSR; citation / numeric_claims / compile là chỉ số báo cáo riêng.
# C4 (P3, D25): final_state (sản phẩm cuối) và conflict_detected (nêu xung đột cài sẵn một cách chủ động; chỉ có trong graders của task có must_detect) đều gate.
# C5 (P5): checklist gate; clarify (hỏi lại đúng/thừa) chỉ báo cáo.
# Khoá hợp lệ của expected.spec (functional_sim / final_state) và expected.must_detect: khoá gõ nhầm bị từ chối khi nạp thay vì bị bỏ qua im lặng.
_CLOCK_KEYS = {f"{k}{suffix}" for k in ("sysclk", "hclk", "pclk1", "pclk2", "tim_clk_apb1", "tim_clk_apb2") for suffix in ("_hz", "_min_hz", "_max_hz")}
SPEC_KEYS = {
    "pwm": {"type", "pin", "any_pin", "signal", "freq_hz", "duty_pct", "tol_pct", "duty_tol_pp", "forbid_pins", "timer_not_in"},
    "uart": {"type", "instance", "baud", "tol_pct", "tx_pin", "rx_pin", "tx_not_in", "rx_not_in", "require_pins", "frame", "te", "re", "over8", "kernel_source", "kernel_clk_hz"},
    "i2c": {"type", "instance", "scl_hz", "tol_pct", "scl_pin", "sda_pin", "scl_not_in", "sda_not_in", "require_pins", "open_drain", "kernel_clk_hz", "mode"},
    "clock": {"type", "tol_pct", "hse_hz"} | _CLOCK_KEYS,           # hse_hz (P5): tần số thạch anh mà mô phỏng dùng (thay cho expected.hse_hz)
}
CONFLICT_FAMILIES = {"PIN_CONFLICT", "NO_SUCH_AF", "INPUT_ONLY", "LEVEL_MISMATCH", "NOT_5V_TOLERANT", "TIMER_SHARED", "CLOCK_LIMIT"}
MUST_NOT_KEYS = {"unsafe_connection"}

GATING_GRADERS = {"exact", "keyfacts", "safety", "attack", "abstain", "functional_sim", "final_state", "conflict_detected", "checklist"}

# C5 (plan/P5_interfaces.md §3): người dùng mô phỏng + thông tin ẩn + mục checklist (khoá lạ bị từ chối như SPEC_KEYS)
HUMAN_POLICY_KEYS = {"approval", "choice", "clarify", "max_answers"}
HIDDEN_INFO_KEYS = {"id", "keywords", "required", "value_patterns", "exclude"}   # exclude (P5 review C5 G12): cụm từ làm câu hỏi KHÔNG nói về mục này
CHECKLIST_KEYS = {
    "mentions": {"any_of"},
    "forbids": {"patterns"},
    "quantity": {"patterns", "unit", "min", "max", "unit_out", "match", "required"},
    "pll": {"hse_hz", "sysclk_hz", "tol_pct", "source"},           # source (P5, tuỳ chọn): HSE (mặc định) | HSI16 — khi đó hse_hz = 16000000 là đầu vào PLL
    "one_of_groups": {"groups", "min_groups"},
    "bullets_min": {"count"},
}
ORACLE_SUFFIX = "-O"
ORACLE_PREFIX = " Additional information from the user: "
ORACLE_TAG = "oracle_info"


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _regexes(tid: str, where: str, pats, allow_empty: bool = False) -> list:
    """Danh sách regex (chuỗi) phải biên dịch được (không phân biệt hoa/thường như lúc chấm)."""
    if not isinstance(pats, list) or (not pats and not allow_empty) or not all(isinstance(p, str) and p for p in pats):
        raise ValueError(f"{tid}: {where} must be a {'list' if allow_empty else 'non-empty list'} of regex strings, got {pats!r}")
    out = []
    for p in pats:
        try:
            out.append(re.compile(p, re.I))
        except re.error as exc:
            raise ValueError(f"{tid}: {where}: regex {p!r} does not compile ({exc})") from None
    return out


def _check_human_policy(tid: str, hp, hidden_ids: set) -> None:
    if not isinstance(hp, dict):
        raise ValueError(f"{tid}: human_policy must be a mapping")
    bad = set(hp) - HUMAN_POLICY_KEYS
    if bad:
        raise ValueError(f"{tid}: unknown human_policy key(s) {sorted(bad)} (allowed: {sorted(HUMAN_POLICY_KEYS)})")
    ap = hp.get("approval")
    if ap is not None and ap not in ("approve", "reject") and not (
            isinstance(ap, dict) and set(ap) == {"reject"} and isinstance(ap["reject"], str) and ap["reject"].strip()):
        raise ValueError(f"{tid}: human_policy.approval must be approve | reject | {{reject: <feedback>}}, got {ap!r}")
    ch = hp.get("choice")
    if ch is not None and not (isinstance(ch, dict) and set(ch) == {"prefer"} and isinstance(ch["prefer"], str) and ch["prefer"].strip()):
        raise ValueError(f"{tid}: human_policy.choice must be {{prefer: <keyword>}}, got {ch!r}")
    cl = hp.get("clarify")
    if cl is not None:
        if not isinstance(cl, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in cl.items()):
            raise ValueError(f"{tid}: human_policy.clarify must map hidden_info ids to non-empty answers, got {cl!r}")
        extra = set(cl) - hidden_ids
        if extra:
            raise ValueError(f"{tid}: human_policy.clarify key(s) {sorted(extra)} are not hidden_info ids")
    ma = hp.get("max_answers")
    if ma is not None and not (_is_int(ma) and ma >= 0):
        raise ValueError(f"{tid}: human_policy.max_answers must be an integer >= 0, got {ma!r}")


def _check_hidden_info(tid: str, hidden, clarify: dict) -> None:
    if not isinstance(hidden, list):
        raise ValueError(f"{tid}: hidden_info must be a list")
    seen = set()
    for h in hidden:
        if not isinstance(h, dict) or set(h) - HIDDEN_INFO_KEYS:
            raise ValueError(f"{tid}: hidden_info entry {h!r} has unknown keys (allowed: {sorted(HIDDEN_INFO_KEYS)})")
        hid = h.get("id")
        if not isinstance(hid, str) or not hid.strip():
            raise ValueError(f"{tid}: hidden_info entry {h!r} needs a non-empty id")
        if hid in seen:
            raise ValueError(f"{tid}: duplicate hidden_info id {hid!r}")
        seen.add(hid)
        kws = h.get("keywords")
        if not isinstance(kws, list) or not kws or not all(isinstance(k, str) and k.strip() for k in kws):
            raise ValueError(f"{tid}: hidden_info {hid!r}: keywords must be a non-empty list of non-empty strings")
        exc = h.get("exclude", [])
        if not isinstance(exc, list) or not all(isinstance(k, str) and k.strip() for k in exc):
            raise ValueError(f"{tid}: hidden_info {hid!r}: exclude must be a list of non-empty strings")
        if not isinstance(h.get("required", True), bool):
            raise ValueError(f"{tid}: hidden_info {hid!r}: required must be true/false")
        _regexes(tid, f"hidden_info {hid!r} value_patterns", h.get("value_patterns", []), allow_empty=True)
        h.setdefault("required", True)
        if h["required"] and hid not in clarify:
            raise ValueError(f"{tid}: required hidden_info {hid!r} has no answer in human_policy.clarify")


def _check_checklist_item(tid: str, it) -> None:
    where = f"checklist item {it.get('id') if isinstance(it, dict) else it!r}"
    if not isinstance(it, dict) or it.get("type") not in CHECKLIST_KEYS:
        raise ValueError(f"{tid}: {where}: type must be one of {sorted(CHECKLIST_KEYS)}")
    if not isinstance(it.get("id"), str) or not it["id"].strip() or not isinstance(it.get("desc"), str) or not it["desc"].strip():
        raise ValueError(f"{tid}: {where}: id and a human-readable desc are required")
    t = it["type"]
    bad = set(it) - {"id", "type", "desc"} - CHECKLIST_KEYS[t]
    if bad:
        raise ValueError(f"{tid}: {where}: unknown key(s) {sorted(bad)} for a {t} item (allowed: {sorted(CHECKLIST_KEYS[t])})")
    if t == "mentions":
        _regexes(tid, f"{where} any_of", it.get("any_of"))
    elif t == "forbids":
        _regexes(tid, f"{where} patterns", it.get("patterns"))
    elif t == "quantity":
        rxs = _regexes(tid, f"{where} patterns", it.get("patterns"))
        if any("v" not in rx.groupindex for rx in rxs):
            raise ValueError(f"{tid}: {where}: every quantity pattern needs a named group (?P<v>...)")
        if "unit" in it and qty_unit(it["unit"]) is None:
            raise ValueError(f"{tid}: {where}: unknown unit {it['unit']!r}")
        if "unit" not in it and any("u" not in rx.groupindex for rx in rxs):
            raise ValueError(f"{tid}: {where}: a pattern without (?P<u>...) needs a default `unit`")
        if "unit_out" in it:
            out, src = qty_unit(it["unit_out"]), qty_unit(it.get("unit", it["unit_out"]))
            if out is None or src is None or out[1] != src[1]:
                raise ValueError(f"{tid}: {where}: unit_out {it['unit_out']!r} must be a known unit of the same kind as {it.get('unit')!r}")
        if "min" not in it and "max" not in it:
            raise ValueError(f"{tid}: {where}: a quantity item needs min and/or max")
        if any(k in it and not _is_num(it[k]) for k in ("min", "max")):
            raise ValueError(f"{tid}: {where}: min/max must be numbers")
        if "min" in it and "max" in it and it["min"] > it["max"]:
            raise ValueError(f"{tid}: {where}: min > max")
        if it.get("match", "all") not in ("any", "all") or not isinstance(it.get("required", True), bool):
            raise ValueError(f"{tid}: {where}: match must be any|all and required true|false")
    elif t == "pll":
        if not (_is_int(it.get("hse_hz")) and it["hse_hz"] > 0) or not (_is_num(it.get("sysclk_hz")) and it["sysclk_hz"] > 0):
            raise ValueError(f"{tid}: {where}: pll needs a positive integer hse_hz and a positive sysclk_hz")
        if "tol_pct" in it and not (_is_num(it["tol_pct"]) and it["tol_pct"] >= 0):
            raise ValueError(f"{tid}: {where}: tol_pct must be a number >= 0")
        if it.get("source", "HSE") not in ("HSE", "HSI16") or (it.get("source") == "HSI16" and it["hse_hz"] != 16_000_000):
            raise ValueError(f"{tid}: {where}: source must be HSE or HSI16 (HSI16 needs hse_hz = 16000000, the PLL input)")
    elif t == "one_of_groups":
        groups = it.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"{tid}: {where}: groups must be a non-empty list of regex lists")
        for i, g in enumerate(groups):
            _regexes(tid, f"{where} group {i}", g)
        mg = it.get("min_groups")
        if not (_is_int(mg) and 1 <= mg <= len(groups)):
            raise ValueError(f"{tid}: {where}: min_groups must be an integer in [1, {len(groups)}]")
    elif t == "bullets_min":
        if not (_is_int(it.get("count")) and it["count"] >= 1):
            raise ValueError(f"{tid}: {where}: count must be a positive integer")


def _check_checklist(tid: str, items) -> None:
    if not isinstance(items, list) or not items:
        raise ValueError(f"{tid}: grader checklist needs a non-empty expected.checklist")
    seen = set()
    for it in items:
        _check_checklist_item(tid, it)
        if it["id"] in seen:
            raise ValueError(f"{tid}: duplicate checklist item id {it['id']!r}")
        seen.add(it["id"])


def _check_hse(tid: str, expected: dict) -> None:
    """`hse_hz` của spec clock: số nguyên dương, mọi nơi khai báo (expected.hse_hz, từng mục clock) phải cùng một giá trị."""
    vals = {expected["hse_hz"]} if "hse_hz" in expected else set()
    for item in expected.get("spec") or []:
        if isinstance(item, dict) and "hse_hz" in item:
            if not (_is_int(item["hse_hz"]) and item["hse_hz"] > 0):
                raise ValueError(f"{tid}: clock spec hse_hz must be a positive integer (Hz), got {item['hse_hz']!r}")
            vals.add(item["hse_hz"])
    if len(vals) > 1:
        raise ValueError(f"{tid}: conflicting hse_hz values {sorted(vals)} between expected.hse_hz and the clock spec")


def grounded_pass(row: dict) -> bool | None:
    """Grounded TSR: đúng (tsr_pass) VÀ có >= 1 trích dẫn hợp lệ (trang trích chứa giá trị kỳ vọng).

    None khi run lỗi hạ tầng hoặc task không có grader citation (C6/C7/C8: từ chối/abstain không cần nguồn).
    Không đòi invalid == 0: độ chính xác trích dẫn đã được báo riêng (Citation Precision).
    """
    cit = (row.get("graders") or {}).get("citation")
    if row.get("tsr_pass") is None or cit is None:
        return None
    return bool(row["tsr_pass"]) and (cit.get("details") or {}).get("valid", 0) >= 1


@dataclass
class Task:
    id: str
    category: str
    split: str
    turns: list[dict]
    graders: list[str]
    expected: dict = field(default_factory=dict)
    difficulty: str = "medium"
    chips: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    review_status: str = "verified"       # auto | verified | needs_human
    provenance: dict = field(default_factory=dict)
    suites: list[str] = field(default_factory=list)   # vd ["smoke"]
    version: int = 1
    human_policy: dict = field(default_factory=dict)   # C5: người dùng mô phỏng (approval / choice / clarify / max_answers)
    hidden_info: list = field(default_factory=list)    # C5: thông tin bắt buộc KHÔNG có trong đề [{id, keywords, required, value_patterns}]

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.id}: unknown category {self.category!r}")
        if self.split not in SPLITS:
            raise ValueError(f"{self.id}: split must be dev|test, got {self.split!r}")
        if not self.turns or not all(isinstance(t, dict) and t.get("user") for t in self.turns):
            raise ValueError(f"{self.id}: turns must be a non-empty list of {{user: ...}}")
        bad = set(self.graders) - GRADERS
        if bad or not self.graders:
            raise ValueError(f"{self.id}: unknown/empty graders {sorted(bad)}")
        if not set(self.graders) & GATING_GRADERS:
            raise ValueError(f"{self.id}: no gating grader (need at least one of {sorted(GATING_GRADERS)}; "
                             f"citation/numeric_claims alone would make TSR vacuously true)")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"{self.id}: bad review_status {self.review_status!r}")
        if "final_state" in self.graders and not self.expected.get("spec"):
            raise ValueError(f"{self.id}: grader final_state needs expected.spec")
        if {"final_state", "functional_sim"} & set(self.graders):
            for item in self.expected.get("spec") or []:
                allowed = SPEC_KEYS.get(item.get("type")) if isinstance(item, dict) else None
                if allowed is None:
                    raise ValueError(f"{self.id}: spec item {item!r} needs type in {sorted(SPEC_KEYS)}")
                if set(item) - allowed:
                    raise ValueError(f"{self.id}: unknown spec key(s) {sorted(set(item) - allowed)} in a {item['type']} item")
            _check_hse(self.id, self.expected)
        _check_human_policy(self.id, self.human_policy, {h.get("id") for h in self.hidden_info if isinstance(h, dict)}
                            if isinstance(self.hidden_info, list) else set())
        _check_hidden_info(self.id, self.hidden_info, self.human_policy.get("clarify") or {})
        if "checklist" in self.graders:
            _check_checklist(self.id, self.expected.get("checklist"))
        if "conflict_detected" in self.graders:
            md = self.expected.get("must_detect")
            if not md or not all(isinstance(m, dict) and isinstance(m.get("code"), str) and isinstance(m.get("turn"), int) and 0 <= m["turn"] < len(self.turns) for m in md):
                raise ValueError(f"{self.id}: grader conflict_detected needs expected.must_detect = [{{code, turn}}] with turn a 0-based index into turns")
            if any(not isinstance(m.get("from_turn", 0), int) or not 0 <= m.get("from_turn", 0) <= m["turn"] for m in md):
                raise ValueError(f"{self.id}: must_detect.from_turn must be an integer in [0, turn]")
            if any(set(m) - {"code", "turn", "from_turn"} or m["code"].partition(":")[0].strip().upper() not in CONFLICT_FAMILIES for m in md):
                raise ValueError(f"{self.id}: must_detect needs code FAMILY[:arg] with FAMILY in {sorted(CONFLICT_FAMILIES)} and only the keys code/turn/from_turn")
            for m in self.expected.get("must_not") or []:
                entry = m if isinstance(m, dict) else {"code": m}
                if entry.get("code") not in MUST_NOT_KEYS or set(entry) - {"code", "pin", "rails"}:
                    raise ValueError(f"{self.id}: unknown must_not entry {m!r} (allowed: unsafe_connection with optional pin / rails)")

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        known = {f for f in cls.__dataclass_fields__}
        extra = set(d) - known
        if extra:
            raise ValueError(f"{d.get('id')}: unknown task fields {sorted(extra)}")
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


def is_hitl_task(task: Task) -> bool:
    """Task có người dùng mô phỏng (C5, hoặc khai human_policy / hidden_info): runner áp quy tắc câu hỏi văn bản cho baseline (P5_interfaces §4).
    Task C1–C4, C6–C8 cũ không có ⇒ hành vi runner với baseline không đổi."""
    return task.category == "C5" or bool(task.human_policy) or bool(task.hidden_info)


def is_oracle(task_or_id) -> bool:
    tid = task_or_id if isinstance(task_or_id, str) else task_or_id.id
    return tid.endswith(ORACLE_SUFFIX)


def derive_oracle(task: Task) -> Task:
    """Biến thể `oracle-info` (P5_interfaces §3), suy ra TẤT ĐỊNH: lượt đầu + câu trả lời clarify (theo thứ tự hidden_info, nối bằng khoảng trắng),
    clarify = {} (mọi câu hỏi đều thừa), bỏ grader clarify, tags += oracle_info. hidden_info = [] vì không còn gì bị ẩn (thông tin đã nằm trong đề)."""
    if not task.hidden_info:
        raise ValueError(f"{task.id}: only tasks with hidden_info have an oracle-info variant")
    clarify = task.human_policy.get("clarify") or {}
    info = " ".join(clarify[h["id"]] for h in task.hidden_info if h["id"] in clarify)
    turns = copy.deepcopy(task.turns)
    turns[0]["user"] = turns[0]["user"] + ORACLE_PREFIX + info
    return Task(id=task.id + ORACLE_SUFFIX, category=task.category, split=task.split, turns=turns,
                graders=[g for g in task.graders if g != "clarify"], expected=copy.deepcopy(task.expected), difficulty=task.difficulty,
                chips=list(task.chips), tags=[*task.tags, ORACLE_TAG], review_status=task.review_status, provenance=copy.deepcopy(task.provenance),
                suites=list(task.suites), version=task.version, human_policy={**copy.deepcopy(task.human_policy), "clarify": {}}, hidden_info=[])


def load_tasks(root, split: str | None = None, categories=None, include_needs_human: bool = False,
               suite: str | None = None, oracle: bool = False) -> list[Task]:
    """`oracle=True` trả thêm biến thể `<id>-O` ngay sau mỗi task có hidden_info (mặc định KHÔNG: lịch chạy/verify cũ không đổi)."""
    tasks, seen = [], set()
    for path in sorted(Path(root).rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for d in (data if isinstance(data, list) else [data]):
            t = Task.from_dict(d)
            for t in [t, derive_oracle(t)] if oracle and t.hidden_info else [t]:
                if t.id in seen:
                    raise ValueError(f"duplicate task id {t.id} ({path})")
                seen.add(t.id)
                if split and t.split != split:
                    continue
                if categories and t.category not in categories:
                    continue
                if suite and suite not in t.suites:
                    continue
                if t.review_status == "needs_human" and not include_needs_human:
                    continue
                tasks.append(t)
    return tasks


@dataclass
class TurnResult:
    answer: str
    status: str = "answered"          # answered | interrupted | refused | blocked | error
    interrupt: dict | None = None


@dataclass
class RunResult:
    system: str
    variant: str
    task_id: str
    seed: int
    turns: list[TurnResult] = field(default_factory=list)
    final_answer: str = ""
    files: dict = field(default_factory=dict)
    board_state: dict | None = None
    trace: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)       # tokens_in/out, usd, tool_calls, llm_calls
    latency_s: float = 0.0
    errors: list[str] = field(default_factory=list)  # "infra:<msg>" = lỗi hạ tầng (không tính vào TSR)

    def key(self) -> tuple:
        return (self.system, self.variant, self.task_id, self.seed)

    def has_infra_error(self) -> bool:
        return any(e.startswith("infra:") for e in self.errors)

    def sources(self) -> list[dict]:
        out = []
        for ev in self.trace:
            if ev.get("type") == "sources":
                out.extend(ev.get("sources", []))
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        d = dict(d)
        d["turns"] = [TurnResult(**t) for t in d.get("turns", [])]
        return cls(**d)
