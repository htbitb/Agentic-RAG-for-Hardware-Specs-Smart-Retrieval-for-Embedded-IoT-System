"""DRC (Design Rule Check, W2): 8 luật xác định trên trạng thái Board State, mỗi vi phạm có MÃ, thông điệp và (nếu có) PHƯƠNG ÁN THAY THẾ.

| Luật | Nội dung |
| DRC-PIN-01 | mỗi chân một chủ, trừ bus chia sẻ khai báo rõ |   | DRC-PIN-02 | tín hiệu phải có trong bảng AF của chân (và chân có trong gói) |
| DRC-PIN-03 | không gán chức năng output cho chân input-only |  | DRC-CLK-01 | tần số dẫn xuất không vượt `clock_limits` |
| DRC-CLK-02 | ngoại vi dùng phải được bật clock (RCC) |         | DRC-ELEC-01 | kết nối giữa hai miền điện áp phải qua kiểm mức logic / chân FT |
| DRC-PWR-01 | tổng dòng theo chế độ ≤ ngân sách |                 | DRC-REQ-01 | mọi requirement phải `satisfied` hoặc `waived` (có lý do) |

Mức: `error` (làm `ok` = False) · `warning` · `unknown` (thiếu số liệu: KHÔNG BAO GIỜ tính là đạt; `complete` = False).
Dữ liệu chân / giới hạn đến từ `hw` (HwStore: bảng AF, pin_flags, electrical_limits, clock_limits của P1); cây clock tái dùng `Simulator` + `clock_tree` của P2.
Module chỉ dành cho agent (eval.tools.freeze_hwmodel.AGENT_ONLY): được phép phụ thuộc `mcp_servers.hw_queries` qua đối tượng `hw` truyền vào.
"""
from __future__ import annotations

import math
import re

from .clock_tree import load_limits
from .periph import rcc
from .sim import Simulator

RULES = {
    "DRC-PIN-01": "Mỗi chân chỉ có một chủ, trừ bus chia sẻ được khai báo rõ",
    "DRC-PIN-02": "Tín hiệu phải tồn tại trong bảng AF của chân đó (và chân phải có trong gói)",
    "DRC-PIN-03": "Không gán chức năng output cho chân input-only",
    "DRC-CLK-01": "Các tần số dẫn xuất không vượt clock_limits",
    "DRC-CLK-02": "Peripheral được dùng phải được bật clock (RCC)",
    "DRC-ELEC-01": "Kết nối giữa hai miền điện áp phải qua kiểm tra mức logic; chân không FT không được nhận 5 V",
    "DRC-PWR-01": "Tổng dòng theo chế độ không vượt ngân sách hoặc yêu cầu",
    "DRC-REQ-01": "Mọi requirement phải ở trạng thái satisfied hoặc waived (có lý do)",
}
EPS = 1e-9
GENERIC_SIGNALS = {"GPIO", "GPIO_IN", "GPIO_OUT"}                      # chân dùng như GPIO thường: hợp lệ trên mọi chân có thật
BUS_SIGNAL = re.compile(r"^(I2C\d*_(SCL|SDA)|SPI\d*_(SCK|MISO|MOSI)|(FD)?CAN\d*_(H|L|RX|TX)|ONEWIRE\d*|OW\d*)$", re.I)
OUTPUT_MODES = {"output", "out", "af_pp", "af_od", "out_pp", "out_od", "push_pull", "open_drain"}
INPUT_MODES = {"input", "in", "analog", "af_in", "floating"}
ROLE_SIGNAL = {"scl_pin": "SCL", "sda_pin": "SDA", "tx_pin": "TX", "rx_pin": "RX", "sck_pin": "SCK", "miso_pin": "MISO", "mosi_pin": "MOSI", "nss_pin": "NSS"}
ROLE_DIRECTION = {"SCL": "inout", "SDA": "inout", "TX": "out", "RX": "in", "SCK": "out", "MISO": "in", "MOSI": "out", "NSS": "out"}


# ------------------------------------------------------------------------------------------------ tiện ích
def _v(x: float) -> str:
    return f"{x:g}"


def _port_gpio(pin: str) -> str | None:
    m = re.fullmatch(r"P([A-G])\d+", pin or "")
    return f"GPIO{m.group(1)}" if m else None


def signal_direction(signal: str | None, mode: str | None = None) -> str | None:
    """'in' | 'out' | 'inout' | None (không biết). `mode` tường minh (output / AF_PP / input / analog...) thắng tên tín hiệu."""
    m = (mode or "").lower()
    if m in OUTPUT_MODES:
        return "out"
    if m in INPUT_MODES:
        return "in"
    s = (signal or "").upper()
    if s == "GPIO_OUT":
        return "out"
    if s == "GPIO_IN":
        return "in"
    if s == "GPIO":
        return "inout"
    if re.search(r"_(SCL|SDA)$", s):
        return "inout"
    if re.search(r"(_TX|_TXD|_MOSI|_SCK|_CK|_RTS|_DE|_NSS|_CS|_OUT\d*|_PWM\d*)$", s) or re.fullmatch(r"U\dTXD|DAC\d*_OUT\d*", s):
        return "out"
    if re.search(r"(_RX|_RXD|_MISO|_CTS|_IN\d*|_ETR|_BKIN\d*)$", s) or re.fullmatch(r"U\dRXD|ADC\d*_(IN|CH)\d+", s):
        return "in"
    return None


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def norm_pin(pin, chips=()) -> str:
    """Tên chân chuẩn hoá để so sánh: bỏ khoảng trắng, viết hoa, bỏ tiền tố '<chip>.' khi `<chip>` là target đã khai báo ('stm32g474.pa8' -> 'PA8').
    Tiền tố lạ ('foo.PA8') và tên có dấu chấm của nRF ('P0.13') được giữ nguyên."""
    s = str(pin).strip().upper()
    head, dot, rest = s.partition(".")
    return rest.strip() if dot and head.strip().lower() in {str(c).lower() for c in chips} else s


REQ_TYPES = ("pwm", "i2c", "uart", "spi", "adc", "dac", "can", "gpio_out", "gpio_in", "clock", "power", "other")
_REQ_STR_KEYS = ("pin", "signal", "instance", "timer", "mode", "scl_pin", "sda_pin", "tx_pin", "rx_pin", "sck_pin", "miso_pin", "mosi_pin", "nss_pin", "evidence", "waiver_reason")
_REQ_NUM_KEYS = ("baud", "bitrate", "budget_ua")
_REQ_NUM_SUFFIX = ("_hz", "_pct", "_ua", "_ma", "_us", "_ns")


def validate_requirement(r) -> list[str]:
    """Các vấn đề về KIỂU của một requirement (danh sách rỗng = dùng được). Dùng chung cho `set_requirements` (từ chối) và DRC (log cũ: báo `unknown`, không ném)."""
    if not isinstance(r, dict):
        return [f"a requirement must be an object, got {type(r).__name__}"]
    out = []
    if not isinstance(r.get("id"), str) or not r["id"].strip():
        out.append("`id` must be a non-empty string")
    typ = r.get("type")
    if not isinstance(typ, str) or typ.strip().lower() not in REQ_TYPES:
        out.append(f"`type` must be one of {list(REQ_TYPES)}, got {typ!r}")
    for k in _REQ_STR_KEYS:
        if r.get(k) is not None and (not isinstance(r[k], str) or not r[k].strip()):
            out.append(f"`{k}` must be a non-empty string, got {r[k]!r}")
    pins = r.get("pins")
    if pins is not None and (not isinstance(pins, (list, tuple)) or not all(isinstance(x, str) and x.strip() for x in pins)):
        out.append(f"`pins` must be a list of non-empty strings, got {pins!r}")
    if r.get("shared") is not None and not isinstance(r["shared"], bool):
        out.append(f"`shared` must be true or false, got {r['shared']!r}")
    for k, v in r.items():
        if v is None or not (k in _REQ_NUM_KEYS or k.endswith(_REQ_NUM_SUFFIX)):
            continue
        if not _finite(v):
            out.append(f"`{k}` must be a finite number, got {v!r}")
        elif k.endswith("_pct") and not 0 <= v <= 100:
            out.append(f"`{k}` must be between 0 and 100, got {v!r}")
        elif (k.endswith("_hz") or k in ("baud", "bitrate")) and v <= 0:
            out.append(f"`{k}` must be positive, got {v!r}")
        elif k.endswith(("_ua", "_ma", "_us", "_ns")) and v < 0:
            out.append(f"`{k}` must not be negative, got {v!r}")
    if isinstance(typ, str) and typ.strip().lower() == "power":
        if not isinstance(r.get("mode"), str) or not r["mode"].strip():
            out.append("a power requirement needs a `mode` such as 'sleep' or 'active'")
        if not _finite(r.get("budget_ua")) or r["budget_ua"] <= 0:
            out.append(f"a power requirement needs `budget_ua` as a positive finite number of microamps, got {r.get('budget_ua')!r}")
    return out


def _claimant(owner: str, req_ids: list[str]) -> str:
    """Chủ của chân quy về requirement: owner == id hoặc id + [-:_ ./] + hậu tố ('R1-motor-pwm' -> 'R1'); nếu không khớp thì giữ nguyên owner."""
    best = ""
    for rid in req_ids:
        if owner == rid or re.match(re.escape(rid) + r"[-:_ ./]", owner):
            best = max(best, rid, key=len)
    return best or owner


def _str_or_none(x) -> str | None:
    return x if isinstance(x, str) and x.strip() else None


def req_pin_roles(r: dict, chips=()) -> list[dict]:
    """[(pin, signal hoặc None, hướng hoặc None, role)] mà một requirement đòi hỏi. Tên chân được chuẩn hoá (`norm_pin`); trường sai kiểu bị BỎ QUA
    (DRC-REQ-01 báo `REQ_INVALID`)."""
    out = []
    inst = _str_or_none(r.get("instance"))
    for key, role in ROLE_SIGNAL.items():
        if _str_or_none(r.get(key)):
            out.append({"pin": norm_pin(r[key], chips), "signal": f"{inst}_{role}" if inst else None, "direction": ROLE_DIRECTION[role], "role": role})
    if _str_or_none(r.get("pin")):
        typ = str(r.get("type") or "").lower()
        direction = {"pwm": "out", "gpio_out": "out", "gpio_in": "in", "adc": "in", "dac": "out"}.get(typ)
        out.append({"pin": norm_pin(r["pin"], chips), "signal": _str_or_none(r.get("signal")), "direction": direction, "role": "PIN"})
    pins = r.get("pins")
    for p in pins if isinstance(pins, (list, tuple)) else []:
        if _str_or_none(p):
            out.append({"pin": norm_pin(p, chips), "signal": None, "direction": None, "role": "PIN"})
    return out


def _chips(state: dict) -> list[str]:
    return [t["chip"] for t in state["targets"]]


# ------------------------------------------------------------------------------------------------ danh mục chân
class Catalog:
    """Tra cứu chân / tín hiệu / giới hạn qua `hw` (HwStore), có cache."""

    def __init__(self, hw):
        self.hw = hw
        self._pins: dict = {}
        self._flex: dict = {}

    def chip(self, name: str | None) -> str | None:
        return self.hw.chip(name)

    def pin(self, chip: str, pin: str) -> dict | None:
        key = (chip, (pin or "").upper())
        if key not in self._pins:
            r = self.hw.query_pin_alternate_function(chip, pin)
            self._pins[key] = None if "error" in r else r
        return self._pins[key]

    def flexible_routing(self, chip: str) -> bool:
        """ESP32 (GPIO matrix) / nRF52840 (PSEL): tín hiệu ngoại vi gán được lên hầu hết chân => không có bảng AF cố định để kiểm."""
        if chip not in self._flex:
            self._flex[chip] = self.hw.conn.execute(
                "SELECT 1 FROM chip_notes WHERE chip=? AND topic IN ('psel_routing','gpio_matrix')", (chip,)).fetchone() is not None
        return self._flex[chip]

    @staticmethod
    def in_package(rec: dict, package: str | None) -> bool | None:
        """True/False nếu biết; None nếu không biết (không có gói, hoặc DB không có dữ liệu gói cho chân này)."""
        pk = rec.get("packages") or {}
        if not package or not pk:
            return None
        if package not in pk:
            return None
        return pk[package] not in (None, "-", "")

    def signal_af(self, chip: str, rec: dict, signal: str):
        """-> ('gpio'|'routable'|'af', af hoặc None) nếu hợp lệ trên chân; None nếu tín hiệu không có trong bảng AF của chân."""
        sig = (signal or "").upper()
        if sig in GENERIC_SIGNALS:
            return ("gpio", None)
        for f in rec.get("functions", []):
            if (f.get("function") or "").upper() == sig:
                return ("af", f.get("af"))
        if self.flexible_routing(chip):
            return ("routable", None)
        return None

    def alternatives(self, chip: str, signal: str, package: str | None = None, taken: dict | None = None, limit: int = 12) -> list[dict]:
        """Chân còn trống mang tín hiệu `signal` (theo bảng AF), có trong gói; thứ tự cổng/số chân tự nhiên."""
        taken = taken or {}
        res = self.hw.find_pins_for_signal(chip, signal, limit=200)
        out = []
        for m in res.get("matches", []):
            if (m.get("function") or "").upper() != (signal or "").upper() or m["pin"] in taken:
                continue
            rec = self.pin(chip, m["pin"])
            if rec is not None and self.in_package(rec, package) is False:
                continue
            pk = (rec or {}).get("packages", {}).get(package) if package else None
            out.append({"pin": m["pin"], "af": m["af"], "signal": m["function"], "free": True, **({"package_pin": pk} if pk else {})})
            if len(out) >= limit:
                break
        return out

    def mcu_current_ua(self, chip: str, mode: str):
        """-> (µA | None, ghi chú). Chỉ lấy từ DB khi ĐÚNG MỘT dòng `power_consumption` khớp tên chế độ và có giá trị `typ`; ngược lại None."""
        norm = lambda s: re.sub(r"[\s_\-]+", " ", (s or "").lower()).strip()      # noqa: E731
        rows = [dict(r) for r in self.hw.conn.execute(
            "SELECT parameter, typ, unit, doc, page FROM electrical_limits WHERE chip=? AND field_type='current' AND category='power_consumption'", (chip,))]
        hits = [r for r in rows if norm(mode) and norm(mode) in norm(r["parameter"])]
        if not rows:
            return None, f"no power-consumption rows for {chip} in the database"
        if len(hits) != 1:
            return None, (f"{len(hits)} database rows match mode {mode!r}" if hits else f"no database row matches mode {mode!r}")
        r = hits[0]
        if r["typ"] in (None, ""):
            return None, f"row {r['parameter']!r} has no typical value"
        scale = {"µa": 1.0, "ua": 1.0, "ma": 1e3, "a": 1e6, "na": 1e-3}.get((r["unit"] or "").lower())
        if scale is None:
            return None, f"unit {r['unit']!r} not understood"
        return float(r["typ"]) * scale, f"{r['doc']} p.{r['page']}: {r['parameter']}"

    def levels(self, chip: str, vdd: float, io_structure: str | None):
        return self.hw.chip_logic_levels(chip, vdd, io_structure)

    def vdda_max(self, chip: str):
        """-> (V, trang) của mức VDDA tối đa khuyến nghị (DS Table 17) hoặc None nếu DB không có (ESP32/nRF)."""
        row = self.hw.conn.execute("SELECT max, page FROM electrical_limits WHERE chip=? AND field_type='analog_supply_voltage' AND category='recommended_operating' "
                                   "AND max IS NOT NULL ORDER BY id", (chip,)).fetchone()
        try:
            return (float(row[0]), row[1]) if row else None
        except (TypeError, ValueError):
            return None


# ------------------------------------------------------------------------------------------------ cây clock (DRC-CLK-01)
class ClockConfigError(ValueError):
    """Cấu hình clock không hợp lệ (không phải vi phạm giới hạn): thiếu hse_hz, M/N/R ngoài trường bit, bộ chia không tồn tại..."""


_HPRE = {1: 0b0000, 2: 0b1000, 4: 0b1001, 8: 0b1010, 16: 0b1011, 64: 0b1100, 128: 0b1101, 256: 0b1110, 512: 0b1111}
_PPRE = {1: 0b000, 2: 0b100, 4: 0b101, 8: 0b110, 16: 0b111}
_PLLR = {2: 0b00, 4: 0b01, 6: 0b10, 8: 0b11}
_SRC = {"HSI": "HSI16", "HSI16": "HSI16", "HSE": "HSE", "PLL": "PLL"}
_RANGES = {"range1_boost": "boost", "range1_normal": "normal", "range2": "range2"}
_CLOCK_CODE = {"sysclk_max": "SYSCLK", "hclk_max_range1_normal": "SYSCLK", "sysclk_max_range2": "SYSCLK", "vco_min": "VCO", "vco_max": "VCO",
               "pll_in_min": "PLL_IN", "pll_in_max": "PLL_IN", "plln_min": "PLLN"}
_EVIDENCE = {"SYSCLK": [{"doc": "STM32G474_Datasheet", "page": 84}, {"doc": "STM32G474_RM0440", "page": 232}], "VCO": [{"doc": "STM32G474_Datasheet", "page": 123}],
             "PLL_IN": [{"doc": "STM32G474_Datasheet", "page": 123}], "HSE": [{"doc": "STM32G474_Datasheet", "page": 117}], "FLASH_WS": [{"doc": "STM32G474_RM0440", "page": 98}],
             "PCLK1": [{"doc": "STM32G474_Datasheet", "page": 84}], "PCLK2": [{"doc": "STM32G474_Datasheet", "page": 84}], "PLLN": [{"doc": "STM32G474_RM0440", "page": 293}]}


def _int(x, what: str, lo: int, hi: int) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or int(x) != x or not lo <= int(x) <= hi:
        raise ClockConfigError(f"{what} must be an integer in [{lo}, {hi}], got {x!r}")
    return int(x)


def normalize_clock_cfg(cfg: dict) -> dict:
    """Cấu hình clock chuẩn hoá (idempotent). Khoá: source (HSI16|HSE|PLL), hse_hz, pll{source,m,n,r}, ahb_div, apb1_div, apb2_div,
    voltage_range (range1_boost|range1_normal|range2), flash_latency (tuỳ chọn), enabled_peripherals (tuỳ chọn; tên theo bảng cổng RCC)."""
    if not isinstance(cfg, dict):
        raise ClockConfigError("clock config must be an object")
    src = _SRC.get(str(cfg.get("source", "")).upper())
    if src is None:
        raise ClockConfigError(f"source must be one of HSI16, HSE, PLL, got {cfg.get('source')!r}")
    out: dict = {"source": src}
    pll = cfg.get("pll")
    if pll and not isinstance(pll, dict):
        raise ClockConfigError(f"pll must be an object {{m, n, r}}, got {type(pll).__name__}")
    sysclk = _SRC.get(str(cfg["sysclk_source"]).upper()) if cfg.get("sysclk_source") else ("PLL" if pll else src)
    if sysclk is None:
        raise ClockConfigError(f"sysclk_source must be one of HSI16, HSE, PLL, got {cfg.get('sysclk_source')!r}")
    if src == "PLL" and not pll:
        raise ClockConfigError("source PLL needs a `pll` object {m, n, r}")
    if sysclk == "PLL" and not pll:
        raise ClockConfigError("sysclk_source PLL needs a `pll` object {m, n, r}")
    out["sysclk_source"] = sysclk
    if pll:
        psrc = _SRC.get(str(pll.get("source") or (src if src in ("HSI16", "HSE") else "HSI16")).upper())
        if psrc not in ("HSI16", "HSE"):
            raise ClockConfigError(f"pll.source must be HSI16 or HSE, got {pll.get('source')!r}")
        out["pll"] = {"source": psrc, "m": _int(pll.get("m"), "pll.m", 1, 16), "n": _int(pll.get("n"), "pll.n", 8, 127), "r": _int(pll.get("r"), "pll.r", 2, 8)}
        if out["pll"]["r"] not in _PLLR:
            raise ClockConfigError(f"pll.r must be one of 2, 4, 6, 8, got {pll.get('r')!r}")
    uses_hse = sysclk == "HSE" or (pll and out["pll"]["source"] == "HSE")
    if cfg.get("hse_hz") is not None or uses_hse:
        if cfg.get("hse_hz") is None:
            raise ClockConfigError("hse_hz (the board's HSE crystal frequency in Hz) is required when HSE is used: it is not guessed")
        out["hse_hz"] = _int(cfg["hse_hz"], "hse_hz", 1, 10**9)
    for key in ("ahb_div", "apb1_div", "apb2_div"):
        table = _HPRE if key == "ahb_div" else _PPRE
        d = cfg.get(key, 1)
        if isinstance(d, bool) or not isinstance(d, (int, float)) or d not in table:
            raise ClockConfigError(f"{key} must be one of {sorted(table)}, got {d!r}")
        out[key] = int(d)
    vr = cfg.get("voltage_range", "range1_boost")
    if not isinstance(vr, str) or vr not in _RANGES:
        raise ClockConfigError(f"voltage_range must be one of {sorted(_RANGES)}, got {vr!r}")
    out["voltage_range"] = vr
    if cfg.get("flash_latency") is not None:
        out["flash_latency"] = _int(cfg["flash_latency"], "flash_latency", 0, 15)
    if cfg.get("enabled_peripherals") is not None:
        ep = cfg["enabled_peripherals"]
        if not isinstance(ep, (list, tuple, set)) or not all(isinstance(n, str) for n in ep):
            raise ClockConfigError(f"enabled_peripherals must be a list of RCC peripheral names, got {ep!r}")
        names = sorted({n.strip() for n in ep})
        known = set(rcc.GATES) | rcc.UNGATED
        bad = [n for n in names if n not in known]
        if bad:
            raise ClockConfigError(f"unknown peripheral name(s) {bad} in enabled_peripherals (use RCC names such as TIM1, GPIOA, I2C3, USART1)")
        out["enabled_peripherals"] = names
    return out


def _clock_ops(n: dict, latency: int, start_need: int = 0) -> list[dict]:
    """Chuỗi ghi thanh ghi. Số chu kỳ chờ Flash được ghi `max(latency, start_need)` TRƯỚC khi đổi nguồn SYSCLK (HCLK khởi đầu là HSI16 16 MHz cần `start_need`)
    và hạ về `latency` SAU khi đổi (RM0440 p.98: tăng tần số thì tăng WS trước, giảm tần số thì giảm WS sau) - nên không có trạng thái chuyển tiếp bị báo oan."""
    op = lambda kind, reg, **kw: {"op": kind, "reg": reg, **kw}                  # noqa: E731
    ops = [op("set_bits", "RCC_APB1ENR1", mask=1 << 28)]                         # PWREN (RM0440 p.309): PWR_CRx chỉ ghi được khi có clock
    vr = n["voltage_range"]
    if vr == "range2":
        ops.append(op("modify", "PWR_CR1", mask=0b11 << 9, value=0b10 << 9))
    else:
        ops += [op("modify", "PWR_CR1", mask=0b11 << 9, value=0b01 << 9),
                op("set_bits" if vr == "range1_normal" else "clear_bits", "PWR_CR5", mask=1 << 8)]
    ops.append(op("modify", "FLASH_ACR", mask=0xF, value=max(latency, start_need)))
    pll = n.get("pll")
    if n["sysclk_source"] == "HSE" or (pll and pll["source"] == "HSE"):
        ops.append(op("set_bits", "RCC_CR", mask=1 << 16))
    if pll:
        src = 0b10 if pll["source"] == "HSI16" else 0b11
        ops += [op("write", "RCC_PLLCFGR", value=src | ((pll["m"] - 1) << 4) | (pll["n"] << 8) | (1 << 24) | (_PLLR[pll["r"]] << 25)),
                op("set_bits", "RCC_CR", mask=1 << 24)]
    ops += [op("modify", "RCC_CFGR", mask=0xF << 4, value=_HPRE[n["ahb_div"]] << 4), op("modify", "RCC_CFGR", mask=0b111 << 8, value=_PPRE[n["apb1_div"]] << 8),
            op("modify", "RCC_CFGR", mask=0b111 << 11, value=_PPRE[n["apb2_div"]] << 11),
            op("modify", "RCC_CFGR", mask=0b11, value={"HSI16": 0b01, "HSE": 0b10, "PLL": 0b11}[n["sysclk_source"]])]
    if latency < start_need:
        ops.append(op("modify", "FLASH_ACR", mask=0xF, value=latency))
    return ops


def _limit_row(hw, symbol: str):
    for r in hw.get_clock_limits("stm32g474", symbol, limit=60).get("results", []):
        if r.get("symbol") == symbol:
            return r
    return None


def evaluate_clock_config(cfg: dict, hw=None) -> dict:
    """Cấu hình clock -> tần số dẫn xuất + vi phạm giới hạn, bằng cách chạy các thao tác thanh ghi tương ứng qua `Simulator` (cùng mô hình với hw-sandbox).

    Trả về {cfg (chuẩn hoá), derived, violations[{code, severity:'error', message, evidence}], assumptions}. Lỗi cấu hình -> ClockConfigError.
    `hw` (HwStore) cho phép kiểm thêm dải thạch anh HSE và trần PCLK1/PCLK2 từ bảng clock_limits."""
    n = normalize_clock_cfg(cfg)
    limits = load_limits("stm32g474")
    mode = _RANGES[n["voltage_range"]]
    first = Simulator("stm32g474", hse_hz=n.get("hse_hz")).run(_clock_ops(n, 15))             # lượt 1: xác định HCLK, rồi chọn số chu kỳ chờ Flash
    clocks = first["clocks"]
    assumptions = []
    if n.get("flash_latency") is not None:
        latency = n["flash_latency"]
    else:
        need = limits.needed_ws(clocks["hclk_hz"], mode) if clocks.get("hclk_hz") else None
        latency = need if need is not None else max(w for w, _ in limits.flash_ws[mode])
        assumptions.append(f"flash_latency not given: the minimum that covers HCLK was used ({latency} WS, RM0440 Table 9 p.98)")
    boot_need = limits.needed_ws(16e6, mode)                                                  # HCLK khởi đầu = HSI16 16 MHz
    res = Simulator("stm32g474", hse_hz=n.get("hse_hz")).run(_clock_ops(n, latency, 0 if boot_need is None else boot_need))
    found: list[dict] = []

    def add(code: str, message: str, key: str):
        if not any(f["code"] == code for f in found):
            found.append({"code": code, "severity": "error", "message": message, "evidence": _EVIDENCE.get(key, [])})

    for v in res["violations"]:
        if v["severity"] != "error":
            continue
        if v["code"] == "SIM-CLK-LIMIT":
            key = _CLOCK_CODE.get(v.get("limit"), "SYSCLK")
            add(f"CLOCK_LIMIT:{key}", v["msg"], key)
        elif v["code"] == "SIM-FLASH-WS":
            add("CLOCK_LIMIT:FLASH_WS", v["msg"], "FLASH_WS")
        elif v["code"] == "SIM-CLK-NOSRC":
            add("CLOCK_CONFIG:NO_SOURCE", v["msg"], "SYSCLK")
    c = res["clocks"]
    if hw is not None:
        if n.get("hse_hz") is not None:
            row = _limit_row(hw, "fOSC_IN")
            if row and row.get("min") is not None and row.get("max") is not None:
                lo, hi = float(row["min"]) * 1e6, float(row["max"]) * 1e6
                if not lo - EPS <= n["hse_hz"] <= hi + EPS:
                    add("CLOCK_LIMIT:HSE", f"HSE {n['hse_hz'] / 1e6:g} MHz is outside the crystal range {lo / 1e6:g}-{hi / 1e6:g} MHz (DS12288 Table 41 p.{row['page']})", "HSE")
        for sym, key, got in (("fPCLK1", "PCLK1", c.get("pclk1_hz")), ("fPCLK2", "PCLK2", c.get("pclk2_hz"))):
            row = _limit_row(hw, sym)
            if row and row.get("max") is not None and got and got > float(row["max"]) * 1e6 + EPS:
                add(f"CLOCK_LIMIT:{key}", f"{key} {got / 1e6:g} MHz > {float(row['max']):g} MHz (DS12288 Table 17 p.{row['page']})", key)
    derived = {k: c.get(k) for k in ("sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz", "tim_clk_apb1_hz", "tim_clk_apb2_hz")}
    derived.update({"sysclk_source": c.get("sysclk_source"), "pll": c.get("pll"), "flash_latency": latency, "voltage_range": n["voltage_range"]})
    return {"cfg": n, "derived": derived, "violations": found, "assumptions": assumptions}


def clock_cfg_of(clock_state: dict) -> dict:
    """Cấu hình (không gồm kết quả dẫn xuất) từ mục `clock` của Board State."""
    return {k: v for k, v in clock_state.items() if k not in ("derived", "violations")}


# ------------------------------------------------------------------------------------------------ mức logic (DRC-ELEC-01)
def _split_ref(ref: str):
    chip, _, rest = (ref or "").partition(".")
    return chip, rest


def endpoint_levels(ref: str, state: dict, cat: Catalog):
    """-> (mô tả điểm cuối, None) hoặc (None, mã lỗi). Điểm cuối MCU: mức logic từ DB theo loại chân; thiết bị: tham số khai báo, thiếu thì giả định CMOS (ghi rõ)."""
    head, rest = _split_ref(ref)
    for t in state["targets"]:
        if head.lower() == t["chip"].lower():
            rec = cat.pin(t["chip"], rest)
            if rec is None or t.get("vdd") is None:
                return None, f"NET_ENDPOINT_UNKNOWN:{ref}"
            lv = cat.levels(t["chip"], float(t["vdd"]), rec.get("io_structure"))
            if "error" in lv:
                return None, f"NET_ENDPOINT_UNKNOWN:{ref}"
            adc = any(re.match(r"ADC\d*_(IN|CH)\d+", str(f.get("function") or ""), re.I) for f in rec.get("functions", []))
            return {"ref": ref, "kind": "mcu", "chip": t["chip"], "pin": rec["pin"], "rail": float(t["vdd"]), "levels": lv, "tolerant_5v": rec.get("is_5v_tolerant"),
                    "adc": adc, "assumed": [], "notes": lv.get("notes", [])}, None
    for d in state["devices"]:
        if head.lower() == str(d["id"]).lower():
            rail = float((d.get("io_vdd_by_pin") or {}).get(rest) or d.get("io_vdd") or d["vdd"])
            lv, assumed = {}, []
            spec = {"vih_min": ("vih_min", 0.7 * rail, "0.7 x VDDIO"), "vil_max": ("vil_max", 0.3 * rail, "0.3 x VDDIO"), "voh_min": ("voh_min", rail - 0.4, "VDDIO - 0.4 V"),
                    "vol_max": ("vol_max", 0.4, "0.4 V"), "in_max": ("vin_max", rail + 0.3, "VDDIO + 0.3 V")}
            for key, (attr, default, text) in spec.items():
                if d.get(attr) is not None:
                    lv[key] = float(d[attr])
                else:
                    lv[key] = default
                    assumed.append(f"{d['id']}.{attr} not given: assumed {text} = {default:g} V")
            lv["voh_max"] = rail
            return {"ref": ref, "kind": "device", "device": d["id"], "pin": rest, "rail": rail, "levels": lv, "tolerant_5v": None, "adc": False, "assumed": assumed, "notes": []}, None
    return None, f"NET_ENDPOINT_UNKNOWN:{ref}"


_KINDS = {"digital": "digital", "bidirectional": "bidirectional", "i2c": "bidirectional", "open_drain": "bidirectional", "analog": "analog"}


def evaluate_net(net: dict, state: dict, cat: Catalog) -> dict:
    """Kiểm mức logic một kết nối: VOH_min ≥ VIH_min, VOL_max ≤ VIL_max, VOH_max ≤ điện áp vào tối đa của đầu nhận (một chiều với digital/analog, hai chiều với bidirectional)."""
    kind = _KINDS.get(net.get("kind"))
    out = {"from": net["from"], "to": net["to"], "kind": net.get("kind"), "status": "PASS", "issues": [], "checks": [], "assumptions": [], "notes": []}
    if kind is None:
        out.update(status="UNKNOWN", issues=[{"code": f"NET_KIND_UNKNOWN:{net.get('kind')}", "severity": "unknown", "message": f"kind must be one of {sorted(_KINDS)}"}])
        return out
    a, ea = endpoint_levels(net["from"], state, cat)
    b, eb = endpoint_levels(net["to"], state, cat)
    for e in (ea, eb):
        if e:
            out["issues"].append({"code": e, "severity": "unknown", "message": f"cannot resolve {e.split(':', 1)[1]} to a target pin or a declared device"})
    if ea or eb:
        out["status"] = "UNKNOWN"
        return out
    out["assumptions"] = a["assumed"] + b["assumed"]
    out["notes"] = a["notes"] + b["notes"]
    pairs = [(a, b)] if kind in ("digital", "analog") else [(a, b), (b, a)]
    codes: dict[str, dict] = {}
    unknown: list[dict] = []
    for src, dst in pairs:
        s, d = src["levels"], dst["levels"]
        pair_ok = True
        checks = []
        if kind != "analog":
            checks.append(("VOH_min >= VIH_min", s["voh_min"] >= d["vih_min"] - EPS, f"{src['ref']} VOH_min {s['voh_min']:g} V vs {dst['ref']} VIH_min {d['vih_min']:g} V", False))
            checks.append(("VOL_max <= VIL_max", s["vol_max"] <= d["vil_max"] + EPS, f"{src['ref']} VOL_max {s['vol_max']:g} V vs {dst['ref']} VIL_max {d['vil_max']:g} V", False))
        if d.get("in_max") is not None:
            checks.append(("VOH_max <= input max", s["voh_max"] <= d["in_max"] + EPS,
                           f"{src['ref']} drives up to {s['voh_max']:g} V, {dst['ref']} accepts at most {d['in_max']:g} V", True))
        else:
            unknown.append({"code": f"NET_INPUT_MAX_UNKNOWN:{dst['ref']}", "severity": "unknown", "direction": f"{src['ref']} -> {dst['ref']}",
                            "message": f"the database has no maximum input voltage for {dst['ref']} ({dst.get('pin')}): the overvoltage check cannot be made, so the connection is not passed"})
        for rule, ok, detail, overvoltage in checks:
            out["checks"].append({"direction": f"{src['ref']} -> {dst['ref']}", "rule": rule, "status": "PASS" if ok else "FAIL", "detail": detail})
            if ok:
                continue
            pair_ok = False
            if overvoltage and dst["kind"] == "mcu" and not dst["tolerant_5v"] and s["voh_max"] >= 4.5:
                code = f"NOT_5V_TOLERANT:{dst['pin']}"
                msg = f"{detail}: pin {dst['pin']} is not 5 V tolerant (DS12288 Table 14 p.82 / Table 17 p.84)"
            else:
                lo, hi = sorted((src["rail"], dst["rail"]))
                code = f"LEVEL_MISMATCH:{_v(lo)}V-{_v(hi)}V"
                msg = detail
            codes.setdefault(code, {"code": code, "severity": "error", "message": msg, "direction": f"{src['ref']} -> {dst['ref']}"})
        if not pair_ok or dst["kind"] != "mcu" or d.get("in_max") is None:
            continue
        direction = f"{src['ref']} -> {dst['ref']}"
        if dst["tolerant_5v"] and s["voh_max"] > dst["rail"] + 0.3 + EPS:
            page = (d.get("in_max_source") or {}).get("page", 84)
            out["notes"].append(f"{dst['pin']}: the input ({s['voh_max']:g} V) is above VDD + 0.3 V ({dst['rail'] + 0.3:g} V): the internal pull-up/pull-down of the pin must be disabled "
                                f"(DS12288 Table 17 p.{page} note: FT pins above min(VDD, VDDA) + 0.3 V)")
        if kind == "analog" and dst.get("adc"):
            v = s["voh_max"]
            vdda = cat.vdda_max(dst["chip"])
            if v <= dst["rail"] + EPS:
                out["assumptions"].append(f"{dst['pin']} has an ADC channel: VDDA/VREF+ assumed equal to VDD = {dst['rail']:g} V (the Board State has no VDDA/VREF+), signal up to {v:g} V is in range")
            elif vdda is not None and v > vdda[0] + EPS:
                code = f"ADC_RANGE:{dst['pin']}"
                codes.setdefault(code, {"code": code, "severity": "error", "direction": direction, "message":
                                        f"{direction}: {v:g} V is above the highest VDDA/VREF+ allowed ({vdda[0]:g} V, DS12288 Table 17 p.{vdda[1]}): the ADC input range VSSA..VREF+ would be exceeded"})
            else:
                unknown.append({"code": f"ADC_RANGE_UNVERIFIED:{dst['pin']}", "severity": "unknown", "direction": direction, "message":
                                f"{dst['pin']} has an ADC channel and the signal reaches {v:g} V, above VDD = {dst['rail']:g} V: VDDA/VREF+ are not declared in the Board State, "
                                f"so the ADC input range cannot be verified (VREF+ must be at least {v:g} V and VDDA <= {vdda[0] if vdda else 'n/a'} V)"})
    out["issues"] = list(codes.values()) + unknown
    out["evidence"] = [e for ep in (a, b) if ep["kind"] == "mcu" for e in ep["levels"].get("evidence", [])]
    out["status"] = "FAIL" if codes else "UNKNOWN" if unknown else "PASS"
    return out


# ------------------------------------------------------------------------------------------------ ngân sách dòng (DRC-PWR-01)
def _norm_mode(m) -> str:
    return re.sub(r"[\s_\-]+", " ", m.lower()).strip() if isinstance(m, str) else ""


def _usable_budget(x) -> bool:
    return _finite(x) and x > 0


def _power_reqs(state: dict, mode: str) -> list[dict]:
    key = _norm_mode(mode)
    return [r for r in state["requirements"] if isinstance(r, dict) and r.get("type") == "power" and key and _norm_mode(r.get("mode")) == key]


def power_budget(state: dict, mode: str, cat: Catalog) -> dict:
    """Tổng dòng (µA) theo chế độ: MCU CHỈ từ DB (đúng một dòng khớp), thiết bị từ số liệu khai báo; thiếu số liệu => `unknown`, không bao giờ 'ok'."""
    contributors, unknown = [], []
    for t in state["targets"]:
        ua, note = cat.mcu_current_ua(t["chip"], mode)
        if ua is None:
            unknown.append({"id": t["chip"], "reason": note})
        else:
            contributors.append({"id": t["chip"], "i_ua": ua, "source": note})
    if not state["targets"]:
        unknown.append({"id": "mcu", "reason": "no target set"})
    key = _norm_mode(mode)
    for d in state["devices"]:
        by_mode = {_norm_mode(k): v for k, v in (d.get("i_ua_by_mode") or {}).items()}
        if key in by_mode and by_mode[key] is not None:
            contributors.append({"id": d["id"], "i_ua": float(by_mode[key]), "source": f"device {d['id']} i_ua_by_mode[{mode}]"})
        elif key in ("active", "typical") and d.get("i_typ_ua") is not None:
            contributors.append({"id": d["id"], "i_ua": float(d["i_typ_ua"]), "source": f"device {d['id']} i_typ_ua"})
        else:
            unknown.append({"id": d["id"], "reason": f"no current given for mode {mode!r}"})
    reqs = _power_reqs(state, mode)
    budgets = [float(r["budget_ua"]) for r in reqs if _usable_budget(r.get("budget_ua"))]
    invalid = [str(r.get("id")) for r in reqs if not _usable_budget(r.get("budget_ua"))]             # thiếu / sai kiểu: không đoán, không ném
    budget = min(budgets) if budgets else None
    known = math.fsum(c["i_ua"] for c in contributors)
    if budget is not None and known > budget + EPS:
        status = "exceeded"
    elif unknown or (budget is None and invalid):
        status = "unknown"
    else:
        status = "no_budget" if budget is None else "ok"
    return {"mode": mode, "budget_ua": budget, "contributors": contributors, "known_total_ua": known, "total_ua": None if unknown else known,
            "unknown_contributors": [u["id"] for u in unknown], "unknown_reasons": unknown, "invalid_budget_requirements": invalid, "status": status}


# ------------------------------------------------------------------------------------------------ các luật
def _item(rule: str, code: str, severity: str, message: str, **extra) -> dict:
    return {"rule": rule, "code": code, "severity": severity, "message": message, **extra}


def _chip_of(state: dict) -> str | None:
    return state["targets"][0]["chip"] if state["targets"] else None


def _package_of(state: dict, chip: str | None) -> str | None:
    return next((t.get("package") for t in state["targets"] if t["chip"] == chip), None)


def rule_pin_01(state: dict, cat: Catalog) -> list[dict]:
    out: list[dict] = []
    req_ids = [r["id"] for r in state["requirements"]]
    claims: dict[str, list[dict]] = {}
    for pin, rec in state["pins"].items():
        owner = _claimant(rec["owner"], req_ids)
        shared = bool(rec["shared_with"])
        claims.setdefault(pin, []).append({"claimant": owner, "signal": rec["signal"], "shared": shared, "source": "allocation"})
        for other in rec["shared_with"]:
            claims[pin].append({"claimant": _claimant(other, req_ids), "signal": rec["signal"], "shared": True, "source": "allocation"})
        if shared and not BUS_SIGNAL.match(rec["signal"]):
            out.append(_item("DRC-PIN-01", f"PIN_CONFLICT:{pin}", "error",
                             f"{pin} is shared by {', '.join([rec['owner'], *rec['shared_with']])} but {rec['signal']} is not a declared shared bus signal (I2C/SPI/CAN/1-Wire)",
                             pin=pin, claims=[{"claimant": c["claimant"], "signal": c["signal"]} for c in claims[pin]]))
    for r in state["requirements"]:
        for pr in req_pin_roles(r, _chips(state)):
            claims.setdefault(pr["pin"], []).append({"claimant": r["id"], "signal": pr["signal"] or pr["role"], "shared": bool(r.get("shared")), "source": "requirement"})
    flagged = {v["pin"] for v in out}
    for pin, cl in claims.items():
        if pin in flagged:
            continue
        distinct = {c["claimant"] for c in cl}
        if len(distinct) <= 1 or all(c["shared"] for c in cl):
            continue
        uniq = []
        for c in cl:
            if not any(u["claimant"] == c["claimant"] for u in uniq):
                uniq.append({"claimant": c["claimant"], "signal": c["signal"]})
        out.append(_item("DRC-PIN-01", f"PIN_CONFLICT:{pin}", "error",
                         f"{pin} is claimed by {' and '.join(u['claimant'] for u in uniq)} ({', '.join(str(u['signal']) for u in uniq)}); a pin can have only one owner unless it is a declared shared bus",
                         pin=pin, claims=uniq))
    return out


def _alt_message(chip: str, signal: str, pin: str, alts: list[dict]) -> str:
    return (f"{signal} is not in the alternate-function table of {pin}; free pins that carry it: " + ", ".join(f"{a['pin']} (AF{a['af']})" for a in alts)) if alts else \
        f"{signal} is not in the alternate-function table of {pin} and no free pin carries it"


def _check_pin_signal(cat: Catalog, chip: str, package: str | None, state: dict, pin: str, signal: str | None, who: str) -> list[dict]:
    rec = cat.pin(chip, pin)
    if rec is None:
        sug = [s for s in (cat.hw.query_pin_alternate_function(chip, pin).get("suggestions") or [])]
        return [_item("DRC-PIN-02", f"NO_SUCH_PIN:{pin}", "error", f"{chip} has no pin {pin!r} ({who})", pin=pin, suggestions=sug)]
    if cat.in_package(rec, package) is False:
        return [_item("DRC-PIN-02", f"PIN_NOT_IN_PACKAGE:{rec['pin']}", "error", f"{rec['pin']} is not bonded out in package {package} ({who})", pin=rec["pin"], package=package)]
    if signal and cat.signal_af(chip, rec, signal) is None:
        alts = cat.alternatives(chip, signal, package, taken=state["pins"])
        return [_item("DRC-PIN-02", f"NO_SUCH_AF:{rec['pin']}", "error", _alt_message(chip, signal, rec["pin"], alts) + f" ({who})",
                      pin=rec["pin"], signal=signal, alternatives=alts, evidence=[{"doc": rec.get("doc"), "page": rec.get("page")}])]
    return []


def rule_pin_02(state: dict, cat: Catalog) -> list[dict]:
    out: list[dict] = []
    if not state["targets"] and (state["pins"] or any(req_pin_roles(r) for r in state["requirements"])):
        return [_item("DRC-PIN-02", "TARGET_NOT_SET", "unknown", "no target chip is set: pins cannot be checked against an alternate-function table")]
    for pin, rec in state["pins"].items():
        chip = cat.chip(rec.get("chip")) or _chip_of(state)
        out += _check_pin_signal(cat, chip, _package_of(state, chip), state, pin, rec["signal"], f"allocated to {rec['owner']}")
    chip = _chip_of(state)
    for r in state["requirements"]:
        for pr in req_pin_roles(r, _chips(state)):
            if pr["pin"] in state["pins"] and pr["signal"] is None:
                continue
            for it in _check_pin_signal(cat, chip, _package_of(state, chip), state, pr["pin"], pr["signal"], f"required by {r['id']}"):
                if not any(o["code"] == it["code"] for o in out):
                    out.append(it)
    return out


def rule_pin_03(state: dict, cat: Catalog) -> list[dict]:
    out: list[dict] = []

    def check(chip: str, pin: str, direction: str | None, who: str, signal: str | None):
        rec = cat.pin(chip, pin)
        if rec is None or not rec.get("input_only"):
            return
        if direction in ("out", "inout"):
            out.append(_item("DRC-PIN-03", f"INPUT_ONLY:{rec['pin']}", "error",
                             f"{rec['pin']} is input-only (no output driver) but {who} needs an output function" + (f" ({signal})" if signal else ""),
                             pin=rec["pin"], evidence=[{"doc": f["doc"], "page": f["page"]} for f in rec.get("flags", []) if f["kind"] == "input_only"]))
        elif direction is None and not any(o["code"] == f"INPUT_ONLY_UNVERIFIED:{rec['pin']}" for o in out):
            out.append(_item("DRC-PIN-03", f"INPUT_ONLY_UNVERIFIED:{rec['pin']}", "unknown",
                             f"{rec['pin']} is input-only and the direction of {signal or who} is not known: confirm it is used as an input", pin=rec["pin"]))

    for pin, rec in state["pins"].items():
        chip = cat.chip(rec.get("chip")) or _chip_of(state)
        check(chip, pin, signal_direction(rec["signal"], rec.get("mode")), f"allocation to {rec['owner']}", rec["signal"])
    chip = _chip_of(state)
    for r in state["requirements"]:
        for pr in req_pin_roles(r, _chips(state)):
            if chip and pr["pin"] not in state["pins"]:
                check(chip, pr["pin"], pr["direction"], f"requirement {r['id']}", pr["signal"])
    return out


def _clock_target(state: dict):
    return next((t for t in state["targets"] if t["chip"] == "stm32g474"), None)


def rule_clk_01(state: dict, cat: Catalog) -> list[dict]:
    if state["targets"] and _clock_target(state) is None:
        return []                                                         # mô hình cây clock chỉ có cho STM32G474 (D21)
    if state["clock"] is None:
        return [_item("DRC-CLK-01", "CLOCK_NOT_CONFIGURED", "unknown", "no clock configuration has been set (set_clock_config): derived frequencies cannot be checked")]
    try:
        ev = evaluate_clock_config(clock_cfg_of(state["clock"]), cat.hw)
    except ClockConfigError as exc:
        return [_item("DRC-CLK-01", "CLOCK_CONFIG:INVALID", "error", str(exc))]
    return [_item("DRC-CLK-01", v["code"], "error", v["message"], evidence=v["evidence"]) for v in ev["violations"]]


def _used_peripherals(state: dict) -> dict[str, str]:
    used: dict[str, str] = {}
    for name in state["peripherals"]:
        used[name] = "allocated pins"
    for pin in state["pins"]:
        g = _port_gpio(pin)
        if g:
            used.setdefault(g, f"pin {pin}")
    for r in state["requirements"]:
        for key in ("instance", "timer"):
            if _str_or_none(r.get(key)):
                used.setdefault(r[key].strip(), f"requirement {r['id']}")
        for pr in req_pin_roles(r, _chips(state)):
            g = _port_gpio(pr["pin"])
            if g:
                used.setdefault(g, f"requirement {r['id']}")
    return used


def rule_clk_02(state: dict, cat: Catalog) -> list[dict]:
    if state["targets"] and _clock_target(state) is None:
        return []
    out = []
    enabled = (state["clock"] or {}).get("enabled_peripherals")
    for name, why in sorted(_used_peripherals(state).items()):
        if name not in rcc.GATES:
            continue                                                      # RCC, EXTI, IWDG, lõi Cortex-M4: không có bit ENR
        enr, fld = rcc.GATES[name]
        if enabled is None:
            out.append(_item("DRC-CLK-02", f"CLOCK_ENABLE_UNKNOWN:{name}", "unknown",
                             f"{name} is used ({why}) but no list of peripherals with clock enabled has been declared (set_clock_config.enabled_peripherals)"))
        elif name not in enabled:
            out.append(_item("DRC-CLK-02", f"CLOCK_GATE:{name}", "error", f"{name} is used ({why}) but its clock is not enabled: set {enr}.{fld} (RM0440 §7.4)", peripheral=name, register=f"{enr}.{fld}"))
    return out


def rule_elec_01(state: dict, cat: Catalog) -> tuple[list[dict], list[dict]]:
    items, nets = [], []
    for net in state["nets"]:
        ev = evaluate_net(net, state, cat)
        nets.append(ev)
        for iss in ev["issues"]:
            items.append(_item("DRC-ELEC-01", iss["code"], iss["severity"], iss["message"], net=f"{net['from']} -> {net['to']}"))
    return items, nets


def rule_pwr_01(state: dict, cat: Catalog) -> tuple[list[dict], dict]:
    items, power = [], {}
    modes = []
    for r in state["requirements"]:
        if isinstance(r, dict) and r.get("type") == "power" and isinstance(r.get("mode"), str) and r["mode"].strip() and r["mode"] not in modes:
            modes.append(r["mode"])
    for mode in modes:
        p = power_budget(state, mode, cat)
        power[mode] = p
        if p["budget_ua"] is None:
            items.append(_item("DRC-PWR-01", f"POWER_BUDGET_MISSING:{mode}", "unknown",
                               f"power requirement(s) {', '.join(p['invalid_budget_requirements'])} for mode {mode!r} have no usable `budget_ua` (a positive number of microamps): "
                               f"the budget cannot be verified", mode=mode))
        elif p["status"] == "exceeded":
            items.append(_item("DRC-PWR-01", f"POWER_BUDGET:{mode}", "error",
                               f"known current in mode {mode!r} is {p['known_total_ua']:g} uA, above the budget of {p['budget_ua']:g} uA", mode=mode))
        elif p["status"] == "unknown":
            items.append(_item("DRC-PWR-01", f"POWER_UNKNOWN:{mode}", "unknown",
                               f"no current figure for {', '.join(p['unknown_contributors'])} in mode {mode!r}: the {p['budget_ua']:g} uA budget cannot be verified "
                               f"(known so far: {p['known_total_ua']:g} uA)", mode=mode))
    return items, power


def rule_req_01(state: dict, cat: Catalog) -> list[dict]:
    out = []
    for r in state["requirements"]:
        status, rid = r.get("status", "pending"), r.get("id")
        problems = validate_requirement(r)
        if problems:
            out.append(_item("DRC-REQ-01", f"REQ_INVALID:{rid}", "unknown",
                             f"requirement {rid} has unusable fields, so it cannot be checked: " + "; ".join(problems)))
        if status == "satisfied":
            if not r.get("evidence"):
                out.append(_item("DRC-REQ-01", f"REQ_NO_EVIDENCE:{rid}", "warning", f"{rid} is marked satisfied without evidence (e.g. a simulation id)"))
        elif status == "waived":
            if not str(r.get("waiver_reason") or "").strip():
                out.append(_item("DRC-REQ-01", f"REQ_WAIVER_REASON:{rid}", "error", f"{rid} is waived without a reason"))
        elif status in ("pending", "open", "unsatisfied", "failed"):
            out.append(_item("DRC-REQ-01", f"REQ_OPEN:{rid}", "error", f"{rid} is {status}: it must be satisfied or waived (with a reason) before finishing"))
        else:
            out.append(_item("DRC-REQ-01", f"REQ_STATUS_INVALID:{rid}", "error", f"{rid} has status {status!r}; expected pending, satisfied or waived"))
    return out


def run_drc(state: dict, hw) -> dict:
    """Chạy cả 8 luật trên một trạng thái (hàm thuần theo `state` và dữ liệu `hw`). `ok` = không có `error`; `complete` = không có `unknown`."""
    cat = hw if isinstance(hw, Catalog) else Catalog(hw)

    def safe(rule: str, fn, empty=None):
        """Một luật ném ngoại lệ (dữ liệu lạ trong log cũ) KHÔNG làm sập run_drc và KHÔNG được tính là đạt: nó thành mục `unknown`."""
        try:
            return fn(state, cat)
        except Exception as exc:                                                                # noqa: BLE001
            item = _item(rule, f"DRC_INTERNAL_ERROR:{rule}", "unknown", f"rule {rule} could not be evaluated ({type(exc).__name__}: {exc}): its result is unknown, not a pass")
            return ([item], empty) if empty is not None else [item]

    by_rule: dict[str, list[dict]] = {
        "DRC-PIN-01": safe("DRC-PIN-01", rule_pin_01), "DRC-PIN-02": safe("DRC-PIN-02", rule_pin_02), "DRC-PIN-03": safe("DRC-PIN-03", rule_pin_03),
        "DRC-CLK-01": safe("DRC-CLK-01", rule_clk_01), "DRC-CLK-02": safe("DRC-CLK-02", rule_clk_02)}
    by_rule["DRC-ELEC-01"], nets = safe("DRC-ELEC-01", rule_elec_01, [])
    by_rule["DRC-PWR-01"], power = safe("DRC-PWR-01", rule_pwr_01, {})
    by_rule["DRC-REQ-01"] = safe("DRC-REQ-01", rule_req_01)
    summary, violations = {}, []
    for rule in RULES:
        items = by_rule[rule]
        violations += items
        errors, warnings, unknown = (sum(1 for i in items if i["severity"] == s) for s in ("error", "warning", "unknown"))
        status = "fail" if errors else "unknown" if unknown else "warn" if warnings else "pass"
        summary[rule] = {"status": status, "count": len(items), "errors": errors, "warnings": warnings, "unknown": unknown, "title": RULES[rule]}
    return {"project_id": state["project_id"], "version": state["version"], "ok": not any(v["severity"] == "error" for v in violations),
            "complete": not any(v["severity"] == "unknown" for v in violations), "summary": summary, "violations": violations, "nets": nets, "power": power}
