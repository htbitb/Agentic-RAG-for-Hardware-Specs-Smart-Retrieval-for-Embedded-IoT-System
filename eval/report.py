"""Sinh report.md + figures/ từ scores.jsonl (+ runs.jsonl, manifest.json).

    python -m eval.report --run eval/results/<timestamp>

Nội dung: bảng chính (hệ x nhóm, TSR + CI bootstrap theo task), chỉ số phụ, so sánh cặp (Δ + CI + McNemar),
phân loại lỗi, lỗi hạ tầng, ví dụ định tính, manifest tái lập. Không gọi LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

from eval import stats
from eval.envload import LLMConfig, redact
from eval.graders import hitl, process
from eval.schema import grounded_pass, is_oracle, load_tasks

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ORDER = ["S0", "S1", "S2", "S2D", "S3@P4", "S3@P5", "S3"]
SYSTEM_TITLES = {"S0": "S0 (Direct LLM)", "S1": "S1 (Native RAG)", "S2": "S2 (Agent v1 đóng băng)",
                 "S2D": "S2D (Agent v1 + dữ liệu P1)", "S3@P4": "S3@P4 (Agent v3, runtime+Gate P4)",
                 "S3@P5": "S3@P5 (Agent v3 + HITL v2, sửa D36/D37)", "S3": "S3 (Agent v3)"}
PAIRS = [("S1", "S0"), ("S2", "S1"), ("S2", "S0"), ("S2D", "S2"), ("S2D", "S1"), ("S2D", "S0"), ("S3@P4", "S2D"), ("S3@P4", "S0"),
         ("S3@P5", "S3@P4"), ("S3@P5", "S0"), ("S3@P5", "S2D")]
CAT_ORDER = ["C1", "C2", "C3", "C4", "C5", "C5-O", "C6", "C7", "C8", "C9", "FI"]
# nhóm CHẨN ĐOÁN (P5): biến thể oracle-info của C5 hiện thành cột riêng "C5-O" nhưng KHÔNG vào cột/hàng "Tổng" (không đếm một task C5 hai lần)
DIAGNOSTIC_GROUPS = {"C5-O"}


# ------------------------------------------------------------------- tổng hợp
def _valid(rows):
    return [r for r in rows if r["tsr_pass"] is not None]


def _primary(rows):
    """Hàng tính vào 'Tổng': bỏ nhóm chẩn đoán (C5-O)."""
    return [r for r in rows if r["category"] not in DIAGNOSTIC_GROUPS]


def relabel_oracle(scores):
    """Hàng của biến thể oracle-info (`<id>-O`, P5) mang nhóm hiển thị `<nhóm>-O` (vd C5-O) để mọi bảng theo nhóm tách C5 thường / C5 oracle-info.
    scores.jsonl giữ nguyên category thật (C5)."""
    return [{**r, "category": f"{r['category']}-O"} if is_oracle(r["task_id"]) and not str(r["category"]).endswith("-O") else r for r in scores]


def task_means(rows, category=None, key=lambda r: r["tsr_pass"]) -> dict[str, float]:
    """task_id -> tỷ lệ pass trung bình qua các seed (bỏ run lỗi hạ tầng và run mà `key` trả None)."""
    acc = defaultdict(list)
    for r in _valid(rows):
        v = key(r)
        if v is not None and (category is None or r["category"] == category):
            acc[r["task_id"]].append(1.0 if v else 0.0)
    return {t: float(np.mean(v)) for t, v in sorted(acc.items())}      # sắp theo task_id: bootstrap không phụ thuộc thứ tự dòng


def discordant(a: dict, b: dict) -> tuple[int, int]:
    """Cặp bất đồng theo phiếu đa số (strict > 0.5) trên các task chung: (a đúng/b sai, a sai/b đúng)."""
    common = sorted(set(a) & set(b))
    x = sum(1 for t in common if a[t] > 0.5 and not b[t] > 0.5)
    y = sum(1 for t in common if b[t] > 0.5 and not a[t] > 0.5)
    return x, y


def _pct(v: float) -> str:
    return "—" if v != v else f"{v * 100:.1f}%"


def _ci(m, lo, hi) -> str:
    return "—" if m != m else f"{m * 100:.1f}% [{lo * 100:.1f}–{hi * 100:.1f}]"


def label(system: str, variant: str | None) -> str:
    """Nhãn hiển thị của (hệ, biến thể): 'S3@P4' hoặc 'S3@P4 [-Planner]' (ablation)."""
    return f"{system} [{variant}]" if variant else system


def _base(system_label: str) -> str:
    return system_label.split(" [", 1)[0]


def relabel_variants(scores, runs):
    """Biến thể ablation (`variant` khác rỗng) trở thành một hệ riêng có nhãn `hệ [biến thể]`, để mọi bảng nhóm theo `system` không gộp
    chúng vào hệ chính. Hệ không có biến thể giữ nguyên (đối tượng cũ)."""
    return ([{**r, "system": label(r["system"], r["variant"])} if r.get("variant") else r for r in scores],
            [replace(r, system=label(r.system, r.variant)) if r.variant else r for r in runs])


def _systems(scores) -> list[str]:
    present = {r["system"] for r in scores}
    return sorted(present, key=lambda s: (SYSTEM_ORDER.index(_base(s)) if _base(s) in SYSTEM_ORDER else len(SYSTEM_ORDER), s))


def _cats(scores) -> list[str]:
    present = {r["category"] for r in scores}
    return [c for c in CAT_ORDER if c in present]


def _table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def _per_task_ratio(rows, grader, num_fn, den_fn, cats=None):
    num, den = defaultdict(float), defaultdict(float)
    for r in _valid(rows):
        g = r["graders"].get(grader)
        if g is None or (cats and r["category"] not in cats):
            continue
        num[r["task_id"]] += num_fn(g["details"])
        den[r["task_id"]] += den_fn(g["details"])
    ids = sorted(num)
    return [num[i] for i in ids], [den[i] for i in ids]


# ------------------------------------------------------------------- các mục
def main_table(scores, n_boot) -> str:
    cats = _cats(scores)
    rows = []
    for s in _systems(scores):
        sr = [r for r in scores if r["system"] == s]
        cells = []
        for c in cats:
            cells.append(_ci(*stats.bootstrap_ci(list(task_means(sr, c).values()), n_boot=n_boot, seed=11)) if task_means(sr, c) else "—")
        cells.append(_ci(*stats.bootstrap_ci(list(task_means(_primary(sr)).values()), n_boot=n_boot, seed=12)))
        rows.append([s, *cells])
    return _table(["Hệ", *cats, "Tổng"], rows)


def grounded_table(scores, n_boot) -> str:
    """Grounded TSR: chỉ trên các nhóm có grader citation (tra cứu có nguồn: C1, C2, ...)."""
    cats = [c for c in _cats(scores) if any(grounded_pass(r) is not None for r in scores if r["category"] == c)]
    if not cats:
        return "_Không có task nào có grader citation._"
    rows = []
    for s in _systems(scores):
        sr = [r for r in scores if r["system"] == s]
        cells = []
        for c in cats:
            tm = task_means(sr, c, key=grounded_pass)
            cells.append(_ci(*stats.bootstrap_ci(list(tm.values()), n_boot=n_boot, seed=31)) if tm else "—")
        tm = task_means([r for r in sr if r["category"] in cats])
        g = task_means([r for r in sr if r["category"] in cats], key=grounded_pass)
        cells.append(_ci(*stats.bootstrap_ci(list(g.values()), n_boot=n_boot, seed=32)) if g else "—")
        cells.append(_ci(*stats.bootstrap_ci(list(tm.values()), n_boot=n_boot, seed=33)) if tm else "—")
        rows.append([s, *cells])
    return _table(["Hệ", *cats, "Grounded (gộp)", "TSR thường trên cùng tập (đối chiếu)"], rows)


def secondary_table(scores, runs, n_boot) -> str:
    infra_keys = {(x["system"], x["task_id"], x["seed"]) for x in scores if x["infra"]}
    runs_by_sys = defaultdict(list)
    for r in runs:
        if (r.system, r.task_id, r.seed) not in infra_keys:       # run lỗi hạ tầng (usage ~0) làm lệch trung bình xuống thấp
            runs_by_sys[r.system].append(r)
    rows = []
    for s in _systems(scores):
        sr = [r for r in scores if r["system"] == s]
        h = stats.bootstrap_ratio(*_per_task_ratio(sr, "numeric_claims", lambda d: len(d["unsupported"]), lambda d: d["claims"]), n_boot=n_boot, seed=1)
        cp = stats.bootstrap_ratio(*_per_task_ratio(sr, "citation", lambda d: d["valid"], lambda d: d["valid"] + d["invalid"]), n_boot=n_boot, seed=2)
        safety_acc = stats.bootstrap_ci(list(task_means(sr, "C6").values()), n_boot=n_boot, seed=3)
        over = stats.bootstrap_ratio(*_per_task_ratio(sr, "safety", lambda d: 1.0 if d["over_refusal"] else 0.0,
                                                      lambda d: 1.0 if d["expected"] != "refuse" else 0.0), n_boot=n_boot, seed=4)
        unsafe = stats.bootstrap_ratio(*_per_task_ratio(sr, "safety", lambda d: 1.0 if d["unsafe"] else 0.0, lambda d: 1.0), n_boot=n_boot, seed=5)
        asr = stats.bootstrap_ratio(*_per_task_ratio(sr, "attack", lambda d: 1.0 if d["attack_success"] else 0.0, lambda d: 1.0), n_boot=n_boot, seed=6)
        absn = stats.bootstrap_ci(list(task_means(sr, "C8").values()), n_boot=n_boot, seed=7)
        rr = runs_by_sys.get(s, [])
        n_tasks = len({r.task_id for r in rr}) or 1
        tin = np.mean([r.usage.get("tokens_in", 0) for r in rr]) if rr else float("nan")
        tout = np.mean([r.usage.get("tokens_out", 0) for r in rr]) if rr else float("nan")
        usd = np.mean([r.usage.get("usd", 0.0) for r in rr]) if rr else float("nan")
        lat = [r.latency_s for r in rr]
        rows.append([s, _ci(*h), _ci(*cp), _ci(*safety_acc), _ci(*over), _ci(*unsafe), _ci(*asr), _ci(*absn),
                     f"{tin:.0f} / {tout:.0f}", f"{usd:.5f}", f"{stats.percentile(lat, 50):.1f}", f"{stats.percentile(lat, 95):.1f}"])
    return _table(["Hệ", "Hallucination Rate", "Citation Precision", "Safety Acc. (C6)", "Over-refusal (C6)", "Unsafe compliance (C6)",
                   "ASR (C7, thấp hơn là tốt hơn)", "Abstention Acc. (C8)", "tokens in/out mỗi run", "USD/task", "latency p50 (s)", "latency p95 (s)"], rows)


def _pass_at(rows, k_first: bool) -> float:
    """Pass@1 = tỷ lệ task đạt ở seed đầu tiên (nhỏ nhất); Pass@k = tỷ lệ task đạt ở ít nhất một seed."""
    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task_id"]].append(r)
    if not by_task:
        return float("nan")
    hit = 0
    for rs in by_task.values():
        rs = sorted(rs, key=lambda r: r["seed"])
        hit += bool(rs[0]["tsr_pass"]) if k_first else any(r["tsr_pass"] for r in rs)
    return hit / len(by_task)


def c3_section(scores, tasks_by_id, n_boot) -> str:
    """C3: TSR/Pass@k của functional_sim, tỷ lệ code phân tích được, compile (ok/error/skipped), mã lỗi theo simulator, TSR theo loại task."""
    c3 = [r for r in scores if r["category"] == "C3" and not r["infra"]]
    if not c3:
        return ""
    systems = [s for s in _systems(scores) if any(r["system"] == s for r in c3)]
    k = max((len({r["seed"] for r in c3 if r["task_id"] == t}) for t in {r["task_id"] for r in c3}), default=1)
    rows = []
    for s in systems:
        sr = [r for r in c3 if r["system"] == s]
        fs = [r["graders"].get("functional_sim", {}).get("details", {}) for r in sr]
        with_code = [d for d in fs if d.get("blocks")]
        analysable = sum(1 for d in with_code if d.get("analysis_ok"))
        comp = Counter(r["graders"].get("compile", {}).get("details", {}).get("status", "n/a") for r in sr)
        tm = list(task_means(sr, "C3").values())
        rows.append([s, _ci(*stats.bootstrap_ci(tm, n_boot=n_boot, seed=41)), _pct(_pass_at(sr, True)), _pct(_pass_at(sr, False)),
                     f"{analysable}/{len(with_code)}", len(fs) - len(with_code), comp["ok"], comp["error"], comp["skipped"]])
    t1 = _table(["Hệ", "TSR C3", "Pass@1", f"Pass@{k}", "Phân tích được", "Không có code", "compile ok", "compile error", "compile skipped"], rows)
    counts = {s: Counter() for s in systems}
    for r in c3:
        if r["tsr_pass"] is False:
            for code in set(r["fail_codes"]) or {"unspecified"}:
                counts[r["system"]][code] += 1
    codes = sorted({c for cnt in counts.values() for c in cnt}, key=lambda c: (-sum(cnt[c] for cnt in counts.values()), c))
    t2 = _table(["Mã lỗi C3 (sim_violation:<mã mô phỏng>, inactive:<lý do>, wrong_*, unsupported_construct:<loại>, unmodeled, no_code)", *systems],
                [[c, *[counts[s][c] for s in systems]] for c in codes]) if codes else "_Không có run C3 thất bại._"
    types = sorted({(tasks_by_id[r["task_id"]].tags[0] if tasks_by_id.get(r["task_id"]) and tasks_by_id[r["task_id"]].tags else "?") for r in c3})
    rows3 = []
    for ty in types:
        ids = {r["task_id"] for r in c3 if tasks_by_id.get(r["task_id"]) and tasks_by_id[r["task_id"]].tags and tasks_by_id[r["task_id"]].tags[0] == ty}
        cell = [_pct(float(np.mean(list(task_means([r for r in c3 if r["system"] == s and r["task_id"] in ids]).values()) or [float("nan")]))) for s in systems]
        rows3.append([ty, *cell, len(ids)])
    t3 = _table(["Loại task (tag đầu)", *systems, "Số task"], rows3)
    return ("## C3 — chức năng (functional_sim) và compile\n"
            "`functional_sim` (gate TSR) chạy code trong câu trả lời qua `analyze_c_code` → `simulate_register_writes` của bản hwmodel ĐÓNG BĂNG (D19) và so `effects` với spec chức năng; "
            "`compile` (clang ARM `-fsyntax-only`) là chỉ số riêng, `skipped` không bao giờ là pass. **Phân tích được** = `analyze_c_code` thành công / số run có code. "
            "Pass@1 = đạt ở seed đầu; Pass@k = đạt ở ít nhất một seed.\n\n" + t1 + "\n\n" + t2 + "\n\n**TSR C3 theo loại task** (trung bình theo seed rồi theo task, không CI vì n nhỏ)\n\n" + t3)


def c4_section(scores, tasks_by_id, n_boot) -> str:
    """C4 (P3): final_state (sản phẩm cuối), conflict_detected (nêu xung đột cài sẵn một cách CHỦ ĐỘNG — D25), Proactive detection rate theo hệ và theo họ xung đột."""
    c4 = [r for r in scores if r["category"] == "C4" and not r["infra"]]
    if not c4:
        return ""
    systems = [s for s in _systems(scores) if any(r["system"] == s for r in c4)]
    rows = []
    for s in systems:
        sr = [r for r in c4 if r["system"] == s]
        items = [i for r in sr for i in (r["graders"].get("conflict_detected", {}).get("details", {}).get("items") or [])]
        late = sum(1 for i in items if i["detected"] and not i["proactive"])
        missed = sum(1 for i in items if not i["detected"])
        must_not = sum(len(r["graders"].get("conflict_detected", {}).get("details", {}).get("must_not") or []) for r in sr)
        fallback = sum(1 for r in sr if (r["graders"].get("final_state", {}).get("details", {}).get("fallback")))
        no_code = sum(1 for r in sr if r["graders"].get("final_state", {}).get("details", {}).get("source_turn", 0) is None)

        def mean_pass(grader):
            acc = defaultdict(list)
            for r in sr:
                g = r["graders"].get(grader)
                if g is not None:
                    acc[r["task_id"]].append(1.0 if g["pass"] else 0.0)
            return [float(np.mean(v)) for _, v in sorted(acc.items())]

        pro = stats.bootstrap_ratio(*_per_task_ratio(sr, "conflict_detected", lambda d: d["n_proactive"], lambda d: d["n_items"], cats={"C4"}), n_boot=n_boot, seed=51)
        det = stats.bootstrap_ratio(*_per_task_ratio(sr, "conflict_detected", lambda d: d["n_detected"], lambda d: d["n_items"], cats={"C4"}), n_boot=n_boot, seed=52)
        rows.append([s, _ci(*stats.bootstrap_ci(list(task_means(sr, "C4").values()), n_boot=n_boot, seed=53)), _pct(float(np.mean(mean_pass("final_state") or [float("nan")]))),
                     _pct(float(np.mean(mean_pass("conflict_detected") or [float("nan")]))), f"{_ci(*pro)} ({sum(1 for i in items if i['proactive'])}/{len(items)})",
                     f"{_ci(*det)}", late, missed, must_not, fallback, no_code])
    t1 = _table(["Hệ", "TSR C4", "final_state", "conflict_detected", "Proactive detection rate", "Phát hiện (bất kể lượt)", "Phát hiện muộn", "Bỏ sót",
                 "Vi phạm must_not", "Code lấy từ lượt trước", "Không có code"], rows)
    sens = []
    for s in systems:
        its = [i for r in c4 if r["system"] == s for i in (r["graders"].get("conflict_detected", {}).get("details", {}).get("items") or [])]
        n = len(its)
        cells = [f"{_pct(sum(1 for i in its if i.get(k)) / n) if n else '—'} ({sum(1 for i in its if i.get(k))}/{n})" for k in ("proactive_from0", "proactive", "proactive_w2")]
        sens.append([s, *cells])
    t_sens = _table(["Hệ", "D25 gốc: tính cả nêu ở lượt TRƯỚC (nới hơn)", "Dùng để chấm: chỉ từ lượt gây xung đột (`from_turn`)", "Như cột 2, cho phép cảnh báo ở câu liền sau (nới 2 câu)"], sens)
    families = sorted({i["code"].split(":", 1)[0] for r in c4 for i in (r["graders"].get("conflict_detected", {}).get("details", {}).get("items") or [])})
    rows2 = []
    for fam in families:
        cell = []
        for s in systems:
            its = [i for r in c4 if r["system"] == s for i in (r["graders"].get("conflict_detected", {}).get("details", {}).get("items") or []) if i["code"].split(":", 1)[0] == fam]
            n = sum(1 for i in its if i["proactive"])
            cell.append(f"{_pct(n / len(its)) if its else '—'} ({n}/{len(its)})")
        rows2.append([fam, *cell])
    t2 = _table(["Họ xung đột (mục chủ động / tổng số mục × seed)", *systems], rows2) if rows2 else "_Không có mục must_detect._"
    counts = {s: Counter() for s in systems}
    for r in c4:
        if r["tsr_pass"] is False:
            for code in set(r["fail_codes"]) or {"unspecified"}:
                counts[r["system"]][code] += 1
    codes = sorted({c for cnt in counts.values() for c in cnt}, key=lambda c: (-sum(cnt[c] for cnt in counts.values()), c))
    t3 = _table(["Mã lỗi C4 (final_state: sim_violation:<mã>, wrong_*, forbidden_pin_used, no_code...; conflict_detected: conflict_missed:<họ>, conflict_late:<họ>, must_not:unsafe_connection)",
                 *systems], [[c, *[counts[s][c] for s in systems]] for c in codes]) if codes else "_Không có run C4 thất bại._"
    return ("## C4 — thiết kế nhiều lượt có xung đột cài sẵn\n"
            "`final_state` (gate) chấm **khối code ở lượt cuối** bằng `functional_sim` với nhiều spec (D25; hệ nào cũng cùng cách, kể cả S3 — Board State không dùng để chấm). "
            "`conflict_detected` (gate) kiểm bộ nhận diện tất định (eval/graders/conflicts.py) xem mỗi xung đột cài sẵn có được **nêu ở lượt gây xung đột hoặc sớm hơn** hay không; "
            "nêu sau khi người dùng đã hỏi là `muộn`, không nêu là `bỏ sót`. **Proactive detection rate** = số mục xung đột được nêu chủ động / tổng số mục (gộp seed), CI bootstrap theo task. "
            "TSR C4 = đạt cả hai grader.\n\n" + t1 + "\n\n**Proactive detection rate theo họ xung đột**\n\n" + t2 +
            "\n\n**Độ nhạy của Proactive detection rate** (chỉ để đọc độ bất định của bộ nhận diện — recall trên diễn đạt tự nhiên < 1; không dùng để chấm): "
            "cột 1 là D25 nguyên văn (một câu nhắc giới hạn ở lượt trước cũng tính), cột 2 là cách chấm thực tế (chỉ từ lượt người dùng đưa ra yêu cầu xung đột), cột 3 nới cách nhận diện (cảnh báo ở câu liền sau). "
            "Giá trị thật nằm quanh khoảng này.\n\n" + t_sens + "\n\n" + t3)


def _frac(n, d) -> str:
    return f"{n}/{d} ({n / d * 100:.1f}%)" if d else "N/A"


def _num(v, fmt="{:.2f}") -> str:
    return "N/A" if v is None else fmt.format(v)


def process_section(scores) -> str:
    """Chỉ số quá trình (P4, plan/P4_interfaces.md §5) từ `graders.process` — chỉ báo cáo. Chỉ xuất hiện khi có ít nhất một hệ có trace v3;
    hệ không có trace v3 hiện N/A."""
    aggs = {s: process.aggregate([r for r in scores if r["system"] == s]) for s in _systems(scores)}
    v3 = [s for s, a in aggs.items() if a["v3"]]
    if not v3:
        return ""
    def rows(fn, width):
        return [[s, *(fn(aggs[s]) if aggs[s]["v3"] else ["N/A"] * width)] for s in aggs]

    t0 = _table(["Hệ", "Run có trace v3", "Run có sản phẩm", "Kiểm tra đầu fail", "Self-Correction Rate", "…trong đó sản phẩm cuối cũng pass grader độc lập",
                 "Mean Repair Iterations"],
                rows(lambda a: [a["n_runs"], a["with_product"], a["first_failed"], _frac(a["self_corrected"], a["first_failed"]),
                                _frac(a["self_corrected_tsr"], a["self_corrected"]), _num(a["mean_repair_iterations"])], 6))
    t1 = _table(["Hệ", "plan_updated (tổng)", "plan_updated sau replan_required / gate fail", "replan_required",
                 "Replan Effectiveness (kết thúc được chấp nhận)", "Replan Effectiveness (pass grader độc lập)", "plan_updated ≥ 1 trên C3/C4"],
                rows(lambda a: [a["plan_updated"], a["plan_updated_after_trigger"], a["replan_required"],
                                _frac(a["replan_ok_accepted"], a["replan_required"]), _frac(a["replan_ok_tsr"], a["replan_required"]),
                                _frac(a["design_with_plan"], a["design_runs"])], 6))
    t2 = _table(["Hệ", "finish (tổng)", "Premature-Finish Rate", "Lượt escalated", "Task kết thúc escalated", "Step Efficiency (tool call / task thành công)",
                 "Tỷ lệ gọi trùng"],
                rows(lambda a: [a["finish_total"], _frac(a["finish_rejected"], a["finish_total"]), a["escalated_turns"],
                                _frac(a["ended_escalated"], a["n_runs"]), _num(a["step_efficiency"]), _frac(a["dup_calls"], a["tool_calls"])], 6))
    codes = sorted({c for s in v3 for c in aggs[s]["gate_fail_codes"]}, key=lambda c: (-sum(aggs[s]["gate_fail_codes"].get(c, 0) for s in v3), c))
    t3 = (_table(["Mã gate fail (finding mức error của gate_result fail)", *v3], [[c, *[aggs[s]["gate_fail_codes"].get(c, 0) for s in v3]] for c in codes])
          if codes else "_Không có gate_result fail._")
    t4 = _table(["Hệ", "Self-Correction (vật lý: G2/G3/G5/simulator/DRC)", "…sản phẩm cuối cũng pass grader độc lập", "…trong đó hỗn hợp G1 + vật lý",
                 "Self-Correction (provenance: G1)", "…sản phẩm cuối cũng pass grader độc lập", "Khác (G4 / không rõ)", "Run first_failed có phân lớp"],
                rows(lambda a: [_frac(a["sc_physical_corrected"], a["sc_physical_first_failed"]), _frac(a["sc_physical_corrected_tsr"], a["sc_physical_corrected"]),
                                a["sc_mixed_first_failed"], _frac(a["sc_provenance_corrected"], a["sc_provenance_first_failed"]),
                                _frac(a["sc_provenance_corrected_tsr"], a["sc_provenance_corrected"]), _frac(a["sc_other_corrected"], a["sc_other_first_failed"]),
                                f"{a['sc_split_runs']}/{a['first_failed']}"], 7))
    return ("## Chỉ số quá trình (S3)\n"
            "Tính trên trace v3 của `RunResult.trace` (hệ có sự kiện `run_started`); định nghĩa chính xác trong `eval/graders/process.py`. **Báo cáo, không gating**: "
            "không ảnh hưởng TSR. Mỗi mục là một run (task × seed), gộp seed, không CI. Hệ không có trace v3 hiện N/A.\n\n"
            "**Lưu ý trung thực:** Self-Correction Rate đo theo Gate của chính agent (requirement do agent ghi vào Board State) và các lần mô phỏng agent tự gọi, "
            "nên một run 'tự sửa' vẫn có thể trượt grader độc lập; vì vậy luôn đọc cột 'sản phẩm cuối cũng pass grader độc lập' ngay bên cạnh, và đối chiếu với TSR.\n\n"
            "**Tự sửa** — Self-Correction Rate = run có kiểm tra ĐẦU fail và kiểm tra CUỐI pass / run có kiểm tra đầu fail (kiểm tra = `gate_result` + `sim_result` của agent gắn artifact); "
            "Mean Repair Iterations = số kiểm tra fail trung bình của các run tự sửa.\n\n" + t0 +
            "\n\n**Lập lại kế hoạch** — Replan Effectiveness = `replan_required` mà lượt đó kết thúc bằng finish được chấp nhận (hoặc task pass grader độc lập) / tổng `replan_required`.\n\n" + t1 +
            "\n\n**Kết thúc và hiệu quả bước** — Premature-Finish Rate = finish bị Gate từ chối / tổng finish (kể cả ngầm); Step Efficiency = tổng tool call do agent gọi của mọi run / số run thành công; "
            "gọi trùng = cùng tool + args trong cùng lượt.\n\n" + t2 + "\n\n**Phân bố mã gate fail**\n\n" + t3 +
            "\n\n**Self-Correction theo lớp lỗi (D35)** — con số gộp ở bảng đầu chủ yếu là lỗi nguồn gốc (G1); bảng này tách: *vật lý* = run có kiểm tra fail "
            "do simulator của agent hoặc finding error của G2/G3/G5/DRC (kể cả run có thêm G1 — cột 'hỗn hợp'); *provenance* = run CHỈ fail vì G1; "
            "*khác* = G4 hoặc gate fail không có finding error. Hàng chấm trước P5 không có phân lớp (cột cuối < first_failed ⇒ cần chấm lại).\n\n" + t4)


def hitl_section(scores, n_boot) -> str:
    """P5 (plan/P5_interfaces.md §5): Clarification Precision/Recall theo nửa thiếu/đủ thông tin, câu hỏi thừa/task trên task đủ thông tin,
    Resume Success, Autonomy Ratio, ask_human thừa, Replan sau Reject, TSR C5 thường vs oracle-info. Chỉ báo cáo, không gating."""
    if not any(r["graders"].get("clarify") or r["graders"].get("hitl") for r in scores) and not any(r["category"] in ("C5", "C5-O") for r in scores):
        return ""
    systems = _systems(scores)
    rows1 = []
    for s in systems:
        c = hitl.clarify_aggregate([r for r in scores if r["system"] == s])
        m, k = c["missing"], c["complete"]
        if m["runs"] or k["runs"]:
            rows1.append([s, _frac(m["necessary"], m["asked"]), _frac(m["covered"], m["required"]), m["guessed"], f"{m['from_interrupt']} / {m['from_text']}",
                          m["runs"], _num(k["unnecessary_per_run"]), f"{k['from_interrupt']} / {k['from_text']}", k["runs"]])
    t1 = (_table(["Hệ", "Clarification Precision (thiếu thông tin)", "Clarification Recall (thiếu thông tin)", "Đoán trùng giá trị ẩn (không hỏi)",
                  "Câu hỏi thiếu tt: interrupt / văn bản", "Run thiếu tt", "Câu hỏi thừa / run (đủ thông tin)", "Câu hỏi đủ tt: interrupt / văn bản", "Run đủ tt"], rows1)
          if rows1 else "_Không có run nào có grader `clarify`._")
    complete = sorted({r["task_id"] for r in scores if ((r["graders"].get("clarify") or {}).get("details") or {}).get("required") == 0})
    rows2 = []
    for tid in complete:
        cells = []
        for s in systems:
            ds = [r["graders"]["clarify"]["details"] for r in _valid(scores) if r["system"] == s and r["task_id"] == tid and r["graders"].get("clarify")]
            cells.append(f"{sum(d['unnecessary'] for d in ds) / len(ds):.2f} ({len(ds)} run)" if ds else "—")
        rows2.append([tid, *cells])
    t2 = _table(["Task đủ thông tin (câu hỏi thừa trung bình mỗi run)", *systems], rows2) if rows2 else "_Không có task C5 đủ thông tin._"
    aggs = {s: hitl.aggregate([r for r in scores if r["system"] == s]) for s in systems}
    rows3 = [[s, a["n_runs"], a["runs_with_interaction"], a["interrupts"], ", ".join(f"{k}×{v}" for k, v in sorted(a["by_kind"].items())) or "—",
              _frac(a["resume_ok"], a["interrupts"]), _num(a["autonomy_ratio"]), _num(a["interventions_per_task"]), a["text_questions"],
              a["ask_human_unnecessary"], _frac(a["replan_after_reject"], a["rejects"]), a["hitl_loop_runs"]] for s, a in aggs.items() if a["hitl"]]
    t3 = (_table(["Hệ", "Run", "Run có tương tác", "Interrupt", "Theo loại", "Resume Success", "Autonomy Ratio", "Can thiệp TB / task",
                  "Lượt bổ sung (câu hỏi văn bản)", "ask_human thừa", "Replan sau Reject", "Run kẹt (hitl_loop)"], rows3)
          if rows3 else "_Không có run nào có tương tác người–hệ._")
    rows4 = []
    for s in systems:
        sr = [r for r in scores if r["system"] == s]
        tn, to = task_means(sr, "C5"), task_means(sr, "C5-O")
        if not tn and not to:
            continue
        common = sorted(t for t in tn if f"{t}-O" in to)
        if common:
            d, lo, hi = stats.paired_bootstrap_diff([to[f"{t}-O"] for t in common], [tn[t] for t in common], n_boot=n_boot, seed=61)
            delta = f"{d * 100:+.1f} pp [{lo * 100:+.1f}, {hi * 100:+.1f}]"
        else:
            delta = "—"
        rows4.append([s, _ci(*stats.bootstrap_ci(list(tn.values()), n_boot=n_boot, seed=62)) if tn else "—",
                      _ci(*stats.bootstrap_ci(list(to.values()), n_boot=n_boot, seed=63)) if to else "—", delta, len(tn), len(common)])
    t4 = (_table(["Hệ", "TSR C5 (thường)", "TSR C5-O (oracle-info)", "Δ oracle − thường trên task có cả hai (CI 95% bootstrap cặp)", "Task C5", "Cặp"], rows4)
          if rows4 else "_Không có run C5._")
    return ("## C5 và Human-in-the-loop (P5)\n"
            "Chỉ báo cáo, **không gating** (TSR C5 gate bởi `checklist` + `functional_sim`/`final_state` khi có code). Câu hỏi được ghi bởi runner thành sự kiện "
            "`human_reply` cho MỌI hệ: interrupt `ask_human` của hệ có HITL và câu hỏi hướng tới người dùng trong câu trả lời của baseline (quy tắc tất định "
            "`eval/sim_human.py::detect_question`; baseline được nhận câu trả lời như một lượt người dùng bổ sung, tối đa `max_answers`). "
            "**Clarification Precision** = câu hỏi cần thiết / tổng câu hỏi làm rõ (gộp mọi run); **Recall** = mục ẩn bắt buộc được hỏi / tổng mục bắt buộc. "
            "Task đủ thông tin chỉ báo số câu hỏi thừa. 'Đoán trùng' = không hỏi mà câu trả lời cuối khớp giá trị ẩn (không gate).\n\n" + t1 +
            "\n\n**Câu hỏi thừa trên task đủ thông tin**\n\n" + t2 +
            "\n\n**Interrupt / Resume** — Resume Success = resume tới trạng thái hợp lệ (không `error`) / số interrupt runner đã thấy; Autonomy Ratio = tool call của "
            "agent (trừ `ask_human`) / (tool call + interrupt), chỉ cho hệ có trace v3; Can thiệp TB/task = (interrupt + lượt bổ sung của baseline) / số run; "
            "ask_human thừa = interrupt `clarify` không cần thiết; Replan sau Reject = lần từ chối (approval) có `plan_updated` trước interrupt kế tiếp / số lần từ chối. "
            "Định nghĩa: `eval/graders/hitl.py`.\n\n" + t3 +
            "\n\n**TSR C5 thường so với oracle-info** — biến thể `C5-xxx-O` đưa sẵn mọi thông tin ẩn ở lượt đầu (tách năng lực thiết kế khỏi năng lực hỏi lại); "
            "cột C5-O không vào 'Tổng' của bảng chính.\n\n" + t4)


def pairwise_table(scores, n_boot) -> str:
    cats = _cats(scores)
    systems = set(_systems(scores))
    rows = []
    for a, b in PAIRS:
        if a not in systems or b not in systems:
            continue
        ta = {c: task_means(_primary([r for r in scores if r["system"] == a]) if c is None else [r for r in scores if r["system"] == a], c) for c in [None, *cats]}
        tb = {c: task_means(_primary([r for r in scores if r["system"] == b]) if c is None else [r for r in scores if r["system"] == b], c) for c in [None, *cats]}
        for c in [*cats, None]:
            common = sorted(set(ta[c]) & set(tb[c]))
            if not common:
                continue
            d, lo, hi = stats.paired_bootstrap_diff([ta[c][t] for t in common], [tb[c][t] for t in common], n_boot=n_boot, seed=21)
            x, y = discordant(ta[c], tb[c])
            rows.append([f"{a} vs {b}", c or "Tổng", f"{d * 100:+.1f} pp [{lo * 100:+.1f}, {hi * 100:+.1f}]",
                         f"p={stats.mcnemar_exact(x, y):.3f}", f"{x}/{y}", len(common)])
    if not rows:
        return "_Cần ít nhất hai hệ để so sánh cặp._"
    return _table(["Cặp", "Nhóm", "ΔTSR (điểm %, CI 95% bootstrap cặp)", "McNemar (chính xác, đa số phiếu theo seed)",
                   "b/c (A đúng-B sai / A sai-B đúng)", "Số task"], rows)


def taxonomy_table(scores) -> str:
    systems = _systems(scores)
    counts = {s: Counter() for s in systems}
    for r in scores:
        if r["tsr_pass"] is False:
            for code in set(r["fail_codes"]) or {"unspecified"}:
                counts[r["system"]][code] += 1
    codes = sorted({c for cnt in counts.values() for c in cnt}, key=lambda c: (-sum(cnt[c] for cnt in counts.values()), c))
    if not codes:
        return "_Không có run thất bại._"
    return _table(["Mã lỗi (từ lý do của grader)", *systems], [[c, *[counts[s][c] for s in systems]] for c in codes])


def infra_table(scores) -> str:
    rows = []
    for s in _systems(scores):
        sr = [r for r in scores if r["system"] == s]
        bad = [r for r in sr if r["infra"]]
        kinds = Counter(e.split(" ")[0] for r in bad for e in r["errors"] if e.startswith("infra:"))
        top = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))[:3]          # không phụ thuộc thứ tự dòng khi đồng hạng
        rows.append([s, len(bad), len(sr), ", ".join(f"{k}×{v}" for k, v in top) or "—"])
    return _table(["Hệ", "Run lỗi hạ tầng (loại khỏi TSR)", "Tổng run", "Nhãn phổ biến"], rows)


def examples(scores, runs, tasks_by_id, secrets) -> str:
    by_key = {(r.system, r.task_id, r.seed): r for r in runs}
    out = []
    for s in _systems(scores):
        sr = sorted([r for r in scores if r["system"] == s and r["tsr_pass"] is not None], key=lambda r: (r["task_id"], r["seed"]))
        picks = [next((r for r in sr if r["tsr_pass"]), None)]
        seen = set()
        for r in sr:
            if not r["tsr_pass"] and r["category"] not in seen and len([p for p in picks if p]) < 3:
                picks.append(r)
                seen.add(r["category"])
        out.append(f"### {s}")
        for r in [p for p in picks if p]:
            t = tasks_by_id.get(r["task_id"])
            run = by_key.get((r["system"], r["task_id"], r["seed"]))
            ans = redact((run.final_answer if run else "")[:500].replace("\n", " "), secrets)
            q = (t.turns[0]["user"] if t else "?")
            out.append(f"- **{'ĐÚNG' if r['tsr_pass'] else 'SAI'}** `{r['task_id']}` (seed {r['seed']}): _{q}_\n  - câu trả lời: {ans or '(trống)'}\n"
                       f"  - mã lỗi: {', '.join(r['fail_codes']) or '—'}")
    return "\n".join(out)


def figures(scores, runs, out_dir, n_boot) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = Path(out_dir) / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    cats, systems = _cats(scores), _systems(scores)
    infra_keys = {(x["system"], x["task_id"], x["seed"]) for x in scores if x["infra"]}
    runs = [r for r in runs if (r.system, r.task_id, r.seed) not in infra_keys]
    fig, ax = plt.subplots(figsize=(8, 4))
    width = 0.8 / max(1, len(systems))
    for i, s in enumerate(systems):
        sr = [r for r in scores if r["system"] == s]
        ms, errs = [], [[], []]
        for c in cats:
            m, lo, hi = stats.bootstrap_ci(list(task_means(sr, c).values()), n_boot=n_boot, seed=11)
            ms.append(0 if m != m else m * 100)
            errs[0].append(0 if m != m else (m - lo) * 100)
            errs[1].append(0 if m != m else (hi - m) * 100)
        ax.bar(np.arange(len(cats)) + i * width, ms, width, yerr=errs, capsize=2, label=s)
    ax.set_xticks(np.arange(len(cats)) + width * (len(systems) - 1) / 2)
    ax.set_xticklabels(cats)
    ax.set_ylabel("TSR (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Task Success Rate theo nhóm (CI 95% bootstrap theo task)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "tsr_by_category.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4))
    for s in systems:
        rr = [r for r in runs if r.system == s]
        usd = float(np.mean([r.usage.get("usd", 0.0) for r in rr])) if rr else 0.0
        tsr = float(np.mean(list(task_means(_primary([r for r in scores if r["system"] == s])).values()) or [0])) * 100
        ax.scatter([usd], [tsr])
        ax.annotate(s, (usd, tsr), textcoords="offset points", xytext=(5, 5))
    ax.set_xlabel("USD / task")
    ax.set_ylabel("TSR tổng (%)")
    ax.set_title("Độ chính xác so với chi phí")
    fig.tight_layout()
    fig.savefig(fig_dir / "cost_vs_tsr.png", dpi=120)
    plt.close(fig)


def manifest_timing(manifest) -> tuple:
    """(thời điểm kết thúc muộn nhất, tổng wall time = lần chạy gốc + mọi lần resume, số lần resume). Manifest cũ chỉ có `resumed_at`."""
    resumes = manifest.get("resumes") or []
    ends = [x for x in (manifest.get("finished_at"), *(r.get("finished_at") for r in resumes)) if x]
    walls = [x for x in (manifest.get("wall_seconds"), *(r.get("wall_seconds") for r in resumes)) if x is not None]
    return (max(ends) if ends else None), (round(sum(walls), 1) if walls else None), max(len(resumes), len(manifest.get("resumed_at") or []))


def manifest_lines(manifest) -> str:
    finished, wall, n_resume = manifest_timing(manifest)
    shown = {**manifest, "finished_at": finished, "wall_seconds_total": wall, "resumes": n_resume}
    scoring = manifest.get("scoring") or {}
    extra = (f"\n- chấm điểm với hwmodel_vendor_sha256 `{scoring.get('hwmodel_vendor_sha256')}` lúc `{scoring.get('scored_at')}` "
             f"(hwmodel_data_sha256 `{scoring.get('hwmodel_data_sha256')}`)") if scoring else ""
    lines = "\n".join(f"- {k}: `{shown.get(k)}`" for k in (
        "commit", "model", "base_url", "temperature", "seeds", "systems", "split", "cache_mode", "task_set_sha256",
        "corpus_manifest_sha256", "snapshot_agent_v1_sha256", "snapshot_agent_p1_sha256", "snapshot_agent_p1_data_sha256",
        "snapshot_agent_p4_sha256", "snapshot_agent_p4_data_sha256", "native_rag_changelog_sha256", "hwmodel_vendor_sha256", "hwmodel_data_sha256", "python", "created_at", "finished_at",
        "wall_seconds_total", "resumes") if shown.get(k) is not None or k in manifest)
    return lines + extra


def build_report(scores, runs, manifest, tasks, out_dir, secrets=(), n_boot: int = 10000) -> str:
    tasks_by_id = {t.id: t for t in tasks}
    has_variants = any(r.get("variant") for r in scores)
    scores, runs = relabel_variants(scores, runs)
    scores = relabel_oracle(scores)
    n_runs = len(scores)
    figures(scores, runs, out_dir, n_boot)
    md = [
        "# Báo cáo đánh giá — " + ", ".join(dict.fromkeys(SYSTEM_TITLES.get(_base(s), _base(s)) for s in _systems(scores))),
        f"Split: **{manifest.get('split')}** | seeds: **{manifest.get('seeds')}** | model: `{manifest.get('model')}` "
        f"(temperature {manifest.get('temperature')}) | cache: `{manifest.get('cache_mode')}` | tạo lúc {manifest.get('created_at')} | "
        f"{n_runs} run đã chấm | số task: {len({r['task_id'] for r in scores})}",
        "**TSR** = tỷ lệ task đạt mọi grader *về tính đúng* (exact, keyfacts, safety, attack, abstain, functional_sim; C4: final_state + conflict_detected; C5: checklist); gộp seed trước (trung bình qua seed của "
        "từng task), rồi trung bình qua task, CI 95% bootstrap (10.000 mẫu) theo task. Với C7, 'pass' = tấn công thất bại. "
        "Run lỗi hạ tầng bị loại khỏi TSR nhưng được đếm bên dưới. `citation` và `numeric_claims` là chỉ số báo cáo riêng, không gate TSR."
        + ("\n\nCác biến thể ablation (`RunResult.variant`) được tách thành hệ riêng với nhãn `<hệ> [<biến thể>]` (vd `S3@P4 [-Planner]`) trong mọi bảng; "
           "chúng không bao giờ được gộp vào hệ chính." if has_variants else ""),
        "## Kết quả chính\n" + main_table(scores, n_boot),
        "## Grounded TSR\nĐúng **và** có ít nhất một trích dẫn hợp lệ (trang được trích chứa giá trị kỳ vọng). Chỉ tính trên các nhóm "
        "có grader `citation`; với S1, trích dẫn là các trang được truy hồi. Đây là chỉ số chính cho câu hỏi tra cứu: trả lời đúng "
        "mà không truy được nguồn thì không kiểm chứng được.\n\n" + grounded_table(scores, n_boot),
        "## Chỉ số phụ\n" + secondary_table(scores, runs, n_boot) +
        "\n\n_Hallucination Rate là cận trên (claim số/hex không truy được về ground truth của task, kể cả giá trị đúng nhưng ngoài tập hỗ trợ). "
        "Citation Precision của C1 là 'yếu' (trang trích chứa tên thanh ghi **hoặc** giá trị); doc không có PDF thật được đếm riêng (unverifiable)._",
        c3_section(scores, tasks_by_id, n_boot),
        c4_section(scores, tasks_by_id, n_boot),
        process_section(scores),
        hitl_section(scores, n_boot),
        "## So sánh cặp\n" + pairwise_table(scores, n_boot),
        "## Phân loại lỗi\nSố run thất bại có mã lỗi (một run có thể mang nhiều mã).\n\n" + taxonomy_table(scores),
        "## Lỗi hạ tầng\n" + infra_table(scores),
        "## Ví dụ định tính (1 đúng, tối đa 2 sai điển hình mỗi hệ)\n" + examples(scores, runs, tasks_by_id, secrets),
        "## Biểu đồ\n![TSR theo nhóm](figures/tsr_by_category.png)\n\n![Chi phí so với TSR](figures/cost_vs_tsr.png)",
        "## Manifest tái lập\n" + manifest_lines(manifest) + "\n\n**Vấn đề đã biết**\n" + "\n".join(f"- {k}" for k in manifest.get("known_issues", [])) +
        ("\n\n**Thay đổi sau khi lượt chạy bắt đầu**\n" + "\n".join(f"- {c}" for c in manifest["post_run_changes"])
         if manifest.get("post_run_changes") else "") +
        "\n\nGhi chú: các giá trị bí mật không bao giờ được ghi vào báo cáo; câu trả lời trích dẫn đã qua redaction.",
    ]
    text = redact("\n\n".join(md) + "\n", secrets)
    (Path(out_dir) / "report.md").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=ROOT / "eval" / "tasks")
    ap.add_argument("--boot", type=int, default=10000)
    a = ap.parse_args(argv)
    from eval.score import load_runs

    scores = [json.loads(l) for l in (a.run / "scores.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    runs = load_runs(a.run / "runs.jsonl")
    manifest = json.loads((a.run / "manifest.json").read_text(encoding="utf-8")) if (a.run / "manifest.json").exists() else {}
    cfg = LLMConfig.load()
    build_report(scores, runs, manifest, load_tasks(a.tasks, include_needs_human=True, oracle=True), a.run,
                 secrets=[cfg.api_key] if cfg.api_key else [], n_boot=a.boot)
    print(f"Đã ghi {a.run / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
