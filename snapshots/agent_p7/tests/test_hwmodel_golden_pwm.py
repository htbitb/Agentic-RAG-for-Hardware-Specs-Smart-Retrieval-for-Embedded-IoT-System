"""GOLDEN: chuỗi PWM chuẩn TIM1_CH1/PA8 + mọi lỗi kinh điển phải bị bắt với ĐÚNG mã (brief P2 Bước 3, D19).

Giá trị kỳ vọng KHÔNG sinh từ simulator: tính tay (ghi ở comment) hoặc lấy từ RM0440 / DS12288 (số trang PDF).
"""
import pytest

from hwmodel.sim import simulate_register_writes
from hwmodel_helpers import (CLK170, IDX, MOD, PWM_PA8, SET, W, codes, errors, effects_of, one_effect, replaced, warnings, without)

SIM = lambda ops, initial=CLK170: simulate_register_writes("stm32g474", ops, initial=initial)       # noqa: E731


# ------------------------------------------------------------------ chuỗi đúng
def test_reference_sequence_gives_20khz_25pct_on_pa8():
    res = SIM(PWM_PA8)
    pwm = one_effect(res, kind="pwm", pin="PA8")
    assert pwm["signal"] == "TIM1_CH1" and pwm["timer"] == "TIM1" and pwm["channel"] == 1
    assert pwm["active"] is True and pwm["reason"] is None
    assert pwm["pwm_hz"] == pytest.approx(20_000.0, rel=1e-9)         # 170e6 / (1 * 8500)
    assert pwm["duty_pct"] == pytest.approx(25.0, rel=1e-9)           # 2125 / 8500
    assert res["violations"] == []
    assert res["ok"] is True
    assert res["clocks"]["tim_clk_apb2_hz"] == 170_000_000


def test_reference_sequence_final_registers_are_reported():
    regs = SIM(PWM_PA8)["final_registers"]
    assert int(regs["TIM1_ARR"], 16) == 8499
    assert int(regs["TIM1_CCR1"], 16) == 2125
    assert int(regs["GPIOA_AFRH"], 16) == 6
    assert int(regs["RCC_APB2ENR"], 16) == 1 << 11


def test_reference_sequence_leaves_nothing_unmodeled_that_matters():
    res = SIM(PWM_PA8)
    assert not [u for u in res["unmodeled"] if u.startswith(("TIM1_", "GPIOA_", "RCC_"))]


# ------------------------------------------------------------------ lỗi kinh điển: cổng clock
def test_forgetting_the_tim1_clock_is_caught_and_the_writes_are_ignored():
    ops = without(PWM_PA8, IDX["tim1_clk"])
    res = SIM(ops)
    gate = [v for v in res["violations"] if v["code"] == "SIM-CLK-GATE"]
    assert [v["peripheral"] for v in gate] == ["TIM1"]
    assert gate[0]["severity"] == "error"
    assert gate[0]["at_op"] == IDX["psc"] - 1                   # op đầu tiên vào TIM1: PSC, trượt 1 chỗ vì đã bỏ op TIM1EN
    assert gate[0]["count"] == 9                                # PSC, ARR, CCR1, CCMR1, CCER, BDTR, CR1, EGR, CR1
    assert "TIM1_ARR" not in res["final_registers"]             # lệnh ghi bị bỏ qua như phần cứng thật
    pa8 = one_effect(res, kind="pwm", pin="PA8")
    assert pa8["active"] is False and pa8["reason"] == "SIM-CLK-GATE"


def test_forgetting_the_gpioa_clock_is_caught():
    ops = without(PWM_PA8, IDX["gpioa_clk"])
    res = SIM(ops)
    gate = [v for v in res["violations"] if v["code"] == "SIM-CLK-GATE"]
    assert [v["peripheral"] for v in gate] == ["GPIOA"] and gate[0]["count"] == 2     # MODER, AFRH
    # kênh TIM1_CH1 bật nhưng không có chân nào được định tuyến vì cấu hình GPIO đã mất
    ch = one_effect(res, kind="pwm", signal="TIM1_CH1")
    assert ch["pin"] is None and ch["active"] is False and ch["reason"] == "SIM-CLK-GATE"


# ------------------------------------------------------------------ lỗi kinh điển: timer
def test_forgetting_moe_on_an_advanced_timer_is_caught():
    res = SIM(without(PWM_PA8, IDX["moe"]))
    assert errors(res) == ["SIM-TIM-MOE"]
    pa8 = one_effect(res, kind="pwm", pin="PA8")
    assert pa8["active"] is False and pa8["reason"] == "SIM-TIM-MOE"


def test_forgetting_cen_is_caught():
    res = SIM(without(PWM_PA8, IDX["cen"]))
    assert errors(res) == ["SIM-TIM-CEN"]
    assert one_effect(res, kind="pwm", pin="PA8")["reason"] == "SIM-TIM-CEN"


def test_forgetting_cc1e_is_caught():
    res = SIM(without(PWM_PA8, IDX["ccer"]))
    assert errors(res) == ["SIM-TIM-CCE"]
    assert one_effect(res, kind="pwm", pin="PA8")["reason"] == "SIM-TIM-CCE"


def test_missing_pwm_mode_in_ccmr1_is_caught():
    # chỉ bật preload, OC1M = 0000 (frozen)
    res = SIM(replaced(PWM_PA8, IDX["ccmr"], MOD("TIM1_CCMR1", 1 << 3, 1 << 3)))
    assert errors(res) == ["SIM-TIM-OCM"]
    assert one_effect(res, kind="pwm", pin="PA8")["reason"] == "SIM-TIM-OCM"


def test_toggle_mode_is_not_pwm():
    res = SIM(replaced(PWM_PA8, IDX["ccmr"], MOD("TIM1_CCMR1", 0b111 << 4, 0b011 << 4)))      # OC1M = 0011 toggle
    assert errors(res) == ["SIM-TIM-OCM"]


# ------------------------------------------------------------------ lỗi kinh điển: GPIO
def test_wrong_alternate_function_is_caught_and_the_pin_shows_what_it_really_does():
    res = SIM(replaced(PWM_PA8, IDX["afrh"], MOD("GPIOA_AFRH", 0xF, 2)))        # AF2 = I2C3_SCL trên PA8 (DS p.73)
    assert errors(res) == ["SIM-GPIO-AF"]
    af = one_effect(res, kind="pin_af", pin="PA8")
    assert af["af"] == 2 and af["signal"] == "I2C3_SCL"
    ch = one_effect(res, kind="pwm", signal="TIM1_CH1")
    assert ch["pin"] is None and ch["active"] is False and ch["reason"] == "SIM-GPIO-AF"


def test_moder_not_in_alternate_function_mode_is_caught():
    res = SIM(replaced(PWM_PA8, IDX["moder"], MOD("GPIOA_MODER", 0b11 << 16, 0b01 << 16)))   # general purpose output
    assert errors(res) == ["SIM-GPIO-MODE"]
    assert one_effect(res, kind="pwm", signal="TIM1_CH1")["reason"] == "SIM-GPIO-MODE"


def test_moder_left_at_reset_analog_is_also_caught():
    res = SIM(without(PWM_PA8, IDX["moder"]))               # MODER8 reset = 11 (analog) — RM p.355: 0xABFF FFFF cho cổng A
    assert errors(res) == ["SIM-GPIO-MODE"]


def test_shifting_the_afrh_value_by_four_selects_pin_9_instead_of_pin_8():
    # GPIOA->AFR[1] |= (6 << 4): AFSEL9 = 6, AFSEL8 vẫn 0 (= MCO). RM: AFSELy ở bit [4*(y-8)+3 : 4*(y-8)] (cổng AFRH)
    res = SIM(replaced(PWM_PA8, IDX["afrh"], MOD("GPIOA_AFRH", 0xF << 4, 6 << 4)))
    assert errors(res) == ["SIM-GPIO-AF"]
    af = one_effect(res, kind="pin_af", pin="PA8")
    assert af["af"] == 0 and af["signal"] == "MCO"          # DS p.73: PA8 AF0 = MCO


# ------------------------------------------------------------------ lỗi kinh điển: số học / clock
def test_psc_off_by_one_halves_the_frequency():
    res = SIM(replaced(PWM_PA8, IDX["psc"], W("TIM1_PSC", 1)))
    pwm = one_effect(res, kind="pwm", pin="PA8")
    assert pwm["pwm_hz"] == pytest.approx(10_000.0, rel=1e-9)          # 170e6 / (2 * 8500)
    assert pwm["duty_pct"] == pytest.approx(25.0, rel=1e-9)
    assert errors(res) == []                                            # hợp lệ về vật lý: lỗi chỉ lộ ra khi so với spec


def test_forgetting_the_x2_rule_when_apb2_is_divided_gives_double_frequency():
    # APB2 prescaler = 2 => PCLK2 = 85 MHz, TIM1CLK = 2 x 85 = 170 MHz (RM p.281 §7.2.13).
    # Người quên quy tắc nhân đôi tính ARR = 85e6/20e3 - 1 = 4249 => thực tế 170e6/4250 = 40 kHz
    forgetful = replaced(PWM_PA8, IDX["arr"], W("TIM1_ARR", 4249))
    res = simulate_register_writes("stm32g474", forgetful, initial="sysclk_170mhz_pll_hsi16_apb2_div2")
    assert res["clocks"]["pclk2_hz"] == 85_000_000 and res["clocks"]["tim_clk_apb2_hz"] == 170_000_000
    assert one_effect(res, kind="pwm", pin="PA8")["pwm_hz"] == pytest.approx(40_000.0, rel=1e-9)


def test_x2_rule_applied_correctly_gives_20khz_with_apb2_divided():
    res = simulate_register_writes("stm32g474", PWM_PA8, initial="sysclk_170mhz_pll_hsi16_apb2_div2")
    assert one_effect(res, kind="pwm", pin="PA8")["pwm_hz"] == pytest.approx(20_000.0, rel=1e-9)


def test_apb_prescaler_one_means_no_doubling():
    res = SIM(PWM_PA8)
    assert res["clocks"]["pclk2_hz"] == res["clocks"]["tim_clk_apb2_hz"] == 170_000_000


# ------------------------------------------------------------------ lỗi kinh điển: thanh ghi
def test_writing_reserved_bits_is_a_warning():
    res = SIM(PWM_PA8 + [W("TIM1_PSC", 0x1_0000)])               # PSC chỉ có [15:0] (RM p.1262)
    assert "SIM-RESERVED" in warnings(res)
    bad = [v for v in res["violations"] if v["code"] == "SIM-RESERVED"][0]
    assert bad["at_op"] == len(PWM_PA8) and bad["reg"] == "TIM1_PSC"


def test_writing_a_nonexistent_address_is_an_error():
    res = SIM(PWM_PA8 + [{"op": "write", "addr": 0x4001_2C80, "value": 1}])      # TIM1 + 0x80: trống (RM p.1286)
    bad = [v for v in res["violations"] if v["code"] == "SIM-BADADDR"]
    assert len(bad) == 1 and bad[0]["severity"] == "error" and bad[0]["at_op"] == len(PWM_PA8)
    assert res["ok"] is False


# ------------------------------------------------------------------ ngữ nghĩa PWM
def _with(seq, **repl):
    out = list(seq)
    for k, op in repl.items():
        out[IDX[k]] = op
    return out


def test_pwm_mode_2_inverts_the_duty():
    ops = _with(PWM_PA8, ccmr=MOD("TIM1_CCMR1", (0b111 << 4) | (1 << 3) | (1 << 16), (0b111 << 4) | (1 << 3)))   # OC1M = 0111
    assert one_effect(SIM(ops), kind="pwm", pin="PA8")["duty_pct"] == pytest.approx(75.0, rel=1e-9)         # 100 - 25


def test_output_polarity_cc1p_inverts_the_duty_at_the_pin():
    ops = PWM_PA8[:IDX["ccer"]] + [SET("TIM1_CCER", (1 << 0) | (1 << 1))] + PWM_PA8[IDX["ccer"] + 1:]           # CC1E | CC1P (p.1260)
    assert one_effect(SIM(ops), kind="pwm", pin="PA8")["duty_pct"] == pytest.approx(75.0, rel=1e-9)


@pytest.mark.parametrize("ccr,duty", [(0, 0.0), (8500, 100.0), (9999, 100.0), (4250, 50.0)])
def test_duty_edge_cases_follow_the_rm(ccr, duty):
    # RM p.1179: CCRx > ARR => tim_ocxref giữ mức 1 (100 %); CCRx = 0 => giữ mức 0. ARR = 8499 => 8500 nhịp/chu kỳ
    res = SIM(_with(PWM_PA8, ccr=W("TIM1_CCR1", ccr)))
    assert one_effect(res, kind="pwm", pin="PA8")["duty_pct"] == pytest.approx(duty, abs=1e-9)


def test_downcounting_pwm1_adds_one_count():
    # RM p.1179 'Downcounting configuration': ocxref thấp khi CNT > CCR => (CCR + 1) nhịp cao: 2126 / 8500
    ops = PWM_PA8[:-1] + [SET("TIM1_CR1", (1 << 0) | (1 << 4))]                       # CEN | DIR
    assert one_effect(SIM(ops), kind="pwm", pin="PA8")["duty_pct"] == pytest.approx(100 * 2126 / 8500, rel=1e-9)


def test_arr_beyond_16_bits_on_a_16_bit_timer_is_an_error():
    # 1 kHz với PSC = 0: ARR = 170e6/1e3 - 1 = 169999 > 0xFFFF — TIM1 chỉ có bộ đếm 16 bit (CNT[15:0], RM p.1262)
    res = SIM(_with(PWM_PA8, arr=W("TIM1_ARR", 169_999)))
    assert errors(res) == ["SIM-TIM-RANGE"]
    assert one_effect(res, kind="pwm", pin="PA8")["reason"] == "SIM-TIM-RANGE"


def test_arr_zero_blocks_the_counter():
    res = SIM(_with(PWM_PA8, arr=W("TIM1_ARR", 0)))               # RM p.1263: 'The counter is blocked while the autoreload value is null'
    assert "SIM-TIM-ARR0" in errors(res)


def _tim2_pwm(arr, extra=()):
    return [
        SET("RCC_AHB2ENR", 1 << 0), SET("RCC_APB1ENR1", 1 << 0),                  # GPIOAEN; TIM2EN = APB1ENR1 bit 0 (p.311)
        MOD("GPIOA_MODER", 0b11 << 0, 0b10 << 0), MOD("GPIOA_AFRL", 0xF, 1),      # PA0 AF1 = TIM2_CH1 (DS p.73)
        W("TIM2_PSC", 0), W("TIM2_ARR", arr), W("TIM2_CCR1", (arr + 1) // 2),
        MOD("TIM2_CCMR1", (0b111 << 4) | (1 << 3), (0b110 << 4) | (1 << 3)),
        SET("TIM2_CCER", 1), *extra, SET("TIM2_CR1", 1),
    ]


def test_general_purpose_32_bit_timer_reaches_1khz_without_moe():
    # 170e6 / (169999 + 1) = 1000 Hz; CCR1 = 85000 => 85000 / 170000 = 50 %. TIM2 là bộ đếm 32 bit (RM p.1387–1389) và không có MOE
    res = SIM(_tim2_pwm(169_999))
    pwm = one_effect(res, kind="pwm", pin="PA0")
    assert pwm["signal"] == "TIM2_CH1" and pwm["active"] is True
    assert pwm["pwm_hz"] == pytest.approx(1000.0, rel=1e-9)
    assert pwm["duty_pct"] == pytest.approx(50.0, rel=1e-9)
    assert res["violations"] == []


def test_timer_on_apb1_uses_pclk1_rule():
    res = simulate_register_writes("stm32g474", _tim2_pwm(169_999), initial="sysclk_170mhz_pll_hsi16_apb1_div2")
    assert res["clocks"]["pclk1_hz"] == 85_000_000 and res["clocks"]["tim_clk_apb1_hz"] == 170_000_000
    assert one_effect(res, kind="pwm", pin="PA0")["pwm_hz"] == pytest.approx(1000.0, rel=1e-9)


# ------------------------------------------------------------------ không mô hình hoá => nói rõ, không pass
def test_center_aligned_mode_is_reported_as_unmodeled():
    res = SIM(PWM_PA8 + [MOD("TIM1_CR1", 0b11 << 5, 0b01 << 5)])         # CMS = 01
    pwm = one_effect(res, kind="pwm", pin="PA8")
    assert pwm["modeled"] is False
    assert any("CMS" in u for u in res["unmodeled"])


def test_dithering_mode_is_reported_as_unmodeled():
    res = SIM(PWM_PA8 + [SET("TIM1_CR1", 1 << 12)])                       # DITHEN
    assert one_effect(res, kind="pwm", pin="PA8")["modeled"] is False
    assert any("DITHEN" in u for u in res["unmodeled"])


def test_unrelated_peripheral_registers_are_listed_as_unmodeled():
    res = SIM(PWM_PA8 + [SET("RCC_AHB1ENR", 1 << 0), W("DMA1_CCR1", 1)])    # DMA1EN, rồi ghi DMA1_CCR1
    assert "DMA1_CCR1" in res["unmodeled"]
    assert effects_of(res, kind="pwm", pin="PA8")[0]["active"] is True


def test_unknown_chip_is_an_error():
    with pytest.raises(KeyError):
        simulate_register_writes("atmega328", PWM_PA8)


def test_semantic_layer_only_exists_for_stm32g474_other_chips_report_unmodeled():
    res = simulate_register_writes("nrf52840", [W("P0_OUT", 1)])
    assert res["effects"] == []
    assert "P0_OUT" in res["unmodeled"]
    assert any("no semantic model" in n for n in res["notes"])
