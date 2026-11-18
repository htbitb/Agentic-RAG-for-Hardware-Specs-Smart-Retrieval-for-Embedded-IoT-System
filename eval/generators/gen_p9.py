"""P9: sinh task FI (fault injection) và C9 (độ bền) TỪ task gốc, kế thừa nguyên ground truth và grader (không viết lại đáp án).

    eval/.venv/bin/python -m eval.generators.gen_p9 --split dev            # ghi eval/tasks/FI/fi_<split>.yaml và eval/tasks/C9/c9_<split>.yaml

FI: mỗi task gốc C1/C2 (tra cứu) được thêm tool_rules kind=raise (TimeoutError) trên các tool tri thức có cấu trúc, đủ số lần (6 lời gọi _invoke, vượt retry của hub) để agent phải TỰ
    phục hồi (gọi lại / đổi tool). Đo: Recovery Rate = TSR(FI) / TSR(gốc) trên cùng task (eval/report.py mục FI).
C9: biến thể cơ học của task C1/C2/C3 gốc, xoay vòng 4 phép biến đổi tất định (không dùng LLM, không đổi số liệu/định danh): typos (hoán vị hai chữ cái liền nhau trong từ tiếng Anh thường),
    abbrev (viết tắt từ thường gặp), reorder (đảo thứ tự các câu mô tả/yêu cầu), vi (lời dẫn tiếng Việt + giữ nguyên đề tiếng Anh). Chỉ là biến đổi bề mặt; không thay cho dịch thuật thật.
Task test chỉ được sinh khi bước P9 'khoá' đã chạy; script không in nội dung task.
"""
from __future__ import annotations

import argparse
import copy
import random
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.schema import Task, load_tasks  # noqa: E402

FI_TOOLS = ("get_register_bitfields", "search_registers", "get_electrical_specs", "query_pin_alternate_function", "find_pins_for_signal", "get_clock_limits")
FI_TIMES = 6
TRANSFORMS = ("typos", "abbrev", "reorder", "vi")
ABBREV = {"register": "reg", "registers": "regs", "frequency": "freq", "configuration": "config", "peripheral": "periph", "voltage": "volt", "maximum": "max", "minimum": "min",
          "address": "addr", "documentation": "docs", "information": "info", "specification": "spec"}
VI_PREFIX = "Trả lời bằng tiếng Việt (giữ nguyên tên thanh ghi, tên bit, số liệu và mã nguồn bằng tiếng Anh, vẫn trích dẫn nguồn như thường lệ). Câu hỏi: "


def _protected(word: str) -> bool:
    """Từ không được đụng tới: có chữ số, gạch dưới, chữ HOA ở giữa/toàn bộ, hay nằm trong ký tự đặc biệt (định danh, số liệu, mã)."""
    return bool(re.search(r"[\d_\-/\\.<>=\[\]()`'\"@#$%&*+:;]", word)) or word.isupper() or any(c.isupper() for c in word[1:])


def typos(text: str, seed: int) -> str:
    rng = random.Random(seed)
    out = []
    for tok in re.split(r"(\s+)", text):
        if tok.strip() and tok.isalpha() and len(tok) >= 6 and not _protected(tok) and rng.random() < 0.18:
            i = rng.randrange(1, len(tok) - 2)
            tok = tok[:i] + tok[i + 1] + tok[i] + tok[i + 2:]
        out.append(tok)
    res = "".join(out)
    if res == text:                                        # đảm bảo có ít nhất một lỗi chính tả nếu có từ đủ điều kiện
        for n, tok in enumerate(out):
            if tok.strip() and tok.isalpha() and len(tok) >= 5 and not _protected(tok):
                out[n] = tok[:1] + tok[2] + tok[1] + tok[3:]
                break
        res = "".join(out)
    return res


def abbrev(text: str, seed: int) -> str:
    return "".join(ABBREV.get(tok, tok) if tok.isalpha() and tok.islower() else tok for tok in re.split(r"(\s+)", text))


def reorder(text: str, seed: int) -> str:
    """Đảo thứ tự câu: đưa câu cuối (thường là yêu cầu/định dạng trả lời) lên trước, giữ nguyên nội dung từng câu."""
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    return text if len(parts) < 3 else " ".join([parts[-1], *parts[:-1]])


def vi(text: str, seed: int) -> str:
    return VI_PREFIX + text


FUNCS = {"typos": typos, "abbrev": abbrev, "reorder": reorder, "vi": vi}


def make_fi(base: Task) -> dict:
    d = copy.deepcopy(base.to_dict())
    d.update(id=f"FI-{base.id}", category="FI", tags=[*base.tags, "fault_injection"], suites=[], review_status="verified",
             provenance={"kind": "derived", "from": base.id, "fault": "tool_unavailable", "tools": list(FI_TOOLS), "times": FI_TIMES},
             tool_rules=[{"tool": t, "kind": "raise", "error": "TimeoutError", "times": FI_TIMES, "message": "injected fault: tool timed out"} for t in FI_TOOLS])
    return d


def make_c9(base: Task, k: int) -> dict:
    d = copy.deepcopy(base.to_dict())
    turns = [dict(t) for t in d["turns"]]
    for j in range(len(TRANSFORMS)):                       # phép xoay vòng không đổi gì (vd không có từ để viết tắt) thì thử phép kế tiếp; nhãn ghi phép THỰC SỰ đã áp
        name = TRANSFORMS[(k + j) % len(TRANSFORMS)]
        new = FUNCS[name](turns[0]["user"], seed=hash_seed(base.id) + j)
        if new != turns[0]["user"]:
            break
    turns[0]["user"] = new
    d.update(id=f"C9-{base.id}-{name}", category="C9", turns=turns, tags=[*base.tags, "robustness", name], suites=[], review_status="verified",
             provenance={"kind": "derived", "from": base.id, "transform": name})
    return d


def hash_seed(s: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(s))


def generate(split: str, root: Path = ROOT / "eval" / "tasks"):
    base = [t for t in load_tasks(root, split=split) if t.category in ("C1", "C2", "C3")]
    fi = [make_fi(t) for t in base if t.category in ("C1", "C2")]
    c9 = [make_c9(t, k) for k, t in enumerate(base)]
    for d in fi + c9:
        Task.from_dict(d)                                  # kiểm schema ngay khi sinh
    return fi, c9


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", required=True, choices=["dev", "test"])
    a = ap.parse_args(argv)
    fi, c9 = generate(a.split)
    for cat, items in (("FI", fi), ("C9", c9)):
        out = ROOT / "eval" / "tasks" / cat / f"{cat.lower()}_{a.split}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# Sinh bởi eval/generators/gen_p9.py --split {a.split}: KẾ THỪA ground truth/grader của task gốc (provenance.from). Không sửa tay.\n"
                       + yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {len(items)} task", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
