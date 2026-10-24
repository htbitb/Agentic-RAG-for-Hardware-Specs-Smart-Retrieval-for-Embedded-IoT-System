"""GOLDEN: cây clock STM32G474 (RCC) — PLL từ HSI16 → 170 MHz, giới hạn, wait state Flash, prescaler (brief P2 Bước 3, D19).

Mọi giá trị kỳ vọng: tính tay (comment) hoặc RM0440/DS12288 (số trang PDF). Mã nguồn simulator không được dùng để sinh số.
"""
import pytest

from hwmodel.sim import simulate_register_writes
from hwmodel_helpers import CLR, MOD, SET, W, errors, warnings, without

SIM = lambda ops, initial="reset", **kw: simulate_register_writes("stm32g474", ops, initial=initial, **kw)      # noqa: E731

# --- trình tự đổi sang PLL 170 MHz từ HSI16 (RM0440 §7.4.4 p.291–293; Flash latency Table 9 p.98; DS12288 Table 46 p.123)
#   f(VCO) = 16 MHz / PLLM * PLLN = 16 / 4 * 85 = 340 MHz (96..344 MHz), f(PLL_R) = 340 / 2 = 170 MHz.
#   PLLM[3:0] mã hoá M-1: M = 4 -> 0b0011; PLLR[1:0] = 00 -> /2; PLLSRC = 10 -> HSI16; PLLREN = bit 24.
#   PWR_CR5 reset = 0x100: R1MODE = 1 (Range 1 NORMAL mode, tối đa 150 MHz); >150 MHz phải xoá R1MODE (RM p.232–233, Table 38 p.232, reset p.267)
#   PWR cần clock: PWREN = RCC_APB1ENR1 bit 28 (p.309).
PWREN = SET("RCC_APB1ENR1", 1 << 28)
BOOST = CLR("PWR_CR5", 1 << 8)                                               # R1MODE = 0 -> Range 1 boost mode
LATENCY4 = MOD("FLASH_ACR", 0xF, 4)                                          # LATENCY = 4 WS (Table 9: 4 WS đến 170 MHz, boost)
PLLCFG85 = W("RCC_PLLCFGR", (1 << 24) | (85 << 8) | (0b0011 << 4) | 0b10)    # PLLREN | PLLN = 85 | PLLM = 4 | PLLR = /2 | PLLSRC = HSI16
PLLON = SET("RCC_CR", 1 << 24)
SW_PLL = MOD("RCC_CFGR", 0b11, 0b11)
PLL170 = [PWREN, BOOST, LATENCY4, PLLCFG85, PLLON, SW_PLL]                    # hợp lệ về vật lý (không có error)
# RM p.233: trước khi lên >150 MHz phải chia HCLK cho 2 (HPRE = 1000), chuyển PLL, đợi >= 1 µs rồi trả HPRE về /1
PLL170_PROPER = [PWREN, BOOST, LATENCY4, PLLCFG85, PLLON, MOD("RCC_CFGR", 0xF0, 0x80), SW_PLL, MOD("RCC_CFGR", 0xF0, 0x00)]


def test_reset_clock_state_is_hsi16_at_16mhz():
    res = SIM([])
    c = res["clocks"]
    assert c["sysclk_hz"] == c["hclk_hz"] == c["pclk1_hz"] == c["pclk2_hz"] == 16_000_000         # RCC_CFGR reset 0x5: SW = HSI16 (p.289)
    assert c["tim_clk_apb1_hz"] == c["tim_clk_apb2_hz"] == 16_000_000                             # prescaler = 1 => không nhân đôi
    assert c["sysclk_source"] == "HSI16"


def test_pll_from_hsi16_reaches_170mhz_without_violations():
    res = SIM(PLL170_PROPER)
    c = res["clocks"]
    assert c["sysclk_hz"] == 170_000_000 and c["hclk_hz"] == 170_000_000
    assert c["pclk1_hz"] == c["pclk2_hz"] == 170_000_000
    assert c["pll"] == {"source": "HSI16", "m": 4, "n": 85, "r": 2, "vco_in_hz": 4_000_000, "vco_hz": 340_000_000, "r_hz": 170_000_000, "on": True}
    assert res["violations"] == []
    assert int(res["final_registers"]["RCC_CFGR"], 16) & 0xF == 0xF              # SW = SWS = 11 (hardware cập nhật SWS)


def test_skipping_the_ahb_divide_by_two_step_is_only_a_procedure_warning():
    # RM p.233 yêu cầu chia HCLK cho 2 khi lên >150 MHz (đợi >= 1 µs): simulator không mô hình thời gian => chỉ cảnh báo, không chặn
    res = SIM(PLL170)
    assert errors(res) == [] and warnings(res) == ["SIM-CLK-PROC"]
    assert res["clocks"]["sysclk_hz"] == 170_000_000 and res["ok"] is True


def test_the_pll_r_output_must_be_enabled_to_become_the_system_clock():
    # RM0440 p.292: PLLREN 'PLL R clock output enable (used as system clock)'; p.278 step 5: enable the desired PLL outputs
    no_pllren = W("RCC_PLLCFGR", (85 << 8) | (0b0011 << 4) | 0b10)
    res = SIM([PWREN, BOOST, LATENCY4, no_pllren, PLLON, SW_PLL])
    assert "SIM-CLK-NOSRC" in errors(res) and res["clocks"]["sysclk_hz"] == 16_000_000
    assert "PLLREN" in [v for v in res["violations"] if v["code"] == "SIM-CLK-NOSRC"][0]["msg"]


def test_the_ahb_divider_warning_applies_to_any_switch_to_the_pll_above_80mhz():
    # RM p.279–280: 'Switching from HSE or HSI16 to PLL with AHB frequency (HCLK) higher than 80 MHz' requires HPRE /2 first
    pll100 = [MOD("FLASH_ACR", 0xF, 3), W("RCC_PLLCFGR", (1 << 24) | (50 << 8) | (0b0011 << 4) | 0b10), PLLON]          # 4 x 50 / 2 = 100 MHz
    assert warnings(SIM(pll100 + [SW_PLL])) == ["SIM-CLK-PROC"]
    assert warnings(SIM(pll100 + [MOD("RCC_CFGR", 0xF0, 0x80), SW_PLL])) == []
    pll80 = [MOD("FLASH_ACR", 0xF, 2), W("RCC_PLLCFGR", (1 << 24) | (40 << 8) | (0b0011 << 4) | 0b10), PLLON]            # 80 MHz: không cần
    assert warnings(SIM(pll80 + [SW_PLL])) == []


def test_rdy_flags_are_assumed_to_rise_immediately_and_this_is_stated():
    res = SIM(PLL170_PROPER)
    assert int(res["final_registers"]["RCC_CR"], 16) & (1 << 25)                    # PLLRDY
    assert any("RDY" in a and "immediately" in a for a in res["assumptions"])


@pytest.mark.parametrize("hpre,ppre1,ppre2,hclk,pclk1,pclk2,t1,t2", [
    (0b0000, 0b000, 0b000, 170e6, 170e6, 170e6, 170e6, 170e6),        # 0xxx: không chia (p.290)
    (0b1000, 0b000, 0b000, 85e6, 85e6, 85e6, 85e6, 85e6),             # HPRE = 1000: /2
    (0b0000, 0b100, 0b100, 170e6, 85e6, 85e6, 170e6, 170e6),          # PPRE = 100: /2 => TIMCLK = 2 x 85
    (0b0000, 0b101, 0b110, 170e6, 42.5e6, 21.25e6, 85e6, 42.5e6),     # PPRE1 = /4, PPRE2 = /8: x2 => 85 và 42.5 MHz
    (0b1001, 0b111, 0b000, 42.5e6, 2.65625e6, 42.5e6, 5.3125e6, 42.5e6),     # HPRE /4, PPRE1 /16
])
def test_prescalers_and_the_timer_x2_rule(hpre, ppre1, ppre2, hclk, pclk1, pclk2, t1, t2):
    # CFGR: PPRE2 [13:11], PPRE1 [10:8], HPRE [7:4] (RM p.289–290); các số kỳ vọng tính tay từ 170 MHz
    cfgr = (ppre2 << 11) | (ppre1 << 8) | (hpre << 4)
    res = SIM(PLL170[:5] + [MOD("RCC_CFGR", 0x3FF3, 0b11 | cfgr)])
    c = res["clocks"]
    assert (c["hclk_hz"], c["pclk1_hz"], c["pclk2_hz"]) == (hclk, pclk1, pclk2)
    assert (c["tim_clk_apb1_hz"], c["tim_clk_apb2_hz"]) == (t1, t2)


def test_pll_from_hse_uses_the_hse_frequency_given_by_the_board():
    # HSE 8 MHz: M = 2 -> 4 MHz, N = 85 -> 340 MHz, R = 2 -> 170 MHz
    ops = [PWREN, BOOST, LATENCY4, SET("RCC_CR", 1 << 16),                                            # HSEON
           W("RCC_PLLCFGR", (1 << 24) | (85 << 8) | (0b0001 << 4) | 0b11), PLLON, SW_PLL]
    res = SIM(ops, initial={"preset": "reset", "hse_hz": 8_000_000})
    assert res["clocks"]["sysclk_hz"] == 170_000_000 and errors(res) == []


def test_hse_without_a_known_frequency_is_not_guessed():
    res = SIM([SET("RCC_CR", 1 << 16), MOD("RCC_CFGR", 0b11, 0b10)])
    assert res["clocks"]["sysclk_hz"] is None
    assert any("hse_hz" in n for n in res["notes"])


# ------------------------------------------------------------------ giới hạn
def test_vco_above_344mhz_is_a_clock_limit_violation():
    # N = 87: VCO = 4 MHz x 87 = 348 MHz > 344 MHz (DS Table 46 p.123, Range 1)
    ops = PLL170[:3] + [W("RCC_PLLCFGR", (1 << 24) | (87 << 8) | (0b0011 << 4) | 0b10), PLLON]
    res = SIM(ops)
    lim = [v for v in res["violations"] if v["code"] == "SIM-CLK-LIMIT"]
    assert {v["limit"] for v in lim} == {"vco_max"} and lim[0]["severity"] == "error"
    assert lim[0]["actual_hz"] == 348_000_000 and lim[0]["max_hz"] == 344_000_000


def test_sysclk_above_170mhz_is_a_clock_limit_violation():
    # N = 88, M = 4, R = 2: VCO = 352 MHz (cũng vượt), R = 176 MHz > 170 MHz (RM p.292 'must not exceed 170 MHz')
    ops = PLL170[:3] + [W("RCC_PLLCFGR", (1 << 24) | (88 << 8) | (0b0011 << 4) | 0b10), PLLON, SW_PLL]
    res = SIM(ops)
    assert {v["limit"] for v in res["violations"] if v["code"] == "SIM-CLK-LIMIT"} == {"vco_max", "sysclk_max"}


def test_vco_below_96mhz_and_pll_input_below_2_66mhz_are_violations():
    ops = [W("RCC_PLLCFGR", (1 << 24) | (8 << 8) | (0b0111 << 4) | 0b10), PLLON]     # M = 8: 2 MHz in; N = 8: 16 MHz VCO
    res = SIM(ops)
    assert {v["limit"] for v in res["violations"] if v["code"] == "SIM-CLK-LIMIT"} == {"pll_in_min", "vco_min"}


def test_pll_input_above_16mhz_from_hse_is_a_violation():
    ops = [SET("RCC_CR", 1 << 16), W("RCC_PLLCFGR", (1 << 24) | (10 << 8) | (0b0000 << 4) | 0b11), PLLON]   # HSE 24 MHz / 1
    res = SIM(ops, initial={"preset": "reset", "hse_hz": 24_000_000})
    assert "pll_in_max" in {v["limit"] for v in res["violations"] if v["code"] == "SIM-CLK-LIMIT"}


def test_plln_below_8_is_a_wrong_configuration():
    ops = [W("RCC_PLLCFGR", (1 << 24) | (7 << 8) | (0b0011 << 4) | 0b10), PLLON]     # RM p.293: PLLN < 8 'wrong configuration'
    assert "SIM-CLK-LIMIT" in errors(SIM(ops))


# ------------------------------------------------------------------ wait state Flash (RM Table 9 p.98, RM §3.3.3) và chế độ nguồn
def test_switching_to_170mhz_without_raising_the_wait_states_is_an_error():
    ops = without(PLL170, 2)                    # bỏ bước FLASH_ACR.LATENCY; SW=PLL nằm ở vị trí 4
    res = SIM(ops)
    bad = [v for v in res["violations"] if v["code"] == "SIM-FLASH-WS"]
    # FLASH_ACR reset = 0x0004 0601 (RM p.130) => LATENCY[3:0] = 1 WS; 170 MHz cần 4 WS (Table 9 p.98)
    assert len(bad) == 1 and bad[0]["at_op"] == 4 and bad[0]["latency"] == 1 and bad[0]["required"] == 4


def test_setting_latency_after_the_switch_is_still_an_error_at_the_switch():
    ops = without(PLL170, 2) + [LATENCY4]
    bad = [v for v in SIM(ops)["violations"] if v["code"] == "SIM-FLASH-WS"]
    assert [v["at_op"] for v in bad] == [4]


@pytest.mark.parametrize("latency,ok", [(0, False), (1, False), (2, False), (3, False), (4, True), (5, True)])
def test_wait_states_needed_for_170mhz(latency, ok):
    # 4 WS: HCLK <= 170 MHz in boost mode; ít hơn thì Table 9 giới hạn 34 / 68 / 102 / 136 MHz (p.98)
    res = SIM([PWREN, BOOST, MOD("FLASH_ACR", 0xF, latency)] + PLL170[3:])
    assert ("SIM-FLASH-WS" not in errors(res)) is ok


def test_170mhz_without_clearing_r1mode_exceeds_the_range_1_normal_mode_limit():
    # PWR_CR5 reset 0x100 => R1MODE = 1 (normal, <= 150 MHz). Quên xoá R1MODE khi lên 170 MHz là lỗi G4 kinh điển (RM p.232–233, Table 38)
    res = SIM(without(PLL170, 1))
    lim = [v for v in res["violations"] if v["code"] == "SIM-CLK-LIMIT"]
    assert [v["limit"] for v in lim] == ["hclk_max_range1_normal"] and lim[0]["max_hz"] == 150_000_000


def test_150mhz_in_range_1_normal_mode_is_fine_without_touching_pwr():
    # M = 4 -> 4 MHz, N = 75 -> 300 MHz, R = 2 -> 150 MHz; Table 9 (normal mode): 4 WS đến 150 MHz
    ops = [LATENCY4, W("RCC_PLLCFGR", (1 << 24) | (75 << 8) | (0b0011 << 4) | 0b10), PLLON, SW_PLL]
    res = SIM(ops)
    assert errors(res) == [] and res["clocks"]["sysclk_hz"] == 150_000_000


def test_writing_pwr_registers_needs_the_pwr_clock():
    res = SIM([CLR("PWR_CR5", 1 << 8)])
    assert [v["peripheral"] for v in res["violations"] if v["code"] == "SIM-CLK-GATE"] == ["PWR"]


def test_range_2_limits_sysclk_to_26mhz():
    # PWR_CR1.VOS[10:9] = 10 -> Range 2 (RM p.253 'VOS'); SYSCLK 80 MHz vượt 26 MHz
    ops = [PWREN, MOD("PWR_CR1", 0b11 << 9, 0b10 << 9), MOD("FLASH_ACR", 0xF, 2),
           W("RCC_PLLCFGR", (1 << 24) | (40 << 8) | (0b0011 << 4) | 0b10), PLLON, SW_PLL]
    assert "SIM-CLK-LIMIT" in errors(SIM(ops))


# ------------------------------------------------------------------ chuỗi sai thứ tự
def test_switching_to_pll_while_it_is_off_leaves_sysclk_unchanged_and_is_reported():
    res = SIM([MOD("RCC_CFGR", 0b11, 0b11)])
    assert "SIM-CLK-NOSRC" in errors(res)
    assert res["clocks"]["sysclk_hz"] == 16_000_000


def test_pll_configuration_is_write_protected_while_the_pll_is_on():
    # RM p.292–293: PLLN/PLLM/PLLR/PLLSRC chỉ ghi được khi PLL tắt => ghi bị bỏ qua
    ops = PLL170[:5] + [W("RCC_PLLCFGR", (1 << 24) | (50 << 8) | (0b0011 << 4) | 0b10), SW_PLL]
    res = SIM(ops)
    assert "SIM-RCC-LOCKED" in errors(res)
    assert res["clocks"]["pll"]["n"] == 85


def test_peripheral_clock_enable_registers_have_the_documented_reset_values():
    res = SIM([])
    assert res["clocks"]["enabled_peripherals"] == sorted(res["clocks"]["enabled_peripherals"])
    assert "TIM1" not in res["clocks"]["enabled_peripherals"] and "GPIOA" not in res["clocks"]["enabled_peripherals"]
    assert "FLASH" in res["clocks"]["enabled_peripherals"]                           # RCC_AHB1ENR reset 0x100 = FLASHEN (p.306)


# ------------------------------------------------------------------ preset khởi đầu
@pytest.mark.parametrize("preset,sysclk,p1,p2", [
    ("reset", 16e6, 16e6, 16e6),
    ("sysclk_170mhz_pll_hsi16_apb_div1", 170e6, 170e6, 170e6),
    ("sysclk_170mhz_pll_hsi16_apb2_div2", 170e6, 170e6, 85e6),
    ("sysclk_170mhz_pll_hsi16_apb1_div2", 170e6, 85e6, 170e6),
    ("sysclk_80mhz_pll_hsi16_apb_div1", 80e6, 80e6, 80e6),
])
def test_initial_presets_have_the_documented_clock_tree_and_no_violations(preset, sysclk, p1, p2):
    res = SIM([], initial=preset)
    assert (res["clocks"]["sysclk_hz"], res["clocks"]["pclk1_hz"], res["clocks"]["pclk2_hz"]) == (sysclk, p1, p2)
    assert res["violations"] == []
    assert res["clocks"]["enabled_peripherals"] == SIM([])["clocks"]["enabled_peripherals"]      # preset không bật clock ngoại vi


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown initial"):
        SIM([], initial="sysclk_999mhz")
