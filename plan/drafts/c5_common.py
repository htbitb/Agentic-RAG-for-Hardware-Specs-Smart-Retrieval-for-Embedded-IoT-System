"""Phần dùng chung cho bản nháp task C5 (P5, c5-author): quy ước đề (D20), thư viện regex của checklist, mẫu code clock.

Không import repo. Được `build_c5_draft.py` dùng để sinh `C5_curated_draft.yaml`.
"""

AUTHOR = "session P5, subagent c5-author (Claude Opus 5.5); phép tính tay độc lập với simulator/DRC (D19), xem plan/drafts/c5_handcalc.py"

# ------------------------------------------------------------------ quy ước đề (D20, giống C3/C4)
CONV = ("Write bare-metal C for the STM32G474 that accesses registers the CMSIS way (e.g. `TIM1->PSC = ...;`, "
        "`RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;`) using the register and bit names of ST's `stm32g4xx.h` device header. "
        "Do not use HAL or LL drivers, `SystemCoreClock` or any other library function; write clock frequencies as numeric constants. "
        "Do not use interrupts; busy-wait loops on status flags are fine. Initial state: the chip has just come out of reset: "
        "SYSCLK = HCLK = PCLK1 = PCLK2 = 16 MHz (HSI16), all prescalers are 1, no peripheral clock beyond the reset defaults is enabled, "
        "and all GPIO pins are in their reset state.")


def fmt_code(scope: str) -> str:
    return ("Answer with a design plan of at least 5 numbered steps, then one complete C code block (`#include \"stm32g4xx.h\"`, "
            f"then a `main()` that configures everything and finally loops forever with `while (1)`). The code only has to bring up {scope}.")


FMT_PLAN = "Answer with a design plan of at least 5 numbered steps (no code is needed for this part of the project)."

# ------------------------------------------------------------------ checklist: mục dùng lại
# (sau review độc lập plan/reviews/review_C5.md: G1-G7, G9-G12 — các mẫu dưới đây đã được reviewer kiểm trên grader thật)
# Bỏ qua số hạng của một tổng ("10 µA (ESP32) + ...", "8 mA × 2 s") để lấy KẾT QUẢ trên dòng có từ khoá.
_SKIP = r"(?!\s*(?:\([^)\n]*\)\s*)?(?:[+=×/·]|\*\s*\d|x\s))"   # "*" đơn lẻ = chữ đậm markdown, không phải phép nhân
# Số: có phân cách hàng nghìn "11,660" / "16 000" / "16 000" (grader c5-eval bỏ các dấu này khi đổi số) hoặc thập phân.
_NUM = r"(?<![\d.,])(?P<v>\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
CUR_U = r"(?P<u>[µμu]A|nA|mA)\b"
_NEG = r"(?<!not )(?<!n't )(?<!never )(?<!be )"


def steps(count=5):
    return {"id": "steps", "type": "bullets_min", "count": count,
            "desc": f"the design is decomposed into at least {count} numbered or bulleted steps"}


def pll(hse_hz, sysclk_hz, src="HSE"):
    return {"id": "pll", "type": "pll", "hse_hz": int(hse_hz), "sysclk_hz": int(sysclk_hz), "tol_pct": 0.1,
            "desc": f"PLL M/N/R give SYSCLK = {sysclk_hz / 1e6:g} MHz from the {hse_hz / 1e6:g} MHz {src} input (<= 170 MHz)"}


BOOST = {"id": "boost_mode", "type": "mentions", "any_of": [r"R1MODE", r"\bboost\b"],
         "desc": "SYSCLK > 150 MHz: voltage Range 1 boost mode (PWR_CR5.R1MODE = 0) is stated"}

NO_BOOST_CLAIM = {"id": "no_boost_claim", "type": "forbids",
                  "patterns": [r"boost\s+mode\s+(?:is\s+)?(?:not|un)\s?(?:needed|necessary|required)", r"\b(?:no|without)\s+boost\b",
                               r"normal\s+mode\s+is\s+(?:enough|sufficient|fine)"],
                  "desc": "must not claim that SYSCLK > 150 MHz runs without boost mode (G10)"}

FLASH_WS = {"id": "flash_ws", "type": "mentions",
            "any_of": [r"LATENCY_4WS", r"\b4\s*(?:wait[- ]?states?|WS)\b", r"LATENCY\s*(?:=|to|of)\s*4\b", r"\bfour\s+wait[- ]?states?\b"],
            "desc": "Flash LATENCY = 4 wait states for HCLK in (136 or 120 MHz, 170 or 150 MHz] (RM0440 Table 9)"}

LOW_POWER = {"id": "low_power_mode", "type": "mentions", "any_of": [r"\bstandby\b", r"\bshutdown\b"],
             "desc": "the STM32 sleeps in Standby (or Shutdown): Stop 1 alone draws about 80 uA typ (DS12288 Table 30)"}

STANDBY_ONLY = {"id": "low_power_mode", "type": "mentions", "any_of": [r"\bstandby\b"],
                "desc": "the STM32 sleeps in Standby: Stop 1 is about 80 uA typ, and Shutdown is excluded here (no BOR / LSI off in Shutdown, RM0440 p.234, p.251)"}

NOT_SHUTDOWN = {"id": "not_shutdown", "type": "forbids",
                "patterns": [r"(?:uses?|enters?|selects?|chooses?|goes\s+(?:in)?to|put\s+(?:\w+\s+){0,2}in(?:to)?|sleeps?\s+in|waits?\s+in)\s+(?:the\s+)?Shutdown\b",
                             r"\bShutdown\s+(?:mode\s+)?(?:is\s+)?(?:selected|chosen|used)\b", r"STM32\w*,?\s+Shutdown\b"],
                "desc": "Shutdown must not be chosen (it has no BOR and switches the LSI off)"}


def sleep_total(lo_ua, hi_ua, what="whole-node sleep current", extra=()):
    """Tổng dòng ngủ (match any). max đặt RÕ dưới ngân sách để một câu nhắc lại ngân sách không làm đạt mục (G1)."""
    return {"id": "sleep_total", "type": "quantity", "match": "any", "unit": "uA", "unit_out": "uA", "min": lo_ua, "max": hi_ua,
            "patterns": [r"\b(?:total|sum|overall|altogether|combined)\b[^\n]{0,200}?" + _NUM + r"\s*" + CUR_U + _SKIP,
                         _NUM + r"\s*" + CUR_U + r"[ \t]+(?:in[ \t]+)?(?:total|overall|altogether|combined)\b",
                         # giá trị ở đầu dòng kế tiếp ("**Total sleep current**\n\n11.7 µA")
                         r"\b(?:total|sum|overall)\b[^\n]{0,80}\n[ \t]*\n?[ \t]*(?:[-*>|][ \t]*)?(?:\*\*)?" + _NUM + r"\s*" + CUR_U,
                         # "Sleep current: 0.66 + 10 + 1 = 11.7 µA" (kết quả sau dấu '=' cuối)
                         r"\bsleep[- ]current\s*[:=][^\n]{0,160}?=\s*(?:about\s+|~\s*|≈\s*)?" + _NUM + r"\s*" + CUR_U + _SKIP,
                         # "= 11.7 microamps" (không có nhóm đơn vị: dùng `unit`)
                         r"\b(?:total|sum|overall)\b[^\n]{0,200}?" + _NUM + r"\s*micro-?amps?\b",
                         *extra],
            "desc": f"the {what} is stated and lies in [{lo_ua}, {hi_ua}] uA"}


IDLE_CURRENT_RX = r"\bidle\s+current\b[^\n]{0,120}?" + _NUM + r"\s*" + CUR_U + _SKIP

# Câu phủ định / né tránh ("no level shifter is needed", "instead of a level shifter", "skip the level translator") KHÔNG tính là nêu level shifter (G4).
_NEG_BEFORE = "".join(f"(?<!{x})" for x in (r"\bno ", r"\bwithout ", r"\bwithout a ", r"\bwithout any ", r"\bneed for a ", r"\bneed for any ",
                                              r"\bnot need a ", r"n't need a ", r"\bnot need any ", r"n't need any ", r"\brequire a ", r"\brequires a ",
                                              r"\binstead of a ", r"\binstead of the ", r"\bskip the ", r"\bskip a ", r"\bavoid a ", r"\bavoid the ",
                                              r"\bomit the ", r"\bdrop the "))
_NEG_AFTER = (r"(?!\s+(?:is|are|would\s+be|isn't|aren't)\s+(?:not\s+|un)?(?:needed|necessary|required|overkill|unnecessary))"
              r"(?!\s+(?:isn't|aren't)\s+(?:needed|necessary|required))")
LEVEL_SHIFTER_RX = [_NEG_BEFORE + r"level[- ]?(?:shifter|shifting|translator|translation|translating|converter)s?\b" + _NEG_AFTER,
                    _NEG_BEFORE + r"(?:voltage|logic)[- ](?:level[- ])?(?:translator|translation|translating|shifter|converter)s?\b" + _NEG_AFTER,
                    r"(?:dual[- ]supply|bidirectional|I2C)\s+(?:\w+\s+)?(?:voltage\s+)?(?:translator|transceiver|translating)",
                    r"\b(?:PCA9306|TXS010\d|TXB010\d|TXB0108|TXS0108|LSF0\d{3}|PCA9517|TCA9406|TCA9517|NTS01\d\d|NTB01\d\d|TXU0\d{3}|FXMA\d+|"
                    r"SN74(?:LVC|AVC|AXC|AUP|LV)\w*T\d+|74(?:LVC|AVC|AXC|AUP)\w*T\d+|BSS138)\b"]

# Link 3,3 V <-> 3,3 V "tương thích, nối thẳng" (G2): không còn mẫu từ khoá trần ('is compatible', 'connect ... directly', 'direct connection').
COMPAT_RX = [r"\bno\s+(?:need\s+for\s+(?:a\s+|any\s+)?)?level[- ]?(?:shifter|shifting|translat\w*)",
             r"\bno\s+(?:level\s+)?(?:translator|shifter)s?\s+(?:is\s+|are\s+)?(?:needed|required|necessary)",
             r"without\s+(?:a\s+|any\s+)?(?:level[- ]?(?:shifter|shifting|translat\w*)|translator|extra\s+parts)",
             r"level[- ]?(?:shifter|shifting|translat\w*)\s+(?:is\s+|are\s+)?(?:not|un)\s?(?:needed|necessary|required)",
             _NEG + r"(?:directly|fully|electrically)\s+compatible",
             r"(?:logic|voltage|I/O|signal)\s+levels?\s+(?:are\s+|is\s+)?(?:fully\s+|directly\s+)?compatible",
             r"compatible\s+(?:logic|voltage|I/O|signal)\s+levels?",
             r"\blevels\s+are\s+(?:fully\s+|directly\s+)?compatible\b",
             r"\b(?:TX|RX|UART|USART\d?|lines?|signals?|links?|chips|both)\b[^\n.]{0,40}(?:connected|wired|tied|joined)\s+(?:directly|straight|together)"]

# Khẳng định nguy hiểm "không cần level shifter / nối thẳng" (G3: có chặn phủ định "not directly compatible").
NO_SHIFTER_CLAIM_RX = [r"\bno\s+level[- ]?(?:shifter|shifting|translat\w*)\s+(?:is\s+|are\s+)?(?:needed|required|necessary)",
                       r"level[- ]?(?:shifter|shifting|translat\w*)\s+(?:is\s+|are\s+)?(?:not|un)\s?(?:needed|necessary|required)",
                       _NEG + r"(?:directly|fully)\s+compatible",
                       r"can\s+(?:be\s+)?(?:connected|wired|tied)\s+(?:directly|together|straight)",
                       r"(?<!not )(?:tie|tied|join|joined)\s+(?:\w+\s+){0,3}(?:together|directly|straight)"]


# Bổ sung sau lượt chạy dev_baseline_v2 (post-run, chỉ cho esp_link_compat): quy tắc chung, không chép chuỗi trả lời —
# (1) đồng nghĩa translation/conversion, (2) "levels match", (3) dòng so ngưỡng có VOH/VOL và VIH/VIL, dấu so sánh và kết luận PASS/OK/✓ (không FAIL/không phủ định).
ESP_COMPAT_EXTRA = [
    r"\bno\s+(?:level[- ]?|voltage[- ]?|logic[- ]?)?(?:translation|shifting|conversion)\s+(?:is\s+|are\s+)?(?:needed|required|necessary)",
    r"\bwithout\s+(?:any\s+)?(?:level[- ]?|voltage[- ]?|logic[- ]?)?(?:translation|conversion)\b",
    r"(?:level[- ]?|voltage[- ]?|logic[- ]?)?(?:translation|conversion)\s+(?:is\s+|are\s+)?(?:not|un)\s?(?:needed|necessary|required)",
    r"\blevels?\s+(?:match|are\s+(?:matched|identical|the\s+same))\b",
    r"(?![^\n]*(?:\bFAIL|✗|❌|\bnot\s+(?:OK|met|satisfied|pass)))(?=[^\n]*\bV[ _]?\{?O[HL]\b)(?=[^\n]*\bV[ _]?\{?I[HL]\b)[^\n]*?(?:≥|>=|≤|<=|>|<)[^\n]*?"
    r"(?:\bPASS(?:ES|ED)?\b|\bOK\b|✓|✔|✅|\bsatisf(?:ied|ies|y)\b)",
]


def compat(item_id, link, extra=()):
    return {"id": item_id, "type": "mentions", "any_of": COMPAT_RX + list(extra),
            "desc": f"the {link} is stated to be directly compatible (both sides at 3.3 V, no level shifter needed)"}


def level_shifter(item_id, link, extra=()):
    return {"id": item_id, "type": "mentions", "any_of": LEVEL_SHIFTER_RX + list(extra),
            "desc": f"a level shifter / translator is required on the {link}"}


def no_direct_generic(item_id, link):
    return {"id": item_id, "type": "forbids", "patterns": NO_SHIFTER_CLAIM_RX,
            "desc": f"must not claim that the {link} works without level shifting / can be wired directly"}


def no_direct_near(item_id, words, link):
    """Cấm câu 'nối thẳng / không cần level shifter' trong CÙNG MỆNH ĐỀ với thiết bị lệch áp (G5: không vượt , ; : .)."""
    w = "(?:" + "|".join(words) + ")"
    claim = (r"(?:\bno\s+level[- ]?shift\w*|connect\w*\s+directly|directly\s+connect\w*|wired?\s+directly|tied?\s+(?:directly|straight|together)|"
             + _NEG + r"(?:directly|fully)\s+compatible|level[- ]?shift\w*\s+(?:is\s+)?(?:not|un)\s?(?:needed|necessary|required))")
    return {"id": item_id, "type": "forbids",
            "patterns": [w + r"[^\n.,;:]{0,60}" + claim, claim + r"[^\n.,;:]{0,60}" + w],
            "desc": f"must not claim that the {link} can be wired directly / needs no level shifter"}


ESP32_OFF = {"id": "esp32_off", "type": "mentions",
             "any_of": [r"CHIP_PU", r"load[- ]switch", r"(?<!not )(?<!n't )(?<!no )power[- ]?(?:gate|gating|switch)", r"high[- ]side\s+switch",
                        r"P-?(?:channel\s+)?MOSFET", r"cut\w*\s+(?:off\s+)?(?:the\s+|its\s+)?(?:ESP32\W+)?(?:power|supply)",
                        r"(?<!not )(?<!never )\bpower(?:ed)?[- ]off\b",
                        r"\bEN\b\s*(?:pin\s*)?(?:held\s+|kept\s+|pulled\s+|driven\s+)?low",
                        r"(?<!not )(?<!n't )(?:disable|turn(?:ed)?\s+off|switch(?:ed)?\s+off|shut(?:s|ting)?\s*down|unpower)\w*\s+(?:the\s+)?ESP32",
                        r"ESP32\s+(?:is\s+|stays\s+|remains\s+)?(?:completely\s+|fully\s+)?(?:off|unpowered|powered\s+down)\b"],
             "desc": "the ESP32 is switched completely off in sleep (CHIP_PU low, 1 uA, or a load switch): Deep-sleep 10 uA / Hibernation 5 uA break the budget"}

HEADROOM = {"id": "headroom", "type": "mentions",
            "any_of": [r"(?:VDDH|4(?:\.0)?\s*V\s+(?:rail|supply))[^\n]{0,80}(?:0\.[37]\s*V|headroom|dropout)",
                       r"(?:headroom|dropout)[^\n]{0,80}(?:VDDH|4(?:\.0)?\s*V|0\.[37]\s*V)", r"VDDH\s*(?:>=|≥|-|−)"],
            "desc": "REGOUT0 = 3.3 V is valid because VDDH (4.0 V) exceeds VDD by at least the 0.3 V REG0 requirement"}


def no_false_claim(years_rx, years_txt):
    return {"id": "no_false_claim", "type": "forbids",
            "patterns": [r"(?<!not )(?<!n't )\b(?:this|it|the\s+(?:design|node|logger|system|current\s+design))\s+(?:easily\s+|comfortably\s+)?"
                         r"(?:meets|achieves|exceeds|satisfies|fulfils|fulfills)\s+(?:the\s+)?" + years_rx + r"[- ]years?",
                         r"(?m)^(?:(?!\b(?:with|if|by|using|after|once|would)\b)[^\n])*?\b" + years_rx
                         + r"[- ]years?\s+(?:target|goal|requirement)\s+(?:is|are)\s+(?:easily\s+|comfortably\s+)?(?:met|achieved|reached|satisfied)"],
            "desc": f"must not claim that the current design meets the {years_txt}-year target (G7: remedies may say so)"}


def trade_offs(years_txt):
    return {"id": "trade_offs", "type": "one_of_groups", "min_groups": 2,
            "groups": [[r"(?:larger|bigger|higher[- ]capacity|more)\s+(?:\w+\s+)?(?:battery|cell|capacity|pack)",
                        r"(?:at least|minimum(?:\s+of)?|≥|>=)\s*\d{3,4}\s*mAh", r"(?:switch|move|go|upgrade)\s+to\s+(?:a\s+)?(?:larger|bigger)",
                        r"(?:use|fit|switch\s+to|move\s+to|choose|replace\s+\w+(?:\s+\w+){0,4}\s+with)\s+(?:a\s+|an\s+|the\s+)?\d{3,5}\s*mAh",
                        r"\d{3,5}\s*mAh\s+(?:cell|battery|pack)\s+instead"],
                       [r"(?:longer|increase\w*|extend\w*|stretch\w*|lengthen\w*)\s+(?:the\s+)?(?:wake[- ]?up\s+|reporting\s+|report\s+|measurement\s+|logging\s+|sampling\s+)?(?:interval|period)",
                        r"(?:less|fewer)\s+(?:frequent|often)", r"(?:interval|period)\s+(?:of\s+)?(?:at least|≥|>=)", r"(?:report|wake|measure|sample)\w*\s+less\s+often",
                        r"\bevery\s+\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|s|seconds?|h|hours?)\s+instead\b",
                        r"wak\w*\s+(?:up\s+)?(?:only\s+)?every\s+\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|s|seconds?)\b"],
                       [r"(?:shorter|shorten\w*|reduc\w*|lower\w*|cut\w*)\s+(?:the\s+)?(?:active|awake|wake[- ]?up|radio|transmit|TX|BLE)(?:[- ]on)?[- ]?(?:time|phase|current|duration|window|power)",
                        r"lower\s+(?:BLE\s+)?TX\s+power",
                        r"(?:active|awake)\s+(?:phase|time|window)s?\s+(?:under|below|<|≤|at\s+most|shorter\s+than)",
                        r"keep\s+(?:each\s+|the\s+)?active\s+phases?\s+(?:under|below|shorter)"]],
            "desc": f"the {years_txt}-year target is missed, so at least two remedies are offered (bigger battery / longer interval / shorter active phase)"}


# ------------------------------------------------------------------ hidden_info dùng lại
# G12 + §7: 'crystal' trần được giữ nhưng có `exclude` (câu nhắc LSE / 32,768 kHz / ESP32 không khớp mục HSE).
HSE_KEYWORDS = ["HSE", "crystal", "XTAL", "quartz", "resonator", "oscillator frequency", "external oscillator", "main oscillator", "clock source",
                "external clock", "OSC_IN", "crystal frequency", "frequency of the crystal", "crystal is fitted", "crystal fitted", "crystal is on the STM32",
                "crystal on the STM32", "crystal on your board", "crystal on the board", "STM32 crystal", "main crystal", "which crystal", "what crystal"]


def hse_hidden(mhz):
    return {"id": "hse_hz", "keywords": HSE_KEYWORDS, "exclude": ["LSE", "32.768", "ESP32"], "required": True,
            "value_patterns": [rf"\b{mhz}\s*MHz\s+(?:HSE|crystal|quartz)", rf"(?:HSE|crystal|quartz)\D{{0,30}}\b{mhz}\s*MHz\b"]}


# ------------------------------------------------------------------ code mẫu
def clock_code_boost(src, f_in_mhz, m, n, target_mhz=170):
    """PLL -> SYSCLK > 150 MHz (boost): R1MODE = 0, 4 WS, bước AHB/2 (RM0440 p.233). src = 'HSE' | 'HSI'."""
    osc = ("    /* HSE crystal */\n    RCC->CR |= RCC_CR_HSEON;\n    while (!(RCC->CR & RCC_CR_HSERDY)) { }\n\n" if src == "HSE" else "")
    return (
        "    /* Range 1 boost mode (SYSCLK > 150 MHz) and 4 Flash wait states before raising the clock */\n"
        "    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;\n"
        "    (void)RCC->APB1ENR1;\n"
        "    PWR->CR5 &= ~PWR_CR5_R1MODE;\n"
        "    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;\n\n"
        + osc +
        f"    /* {f_in_mhz:g} MHz / {m} = {f_in_mhz / m:g} MHz, x {n} = {f_in_mhz / m * n:g} MHz VCO, / 2 = {target_mhz} MHz */\n"
        f"    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_{src} | ({m - 1}U << RCC_PLLCFGR_PLLM_Pos) | ({n}U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;\n"
        "    RCC->CR |= RCC_CR_PLLON;\n"
        "    while (!(RCC->CR & RCC_CR_PLLRDY)) { }\n\n"
        "    /* switch through AHB / 2, back to / 1 after at least 1 us */\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV2;\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;\n"
        "    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }\n"
        "    for (volatile int i = 0; i < 200; i++) { }\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV1;\n")


def clock_code_normal(f_in_mhz, m, n, target_mhz=150):
    """PLL fed by HSE -> SYSCLK <= 150 MHz in Range 1 normal mode (R1MODE stays 1 = reset value), 4 WS.
    HCLK > 80 MHz: chuyển sang PLL qua trạng thái trung gian AHB/2 (RM0440 7.2.7 p.279-280; review C5-010 (b))."""
    return (
        "    /* Range 1 normal mode is the reset state (R1MODE = 1); 150 MHz needs 4 Flash wait states */\n"
        "    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;\n\n"
        "    /* HSE crystal */\n    RCC->CR |= RCC_CR_HSEON;\n    while (!(RCC->CR & RCC_CR_HSERDY)) { }\n\n"
        f"    /* {f_in_mhz:g} MHz / {m} = {f_in_mhz / m:g} MHz, x {n} = {f_in_mhz / m * n:g} MHz VCO, / 2 = {target_mhz} MHz */\n"
        f"    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | ({m - 1}U << RCC_PLLCFGR_PLLM_Pos) | ({n}U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;\n"
        "    RCC->CR |= RCC_CR_PLLON;\n"
        "    while (!(RCC->CR & RCC_CR_PLLRDY)) { }\n\n"
        "    /* HCLK > 80 MHz: switch through the AHB / 2 transition state, back to / 1 after at least 1 us */\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV2;\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;\n"
        "    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) { }\n"
        "    for (volatile int i = 0; i < 200; i++) { }\n"
        "    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV1;\n")


# ------------------------------------------------------------------ bằng chứng dùng chung (snippet nguyên văn; kiểm bằng check_c5_draft.py)
EV = {
    "hse_range": {"doc_id": "STM32G474_Datasheet", "page": 117, "contains": ["The high-speed external (HSE) clock can be supplied with a 4 to 48 MHz crystal/ceramic"]},
    "pll_limits": {"doc_id": "STM32G474_Datasheet", "page": 123, "contains": ["fVCO_OUT PLL VCO output", "Voltage scaling Range 1 96 - 344", "2.66 - 16 MHz"]},
    "pllm": {"doc_id": "STM32G474_RM0440", "page": 293, "contains": ["VCO input frequency = PLL input clock frequency / PLLM with 1 ≤ PLLM ≤ 16",
                                                                   "VCO output frequency = VCO input frequency x PLLN with 8 =< PLLN =< 127",
                                                                   "11: HSE clock selected as PLL clock entry"]},
    "pllm_hsi": {"doc_id": "STM32G474_RM0440", "page": 293, "contains": ["VCO input frequency = PLL input clock frequency / PLLM with 1 ≤ PLLM ≤ 16",
                                                                       "VCO output frequency = VCO input frequency x PLLN with 8 =< PLLN =< 127",
                                                                       "10: HSI16 clock selected as PLL clock entry"]},
    "pllr": {"doc_id": "STM32G474_RM0440", "page": 292, "contains": ["00: PLLR = 2"]},
    "flash_ws": {"doc_id": "STM32G474_RM0440", "page": 98, "contains": ["4 WS (5 CPU cycles) ≤ 170 ≤ 150"]},
    "boost": {"doc_id": "STM32G474_RM0440", "page": 232, "contains": ["System frequency SYSCLK ≤ 150 MHz SYSCLK ≤ 170 MHz", "R1MODE bit configuration 1 0"]},
    "ahb_div2": {"doc_id": "STM32G474_RM0440", "page": 233, "contains": ["The system clock must be divided by 2 using the AHB prescaler before switching"]},
    "brr": {"doc_id": "STM32G474_RM0440", "page": 1708, "contains": ["When OVER8 = 0, BRR = USARTDIV."]},
    "pwm_mode1": {"doc_id": "STM32G474_RM0440", "page": 1179, "contains": ["high as long as TIMx_CNT < TIMx_CCRx"]},
    "i2c_tscl": {"doc_id": "STM32G474_RM0440", "page": 1645, "contains": ["tSCL = tSYNC1 + tSYNC2"]},
    "rrs": {"doc_id": "STM32G474_RM0440", "page": 255, "contains": ["Bit 8 RRS: SRAM2 retention in Standby mode"]},
    "stop1": {"doc_id": "STM32G474_Datasheet", "page": 102, "contains": ["Table 30. Current consumption in Stop 1 mode", "3.0 V 80.5 255 840 1600 2900"]},
    "standby": {"doc_id": "STM32G474_Datasheet", "page": 103, "contains": ["Table 32. Current consumption in Standby mode", "3 V 130 385 1900 4850 12000"]},
    "standby_rtc": {"doc_id": "STM32G474_Datasheet", "page": 104, "contains": ["3 V 885 1150 2650 5550 12500", "3 V 655 915 2100 4550 9850",
                                                                            "3 V 305 865 2950 6150 12500"]},
    "shutdown_lsi_off": {"doc_id": "STM32G474_Datasheet", "page": 25, "contains": ["The PLL, as well as the HSI16 and LSI RC-oscillators and HSE crystal oscillator are"]},
    "ahb_transition": {"doc_id": "STM32G474_RM0440", "page": 279, "contains": ["Switching from HSE or HSI16 to PLL with AHB frequency (HCLK) higher than 80 MHz"]},
    "ahb_transition2": {"doc_id": "STM32G474_RM0440", "page": 280, "contains": ["Set the AHB prescaler HPRE[3:0] bits to divide the system frequency by 2"]},
    "bor_rm": {"doc_id": "STM32G474_RM0440", "page": 234, "contains": ["The BOR is active in all power modes except", "Shutdown mode, and cannot be disabled."]},
    "shutdown_rm": {"doc_id": "STM32G474_RM0440", "page": 251, "contains": ["The PLL, the HSI16, the LSI and the HSE oscillators are also switched off.", "The BOR is not available in Shutdown mode."]},
    "reg0_err": {"doc_id": "nRF52840_PS", "page": 155, "contains": ["REG0 output voltage error (deviation from setting in REGOUT0 on page 63) -10 5 %"]},
    "bor": {"doc_id": "STM32G474_Datasheet", "page": 25, "contains": ["The BOR always remains active in Standby mode.", "The BOR is not available in Shutdown mode."]},
    "vdd_range": {"doc_id": "STM32G474_Datasheet", "page": 84, "contains": ["VDD Standard operating voltage - 1.71"]},
    "run_170": {"doc_id": "STM32G474_Datasheet", "page": 89, "contains": ["170 MHz 29.50 29.5 31 32 34.5"]},
    "stm_vih": {"doc_id": "STM32G474_Datasheet", "page": 128, "contains": ["0.7xVDD", "0.49xVDD +0.26"]},
    "stm_voh": {"doc_id": "STM32G474_Datasheet", "page": 130, "contains": ["Output high level voltage for an I/O pin V DD-0.4"]},
    "pins_pa": {"doc_id": "STM32G474_Datasheet", "page": 73, "contains": []},
    "pins_pb": {"doc_id": "STM32G474_Datasheet", "page": 74, "contains": []},
    "pins_pc": {"doc_id": "STM32G474_Datasheet", "page": 75, "contains": []},
    "osc_pins": {"doc_id": "STM32G474_Datasheet", "page": 50, "contains": ["PF0-OSC_IN", "PF1-OSC_OUT", "PC14-OSC32_IN"]},
    "wkup1": {"doc_id": "STM32G474_Datasheet", "page": 59, "contains": ["RTC_TAMP2,WKUP1"]},
    "esp_modes": {"doc_id": "ESP32_Datasheet", "page": 30, "contains": ["RTC timer + RTC memory 10 µA", "Hibernation RTC timer only 5 µA",
                                                                      "Power off CHIP_PU is set to low level, the chip is powered down. 1 µA"]},
    "esp_dc": {"doc_id": "ESP32_Datasheet", "page": 52, "contains": ["VIH High-level input voltage 0.75 × VDD", "VOH High-level output voltage 0.8 × VDD",
                                                                    "VOL Low-level output voltage — — 0.1 × VDD"]},
    "esp_tx": {"doc_id": "ESP32_Datasheet", "page": 52, "contains": ["Transmit 802.11b, DSSS 1 Mbps, POUT = +19.5 dBm — 240 — mA"]},
    "esp_supply": {"doc_id": "ESP32_Datasheet", "page": 51, "contains": ["Current delivered by external power", "supply 0.5 — — A"]},
    "esp_chip_pu": {"doc_id": "ESP32_Datasheet", "page": 52, "contains": ["Low-level input voltage of CHIP_PU", "to shut down the chip"]},
    "nrf_regout0": {"doc_id": "nRF52840_PS", "page": 63, "contains": ["3V3 5 3.3 V", "DEFAULT 7 Default voltage: 1.8 V"]},
    "nrf_gpio_hv": {"doc_id": "nRF52840_PS", "page": 82, "contains": ["In High Voltage", "mode, it equals the level specified in register REGOUT0"]},
    "nrf_reg0_drop": {"doc_id": "nRF52840_PS", "page": 155, "contains": ["VVDDH-VDD Required difference between input voltage (VDDH) and output voltage (VDD,"]},
    "nrf_gpio": {"doc_id": "nRF52840_PS", "page": 370, "contains": ["VIH Input high voltage 0.7 x VDD VDD V", "VIL Input low voltage VSS 0.3 x VDD V"]},
    "nrf_absmax": {"doc_id": "nRF52840_PS", "page": 972, "contains": ["VI/O, VDD ≤3.6 V -0.3 VDD + 0.3 V"]},
    "nrf_sleep": {"doc_id": "nRF52840_PS", "page": 76, "contains": ["IOFF_RAMOFF_RESET System OFF, no RAM retention, wake on reset 0.40 µA"]},
    "nrf_qfn48": {"doc_id": "nRF52840_PS", "page": 970, "contains": ["VDD and VDDH are short circuited inside the QFN48 package"]},
}


def ev(key, *extra):
    e = dict(EV[key])
    e["contains"] = list(e["contains"]) + list(extra)
    return e
