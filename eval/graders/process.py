"""Grader `process` (P4): chỉ số QUÁ TRÌNH của S3@P4, tính trên `RunResult.trace` (sự kiện phẳng, plan/P4_interfaces.md §4–§5).
CHỈ BÁO CÁO: không có `pass`/`score`, không nằm trong GATING_GRADERS, không ảnh hưởng `tsr_pass`.

Trace v3 = có ít nhất một sự kiện `type == "run_started"`; mọi hệ khác (S0..S2D) ⇒ `{"v3": False}` và báo cáo ghi N/A.
Sự kiện được gom theo lượt = nhóm `(turn, run_id)` (mỗi `rt.ask` là một run; gom thêm theo `run_id` để hai lượt lỡ cùng số `turn` không bị trộn `seq`),
các lượt sắp theo `turn` rồi theo thứ tự xuất hiện đầu tiên trong trace, sự kiện trong lượt sắp theo `seq` (không phụ thuộc thứ tự trong danh sách);
sự kiện không phải dict hoặc thiếu trường bắt buộc bị bỏ qua, không làm hỏng việc chấm.

Định nghĩa chính xác (mỗi run = một (task, seed), gộp mọi lượt của task):

* **Chuỗi kiểm tra** = các sự kiện, theo `(turn, seq)`, thuộc một trong hai loại:
  `gate_result` có `passed` kiểu bool, và `sim_result` có `source == "agent"`, `artifact` khác rỗng, `pass` kiểu bool.
  `sim_result` do Gate chạy (`source == "gate"`) KHÔNG được đếm riêng vì đã nằm trong `gate_result` kèm theo (đếm hai lần sẽ làm phồng số lần sửa);
  mô phỏng thăm dò của agent không gắn `artifact` cũng không phải kiểm tra sản phẩm. Ghi trong `checks` là chuỗi "P"/"F" (vd "FFP").
  Run "có sản phẩm" (`has_product`) nếu chuỗi không rỗng.
* **Self-Correction**: `first_failed` = kiểm tra ĐẦU TIÊN fail (mẫu số); `self_corrected` = `first_failed` và kiểm tra CUỐI CÙNG pass (tử số).
  Self-Correction Rate = Σ self_corrected / Σ first_failed. Đo theo Gate/simulator CỦA AGENT (requirement do agent ghi), nên luôn đọc kèm
  `self_corrected_tsr_rate` = (số run tự sửa mà `tsr_pass` của grader độc lập cũng True) / số run tự sửa.
* **Mean Repair Iterations** = trung bình trên các run `self_corrected` của số kiểm tra fail trong chuỗi (chuỗi kết thúc bằng pass nên
  đó cũng là số lần fail từ kiểm tra đầu tiên đến lần pass cuối cùng; nhiều lượt được nối theo thứ tự lượt). `repair_iterations` = None nếu không tự sửa.
* **Replan**: `plan_updated` = tổng số sự kiện `plan_updated`; `plan_updated_after_trigger` = số `plan_updated` xuất hiện SAU một `replan_required`
  hoặc một `gate_result` fail TRONG CÙNG LƯỢT (lập lại kế hoạch có lý do; kế hoạch đầu tiên và lần cập nhật sau chỉ một `sim_result` fail của agent
  không tính). `replan_required` = số sự kiện `replan_required`.
  **Replan Effectiveness** (hai cách): `replan_ok_accepted` = số `replan_required` mà lượt của nó KẾT THÚC bằng `finish` có `accepted=true`
  nằm SAU nó và không có `escalated` sau finish đó (quyết định theo lượt chứa replan); `replan_ok_tsr` = `replan_required` nếu `tsr_pass` is True, ngược lại 0.
  Replan Effectiveness = Σ replan_ok_* / Σ replan_required.
* **Premature-Finish Rate** = Σ `finish_rejected` / Σ `finish_total`, với `finish_total` = số sự kiện `finish` (kể cả `implicit`) và
  `finish_rejected` = số `finish` có `accepted == false`. Kèm: `escalated_turns` = số lượt có sự kiện `escalated` hoặc `done.status == "escalated"`;
  `ended_escalated` = lượt CUỐI của task escalated; tỷ lệ task kết thúc escalated = Σ ended_escalated / số run.
* **Step Efficiency** = Σ `tool_calls` (sự kiện `tool_call` có `internal` không True, tức do agent gọi) của MỌI run chấm được / số run thành công
  (`tsr_pass` True) — chi phí bước cho mỗi thành công, run thất bại cũng góp chi phí; None khi chưa có thành công.
  **Tỷ lệ gọi trùng** = Σ `dup_calls` / Σ `tool_calls`, `dup_calls` = lời gọi có cùng `tool` + `args` (khoá JSON đã sắp) với một lời gọi trước đó CÙNG LƯỢT.
* **Phủ kế hoạch** trên task thiết kế (C3/C4): tỷ lệ run có `plan_updated >= 1`.
* **Phân bố mã gate fail**: với mỗi `gate_result` fail, đếm mã của các finding có `severity == "error"` (finding `unknown`/`warning` không chặn nên
  không tính); `gate_result` fail không có finding error được đếm là "unspecified".

* **Self-Correction theo lớp lỗi (D35, P5)** — chỉ THÊM khoá, không đổi khoá cũ: mỗi kiểm tra fail mang một lớp:
  `sim_result` fail của agent ⇒ `physical` (simulator); `gate_result` fail ⇒ lớp của từng finding mức error theo trường `gate` (thiếu thì theo tiền tố
  `code`): G1 ⇒ `provenance`; G2/G3/G5 hoặc mã DRC-* ⇒ `physical`; G4 ⇒ `safety`; khác / gate fail không có finding error ⇒ `unspecified`.
  `fail_classes` = các lớp đã gặp trong mọi kiểm tra fail của run; với run `first_failed`, `fail_class` = `physical` (có lỗi vật lý, không có G1),
  `mixed` (cả G1 lẫn vật lý), `provenance` (CHỈ G1), `other` (còn lại: G4 / không rõ); run không first_failed ⇒ None.
  aggregate: Self-Correction (vật lý) = tự sửa / first_failed trên run `physical` + `mixed`; Self-Correction (provenance) = trên run `provenance`;
  `other` báo riêng. Hàng scores.jsonl cũ (chưa có khoá) không vào phép tách (`sc_split_runs` đếm số run first_failed có khoá).
* Sự kiện do RUNNER ghi (`human_reply`, `resume_result`, `hitl_loop` — P5) và mọi sự kiện KHÔNG có `run_id` (vd `worker` của adapter) bị bỏ qua khi gom
  lượt (review P4 m3: trước P5 sự kiện `worker` làm `turns` lớn hơn số lần `rt.ask` đúng 1; các chỉ số khác không đổi). Gọi trùng (P5 review m2) so
  `(tool, args_sha)` khi sự kiện có `args_sha` (băm tham số đầy đủ), ngược lại so `(tool, args)` như cũ.

`process_metrics(run, tsr_pass)` trả chi tiết một run; `aggregate(rows)` gộp các hàng scores.jsonl (cùng một hệ/biến thể) cho report;
mẫu số rỗng ⇒ tỷ lệ là None (report in N/A), không phải 0.
"""
from __future__ import annotations

import json
from collections import Counter

DESIGN_CATEGORIES = ("C3", "C4")
RUNNER_EVENTS = ("human_reply", "resume_result", "hitl_loop")
PHYSICAL_GATES = ("G2", "G3", "G5")


def _dicts(trace) -> list[dict]:
    return [e for e in (trace or []) if isinstance(e, dict) and e.get("type") not in RUNNER_EVENTS]


def is_v3(trace) -> bool:
    return any(e.get("type") == "run_started" for e in _dicts(trace))


def _turn(e: dict) -> int:
    t = e.get("turn")
    return t if isinstance(t, int) and not isinstance(t, bool) else 0


def _turns(trace) -> list[list[dict]]:
    """Các lượt theo thứ tự (turn, lần xuất hiện đầu); mỗi lượt là danh sách sự kiện sắp theo `seq` (thiếu seq ⇒ giữ thứ tự xuất hiện)."""
    groups: dict[tuple, list[tuple]] = {}
    for idx, e in enumerate(_dicts(trace)):
        if e.get("run_id") is None:
            continue                                  # P5 review m3: sự kiện `worker` của adapter (không run_id) từng thành một "lượt" thừa
        seq = e.get("seq")
        seq = seq if isinstance(seq, (int, float)) and not isinstance(seq, bool) else idx
        groups.setdefault((_turn(e), e.get("run_id")), []).append((seq, idx, e))
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][0], min(i for _, i, _ in kv[1])))
    return [[e for _, _, e in sorted(items, key=lambda x: (x[0], x[1]))] for _, items in ordered]


def _check_result(e: dict) -> bool | None:
    """Kết quả của một sự kiện nếu nó là một kiểm tra sản phẩm (xem docstring), ngược lại None."""
    if e.get("type") == "gate_result":
        return e["passed"] if isinstance(e.get("passed"), bool) else None
    if e.get("type") == "sim_result" and e.get("source") == "agent" and e.get("artifact"):
        return e["pass"] if isinstance(e.get("pass"), bool) else None
    return None


def _call_key(e: dict) -> tuple:
    """(tool, args_sha) khi runtime ghi `args_sha` (băm tham số ĐẦY ĐỦ, P5 review m2: `args` trong sự kiện bị cắt 400 ký tự); trace cũ: (tool, JSON args)."""
    if e.get("args_sha"):
        return (e.get("tool"), "sha:" + str(e["args_sha"]))
    return (e.get("tool"), json.dumps(e.get("args"), sort_keys=True, ensure_ascii=False, default=str))


def _finding_class(f: dict) -> str:
    gate, code = str(f.get("gate") or ""), str(f.get("code") or "")
    if gate == "G1" or (not gate and code.startswith("G1")):
        return "provenance"
    if gate in PHYSICAL_GATES or (gate in ("", "DRC") and code.startswith(("DRC", *PHYSICAL_GATES))):
        return "physical"
    if gate == "G4" or (not gate and code.startswith("G4")):
        return "safety"
    return "unspecified"


def _failure_classes(e: dict) -> set[str]:
    """Lớp lỗi của một kiểm tra FAIL (xem docstring)."""
    if e.get("type") == "sim_result":
        return {"physical"}
    errs = [f for f in (e.get("findings") or []) if isinstance(f, dict) and f.get("severity", "error") == "error"]
    return {_finding_class(f) for f in errs} or {"unspecified"}


def _fail_class(classes: set[str]) -> str:
    if "physical" in classes:
        return "mixed" if "provenance" in classes else "physical"
    return "provenance" if classes == {"provenance"} else "other"


def process_metrics(run, tsr_pass: bool | None) -> dict:
    trace = getattr(run, "trace", None) or []
    if not is_v3(trace):
        return {"v3": False}
    turns = _turns(trace)
    checks, codes, classes = [], Counter(), set()
    plan_updated = after_trigger = replan_required = replan_ok = 0
    finish_total = finish_rejected = tool_calls = dup_calls = 0
    escalated_turns: set[int] = set()
    for turn, evs in enumerate(turns):
        last_finish = max((i for i, e in enumerate(evs) if e.get("type") == "finish"), default=None)
        last_escalated = max((i for i, e in enumerate(evs) if e.get("type") == "escalated"), default=-1)
        ended_accepted = last_finish is not None and evs[last_finish].get("accepted") is True and last_escalated < last_finish
        triggered, seen = False, set()
        for i, e in enumerate(evs):
            kind = e.get("type")
            ok = _check_result(e)
            if ok is not None:
                checks.append("P" if ok else "F")
                if not ok:
                    classes |= _failure_classes(e)
            if kind == "gate_result" and e.get("passed") is False:
                triggered = True
                errs = [f.get("code") or "unspecified" for f in (e.get("findings") or []) if isinstance(f, dict) and f.get("severity", "error") == "error"]
                codes.update(errs or ["unspecified"])
            elif kind == "replan_required":
                triggered = True
                replan_required += 1
                replan_ok += bool(ended_accepted and last_finish > i)
            elif kind == "plan_updated":
                plan_updated += 1
                after_trigger += triggered
            elif kind == "finish":
                finish_total += 1
                finish_rejected += e.get("accepted") is False
            elif kind == "tool_call" and e.get("internal") is not True:
                tool_calls += 1
                key = _call_key(e)
                dup_calls += key in seen
                seen.add(key)
            elif kind == "escalated" or (kind == "done" and e.get("status") == "escalated"):
                escalated_turns.add(turn)
    seq = "".join(checks)
    first_failed = seq.startswith("F")
    self_corrected = first_failed and seq.endswith("P")
    return {"v3": True, "tsr_pass": tsr_pass, "turns": len(turns), "checks": seq, "has_product": bool(seq),
            "first_failed": first_failed, "self_corrected": self_corrected, "repair_iterations": seq.count("F") if self_corrected else None,
            "plan_updated": plan_updated, "plan_updated_after_trigger": after_trigger, "replan_required": replan_required,
            "replan_ok_accepted": replan_ok, "replan_ok_tsr": replan_required if tsr_pass is True else 0,
            "finish_total": finish_total, "finish_rejected": finish_rejected,
            "escalated_turns": len(escalated_turns), "ended_escalated": bool(turns) and len(turns) - 1 in escalated_turns,
            "tool_calls": tool_calls, "dup_calls": dup_calls, "gate_fail_codes": dict(codes),
            "fail_classes": sorted(classes), "fail_class": _fail_class(classes) if first_failed else None}


def grader_result(run, tsr_pass: bool | None) -> dict:
    """Hình dạng trong scores.jsonl (`graders.process`): không `pass`/`score` vì không gating."""
    return {"pass": None, "score": None, "reasons": [], "details": process_metrics(run, tsr_pass)}


def _ratio(num, den):
    return num / den if den else None


def _split(items) -> dict:
    """Self-Correction tách lớp (D35) trên các run first_failed CÓ khoá `fail_class` (hàng chấm trước P5 không có)."""
    ff = [(r, d) for r, d in items if d.get("first_failed") and "fail_class" in d]
    out = {"sc_split_runs": len(ff)}
    for name, keep in (("physical", ("physical", "mixed")), ("provenance", ("provenance",)), ("other", ("other",))):
        grp = [(r, d) for r, d in ff if d["fail_class"] in keep]
        fixed = [(r, d) for r, d in grp if d["self_corrected"]]
        fixed_tsr = sum(r.get("tsr_pass") is True for r, _ in fixed)
        out.update({f"sc_{name}_first_failed": len(grp), f"sc_{name}_corrected": len(fixed), f"sc_{name}_rate": _ratio(len(fixed), len(grp)),
                    f"sc_{name}_corrected_tsr": fixed_tsr, f"sc_{name}_corrected_tsr_rate": _ratio(fixed_tsr, len(fixed))})
    out["sc_mixed_first_failed"] = sum(d["fail_class"] == "mixed" for _, d in ff)
    return out


def aggregate(rows) -> dict:
    """Gộp các hàng scores.jsonl của MỘT hệ/biến thể; hàng không có `graders.process.details.v3` bị bỏ qua. Không có hàng nào ⇒ {"v3": False}."""
    items = []
    for r in rows:
        d = (((r.get("graders") or {}).get("process") or {}).get("details")) or {}
        if d.get("v3"):
            items.append((r, d))
    if not items:
        return {"v3": False}
    ds = [d for _, d in items]
    total = lambda k: sum(d.get(k) or 0 for d in ds)
    n = len(items)
    with_product = sum(d["has_product"] for d in ds)
    first_failed = sum(d["first_failed"] for d in ds)
    corrected = [(r, d) for r, d in items if d["self_corrected"]]
    corrected_tsr = sum(r.get("tsr_pass") is True for r, _ in corrected)
    repairs = [d["repair_iterations"] for _, d in corrected]
    successes = sum(r.get("tsr_pass") is True for r, _ in items)
    design = [d for r, d in items if r.get("category") in DESIGN_CATEGORIES]
    design_plan = sum(d["plan_updated"] >= 1 for d in design)
    codes: Counter = Counter()
    for d in ds:
        codes.update(d.get("gate_fail_codes") or {})
    replans, ended_esc = total("replan_required"), sum(d["ended_escalated"] for d in ds)
    return {"v3": True, "n_runs": n, "with_product": with_product, "first_failed": first_failed,
            "self_corrected": len(corrected), "self_corrected_tsr": corrected_tsr,
            "self_correction_rate": _ratio(len(corrected), first_failed), "self_corrected_tsr_rate": _ratio(corrected_tsr, len(corrected)),
            "mean_repair_iterations": _ratio(sum(repairs), len(repairs)),
            "plan_updated": total("plan_updated"), "plan_updated_after_trigger": total("plan_updated_after_trigger"),
            "replan_required": replans, "replan_ok_accepted": total("replan_ok_accepted"), "replan_ok_tsr": total("replan_ok_tsr"),
            "replan_effectiveness_accepted": _ratio(total("replan_ok_accepted"), replans), "replan_effectiveness_tsr": _ratio(total("replan_ok_tsr"), replans),
            "finish_total": total("finish_total"), "finish_rejected": total("finish_rejected"),
            "premature_finish_rate": _ratio(total("finish_rejected"), total("finish_total")),
            "escalated_turns": total("escalated_turns"), "ended_escalated": ended_esc, "ended_escalated_rate": _ratio(ended_esc, n),
            "tool_calls": total("tool_calls"), "successes": successes, "step_efficiency": _ratio(total("tool_calls"), successes),
            "dup_calls": total("dup_calls"), "dup_rate": _ratio(total("dup_calls"), total("tool_calls")),
            "design_runs": len(design), "design_with_plan": design_plan, "design_plan_coverage": _ratio(design_plan, len(design)),
            "gate_fail_codes": dict(codes), **_split(items)}
