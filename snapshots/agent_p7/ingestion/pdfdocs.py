"""Đọc corpus dùng chung: `corpus/manifest.yaml`, text từng trang (cache của `corpus/build_page_text.py`) và outline PDF.

Agent chỉ ĐỌC corpus; mọi giá trị trong DB truy được về SVD hoặc trang PDF của các file này. PDF là dữ liệu không tin
cậy: chỉ trích text/outline, không thực thi.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent          # agent/
CORPUS = ROOT.parent / "corpus"
PAGES_DIR = CORPUS / ".cache" / "pages"
OUTLINE_DIR = CORPUS / ".cache" / "outline"


@dataclass(frozen=True)
class OutlineEntry:
    level: int
    title: str
    page: int | None            # 1-based, theo chỉ số trang PDF (page_offset = 0 cho mọi doc hiện tại)
    path: tuple[str, ...]       # tiêu đề các mục cha (từ gốc xuống)


def load_manifest() -> list[dict]:
    return yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))


def manifest_entry(doc_id: str) -> dict:
    for e in load_manifest():
        if e["doc_id"] == doc_id:
            return e
    raise KeyError(doc_id)


def doc_pdf(doc_id: str) -> Path | None:
    f = manifest_entry(doc_id).get("file")
    return (CORPUS / f) if f else None


def load_pages(doc_id: str) -> dict[int, str]:
    """{trang 1-based: text}. Từ chối cache có sha256 không khớp manifest (PDF đã đổi mà cache chưa dựng lại)."""
    entry = manifest_entry(doc_id)
    jsonl, stamp = PAGES_DIR / f"{doc_id}.jsonl", PAGES_DIR / f"{doc_id}.sha256"
    if not jsonl.is_file():
        raise FileNotFoundError(f"{jsonl} missing - run corpus/build_page_text.py")
    if stamp.is_file() and stamp.read_text().strip() != entry["sha256"]:
        raise RuntimeError(f"{doc_id}: page cache sha256 does not match corpus/manifest.yaml")
    out: dict[int, str] = {}
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[int(r["page_1based"])] = r["text"]
    return out


def load_outline(doc_id: str) -> list[OutlineEntry]:
    """Outline/bookmark của PDF (pypdf), có cache JSON theo sha256. PDF không có bookmark -> []."""
    entry = manifest_entry(doc_id)
    cache = OUTLINE_DIR / f"{doc_id}.json"
    if cache.is_file():
        blob = json.loads(cache.read_text(encoding="utf-8"))
        if blob.get("sha256") == entry["sha256"]:
            return [OutlineEntry(e[0], e[1], e[2], tuple(e[3])) for e in blob["entries"]]
    pdf = doc_pdf(doc_id)
    if pdf is None:
        return []
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    entries: list[OutlineEntry] = []

    def walk(items, level: int, parents: tuple[str, ...]) -> None:
        last: str | None = None
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1, parents + ((last,) if last else ()))
                continue
            try:
                page = reader.get_destination_page_number(it) + 1
            except Exception:
                page = None
            title = " ".join(str(it.title).split())
            entries.append(OutlineEntry(level, title, page, parents))
            last = title

    walk(reader.outline, 0, ())
    OUTLINE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"sha256": entry["sha256"], "entries": [
        [e.level, e.title, e.page, list(e.path)] for e in entries]}, ensure_ascii=False), encoding="utf-8")
    return entries
