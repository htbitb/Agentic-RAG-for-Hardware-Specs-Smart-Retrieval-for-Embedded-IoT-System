"""Gắn trang tài liệu (RM/TRM/PS) cho từng thanh ghi trong SVD.

Nguồn trang (theo thứ tự tin cậy):
  * outline PDF (bookmark) — mỗi thanh ghi có mục "37.6.6 RTC wakeup timer register (RTC_WUTR)" kèm số trang chính xác
    (RM0440, nRF52840 PS);
  * text trang — dòng "Address offset: 0x14" / "Register 13.1. NAME_REG (0x0000)" / bảng Register Summary (ESP32 TRM).
Mỗi kết quả có `confidence`:  high = tên và offset cùng khớp trang mô tả thanh ghi; name = chỉ khớp tên (trang không
cho offset đọc được); offset_mismatch = khớp tên nhưng offset trên trang khác SVD (bất thường, báo trong báo cáo).
Không tìm được -> None (caller ghi `doc=<chip>_SVD`, `page=NULL`). Mọi nhận định "không có trong manual" là kết quả của
việc KHÔNG khớp được — báo cáo chất lượng phải nói rõ đây là chỉ báo chứ không phải bằng chứng tuyệt đối.
"""
from __future__ import annotations

import bisect
import difflib
import re
from dataclasses import dataclass, field

from . import pdfdocs
from .svd_ingest import Peripheral, Register

ST_RM = "STM32G474_RM0440"

# RM0440 mô tả 3 họ flash: ở chương riêng cho "category 3/4/2 devices". STM32G474 = Category 3 (RM0440 Table 1, tr.75).
CHAPTER_EXCLUDE = {"stm32g474": [re.compile(r"category [24] devices", re.I)]}


@dataclass
class PageRef:
    doc: str
    page: int
    confidence: str                      # high | name | offset_mismatch
    alt_pages: list[int] = field(default_factory=list)
    rm_name: str | None = None           # tên thanh ghi trong tài liệu
    rm_offsets: list[int] | None = None  # offset(s) tài liệu in (để báo cáo lệch)
    rm_reset: int | None = None          # reset value in trên trang (một giá trị duy nhất), để so với SVD
    note: str | None = None


@dataclass
class Block:
    doc: str
    page: int
    title: str
    names: list[str]
    var_sets: dict[str, set[str] | None]
    offsets: set[int] | None
    chapter: str
    alternate: bool = False
    abs_addrs: set[int] | None = None    # khi trang in địa chỉ tuyệt đối ('Address: 0xE004 2004')
    reset: int | None = None             # 'Reset value: 0x0004 0601' (chỉ khi là một giá trị duy nhất)
    path: tuple[str, ...] = ()           # tiêu đề các mục cha + mục này (để chọn chương theo tên peripheral)


# --------------------------------------------------------------------------- parsing helpers
_HEX = r"0[xX][0-9A-Fa-f_]+"


def _expand_range(spec: str) -> set[str] | None:
    """'A to G' / '1 to 8' / '1...6' / '2, 5' / '12 or 345' -> tập chuỗi."""
    spec = spec.strip().strip(".")
    out: set[str] = set()
    for part in re.split(r"\s*(?:,|\bor\b|\band\b)\s*", spec):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:to|\.\.\.|\.\.|-|–)\s*(\d+)", part)
        if m:
            out |= {str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)}
            continue
        m = re.fullmatch(r"([A-Za-z])\s*(?:to|\.\.\.|\.\.|-|–)\s*([A-Za-z])", part)
        if m:
            out |= {chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)}
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", part):
            out.add(part)
            continue
        return None
    return out or None


def parse_qualifier(title: str) -> dict[str, set[str] | None]:
    """'(TIMx_CR1)(x = 1, 8, 20)' -> {'x': {'1','8','20'}}. Không có qualifier -> {}."""
    out: dict[str, set[str] | None] = {}
    for m in re.finditer(r"\(\s*([xyn])\s*=\s*([^)]*)\)", title):
        out[m.group(1)] = _expand_range(m.group(2))
    return out


def parse_offsets(expr: str) -> set[int] | None:
    """Biểu thức 'Address offset' của ST -> tập offset. None nếu không đọc được (vd. [USB_BTABLE] + n*8)."""
    s = " ".join(expr.split())
    if "[" in s and "]" in s and "USB" in s:
        return None
    if re.search(r"\bBlock\b", s):
        vals = {int(h.replace("_", ""), 16) for h in re.findall(rf"Block [A-Z]:\s*({_HEX})", s)} or \
               {int(h.replace("_", ""), 16) for h in re.findall(_HEX, s)}
        return vals or None
    m = re.match(rf"({_HEX})\s*\+\s*({_HEX}|\d+)\s*\*\s*\(?\s*([xyn])\s*(?:-\s*(\d+))?\s*\)?\s*,?\s*\(?\s*\3\s*=\s*(\d+)\s*to\s*(\d+)", s)
    if m:
        base, stride = int(m.group(1).replace("_", ""), 16), int(m.group(2).replace("_", ""), 0)
        c = int(m.group(4) or 0)
        return {base + stride * (i - c) for i in range(int(m.group(5)), int(m.group(6)) + 1)}
    m = re.match(rf"({_HEX})\s+to\s+({_HEX})", s)
    if m:                                      # 'Address offset: 0x00 to 0x1C' (mảng thanh ghi liên tiếp, bước 4)
        lo, hi = (int(m.group(i).replace("_", ""), 16) for i in (1, 2))
        return set(range(lo, hi + 1, 4))
    m = re.match(rf"({_HEX})", s)
    if m:
        return {int(m.group(1).replace("_", ""), 16)}
    return None


_RESET_TEXT = re.compile(r"^\s*(0[xX][0-9A-Fa-f]{1,4}(?:\s[0-9A-Fa-f]{4})?)\s*\.?\s*$")


def parse_reset_text(s: str) -> int | None:
    """'0x0004 0601' -> 0x40601. None nếu có nhiều giá trị / bit không xác định (x, U) / chú thích ('for port A')."""
    m = _RESET_TEXT.match(s)
    return int(m.group(1).replace(" ", ""), 16) if m else None


# --------------------------------------------------------------------------- STM32 (RM0440)
_ST_HEAD = re.compile(r"^(\d+(?:\.\d+)+)\s+(.*)$")
_NAME_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]$")
_PAREN_NAME = re.compile(r"\(([A-Za-z][A-Za-z0-9_]*)\)")
_OFFSET_LINE = re.compile(r"^\s*Address offset\s*:\s*(.*)$")
_RESET_LINE = re.compile(r"^\s*(?:[A-Za-z-]+ (?:domain )?)?[Rr]eset value\s*:\s*(.*)$")
_BARE_NAME = re.compile(r"^\s*[A-Z][A-Z0-9]+_[A-Z0-9_]*[A-Z0-9]\s*$")
_ABS_LINE = re.compile(r"^\s*Address\s*:\s*(0[xX][0-9A-Fa-f ]+)\s*$")
_MODE_SUFFIX = re.compile(r"_(Output|Input)$", re.I)
OFFSET_FALLBACK_MIN_SIM = 0.6
ABS_ADDR_MIN = 0x20000000


def _name_tokens(title: str) -> list[str]:
    toks = []
    for m in re.finditer(r"\(([^()]*)\)", title):
        t = m.group(1).strip()
        if _NAME_TOKEN.match(t) and not re.match(r"^[xyn]$", t) and ("_" in t or t.isupper()):
            toks.append(t)
    return toks


def _reset_in(lines: list[str]) -> int | None:
    for ln in lines:
        m = _RESET_LINE.match(ln)
        if m:
            return parse_reset_text(m.group(1))
    return None


def _anchor_reset(page_text: str, section: str) -> int | None:
    m = re.search(rf"(?m)^\s*{re.escape(section)}\s", page_text)
    if not m:
        return None
    tail = page_text[m.end(): m.end() + 1500].split("\n")
    for i, line in enumerate(tail[:24]):
        if i and _ST_HEAD.match(line):
            return None
        mm = _RESET_LINE.match(line)
        if mm:
            return parse_reset_text(mm.group(1))
    return None


def _anchor_offset(page_text: str, section: str) -> tuple[str, str] | None:
    """('offset', biểu thức) từ dòng(các dòng liên tiếp) 'Address offset: ...' đầu tiên sau tiêu đề mục `section`;
    ('abs', '0xE0042004') nếu trang in địa chỉ tuyệt đối ('Address: 0xE004 2004'). None nếu không có."""
    m = re.search(rf"(?m)^\s*{re.escape(section)}\s", page_text)
    if not m:
        return None
    tail = page_text[m.end(): m.end() + 1200].split("\n")
    for i, line in enumerate(tail[:18]):
        if i and _ST_HEAD.match(line):
            return None                       # sang mục khác trước khi gặp "Address offset"
        mm = _OFFSET_LINE.match(line)
        if mm:
            parts = [mm.group(1)]
            for nxt in tail[i + 1: i + 9]:     # HRTIM: 'Address offset: Block A: 0x0BC' lặp cho Block B..F
                m2 = _OFFSET_LINE.match(nxt)
                if not m2:
                    break
                parts.append(m2.group(1))
            return "offset", " ".join(parts)
        ma = _ABS_LINE.match(line)
        if ma:
            v = re.sub(r"\s+", "", ma.group(1))
            return ("abs", v) if int(v, 16) >= ABS_ADDR_MIN else ("offset", v)   # RCC: 'Address: 0x58' là offset
    return None


def stm32_blocks(doc_id: str = ST_RM) -> list[Block]:
    """Khối mô tả thanh ghi: (1) từ outline PDF (có số trang chính xác); (2) từ text trang cho những mục không có
    trong outline (tiêu đề ngắt dòng, vd. FMC_BCRx, USB_EPnR)."""
    pages = pdfdocs.load_pages(doc_id)
    outline = [e for e in pdfdocs.load_outline(doc_id) if e.page is not None]
    out: list[Block] = []
    seen: set[tuple[int, str]] = set()
    for e in outline:
        m = _ST_HEAD.match(e.title)
        names = _name_tokens(e.title) if m else []
        if not names:
            continue
        anchor = _anchor_offset(pages.get(e.page, ""), m.group(1))
        expr = anchor[1] if anchor and anchor[0] == "offset" else None
        offsets = parse_offsets(expr) if expr else None
        absa = {int(anchor[1], 16)} if anchor and anchor[0] == "abs" else None
        quals = parse_qualifier(e.title)
        if expr:
            for k, v in parse_qualifier(expr).items():
                quals.setdefault(k, v)
        out.append(Block(doc=doc_id, page=e.page, title=e.title, names=names, var_sets=quals, offsets=offsets,
                         chapter=e.path[0] if e.path else e.title, alternate="[alternate]" in e.title,
                         abs_addrs=absa, reset=_anchor_reset(pages.get(e.page, ""), m.group(1)),
                         path=e.path + (e.title,)))
        seen.update((e.page, n.upper()) for n in names)
    starts = [e.page for e in outline]
    for page, text in sorted(pages.items()):
        lines = text.split("\n")
        last_offset_line = -1
        for i, line in enumerate(lines):
            mo, ma = _OFFSET_LINE.match(line), _ABS_LINE.match(line)
            if not (mo or ma) or i <= last_offset_line:
                continue
            kind, expr, k = "offset", "", i
            if mo:
                while k + 1 < len(lines) and _OFFSET_LINE.match(lines[k + 1]):
                    k += 1
                expr = " ".join(_OFFSET_LINE.match(lines[j]).group(1) for j in range(i, k + 1))
            else:
                v = re.sub(r"\s+", "", ma.group(1))
                kind, expr = ("abs", v) if int(v, 16) >= ABS_ADDR_MIN else ("offset", v)
            head = lines[max(last_offset_line + 1, i - 8): i]
            last_offset_line = k
            name = next((n for l in reversed(head) for n in reversed(_PAREN_NAME.findall(l)) if "_" in n), None)
            if not name and head and _BARE_NAME.match(head[-1]):
                name = head[-1].strip()           # 'DBGMCU_IDCODE' đứng riêng một dòng
            if not name or (page, name.upper()) in seen:
                continue
            j = bisect.bisect_right(starts, page) - 1
            ctx = (outline[j].path + (outline[j].title,)) if j >= 0 else ()
            quals = parse_qualifier(" ".join(head) + " " + expr)
            title = " ".join(x.strip() for x in head if x.strip())[-160:]
            out.append(Block(doc=doc_id, page=page, title=title, names=[name], var_sets=quals,
                             offsets=parse_offsets(expr) if kind == "offset" else None,
                             abs_addrs={int(expr, 16)} if kind == "abs" else None,
                             reset=_reset_in(lines[k + 1: k + 8]),
                             chapter=ctx[0] if ctx else "", alternate="[alternate]" in title, path=ctx))
            seen.add((page, name.upper()))
    return out


def group_bases(device) -> dict[str, int]:
    """groupName -> địa chỉ nhỏ nhất của nhóm. SVD của ST đặt base HRTIM_TIMA = base HRTIM + 0x80 còn RM in offset
    từ base HRTIM; so offset cả theo `address - group_base`."""
    out: dict[str, int] = {}
    for p in device.peripherals:
        if p.group:
            out[p.group] = min(out.get(p.group, p.base_address), p.base_address)
    return out


def _st_candidates(p: Peripheral, r: Register) -> list[tuple[int, str]]:
    """Tên thanh ghi trong RM có thể tương ứng, theo ưu tiên (số nhỏ = ưu tiên cao).
    SVD tách một thanh ghi hai chế độ thành `CCMR1_Output` / `CCMR1_Input`; RM chỉ gọi `TIMx_CCMR1`."""
    tok0 = p.name.split("_")[0]
    pbase = re.sub(r"\d+$", "", tok0)
    variants = [r.short_name]
    stripped = _MODE_SUFFIX.sub("", r.short_name)
    if stripped != r.short_name:
        variants.append(stripped)
    cands: list[tuple[int, str]] = []
    for s in variants:
        cands += [(0, f"{p.name}_{s}"), (1, f"{tok0}_{s}"), (2, f"{pbase}_{s}")]
        if p.group:
            cands.append((3, f"{p.group}_{s}"))
        cands.append((4, s))
    seen, out = set(), []
    for pr, c in cands:
        if c.upper() not in seen:
            seen.add(c.upper())
            out.append((pr, c))
    return out


def _name_matches(block_name: str, var_sets: dict, cand: str) -> bool:
    """Tên trong RM có chữ thường x/y/n = biến (TIMx_CR1, DMA_CCRx, USB_EPnR). Giá trị biến phải thuộc qualifier."""
    if block_name.upper() == cand.upper():
        return True
    vars_in = sorted({ch for ch in block_name if ch in "xyn"})
    if not vars_in:
        return False
    rx, seen = "", {}
    for ch in block_name:
        if ch in vars_in:
            if ch in seen:
                rx += f"(?P={seen[ch]})"
            else:
                seen[ch] = f"v_{ch}"
                rx += f"(?P<v_{ch}>[A-Za-z0-9]+?)"
        else:
            rx += re.escape(ch)
    m = re.fullmatch(rx, cand, re.I)
    if not m:
        return False
    for v, grp in seen.items():
        allowed = var_sets.get(v)
        if allowed is not None and m.group(grp).upper() not in {a.upper() for a in allowed}:
            return False
    return True


def _offset_ok(b: Block, offs: set[int], r: Register) -> bool:
    if b.abs_addrs is not None:
        return r.address in b.abs_addrs
    return b.offsets is None or bool(offs & b.offsets)


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def locate_stm32(chip: str, p: Peripheral, r: Register, blocks: list[Block],
                 bases: dict[str, int] | None = None) -> PageRef | None:
    excl = CHAPTER_EXCLUDE.get(chip, [])
    offs = {r.offset}
    gb = (bases or {}).get(p.group or "")
    if gb is not None and gb != p.base_address:
        offs.add(r.address - gb)
    cands = _st_candidates(p, r)
    # RM: trang chính = input capture, trang "[alternate]" = output compare
    mode = (_MODE_SUFFIX.search(r.short_name) or [None, None])[1]
    want_alt = None if mode is None else (mode.lower() == "output")
    best: list[tuple[tuple, Block]] = []
    for b in blocks:
        if any(x.search(b.chapter) for x in excl):
            continue
        for bn in b.names:
            for pr, c in cands:
                if _name_matches(bn, b.var_sets, c):
                    off_ok = _offset_ok(b, offs, r)
                    mode_ok = 0 if (want_alt is None or b.alternate == want_alt) else 1
                    best.append(((pr, 0 if off_ok else 1, mode_ok, 1 if b.alternate else 0, b.page), b))
                    break
    if best:
        best.sort(key=lambda t: t[0])
        top_key, top = best[0]
        same = [b for k, b in best if b.page != top.page and (k[:3] == top_key[:3] or (
            k[:2] == top_key[:2] and b.alternate != top.alternate))]
        has_loc = top.offsets is not None or top.abs_addrs is not None
        conf = "high" if (has_loc and _offset_ok(top, offs, r)) else ("name" if not has_loc else "offset_mismatch")
        variants = {b.reset for k, b in best if b.reset is not None and k[:2] == top_key[:2]}
        rm_reset = r.reset_value if r.reset_value in variants else top.reset   # RM có thể có nhiều biến thể (FIFO on/off)
        return PageRef(top.doc, top.page, conf, alt_pages=sorted({b.page for b in same}), rm_name=top.names[0],
                       rm_offsets=sorted(top.offsets) if top.offsets else None, rm_reset=rm_reset)
    return _offset_fallback(p, r, blocks, offs, excl)


def _offset_fallback(p: Peripheral, r: Register, blocks: list[Block], offs: set[int], excl) -> PageRef | None:
    """Tên SVD khác tên RM (CFG1 vs UCPD_CFGR1): cùng offset + chương/mục nhắc peripheral + tên đủ giống + duy nhất."""
    tok0 = p.name.split("_")[0]
    wanted = {x.upper() for x in (p.name, tok0, re.sub(r"\d+$", "", tok0), p.group or "") if x}
    scored: list[tuple[float, Block, str]] = []
    for b in blocks:
        if (b.offsets is None and b.abs_addrs is None) or not _offset_ok(b, offs, r) or \
                any(x.search(b.chapter) for x in excl):
            continue
        toks = set(re.findall(r"[A-Za-z0-9]+", " ".join(b.path or (b.chapter,)).upper()))
        if not (wanted & toks):
            continue
        for bn in b.names:
            suffix = bn.split("_", 1)[-1]
            sim = difflib.SequenceMatcher(None, _norm(r.short_name), _norm(suffix)).ratio()
            if sim >= OFFSET_FALLBACK_MIN_SIM:
                scored.append((sim, b, bn))
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.05 and scored[1][1].page != scored[0][1].page:
        return None                            # hai ứng viên ngang nhau -> không đoán
    sim, b, bn = scored[0]
    return PageRef(b.doc, b.page, "offset", rm_name=bn, rm_offsets=sorted(b.offsets) if b.offsets else None,
                   note=f"name differs: SVD {r.short_name!r} vs manual {bn!r} (matched by offset, similarity {sim:.2f})")


# --------------------------------------------------------------------------- nRF52840 (Product Specification)
NRF_PS = "nRF52840_PS"
_NRF_CHAPTER = re.compile(r"^\d+(?:\.\d+)?\s+([A-Za-z0-9_]+)\s+[—–-]\s+")
_NRF_REG = re.compile(r"^(\d+(?:\.\d+){3,5})\s+([A-Z][A-Z0-9_]*(?:\[[0-9n]+\])?(?:\.[A-Z][A-Z0-9_]*(?:\[[0-9n]+\])?)*)"
                      r"(?:\s+\([Dd]eprecated[^)]*\))?$")


def nrf_blocks(doc_id: str = NRF_PS) -> list[Block]:
    """Mỗi thanh ghi/cluster có một mục outline '6.31.7.16 INTENCLR'; 'Address offset' đọc ở text trang."""
    pages = pdfdocs.load_pages(doc_id)
    out: list[Block] = []
    for e in pdfdocs.load_outline(doc_id):
        m = _NRF_REG.match(e.title)
        if not m or e.page is None:
            continue
        chapter = next((a for a in e.path if _NRF_CHAPTER.match(a)), None)
        if chapter is None:
            continue
        anchor = _anchor_offset(pages.get(e.page, ""), m.group(1))
        offsets = parse_offsets(anchor[1]) if anchor and anchor[0] == "offset" else None
        rm = re.search(rf"(?m)^\s*{re.escape(m.group(1))}\s.*?^\s*Reset (0x[0-9A-Fa-f]{{8}})\b",
                       pages.get(e.page, ""), re.S | re.M)
        out.append(Block(doc=doc_id, page=e.page, title=e.title, names=[m.group(2)], var_sets={}, offsets=offsets,
                         chapter=chapter, path=e.path + (e.title,), reset=int(rm.group(1), 16) if rm else None))
    return out


def _nrf_acronyms(p: Peripheral) -> list[str]:
    """Tên chương PS có thể ứng với peripheral, theo ưu tiên: group, tên, rồi alias (alternatePeripheral)."""
    out: list[str] = []
    for x in (p.group, p.name, p.alternate_peripheral):
        for v in ((x or "").upper(), re.sub(r"\d+$", "", x or "").upper()):
            if v and v not in out:
                out.append(v)
    return out


def locate_nrf(p: Peripheral, r: Register, blocks: list[Block]) -> PageRef | None:
    for acr in _nrf_acronyms(p):
        chap = [b for b in blocks if (_NRF_CHAPTER.match(b.chapter) or [None, ""])[1].upper() == acr]
        exact = [b for b in chap if r.name in b.names]
        if exact:
            b = exact[0]
            has = b.offsets is not None
            conf = "high" if has and r.offset in b.offsets else ("name" if not has else "offset_mismatch")
            return PageRef(b.doc, b.page, conf, rm_name=b.names[0],
                           rm_offsets=sorted(b.offsets) if b.offsets else None, rm_reset=b.reset)
        if r.cluster_path:                      # thanh ghi con của cluster (RXD.PTR) mô tả chung ở mục cluster
            for cp in (r.cluster_path, re.sub(r"\[\d+\]", "[n]", r.cluster_path)):
                cl = [b for b in chap if cp in b.names]
                if cl:
                    b = cl[0]
                    return PageRef(b.doc, b.page, "cluster", rm_name=b.names[0],
                                   note=f"described with its cluster {r.cluster_path}")
    return None


# --------------------------------------------------------------------------- ESP32 (Technical Reference Manual)
ESP_TRM = "ESP32_TRM"
_ESP_ACC = re.compile(r"\b(?:R/W[A-Z0-9/]*|R/O|RO[A-Z/]*|WO[A-Z]*|R/WC[A-Z/]*|R/SS[A-Z/]*|R/W1[A-Z]?|SO|R)\s*$")
_ESP_ADDR = re.compile(r"(?<![0-9A-Za-z])(?:0[xX])?((?:3FF|600)[0-9A-Fa-f]{5})(?![0-9A-Za-z])")
_ESP_SUMMARY_NAME = re.compile(r"^\s*([A-Z][A-Z0-9_]*_REG)\b(.*)$")
_ESP_DESC = re.compile(r"^\s*Register\s*\d+\s*\.\s*\d+\s*\.\s*(.+?_REG)\b")


def dport_window(addr: int) -> int:
    """TRM tr.73: (0x3FF40000 + n) và (0x60000000 + n) truy cập cùng nội dung, n = 0..0x3FFFF."""
    return addr - 0x60000000 + 0x3FF40000 if 0x60000000 <= addr < 0x60040000 else addr


def ahb_alias(addr: int) -> int | None:
    """Địa chỉ ở cửa sổ còn lại (DPORT <-> AHB); None nếu không thuộc hai cửa sổ."""
    if 0x3FF40000 <= addr < 0x3FF80000:
        return addr - 0x3FF40000 + 0x60000000
    if 0x60000000 <= addr < 0x60040000:
        return addr - 0x60000000 + 0x3FF40000
    return None


@dataclass
class EspIndex:
    summary: dict[int, list[tuple[str, int]]]            # địa chỉ (cửa sổ DPORT) -> [(tên TRM, trang bảng tóm tắt)]
    desc: dict[str, int]                                 # TÊN_TRM -> trang mô tả ("Register N.M. NAME (0x..)")
    desc_patterns: list[tuple[re.Pattern, str, int, frozenset | None]]   # tên có biến n/m/x/y -> (regex, tên, trang, chỉ số hợp lệ)
    summary_names: dict[str, int]                        # TÊN_TRM -> trang bảng tóm tắt đầu tiên

    def desc_page(self, name: str) -> int | None:
        u = name.upper()
        if u in self.desc:
            return self.desc[u]
        for rx, _n, pg, allowed in self.desc_patterns:
            m = rx.fullmatch(name)
            if m and (allowed is None or int(m.group(1)) in allowed):   # TRM: '(n: 0-19, 21-23, ...)' — chỉ số ngoài khoảng không tồn tại
                return pg
        return None


def _nz(s: str) -> str:
    return re.sub(r"\s+", "", s)


def parse_index_ranges(spec: str) -> set[int]:
    """'0-19, 21-23, 25-27 , 32-39' / '8, 9' / '0-19, 20 1' (số 1 là chú thích) -> tập chỉ số."""
    out: set[int] = set()
    for part in spec.split(","):
        m = re.match(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?", part)
        if m:
            out |= set(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    return out


_ESP_RANGE = re.compile(r"\(\s*([nmxy])\s*[:=]\s*([0-9][^)]*)\)")


def _pattern_regex(name: str) -> tuple[re.Pattern, str | None]:
    """Tên có biến thường (GPIO_PINn_REG) -> regex; nếu có đúng MỘT chữ biến thì nó là nhóm bắt chỉ số (để kiểm khoảng hợp lệ)."""
    var_letters = [ch for ch in name if ch in "nmxy"]
    single = len(var_letters) == 1
    return re.compile("".join((r"(\d+)" if single else r"\d+") if ch in "nmxy" else re.escape(ch) for ch in name)), \
        (var_letters[0] if single else None)


def esp32_index(doc_id: str = ESP_TRM) -> EspIndex:
    pages = pdfdocs.load_pages(doc_id)
    summary: dict[int, list[tuple[str, int]]] = {}
    names: dict[str, int] = {}
    desc: dict[str, int] = {}
    patterns: list[tuple[re.Pattern, str, int, frozenset | None]] = []
    for page, text in sorted(pages.items()):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            md = _ESP_DESC.match(line)
            if md:
                name = _nz(md.group(1))
                if re.search(r"[a-z]", name):          # biến n/m/x/y viết thường: SENS_ULP_CP_SLEEP_CYCn_REG
                    rx, var = _pattern_regex(name)
                    mr = _ESP_RANGE.search(line[md.end():])
                    allowed = frozenset(parse_index_ranges(mr.group(2))) if (mr and var and mr.group(1) == var) else None
                    patterns.append((rx, name, page, allowed))
                else:
                    desc.setdefault(name.upper(), page)
                continue
            ms = _ESP_SUMMARY_NAME.match(line)
            if not ms:
                continue
            name, rest = ms.group(1), ms.group(2)
            found = [int(a, 16) for a in _ESP_ADDR.findall(rest)]
            if not _ESP_ACC.search(rest):               # tên/mô tả ngắt dòng: gom thêm tối đa 4 dòng cho tới cột Access
                for nxt in lines[i + 1: i + 5]:
                    if _ESP_SUMMARY_NAME.match(nxt):
                        break
                    found += [int(a, 16) for a in _ESP_ADDR.findall(nxt)]
                    if _ESP_ACC.search(nxt):
                        break
            if found:
                names.setdefault(name.upper(), page)
                for a in found:
                    summary.setdefault(dport_window(a), []).append((name, page))
    return EspIndex(summary, desc, patterns, names)


def _esp_name_candidates(p: Peripheral, r: Register) -> list[str]:
    base = re.sub(r"[\[\]]", "", r.short_name.replace("].", "_").replace(".", "_"))
    pb = re.sub(r"\d+$", "", p.name)
    return [f"{p.name}_{base}_REG", f"{pb}_{base}_REG", f"{base}_REG"]


def locate_esp32(p: Peripheral, r: Register, idx: EspIndex) -> PageRef | None:
    rows = idx.summary.get(dport_window(r.address))
    if rows:
        name, spage = rows[0]
        dpage = idx.desc_page(name)
        if dpage:
            return PageRef(ESP_TRM, dpage, "high", alt_pages=[spage] if spage != dpage else [], rm_name=name)
        return PageRef(ESP_TRM, spage, "summary", rm_name=name,
                       note="listed in the TRM register summary table (no per-register description page found)")
    for cand in _esp_name_candidates(p, r):
        dpage = idx.desc_page(cand)
        if dpage:
            return PageRef(ESP_TRM, dpage, "name", rm_name=cand.upper())
        if cand.upper() in idx.summary_names:
            return PageRef(ESP_TRM, idx.summary_names[cand.upper()], "name", rm_name=cand.upper())
    return None
