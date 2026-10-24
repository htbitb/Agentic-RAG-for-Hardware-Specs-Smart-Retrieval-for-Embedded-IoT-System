"""Chân / Alternate Function / cấu trúc I/O từ datasheet -> bảng `pins`, `pin_functions` của hw_specs.sqlite.

STM32G474 (DS12288 Rev 6): Table 13 "Alternate function" (tr.73–79) và Table 12 "Pin definition" (tr.56–72) trích bằng
pdfplumber (bảng có đường kẻ nên cột không lệch); kiểm tra chéo bằng script (xem `stm32_checks`): mỗi chân đủ 16 khe AF,
tín hiệu có tiền tố là peripheral tồn tại trong SVD, mọi chân GPIO của gói lớn nhất có hàng AF, tín hiệu ở cột
"Alternate functions" của bảng pin definition đều có trong hàng AF của chân đó.
ESP32 / nRF52840: xem phần cuối file (phần tự động và phần tuyển chọn có trích dẫn trang được tách bạch ở `source`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import pdfdocs

ST_DS = "STM32G474_Datasheet"
_GPIO = re.compile(r"^(P[A-G])(\d{1,2})$")
_PIN_NAME = re.compile(r"^(P[A-G]\d{1,2})(?:-(.+))?$")


# --------------------------------------------------------------------------- common
def normalize_cell(raw: str | None) -> list[str]:
    """Ô bảng AF -> danh sách tín hiệu. Nối dòng gập ('USART2_\\nCTS'), '-' = không có, '/' = nhiều tín hiệu cùng khe."""
    if not raw:
        return []
    s = raw.replace("\n", "").strip()
    if s in ("", "-", "--", "—"):
        return []
    return [p.strip() for p in s.split("/") if p.strip() and p.strip() != "-"]


def _section_pages(doc_id: str, start_title: str, end_title: str) -> range:
    ol = {e.title: e.page for e in pdfdocs.load_outline(doc_id)}
    return range(ol[start_title], ol[end_title])


# --------------------------------------------------------------------------- STM32G474
@dataclass
class AfRow:
    pin: str
    page: int
    slots: dict[int, list[str]]


@dataclass
class PinDef:
    name: str                       # PA8
    pad_name: str                   # PC14-OSC32_IN
    pin_type: str                   # I/O | S | I
    io_structure: str               # FT_a, FT_f, TT_a, B, NRST, -
    is_5v_tolerant: bool
    packages: dict[str, str]        # gói -> số chân/bi ('-' = không có)
    notes: str
    alt_functions: list[str]
    additional_functions: list[str]
    page: int
    doc: str = ST_DS
    is_gpio: bool = field(default=False)


def _plumber_pages(doc_id: str, pages: range):
    import pdfplumber

    with pdfplumber.open(pdfdocs.doc_pdf(doc_id)) as pdf:
        for p in pages:
            yield p, pdf.pages[p - 1]


def stm32_af_rows(doc_id: str = ST_DS) -> list[AfRow]:
    pages = _section_pages(doc_id, "4.11 Alternate functions", "5 Electrical characteristics")
    rows: list[AfRow] = []
    for page_no, page in _plumber_pages(doc_id, pages):
        for table in page.extract_tables():
            for row in table:
                pin = (row[1] or "").replace("\n", "").strip() if len(row) > 1 else ""
                if not _GPIO.match(pin):
                    continue
                if len(row) != 18:
                    raise ValueError(f"{doc_id} p.{page_no} {pin}: AF row has {len(row)} columns, expected 18")
                rows.append(AfRow(pin, page_no, {af: normalize_cell(row[2 + af]) for af in range(16)}))
    return rows


_KNOWN_PACKAGES = ("WLCSP81", "UFQFPN48", "LQFP48", "LQFP64", "LQFP80", "TFBGA100", "LQFP100", "UFBGA121", "LQFP128")


def _package_name(rotated: str | None) -> str:
    """Tiêu đề cột gói xoay 90° nên text bị đảo ('18PSCLW' = WLCSP81) và PDF hoán vị glyph ('001FQPL' ~ LQFP100):
    đưa về tên chuẩn bằng so sánh tập ký tự với danh sách gói của datasheet (Table 2/§4)."""
    s = (rotated or "").replace("\n", "")[::-1]
    for known in _KNOWN_PACKAGES:
        if sorted(s) == sorted(known):
            return known
    return s


def stm32_pin_definitions(doc_id: str = ST_DS) -> dict[str, PinDef]:
    pages = _section_pages(doc_id, "4.10 Pin definition", "4.11 Alternate functions")
    out: dict[str, PinDef] = {}
    for page_no, page in _plumber_pages(doc_id, pages):
        for table in page.extract_tables():
            pkgs: list[str] | None = None
            for row in table:
                if len(row) != 15:
                    continue
                if (row[0] or "").startswith("Pin Number"):
                    continue
                if pkgs is None and re.fullmatch(r"\d+[A-Z]+", (row[0] or "").replace("\n", "")):
                    pkgs = [_package_name(c) for c in row[:9]]
                    continue
                name = (row[9] or "").replace("\n", "").strip()
                if not name or pkgs is None:
                    continue
                m = _PIN_NAME.match(name)
                key = m.group(1) if m else name
                io = (row[11] or "").replace("\n", "").strip() or "-"
                if key in out and not m:
                    key = f"{name}#{page_no}"                # VSS/VDD... lặp nhiều hàng
                out[key] = PinDef(
                    name=key, pad_name=name, pin_type=(row[10] or "").strip(), io_structure=io,
                    is_5v_tolerant=io.startswith("FT"),
                    packages={p: (c or "").replace("\n", "").strip() or "-" for p, c in zip(pkgs, row[:9])},
                    notes=(row[12] or "").replace("\n", "").strip(),
                    alt_functions=[x.strip() for x in (row[13] or "").replace("\n", "").split(",") if x.strip() and x.strip() != "-"],
                    additional_functions=[x.strip() for x in (row[14] or "").replace("\n", "").split(",") if x.strip() and x.strip() != "-"],
                    page=page_no, is_gpio=bool(m))
    return out


# --------------------------------------------------------------------------- tiện ích chung: kiểm trích dẫn
def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def verify_quote(doc_id: str, page: int, quote: str) -> bool:
    """Chuỗi trích dẫn phải có trong text của đúng trang (bỏ qua khoảng trắng/hoa-thường, không bỏ qua nội dung)."""
    return _squash(quote) in _squash(pdfdocs.load_pages(doc_id).get(page, ""))


# --------------------------------------------------------------------------- ESP32
ESP_DS = "ESP32_Datasheet"
ESP_TRM = "ESP32_TRM"
_ESP_ROW = re.compile(r"^(\d{1,2})\s+(\S+)\s+((?:\S+\s+){5}\S+)\s+([0-3])\s+(-|R(?:, I)?)\s*$")


@dataclass
class EspPad:
    gpio: int
    pad_name: str
    functions: dict[int, str | None]          # IO_MUX Function0..5 (TRM Table 6.10-1)
    reset_cfg: int                            # 0: IE=0; 1: IE=1; 2: IE=1,WPD; 3: IE=1,WPU
    input_only: bool
    rtc_capable: bool
    page: int = 133
    doc: str = ESP_TRM
    # từ datasheet Appendix A.4 (IO_MUX, tr.69)
    package_pin: int | None = None
    power_domain: str | None = None
    analog: list[str] = field(default_factory=list)
    rtc_funcs: list[str] = field(default_factory=list)
    types: dict[int, str] = field(default_factory=dict)
    drive_strength: str | None = None
    ds_page: int = 69


def _esp_trm_rows() -> dict[int, EspPad]:
    text = pdfdocs.load_pages(ESP_TRM)[133]
    out: dict[int, EspPad] = {}
    for line in text.split("\n"):
        m = _ESP_ROW.match(line.strip())
        if not m:
            continue
        toks = m.group(3).split()
        notes = m.group(5)
        out[int(m.group(1))] = EspPad(
            gpio=int(m.group(1)), pad_name=m.group(2), functions={i: (None if t == "-" else t) for i, t in enumerate(toks)},
            reset_cfg=int(m.group(4)), input_only="I" in notes.replace("R", ""), rtc_capable=notes.startswith("R"))
    return out


def _esp_datasheet_rows(pads: dict[int, EspPad]) -> None:
    """Bổ sung số chân QFN48, miền nguồn, chức năng analog/RTC, loại tín hiệu, drive strength từ bảng IO_MUX của datasheet."""
    import pdfplumber

    with pdfplumber.open(pdfdocs.doc_pdf(ESP_DS)) as pdf:
        for table in pdf.pages[69 - 1].extract_tables():
            for row in table:
                if len(row) != 25 or not (row[0] or "").strip().isdigit():
                    continue
                cells = [re.sub(r"\s+", "", c or "") for c in row]
                funcs = [cells[10 + 2 * i] for i in range(6)]
                gpios = {int(g[4:]) for g in funcs if re.fullmatch(r"GPIO\d+", g)}
                if len(gpios) != 1:
                    continue
                pad = pads.get(gpios.pop())
                if pad is None:
                    continue
                pad.package_pin = int(cells[0])
                pad.power_domain = cells[4] or None
                pad.analog = [c for c in cells[5:8] if c]
                pad.rtc_funcs = [c for c in cells[8:10] if c]
                pad.types = {i: cells[11 + 2 * i] for i in range(6) if cells[11 + 2 * i]}
                pad.drive_strength = cells[22] or None


def esp32_io_mux() -> list[EspPad]:
    pads = _esp_trm_rows()
    _esp_datasheet_rows(pads)
    return [pads[k] for k in sorted(pads)]


@dataclass
class PinFlag:
    gpio: int
    kind: str                # strapping | input_only | flash
    note: str
    doc: str
    page: int
    quote: str


_STRAP_QUOTES = {0: "GPIO0 Pull-up 1", 2: "GPIO2 Pull-down 0", 12: "MTDI Pull-down 0", 15: "MTDO Pull-up 1", 5: "GPIO5 Pull-up 1"}
_FLASH_QUOTES = {  # Table 2-6 (tr.20): "Chip Pin | Off-Package Flash"; GPIO tương ứng lấy từ IO_MUX (TRM tr.133: GPIO6 = SD_CLK ...)
    6: ("SD_CLK", "SD_CLK CLK"), 7: ("SD_DATA_0", "SD_DATA_0/SPIQ IO1/DO"), 8: ("SD_DATA_1", "SD_DATA_1/SPID IO0/DI"),
    9: ("SD_DATA_2", "SD_DATA_2/SPIHD IO3/HOLD#"), 10: ("SD_DATA_3", "SD_DATA_3/SPIWP IO2/WP#"), 11: ("SD_CMD", "SD_CMD CS#"),
    16: ("GPIO16", "GPIO16 CS#"), 17: ("GPIO17", "GPIO17 IO1/DO")}


def esp32_pin_flags() -> list[PinFlag]:
    flags: list[PinFlag] = []
    for g, q in _STRAP_QUOTES.items():
        flags.append(PinFlag(g, "strapping", f"Strapping pin: default {q.split(' ', 1)[1]} (bit value) at reset (Table 3-1)",
                             ESP_DS, 22, q))
    for g in range(34, 40):
        flags.append(PinFlag(g, "input_only", "Input-only: no output driver, no internal pull-up/pull-down",
                             ESP_DS, 61, "GPIO pins 34-39 are input-only"))
    for g, (pad, q) in _FLASH_QUOTES.items():
        extra = (" (only on variants with in-package flash/PSRAM, Table 2-5)" if g in (16, 17) else "")
        flags.append(PinFlag(g, "flash", f"{pad}: connected to external/in-package SPI flash or PSRAM; not recommended for "
                                         f"other uses (Section 2.6){extra}", ESP_DS, 20, q))
    return flags


# --------------------------------------------------------------------------- nRF52840
NRF_PS = "nRF52840_PS"
_NRF_ROW = re.compile(r"^((?:[A-Z]{1,2}\d{1,2})|Die pad)\s+(\S.*)$")
_NRF_NOISE = re.compile(r"^(4413_417 |Hardware and layout$|Pin Name Function Description Recommended usage$)")


@dataclass
class NrfPin:
    pin: str                      # P0.31
    ball: str                     # A8 (aQFN73)
    functions: list[str]          # AIN7, XL1, NFC1, TRACEDATA0, SWO, nRESET ...
    low_frequency_only: bool
    usage: str                    # nguyên văn cột mô tả/khuyến nghị đã gom
    page: int
    doc: str = NRF_PS


def nrf_fixed_functions(doc_id: str = NRF_PS) -> list[NrfPin]:
    pages = pdfdocs.load_pages(doc_id)
    rows: list[tuple[str, int, list[str]]] = []
    for p in (927, 928, 929):
        done = False
        for line in pages[p].split("\n"):
            line = line.strip()
            if not line or _NRF_NOISE.match(line):
                continue
            if line.startswith("Table 61:"):
                done = True
                break
            m = _NRF_ROW.match(line)
            if m and not line.startswith(("D+", "D-")):
                rows.append((m.group(1), p, [m.group(2)]))
            elif rows:
                rows[-1][2].append(line)
        if done:
            break
    out: list[NrfPin] = []
    for ball, page, lines in rows:
        name = lines[0].split()[0]
        if not re.fullmatch(r"P[01]\.\d{2}", name):
            continue
        blob = " ".join(lines)
        funcs = [f for f in re.findall(r"\b(AIN\d|XL[12]|NFC[12]|TRACECLK|TRACEDATA\d|nRESET|SWO)\b", blob)]
        if "Serial wire output (SWO)" in blob and "SWO" not in funcs:
            funcs.append("SWO")
        out.append(NrfPin(pin=name, ball=ball, functions=list(dict.fromkeys(funcs)),
                          low_frequency_only="low frequency I/O only" in re.sub(r"\s+", " ", blob), usage=blob, page=page))
    return sorted(out, key=lambda r: (int(r.pin[1]), int(r.pin[3:])))


# --------------------------------------------------------------------------- ánh xạ tín hiệu -> peripheral SVD
_DEBUG = "debug/trace port (Arm CoreSight), not an SVD peripheral"
_NO_PERIPHERAL = {
    "EVENTOUT": "Cortex-M4 event output pin function (EVENTOUT), not an SVD peripheral",
    "IR": "infrared output is produced by TIM16/TIM17 (datasheet §3.27), not a separate SVD peripheral",
    "I2SCKIN": "external I2S clock input (I2S_CKIN) feeds RCC; not a standalone SVD peripheral",
    "SWDIO": _DEBUG, "SWCLK": _DEBUG, "JTMS": _DEBUG, "JTCK": _DEBUG, "JTDI": _DEBUG, "JTDO": _DEBUG, "JTRST": _DEBUG,
    "TRACESWO": _DEBUG, "TRACECK": _DEBUG,
}


def signal_peripheral(signal: str, svd: dict[str, str | None]) -> tuple[str | None, str | None]:
    """(peripheral SVD, None) hoặc (None, lý do). `svd` = {tên peripheral: groupName}."""
    prefix = re.split(r"[_-]", signal)[0]
    if prefix in _NO_PERIPHERAL:
        return None, _NO_PERIPHERAL[prefix]
    if re.fullmatch(r"TRACED\d", prefix):
        return None, _DEBUG
    if prefix == "MCO":
        return "RCC", None
    if prefix in svd:
        return prefix, None
    m = re.fullmatch(r"I2S(\d)", prefix)
    if m and f"SPI{m.group(1)}" in svd:                       # SVD gọi SPI/I2S là SPIx
        return f"SPI{m.group(1)}", None
    base = re.sub(r"\d+$", "", prefix)
    digits = prefix[len(base):]
    pool = sorted(n for n, g in svd.items() if (g or "").upper() == base.upper() or n.upper() == base.upper())
    if pool:
        same = [n for n in pool if digits and re.search(rf"{re.escape(digits)}$", n)]
        return (same or pool)[0], None
    return None, f"unknown signal prefix {prefix!r}"


# --------------------------------------------------------------------------- ghi vào SQLite
def stm32_checks(af_rows: list[AfRow], pindefs: dict[str, PinDef], svd: dict[str, str | None]) -> dict:
    """Kiểm tra chéo cho báo cáo chất lượng: thiếu khe AF, tín hiệu không có peripheral SVD, AF vs pin definition."""
    missing = [r.pin for r in af_rows if sorted(r.slots) != list(range(16))]
    unknown: dict[str, list[str]] = {}
    for r in af_rows:
        for ss in r.slots.values():
            for s in ss:
                per, reason = signal_peripheral(s, svd)
                if per is None:
                    unknown.setdefault(re.split(r"[_-]", s)[0], []).append(s)
    by_pin = {r.pin: {s for ss in r.slots.values() for s in ss} for r in af_rows}
    mismatch: dict[str, list[str]] = {}
    for n, d in pindefs.items():
        if not d.is_gpio:
            continue
        if n not in by_pin:
            mismatch[n] = ["<no AF row>"]
            continue
        extra = [s for s in d.alt_functions if not any(x in by_pin[n] for x in [s, *s.split("/")])]
        if extra:
            mismatch[n] = extra
    return {"missing_slots": missing, "no_peripheral": {k: sorted(set(v)) for k, v in unknown.items()}, "af_vs_pindef": mismatch}


def _svd_names(conn, chip: str) -> dict[str, str | None]:
    return {r["name"]: r["group_name"] for r in conn.execute("select name, group_name from peripherals where chip=?", (chip,))}


def ingest_stm32(conn) -> dict:
    chip = "stm32g474"
    af_rows, pindefs = stm32_af_rows(), stm32_pin_definitions()
    svd = _svd_names(conn, chip)
    checks = stm32_checks(af_rows, pindefs, svd)
    if checks["missing_slots"]:
        raise ValueError(f"AF table: pins without 16 AF slots: {checks['missing_slots']}")
    for t in ("pins", "pin_functions", "pin_flags", "chip_notes"):
        conn.execute(f"DELETE FROM {t} WHERE chip=?", (chip,))
    conn.execute("DELETE FROM data_anomalies WHERE chip=? AND kind IN ('af_vs_pindef','af_signal_without_peripheral')", (chip,))
    import json
    for r in af_rows:
        d = pindefs.get(r.pin)
        m = _GPIO.match(r.pin)
        conn.execute("INSERT INTO pins VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (chip, r.pin, m.group(1)[1], int(m.group(2)), d.pad_name if d else r.pin, d.io_structure if d else None,
                      int(d.is_5v_tolerant) if d else None, None, None, d.notes if d else None,
                      json.dumps(d.packages) if d else None, ST_DS, d.page if d else r.page, "auto", None))
        for af, sigs in r.slots.items():
            for s in sigs:
                per, reason = signal_peripheral(s, svd)
                conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (chip, r.pin, af, s, per, "af", reason, ST_DS, r.page, "auto"))
        for s in (d.additional_functions if d else []):
            conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (chip, r.pin, None, s, None, "additional", "functions directly selected through peripheral registers",
                          ST_DS, d.page, "auto"))
    for pin, extra in checks["af_vs_pindef"].items():
        conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)", (chip, "af_vs_pindef", pin,
                     f"pin-definition table (Table 12) lists {extra} not found in the Table 13 AF row"))
    for pre, sigs in checks["no_peripheral"].items():
        conn.execute("INSERT INTO data_anomalies VALUES (?,?,?,?)", (chip, "af_signal_without_peripheral", pre,
                     f"{len(sigs)} signal(s) {sigs[:4]}: {signal_peripheral(sigs[0], svd)[1]}"))
    conn.execute("INSERT INTO chip_notes VALUES (?,?,?,?,?,?,?)",
                 (chip, "af_slots_per_pin", "16", ST_DS, 73, "Port AF0 AF1 AF2 AF3 AF4 AF5 AF6 AF7 AF8 AF9 AF10 AF11 AF12 AF13 AF14 AF15", "auto"))
    conn.commit()
    return {"pins": len(af_rows), "checks": {k: len(v) for k, v in checks.items()}}


def ingest_esp32(conn) -> dict:
    import json
    chip = "esp32"
    pads = esp32_io_mux()
    flags = esp32_pin_flags()
    for f in flags:
        if not verify_quote(f.doc, f.page, f.quote):
            raise ValueError(f"quote not found on {f.doc} p.{f.page}: {f.quote!r}")
    for t in ("pins", "pin_functions", "pin_flags", "chip_notes"):
        conn.execute(f"DELETE FROM {t} WHERE chip=?", (chip,))
    reset_txt = {0: "IE=0 (input disabled)", 1: "IE=1 (input enabled)", 2: "IE=1, WPD=1 (input enabled, pull-down)",
                 3: "IE=1, WPU=1 (input enabled, pull-up)"}
    strap = {f.gpio: f for f in flags if f.kind == "strapping"}
    for p in pads:
        pin = f"GPIO{p.gpio}"
        notes = [f"reset: {reset_txt[p.reset_cfg]} (TRM Table 6.10-1)"]
        if p.power_domain:
            notes.append(f"power domain {p.power_domain} (datasheet A.4)")
        if p.rtc_capable:
            notes.append("RTC/analog functions via RTC_MUX")
        conn.execute("INSERT INTO pins VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (chip, pin, None, p.gpio, p.pad_name, None, None, int(p.input_only),
                      strap[p.gpio].note if p.gpio in strap else None, "; ".join(notes),
                      json.dumps({"chip_pin_no": p.package_pin}) if p.package_pin else None, ESP_TRM, p.page, "auto", None))
        for n, sig in p.functions.items():
            if sig:
                conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (chip, pin, n, sig, None, "io_mux", f"type {p.types[n]}" if n in p.types else None,
                              ESP_TRM, p.page, "auto"))
        for a in p.analog:
            conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (chip, pin, None, a, None, "analog", None, ESP_DS, p.ds_page, "auto"))
        for a in p.rtc_funcs:
            conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (chip, pin, None, a, None, "rtc", None, ESP_DS, p.ds_page, "auto"))
    for f in flags:
        conn.execute("INSERT INTO pin_flags VALUES (?,?,?,?,?,?,?,?)",
                     (chip, f"GPIO{f.gpio}", f.kind, f.note, f.doc, f.page, f.quote, "curated"))
    q = "can be mapped onto any GPIO pin"
    if not verify_quote(ESP_DS, 62, q):
        raise ValueError("gpio matrix quote not found")
    conn.execute("INSERT INTO chip_notes VALUES (?,?,?,?,?,?,?)",
                 (chip, "gpio_matrix", "Signals of on-chip peripherals can be routed to any GPIO through the GPIO matrix; "
                  "IO_MUX Function0..5 give the direct (fast) assignments listed per pin.", ESP_DS, 62, q, "curated"))
    conn.commit()
    return {"pins": len(pads), "flags": len(flags)}


def ingest_nrf(conn) -> dict:
    chip = "nrf52840"
    pins = nrf_fixed_functions()
    for t in ("pins", "pin_functions", "pin_flags", "chip_notes"):
        conn.execute(f"DELETE FROM {t} WHERE chip=?", (chip,))
    import json
    for p in pins:
        port, num = int(p.pin[1]), int(p.pin[3:])
        conn.execute("INSERT INTO pins VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (chip, p.pin, str(port), num, p.pin, None, None, 0, None,
                      "standard drive, low frequency I/O only (recommended usage)" if p.low_frequency_only else None,
                      json.dumps({"aQFN73": p.ball}), p.doc, p.page, "auto", None))
        for f in p.functions:
            conn.execute("INSERT INTO pin_functions VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (chip, p.pin, None, f, None, "fixed", None, p.doc, p.page, "auto"))
    quotes = {"psel_routing": ("Any pin can be mapped to a peripheral for layout flexibility", 322,
                               "GPIO is freely routable: any peripheral signal can be assigned to any P0/P1 pin through the "
                               "peripheral's PSEL.<signal> register (no alternate-function table). Only a few pins have fixed "
                               "functions (AIN, XL1/XL2, NFC1/NFC2, TRACE*, nRESET); see pin_functions kind='fixed'."),
              "psel_register_layout": ("Connected 0 Connect", 798,
                                       "PSEL register: PIN [0..31] bits 4:0, PORT [0..1] bit 5, CONNECT bit 31 "
                                       "(0 = Connected, 1 = Disconnected; reset 0xFFFFFFFF). Example: TWIM PSEL.SCL / PSEL.SDA.")}
    for topic, (q, page, value) in quotes.items():
        if not verify_quote(NRF_PS, page, q):
            raise ValueError(f"nRF note quote not found on p.{page}: {q!r}")
        conn.execute("INSERT INTO chip_notes VALUES (?,?,?,?,?,?,?)", (chip, topic, value, NRF_PS, page, q, "curated"))
    conn.commit()
    return {"pins": len(pins), "fixed": sum(len(p.functions) for p in pins)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from . import hwdb

    ap = argparse.ArgumentParser(description="Chân / AF / cấu trúc I/O -> data/hw_specs.sqlite")
    ap.add_argument("--db", default=str(hwdb.DEFAULT_DB))
    a = ap.parse_args(argv)
    conn = hwdb.connect(a.db)
    hwdb.init_schema(conn)
    for name, fn in (("stm32g474", ingest_stm32), ("esp32", ingest_esp32), ("nrf52840", ingest_nrf)):
        print(name, fn(conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
