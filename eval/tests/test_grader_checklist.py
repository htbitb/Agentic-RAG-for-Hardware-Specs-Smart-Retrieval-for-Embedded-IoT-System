"""Grader `checklist` (C5, gate, tất định — plan/P5_interfaces.md §3): mentions, forbids, quantity, pll, one_of_groups, bullets_min.
Có ca âm đối kháng: đúng từ sai số, số sai đơn vị, câu phủ định, cấu hình PLL không khớp HSE, giá trị reset PLLN không được xoá."""
import pytest

from eval.graders import checklist
from eval.schema import Task
from eval.tests.helpers import mk_run


def task(*items):
    return Task(id="C5-900", category="C5", split="dev", turns=[{"user": "q"}], graders=["checklist"], expected={"checklist": list(items)})


def grade(answer, *items):
    return checklist.grade(task(*items), mk_run(answer), None)


def ok(answer, item):
    return grade(answer, item)["details"]["items"][item["id"]]


def M(*any_of, id="m"):
    return {"id": id, "type": "mentions", "desc": "d", "any_of": list(any_of)}


def PLL(hse=8_000_000, sysclk=170_000_000, tol=0.1):
    return {"id": "pll", "type": "pll", "desc": "PLL", "hse_hz": hse, "sysclk_hz": sysclk, "tol_pct": tol}


# ------------------------------------------------------------------ hình dạng kết quả
def test_result_shape_and_reasons_name_the_failing_items():
    r = grade("Use a level shifter.", M("level[- ]shifter", id="ls"), M("wait states?", id="ws"))
    assert r["pass"] is False and r["details"]["items"] == {"ls": True, "ws": False}
    assert len(r["reasons"]) == 1 and r["reasons"][0].startswith("item ws: ")
    assert r["score"] == 0.5


def test_all_items_pass():
    r = grade("Use a level shifter and 4 wait states.", M("level shifter", id="ls"), M("wait states?", id="ws"))
    assert r["pass"] is True and r["reasons"] == [] and r["score"] == 1.0


# ------------------------------------------------------------------ mentions / forbids
def test_mentions_is_case_insensitive_and_looks_inside_code_blocks():
    assert ok("```c\nFLASH->ACR |= flash_acr_latency_4ws;\n```", M("FLASH_ACR_LATENCY_4WS"))
    assert not ok("Set the flash latency.", M("FLASH_ACR_LATENCY_4WS"))


AFFIRMATIVE_LS = r"(?<!not )(?<!n't )(?<!no need to )\b(?:use|add|insert|place|need)\s+(?:an?\s+)?(?:bidirectional\s+)?level[- ]shifter"


@pytest.mark.parametrize("text,expected", [
    ("Use a level shifter (TXS0108E) between the 1.8 V sensor and the MCU.", True),
    ("We add a bidirectional level-shifter on SDA/SCL.", True),
    ("Do not use a level shifter here; the pins are 5 V tolerant.", False),
    ("You don't need a level shifter.", False),
    ("There is no need to add a level shifter.", False),
    ("A level shifter is not required.", False),
])
def test_a_regex_written_to_require_affirmative_phrasing_rejects_negations(text, expected):
    assert ok(text, M(AFFIRMATIVE_LS)) is expected


def test_forbids_fails_on_any_match_and_names_the_pattern():
    item = {"id": "f", "type": "forbids", "desc": "no HSI PLL", "patterns": [r"PLLSRC_HSI\b", r"\bHAL_"]}
    assert ok("RCC_PLLCFGR_PLLSRC_HSE", item)
    r = grade("HAL_RCC_OscConfig(&osc);", item)
    assert r["pass"] is False and "HAL_" in r["reasons"][0]


# ------------------------------------------------------------------ quantity
SLEEP = {"id": "sleep", "type": "quantity", "desc": "sleep current <= 10 uA", "patterns": [r"sleep current[^.\n]{0,30}?(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>[unµμm]A)\b"],
         "unit": "uA", "max": 10e-6}


@pytest.mark.parametrize("text,expected", [
    ("Total sleep current: 2.5 uA.", True),
    ("Total sleep current: 2,5 µA.", True),
    ("Total sleep current is about 2500 nA.", True),
    ("Total sleep current: 9.9 μA", True),
    ("Total sleep current: 2.5 mA.", False),                     # đúng chữ, sai đơn vị
    ("Total sleep current: 12 uA.", False),                      # đúng chữ, sai số
    ("Sleep is fine.", False),                                   # required (mặc định) mà không có giá trị
])
def test_quantity_converts_units_and_checks_the_bounds(text, expected):
    assert ok(text, SLEEP) is expected


def test_quantity_default_unit_unit_out_and_required_false():
    item = {"id": "s", "type": "quantity", "desc": "d", "patterns": [r"SYSCLK\s*=\s*(?P<v>\d+(?:\.\d+)?)"], "unit": "MHz", "unit_out": "MHz", "min": 100, "max": 170}
    assert ok("SYSCLK = 170", item) and not ok("SYSCLK = 180", item) and not ok("SYSCLK = 64", item)
    si = {**item, "unit_out": None, "min": 100e6, "max": 170e6}
    del si["unit_out"]
    assert ok("SYSCLK = 168", si) and not ok("SYSCLK = 171", si)
    opt = {**item, "required": False}
    assert ok("no clock mentioned", opt) and not ok("no clock mentioned", item)


def test_quantity_match_all_versus_any():
    pats = [r"(?P<v>\d+(?:\.\d+)?)\s*(?P<u>mA)\b"]
    all_ = {"id": "i", "type": "quantity", "desc": "d", "patterns": pats, "max": 0.02}
    any_ = {**all_, "match": "any"}
    text = "Idle 5 mA, peak 35 mA."
    assert not ok(text, all_) and ok(text, any_)
    assert ok("Idle 5 mA, peak 15 mA.", all_)


def test_quantity_ignores_a_captured_unit_it_cannot_convert():
    item = {"id": "i", "type": "quantity", "desc": "d", "patterns": [r"(?P<v>\d+)\s*(?P<u>[A-Za-z]+)"], "unit": "mA", "max": 0.02}
    r = grade("It takes 5 cycles.", item)
    assert r["pass"] is False and "no usable value" in r["reasons"][0]
    assert ok("It takes 5 cycles and 3 mA.", item)


def test_quantity_thousands_separators():
    item = {"id": "b", "type": "quantity", "desc": "d", "patterns": [r"baud(?: rate)?\s*(?:of|=|:)?\s*(?P<v>\d[\d,]*)"], "unit": "bps", "min": 115000, "max": 116000}
    assert ok("baud rate = 115,200", item) and not ok("baud rate = 9,600", item)


# ------------------------------------------------------------------ pll: thanh ghi
REF = """```c
RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | (1U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;
```"""


def test_pll_register_write_of_the_reference_passes():
    r = grade(REF, PLL())
    assert r["pass"] is True, r["reasons"]
    d = r["details"]["pll"]["pll"]
    assert d["source"] == "register" and (d["m"], d["n"], d["r"]) == (2, 85, 2) and d["sysclk_hz"] == 170_000_000


@pytest.mark.parametrize("code,why", [
    ("RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | (0U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;", "SYSCLK"),
    ("RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (1U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;", "source"),
    ("RCC->PLLCFGR = (1U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;", "source"),
    ("RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | (1U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | (1U << RCC_PLLCFGR_PLLR_Pos);", "SYSCLK"),
    ("RCC->PLLCFGR = 0x3 | (4U << 4) | (68U << 8);", "SYSCLK"),                         # thạch anh 25 MHz bị đoán: 8/5*68/2 = 54.4 MHz
])
def test_pll_register_configurations_inconsistent_with_the_hse_fail(code, why):
    r = grade(f"```c\n{code}\n```", PLL())
    assert r["pass"] is False and why in r["reasons"][0], r["reasons"]


def test_pll_register_sequence_with_clear_then_set_and_raw_numbers():
    code = """```c
    RCC->PLLCFGR &= ~(RCC_PLLCFGR_PLLSRC | RCC_PLLCFGR_PLLM | RCC_PLLCFGR_PLLN | RCC_PLLCFGR_PLLR);
    RCC->PLLCFGR |= RCC_PLLCFGR_PLLSRC_HSE | ((2 - 1) << 4) | (85UL << 8) | (0 << 25);
    RCC->PLLCFGR |= RCC_PLLCFGR_PLLREN;
    ```"""
    assert grade(code, PLL())["pass"] is True


def test_pll_or_into_the_reset_value_keeps_the_reset_plln_bits():
    """PLLCFGR reset = 0x00001000 (PLLN = 16): `|=` mà không xoá PLLN thì N = 75 | 16 = 91 ⇒ 182 MHz, không phải 150 MHz."""
    set_only = "```c\nRCC->PLLCFGR |= RCC_PLLCFGR_PLLSRC_HSE | (1U << RCC_PLLCFGR_PLLM_Pos) | (75U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;\n```"
    assign = set_only.replace("|=", "=")
    assert grade(assign, PLL(sysclk=150_000_000))["pass"] is True
    r = grade(set_only, PLL(sysclk=150_000_000))
    assert r["pass"] is False and r["details"]["pll"]["pll"]["n"] == 91


def test_pll_cmsis_and_ll_macros_and_local_defines():
    modify = "```c\nMODIFY_REG(RCC->PLLCFGR, RCC_PLLCFGR_PLLSRC | RCC_PLLCFGR_PLLM | RCC_PLLCFGR_PLLN | RCC_PLLCFGR_PLLR,\n" \
             "           RCC_PLLCFGR_PLLSRC_HSE | _VAL2FLD(RCC_PLLCFGR_PLLM, 1U) | _VAL2FLD(RCC_PLLCFGR_PLLN, 85U));\nSET_BIT(RCC->PLLCFGR, RCC_PLLCFGR_PLLREN);\n```"
    assert grade(modify, PLL())["pass"] is True
    defines = "```c\n#define PLL_M 2U\n#define PLL_N 85U\nWRITE_REG(RCC->PLLCFGR, RCC_PLLCFGR_PLLSRC_HSE | ((PLL_M - 1U) << RCC_PLLCFGR_PLLM_Pos) | (PLL_N << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN);\n```"
    assert grade(defines, PLL())["pass"] is True
    readback = "```c\nRCC->PLLCFGR = (RCC->PLLCFGR & ~(RCC_PLLCFGR_PLLM | RCC_PLLCFGR_PLLN | RCC_PLLCFGR_PLLSRC)) | (uint32_t)(RCC_PLLCFGR_PLLSRC_HSE | (1U << 4) | (85U << 8));\n```"
    assert grade(readback, PLL())["pass"] is True


def test_pll_vco_and_field_limits_are_enforced():
    # 8 MHz / 1 × 84 = 672 MHz VCO (> 344) / 4 = 168 MHz: SYSCLK đúng nhưng VCO vượt giới hạn
    r = grade("```c\nRCC->PLLCFGR = 0x3 | (0U << 4) | (84U << 8) | (1U << 25);\n```", PLL(sysclk=168_000_000))
    assert r["pass"] is False and "VCO" in r["reasons"][0]
    # 8 MHz / 4 = 2 MHz đầu vào VCO (< 2.66 MHz)
    r = grade("```c\nRCC->PLLCFGR = 0x3 | (3U << 4) | (127U << 8);\n```", PLL(sysclk=127_000_000))
    assert r["pass"] is False and "input" in r["reasons"][0]


def test_pll_never_passes_above_170_mhz_even_if_the_target_says_so():
    r = grade("PLLM = 1, PLLN = 45, PLLR = 2", PLL(sysclk=180_000_000))
    assert r["pass"] is False and "170" in r["reasons"][0]


# ------------------------------------------------------------------ pll: văn bản / HAL / LL
@pytest.mark.parametrize("text", [
    "PLL settings: PLLM = 2, PLLN = 85, PLLR = 2.",
    "PLLM=/2, PLLN=x85, PLLR=/2",
    "Set PLLM to 2, PLLN to 85 and PLLR to 2.",
    "PLL: M = 2, N = 85, R = 2 (8 MHz / 2 * 85 / 2 = 170 MHz).",
    "PLLR = 0 (/2), PLLM = 2, PLLN = 85",
    "```c\nosc.PLL.PLLSource = RCC_PLLSOURCE_HSE;\nosc.PLL.PLLM = RCC_PLLM_DIV2;\nosc.PLL.PLLN = 85;\nosc.PLL.PLLR = RCC_PLLR_DIV2;\n```",
    "```c\nLL_RCC_PLL_ConfigDomain_SYS(LL_RCC_PLLSOURCE_HSE, LL_RCC_PLLM_DIV_2, 85, LL_RCC_PLLR_DIV_2);\n```",
])
def test_pll_text_hal_and_ll_forms_pass(text):
    r = grade(text, PLL())
    assert r["pass"] is True, (text, r["reasons"])


@pytest.mark.parametrize("text,why", [
    ("With the 8 MHz crystal: PLLM = 4, PLLN = 85, PLLR = 2 gives SYSCLK = 170 MHz.", "SYSCLK"),        # đúng chữ, sai số
    ("PLLM = 1, PLLN = 85, PLLR = 2", "170"),                                                            # 340 MHz
    ("Use PLLM = 2 or PLLM = 5 with PLLN = 85, PLLR = 2.", "ambiguous"),
    ("PLLN = 85 and PLLR = 2.", "PLLM"),
    ("The PLL multiplies the crystal up to 170 MHz.", "no PLL configuration"),
    ("```c\nosc.PLL.PLLSource = RCC_PLLSOURCE_HSI;\nosc.PLL.PLLM = RCC_PLLM_DIV2;\nosc.PLL.PLLN = 85;\nosc.PLL.PLLR = RCC_PLLR_DIV2;\n```", "source"),
    ("PLLN = 85 MHz, PLLM = 2, PLLR = 2", "PLLN"),                                                       # '85 MHz' là tần số, không phải hệ số N
])
def test_pll_text_forms_that_must_fail(text, why):
    r = grade(text, PLL())
    assert r["pass"] is False and why in r["reasons"][0], (text, r["reasons"])


def test_pll_code_is_authoritative_over_prose():
    prose_wrong_code_right = "First I thought PLLM = 1 would do.\n\n" + REF
    assert grade(prose_wrong_code_right, PLL())["pass"] is True
    prose_right_code_wrong = "PLLM = 2, PLLN = 85, PLLR = 2.\n\n" + REF.replace("(1U << RCC_PLLCFGR_PLLM_Pos)", "(4U << RCC_PLLCFGR_PLLM_Pos)")
    assert grade(prose_right_code_wrong, PLL())["pass"] is False


def test_pll_bare_letters_need_a_pll_context_on_the_same_line():
    assert grade("Let M = 2, N = 85, R = 2.", PLL())["pass"] is False
    assert grade("PLL dividers: M = 2, N = 85, R = 2.", PLL())["pass"] is True


def test_pll_with_a_24_mhz_crystal():
    assert grade("PLLM = 6, PLLN = 85, PLLR = 2", PLL(hse=24_000_000))["pass"] is True
    assert grade("PLLM = 2, PLLN = 85, PLLR = 2", PLL(hse=24_000_000))["pass"] is False


def test_pll_macro_table_matches_the_frozen_cmsis_header():
    """Bảng macro RCC_PLLCFGR_* của grader (chép tay từ RM0440 §7.4.4) khớp header đã đóng băng (độc lập nhưng phải trùng)."""
    import importlib
    import re

    from eval import sandbox

    sandbox.load()
    hg = importlib.import_module("hwmodel_vendored.header_gen")
    header = hg.render(hg.build_model())["stm32g474xx.h"]
    defines = dict(re.findall(r"#define\s+(RCC_PLLCFGR_\w+)\s+(.+)", header))
    assert len(defines) > 40
    for name, body in defines.items():
        assert checklist.PLLCFGR_MACROS[name] == checklist.eval_c_expr(body, defines), name
    assert set(defines) <= set(checklist.PLLCFGR_MACROS)
    assert checklist.PLLCFGR_RESET == 0x00001000


# ------------------------------------------------------------------ one_of_groups / bullets_min
def test_one_of_groups_counts_groups_with_a_hit():
    item = {"id": "t", "type": "one_of_groups", "desc": "two options", "groups": [["level shifter", "TXS0108"], ["1\\.8 ?V sensor", "replace the sensor"]], "min_groups": 2}
    assert ok("Option A: TXS0108. Option B: replace the sensor.", item)
    assert not ok("Option A: a level shifter.", item)


@pytest.mark.parametrize("text,count", [
    ("1. a\n2. b\n3) c\n- d\n* e\n• f", 6),
    ("### 1. Clocks\n### 2. GPIO\n**Step 3:** I2C", 3),
    ("Intro\n\n```c\n/*\n * not a step\n * nor this\n */\n- also not\n```\n1. real", 1),
    ("A paragraph with - a dash and 2. a number inside.", 0),
])
def test_bullets_min_counts_numbered_and_bulleted_lines_outside_code(text, count):
    assert checklist.count_steps(text) == count


def test_bullets_min_threshold():
    item = {"id": "b", "type": "bullets_min", "desc": "five steps", "count": 5}
    assert ok("1. a\n2. b\n3. c\n4. d\n5. e", item) and not ok("1. a\n2. b\n3. c\n4. d", item)


def test_the_whole_final_answer_is_used_not_earlier_turns():
    from eval.schema import RunResult, TurnResult
    run = RunResult(system="S0", variant="", task_id="C5-900", seed=0, turns=[TurnResult(answer="level shifter"), TurnResult(answer="final")], final_answer="final")
    assert checklist.grade(task(M("level shifter")), run, None)["pass"] is False


# ------------------------------------------------------------------ P5 bổ sung (yêu cầu của c5-author): nguồn HSI16, đơn vị thời gian dài, '/M = 3'
def test_pll_source_hsi16_item():
    item = {**PLL(hse=16_000_000), "source": "HSI16"}
    hsi = "```c\nRCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI | (3U << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;\n```"
    assert grade(hsi, item)["pass"] is True
    r = grade(hsi.replace("PLLSRC_HSI", "PLLSRC_HSE"), item)
    assert r["pass"] is False and "PLL source is HSE, expected HSI16" in r["reasons"][0]
    assert grade("PLL source: HSI16, PLLM = 4, PLLN = 85, PLLR = 2", item)["pass"] is True
    assert grade("PLLM = 4, PLLN = 85, PLLR = 2", item)["pass"] is True                       # văn xuôi không nêu nguồn: không trượt vì nguồn
    assert grade(hsi, PLL(hse=16_000_000))["pass"] is False                                   # mặc định vẫn đòi HSE


def test_the_c5_author_reference_forms():
    text = "PLL: PLLM = /3 (M = 3), PLLN = 85, PLLR = /2 (R = 2)."
    assert grade(text, PLL(hse=12_000_000))["pass"] is True
    code = "```c\nRCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSE | ((3U - 1U) << RCC_PLLCFGR_PLLM_Pos) | (85U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN;\n```"
    r = grade(text + "\n\n" + code, PLL(hse=12_000_000))
    assert r["pass"] is True and r["details"]["pll"]["pll"]["source"] == "register" and r["details"]["pll"]["pll"]["m"] == 3
    assert grade("HSE /M = 3, xN = 85, /R = 2 feeds the PLL.", PLL(hse=12_000_000))["pass"] is False      # 'xN' không phải dạng N được nhận
    assert grade("PLL: HSE /M = 3, N = 85, /R = 2.", PLL(hse=12_000_000))["pass"] is True


@pytest.mark.parametrize("text,expected", [
    ("Battery life: about 2.3 years.", True),
    ("Battery life: about 27 months.", True),                    # 2,25 năm
    ("Battery life: about 840 days.", True),
    ("Battery life: about 20000 hours.", True),                  # 2,28 năm
    ("Battery life: about 9 months.", False),
    ("Battery life: about 2.3 yrs", True),
])
def test_quantity_with_long_time_units_and_unit_out_years(text, expected):
    item = {"id": "life", "type": "quantity", "desc": "battery life 2-3 years",
            "patterns": [r"battery life[^.\n]{0,20}?(?P<v>\d+(?:\.\d+)?)\s*(?P<u>years?|yrs?|months?|days?|hours?|h)\b"], "unit_out": "year", "min": 2, "max": 3}
    assert ok(text, item) is expected
