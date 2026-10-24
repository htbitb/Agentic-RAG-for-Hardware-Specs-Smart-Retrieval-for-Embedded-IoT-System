"""D29: gói nhãn mù cho annotator độc lập (không chứa kết quả của bộ nhận diện) và phép so nhãn người/mô hình với bộ nhận diện (precision, recall, kappa)."""
import csv
import json

from eval.tools.blind_label import cohen_kappa, compare, describe, make_pack


def test_descriptions_define_each_conflict_family_without_naming_the_detector():
    assert "already" in describe("PIN_CONFLICT:PA8") and "PA8" in describe("PIN_CONFLICT:PA8")
    assert "voltage" in describe("LEVEL_MISMATCH:1.8V-3.3V").lower() and "1.8V" in describe("LEVEL_MISMATCH:1.8V-3.3V")
    assert "5 V" in describe("NOT_5V_TOLERANT:PC5") and "timer" in describe("TIMER_SHARED:TIM3").lower()
    assert "clock" in describe("CLOCK_LIMIT:SYSCLK").lower() and "alternate function" in describe("NO_SUCH_AF:PA2").lower()


def test_the_pack_has_conversations_and_blank_labels_but_no_detector_output(tmp_path):
    runs = [{"system": "S3@P4", "variant": "", "task_id": "C4-001", "seed": 0, "turns": [{"answer": "turn 0 answer"}, {"answer": "PA8 is already used; I moved SCL to PC8."}]}]
    scores = [{"system": "S3@P4", "variant": "", "task_id": "C4-001", "seed": 0, "infra": False,
               "graders": {"conflict_detected": {"details": {"items": [{"code": "PIN_CONFLICT:PA8", "cause_turn": 1, "from_turn": 1, "detected": True, "proactive": True, "evidence": "SECRET-DETECTOR-EVIDENCE"}]}}}}]
    users = {"C4-001": ["user message 0", "user message 1"]}
    out = make_pack(runs, scores, users, tmp_path, system="S3@P4")
    text = (tmp_path / "C4-001_s0.md").read_text()
    assert "user message 1" in text and "PA8 is already used" in text and "PIN_CONFLICT:PA8" in text
    assert "SECRET-DETECTOR-EVIDENCE" not in text and "detected" not in text.lower().replace("undetected", "")
    rows = list(csv.DictReader(open(out["template"])))
    assert rows == [{"system": "S3@P4", "task_id": "C4-001", "seed": "0", "item": "PIN_CONFLICT:PA8", "from_turn": "1", "label": "", "turn_flagged": "", "evidence_quote": ""}]


def test_compare_counts_explicit_as_positive_and_reports_precision_recall_kappa():
    scores = [{"system": "S", "variant": "", "task_id": "T", "seed": s, "infra": False, "graders": {"conflict_detected": {"details": {"items": [
        {"code": "A", "from_turn": 1, "proactive": p}]}}}} for s, p in enumerate([True, True, False, False])]
    labels = [{"system": "S", "task_id": "T", "seed": str(s), "item": "A", "label": lab} for s, lab in enumerate(["explicit", "none", "explicit", "none"])]
    r = compare(scores, labels, system="S")
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 1) and r["precision"] == 0.5 and r["recall"] == 0.5 and r["n"] == 4
    assert abs(r["kappa"]) < 1e-9 and r["agreement"] == 0.5


def test_implicit_label_is_not_positive_and_missing_labels_are_reported():
    scores = [{"system": "S", "variant": "", "task_id": "T", "seed": 0, "infra": False, "graders": {"conflict_detected": {"details": {"items": [{"code": "A", "from_turn": 1, "proactive": False}]}}}}]
    r = compare(scores, [{"system": "S", "task_id": "T", "seed": "0", "item": "A", "label": "implicit"}], system="S")
    assert (r["tp"], r["fn"], r["tn"], r["fp"]) == (0, 0, 1, 0) and r["implicit"] == 1
    r = compare(scores, [], system="S")
    assert r["n"] == 0 and r["unlabelled"] == 1


def test_cohen_kappa_extremes():
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert cohen_kappa([1, 1, 1, 1], [1, 1, 1, 1]) == 1.0
