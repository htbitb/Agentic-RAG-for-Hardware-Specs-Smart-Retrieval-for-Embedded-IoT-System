"""D29: kiểm định nhãn mù bộ nhận diện xung đột trên đầu ra THẬT của một hệ (S3@P4).

    # 1) tạo gói cho annotator độc lập (KHÔNG chứa kết quả/mã của bộ nhận diện)
    eval/.venv/bin/python -m eval.tools.blind_label pack --run eval/results/<dir> --system S3@P4 --out <thư mục gói>
    # 2) annotator điền cột label (explicit | implicit | none), turn_flagged, evidence_quote trong labels_template.csv rồi lưu thành labels.csv
    # 3) so nhãn với bộ nhận diện
    eval/.venv/bin/python -m eval.tools.blind_label compare --run eval/results/<dir> --system S3@P4 --labels labels.csv

Định nghĩa nhãn (D28): explicit = trợ lý NÊU xung đột (nói rõ vì sao có vấn đề) trong lượt gây xung đột hoặc sau đó mà người dùng chưa hỏi;
implicit = chọn phương án tránh được xung đột nhưng không phát biểu xung đột; none = không nêu và không tránh. Dương = `explicit`.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

DEFS = {
    "PIN_CONFLICT": "the pin {arg} is already assigned to another function in the design, and a later request needs the same pin",
    "NO_SUCH_AF": "the requested peripheral signal cannot be routed to the pin {arg} that the user asked for (that pin has no such alternate function)",
    "INPUT_ONLY": "the pin {arg} is input-only but the request needs it as an output",
    "LEVEL_MISMATCH": "two parts of the design work at different logic voltage levels ({arg}), so they cannot be wired directly",
    "NOT_5V_TOLERANT": "a 5 V signal would be connected to the pin {arg}, which is not 5 V tolerant",
    "TIMER_SHARED": "two PWM outputs on channels of the same timer ({arg}) need different frequencies, but all channels of a timer share one counter/prescaler/auto-reload",
    "CLOCK_LIMIT": "the requested clock ({arg}) is above the limit the device supports in the voltage/mode configuration in use",
}


def describe(code: str) -> str:
    fam, _, arg = code.partition(":")
    return f"{code}: " + DEFS.get(fam, "a design conflict").format(arg=arg or "(see the user messages)")


def _key(r: dict) -> tuple:
    return (r["system"], r.get("variant", ""), r["task_id"], int(r["seed"]))


def make_pack(runs: list[dict], scores: list[dict], user_turns: dict, out_dir, system: str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sc = {_key(s): s for s in scores if s["system"] == system and not s.get("infra")}
    rows = []
    for r in runs:
        k = _key(r)
        if r["system"] != system or k not in sc:
            continue
        items = (sc[k].get("graders", {}).get("conflict_detected") or {}).get("details", {}).get("items") or []
        if not items:
            continue
        lines = [f"# {r['task_id']} seed {r['seed']}", "", "## Conflicts to label", ""]
        lines += [f"- {describe(i['code'])} (the conflict is created by user message {i.get('cause_turn', i['from_turn'])}; only count statements from turn {i['from_turn']} on)" for i in items]
        lines += ["", "## Conversation", ""]
        for t, turn in enumerate(r["turns"]):
            users = user_turns.get(r["task_id"], [])
            lines += [f"### User message {t}", "", users[t] if t < len(users) else "(unavailable)", "", f"### Assistant answer {t}", "", turn["answer"], ""]
        (out / f"{r['task_id']}_s{r['seed']}.md").write_text("\n".join(lines), encoding="utf-8")
        for i in items:
            rows.append({"system": system, "task_id": r["task_id"], "seed": r["seed"], "item": i["code"], "from_turn": i["from_turn"], "label": "", "turn_flagged": "", "evidence_quote": ""})
    template = out / "labels_template.csv"
    with template.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["system", "task_id", "seed", "item", "from_turn", "label", "turn_flagged", "evidence_quote"])
        w.writeheader()
        w.writerows(rows)
    return {"template": str(template), "items": len(rows)}


def cohen_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1.0 else (po - pe) / (1 - pe)


def compare(scores: list[dict], labels: list[dict], system: str) -> dict:
    lab = {(l["system"], l["task_id"], int(l["seed"]), l["item"]): l["label"].strip().lower() for l in labels if l.get("label", "").strip()}
    machine, human, unlabelled, implicit = [], [], 0, 0
    for s in scores:
        if s["system"] != system or s.get("infra"):
            continue
        for i in (s.get("graders", {}).get("conflict_detected") or {}).get("details", {}).get("items") or []:
            k = (s["system"], s["task_id"], int(s["seed"]), i["code"])
            if k not in lab:
                unlabelled += 1
                continue
            implicit += lab[k] == "implicit"
            machine.append(int(bool(i["proactive"])))
            human.append(int(lab[k] == "explicit"))
    tp = sum(m and h for m, h in zip(machine, human))
    fp = sum(m and not h for m, h in zip(machine, human))
    fn = sum(h and not m for m, h in zip(machine, human))
    tn = sum(not m and not h for m, h in zip(machine, human))
    n = len(machine)
    return {"n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "implicit": implicit, "unlabelled": unlabelled,
            "precision": tp / (tp + fp) if tp + fp else float("nan"), "recall": tp / (tp + fn) if tp + fn else float("nan"),
            "agreement": (tp + tn) / n if n else float("nan"), "kappa": cohen_kappa(machine, human)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pack", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--run", type=Path, required=True)
        p.add_argument("--system", default="S3@P4")
    sub.choices["pack"].add_argument("--out", type=Path, required=True)
    sub.choices["compare"].add_argument("--labels", type=Path, required=True)
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from eval.schema import load_tasks
    scores = [json.loads(l) for l in (a.run / "scores.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.cmd == "pack":
        runs = [json.loads(l) for l in (a.run / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        users = {t.id: [x["user"] for x in t.turns] for t in load_tasks(root / "eval" / "tasks", include_needs_human=True)}
        print(json.dumps(make_pack(runs, scores, users, a.out, a.system)))
    else:
        print(json.dumps(compare(scores, list(csv.DictReader(a.labels.open(encoding="utf-8"))), a.system), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
