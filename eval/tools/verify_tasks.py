"""Xác minh ground truth của task tuyển chọn (C2, C6, ...) trên text trang PDF của corpus.

Mỗi task cần `provenance.evidence`: [{doc_id, page, contains: [snippet, ...]}] (page = chỉ số PDF 1-based):
  * mọi snippet phải xuất hiện nguyên văn trên trang (không phân biệt hoa/thường, khoảng trắng);
  * keyfact dạng số / đại lượng / hex phải xuất hiện trên ít nhất một trang bằng chứng;
  * keyfact dạng text chỉ bị kiểm khi đánh dấu `literal: true` (AF trong bảng vị trí không có dạng chữ nguyên văn);
  * keyfact `derived: true` (suy ra từ các giá trị khác, vd hiệu hai tần số) được miễn kiểm.

    eval/.venv/bin/python -m eval.tools.verify_tasks [--categories C2,C6] [--split dev]

C3, C4, C5 có bộ kiểm riêng (verify_c3 / verify_c4 / verify_c5 — C5: lời giải tham chiếu + biến thể sai theo checklist, thông tin ẩn, oracle-info).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from eval.context import GradeContext
from eval.graders.common import fact_kind, fact_present
from eval.schema import load_tasks

ROOT = Path(__file__).resolve().parents[2]


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def check_evidence(task, ctx) -> tuple[list[str], list[str]]:
    """Mỗi snippet bằng chứng phải nằm nguyên văn trên trang PDF đã cho. Trả về (vấn đề, text các trang)."""
    evidence = (task.provenance or {}).get("evidence")
    if not evidence:
        return [f"{task.id}: no evidence in provenance"], []
    problems, texts = [], []
    for ev in evidence:
        entry = ctx.entry(ev.get("doc_id", ""))
        if entry is None or not entry.get("file"):
            problems.append(f"{task.id}: unknown doc {ev.get('doc_id')!r} (or no real PDF)")
            continue
        page = int(ev["page"])
        if not (1 <= page <= (entry.get("pages") or 0)):
            problems.append(f"{task.id}: page {page} out of range for {ev['doc_id']}")
            continue
        text = ctx.page_text(ev["doc_id"], page) or ""
        texts.append(text)
        for snip in ev.get("contains", []):
            if _squash(snip) not in _squash(text):
                problems.append(f"{task.id}: snippet not found on {ev['doc_id']} p.{page}: {snip!r}")
    return problems, texts


def verify_task(task, ctx) -> list[str]:
    if task.category == "C3":
        return verify_c3(task, ctx)
    if task.category == "C4":
        return verify_c4(task, ctx)
    if task.category == "C5":
        return verify_c5(task, ctx)
    problems, texts = check_evidence(task, ctx)
    if not texts and problems:
        return problems
    for fact in task.expected.get("keyfacts", []):
        if fact.get("derived") or (fact_kind(fact) == "text" and not fact.get("literal")):
            continue
        if not any(fact_present(t, fact) for t in texts):
            problems.append(f"{task.id}: keyfact {fact.get('attribute')}={fact.get('value')} not on any evidence page")
    return problems


# ------------------------------------------------------------------------------------------ C3
PRESETS = ("reset", "sysclk_170mhz_pll_hsi16_apb_div1", "sysclk_170mhz_pll_hsi16_apb2_div2", "sysclk_170mhz_pll_hsi16_apb1_div2",
           "sysclk_80mhz_pll_hsi16_apb_div1")
STATEMENT_MUST_CONTAIN = ("CMSIS", "HAL", "Initial state", "C code block")        # D20: quy ước + trạng thái khởi đầu + dạng câu trả lời nằm trong đề


def _run_for(code: str):
    from eval.schema import RunResult
    return RunResult(system="ref", variant="", task_id="ref", seed=0, final_answer=f"```c\n{code}\n```", turns=[])


def apply_patches(code: str, patches: list[dict]) -> tuple[str | None, str | None]:
    for p in patches:
        if p["find"] not in code:
            return None, f"patch text not found: {p['find'][:60]!r}"
        code = code.replace(p["find"], p["replace"])
    return code, None


def verify_c3(task, ctx) -> list[str]:
    """Lời giải tham chiếu pass functional_sim (+ compile ok), có phép tính tay + bằng chứng, đề nêu quy ước D20; biến thể sai trượt đúng mã."""
    from eval.graders import compile as compile_grader
    from eval.graders import functional_sim
    from eval.score import fail_code

    tid, prov, problems = task.id, task.provenance or {}, []
    ref = prov.get("reference_solution")
    if not ref or not str(ref).strip():
        return [f"{tid}: provenance.reference_solution is missing"]
    if len(str(prov.get("reference_calc", "")).strip()) < 40:
        problems.append(f"{tid}: provenance.reference_calc (hand calculation with formulas and pages) is missing or too short")
    ev_problems, _ = check_evidence(task, ctx)
    problems += ev_problems
    text = task.turns[0]["user"]
    problems += [f"{tid}: the statement must mention {n!r} (D20)" for n in STATEMENT_MUST_CONTAIN if n not in text]
    exp = task.expected
    if exp.get("initial", "reset") not in PRESETS:
        problems.append(f"{tid}: unknown initial preset {exp.get('initial')!r}")
    if not exp.get("spec"):
        problems.append(f"{tid}: expected.spec is empty")
    if problems and any("spec is empty" in p or "unknown initial" in p for p in problems):
        return problems
    res = functional_sim.grade(task, _run_for(str(ref)), ctx)
    if not res["pass"]:
        problems.append(f"{tid}: the reference solution does not pass functional_sim: " + " | ".join(r[:160] for r in res["reasons"]))
    cc = compile_grader.grade(task, _run_for(str(ref)), ctx)
    if cc["details"]["status"] == "error":
        problems.append(f"{tid}: the reference solution does not compile: {cc['reasons'][0][:160]}")
    elif cc["details"]["status"] == "skipped":
        problems.append(f"{tid}: compile check was skipped ({cc['details'].get('reason')}); install clang to verify C3 tasks")
    variants = prov.get("wrong_variants") or []
    if not variants:
        problems.append(f"{tid}: no wrong_variants (each task needs at least one classic mistake that must fail)")
    for v in variants:
        code, err = apply_patches(str(ref), v.get("patches", []))
        if err:
            problems.append(f"{tid}/{v.get('name')}: {err} (patch must apply to the reference solution)")
            continue
        if code == str(ref):
            problems.append(f"{tid}/{v.get('name')}: the variant is identical to the reference solution")
            continue
        r = functional_sim.grade(task, _run_for(code), ctx)
        if r["pass"]:
            problems.append(f"{tid}/{v.get('name')}: should fail functional_sim but passes")
            continue
        got = {fail_code(x) for x in r["reasons"]}
        missing = [c for c in v.get("expect", []) if c not in got]
        if missing:
            problems.append(f"{tid}/{v.get('name')}: expected fail code(s) {missing} but got {sorted(got)}")
    return problems


# ------------------------------------------------------------------------------------------------------ C4
C4_FIRST_TURN = ("CMSIS", "HAL", "Initial state", "C code block")         # D20: quy ước + trạng thái khởi đầu + dạng câu trả lời nằm trong đề (lượt 1)
C4_LAST_TURN = ("complete", "C code block")                                # D25: lượt cuối đòi chương trình HOÀN CHỈNH (sản phẩm cuối được chấm)
C4_FAMILIES = ("PIN_CONFLICT", "NO_SUCH_AF", "INPUT_ONLY", "LEVEL_MISMATCH", "NOT_5V_TOLERANT", "TIMER_SHARED", "CLOCK_LIMIT")


def _conversation(task, answers):
    from eval.schema import RunResult, TurnResult
    return RunResult(system="ref", variant="", task_id=task.id, seed=0, turns=[TurnResult(answer=a) for a in answers], final_answer=answers[-1] if answers else "")


def apply_edits(answers: list[str], edits: list[dict]) -> tuple[list[str] | None, str | None]:
    out = list(answers)
    for e in edits:
        i = e.get("turn", len(out) - 1)
        if not 0 <= i < len(out):
            return None, f"edit refers to turn {i}, the conversation has {len(out)} turns"
        if e["find"] not in out[i]:
            return None, f"edit text not found in turn {i}: {e['find'][:60]!r}"
        out[i] = out[i].replace(e["find"], e["replace"])
    return out, None


def check_conflict_facts(task, facts: list[dict]) -> list[str]:
    """Sự thật làm nên xung đột, đối chiếu DB P1 (bảng AF / loại chân / giới hạn clock — rút từ PDF, độc lập với simulator và DRC).
    af {pin, signal, af} · no_af {pin, signal} · ft {pin, tolerant} · clock_limit {like, max}"""
    import sqlite3

    from eval import sandbox
    db = sandbox.VENDOR / "hwmodel_data" / "hw_specs.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    problems = []
    try:
        for f in facts:
            t = f.get("type")
            if t in ("af", "no_af"):
                row = con.execute("SELECT af FROM pin_functions WHERE chip='stm32g474' AND pin=? AND signal=?", (f["pin"], f["signal"])).fetchall()
                if t == "af" and (f["af"],) not in row:
                    problems.append(f"{task.id}: fact {f} not in the database (found AF {sorted(r[0] for r in row)})")
                if t == "no_af" and row:
                    problems.append(f"{task.id}: fact {f} is false: {f['pin']} does carry {f['signal']} (AF {sorted(r[0] for r in row)})")
            elif t == "ft":
                row = con.execute("SELECT is_5v_tolerant FROM pins WHERE chip='stm32g474' AND pin=?", (f["pin"],)).fetchone()
                if row is None or bool(row[0]) != bool(f["tolerant"]):
                    problems.append(f"{task.id}: fact {f} does not match the database (is_5v_tolerant={row[0] if row else None})")
            elif t == "clock_limit":
                row = con.execute("SELECT max FROM clock_limits WHERE chip='stm32g474' AND parameter LIKE ?", (f["like"],)).fetchall()
                if not any(r[0] not in (None, "") and float(r[0]) == float(f["max"]) for r in row):
                    problems.append(f"{task.id}: fact {f} does not match clock_limits {[r[0] for r in row]}")
            else:
                problems.append(f"{task.id}: unknown conflict fact type {t!r}")
    finally:
        con.close()
    return problems


def verify_c4(task, ctx) -> list[str]:
    """C4 (nhiều lượt, xung đột cài sẵn): đề đúng quy ước (D20/D25), người dùng KHÔNG nhắc xung đột, sự thật xung đột khớp DB + bằng chứng trang,
    hội thoại tham chiếu pass final_state + conflict_detected (chủ động) + biên dịch được, mỗi biến thể sai trượt ĐÚNG mã."""
    from eval.graders import compile as compile_grader
    from eval.graders import conflict_detected, conflicts, final_state
    from eval.score import fail_code

    tid, prov, exp, problems = task.id, task.provenance or {}, task.expected, []
    if not 3 <= len(task.turns) <= 6:
        problems.append(f"{tid}: a C4 task has 3-6 turns, found {len(task.turns)}")
    first, last = task.turns[0]["user"], task.turns[-1]["user"]
    problems += [f"{tid}: the first turn must mention {n!r} (D20)" for n in C4_FIRST_TURN if n not in first]
    problems += [f"{tid}: the last turn must ask for the {n!r} (D25: the final product is graded)" for n in C4_LAST_TURN if n not in last]
    if exp.get("initial", "reset") not in PRESETS:
        problems.append(f"{tid}: unknown initial preset {exp.get('initial')!r}")
    if not exp.get("spec"):
        problems.append(f"{tid}: expected.spec is empty")
    if not exp.get("must_detect"):
        problems.append(f"{tid}: expected.must_detect is empty (every C4 task has at least one planted conflict)")
    if "final_state" not in task.graders or "conflict_detected" not in task.graders:
        problems.append(f"{tid}: graders must include final_state and conflict_detected")
    for m in exp.get("must_detect", []):
        fam = conflicts.parse_code(m["code"])[0]
        if fam not in C4_FAMILIES:
            problems.append(f"{tid}: unknown conflict family {fam!r} in {m['code']!r}")
        for i, turn in enumerate(task.turns):
            hit = conflicts.detect(turn["user"], m["code"]) if fam in C4_FAMILIES else None
            if hit:
                problems.append(f"{tid}: user turn {i} already raises {m['code']} ({hit['sentence'][:80]!r}): the conflict must not be mentioned by the user")
    if len(str(prov.get("reference_calc", "")).strip()) < 40:
        problems.append(f"{tid}: provenance.reference_calc (hand calculation with formulas and pages) is missing or too short")
    ev_problems, _ = check_evidence(task, ctx)
    problems += ev_problems
    problems += check_conflict_facts(task, prov.get("conflict_facts") or [])
    if not prov.get("conflict_facts"):
        problems.append(f"{tid}: provenance.conflict_facts is missing (database cross-check of the planted conflicts)")
    ref = prov.get("reference_solution")
    if not isinstance(ref, dict) or not isinstance(ref.get("turns"), list) or len(ref["turns"]) != len(task.turns) or not all(isinstance(a, str) and a.strip() for a in ref["turns"]):
        return problems + [f"{tid}: provenance.reference_solution.turns must list one answer per user turn ({len(task.turns)})"]
    answers = [str(a) for a in ref["turns"]]
    if problems and any("unknown initial" in p or "spec is empty" in p or "must_detect is empty" in p for p in problems):
        return problems
    run = _conversation(task, answers)
    fs = final_state.grade(task, run, ctx)
    if not fs["pass"]:
        problems.append(f"{tid}: the reference conversation does not pass final_state: " + " | ".join(r[:160] for r in fs["reasons"]))
    cd = conflict_detected.grade(task, run, ctx)
    if not cd["pass"]:
        problems.append(f"{tid}: the reference conversation does not pass conflict_detected: " + " | ".join(r[:160] for r in cd["reasons"]))
    cc = compile_grader.grade(task, run, ctx)
    if cc["details"]["status"] == "error":
        problems.append(f"{tid}: the final reference code does not compile: {cc['reasons'][0][:160]}")
    elif cc["details"]["status"] == "skipped":
        problems.append(f"{tid}: compile check was skipped ({cc['details'].get('reason')}); install clang to verify C4 tasks")
    variants = prov.get("wrong_variants") or []
    for want in ("final_state", "conflict_detected"):
        if not any(v.get("grader") == want for v in variants):
            problems.append(f"{tid}: no wrong_variants with grader {want!r} (each task needs at least one classic mistake per graded dimension)")
    graders = {"final_state": final_state.grade, "conflict_detected": conflict_detected.grade}
    for v in variants:
        name = v.get("name", "?")
        if v.get("grader") not in graders:
            problems.append(f"{tid}/{name}: grader must be final_state or conflict_detected")
            continue
        edited, err = apply_edits(answers, v.get("edits", []))
        if err:
            problems.append(f"{tid}/{name}: {err} (edits must apply to the reference conversation)")
            continue
        if edited == answers:
            problems.append(f"{tid}/{name}: the variant is identical to the reference conversation")
            continue
        if not v.get("expect"):
            problems.append(f"{tid}/{name}: a wrong variant needs a non-empty `expect` (the fail codes it must produce)")
        r = graders[v["grader"]](task, _conversation(task, edited), ctx)
        if r["pass"]:
            problems.append(f"{tid}/{name}: should fail {v['grader']} but passes")
            continue
        got = {fail_code(x) for x in r["reasons"]}
        missing = [c for c in v.get("expect", []) if c not in got]
        if missing:
            problems.append(f"{tid}/{name}: expected fail code(s) {missing} but got {sorted(got)}")
    for v in prov.get("valid_variants") or []:                       # cách sửa HỢP LỆ khác lời giải tham chiếu: spec không được loại oan
        name = v.get("name", "?")
        edited, err = apply_edits(answers, v.get("edits", []))
        if err:
            problems.append(f"{tid}/valid:{name}: {err} (edits must apply to the reference conversation)")
            continue
        r = final_state.grade(task, _conversation(task, edited), ctx)
        if not r["pass"]:
            problems.append(f"{tid}/valid:{name}: a valid alternative fix is rejected by final_state: " + " | ".join(x[:140] for x in r["reasons"]))
    return problems


# ------------------------------------------------------------------------------------------------------ C5
C5_MIN_STEPS = 5                                                            # P5_Handoff Bước 6: mục tiêu cấp hệ thống phân rã >= 5 bước


def verify_c5(task, ctx) -> list[str]:
    """C5 (P5_interfaces §3): (a) lời giải tham chiếu (`provenance.reference_solution.answer`, toàn văn) pass checklist (+ functional_sim/final_state nếu có);
    (b) mỗi `wrong_variants` = {name, answer, must_fail: [id mục checklist]} trượt ĐÚNG các mục đó; (c) không giá trị ẩn nào (`value_patterns`) nằm trong
    lời người dùng; (d) mỗi mục ẩn có từ khoá, có value_patterns và câu trả lời clarify khớp chính value_patterns của nó; (e) biến thể oracle-info suy ra đúng.
    Kèm: reference_calc, bằng chứng trang (nếu khai), checklist có bullets_min >= 5, MỌI task C5 gốc (không phải -O) có grader clarify."""
    from eval import schema
    from eval.graders import checklist, final_state, functional_sim

    tid, prov, problems = task.id, task.provenance or {}, []
    items = task.expected.get("checklist") or []
    ids = {i["id"] for i in items}
    if "checklist" not in task.graders:
        problems.append(f"{tid}: graders must include checklist")
    if not schema.is_oracle(task) and "clarify" not in task.graders:      # review C5 B1: task đủ thông tin cũng cần clarify (đếm câu hỏi thừa)
        problems.append(f"{tid}: every C5 task must list the clarify grader (missing-info: recall; complete-info: unnecessary questions)")
    if not any(i["type"] == "bullets_min" and i["count"] >= C5_MIN_STEPS for i in items):
        problems.append(f"{tid}: the checklist needs a bullets_min item with count >= {C5_MIN_STEPS} (system goal broken into >= {C5_MIN_STEPS} steps)")
    if len(str(prov.get("reference_calc", "")).strip()) < 40:
        problems.append(f"{tid}: provenance.reference_calc (hand calculation with formulas and pages) is missing or too short")
    if prov.get("evidence"):
        problems += check_evidence(task, ctx)[0]
    # (c) + (d): thông tin ẩn
    clar = task.human_policy.get("clarify") or {}
    for h in task.hidden_info:
        pats = h.get("value_patterns") or []
        if not h.get("keywords"):
            problems.append(f"{tid}: hidden_info {h['id']!r} has no keywords")
        if not pats:
            problems.append(f"{tid}: hidden_info {h['id']!r} has no value_patterns (needed to detect leaks and correct guesses)")
        for i, turn in enumerate(task.turns):
            hit = next((p for p in pats if re.search(p, turn["user"], re.I)), None)
            if hit:
                problems.append(f"{tid}: user turn {i} already reveals hidden_info {h['id']!r} (matches {hit!r})")
        if pats and h["id"] in clar and not any(re.search(p, clar[h["id"]], re.I) for p in pats):
            problems.append(f"{tid}: the clarify answer for {h['id']!r} does not match its own value_patterns {pats}")
    # (a) lời giải tham chiếu
    ref = prov.get("reference_solution")
    answer = ref.get("answer") if isinstance(ref, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        return problems + [f"{tid}: provenance.reference_solution.answer (the full reference answer) is missing"]
    run = _conversation(task, [answer])
    res = checklist.grade(task, run, ctx)
    if not res["pass"]:
        problems.append(f"{tid}: the reference answer does not pass checklist: " + " | ".join(r[:160] for r in res["reasons"]))
    for name, fn in (("functional_sim", functional_sim.grade), ("final_state", final_state.grade)):
        if name in task.graders:
            r = fn(task, run, ctx)
            if not r["pass"]:
                problems.append(f"{tid}: the reference answer does not pass {name}: " + " | ".join(x[:160] for x in r["reasons"]))
    # (b) biến thể sai: trượt ĐÚNG các mục khai báo
    variants = prov.get("wrong_variants") or []
    if not variants:
        problems.append(f"{tid}: no wrong_variants (each task needs at least one wrong answer that fails the checklist)")
    for v in variants:
        name, ans, must = v.get("name", "?"), v.get("answer"), v.get("must_fail")
        if not isinstance(ans, str) or not ans.strip():
            problems.append(f"{tid}/{name}: a wrong variant needs a full `answer`")
            continue
        if not isinstance(must, list) or not must:
            problems.append(f"{tid}/{name}: a wrong variant needs a non-empty `must_fail` (checklist item ids)")
            continue
        unknown = sorted(set(must) - ids)
        if unknown:
            problems.append(f"{tid}/{name}: must_fail names unknown checklist item(s) {unknown}")
            continue
        if ans.strip() == answer.strip():
            problems.append(f"{tid}/{name}: the variant is identical to the reference answer")
            continue
        got = sorted(k for k, ok in checklist.grade(task, _conversation(task, [ans]), ctx)["details"]["items"].items() if not ok)
        if got != sorted(set(must)):
            problems.append(f"{tid}/{name}: fails checklist items {got} but must_fail is {sorted(set(must))}")
    # (e) oracle-info
    if task.hidden_info:
        try:
            o = schema.derive_oracle(task)
            schema.Task.from_dict(o.to_dict())
        except ValueError as exc:
            return problems + [f"{tid}: the oracle-info variant cannot be derived ({exc})"]
        want = task.turns[0]["user"] + schema.ORACLE_PREFIX + " ".join(clar[h["id"]] for h in task.hidden_info if h["id"] in clar)
        if (o.id != tid + schema.ORACLE_SUFFIX or o.split != task.split or o.turns[0]["user"] != want or o.turns[1:] != task.turns[1:]
                or o.human_policy.get("clarify") != {} or "clarify" in o.graders or schema.ORACLE_TAG not in o.tags or o.hidden_info
                or o.expected != task.expected):
            problems.append(f"{tid}: the oracle-info variant is not derived as specified (P5_interfaces §3)")
        elif not checklist.grade(o, run, ctx)["pass"]:
            problems.append(f"{tid}: the reference answer does not pass the checklist of the oracle-info variant")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=ROOT / "eval" / "tasks")
    ap.add_argument("--categories", default="C2,C6")
    ap.add_argument("--split")
    ap.add_argument("--include-needs-human", action="store_true")
    a = ap.parse_args(argv)
    ctx = GradeContext.load()
    tasks = load_tasks(a.tasks, split=a.split, categories=a.categories.split(","), include_needs_human=a.include_needs_human)
    bad = 0
    for t in tasks:
        for p in verify_task(t, ctx):
            print("PROBLEM", p)
            bad += 1
    print(f"{len(tasks)} task kiểm tra, {bad} vấn đề")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
