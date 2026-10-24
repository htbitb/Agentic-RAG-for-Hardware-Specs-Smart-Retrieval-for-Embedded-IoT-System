"""Chia PDF thành chunk THEO CẤU TRÚC cho text index (W1): outline/bookmark -> breadcrumb 'Chương > Mục > Tiểu mục'.

* Mỗi chunk nằm trong một mục (tiêu đề tách ngay trong trang), mang `doc_id`, `page_start`, `page_end`, `breadcrumb`.
* Không cắt ngang bảng nếu tránh được (ranh giới chỉ đặt giữa hai dòng khi không cùng là dòng bảng).
* Header/footer lặp lại của từng tài liệu bị loại; mục quá nhỏ được gộp vào mục kế (không mất nội dung).
* Tài liệu không có bookmark (FreeRTOS) dùng tiêu đề số 'N.M Tên' làm outline tổng hợp.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import pdfdocs
from .pdfdocs import OutlineEntry

MAX_CHARS = 1100        # ~ vừa cửa sổ 256 token của all-MiniLM-L6-v2 (D09), cùng cỡ chunk 1000 của S1
OVERLAP = 120
MIN_SECTION_CHARS = 200

_NOISE = [re.compile(p) for p in (
    r"^\s*RM0440 Rev \d+ \d+/\d+\s*$", r"^\s*\d+/\d+ RM0440 Rev \d+\s*$", r"^\s*RM0440\s+\S.*$",
    r"^\s*DS12288 Rev \d+\s+\d+/\d+\s*$", r"^\s*\d+/\d+\s+DS12288 Rev \d+\s*$", r"^\s*STM32G474x[BCE].*Datasheet.*$",
    r"^\s*(Pinouts and pin description|Electrical characteristics|Functional overview|Package information)\s+STM32G4.*$",
    r"^\s*STM32G474xB STM32G474xC STM32G474xE.*$", r"^\s*\d{1,3}\s*$",
    r"^\s*Espressif Systems \d+\s*$", r"^\s*Submit Documentation Feedback\s*$", r"^\s*ESP32 TRM \(Version [\d.]+\)\s*$",
    r"^\s*ESP32 Series Datasheet v[\d.]+\s*$", r"^\s*Chapter \d+ .*GoBack\s*$",
    r"^\s*4413_417 v[\d.]+ \d+\s*$",
    r".*(?:\. ){4,}.*", r".*\.{6,}.*",                      # mục lục: dòng có chuỗi dấu chấm dẫn
)]
_TABLE_TOKEN = re.compile(r"^(?:[-+]?[\d.,]+|0[xX][0-9A-Fa-f]+|[A-Z]{1,3}\d*|rw|r|w|rc_w1|-|—|Res\.|\(\d+\)|\d+\(\d+\))$")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    chip: str
    page_start: int
    page_end: int
    breadcrumb: str
    section: str
    text: str
    ord: int


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip() or any(rx.match(line) for rx in _NOISE):
            continue
        out.append(line)
    return out


def _is_table_line(line: str) -> bool:
    toks = line.split()
    if len(toks) < 3:
        return False
    hits = sum(1 for t in toks if _TABLE_TOKEN.match(t))
    return hits / len(toks) >= 0.6


def _find_heading_line(lines: list[str], title: str) -> int | None:
    key = _squash(title)[:30]
    for i, line in enumerate(lines):
        sl = _squash(line)
        if sl.startswith(key) or (len(sl) >= 8 and key.startswith(sl)):
            return i
    return None


def synthetic_outline(pages: dict[int, str], first_page: int = 10) -> list[OutlineEntry]:
    """Outline từ tiêu đề số 'N.M Tên' (tài liệu không có bookmark); bỏ qua mục lục (trang đầu)."""
    out: list[OutlineEntry] = []
    stack: list[tuple[int, str]] = []
    rx = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+([A-Za-z_][\w()/\-, ]{2,70}?)\s*$")
    for p in sorted(pages):
        if p < first_page:
            continue
        for line in pages[p].split("\n"):
            m = rx.match(line)
            if not m or len(m.group(2).split()) > 8 or m.group(2).endswith("."):
                continue
            level = m.group(1).count(".")
            title = f"{m.group(1)} {m.group(2).strip()}"
            while stack and stack[-1][0] >= level:
                stack.pop()
            out.append(OutlineEntry(level, title, p, tuple(t for _l, t in stack)))
            stack.append((level, title))
    return out


def _split_items(items: list[tuple[int, str]], max_chars: int, overlap: int) -> list[list[tuple[int, str]]]:
    chunks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    size = 0
    n = len(items)
    for idx, (pg, line) in enumerate(items):
        cur.append((pg, line))
        size += len(line) + 1
        nxt = items[idx + 1][1] if idx + 1 < n else None
        if nxt is None:
            break
        safe = not (_is_table_line(line) and _is_table_line(nxt))
        if size >= max_chars and not safe and size < int(max_chars * 1.6):
            run = len(cur)                                   # đang ở giữa bảng: tìm điểm bắt đầu của bảng
            while run > 0 and _is_table_line(cur[run - 1][1]):
                run -= 1
            run_chars = sum(len(l) + 1 for _p, l in cur[run:])
            if 0 < run and run_chars <= int(max_chars * 1.6):
                chunks.append(cur[:run])                     # đóng chunk TRƯỚC bảng, bảng mở chunk mới
                cur, size = cur[run:], run_chars
                continue
        if (size >= max_chars and safe) or size >= int(max_chars * 1.6):
            chunks.append(cur)
            tail: list[tuple[int, str]] = []
            tsz = 0
            for it in reversed(cur):
                if tsz + len(it[1]) + 1 > overlap or _is_table_line(it[1]):
                    break
                tail.insert(0, it)
                tsz += len(it[1]) + 1
            cur, size = tail, tsz
    if cur and (not chunks or any(l not in chunks[-1] for l in cur)):
        chunks.append(cur)
    return chunks


def chunk_pages(pages: dict[int, str], outline: list[OutlineEntry], *, doc_id: str, chip: str, doc_title: str,
                max_chars: int = MAX_CHARS, overlap: int = OVERLAP, min_section_chars: int = MIN_SECTION_CHARS) -> list[Chunk]:
    ol = [e for e in outline if e.page is not None]
    by_page: dict[int, list[OutlineEntry]] = {}
    for e in ol:
        by_page.setdefault(e.page, []).append(e)
    # 1) luồng (section_path, page, line)
    sections: list[tuple[tuple[str, ...], list[tuple[int, str]]]] = []
    path: tuple[str, ...] = ()
    cur: list[tuple[int, str]] = []

    def flush():
        nonlocal cur
        if cur:
            sections.append((path, cur))
        cur = []

    for p in sorted(pages):
        lines = _clean_lines(pages[p])
        events: list[tuple[int, OutlineEntry]] = []
        last = 0
        for e in by_page.get(p, []):
            i = _find_heading_line(lines, e.title)
            i = last if i is None else max(i, last)
            events.append((i, e))
            last = i
        pos = 0
        for i, e in events:
            for ln in lines[pos:i]:
                cur.append((p, ln))
            flush()
            path = tuple(e.path) + (e.title,)
            pos = i                                     # dòng tiêu đề thuộc mục mới
        for ln in lines[pos:]:
            cur.append((p, ln))
    flush()
    # 2) gộp mục nhỏ vào mục kế (không vượt ranh giới chương cấp 0)
    merged: list[tuple[tuple[str, ...], list[tuple[int, str]]]] = []
    carry: list[tuple[int, str]] = []
    carry_root = None
    for sp, items in sections:
        root = sp[0] if sp else None
        if carry and root != carry_root:
            merged.append((sp_prev, carry))
            carry = []
        items = carry + items
        size = sum(len(l) + 1 for _p, l in items)
        if size < min_section_chars and (sp, items) is not sections[-1]:
            carry, carry_root, sp_prev = items, root, sp
            continue
        carry = []
        merged.append((sp, items))
    if carry:
        merged.append((sp_prev, carry))
    # 3) chia theo kích thước
    out: list[Chunk] = []
    for sp, items in merged:
        crumb = " > ".join((doc_title, *sp)) if sp else doc_title
        for part in _split_items(items, max_chars, overlap):
            text = "\n".join(l for _p, l in part).strip()
            if not text:
                continue
            k = len(out)
            out.append(Chunk(chunk_id=f"{doc_id}:{k:05d}", doc_id=doc_id, chip=chip, page_start=part[0][0],
                             page_end=part[-1][0], breadcrumb=crumb, section=sp[-1] if sp else "", text=text, ord=k))
    return out


def chunk_document(doc_id: str, **kw) -> list[Chunk]:
    entry = pdfdocs.manifest_entry(doc_id)
    pages = pdfdocs.load_pages(doc_id)
    outline = pdfdocs.load_outline(doc_id) or synthetic_outline(pages)
    return chunk_pages(pages, outline, doc_id=doc_id, chip=entry["chip"], doc_title=entry.get("title") or doc_id, **kw)
