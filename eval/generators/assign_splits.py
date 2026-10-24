"""Chia task thành dev (~30%) / test (~70%), phân tầng theo nhóm, cố định bằng seed, ghi vào trường `split:` của YAML.

* Phân tầng theo nhóm (category); riêng C1 phân tầng thêm theo chip để dev có đủ ba chip, C3 theo loại task (pwm/uart/i2c/pll/combo); C4 theo họ xung đột chính (tag đầu: pin_conflict/no_such_af/non_ft/timer_shared/clock_limit/level_shift/multi_conflict).
* Task gần như trùng 8 câu ví dụ của UI agent (agent/ui/static/index.html) bị ép vào dev (không được vào test).
* Số task dev mỗi nhóm = round(0.3 * n); chia cho các tầng theo phần dư lớn nhất.

    eval/.venv/bin/python -m eval.generators.assign_splits --seed 20261021
"""
from __future__ import annotations

import argparse
import difflib
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV_FRACTION = 0.3


def stratum_of(task) -> str:
    """Tầng chia dev/test trong một nhóm: C1 theo chip (dev có đủ ba chip); C3 theo loại task (tag đầu: pwm/uart/i2c/pll/combo); C4 theo họ xung đột chính (tag đầu); còn lại theo nhóm."""
    if task.category == "C1" and task.chips:
        return task.chips[0]
    if task.category in ("C3", "C4") and task.tags:
        return task.tags[0]
    return task.category


def ui_examples() -> list[str]:
    """8 câu EXAMPLES trong UI hiện tại (đọc trực tiếp từ snapshot Agent v1 để không phụ thuộc agent/ đang phát triển)."""
    html = (ROOT / "snapshots" / "agent_v1" / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    block = re.search(r"const EXAMPLES = \[(.*?)\];", html, re.S).group(1)
    return re.findall(r'"((?:[^"\\]|\\.)*)"', block)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split()


def near_duplicates(texts: dict[str, str], examples: list[str], threshold: float = 0.8) -> set[str]:
    out = set()
    for tid, text in texts.items():
        a = " ".join(_norm(text))
        for ex in examples:
            b = " ".join(_norm(ex))
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            tokens_a, tokens_b = set(a.split()), set(b.split())
            jaccard = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
            if ratio >= threshold or jaccard >= threshold:
                out.add(tid)
    return out


def _allocate(total: int, sizes: dict[str, int]) -> dict[str, int]:
    """Phần dư lớn nhất: chia `total` suất dev cho các tầng theo kích thước."""
    n = sum(sizes.values())
    raw = {k: total * v / n for k, v in sizes.items()}
    got = {k: int(r) for k, r in raw.items()}
    for k in sorted(raw, key=lambda k: (raw[k] - got[k], sizes[k]), reverse=True)[: total - sum(got.values())]:
        got[k] += 1
    return got


def plan_splits(tasks: dict[str, tuple[str, str]], seed: int, force_dev: set[str] = frozenset(),
                dev_fraction: float = DEV_FRACTION) -> dict[str, str]:
    """tasks: id -> (category, stratum). Trả về id -> 'dev' | 'test'."""
    plan: dict[str, str] = {}
    by_cat: dict[str, list[str]] = {}
    for tid, (cat, _) in tasks.items():
        by_cat.setdefault(cat, []).append(tid)
    for cat, members in sorted(by_cat.items()):
        total_dev = int(dev_fraction * len(members) + 0.5)
        forced = [t for t in members if t in force_dev]
        strata: dict[str, list[str]] = {}
        for t in sorted(members):
            strata.setdefault(tasks[t][1], []).append(t)
        quota = _allocate(max(total_dev, len(forced)), {k: len(v) for k, v in strata.items()})
        for k, v in sorted(strata.items()):
            rng = random.Random(f"{seed}:{cat}:{k}")
            pool = sorted(v)
            rng.shuffle(pool)
            dev = [t for t in pool if t in force_dev]
            dev += [t for t in pool if t not in force_dev][: max(0, quota[k] - len(dev))]
            for t in v:
                plan[t] = "dev" if t in dev else "test"
    return plan


def apply_splits(path: Path, plan: dict[str, str]) -> None:
    """Ghi lại dòng `split:` của từng task trong file YAML, giữ nguyên mọi dòng khác (kể cả chú thích)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines(keepends=True)
    current = None
    for i, line in enumerate(lines):
        m = re.match(r"^-\s+id:\s*(\S+)", line) or re.match(r"^id:\s*(\S+)", line)
        if m:
            current = m.group(1).strip("'\"")
        elif current in plan and re.match(r"^\s*split:\s*\S+", line):
            indent = re.match(r"^(\s*)", line).group(1)
            lines[i] = f"{indent}split: {plan[current]}\n"
    Path(path).write_text("".join(lines), encoding="utf-8")


SMOKE_IDS = ["C1-002", "C1-022", "C2-003", "C6-005", "C6-015", "C7-004", "C7-012", "C8-004"]   # task dev trải các nhóm


def apply_suites(path: Path, ids: set[str], suite: str) -> None:
    """Thêm `suites: [<suite>]` ngay sau dòng `split:` của các task trong `ids` (idempotent)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines(keepends=True)
    out, current = [], None
    for i, line in enumerate(lines):
        m = re.match(r"^-\s+id:\s*(\S+)", line) or re.match(r"^id:\s*(\S+)", line)
        if m:
            current = m.group(1).strip("'\"")
        if current in ids and re.match(r"^\s*suites:", line):
            continue                                   # bỏ dòng suites cũ để ghi lại (idempotent)
        out.append(line)
        if current in ids and re.match(r"^\s*split:\s*\S+", line):
            indent = re.match(r"^(\s*)", line).group(1)
            out.append(f"{indent}suites: [{suite}]\n")
    Path(path).write_text("".join(out), encoding="utf-8")


def main() -> int:
    import yaml

    from eval.schema import load_tasks

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--tasks", type=Path, default=ROOT / "eval" / "tasks")
    a = ap.parse_args()
    tasks = load_tasks(a.tasks, include_needs_human=True)
    meta = {t.id: (t.category, stratum_of(t)) for t in tasks}
    forced = near_duplicates({t.id: t.turns[0]["user"] for t in tasks}, ui_examples(), threshold=0.75)
    plan = plan_splits(meta, a.seed, force_dev=forced)
    for f in sorted(a.tasks.rglob("*.yaml")):
        apply_splits(f, plan)
        apply_suites(f, set(SMOKE_IDS), "smoke")
    counts: dict[str, list[int]] = {}
    for tid, s in plan.items():
        counts.setdefault(meta[tid][0], [0, 0])[0 if s == "dev" else 1] += 1
    print("seed", a.seed, "| force_dev(UI examples):", sorted(forced))
    for c, (d, t) in sorted(counts.items()):
        print(f"  {c}: dev={d} test={t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
