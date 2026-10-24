"""Trích text từng trang PDF của corpus -> corpus/.cache/pages/<doc_id>.jsonl.

Mỗi dòng: {"page_1based": int, "text": str}. Dùng cho grader citation và để kiểm
tra ground truth (xem eval/graders/citation.py).

Chạy bằng venv của eval:
    eval/.venv/bin/python corpus/build_page_text.py            # mọi PDF, bỏ qua doc đã có cache khớp sha256
    eval/.venv/bin/python corpus/build_page_text.py --doc STM32G474_RM0440 --force
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

CORPUS = Path(__file__).resolve().parent
PAGES_DIR = CORPUS / ".cache" / "pages"


def load_manifest() -> list[dict]:
    return yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))


def _cache_ok(entry: dict) -> bool:
    jsonl, stamp = PAGES_DIR / f"{entry['doc_id']}.jsonl", PAGES_DIR / f"{entry['doc_id']}.sha256"
    return jsonl.is_file() and stamp.is_file() and stamp.read_text().strip() == entry["sha256"]


def extract_doc(entry: dict) -> tuple[str, int, float]:
    from pypdf import PdfReader

    t0 = time.time()
    reader = PdfReader(str(CORPUS / entry["file"]))
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PAGES_DIR / f"{entry['doc_id']}.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # trang hỏng không được làm sập cả tài liệu
                text = ""
                print(f"[warn] {entry['doc_id']} p.{i}: {type(exc).__name__}", file=sys.stderr)
            f.write(json.dumps({"page_1based": i, "text": text}, ensure_ascii=False) + "\n")
    tmp.replace(PAGES_DIR / f"{entry['doc_id']}.jsonl")
    (PAGES_DIR / f"{entry['doc_id']}.sha256").write_text(entry["sha256"])
    return entry["doc_id"], len(reader.pages), time.time() - t0


def load_pages(doc_id: str) -> list[str]:
    """Đọc cache: list text, chỉ số 0 ứng với trang PDF 1."""
    path = PAGES_DIR / f"{doc_id}.jsonl"
    return [json.loads(l)["text"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append", help="chỉ xử lý doc_id này (lặp lại được)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    todo = [e for e in load_manifest() if e.get("kind") == "pdf" and e.get("file")]
    if args.doc:
        todo = [e for e in todo if e["doc_id"] in args.doc]
    todo = [e for e in todo if args.force or not _cache_ok(e)]
    if not todo:
        print("cache đã đầy đủ")
        return 0
    todo.sort(key=lambda e: -(e.get("pages") or 0))
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for doc_id, n, dt in ex.map(extract_doc, todo):
            print(f"{doc_id}: {n} trang trong {dt:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
