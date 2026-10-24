"""Tự kiểm bản nháp C5 (P5, c5-author) — KHÔNG import repo; chỉ `re`, `json`, `yaml` (đọc file).

    eval/.venv/bin/python plan/drafts/check_c5_draft.py [--verbose]

Kiểm:
  1. Checklist (cài lại độc lập, trung thành với P5_interfaces §3): reference_solution PASS mọi mục; mỗi wrong_variant trượt ĐÚNG tập must_fail.
     `pll` được kiểm theo hai ngữ nghĩa: lời giải tham chiếu phải đạt cả khi grader đòi MỌI bộ (M,N,R) tìm thấy đều đúng; biến thể sai phải trượt cả khi
     grader chỉ cần MỘT bộ đúng — nên kết quả không phụ thuộc cách c5-eval gom các bộ.
  2. Bằng chứng: mọi snippet `contains` có nguyên văn trên trang (so khớp bỏ khoảng trắng, không phân biệt hoa/thường — như eval/tools/verify_tasks.py).
  3. Đề: không chứa giá trị ẩn (value_patterns), có quy ước D20 khi có code; câu trả lời clarify khớp value_patterns; câu hỏi mẫu hợp lý khớp đúng mục hidden_info.
  4. Cấu trúc: split cố định (dev = 002, 005, 008, 011), 6 thiếu / 6 đủ, grader clarify chỉ ở task thiếu thông tin.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRAFT = HERE / "C5_curated_draft.yaml"
PAGES = ROOT / "corpus" / ".cache" / "pages"
VERBOSE = "--verbose" in sys.argv

# Đơn vị: bảng của eval/textnorm.QTY_UNITS (chép tay, không import) + thời gian dài (h/day/month/year) mà c5-author đã đề nghị c5-eval bổ sung.
UNITS = {
    "v": (1.0, "V"), "mv": (1e-3, "V"),
    "a": (1.0, "A"), "ma": (1e-3, "A"), "ua": (1e-6, "A"), "µa": (1e-6, "A"), "μa": (1e-6, "A"), "na": (1e-9, "A"),
    "ghz": (1e9, "Hz"), "mhz": (1e6, "Hz"), "khz": (1e3, "Hz"), "hz": (1.0, "Hz"),
    "bps": (1.0, "bps"), "kbps": (1e3, "bps"), "mbps": (1e6, "bps"), "baud": (1.0, "bps"), "kbaud": (1e3, "bps"), "bd": (1.0, "bps"),
    "s": (1.0, "s"), "ms": (1e-3, "s"), "us": (1e-6, "s"), "µs": (1e-6, "s"),
    "mah": (1e-3, "Ah"), "ah": (1.0, "Ah"),
    # đề nghị bổ sung (năm Julian 365,25 ngày):
    "h": (3600.0, "s"), "hour": (3600.0, "s"), "hours": (3600.0, "s"), "day": (86400.0, "s"), "days": (86400.0, "s"),
    "month": (2629800.0, "s"), "months": (2629800.0, "s"), "year": (31557600.0, "s"), "years": (31557600.0, "s"),
    "yr": (31557600.0, "s"), "yrs": (31557600.0, "s"),
}

FENCE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.S)


def unit(u: str):
    k = (u or "").strip().lower()
    if k not in UNITS:
        raise KeyError(f"unknown unit {u!r}")
    return UNITS[k]


# ----------------------------------------------------------------------------------------------- checklist
def chk_mentions(it, text):
    hits = [p for p in it["any_of"] if re.search(p, text, re.I)]
    return bool(hits), f"matched {hits[:1]}" if hits else "no regex matched"


def chk_forbids(it, text):
    hits = [(p, re.search(p, text, re.I).group(0)) for p in it["patterns"] if re.search(p, text, re.I)]
    return not hits, f"forbidden text {hits[0][1]!r}" if hits else "clean"


def _number(raw: str) -> float:
    """Như checklist._number của c5-eval: '115,200' / '16 000' / '16\u202f000' là phân cách hàng nghìn, '2,5' là thập phân."""
    t = raw.strip().rstrip(",").replace("_", "").replace(" ", "").replace("\u202f", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    return float(t.replace(",", "."))


def chk_quantity(it, text):
    vals = []
    for p in it["patterns"]:
        for m in re.finditer(p, text, re.I):
            u = m.groupdict().get("u") or it.get("unit")
            scale, base = unit(u)
            v = _number(m.group("v")) * scale
            if "unit_out" in it:
                s_out, b_out = unit(it["unit_out"])
                assert b_out == base, (it["id"], u, it["unit_out"])
                v = v / s_out
            vals.append(round(v, 6))
    lo, hi = it.get("min", float("-inf")), it.get("max", float("inf"))
    ok_vals = [v for v in vals if lo <= v <= hi]
    if not vals:
        return (not it.get("required", True)), "no match"
    if it.get("match", "all") == "any":
        return bool(ok_vals), f"values {vals}"
    return len(ok_vals) == len(vals), f"values {vals}"


PLL_TXT = {"M": r"\bPLLM\s*(?:=|:|is)\s*/?\s*(\d+)\b", "N": r"\bPLLN\s*(?:=|:|is)\s*[x×]?\s*(\d+)\b", "R": r"\bPLLR\s*(?:=|:|is)\s*/?\s*(\d+)\b"}


def pll_triples(text):
    """[(nguồn cấu hình, M, N, R, nguồn PLL 'HSE'|'HSI16'|None)] từ văn xuôi và từ lệnh ghi RCC->PLLCFGR trong code."""
    prose = FENCE.sub(" ", text)
    code = "\n".join(m.group(0) for m in FENCE.finditer(text))
    out = []
    t = {k: [int(x) for x in re.findall(rx, prose, re.I)] for k, rx in PLL_TXT.items()}
    src = re.findall(r"\bPLLSRC\s*(?:=|:|is|to)?\s*(HSE|HSI(?:16)?)\b", prose, re.I)
    if t["M"] and t["N"] and t["R"]:
        out.append(("text", t["M"][0], t["N"][0], t["R"][0], ("HSE" if src[-1].upper() == "HSE" else "HSI16") if src else None))
    for stmt in re.findall(r"RCC->PLLCFGR\s*=[^;]*;", code):
        m = re.search(r"(\d+)U?\s*<<\s*RCC_PLLCFGR_PLLM_Pos", stmt)
        n = re.search(r"(\d+)U?\s*<<\s*RCC_PLLCFGR_PLLN_Pos", stmt)
        r = re.search(r"(\d+)U?\s*<<\s*RCC_PLLCFGR_PLLR_Pos", stmt)
        s = "HSE" if "PLLSRC_HSE" in stmt else "HSI16" if "PLLSRC_HSI" in stmt else None
        if m and n:
            out.append(("code", int(m.group(1)) + 1, int(n.group(1)), 2 * (int(r.group(1)) + 1) if r else 2, s))
    return out


def pll_ok(it, m, n, r, src):
    f_in = it["hse_hz"] / m
    vco = f_in * n
    f = vco / r
    tol = it.get("tol_pct", 0.1)
    src_ok = src in (None, it.get("source", "HSE"))     # như c5-eval: nguồn nêu ra phải đúng; khoá `source` (đề nghị) mặc định HSE
    return (src_ok and abs(f - it["sysclk_hz"]) / it["sysclk_hz"] * 100 <= tol and f <= 170e6 and 2.66e6 <= f_in <= 16e6 and 96e6 <= vco <= 344e6), f


def chk_pll(it, text, mode):
    tr = pll_triples(text)
    if not tr:
        return False, "no PLL configuration found"
    res = [(cs, m, n, r, src, *pll_ok(it, m, n, r, src)) for cs, m, n, r, src in tr]
    good = [x for x in res if x[5]]
    desc = "; ".join(f"{s}: {src} M={m} N={n} R={r} -> {f / 1e6:.4g} MHz{' ok' if ok else ' BAD'}" for s, m, n, r, src, ok, f in res)
    return (len(good) == len(res)) if mode == "all" else bool(good), desc


def chk_groups(it, text):
    hit = [i for i, g in enumerate(it["groups"]) if any(re.search(p, text, re.I) for p in g)]
    return len(hit) >= it["min_groups"], f"groups hit {hit}"


BULLET = re.compile(r"^\s*(?:\d+[.)]|[-*•+])\s+\S", re.M)


def chk_bullets(it, text):
    n = len(BULLET.findall(FENCE.sub("", text)))
    return n >= it["count"], f"{n} bullets"


def grade(task, text, pll_mode):
    res = {}
    for it in task["expected"]["checklist"]:
        t = it["type"]
        if t == "mentions":
            res[it["id"]] = chk_mentions(it, text)
        elif t == "forbids":
            res[it["id"]] = chk_forbids(it, text)
        elif t == "quantity":
            res[it["id"]] = chk_quantity(it, text)
        elif t == "pll":
            res[it["id"]] = chk_pll(it, text, pll_mode)
        elif t == "one_of_groups":
            res[it["id"]] = chk_groups(it, text)
        elif t == "bullets_min":
            res[it["id"]] = chk_bullets(it, text)
        else:
            raise ValueError(t)
    return res


# ----------------------------------------------------------------------------------------------- evidence
_page_cache: dict[str, list[str]] = {}


def page(doc, p):
    if doc not in _page_cache:
        _page_cache[doc] = [json.loads(l)["text"] for l in (PAGES / f"{doc}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return _page_cache[doc][p - 1]


def squash(s):
    return re.sub(r"\s+", "", s or "").lower()


# ----------------------------------------------------------------------------------------------- câu hỏi mẫu cho hidden_info
SAMPLE_QUESTIONS = {
    "hse_hz": ["What is the frequency of the HSE crystal on your board?", "Which crystal frequency is fitted on OSC_IN/OSC_OUT?",
               "What XTAL frequency is fitted for the STM32?", "What is the frequency of the external oscillator?",
               "How fast is the main clock source of the STM32: 8 MHz or 25 MHz?", "What frequency is the crystal?",
               "The LSE crystal is 32.768 kHz. Which crystal is fitted on the HSE pins?"],
    "pwm_hz": ["What PWM frequency does the motor driver module require?", "At what switching frequency should the PWM run?",
               "What is the driver's maximum PWM input rate?", "At what frequency should TIM1 run for the driver's input?",
               "Which motor driver module is it (part number)?"],
    "esp_baud": ["What baud rate does the ESP32 bridge firmware use?", "Which UART speed is the ESP32 firmware configured for?",
                 "How fast is the serial link to the ESP32?", "What speed does the bridge firmware's UART run at?",
                 "Which data rate does the UART-to-Wi-Fi bridge expect?"],
    "battery_mah": ["What is the capacity of the battery (mAh)?", "Which battery fits the enclosure?", "Which coin cell or AA size do you use?",
                    "What is the energy storage available, e.g. a CR2477?"],
    "nrf_supply": ["How is the nRF52840 powered: from VDD or from VDDH?", "What I/O voltage does the nRF52840 run at?", "Was REGOUT0 programmed?",
                   "What is the nRF52840's VDD?", "Is the nRF52840 on the same 3.3 V rail as the STM32?"],
    "sensor_io_v": ["What I/O voltage does the breakout use: 1.8 V or 3.3 V?", "What logic level does the sensor breakout run at?",
                    "Does the breakout include a level translator?", "What is the VDD of the accelerometer breakout?", "Is the breakout 3.3 V compatible?"],
    "sleep_budget": ["What is the sleep-current budget for the night phase?", "How much current may the node draw at night?",
                     "What is the target standby current for the whole node?"],
}
UNRELATED_QUESTIONS = ["Which pins are free on the connector?", "Do you want the code to use DMA?", "Should the LED blink when a report is sent?",
                       # câu hỏi khớp nhầm mà review nêu (G12) — không được làm lộ giá trị ẩn nữa
                       "What load capacitance does the 32.768 kHz LSE crystal need?", "Is the 40 MHz crystal already on the ESP32 module?",
                       "Does the motor driver module accept a 3.3 V logic input?", "Should the LDO be fed directly from the battery?",
                       "Is the board powered from USB?", "What supply voltage does the STM32 use?", "Is the debug UART powered from the ST-Link?",
                       "Is the soil sensor's 0.6 µA idle current measured at 3.3 V?", "What is the power budget of the Wi-Fi transmit phase?",
                       "Is the STM32's 3.3 V rail from an LDO or a buck?", "What is the VDD of the STM32 board?"]


PROBES = [
    ("C5-001", "sleep_total", "Overall the node sleeps at about 11.7 µA.", True),
    ("C5-001", "sleep_total", "Sleep budget: 0.655 µA (STM32) + 10 µA (ESP32) + 1 µA (driver) = 11.655 µA in total.", True),
    ("C5-001", "sleep_total", "| **Total** | | **11.7 µA** |", True),
    ("C5-001", "sleep_total", "Total sleep current: 80.5 µA (Stop 1) + 10 µA + 1 µA = 91.5 µA, close to budget.", False),
    ("C5-001", "sleep_total", "Total sleep current ≈ 1.7 µA (STM32 and driver).", False),
    ("C5-001", "pwm_freq", "The motor driver wants a PWM frequency of 16 kHz.", True),
    ("C5-001", "pwm_freq", "A 16 kHz PWM with ARR = 10624.", True),
    ("C5-001", "pwm_freq", "PWM: 20 kHz, 40 % duty.", False),
    ("C5-001", "pll", "M = 6 is not shown here; PLLM = 6, PLLN = 85, PLLR = 2.", True),
    ("C5-001", "pll", "PLLM = 3, PLLN = 85, PLLR = 2 (assuming 12 MHz).", False),
    ("C5-001", "esp_link_compat", "Both sides use 3.3 V logic, so the levels are compatible.", True),
    ("C5-001", "esp_link_compat", "The UART lines can be connected directly.", True),
    ("C5-001", "esp_link_compat", "Add a level shifter between the STM32 and the ESP32.", False),
    ("C5-001", "flash_ws", "Set FLASH->ACR LATENCY to 4 wait states.", True),
    ("C5-001", "flash_ws", "Use 3 wait states.", False),
    ("C5-002", "baud", "The bridge expects 921,600 baud.", True),
    ("C5-002", "baud", "USART2 at 921.6 kbaud (BRR = 184).", True),
    ("C5-002", "baud", "USART2 at 115200 baud (BRR = 1476).", False),
    ("C5-002", "peak_current", "Worst case the rail must supply roughly 271 mA.", True),
    ("C5-002", "peak_current", "That is about 270 mA total during a Wi-Fi burst.", True),
    ("C5-002", "peak_current", "The total current is about 31 mA.", False),
    ("C5-002", "supply_rating", "Replace it with a 1 A LDO.", True),
    ("C5-002", "supply_rating", "Use a buck converter rated for at least 600 mA.", True),
    ("C5-002", "supply_rating", "The 250 mA LDO is sufficient.", False),
    ("C5-003", "lifetime", "Expected battery life is about 2.3 years.", True),
    ("C5-003", "lifetime", "That gives roughly 27.6 months of battery life.", True),
    ("C5-003", "lifetime", "Battery lifetime: 20,170 h (2.3 years).", True),
    ("C5-003", "lifetime", "Battery life is about 11.5 years.", False),
    ("C5-003", "avg_current", "The node draws about 19.8 µA on average.", True),
    ("C5-003", "avg_current", "I_avg = 17.8 µA + 2.05 µA = 19.8 µA", True),
    ("C5-003", "avg_current", "Average current ≈ 8 mA.", False),
    ("C5-003", "trade_offs", "Either use a bigger lithium cell or report less often.", True),
    ("C5-003", "trade_offs", "Increase the wake-up interval to 21 min and shorten the radio-on time.", True),
    ("C5-003", "trade_offs", "Use a bigger cell.", False),
    ("C5-003", "no_false_claim", "The 3-year target is not met.", True),
    ("C5-003", "no_false_claim", "This easily meets the 3-year target.", False),
    ("C5-003", "no_false_claim", "The three-year goal is comfortably met.", False),
    ("C5-004", "level_shifter", "Fit a voltage translator (e.g. TXB0102) between the chips.", True),
    ("C5-004", "level_shifter", "No level shifter is needed.", False),
    ("C5-004", "level_shifter", "The link does not need a level shifter.", False),
    ("C5-004", "level_shifter", "A level shifter isn't required here.", False),
    ("C5-004", "no_direct", "The two chips are directly compatible.", False),
    ("C5-004", "no_direct", "A level shifter is required because the nRF52840 I/O is at 1.8 V.", True),
    ("C5-005", "level_shifter", "Alternatively run the MCU at 1.8 V so both sides match.", True),
    ("C5-005", "level_shifter", "Use a bidirectional translator such as PCA9306.", True),
    ("C5-005", "vih_reason", "1.8 V is below 70 % of VDD (2.31 V).", True),
    ("C5-006", "esp32_off", "Keep the ESP32's EN pin low between reports.", True),
    ("C5-006", "esp32_off", "Switch off the ESP32 with a high-side load switch.", True),
    ("C5-006", "esp32_off", "Put the ESP32 into Deep-sleep (10 µA).", False),
    ("C5-006", "esp32_off", "Use ESP32 Hibernation mode (5 µA).", False),
    ("C5-006", "sleep_total", "Total ≈ 3.3 µA, under the 5 µA budget.", True),
    ("C5-006", "sleep_total", "Total ≈ 7.3 µA with Hibernation.", False),
    ("C5-008", "no_direct_sensor", "The humidity sensor can be wired directly to PC8/PC9.", False),
    ("C5-008", "no_direct_sensor", "The nRF52840 link needs no level shifter. The humidity sensor needs one.", True),
    ("C5-008", "nrf_link_compat", "The nRF52840 link needs no level shifter.", True),
    ("C5-010", "headroom", "VDDH - VDD = 0.7 V, more than the 0.3 V REG0 needs.", True),
    ("C5-011", "esp32_off", "The ESP32 is completely unpowered between reports.", True),
    ("C5-011", "sleep_total", "   - LDO quiescent current: 5 µA\n\n   Total sleep current = 0.655 + 10 + 1.5 + 5 = 17.2 µA", False),
    ("C5-011", "sleep_total", "That is 4.2 µA in total.", True),
    ("C5-012", "standby", "Use Shutdown mode.", False),
    # post-run (dev_baseline_v2): diễn đạt đúng bị trượt trước đây (phải PASS) và đối chứng sai/phủ định (phải FAIL)
    ("C5-002", "esp_link_compat", "Both devices operate on 3.3 V; no translation needed.", True),
    ("C5-011", "esp_link_compat", "UART TX/RX cross-connected (no translation required).", True),
    ("C5-002", "esp_link_compat", "Logic levels match directly.", True),
    ("C5-011", "esp_link_compat", "V_OH,min 2.9 V ≥ V_IH,min 2.475 V (PASS)", True),
    ("C5-002", "esp_link_compat", "| V_OL,max 0.4 V ≤ V_IL,max 0.825 V | ✓ |", True),
    ("C5-002", "esp_link_compat", "Level translation is required between the two chips.", False),
    ("C5-002", "esp_link_compat", "V_OH 1.8 V < V_IH 2.31 V → FAIL", False),
    ("C5-002", "esp_link_compat", "V_OH ≥ V_IH is not OK here, so add a translator.", False),
    ("C5-011", "esp_link_compat", "The logic levels do not match.", False),
    ("C5-002", "peak_current", "STM32 50 mA + sensor 1 mA + ESP32 TX 240 mA = 291 mA.", True),
    ("C5-002", "peak_current", "Worst-case draw: 240 mA to 350 mA+ ≈ 291 mA to 400 mA+ on the 3.3 V rail.", True),
    ("C5-002", "peak_current", "Wi-Fi current peaks reaching 350 to 500 mA are possible.", True),
    ("C5-002", "peak_current", "29.5 mA + 1 mA + 100 mA = 130.5 mA on average.", False),
    ("C5-002", "peak_current", "Average total current is about 130.5 mA.", False),
    ("C5-002", "esp_link_compat", "Margin check: STM32 V OH,min = 2.9 V ≥ ESP32 V IH,min = 2.475 V (PASS)", True),
    ("C5-011", "esp_link_compat", "Low side: V OL,max 0.4 V ≤ V IL,max 0.825 V → OK", True),
    ("C5-011", "esp_link_compat", "Sensor side: V OH 1.8 V < V IH,min 2.31 V (FAIL)", False),
    ("C5-002", "esp_link_compat", "The 3.3 V older revision is OK; V IH is 2.475 V.", False),
    ("C5-002", "peak_current", "Base load is 240 mA + 1 mA = 241 mA, leaving 9 mA of headroom.", False),
    # ---- chuỗi đối kháng của review độc lập (plan/reviews/review_C5.md §1-§2), giữ làm hồi quy
    ("C5-001", "sleep_total", "Node total = 95.5 µA, above the total budget of 50 µA.", False),                      # G1
    ("C5-001", "esp_link_compat", "The STM32 and the ESP32 are not directly compatible, so add a level shifter.", False),  # G2
    ("C5-001", "esp_link_compat", "PA9 is compatible with USART1_TX (AF7).", False),
    ("C5-001", "esp_link_compat", "Connect the 24 MHz crystal directly to PF0/PF1.", False),
    ("C5-001", "esp_link_compat", "Use a direct connection from PA8 to the driver PWM input.", False),
    ("C5-001", "esp_link_compat", "There is no need for level shifting between the two 3.3 V chips.", True),
    ("C5-001", "esp_link_compat", "No translator is required: TX and RX can be tied straight to each other.", True),
    ("C5-001", "pwm_freq", "PWM frequency: 16,000 Hz.", True),                                                     # G9
    ("C5-001", "pwm_freq", "PWM frequency: 16 000 Hz.", True),
    ("C5-001", "pwm_freq", "It needs a 16-kHz PWM signal.", True),
    ("C5-001", "sleep_total", "Total sleep current = 11.7 microamps.", True),
    ("C5-001", "sleep_total", "Total sleep current = 11,660 nA.", True),
    ("C5-001", "sleep_total", "**Total sleep current**\n\n11.7 µA", True),
    ("C5-001", "sleep_total", "Sleep current: 0.66 + 10 + 1 = 11.7 µA.", True),
    ("C5-002", "peak_current", "Using the WROOM module figure, the worst-case total is about 410 mA.", True),
    ("C5-002", "peak_current", "The rail sees 270.5 mA at peak.", True),
    ("C5-002", "no_ldo_ok_claim", "The worst-case peak of 270.5 mA lasts only microseconds, so the 250 mA LDO is adequate.", False),
    # review §7: diễn đạt khác của kết luận sai "LDO 250 mA đủ" (phải trượt) và câu đúng không được bị cấm
    ("C5-002", "no_ldo_ok_claim", "The 250 mA regulator can handle it.", False),
    ("C5-002", "no_ldo_ok_claim", "250 mA is enough for this node.", False),
    ("C5-002", "no_ldo_ok_claim", "The LDO will cope with the peaks.", False),
    ("C5-002", "no_ldo_ok_claim", "There is no need to change the LDO.", False),
    ("C5-002", "no_ldo_ok_claim", "Keeping the 250 mA LDO is acceptable.", False),
    ("C5-002", "no_ldo_ok_claim", "The 250 mA LDO is not adequate.", True),
    ("C5-002", "no_ldo_ok_claim", "250 mA is not enough for the Wi-Fi bursts.", True),
    ("C5-002", "no_ldo_ok_claim", "A 600 mA LDO will easily handle the 270 mA peaks.", True),
    ("C5-002", "no_ldo_ok_claim", "Replace it with a buck converter; the new regulator will supply both the STM32 and the ESP32.", True),
    ("C5-003", "trade_offs", "Use a 650 mAh cell instead of the 400 mAh one; wake up every 21 minutes instead of every 15 minutes; keep each active phase under 1.48 s.", True),
    ("C5-003", "no_false_claim", "A 650 mAh cell meets the 3-year target with a 20 % margin.", True),
    ("C5-003", "not_shutdown", "The STM32 uses Shutdown mode with the RTC on the LSE.", False),
    ("C5-004", "no_direct", "The 3.3 V STM32 and the 1.8 V nRF52840 are not directly compatible, so a translator is required.", True),  # G3
    ("C5-004", "no_direct", "No problem: the pins can simply be tied together.", False),
    ("C5-004", "level_shifter", "The link does not require a level shifter.", False),                                 # G4
    ("C5-004", "level_shifter", "Instead of a level shifter, a 1 kOhm series resistor on TX is enough.", False),
    ("C5-004", "level_shifter", "We can skip the level translator.", False),
    ("C5-004", "level_shifter", "Fit an NTS0104 (dual-supply translating transceiver) between the chips.", True),
    ("C5-005", "no_direct", "The breakout is not fully compatible with 3.3 V logic.", True),
    ("C5-005", "level_shifter", "Fit a level-translating I2C buffer such as the TCA9406.", True),
    ("C5-006", "sleep_total", "Total = 5.0 µA, exactly at the 5 µA budget.", False),
    ("C5-008", "no_direct_sensor", "Unlike the humidity sensor, the nRF52840 can be connected directly because both run at 3.3 V.", True),  # G5
    ("C5-008", "no_direct_sensor", "The nRF52840 UART is directly compatible, while the humidity sensor needs a PCA9306.", True),
    ("C5-009", "trade_offs", "Use a 3600 mAh cell instead of the 2600 mAh one, or wake up every 12 minutes instead of every 10 minutes.", True),
    ("C5-009", "no_false_claim", "A 3600 mAh cell meets the 12-year target.", True),
    ("C5-010", "headroom", "That is a problem because the 3.3 V STM32 output exceeds VDD + 0.3 V.", False),          # G10
    ("C5-011", "no_direct_sensor", "The ESP32 link is directly compatible; the gas sensor on I2C1 needs a level shifter.", True),
    ("C5-011", "no_boost_claim", "160 MHz runs in Range 1 normal mode; boost mode is not required.", False),
    ("C5-011", "esp32_off", "We do not power-gate the ESP32 and keep it in Deep-sleep.", False),
    ("C5-011", "esp32_off", "Its EN pin keeps the usual 10 kΩ / 1 µF RC delay.", False),
    ("C5-012", "sleep_total", "STM32 idle current = 0.13 + 0.305 = 0.44 µA", True),
    ("C5-012", "no_direct", "Only if REGOUT0 were programmed to 3.3 V would the two chips be fully compatible.", True),
    ("C5-012", "sleep_total", "STM32 idle: 0.13 µA + 0.305 µA = 0.435 µA in total.", True),
]


FULL_PROBES = [
    ("C5-001", "stop1_over_budget", [], "\nStandby would lose the clock configuration, so Stop 1 is kept; the total must stay below 50 µA.\n", {"sleep_total"}),
    ("C5-002", "ldo_judged_adequate", [], "\nThe ESP32 datasheet recommends at least 500 mA, but the worst-case peak of 270.5 mA lasts only microseconds, so the 250 mA LDO is adequate.\n",
     {"no_ldo_ok_claim"}),
    ("C5-003", "ref", [("Standby with the RTC on the LSE crystal draws 0.655 µA typical at 3 V (DS12288 Table 32) and keeps the brown-out reset active, which matters on a battery (the BOR is not available in Shutdown).",
                        "The STM32 uses Shutdown mode with the RTC on the LSE crystal: 0.565 µA typical at 3 V (DS12288 Table 33)."),
                       ("STM32G474, Standby + RTC (LSE): 0.655 µA", "STM32G474, Shutdown + RTC (LSE): 0.565 µA"),
                       ("Total sleep current = 0.655 + 0.40 + 1 = 2.06 µA.", "Total sleep current = 0.565 + 0.40 + 1 = 1.97 µA.")], "", {"not_shutdown"}),
    ("C5-006", "ref", [("   - ESP32, power off (CHIP_PU low): 1 µA", "   - ESP32 behind a high-side load switch: about 0.01 µA (switch leakage)"),
                       ("Total sleep current = 0.655 + 1 + 0.6 + 1 = 3.26 µA", "Total sleep current = 0.655 + 0.01 + 0.6 + 1 = 2.27 µA")], "", "pass"),
    ("C5-007", "ref", [("so the STM32 uses Standby mode with the RTC on the LSI and the RTC wake-up timer set to 300 s. Shutdown is not an option here: it switches the LSI off and there is no LSE crystal to keep the RTC running. Standby with the RTC on the LSI draws 0.885 µA typical at 3 V (Table 32).",
                        "so the STM32 uses Shutdown mode with the RTC on the LSI and the RTC wake-up timer set to 300 s (0.565 µA)."),
                       ("STM32G474, Standby + RTC (LSI): 0.885 µA", "STM32G474, Shutdown + RTC (LSI): 0.565 µA"),
                       ("Total sleep current = 0.885 + 10 + 2 = 12.9 µA", "Total sleep current = 0.565 + 10 + 2 = 12.6 µA"),
                       ("Standby loses the clock configuration", "Shutdown loses the clock configuration")], "", {"not_shutdown", "low_power_mode"}),
    ("C5-011", "esp32_left_in_deep_sleep", [("slightly above the 8 µA budget but acceptable", "slightly above the total budget of 8 µA")],
     "\nIts EN pin keeps the usual 10 kΩ / 1 µF RC delay.\n", {"esp32_off", "sleep_total"}),
    ("C5-011", "ref", [("   - ESP32, power off (CHIP_PU low): 1 µA", "   - ESP32 behind a high-side load switch: about 0.01 µA"),
                       ("Total sleep current = 0.655 + 1 + 1.5 + 1 = 4.16 µA", "Total sleep current = 0.655 + 0.01 + 1.5 + 1 = 3.17 µA")], "", "pass"),
]


def full_probe_text(task, base, edits, append):
    text = task["provenance"]["reference_solution"]["answer"] if base == "ref" else \
        next(v["answer"] for v in task["provenance"]["wrong_variants"] if v["name"] == base)
    for a, b in edits:
        assert a in text, (task["id"], base, a[:60])
        text = text.replace(a, b)
    return text + append


def _norm(x: str) -> str:
    x = re.sub(r"(?<=\w)['’]s\b", "", str(x or ""))              # bỏ sở hữu cách như eval/sim_human (bản sau review)
    x = re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", x.lower())
    return " " + " ".join(re.sub(r"[\W_]+", " ", x).split()) + " "


def _has_phrase(text_n: str, phrase: str) -> bool:
    ph = _norm(phrase).strip()
    return bool(ph) and any(f" {ph}{suf} " in text_n for suf in ("", "s", "es"))


def matched_ids(task, q):
    """Như SimulatedHuman.match: tách câu theo . ? ! ; + khoảng trắng / xuống dòng; câu có từ khoá và KHÔNG có cụm `exclude` của mục thì khớp."""
    parts = [_norm(x) for x in re.split(r"[.?!;？]+(?=\s|$)|\n+", q or "") if x.strip()]
    return [h["id"] for h in task["hidden_info"]
            if any(any(_has_phrase(pn, k) for k in h["keywords"]) and not any(_has_phrase(pn, x) for x in h.get("exclude") or []) for pn in parts)]


# ----------------------------------------------------------------------------------------------- main
def main() -> int:
    tasks = yaml.safe_load(DRAFT.read_text(encoding="utf-8"))
    problems: list[str] = []
    n_items = n_var = n_snip = 0
    split = {t["id"]: t["split"] for t in tasks}
    if sorted(k for k, v in split.items() if v == "dev") != ["C5-002", "C5-005", "C5-008", "C5-011"]:
        problems.append(f"split: dev set is {sorted(k for k, v in split.items() if v == 'dev')}")
    for t in tasks:
        tid = t["id"]
        missing = int(tid[-3:]) <= 6
        if missing != bool(t["hidden_info"]) or "clarify" not in t["graders"]:
            problems.append(f"{tid}: hidden_info must be non-empty exactly for 001-006 and every C5 task lists the clarify grader (review B1)")
        user = t["turns"][0]["user"]
        # 3. đề
        for h in t["hidden_info"]:
            for vp in h.get("value_patterns", []):
                if re.search(vp, user, re.I):
                    problems.append(f"{tid}: question text leaks hidden {h['id']} ({vp})")
            ans = t["human_policy"]["clarify"].get(h["id"], "")
            if h.get("value_patterns") and not any(re.search(vp, ans, re.I) for vp in h["value_patterns"]):
                problems.append(f"{tid}: clarify answer for {h['id']} does not match its own value_patterns")
            for q in SAMPLE_QUESTIONS[h["id"]]:
                if h["id"] not in matched_ids(t, q):
                    problems.append(f"{tid}: sensible question {q!r} does not match keywords of {h['id']}")
                other = [x for x in matched_ids(t, q) if x != h["id"]]
                if other:
                    problems.append(f"{tid}: question {q!r} for {h['id']} also matches {other}")
        for q in UNRELATED_QUESTIONS:
            if matched_ids(t, q):
                problems.append(f"{tid}: unrelated question {q!r} matches {matched_ids(t, q)}")
        if "functional_sim" in t["graders"]:
            for kw in ("CMSIS", "HAL", "Initial state", "C code block"):
                if kw not in user:
                    problems.append(f"{tid}: code task statement lacks D20 convention keyword {kw!r}")
            if not t["expected"].get("spec"):
                problems.append(f"{tid}: functional_sim without spec")
        # 1. checklist
        ref = t["provenance"]["reference_solution"]["answer"]
        res = grade(t, ref, "all")
        n_items += len(res)
        for k, (ok, why) in res.items():
            if not ok:
                problems.append(f"{tid}: REFERENCE fails {k}: {why}")
            elif VERBOSE:
                print(f"  {tid} ref {k}: {why}")
        nv = len(t["provenance"]["wrong_variants"])
        if nv < (2 if missing else 1):
            problems.append(f"{tid}: only {nv} wrong variants")
        for v in t["provenance"]["wrong_variants"]:
            n_var += 1
            r_any = grade(t, v["answer"], "any")
            r_all = grade(t, v["answer"], "all")
            failed_any = {k for k, (ok, _) in r_any.items() if not ok}
            failed_all = {k for k, (ok, _) in r_all.items() if not ok}
            want = set(v["must_fail"])
            if failed_any != want or failed_all != want:
                problems.append(f"{tid}/{v['name']}: fails {sorted(failed_any)} (pll any) / {sorted(failed_all)} (pll all), must_fail {sorted(want)}; "
                                + "; ".join(f"{k}: {r_any[k][1]}" for k in sorted(failed_any ^ want)))
            elif VERBOSE:
                print(f"  {tid}/{v['name']}: fails exactly {sorted(want)}")
        # 2. bằng chứng
        for e in t["provenance"]["evidence"]:
            txt = squash(page(e["doc_id"], e["page"]))
            for s in e["contains"]:
                n_snip += 1
                if squash(s) not in txt:
                    problems.append(f"{tid}: snippet not on {e['doc_id']} p.{e['page']}: {s!r}")
    by_id = {t["id"]: t for t in tasks}
    for tid, item, text, want in PROBES:
        it = next(i for i in by_id[tid]["expected"]["checklist"] if i["id"] == item)
        got, why = grade({"expected": {"checklist": [it]}}, text, "any")[item]
        if got != want:
            problems.append(f"probe {tid}/{item}: expected {'PASS' if want else 'FAIL'} for {text!r}, got {why}")
    for tid, base, edits, append, want in FULL_PROBES:
        text = full_probe_text(by_id[tid], base, edits, append)
        res = grade(by_id[tid], text, "any")
        failed = {k for k, (ok, _) in res.items() if not ok}
        if (want == "pass" and failed) or (want != "pass" and not set(want) <= failed):
            problems.append(f"full probe {tid}/{base}: failing items {sorted(failed)}, expected {want}")
    print(f"{len(tasks)} tasks, {n_items} checklist items on reference answers, {n_var} wrong variants, {n_snip} evidence snippets checked, "
          f"{len(PROBES)} item probes, {len(FULL_PROBES)} full-answer probes")
    if problems:
        print(f"{len(problems)} PROBLEM(S):")
        for p in problems:
            print("  -", p)
        return 1
    print("0 problems: every reference passes its checklist, every wrong variant fails exactly its must_fail items, all snippets verbatim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
