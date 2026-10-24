"""Recall@k của truy hồi trên split `dev` (C1 + C2): trang được truy hồi có chứa giá trị kỳ vọng không?

Cùng định nghĩa với `retrieval_hit` của grader citation (S1): hit khi ít nhất một trang/chunk trong top-k chứa một fact
kiểm được (`task_facts` + `fact_present`). Chỉ nạp split `dev` (D05 — không đụng split `test`).

    agent/.venv/bin/python -m eval.tools.retrieval_recall [--out plan/P1_retrieval_recall.json]

Chạy bằng venv của agent (cần numpy/sentence-transformers cho truy hồi dense). Đọc chỉ mục `agent/data/text_index.*`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from eval.context import GradeContext  # noqa: E402
from eval.graders.citation import task_facts  # noqa: E402
from eval.graders.common import fact_present  # noqa: E402
from eval.schema import load_tasks  # noqa: E402

KS = (4, 8)
MODES = ("bm25", "dense", "hybrid")


def s1_baseline(scores_path: Path, task_ids: set[str]) -> dict:
    """Recall@4 của S1 = trung bình (theo task, rồi theo seed) của citation.details.retrieval_hit trong scores.jsonl."""
    per: dict[str, list[bool]] = {}
    for line in scores_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["system"] != "S1" or r["split"] != "dev" or r["task_id"] not in task_ids or r.get("infra"):
            continue
        c = r["graders"].get("citation")
        if c and c["details"].get("source") == "sources":
            per.setdefault(r["task_id"], []).append(bool(c["details"]["retrieval_hit"]))
    by_task = {t: sum(v) / len(v) for t, v in per.items()}
    return {"k": 4, "tasks": len(by_task), "recall": sum(by_task.values()) / len(by_task) if by_task else None,
            "by_task": by_task}


def measure(index, ctx, tasks, ks=KS, modes=MODES) -> dict:
    res = {m: {k: {"page": {}, "first_page": {}, "chunk": {}} for k in ks} for m in modes}
    for t in tasks:
        facts = task_facts(t)
        if not facts:
            continue
        q = t.turns[0]["user"]
        for m in modes:
            hits = index.search(q, k=max(ks), mode=m, pool=60)
            for k in ks:
                top = hits[:k]
                res[m][k]["page"][t.id] = any(
                    any(fact_present(ctx.page_text(h["doc"], p) or "", f) for f in facts)
                    for h in top for p in range(h["page_start"], h["page_end"] + 1))
                # S1 chỉ có MỘT trang cho mỗi nguồn; 'first_page' là biến thể cùng đơn vị với S1 (trang đầu của chunk),
                # 'page' chấp nhận mọi trang trong page_start..page_end (rộng hơn), 'chunk' yêu cầu chính chunk chứa giá trị (chặt nhất)
                res[m][k]["first_page"][t.id] = any(
                    any(fact_present(ctx.page_text(h["doc"], h["page_start"]) or "", f) for f in facts) for h in top)
                res[m][k]["chunk"][t.id] = any(fact_present(h["text"], f) for h in top for f in facts)
    return res


def summarize(res: dict, tasks) -> dict:
    cat = {t.id: t.category for t in tasks}
    out = {}
    for m, by_k in res.items():
        out[m] = {}
        for k, by_kind in by_k.items():
            out[m][k] = {}
            for kind, per in by_kind.items():
                allv = list(per.values())
                row = {"all": sum(allv) / len(allv) if allv else None, "n": len(allv)}
                for c in ("C1", "C2"):
                    v = [per[i] for i in per if cat[i] == c]
                    row[c] = sum(v) / len(v) if v else None
                out[m][k][kind] = row
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "plan" / "P1_retrieval_recall.json"))
    ap.add_argument("--scores", default=str(ROOT / "eval" / "results" / "dev_baseline" / "scores.jsonl"))
    a = ap.parse_args(argv)
    from ingestion.text_index import TextIndex, default_embedder

    tasks = load_tasks(ROOT / "eval" / "tasks", split="dev", categories=("C1", "C2"))
    assert tasks and all(t.split == "dev" for t in tasks)
    ctx = GradeContext.load()
    index = TextIndex(embedder=default_embedder())
    res = measure(index, ctx, tasks)
    summary = summarize(res, tasks)
    base = s1_baseline(Path(a.scores), {t.id for t in tasks})
    per_task = {m: {k: {kind: res[m][k][kind] for kind in res[m][k]} for k in res[m]} for m in res}
    out = {"split": "dev", "categories": ["C1", "C2"], "n_tasks": len(tasks), "S1_top4": {k: v for k, v in base.items() if k != "by_task"},
           "S1_by_task": base["by_task"], "agent_index": summary, "agent_by_task": {
               m: {str(k): per_task[m][k] for k in per_task[m]} for m in per_task},
           "index_meta": {k: v for k, v in index.meta().items() if k in ("n_chunks", "model", "chunking")}}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"dev C1+C2 tasks: {len(tasks)}  | S1 Recall@4 = {base['recall']:.3f} over {base['tasks']} tasks")
    for m in MODES:
        for k in KS:
            s = summary[m][k]
            print(f"{m:7s} k={k}: first-page {s['first_page']['all']:.3f} | page-range {s['page']['all']:.3f} "
                  f"(C1 {s['page']['C1']:.3f}, C2 {s['page']['C2']:.3f}) | chunk-text {s['chunk']['all']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
