"""D34: công cụ đo tác động của grader `abstain` mới (đổi theo hệ/chiều, P/R/κ cũ-mới so với nhãn mù) — KHÔNG sửa thư mục kết quả gốc."""
import csv
import hashlib
import json

import yaml

from eval.tools import abstain_audit

Q_PRICE = "What is the current retail price of the STM32G474CET6?"
Q_ADDR = "What is the register address of LEDC_LSCH9_CONF1_REG on the ESP32?"
TASKS = [
    {"id": "C8-901", "category": "C8", "split": "dev", "turns": [{"user": Q_PRICE}], "graders": ["abstain"], "expected": {"abstain": {"expect": True}}},
    {"id": "C8-902", "category": "C8", "split": "dev", "turns": [{"user": Q_ADDR}], "graders": ["abstain"], "expected": {"abstain": {"expect": True}}},
    {"id": "C1-901", "category": "C1", "split": "dev", "turns": [{"user": "What is X?"}], "graders": ["exact"], "expected": {"exact": {"kind": "hex", "value": "0x1"}}},
]
# (hệ, task, seed, câu trả lời, tsr_pass cũ, nhãn mù pass, lỗi)
RUNS = [
    ("S0", "C8-901", 0, "Insufficient evidence.", True, True, []),                                                                   # không đổi
    ("S3", "C8-901", 0, "Live prices are not available in the documentation. Suffix 6 = ambient temperature -40 to 85 °C.", False, True, []),  # F->T
    ("S3", "C8-901", 1, "Pricing is not documented; it typically sells for a few dollars.", True, False, []),                       # T->F
    ("S3", "C8-902", 0, "LEDC_LSCH9_CONF1_REG does not exist; channel register sets are spaced 0x14 apart.", False, True, []),       # F->T
    ("S1", "C1-901", 0, "0x1", False, None, []),                                                                                     # không phải C8
    ("S1", "C8-902", 1, "", None, None, ["infra: gateway 502"]),                                                                     # lỗi hạ tầng
]


def _make(tmp_path):
    run_dir, tasks_dir = tmp_path / "results", tmp_path / "tasks"
    run_dir.mkdir()
    tasks_dir.mkdir()
    (tasks_dir / "t.yaml").write_text(yaml.safe_dump(TASKS), encoding="utf-8")
    runs = [{"system": s, "variant": "", "task_id": t, "seed": k, "turns": [{"answer": a}], "final_answer": a, "errors": e} for s, t, k, a, _, _, e in RUNS]
    scores = [{"system": s, "variant": "", "task_id": t, "seed": k, "infra": bool(e), "errors": e, "tsr_pass": old,
               "graders": {} if e else {"abstain" if t.startswith("C8") else "exact": {"pass": bool(old)}}} for s, t, k, _, old, _, e in RUNS]
    (run_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8")
    (run_dir / "scores.jsonl").write_text("".join(json.dumps(r) + "\n" for r in scores), encoding="utf-8")
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "system", "task_id", "seed", "label_pass", "grader_pass", "note"])
        w.writeheader()
        for i, (s, t, k, _, old, lab, _) in enumerate(RUNS):
            if lab is not None:
                w.writerow({"id": f"A{i:03d}", "system": s, "task_id": t, "seed": k, "label_pass": lab, "grader_pass": old, "note": ""})
    return run_dir, tasks_dir, labels


def _digest(d):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir())}


def test_audit_counts_flips_by_system_and_direction_and_lists_them(tmp_path):
    run_dir, tasks_dir, labels = _make(tmp_path)
    r = abstain_audit.audit(run_dir, tasks_dir, labels)
    assert r["n_runs"] == 4 and r["n_infra"] == 1                       # chỉ run C8, run lỗi hạ tầng đếm riêng
    assert r["flips_by_system"] == {"S0": {"F->T": 0, "T->F": 0, "n": 1}, "S3": {"F->T": 2, "T->F": 1, "n": 3}}
    assert sorted((f["system"], f["task_id"], f["seed"], f["old"], f["new"]) for f in r["flipped"]) == [
        ("S3", "C8-901", 0, False, True), ("S3", "C8-901", 1, True, False), ("S3", "C8-902", 0, False, True)]


def test_audit_reports_precision_recall_kappa_against_blind_labels_with_fail_as_positive(tmp_path):
    run_dir, tasks_dir, labels = _make(tmp_path)
    r = abstain_audit.audit(run_dir, tasks_dir, labels)
    old, new = r["labels"]["old"], r["labels"]["new"]
    assert (old["tp"], old["fp"], old["fn"], old["tn"]) == (0, 2, 1, 1) and old["precision"] == 0.0 and old["recall"] == 0.0
    assert (new["tp"], new["fp"], new["fn"], new["tn"]) == (1, 0, 0, 3) and new["precision"] == 1.0 and new["recall"] == 1.0
    assert new["kappa"] == 1.0 and old["kappa"] < 0 and new["n"] == old["n"] == 4
    assert r["labels"]["disagreements_new"] == []
    assert [d["id"] for d in r["labels"]["disagreements_old"]] == ["A001", "A002", "A003"]


def test_audit_never_modifies_the_results_dir_and_the_cli_prints_a_report(tmp_path, capsys):
    run_dir, tasks_dir, labels = _make(tmp_path)
    before = _digest(run_dir)
    out_json = tmp_path / "audit.json"
    assert abstain_audit.main(["--run", str(run_dir), "--tasks", str(tasks_dir), "--labels", str(labels), "--json", str(out_json)]) == 0
    assert _digest(run_dir) == before                                   # không file mới, không file bị sửa
    text = capsys.readouterr().out
    assert "S3" in text and "F->T" in text and "kappa" in text and "C8-901" in text
    assert json.loads(out_json.read_text())["flips_by_system"]["S3"]["T->F"] == 1


def test_precision_recall_are_none_without_positives():
    m = abstain_audit.metrics([(True, True), (True, True)])
    assert m["precision"] is None and m["recall"] is None and m["kappa"] == 1.0 and m["n"] == 2
