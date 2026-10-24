"""Sinh eval/tasks/INDEX.md: số task theo nhóm x split x chip x trạng thái duyệt."""
from __future__ import annotations

import collections
from pathlib import Path

from eval.schema import load_tasks

ROOT = Path(__file__).resolve().parents[2]


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def index_markdown(tasks) -> str:
    by_cat = collections.defaultdict(lambda: {"dev": 0, "test": 0})
    by_chip = collections.defaultdict(lambda: {"dev": 0, "test": 0})
    status = collections.Counter()
    for t in tasks:
        by_cat[t.category][t.split] += 1
        for c in (t.chips or ["(không gắn chip)"]):
            by_chip[c][t.split] += 1
        status[t.review_status] += 1
    cat_rows = [[c, v["dev"], v["test"], v["dev"] + v["test"]] for c, v in sorted(by_cat.items())]
    dev, test = sum(r[1] for r in cat_rows), sum(r[2] for r in cat_rows)
    cat_rows.append(["**Tổng**", dev, test, dev + test])
    chip_rows = [[c, v["dev"], v["test"], v["dev"] + v["test"]] for c, v in sorted(by_chip.items())]
    st_rows = [[k, v] for k, v in sorted(status.items())]
    return "\n\n".join([
        "# Chỉ mục task (P0)",
        "Sinh bởi `python -m eval.tools.make_index`. P0 chỉ chạy split `dev`; `test` được niêm phong cho báo cáo cuối.",
        "## Theo nhóm x split\n" + _table(["Nhóm", "dev", "test", "Tổng"], cat_rows),
        "## Theo chip x split (task nhiều chip được tính cho từng chip)\n" + _table(["Chip", "dev", "test", "Tổng"], chip_rows),
        "## Theo trạng thái duyệt\n" + _table(["review_status", "Số task"], st_rows),
        "`auto` = sinh tự động (C1, từ SVD, chỉ giữ khi PDF corpus nhắc tới thanh ghi/giá trị); `verified` = đã qua "
        "`eval.tools.verify_tasks` (bằng chứng trên text trang) nhưng CHƯA có người duyệt độc lập; `needs_human` = bị loại khỏi chạy chính thức.",
    ]) + "\n"


def main() -> int:
    tasks = load_tasks(ROOT / "eval" / "tasks", include_needs_human=True)
    (ROOT / "eval" / "tasks" / "INDEX.md").write_text(index_markdown(tasks), encoding="utf-8")
    print(f"INDEX.md: {len(tasks)} task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
