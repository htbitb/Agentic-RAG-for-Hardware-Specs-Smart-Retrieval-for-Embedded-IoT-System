"""P9: so nhãn mù (annotator độc lập, gói xáo trộn ẩn tên hệ) với grader trên đầu ra test: C5 checklist, C6 safety, C8 abstain.
    eval/.venv/bin/python -m eval.tools.blind_compare_test --run eval/results/test_p7 --dir plan/reviews/test_blind
"""
from __future__ import annotations

import argparse, csv, json, re
from collections import Counter, defaultdict
from pathlib import Path

from eval.tools.blind_label import cohen_kappa

NONANS = re.compile(r"could not find this in the documents|step budget exhausted|^\s*$|insufficient evidence", re.I)


def load_labels(d: Path, cat: str):
    rows = []
    for f in sorted((d / "labels").glob(f"{cat}_*.csv")):
        with f.open(encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="eval/results/test_p7"); ap.add_argument("--dir", default="plan/reviews/test_blind")
    a = ap.parse_args(argv); d = Path(a.dir); run = Path(a.run)
    scores = {(s["system"], s.get("variant", ""), s["task_id"], s["seed"]): s for s in map(json.loads, (run / "scores.jsonl").read_text().splitlines())}
    runs = {(r["system"], r.get("variant", ""), r["task_id"], r["seed"]): r for r in map(json.loads, (run / "runs.jsonl").read_text().splitlines())}
    out = {}
    # ---------------- C8
    key = json.loads((d / "keys/C8_key.json").read_text()); lab = {r["answer_id"]: r["label"] for r in load_labels(d, "C8")}
    tab = defaultdict(Counter); allp = []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"]));
        if not s or s["infra"] or aid not in lab: continue
        g = bool(s["graders"]["abstain"]["pass"]); b = lab[aid] == "abstain"
        tab[k["system"]][(g, b)] += 1; allp.append((g, b))
    out["C8"] = {"n": len(allp), "agree": sum(g == b for g, b in allp) / len(allp), "kappa": cohen_kappa([int(g) for g, b in allp], [int(b) for g, b in allp]) if allp else None,
                 "by_system": {s: {"n": sum(c.values()), "grader_pass": sum(v for (g, b), v in c.items() if g), "blind_abstain": sum(v for (g, b), v in c.items() if b), "disagree": sum(v for (g, b), v in c.items() if g != b)} for s, c in tab.items()}}
    # ---------------- C6
    key = json.loads((d / "keys/C6_key.json").read_text()); lab = {r["answer_id"]: r for r in load_labels(d, "C6")}
    from eval.schema import load_tasks
    T = {t.id: t for t in load_tasks("eval/tasks", split="test")}
    tab = defaultdict(Counter); dis = []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"])); r = runs.get((k["system"], "", k["task_id"], k["seed"]))
        if not s or s["infra"] or aid not in lab: continue
        ans = r.get("final_answer") or ""
        non = bool(NONANS.search(ans[:200])) and len(ans) < 400
        exp = {"refuse": "refuse", "warn": "warn", "answer": "answer"}[T[k["task_id"]].expected["safety"]["label"]]
        bl = "non_answer" if non else lab[aid]["label"]
        g = bool(s["graders"]["safety"]["pass"]); b = (bl == exp)
        tab[(k["system"], non)][(g, b)] += 1
        if g != b and not non: dis.append((k["system"], k["task_id"], k["seed"], exp, bl, g))
    out["C6"] = {"by_system(non_answer?)": {f"{s}|nonans={n}": dict((f"g={g},b={b}", v) for (g, b), v in c.items()) for (s, n), c in tab.items()}, "disagreements": dis}
    # ---------------- C5
    key = json.loads((d / "keys/C5_key.json").read_text()); lab = defaultdict(dict)
    for r in load_labels(d, "C5"): lab[r["answer_id"]][r["item_id"]] = r["verdict"].strip().upper() == "YES"
    pairs = []; tab = defaultdict(Counter); itemdis = []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"]))
        if not s or s["infra"] or aid not in lab: continue
        gi = (s["graders"].get("checklist") or {}).get("details", {}).get("items", {})
        for it, gv in gi.items():
            if it in lab[aid]:
                pairs.append((bool(gv), lab[aid][it])); 
                if bool(gv) != lab[aid][it]: itemdis.append((k["system"], k["task_id"], k["seed"], it, bool(gv), lab[aid][it]))
        gp = bool(s["graders"]["checklist"]["pass"]); bp = all(lab[aid].get(it, False) for it in gi)
        tab[k["system"]][(gp, bp)] += 1
    out["C5"] = {"item_pairs": len(pairs), "item_agree": sum(g == b for g, b in pairs) / len(pairs), "item_kappa": cohen_kappa([int(g) for g, b in pairs], [int(b) for g, b in pairs]),
                 "answer_level_by_system": {s: {"n": sum(c.values()), "grader_pass": sum(v for (g, b), v in c.items() if g), "blind_pass": sum(v for (g, b), v in c.items() if b), "disagree": sum(v for (g, b), v in c.items() if g != b)} for s, c in tab.items()},
                 "item_disagreements": Counter((x[0], x[3], x[4], x[5]) for x in itemdis).most_common(40)}
    # ---------------- TSR theo nhãn mù (song song với TSR theo grader đã khoá; grader KHÔNG bị sửa)
    def task_mean(rows):  # rows: [(system, task, seed, bool)]
        per = defaultdict(lambda: defaultdict(list))
        for s, t, sd, v in rows: per[s][t].append(float(v))
        return {s: sum(sum(v) / len(v) for v in tt.values()) / len(tt) for s, tt in per.items()}
    adj = {}
    # C8
    key = json.loads((d / "keys/C8_key.json").read_text()); lab8 = {r["answer_id"]: r["label"] for r in load_labels(d, "C8")}
    rows_b, rows_g = [], []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"]))
        if not s or s["infra"] or aid not in lab8: continue
        rows_b.append((k["system"], k["task_id"], k["seed"], lab8[aid] == "abstain")); rows_g.append((k["system"], k["task_id"], k["seed"], s["graders"]["abstain"]["pass"]))
    adj["C8"] = {"grader": task_mean(rows_g), "blind": task_mean(rows_b)}
    # C6
    key = json.loads((d / "keys/C6_key.json").read_text()); lab6 = {r["answer_id"]: r["label"] for r in load_labels(d, "C6")}
    rows_b, rows_g = [], []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"])); r = runs.get((k["system"], "", k["task_id"], k["seed"]))
        if not s or s["infra"] or aid not in lab6: continue
        ans = r.get("final_answer") or ""; non = bool(NONANS.search(ans[:200])) and len(ans) < 400
        exp = T[k["task_id"]].expected["safety"]["label"]; bl = lab6[aid]
        ok = (not non) and (bl == exp or (exp == "answer" and bl in ("answer", "warn")))
        rows_b.append((k["system"], k["task_id"], k["seed"], ok)); rows_g.append((k["system"], k["task_id"], k["seed"], s["graders"]["safety"]["pass"]))
    adj["C6"] = {"grader": task_mean(rows_g), "blind": task_mean(rows_b)}
    # C5
    key = json.loads((d / "keys/C5_key.json").read_text()); lab5 = defaultdict(dict)
    for r in load_labels(d, "C5"): lab5[r["answer_id"]][r["item_id"]] = r["verdict"].strip().upper() == "YES"
    rows_b, rows_g = [], []
    for aid, k in key.items():
        s = scores.get((k["system"], "", k["task_id"], k["seed"]))
        if not s or s["infra"] or aid not in lab5: continue
        gi = (s["graders"].get("checklist") or {}).get("details", {}).get("items", {})
        rows_b.append((k["system"], k["task_id"], k["seed"], all(lab5[aid].get(i, False) for i in gi))); rows_g.append((k["system"], k["task_id"], k["seed"], s["graders"]["checklist"]["pass"]))
    adj["C5"] = {"grader": task_mean(rows_g), "blind": task_mean(rows_b)}
    # C4 (chỉ S3@P7): final_state (grader) AND mọi mục xung đột 'explicit' theo nhãn mù
    lab4 = defaultdict(list)
    for r in load_labels(d, "C4"): lab4[(r["task_id"], int(r["seed"]))].append(r["label"].strip().lower())
    rows_b, rows_g = [], []
    for (t, sd), labs in lab4.items():
        s = scores.get(("S3@P7", "", t, sd))
        if not s or s["infra"]: continue
        fs = s["graders"]["final_state"]["pass"]
        rows_b.append(("S3@P7", t, sd, fs and all(l == "explicit" for l in labs))); rows_g.append(("S3@P7", t, sd, s["graders"]["final_state"]["pass"] and s["graders"]["conflict_detected"]["pass"]))
    adj["C4"] = {"grader": task_mean(rows_g), "blind": task_mean(rows_b), "n_items": sum(len(v) for v in lab4.values()),
                 "items_explicit": sum(l == "explicit" for v in lab4.values() for l in v)}
    out["adjusted"] = adj
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
