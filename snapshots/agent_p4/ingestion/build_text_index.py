"""Dựng text index hybrid từ mọi PDF trong corpus/manifest.yaml: chunk theo cấu trúc -> FTS5 (BM25) + embedding MiniLM.

    agent/.venv/bin/python -m ingestion.build_text_index [--no-embeddings]
"""
from __future__ import annotations

import argparse
import datetime
import time

from . import pdfdocs
from .pdf_chunker import MAX_CHARS, MIN_SECTION_CHARS, OVERLAP, chunk_document
from .text_index import DEFAULT_DB, DEFAULT_EMB, MODEL_NAME, build_index, default_embedder


def manifest_docs() -> list[dict]:
    """Thông tin tài liệu từ corpus/manifest.yaml (nhúng vào index để `list_documents` tự đủ, không cần đọc manifest lúc chạy)."""
    out = []
    for e in pdfdocs.load_manifest():
        if e.get("kind") != "pdf":
            continue
        d = {"doc": e["doc_id"], "title": e.get("title"), "version": e.get("version"), "chip": e.get("chip"),
             "pages": e.get("pages"), "sha256": e.get("sha256"), "indexed": bool(e.get("file")),
             "aliases": e.get("aliases", [])}
        if not e.get("file"):
            d["note"] = "; ".join(e.get("known_issues") or []) or "no PDF in the corpus"
        out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--emb", default=str(DEFAULT_EMB))
    ap.add_argument("--no-embeddings", action="store_true", help="chỉ BM25 (không tải mô hình)")
    a = ap.parse_args(argv)
    t0 = time.time()
    chunks = []
    for e in pdfdocs.load_manifest():
        if e.get("kind") != "pdf" or not e.get("file"):
            continue
        cs = chunk_document(e["doc_id"])
        chunks += cs
        print(f"{e['doc_id']:22s} {len(cs):5d} chunks")
    embedder = None if a.no_embeddings else default_embedder()
    info = build_index(chunks, a.db, a.emb, embedder=embedder, meta={
        "model": None if a.no_embeddings else MODEL_NAME, "chunking": {"max_chars": MAX_CHARS, "overlap": OVERLAP,
                                                                          "min_section_chars": MIN_SECTION_CHARS},
        "docs": manifest_docs(), "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print(f"index: {info['n_chunks']} chunks, dim {info['dim']}, {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
