"""solve_timer_config: liệt kê (PSC, ARR), chọn sai số tần số nhỏ nhất rồi độ phân giải duty lớn nhất; tính CCR.
Kỳ vọng tính tay (comment) — công thức f = f_TIM / ((PSC + 1)(ARR + 1)), duty = CCR / (ARR + 1) (RM0440 p.1179)."""
from fractions import Fraction

import pytest

from hwmodel.solver import solve_timer_config


def solve(timer="TIM1", hz=20_000, duty=25, ch=1, clock=None, chip="stm32g474"):
    return solve_timer_config(chip, timer, hz, duty, ch, clock_state=clock)


def test_the_plan_example_170mhz_20khz_25pct():
    r = solve(clock={"tim_clk_hz": 170_000_000})
    assert r["ok"] is True
    best = r["best"]
    assert (best["psc"], best["arr"], best["ccr"]) == (0, 8499, 2125)          # 170e6 / 20e3 = 8500 nhịp; 25 % của 8500 = 2125
    assert best["freq_hz"] == pytest.approx(20_000.0, rel=1e-12) and best["freq_error_pct"] == pytest.approx(0.0, abs=1e-12)
    assert best["duty_pct"] == pytest.approx(25.0, rel=1e-12) and best["duty_error_pct"] == pytest.approx(0.0, abs=1e-12)
    assert best["duty_steps"] == 8500 and best["duty_resolution_bits"] == pytest.approx(13.0533, abs=1e-3)      # log2(8500)
    assert r["registers"] == {"TIM1_PSC": 0, "TIM1_ARR": 8499, "TIM1_CCR1": 2125}
    assert r["tim_clk_hz"] == 170_000_000 and r["counter_bits"] == 16


def test_x2_rule_is_applied_from_pclk_and_apb_prescaler():
    # APB2 prescaler = 2, PCLK2 = 85 MHz => TIMxCLK = 170 MHz (RM p.281 §7.2.13)
    a = solve(clock={"pclk_hz": 85_000_000, "apb_prescaler": 2})
    assert a["tim_clk_hz"] == 170_000_000 and a["best"]["arr"] == 8499
    # prescaler = 1 => TIMxCLK = PCLK = 85 MHz; 10 kHz => 8500 nhịp
    b = solve(hz=10_000, clock={"pclk_hz": 85_000_000, "apb_prescaler": 1})
    assert b["tim_clk_hz"] == 85_000_000 and (b["best"]["psc"], b["best"]["arr"], b["best"]["ccr"]) == (0, 8499, 2125)


def test_without_a_clock_state_the_assumption_is_stated_not_hidden():
    r = solve()
    assert r["tim_clk_hz"] == 170_000_000
    assert any("assumed TIMxCLK = 170 MHz" in a for a in r["assumptions"])


def test_16_bit_timer_needs_a_prescaler_for_1khz():
    # 170e6 / 1e3 = 170000 = (PSC+1)(ARR+1); ARR+1 <= 65536 => PSC+1 >= 2.6. Ước của 170000 = 2^4 5^4 17 không có 3 => PSC+1 = 4, ARR+1 = 42500
    r = solve(hz=1_000, duty=50, clock={"tim_clk_hz": 170_000_000})
    assert (r["best"]["psc"], r["best"]["arr"], r["best"]["ccr"]) == (3, 42_499, 21_250)
    assert r["best"]["freq_error_pct"] == pytest.approx(0.0, abs=1e-12)


def test_32_bit_timer_reaches_1khz_without_prescaler():
    r = solve(timer="TIM2", hz=1_000, duty=50, clock={"tim_clk_hz": 170_000_000})
    assert (r["best"]["psc"], r["best"]["arr"], r["best"]["ccr"]) == (0, 169_999, 85_000)
    assert r["counter_bits"] == 32 and r["registers"]["TIM2_CCR1"] == 85_000


def _brute(clk, target, nmax=65536):
    """Oracle độc lập (không dùng mã solver): với mỗi PSC+1 thử hai số nhịp ARR+1 sát nhất (sàn và trần của clk/((PSC+1) f))."""
    out = []
    for psc1 in range(1, 65537):
        x = Fraction(clk, psc1 * target)
        for n in {x.numerator // x.denominator, -(-x.numerator // x.denominator)}:
            if 2 <= n <= nmax:
                out.append((abs(Fraction(clk, psc1 * n) - target) / target, -n, psc1))
    return sorted(out)


def test_the_pick_has_the_smallest_error_then_the_largest_duty_resolution():
    # hz = 44100 không chia hết 170 MHz: sai số tối thiểu có thể có
    clk, target = 170_000_000, 44_100
    ranked = _brute(clk, target)
    err, neg_n, psc1 = ranked[0]
    r = solve(hz=44_100, duty=33, clock={"tim_clk_hz": clk})
    assert r["best"]["freq_error_pct"] / 100 == pytest.approx(float(err), rel=1e-9)
    assert r["best"]["arr"] + 1 == -neg_n and r["best"]["psc"] + 1 == psc1


def test_ccr_rounds_to_the_nearest_count_and_reports_the_duty_error():
    # 170 MHz, 50 kHz => ARR + 1 = 3400; 33.3 % => 0.333 x 3400 = 1132.2 => CCR = 1132 => duty = 33.2941 %, sai số 0.0059 điểm %
    r = solve(hz=50_000, duty=33.3, clock={"tim_clk_hz": 170_000_000})
    assert r["best"]["arr"] == 3399 and r["best"]["ccr"] == 1132
    assert r["best"]["duty_pct"] == pytest.approx(100 * 1132 / 3400, rel=1e-12)
    assert r["best"]["duty_error_pct"] == pytest.approx(33.3 - 100 * 1132 / 3400, abs=1e-9)


@pytest.mark.parametrize("duty,ccr", [(0, 0), (100, 8500)])
def test_duty_extremes(duty, ccr):
    # RM p.1179: CCR = 0 => 0 %; CCR > ARR => 100 % (CCR = ARR + 1 = 8500 là giá trị nhỏ nhất cho 100 %)
    assert solve(duty=duty, clock={"tim_clk_hz": 170_000_000})["best"]["ccr"] == ccr


def test_alternatives_are_listed_in_quality_order():
    r = solve(hz=1_000, duty=50, clock={"tim_clk_hz": 170_000_000})
    errs = [(a["freq_error_pct"], -a["duty_steps"]) for a in [r["best"], *r["alternatives"]]]
    assert errs == sorted(errs) and len(r["alternatives"]) >= 2


@pytest.mark.parametrize("timer,ch,ok", [("TIM1", 4, True), ("TIM1", 5, False), ("TIM2", 1, True), ("TIM15", 2, True), ("TIM15", 3, False),
                                         ("TIM16", 1, True), ("TIM16", 2, False), ("TIM6", 1, False), ("TIM9", 1, False)])
def test_timer_and_channel_validation(timer, ch, ok):
    r = solve(timer=timer, ch=ch, clock={"tim_clk_hz": 170_000_000})
    assert r["ok"] is ok
    if not ok:
        assert "error" in r


@pytest.mark.parametrize("hz,why", [(100_000_000, "too high"), (0, "positive"), (-5, "positive"), (0.01, "too low")])
def test_infeasible_targets_are_reported_not_guessed(hz, why):
    r = solve(hz=hz, clock={"tim_clk_hz": 170_000_000})
    assert r["ok"] is False and why in r["error"]


def test_invalid_duty_and_chip():
    assert solve(duty=101, clock={"tim_clk_hz": 170_000_000})["ok"] is False
    assert solve(chip="esp32", clock={"tim_clk_hz": 170_000_000})["ok"] is False
    assert "stm32g474" in solve(chip="esp32")["error"]


def test_timer_register_names_exist_in_the_register_map():
    from hwmodel.regmap import load_regmap
    rm = load_regmap("stm32g474")
    for t, ch in (("TIM1", 1), ("TIM2", 4), ("TIM15", 2), ("TIM17", 1)):
        for name in solve(timer=t, ch=ch, clock={"tim_clk_hz": 170_000_000})["registers"]:
            assert rm.get(name) is not None, name
