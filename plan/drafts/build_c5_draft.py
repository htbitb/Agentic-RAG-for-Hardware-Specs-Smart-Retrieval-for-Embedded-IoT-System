"""Sinh plan/drafts/C5_curated_draft.yaml từ c5_tasks_a.py / c5_tasks_b.py (P5, c5-author).

    eval/.venv/bin/python plan/drafts/build_c5_draft.py

Biến thể sai được tạo bằng cách sửa (find -> replace, thay MỌI lần xuất hiện; find phải có mặt) trên câu trả lời tham chiếu,
rồi ghi NGUYÊN VĂN câu trả lời vào `provenance.wrong_variants[].answer` (định dạng P5_interfaces §3). Không import repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from c5_common import AUTHOR  # noqa: E402
from c5_tasks_a import TASKS_A  # noqa: E402
from c5_tasks_b import TASKS_B  # noqa: E402

OUT = HERE / "C5_curated_draft.yaml"

HEADER = """\
# C5 — Mục tiêu cấp hệ thống (P5). BẢN NHÁP của c5-author; controller sẽ chuyển sang eval/tasks/C5/c5_curated.yaml sau khi kiểm.
# 12 task: C5-001…006 THIẾU ≥ 1 thông tin bắt buộc không tra được (hidden_info + human_policy.clarify), C5-007…012 ĐỦ thông tin (đo "không hỏi khi không cần").
# Split cố định TRƯỚC khi chạy bất kỳ hệ nào (brief của controller): dev = C5-002, C5-005 (thiếu), C5-008, C5-011 (đủ); còn lại test.
# Chấm: `checklist` (gate) + `functional_sim` (gate, task có code) + `compile` (chỉ số) + `clarify` (không gate, MỌI task — review B1).
# Đã áp dụng review độc lập plan/reviews/review_C5.md (B1, G1–G7, G9–G13 phía task); xem plan/drafts/C5_authoring_notes.md.
# Mọi số liệu: phép tính TAY có trang PDF trong provenance.reference_calc (D19, không dùng simulator/DRC), bằng chứng nguyên văn trong provenance.evidence.
# provenance.reference_solution.answer PHẢI pass checklist; mỗi wrong_variants[].answer PHẢI trượt ĐÚNG các mục must_fail (kiểm: plan/drafts/check_c5_draft.py).
# Sinh bởi plan/drafts/build_c5_draft.py — sửa nguồn ở c5_tasks_a.py / c5_tasks_b.py rồi sinh lại, không sửa tay file này.
"""


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):            # không dùng &anchor/*alias: mục dùng chung được chép ra đầy đủ ở từng task
        return True


def _str(dumper, s):
    if "\n" in s:
        return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", s)


_Dumper.add_representer(str, _str)


def apply_edits(text: str, edits, name: str) -> str:
    out = text
    for find, repl in edits:
        if find not in out:
            raise SystemExit(f"variant {name}: edit target not found: {find[:80]!r}")
        out = out.replace(find, repl)
    if out == text:
        raise SystemExit(f"variant {name}: no change")
    return out


def build_task(t: dict) -> dict:
    ref = t["ref"].rstrip() + "\n"
    if any(line != line.rstrip() for line in ref.splitlines()):
        raise SystemExit(f"{t['id']}: trailing spaces in reference answer (breaks YAML literal style)")
    variants = []
    for v in t["variants"]:
        ans = apply_edits(ref, v["edits"], f"{t['id']}/{v['name']}")
        variants.append({"name": v["name"], "answer": ans, "must_fail": list(v["must_fail"])})
    hidden = t.get("hidden_info", [])
    graders = list(t["graders"])
    assert "clarify" in graders, t["id"]          # review B1: clarify (không gate) trên MỌI task C5 để đo câu hỏi thừa ở nửa đủ thông tin
    d = {
        "id": t["id"], "category": "C5", "split": t["split"], "difficulty": t["difficulty"], "chips": t["chips"], "tags": t["tags"],
        "turns": [{"user": t["user"]}],
        "human_policy": t["human_policy"],
        "hidden_info": hidden,
        "expected": t["expected"],
        "graders": graders,
        "review_status": "verified",
        "provenance": {
            "authored_by": AUTHOR,
            "reference_calc": t["reference_calc"],
            "evidence": [e for e in t["evidence"] if e["contains"]],
            "reference_solution": {"answer": ref},
            "wrong_variants": variants,
        },
    }
    if t.get("limitations"):
        d["provenance"]["limitations"] = t["limitations"]
    return d


def main() -> int:
    tasks = [build_task(t) for t in TASKS_A + TASKS_B]
    ids = [t["id"] for t in tasks]
    assert ids == [f"C5-{i:03d}" for i in range(1, 13)], ids
    dev = sorted(t["id"] for t in tasks if t["split"] == "dev")
    assert dev == ["C5-002", "C5-005", "C5-008", "C5-011"], dev
    body = yaml.dump(tasks, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100000, default_flow_style=False)
    OUT.write_text(HEADER + "\n" + body, encoding="utf-8")
    back = yaml.safe_load(OUT.read_text(encoding="utf-8"))
    for a, b in zip(tasks, back):
        assert a == b, f"round-trip mismatch in {a['id']}"
    print(f"wrote {OUT} ({len(tasks)} tasks, {OUT.stat().st_size} bytes); YAML round-trip OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
