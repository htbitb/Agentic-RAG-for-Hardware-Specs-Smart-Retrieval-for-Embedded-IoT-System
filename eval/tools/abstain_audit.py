"""D34: đo tác động của grader `abstain` hiện tại lên một thư mục kết quả, KHÔNG sửa thư mục đó (không gọi LLM / mạng).

    eval/.venv/bin/python -m eval.tools.abstain_audit --run eval/results/dev_baseline_v2 \
        --labels plan/reviews/c8_blind_labels_dev_v2_unblinded.csv [--json <file>]

Chép runs.jsonl sang thư mục tạm và chấm lại mọi run có grader `abstain` (C8) bằng grader hiện tại; 'cũ' = tsr_pass trong scores.jsonl
đang lưu (bản chấm trước khi sửa). In ra: (1) số run đổi tsr_pass theo hệ và chiều đổi trên MỌI run C8 của thư mục; (2) precision /
recall / Cohen's κ của grader cũ và mới so với nhãn mù (coi 'fail' là dương); (3) danh sách run đổi. Chấm chính thức vẫn là `eval.score`.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

from eval.graders import abstain
from eval.schema import GATING_GRADERS, RunResult, load_tasks
from eval.tools.blind_label import cohen_kappa

ROOT = Path(__file__).resolve().parents[2]


def _key(system, variant, task_id, seed) -> tuple:
    return (system, variant or "", task_id, int(seed))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs = [(grader_pass, label_pass)]; dương = fail."""
    pred, gold = [int(not p) for p, _ in pairs], [int(not g) for _, g in pairs]
    tp = sum(p and g for p, g in zip(pred, gold))
    fp = sum(p and not g for p, g in zip(pred, gold))
    fn = sum(g and not p for p, g in zip(pred, gold))
    tn = len(pairs) - tp - fp - fn
    return {"n": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "agreement": (tp + tn) / len(pairs) if pairs else None,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "kappa": cohen_kappa(pred, gold)}


def audit(run_dir, tasks_dir, labels_csv=None) -> dict:
    run_dir = Path(run_dir)
    tasks = {t.id: t for t in load_tasks(tasks_dir, include_needs_human=True)}
    old = {_key(s["system"], s.get("variant"), s["task_id"], s["seed"]): s for s in _read_jsonl(run_dir / "scores.jsonl")}
    rows, n_infra = [], 0
    with tempfile.TemporaryDirectory() as tmp:                     # chỉ đọc bản sao: thư mục kết quả gốc không bị chạm tới
        copy = Path(shutil.copy(run_dir / "runs.jsonl", Path(tmp) / "runs.jsonl"))
        for d in _read_jsonl(copy):
            run = RunResult.from_dict(d)
            task = tasks.get(run.task_id)
            if task is None or "abstain" not in task.graders:
                continue
            if run.has_infra_error():
                n_infra += 1
                continue
            prev = old[run.key()]
            res = abstain.grade(task, run, None)
            gating = [n for n in task.graders if n in GATING_GRADERS]
            new_pass = all(res["pass"] if n == "abstain" else prev["graders"][n]["pass"] for n in gating) \
                and not any(e.startswith("error:") for e in run.errors)
            rows.append({"system": run.system, "variant": run.variant, "task_id": run.task_id, "seed": run.seed,
                         "old": bool(prev["tsr_pass"]), "new": new_pass, "details": res["details"]})
    flips = {}
    for r in rows:
        f = flips.setdefault(r["system"], {"F->T": 0, "T->F": 0, "n": 0})
        f["n"] += 1
        if r["old"] != r["new"]:
            f["F->T" if r["new"] else "T->F"] += 1
    out = {"run_dir": str(run_dir), "n_runs": len(rows), "n_infra": n_infra, "flips_by_system": dict(sorted(flips.items())),
           "flipped": [r for r in rows if r["old"] != r["new"]]}
    if labels_csv:
        by_key = {(r["system"], r["task_id"], r["seed"]): r for r in rows if not r["variant"]}
        labelled, missing = [], []
        for lab in csv.DictReader(Path(labels_csv).open(encoding="utf-8")):
            r = by_key.get((lab["system"], lab["task_id"], int(lab["seed"])))
            if r is None:
                missing.append(lab["id"])
                continue
            labelled.append({"id": lab["id"], "system": r["system"], "task_id": r["task_id"], "seed": r["seed"],
                             "label": lab["label_pass"].strip().lower() == "true", "old": r["old"], "new": r["new"]})
        out["labels"] = {"old": metrics([(x["old"], x["label"]) for x in labelled]), "new": metrics([(x["new"], x["label"]) for x in labelled]),
                         "disagreements_old": [x for x in labelled if x["old"] != x["label"]],
                         "disagreements_new": [x for x in labelled if x["new"] != x["label"]], "missing": missing}
    return out


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.2f}"


def render(r: dict) -> str:
    lines = [f"# abstain_audit: {r['run_dir']} — {r['n_runs']} run C8 (bỏ {r['n_infra']} run lỗi hạ tầng)", "",
             "## (1) Run đổi tsr_pass theo hệ (cũ = scores.jsonl đang lưu, mới = grader hiện tại)", "",
             "| hệ | n | F->T | T->F |", "|---|---|---|---|"]
    lines += [f"| {s} | {f['n']} | {f['F->T']} | {f['T->F']} |" for s, f in r["flips_by_system"].items()]
    if "labels" in r:
        lab = r["labels"]
        lines += ["", "## (2) So với nhãn mù (dương = fail)", "", "| grader | n | TP | FP | FN | TN | precision | recall | kappa |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for name in ("old", "new"):
            m = lab[name]
            lines.append(f"| {name} | {m['n']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | {_fmt(m['precision'])} | {_fmt(m['recall'])} | {_fmt(m['kappa'])} |")
        for name in ("old", "new"):
            lines.append(f"- lệch nhãn ({name}): " + (", ".join(f"{x['id']} {x['system']} {x['task_id']} s{x['seed']} (nhãn {'pass' if x['label'] else 'fail'})"
                                                              for x in lab[f"disagreements_{name}"]) or "không có"))
        if lab["missing"]:
            lines.append(f"- nhãn không khớp run nào: {', '.join(lab['missing'])}")
    lines += ["", "## (3) Run đổi", ""]
    for f in r["flipped"]:
        d = f["details"]
        lines.append(f"- {f['system']} {f['task_id']} seed {f['seed']}: {'pass' if f['old'] else 'fail'} -> {'pass' if f['new'] else 'fail'}"
                     f" (fabricated={d['fabricated']}, other_attribute={d['other_attribute']}, abstained={d['abstained']})")
    if not r["flipped"]:
        lines.append("- không có")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=ROOT / "eval" / "tasks")
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--json", type=Path, help="ghi kết quả dạng JSON (đặt NGOÀI thư mục kết quả)")
    a = ap.parse_args(argv)
    if a.json and a.run.resolve() in a.json.resolve().parents:
        print("--json phải nằm ngoài thư mục kết quả (công cụ này không được ghi vào đó)", file=sys.stderr)
        return 2
    r = audit(a.run, a.tasks, a.labels)
    print(render(r))
    if a.json:
        a.json.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
