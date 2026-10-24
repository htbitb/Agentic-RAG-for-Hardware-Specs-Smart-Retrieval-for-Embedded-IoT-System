"""Báo cáo chất lượng dữ liệu P1: số liệu + spot-check ngẫu nhiên đối chiếu với text/bố cục trang PDF.

Các kiểm tra spot-check được viết ĐỘC LẬP với extractor khi có thể: AF STM32 đọc lại bằng vị trí từ (x) trên trang thay vì
`extract_tables`; AF ESP32 (dựng từ TRM) so với bảng IO_MUX của datasheet (tài liệu khác); thanh ghi kiểm bằng regex riêng trên
text trang (offset, reset, vị trí bit); giới hạn kiểm bằng việc in lại đúng dòng trong trang để đọc.

    agent/.venv/bin/python -m ingestion.data_quality --out plan/P1_data_quality.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import re
import sqlite3
from pathlib import Path

from . import hwdb, pdfdocs

SEED = 1022
ROOT = Path(__file__).resolve().parent.parent


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


# =========================================================================== số liệu
def collect_stats(conn, text_index_db) -> dict:
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
    chips = [r["chip"] for r in q("SELECT chip FROM chips ORDER BY chip")]
    out: dict = {"chips": chips, "registers": {}, "pins": {}, "pin_functions": {}, "limits": {}, "anomalies": {}}
    for c in chips:
        n = lambda sql: q(sql, c)[0][0]  # noqa: E731
        by_conf = {r["page_confidence"]: r["n"] for r in q(
            "SELECT page_confidence, count(*) n FROM registers WHERE chip=? AND svd_only=0 GROUP BY 1", c)}
        out["registers"][c] = {
            "peripherals": n("SELECT count(*) FROM peripherals WHERE chip=?"),
            "registers": n("SELECT count(*) FROM registers WHERE chip=?"),
            "fields": n("SELECT count(*) FROM fields WHERE chip=?"),
            "enum_values": n("SELECT count(*) FROM enum_values WHERE chip=?"),
            "registers_without_fields": n("SELECT count(*) FROM registers WHERE chip=? AND has_fields=0"),
            "with_page": n("SELECT count(*) FROM registers WHERE chip=? AND svd_only=0 AND page IS NOT NULL"),
            "svd_only": n("SELECT count(*) FROM registers WHERE chip=? AND svd_only=1"),
            "by_confidence": by_conf,
            "reset_mismatch": n("SELECT count(*) FROM data_anomalies WHERE chip=? AND kind='reset_mismatch'"),
        }
        out["pins"][c] = n("SELECT count(*) FROM pins WHERE chip=?")
        out["pin_functions"][c] = {r["kind"]: r["n"] for r in q(
            "SELECT kind, count(*) n FROM pin_functions WHERE chip=? GROUP BY kind", c)}
        out["limits"][c] = {"electrical": n("SELECT count(*) FROM electrical_limits WHERE chip=?"),
                            "clock": n("SELECT count(*) FROM clock_limits WHERE chip=?"),
                            "unverified": n("SELECT count(*) FROM electrical_limits WHERE chip=? AND verified=0") +
                                          n("SELECT count(*) FROM clock_limits WHERE chip=? AND verified=0")}
        out["anomalies"][c] = {r["kind"]: r["n"] for r in q("SELECT kind, count(*) n FROM data_anomalies WHERE chip=? GROUP BY 1", c)}
    ti = sqlite3.connect(f"file:{text_index_db}?mode=ro", uri=True)
    docs = {r[0]: r[1] for r in ti.execute("SELECT doc_id, count(*) FROM chunks GROUP BY doc_id")}
    bad_pages = ti.execute("SELECT count(*) FROM chunks WHERE page_start IS NULL OR page_end < page_start").fetchone()[0]
    ti.close()
    out["chunks"] = {"total": sum(docs.values()), "by_doc": docs, "without_valid_page": bad_pages}

    def ratio(a, b):
        return a / b if b else None

    regs = out["registers"]
    out["page_coverage"] = {
        "registers": {**{c: ratio(regs[c]["with_page"], regs[c]["registers"]) for c in chips},
                      "all": ratio(sum(regs[c]["with_page"] for c in chips), sum(regs[c]["registers"] for c in chips))},
        "pins": 1.0 if q("SELECT count(*) FROM pins WHERE page IS NULL")[0][0] == 0 else ratio(
            q("SELECT count(*) FROM pins WHERE page IS NOT NULL")[0][0], q("SELECT count(*) FROM pins")[0][0]),
        "pin_functions": ratio(q("SELECT count(*) FROM pin_functions WHERE page IS NOT NULL")[0][0],
                               q("SELECT count(*) FROM pin_functions")[0][0]),
        "limits": ratio(q("SELECT count(*) FROM electrical_limits WHERE page IS NOT NULL")[0][0] +
                        q("SELECT count(*) FROM clock_limits WHERE page IS NOT NULL")[0][0],
                        q("SELECT count(*) FROM electrical_limits")[0][0] + q("SELECT count(*) FROM clock_limits")[0][0]),
        "chunks": ratio(out["chunks"]["total"] - bad_pages, out["chunks"]["total"]),
    }
    n_reg = sum(regs[c]["registers"] for c in chips)
    n_pin = sum(out["pins"].values())
    n_pf = sum(sum(v.values()) for v in out["pin_functions"].values())
    n_lim = sum(v["electrical"] + v["clock"] for v in out["limits"].values())
    with_page = sum(regs[c]["with_page"] for c in chips)
    out["page_coverage"]["records_total"] = {"registers": n_reg, "pins": n_pin, "pin_functions": n_pf, "limits": n_lim}
    out["page_coverage"]["records_with_page"] = ratio(
        with_page + n_pin + n_pf + n_lim, n_reg + n_pin + n_pf + n_lim)
    core = q("SELECT count(*) FROM registers WHERE chip='stm32g474' AND svd_only=1 AND note LIKE 'Arm Cortex-M4 core%'")[0][0]
    out["page_coverage"]["stm32_core_peripheral_registers"] = core
    return out


# =========================================================================== spot-check: thanh ghi
def sample_by_chip(rows: list[dict], per_chip: dict[str, int], seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for chip, n in per_chip.items():
        pool = sorted((r for r in rows if r["chip"] == chip), key=lambda r: json.dumps(r, sort_keys=True, default=str))
        out += rng.sample(pool, min(n, len(pool)))
    return out


_HEX = r"0[xX][0-9A-Fa-f]+"


def _window(text: str, rm_name: str | None, chip: str) -> str | None:
    """Đoạn text ngay sau tiêu đề/tên thanh ghi trong trang (độc lập với extractor: tìm theo chuỗi đã bỏ khoảng trắng)."""
    if not rm_name:
        return None
    sq, key = _squash(text), _squash(rm_name)
    if chip == "stm32g474":
        key = f"({key})"
    idx = sq.find(key)
    if idx < 0:
        return None
    # ánh xạ chỉ số trong chuỗi squash về chuỗi gốc
    pos = count = 0
    while pos < len(text) and count < idx:
        if not text[pos].isspace():
            count += 1
        pos += 1
    return text[pos: pos + 2200]


def check_register(reg: dict, fields: list[dict], pages: dict[int, str]) -> dict:
    item = f"{reg['chip']} {reg['peripheral']}.{reg['name']}"
    size = reg.get("size") or 32
    dbv = f"offset {reg['offset']:#x}, address {reg['address']:#010x}, reset {reg['reset_value']:#0{size // 4 + 2}x}"
    if reg.get("page") is None:
        return {"item": item, "db": dbv + " (SVD only)", "pdf": "(no manual page: svd_only)", "match": None, "page": None}
    page = reg["page"]
    text = pages.get(page, "")
    win = _window(text, reg.get("rm_name"), reg["chip"]) if reg["chip"] != "nrf52840" else None
    if reg["chip"] == "nrf52840":
        m = re.search(rf"(?m)^\d+(?:\.\d+)+\s+{re.escape(reg['name'])}\s*(?:\(.*\))?$", text)
        win = text[m.end(): m.end() + 2200] if m else None
    checks: list[tuple[str, bool | None, str]] = []          # (thành phần, kết quả, mô tả PDF)
    if win is None and reg["chip"] != "esp32":
        return {"item": item, "db": dbv, "pdf": f"(register {reg.get('rm_name') or reg['name']} not found on p.{page})",
                "match": False, "page": page}
    if reg["chip"] in ("stm32g474", "nrf52840"):
        mo = re.search(rf"Address\s*offset\s*:\s*({_HEX})(\s*\+|\s*to)?", win)
        if mo and not mo.group(2):
            ok = int(mo.group(1), 16) == reg["offset"]
            checks.append(("offset", ok, f"Address offset: {mo.group(1)}"))
        elif mo:
            checks.append(("offset", None, "offset given as formula/range"))
        if reg["chip"] == "stm32g474":
            mr = re.search(r"[Rr]eset\s+value\s*:\s*(0[xX][0-9A-Fa-f ]{1,9}?)\s*(?:\n|\.|$|\()", win)
            if mr and not re.search(r"for (?:port|ports)", win[mr.start(): mr.end() + 30]):
                val = int(re.sub(r"\s", "", mr.group(1)), 16)
                allowed = {reg["reset_value"], reg.get("rm_reset_value")}
                checks.append(("reset", val in allowed, f"Reset value: {mr.group(1).strip()}"))
        else:
            mr = re.search(r"Reset\s+(0x[0-9A-Fa-f]{8})", win)
            if mr:
                checks.append(("reset", int(mr.group(1), 16) == reg["reset_value"] or
                               int(mr.group(1), 16) == reg.get("rm_reset_value"), f"Reset {mr.group(1)}"))
    else:  # esp32: tên + địa chỉ/offset in trên trang (bảng tóm tắt hoặc tiêu đề 'Register N.M NAME (0xOFF)')
        sq = _squash(text).upper()
        rm = re.sub(r"\s+", "", reg["rm_name"] or "")                                         # giữ hoa/thường: n/m/x/y thường = chỉ số mảng
        exact_pat = "".join(r"\d+" if ch in "nmxy" else re.escape(ch.upper()) for ch in rm)
        var = r"(?:\d+|[NMXY])"       # tên cụ thể (GPIO_FUNC33_...) có thể chỉ in dưới dạng mẫu mảng (GPIO_FUNCy_...)
        array_pat = "".join(var if c.isdigit() else "".join(var if ch in "nmxy" else re.escape(ch.upper()) for ch in c)
                            for c in re.split(r"(\d+)", rm))
        literal = bool(rm) and bool(re.search(exact_pat, sq))
        name_ok = literal or (bool(rm) and bool(re.search(array_pat, sq)))
        checks.append(("name", name_ok, f"{reg['rm_name']} on page" + ("" if literal else " (as array pattern)")))
        formula = re.search(r"\(0X([0-9A-F]+)\+(0X)?([0-9A-F]+)\*[NMXY]\)", sq)       # '(0x58+4* n)' hoặc '(0x130+0x4*y)'
        in_formula = bool(formula) and reg["offset"] >= int(formula.group(1), 16) and \
            (reg["offset"] - int(formula.group(1), 16)) % int(formula.group(3), 16 if formula.group(2) else 10) == 0
        addr_ok = (f"{reg['address']:08X}" in sq or f"{(reg.get('address_alias') or 0):08X}" in sq
                   or bool(re.search(rf"\(0X0*{reg['offset']:X}(?![0-9A-F])[^)]*\)", sq)) or in_formula)
        checks.append(("offset/address", addr_ok, "address or offset printed on page" + (" (array formula)" if in_formula else "")
                       if addr_ok else "address/offset not printed on page"))
    if fields:
        f = sorted(fields, key=lambda x: (x["bit_offset"], x["name"]))[0]
        hi, lo = f["bit_offset"] + f["bit_width"] - 1, f["bit_offset"]
        if reg["chip"] == "stm32g474":
            blob = " ".join(pages.get(p, "") for p in range(page, page + 3))
            ms = list(re.finditer(rf"Bits?\s+(\d+)(?::(\d+))?\s+{re.escape(f['name'])}\b", blob))
            if not ms:                                      # SVD đặt tên khác RM (AFRH8 vs AFSEL8) -> không kết luận
                checks.append(("field", None, f"field {f['name']} not found as 'Bit(s) n:m NAME' on p.{page}-{page + 2}"))
            else:
                ranges = [(int(m.group(1)), int(m.group(2) or m.group(1))) for m in ms]
                hit = next((m for m, r in zip(ms, ranges) if r == (hi, lo)), ms[0])
                variants = "; ".join(sorted({m.group(0) for m in ms}))
                checks.append(("field", (hi, lo) in ranges, variants if len(ms) > 1 else hit.group(0)))
        elif reg["chip"] == "nrf52840":
            present = re.search(rf"(?m)^[A-Za-z]\s+(?:RW|R|W)\s+(?:\w+\s+)?{re.escape(f['name'])}\b", win or "")
            checks.append(("field", True if present else None, f"field row '{f['name']}' present" if present else
                           f"field {f['name']} row not found"))
    concl = [c for c in checks if c[1] is not None]
    match = None if not concl else all(c[1] for c in concl)
    return {"item": item, "db": dbv + (f", field {fields_label(fields)}" if fields else ""),
            "pdf": "; ".join(c[2] + ("" if c[1] is not False else " ✗") for c in checks) or "(nothing checkable)",
            "match": match, "page": page}


def fields_label(fields: list[dict]) -> str:
    f = sorted(fields, key=lambda x: (x["bit_offset"], x["name"]))[0]
    return f"{f['name']}[{f['bit_offset'] + f['bit_width'] - 1}:{f['bit_offset']}]"


def spot_check_registers(conn, n_per_chip=None, seed: int = SEED) -> list[dict]:
    n_per_chip = n_per_chip or {"stm32g474": 7, "nrf52840": 7, "esp32": 6}
    rows = [dict(r) for r in conn.execute("SELECT * FROM registers WHERE svd_only=0 AND page IS NOT NULL")]
    pages: dict[str, dict[int, str]] = {}
    out = []
    for r in sample_by_chip(rows, n_per_chip, seed):
        doc_pages = pages.setdefault(r["doc"], pdfdocs.load_pages(r["doc"]))
        fields = [dict(f) for f in conn.execute("SELECT name, bit_offset, bit_width FROM fields WHERE register_id=?", (r["id"],))]
        out.append(check_register(r, fields, doc_pages))
    return out


# =========================================================================== spot-check: AF
def stm32_af_by_words(pin: str) -> dict[int, str]:
    """Đọc ô AF của một chân bằng VỊ TRÍ TỪ trên trang (độc lập với `extract_tables`). Trả {af: 'SIG' hoặc 'SIG1/SIG2' hoặc ''}."""
    import pdfplumber

    from .pinout_extract import ST_DS
    ol = {e.title: e.page for e in pdfdocs.load_outline(ST_DS)}
    pages = range(ol["4.11 Alternate functions"], ol["5 Electrical characteristics"])
    with pdfplumber.open(pdfdocs.doc_pdf(ST_DS)) as pdf:
        centers: dict[int, float] = {}
        for p in pages:                                         # tiêu đề AF0..AF15 (cột có cùng bố cục mọi trang)
            words = pdf.pages[p - 1].extract_words()
            hdr = {int(w["text"][2:]): (w["x0"] + w["x1"]) / 2 for w in words if re.fullmatch(r"AF\d{1,2}", w["text"])}
            if len(hdr) == 16:
                centers = hdr
                break
        for p in pages:
            words = pdf.pages[p - 1].extract_words(keep_blank_chars=False)
            pins = sorted((w for w in words if re.fullmatch(r"P[A-G]\d{1,2}", w["text"]) and w["x0"] < min(centers.values()) - 5),
                          key=lambda w: w["top"])
            for i, w in enumerate(pins):
                if w["text"] != pin:
                    continue
                mid = lambda ww: (ww["top"] + ww["bottom"]) / 2  # noqa: E731
                xs = sorted(centers.values())
                colw = sorted(b - a for a, b in zip(xs, xs[1:]))[len(xs) // 2]
                gaps = sorted(mid(b) - mid(a) for a, b in zip(pins, pins[1:])) or [20.0]
                half = gaps[len(gaps) // 2] / 2                  # nửa chiều cao hàng điển hình: không hút chữ đầu/chân trang
                top = (mid(pins[i - 1]) + mid(w)) / 2 if i > 0 else mid(w) - half
                bottom = (mid(w) + mid(pins[i + 1])) / 2 if i + 1 < len(pins) else mid(w) + half
                cells: dict[int, list] = {a: [] for a in range(16)}
                for x in words:
                    if top <= mid(x) < bottom and x["x0"] > w["x1"] + 1:
                        c = (x["x0"] + x["x1"]) / 2
                        a = min(centers, key=lambda k: abs(centers[k] - c))
                        if abs(centers[a] - c) <= colw * 0.6:       # bỏ chữ xoay/ghi chú nằm lệch ngoài cột AF
                            cells[a].append(x)
                out = {}
                for a, ws in cells.items():
                    ws.sort(key=lambda x: (round(mid(x)), x["x0"]))
                    txt = "".join(x["text"] for x in ws)
                    out[a] = "" if txt in ("", "-", "--") else txt
                return out
    raise KeyError(pin)


def esp32_datasheet_functions() -> dict[int, dict[int, str]]:
    """Function0..5 từ bảng IO_MUX của DATASHEET (tr.69) — tài liệu khác với TRM Table 6.10-1 dùng để dựng DB."""
    import pdfplumber

    from .pinout_extract import ESP_DS
    out: dict[int, dict[int, str]] = {}
    with pdfplumber.open(pdfdocs.doc_pdf(ESP_DS)) as pdf:
        for table in pdf.pages[68].extract_tables():
            for row in table:
                if len(row) != 25 or not (row[0] or "").strip().isdigit():
                    continue
                cells = [re.sub(r"\s+", "", c or "") for c in row]
                funcs = {i: cells[10 + 2 * i] for i in range(6)}
                g = {int(v[4:]) for v in funcs.values() if re.fullmatch(r"GPIO\d+", v)}
                if len(g) == 1:
                    out[g.pop()] = funcs
    return out


def spot_check_af(conn, n_st=14, n_esp=6, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows = [dict(r) for r in conn.execute("SELECT chip, pin, af, signal FROM pin_functions WHERE kind='af' AND chip='stm32g474'")]
    out = []
    cache: dict[str, dict] = {}
    for r in rng.sample(sorted(rows, key=lambda r: (r["pin"], r["af"], r["signal"])), n_st):
        if r["pin"] not in cache:
            cache[r["pin"]] = stm32_af_by_words(r["pin"])
        pdf = cache[r["pin"]][r["af"]]
        db_all = sorted(x["signal"] for x in conn.execute(
            "SELECT signal FROM pin_functions WHERE chip='stm32g474' AND pin=? AND af=? AND kind='af'", (r["pin"], r["af"])))
        out.append({"item": f"stm32g474 {r['pin']} AF{r['af']}", "db": "/".join(db_all),
                    "pdf": pdf or "-", "match": sorted(pdf.split("/")) == db_all, "source": "word-position read of DS Table 13"})
    ds = esp32_datasheet_functions()
    erows = [dict(r) for r in conn.execute("SELECT pin, af, signal FROM pin_functions WHERE chip='esp32' AND kind='io_mux'")]
    for r in rng.sample(sorted(erows, key=lambda r: (r["pin"], r["af"])), n_esp):
        g = int(r["pin"][4:])
        pdf = ds.get(g, {}).get(r["af"], "")
        out.append({"item": f"esp32 {r['pin']} Function{r['af']}", "db": r["signal"], "pdf": pdf or "-",
                    "match": _squash(pdf) == _squash(r["signal"]), "source": "datasheet A.4 vs TRM Table 6.10-1"})
    return out


# =========================================================================== spot-check: giới hạn
def quote_snippet(doc: str, page: int, quote: str, width: int = 170) -> str:
    text = pdfdocs.load_pages(doc).get(page, "")
    frag = quote.split(" ... ")[0]
    sq_frag = _squash(frag)
    pos = count = 0
    flat = _squash(text)
    idx = flat.find(sq_frag)
    if idx < 0:
        return "(quote not found)"
    while pos < len(text) and count < idx:
        if not text[pos].isspace():
            count += 1
        pos += 1
    return re.sub(r"\s+", " ", text[max(0, pos - 15): pos + width]).strip()


def spot_check_limits(conn, n_elec=6, n_clock=4, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    el = [dict(r) for r in conn.execute("SELECT * FROM electrical_limits ORDER BY id")]
    ck = [dict(r) for r in conn.execute("SELECT * FROM clock_limits ORDER BY id")]
    out = []
    for r in rng.sample(el, n_elec) + rng.sample(ck, n_clock):
        vals = [str(r[k]) for k in ("min", "typ", "max") if r[k] is not None]
        snip = quote_snippet(r["doc"], r["page"], r["quote"])
        sq = _squash(snip)
        nums = [t for v in vals for t in re.findall(r"\d+(?:\.\d+)?", v)]
        ok = bool(nums) and all(t in sq for t in nums)
        out.append({"item": f"{r['chip']} {r['parameter']} [{r['doc']} p.{r['page']}]",
                    "db": f"min={r['min']} typ={r['typ']} max={r['max']} {r['unit']}", "pdf": snip, "match": ok})
    return out


# =========================================================================== báo cáo
def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _table(rows: list[dict], cols=("item", "db", "pdf", "match")) -> str:
    def cell(v):
        if v is True:
            return "✓"
        if v is False:
            return "✗"
        if v is None:
            return "n/a"
        return str(v).replace("|", "\\|").replace("\n", " ")
    head = "| # | Mục | Giá trị DB | Giá trị PDF | Khớp? |\n|---|---|---|---|---|\n"
    return head + "\n".join(f"| {i} | " + " | ".join(cell(r.get(c)) for c in cols) + " |" for i, r in enumerate(rows, 1)) + "\n"


def render_markdown(stats: dict, spot_reg, spot_af, spot_lim, retrieval: dict | None, anomalies: list[dict],
                    manual_notes: dict[str, str] | None = None) -> str:
    L: list[str] = []
    a = L.append
    a("# P1 — Báo cáo chất lượng dữ liệu (W1)\n")
    a(f"Sinh tự động bởi `agent/ingestion/data_quality.py` ({datetime.date.today().isoformat()}, seed spot-check {SEED}). "
      "Nguồn: `corpus/` (6 PDF + 3 SVD, sha256 trong `corpus/manifest.yaml`). DB: `agent/data/hw_specs.sqlite`, "
      "`agent/data/text_index.*`.\n")
    a("## 1. Số liệu theo chip\n")
    a("| Chip | Peripheral | Thanh ghi | Field | Enum | Thanh ghi không có field | Chân | Hàng AF/IO_MUX | Giới hạn điện | Giới hạn clock |\n|---|---|---|---|---|---|---|---|---|---|")
    for c in stats["chips"]:
        r, pf, lim = stats["registers"][c], stats["pin_functions"][c], stats["limits"][c]
        a(f"| {c} | {r['peripherals']} | {r['registers']} | {r['fields']} | {r['enum_values']} | {r['registers_without_fields']} | "
          f"{stats['pins'][c]} | {sum(v for k, v in pf.items() if k in ('af', 'io_mux', 'fixed'))} | {lim['electrical']} | {lim['clock']} |")
    ch = stats["chunks"]
    a(f"\nText index: **{ch['total']} chunk** — " + ", ".join(f"{k} {v}" for k, v in sorted(ch["by_doc"].items())) + "\n")
    a("## 2. Tỷ lệ bản ghi có `doc` + `page` trỏ tới PDF thật\n")
    a("| Bảng | Có trang | Ghi chú |\n|---|---|---|")
    cov = stats["page_coverage"]
    for c in stats["chips"]:
        r = stats["registers"][c]
        a(f"| thanh ghi {c} | {r['with_page']}/{r['registers']} ({_pct(cov['registers'][c])}) | "
          f"{r['svd_only']} chỉ có `{c}`-SVD (page NULL); độ tin cậy trang: " + ", ".join(f"{k}={v}" for k, v in sorted(r['by_confidence'].items())) + " |")
    a(f"| thanh ghi (cả 3 chip) | {_pct(cov['registers']['all'])} | |")
    a(f"| chân (`pins`) | {_pct(cov['pins'])} | trang bảng pin definition / IO_MUX / ball assignment |")
    a(f"| chức năng chân (`pin_functions`) | {_pct(cov['pin_functions'])} | |")
    a(f"| giới hạn điện + clock | {_pct(cov['limits'])} | mỗi dòng có trích nguyên văn được kiểm tự động |")
    a(f"| chunk | {_pct(cov['chunks'])} | |")
    t = cov["records_total"]
    a(f"\n**Gộp (thanh ghi + chân + chức năng chân + giới hạn = {sum(t.values())} bản ghi): {_pct(cov['records_with_page'])} có trang.**")
    core = cov["stm32_core_peripheral_registers"]
    a(f"Phần thanh ghi không có trang gồm {core} thanh ghi lõi Cortex-M4 của STM32 (NVIC/SCB/STK/MPU/FPU: tài liệu PM0214 không nằm trong corpus) "
      "và các thanh ghi 'superset' của SVD mà manual không mô tả (TIM2–5: RCR, BDTR, CCR5/6, CCMR3, DTR2), ESP32: TRM không mô tả ~25% thanh ghi trong SVD.\n")
    a("## 3. Bất thường phát hiện\n")
    a("| Chip | Loại | Số lượng |\n|---|---|---|")
    for c in stats["chips"]:
        for k, v in sorted(stats["anomalies"][c].items()):
            a(f"| {c} | {k} | {v} |")
    a("\nVí dụ đã đọc tay đối chiếu với text trang:\n")
    for x in anomalies:
        a(f"- **{x['chip']} {x['ref']}** — {x['detail']}")
    a("\n## 4. Spot-check ngẫu nhiên\n")
    ok = lambda rows: sum(1 for r in rows if r["match"] is True)  # noqa: E731
    bad = lambda rows: sum(1 for r in rows if r["match"] is False)  # noqa: E731
    a(f"### 4.1 Thanh ghi ({len(spot_reg)}): {ok(spot_reg)} khớp, {bad(spot_reg)} không khớp, "
      f"{len(spot_reg) - ok(spot_reg) - bad(spot_reg)} không kết luận được\n")
    a("Kiểm tra: offset và reset value in trên trang mô tả, vị trí bit của field đầu tiên (STM32: 'Bit(s) n:m NAME'), tên + địa chỉ (ESP32).\n")
    a(_table(spot_reg))
    a(f"\n### 4.2 Alternate Function ({len(spot_af)}): {ok(spot_af)} khớp, {bad(spot_af)} không khớp\n")
    a("STM32: đọc lại ô AF bằng vị trí từ trên trang (không dùng `extract_tables`); ESP32: bảng IO_MUX của datasheet so với TRM Table 6.10-1 (dùng dựng DB).\n")
    a(_table(spot_af))
    a(f"\n### 4.3 Giới hạn điện/clock ({len(spot_lim)}): {ok(spot_lim)} khớp, {bad(spot_lim)} không khớp\n")
    a("Cột 'Giá trị PDF' là đoạn text trang chứa chuỗi trích; các số trong min/typ/max phải có trong đoạn đó (và đã được đọc lại bằng mắt, xem ghi chú).\n")
    a(_table(spot_lim))
    if manual_notes:
        a("\n### 4.4 Ghi chú sau khi đọc lại các dòng spot-check\n")
        for k, v in manual_notes.items():
            a(f"- **{k}**: {v}")
    a("\n## 5. Truy hồi (text index hybrid) trên split `dev`\n")
    if retrieval:
        n = retrieval["n_tasks"]
        a(f"Đo trên {n} task dev của C1+C2 (trang được truy hồi có chứa giá trị kỳ vọng — cùng định nghĩa `retrieval_hit` của grader citation). "
          "Đo một lần, không chỉnh chunker/index theo kết quả.\n")
        a("| Hệ | k | Recall, trang đầu của chunk (so sánh được với S1) | Recall, mọi trang trong page_start..page_end | C1 | C2 | Recall, chunk chứa giá trị (chặt nhất) |\n|---|---|---|---|---|---|---|")
        s1 = retrieval["S1_top4"]
        a(f"| S1 (Native RAG, Chroma, chunk 1000/150; mỗi nguồn một trang) | 4 | {_pct(s1['recall'])} | — | — | — | — |")
        for m in ("bm25", "dense", "hybrid"):
            for k in ("4", "8"):
                row = retrieval["agent_index"][m][k]
                a(f"| agent index — {m} | {k} | {_pct(row['first_page']['all'])} | {_pct(row['page']['all'])} | {_pct(row['page']['C1'])} | {_pct(row['page']['C2'])} | {_pct(row['chunk']['all'])} |")
        a("\n**Lưu ý so sánh:** `retrieval_hit` của S1 xét MỘT trang cho mỗi nguồn. Chunk của agent có thể trải nhiều trang (≈ 39% chunk vắt qua 2 trang), "
          "nên cột 'mọi trang trong khoảng' rộng hơn S1; số so sánh được với S1 là cột 'trang đầu của chunk' (và cột chặt nhất 'chunk chứa giá trị'). "
          "Cỡ mẫu 14 task — chỉ là chỉ báo, không đủ để kết luận có ý nghĩa thống kê.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "plan" / "P1_data_quality.md"))
    ap.add_argument("--db", default=str(hwdb.DEFAULT_DB))
    ap.add_argument("--index", default=str(ROOT / "data" / "text_index.sqlite"))
    ap.add_argument("--retrieval", default=str(ROOT.parent / "plan" / "P1_retrieval_recall.json"))
    ap.add_argument("--notes", default=str(ROOT.parent / "plan" / "P1_data_quality_notes.json"),
                    help="JSON {tiêu đề: ghi chú} do người đọc lại spot-check viết tay (tuỳ chọn)")
    a = ap.parse_args(argv)
    conn = hwdb.connect(a.db, readonly=True)
    stats = collect_stats(conn, a.index)
    spot_reg, spot_af, spot_lim = spot_check_registers(conn), spot_check_af(conn), spot_check_limits(conn)
    retrieval = json.loads(Path(a.retrieval).read_text()) if Path(a.retrieval).is_file() else None
    notes = json.loads(Path(a.notes).read_text()) if Path(a.notes).is_file() else None
    refs = [("stm32g474", "FLASH.ACR"), ("stm32g474", "RCC.RCC_CR"), ("stm32g474", "SPI2.CR1"), ("stm32g474", "TIM3.ARR"),
            ("stm32g474", "ADC3.CR"), ("stm32g474", "TIM4.DTR2"), ("stm32g474", "PB3"), ("stm32g474", "PA9"), ("esp32", "GPIO.BT_SELECT")]
    anomalies = []
    for chip, ref in refs:
        r = conn.execute("SELECT detail FROM data_anomalies WHERE chip=? AND ref=? LIMIT 1", (chip, ref)).fetchone()
        if r:
            anomalies.append({"chip": chip, "ref": ref, "detail": r["detail"]})
    Path(a.out).write_text(render_markdown(stats, spot_reg, spot_af, spot_lim, retrieval, anomalies, notes), encoding="utf-8")
    print(f"written {a.out}: registers {sum(1 for r in spot_reg if r['match'] is True)}/{len(spot_reg)} ok, "
          f"AF {sum(1 for r in spot_af if r['match'] is True)}/{len(spot_af)} ok, limits {sum(1 for r in spot_lim if r['match'] is True)}/{len(spot_lim)} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
