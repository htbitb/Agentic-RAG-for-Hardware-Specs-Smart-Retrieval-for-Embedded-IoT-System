"""Gate v3 — G2 Functional (P4_interfaces §2.3): code của câu trả lời -> analyze_c_code -> simulate_register_writes -> so `effects` với requirement
của Board State. `unmodeled` không bao giờ là pass. Dùng analyzer/simulator thật qua `call`; `call` giả chỉ để tiêm lỗi tool."""
import json

import pytest

from agent.gate import codeblocks, functional
from test_gate_support import CLK170, D1_DRAFT1_C, I2C_C, PWM_C, PWM_PA9_C, UART_C, Recorder, board, fenced, obs  # noqa: F401  (fixture)

R_PWM = {"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1.0, "status": "pending"}
R_UART = {"id": "R2", "type": "uart", "instance": "USART2", "baud": 9600, "tx_pin": "PA2", "rx_pin": "PA3", "status": "pending"}
R_I2C = {"id": "R3", "type": "i2c", "instance": "I2C3", "scl_hz": 100000, "scl_pin": "PC8", "sda_pin": "PC9", "status": "pending"}


def g2(code, reqs=None, initial=CLK170, hse_hz=None, call=None, chip="stm32g474", req_error=None, answer=None, observations=()):
    prog = codeblocks.program(answer if answer is not None else (fenced(code) if code else "No code."))
    return functional.run(call or Recorder(), prog, reqs, req_error, chip, initial, hse_hz, list(observations))


def codes(res):
    return [f.code for f in res.findings]


def errors(res):
    return [f.code for f in res.findings if f.severity == "error"]


def ok(res):
    """`status` là trạng thái nền (pass | skipped | na); Gate suy ra "fail" từ finding error."""
    return res.status == "pass" and errors(res) == []


# ------------------------------------------------------------------------------------------------ PWM
def test_correct_pwm_satisfies_its_requirement():
    res = g2(PWM_C, [R_PWM])
    assert ok(res) and res.findings == []
    assert res.details["requirements_checked"] == 1
    eff = res.sim["effects"][0]
    assert (eff["pin"], eff["signal"], eff["pwm_hz"], eff["duty_pct"]) == ("PA8", "TIM1_CH1", 20000.0, 25.0)


def test_wrong_frequency_gives_a_typed_g2_freq_finding():
    res = g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), [R_PWM])           # 170 MHz / 8400 = 20238 Hz (+1.19 %)
    assert errors(res) == ["G2-FREQ"]
    f = res.findings[0]
    assert f.where == "requirement R1 (PA8 PWM)" and f.expected == "20000 Hz ±1%"
    assert "20238" in f.actual and "solve_timer_config" in f.hint_source and "(PSC+1)(ARR+1)" in f.hint_source
    assert f.kind == "local" and not f.waivable


def test_default_pwm_tolerance_is_one_percent():
    req = {k: v for k, v in R_PWM.items() if k != "tol_pct"}
    assert errors(g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), [req])) == ["G2-FREQ"]       # +1.19 %
    assert ok(g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8580;"), [req]))                         # -0.94 %


def test_an_unrouted_required_channel_is_reported_once_by_the_simulator_code():
    code = PWM_C.replace("    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;\n", "")
    code = code.replace("    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);\n", "")
    res = g2(code, [R_PWM])
    assert errors(res) == ["G2-SIM-GPIO-AF"] and "TIM1_CH1" in res.findings[0].where


def test_frequency_and_duty_just_inside_the_tolerance_pass():
    res = g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8580;"), [R_PWM])           # 19811 Hz (-0.94 %), duty 24.76 %
    assert ok(res)


def test_wrong_duty_gives_g2_duty_in_percentage_points():
    res = g2(PWM_C.replace("TIM1->CCR1 = 2125;", "TIM1->CCR1 = 2500;"), [R_PWM])         # 29.4 %
    assert errors(res) == ["G2-DUTY"]
    assert res.findings[0].expected == "25% ±1 pp" and "29.4" in res.findings[0].actual


def test_missing_moe_is_reported_once_as_the_simulator_code_with_its_location():
    res = g2(PWM_C.replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", ""), [R_PWM])
    assert errors(res) == ["G2-SIM-TIM-MOE"]
    f = res.findings[0]
    assert "TIM1_CH1" in f.where and "PA8" in f.where and "MOE" in f.actual and "BDTR" in f.hint_source


def test_a_write_to_an_unclocked_peripheral_points_at_the_code_line_and_hides_its_consequences():
    """Mọi lệnh ghi TIM1 bị bỏ qua => CEN/CCE/OCM/MOE ở cuối chuỗi chỉ là hệ quả: chỉ báo nguyên nhân gốc (ghi trong details)."""
    res = g2(PWM_C.replace("    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;\n", ""), [R_PWM])
    assert errors(res) == ["G2-SIM-CLK-GATE"]
    f = res.findings[0]
    assert f.where.startswith("code block 1, line 6") and "TIM1->PSC = 0" in f.where and "RCC" in f.hint_source
    assert "SIM-TIM-CEN" in res.details["suppressed"]


def test_pwm_on_another_pin_is_a_pin_finding():
    res = g2(PWM_C, [{**R_PWM, "pin": "PA9", "signal": None}])
    assert errors(res) == ["G2-PIN"]
    assert "PA8" in res.findings[0].actual and res.findings[0].where == "requirement R1 (PA9 PWM)"


def test_an_unrouted_extra_channel_is_harmless_but_still_listed_in_the_simulation():
    code = PWM_C.replace("TIM1->CCER = TIM_CCER_CC1E;", "TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC2E;")
    res = g2(code, [R_PWM])
    assert ok(res)
    assert "SIM-GPIO-AF" in res.sim["violations"]


def test_center_aligned_pwm_is_unmodeled_and_waivable_never_a_pass():
    res = g2(PWM_C.replace("TIM1->CR1 = TIM_CR1_CEN;", "TIM1->CR1 = TIM_CR1_CEN | TIM_CR1_CMS_0;"), [R_PWM])
    assert errors(res) == ["G2-UNMODELED"]
    f = res.findings[0]
    assert f.waivable is True and "CMS" in f.actual and "waived_requirements" in f.hint_source


def test_pwm_requirement_without_pin_accepts_any_pin_with_the_right_signal():
    assert ok(g2(PWM_C, [{"id": "R1", "type": "pwm", "freq_hz": 20000, "duty_pct": 25}]))
    res = g2(PWM_C, [{"id": "R1", "type": "pwm", "freq_hz": 10000}])
    assert errors(res) == ["G2-FREQ"]


# ------------------------------------------------------------------------------------------------ UART / I2C / clock
def test_uart_requirement_pass_and_wrong_baud():
    assert ok(g2(UART_C, [R_UART], initial="reset"))
    res = g2(UART_C.replace("0x683", "0x341"), [R_UART], initial="reset")                  # 16 MHz / 833 = 19208 baud
    assert errors(res) == ["G2-BAUD"]
    assert res.findings[0].expected == "9600 baud ±2%" and "19207" in res.findings[0].actual


def test_uart_on_the_wrong_tx_pin_is_a_pin_finding():
    res = g2(UART_C, [{**R_UART, "tx_pin": "PB3"}], initial="reset")
    assert errors(res) == ["G2-PIN"] and "PA2" in res.findings[0].actual


def test_peripheral_switched_off_at_the_end_is_inactive():
    code = UART_C.replace("    while (1) { }", "    RCC->APB1ENR1 &= ~RCC_APB1ENR1_USART2EN;\n    while (1) { }")
    res = g2(code, [R_UART], initial="reset")
    assert errors(res) == ["G2-INACTIVE"] and "SIM-CLK-GATE" in res.findings[0].actual


def test_i2c_requirement_pass_and_wrong_scl():
    assert ok(g2(I2C_C, [R_I2C], initial="reset"))
    res = g2(I2C_C.replace("0x30420F13", "0x10420F13"), [R_I2C], initial="reset")          # PRESC 1 -> ~200 kHz
    assert errors(res) == ["G2-SCL"] and res.findings[0].expected == "100000 Hz ±5%"


def test_clock_requirement_checks_the_simulated_tree_with_exact_and_bound_keys():
    req = {"id": "R4", "type": "clock", "sysclk_hz": 170_000_000}
    assert ok(g2(PWM_C, [req], initial=CLK170))
    res = g2(PWM_C, [req], initial="reset")
    assert errors(res) == ["G2-CLOCK"] and "16000000" in res.findings[0].actual
    assert ok(g2(PWM_C, [{"id": "R4", "type": "clock", "pclk2_max_hz": 170_000_000}], initial=CLK170))
    assert errors(g2(PWM_C, [{"id": "R4", "type": "clock", "sysclk_min_hz": 100_000_000}], initial="reset")) == ["G2-CLOCK"]


def test_requirement_types_the_simulator_does_not_model_are_unmodeled_when_code_exists():
    reqs = [R_PWM, {"id": "R5", "type": "spi", "instance": "SPI1"}, {"id": "R6", "type": "power", "mode": "sleep", "budget_ua": 10},
            {"id": "R7", "type": "other"}]
    res = g2(PWM_C, reqs)
    assert errors(res) == ["G2-UNMODELED"]
    assert res.findings[0].where.startswith("requirement R5") and res.findings[0].waivable


def test_no_effect_for_a_pending_requirement_is_an_error():
    res = g2(UART_C, [R_UART, R_PWM], initial="reset")
    assert errors(res) == ["G2-NO-EFFECT"] and res.findings[0].where.startswith("requirement R1")


def test_satisfied_requirement_from_an_earlier_turn_whose_kind_is_absent_is_not_rechecked_and_g2_is_not_a_pass():
    """Fix round 1 (I1, I7): không kiểm lại => cảnh báo G2-NOT-IN-CODE và trạng thái `skipped` (không bao giờ `pass`)."""
    done = {**R_PWM, "status": "satisfied", "evidence": "sim#3"}
    res = g2(UART_C, [R_UART, done], initial="reset")
    assert res.status == "skipped" and errors(res) == [] and codes(res) == ["G2-NOT-IN-CODE"]
    assert res.findings[0].severity == "warning" and res.details["not_rechecked"] == ["R1"]
    # satisfied nhưng code của lượt này có đụng tới: kiểm lại đầy đủ
    res = g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), [done])
    assert errors(res) == ["G2-FREQ"]


# ------------------------------------------------------------------------------------------------ không requirement / không code / lỗi phân tích
def test_without_requirements_only_op_level_and_routed_channel_violations_count():
    res = g2(PWM_C.replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", ""), None)
    assert errors(res) == ["G2-SIM-TIM-MOE"] and res.details["requirements_checked"] == 0
    code = PWM_C.replace("TIM1->CCER = TIM_CCER_CC1E;", "TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC2E;")
    assert ok(g2(code, None))                                                  # kênh 2 không nối chân: vô hại


def test_no_code_is_not_applicable_with_a_warning_only_if_a_modelable_requirement_exists():
    res = g2(None, [R_PWM])
    assert res.status == "na" and codes(res) == ["G2-NO-CODE"] and res.findings[0].severity == "warning"
    assert g2(None, [{"id": "R9", "type": "power", "mode": "sleep", "budget_ua": 3}]).findings == []
    assert g2(None, None).status == "na"


def test_unsupported_construct_points_at_block_and_line():
    code = PWM_C.replace("TIM1->PSC = 0;", "HAL_TIM_PWM_Start(0, 0);")
    res = g2(code, [R_PWM], answer="Intro\n```python\nprint(1)\n```\n" + fenced(code))
    assert errors(res) == ["G2-UNSUPPORTED"]
    f = res.findings[0]
    assert f.where == "code block 2, line 7" and "HAL_TIM_PWM_Start" in f.actual and f.hint_source == "analyze_c_code"


def test_fragment_answers_are_simulated_inside_a_wrapper_function():
    ans = "Set the divider:\n```c\nRCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;\nUSART2->BRR = 0x683;\nUSART2->CR1 = USART_CR1_TE | USART_CR1_UE;\n```"
    res = g2(None, [{"id": "R2", "type": "uart", "instance": "USART2", "baud": 9600}], initial="reset", answer=ans)
    assert ok(res) and res.sim["effects"][0]["baud"] == pytest.approx(9598.08, abs=0.01)


# ------------------------------------------------------------------------------------------------ lỗi tool => unknown / skipped, không bao giờ pass
@pytest.mark.parametrize("tool", ["analyze_c_code", "simulate_register_writes"])
def test_a_tool_error_fails_closed_when_code_meets_a_modelable_requirement(tool):
    """Fix round 1 (C1): code + requirement mô phỏng được mà G2 không chạy xong => error (không phải unknown/skipped)."""
    res = g2(PWM_C, [R_PWM], call=Recorder({tool: {"error": "timed out after 60 s"}}))
    assert errors(res) == ["G2-TOOL-ERROR"]
    f = res.findings[0]
    assert f.kind == "local" and tool in f.where and "timed out" in f.actual and f.expected and f.hint_source


@pytest.mark.parametrize("reqs", [None, [{"id": "P1", "type": "power", "mode": "sleep", "budget_ua": 10}]])
def test_a_tool_error_is_unknown_when_there_is_no_modelable_requirement(reqs):
    res = g2(PWM_C, reqs, call=Recorder({"analyze_c_code": {"error": "timed out after 60 s"}}))
    assert res.status == "skipped" and codes(res) == ["G2-TOOL-ERROR"] and res.findings[0].severity == "unknown"


def test_missing_toolchain_in_the_analyzer_is_a_tool_problem_not_a_code_error():
    no_clang = {"ok": False, "chip": "stm32g474", "ops": [], "unsupported": [{"kind": "no_toolchain", "line": None, "msg": "clang is not installed",
                                                                           "construct": "clang"}], "notes": [], "complete": False}
    res = g2(PWM_C, [R_PWM], call=Recorder({"analyze_c_code": no_clang}))
    assert errors(res) == ["G2-TOOL-ERROR"]                                              # fail closed (C1)
    res = g2(PWM_C, None, call=Recorder({"analyze_c_code": no_clang}))
    assert res.status == "skipped" and res.findings[0].severity == "unknown"


def test_unreadable_requirements_never_pass():
    res = g2(PWM_C, None, req_error="get_board_state: database is locked")
    assert res.status == "skipped" and codes(res) == ["G2-TOOL-ERROR"] and res.findings[0].severity == "unknown"


def test_chip_without_simulator_model_makes_requirements_unmodeled():
    res = g2(PWM_C, [R_PWM], chip="esp32")
    assert errors(res) == ["G2-UNMODELED"]
    res = g2(PWM_C, None, chip="esp32")
    assert res.status == "skipped" and codes(res) == ["G2-SKIPPED"] and res.findings[0].severity == "unknown"


# ------------------------------------------------------------------------------------------------ trạng thái khởi đầu + tóm tắt mô phỏng
def test_start_state_priority_requirement_code_agent_simulation_context_default():
    """Fix round 1 (C2): requirement > code tự cấu hình clock (=> reset) > lần simulate THÀNH CÔNG gần nhất của agent > ctx.initial > reset."""
    sim80 = obs("simulate_register_writes", {"ok": True, "effects": [], "violations": []}, chip="stm32g474", ops=[],
                initial="sysclk_80mhz_pll_hsi16_apb_div1", hse_hz=8_000_000)
    failed = obs("simulate_register_writes", {"error": "unknown initial state 'sysclk_170mhz'"}, chip="stm32g474", ops=[], initial="sysclk_170mhz")
    clock_ops = [{"op": "set_bits", "reg": "RCC_CFGR", "mask": 3}]
    other_ops = [{"op": "write", "reg": "TIM1_PSC", "value": 0}]
    rs = functional.resolve_start
    assert rs([{**R_PWM, "initial": CLK170, "hse_hz": 24_000_000}], clock_ops, [sim80], "reset", None) == (CLK170, 24_000_000, "requirement")
    assert rs([R_PWM], clock_ops, [sim80], CLK170, None) == ("reset", 8_000_000, "code_configures_clock")
    assert rs([R_PWM], other_ops, [sim80, failed], CLK170, None) == ("sysclk_80mhz_pll_hsi16_apb_div1", 8_000_000, "agent_simulation")
    assert rs([R_PWM], other_ops, [failed], "sysclk_170mhz_pll_hsi16_apb2_div2", None) == ("sysclk_170mhz_pll_hsi16_apb2_div2", None, "context")
    assert rs(None, other_ops, [], "reset", None) == ("reset", None, "default")


@pytest.mark.parametrize("op", [{"op": "write", "reg": "RCC_CFGR", "value": 0}, {"op": "clear_bits", "reg": "RCC_CFGR", "mask": 3},
                                {"op": "modify", "reg": "RCC_CFGR", "mask": 3, "value": 3}, {"op": "rmw", "reg": "RCC_CFGR", "and": 0xFFFFFFFC, "or": 3},
                                {"op": "write", "reg": "RCC_PLLCFGR", "value": 1 << 24}])
def test_writes_to_the_clock_switch_or_the_pll_count_as_configuring_the_clock(op):
    assert functional.resolve_start(None, [op], [], CLK170, None)[2] == "code_configures_clock"


def test_other_rcc_cfgr_fields_do_not_count_as_configuring_the_clock():
    assert functional.resolve_start(None, [{"op": "modify", "reg": "RCC_CFGR", "mask": 0xF0, "value": 0x80}], [], CLK170, None)[2] == "context"


def test_the_simulation_used_by_g2_is_the_one_resolved_and_the_summary_is_compact():
    rec = Recorder()
    res = g2(PWM_C, [R_PWM], initial=CLK170, call=rec)
    sim_call = next(a for n, a in rec.calls if n == "simulate_register_writes")
    assert sim_call["initial"] == CLK170 and sim_call["chip"] == "stm32g474"
    json.dumps(res.sim)
    assert set(res.sim) >= {"ok", "violations", "effects", "unmodeled", "initial", "n_ops"} and res.sim["initial"] == CLK170
    assert len(res.sim.get("final_registers", {})) <= 40
    assert all(name in ("analyze_c_code", "simulate_register_writes") for name in rec.names())


def test_an_empty_or_unchecked_requirement_list_behaves_like_no_requirements():
    """Board State có nhưng không có requirement kiểm được => cùng chế độ với board=False (lỗi tại lệnh + kênh đã nối chân)."""
    code = PWM_C.replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", "")
    for reqs in ([], [{"id": "P1", "type": "power", "mode": "sleep", "budget_ua": 10}]):
        res = g2(code, reqs)
        assert errors(res) == ["G2-SIM-TIM-MOE"] and res.details["requirements_checked"] == 0, reqs


# ================================================================================================ fix round 1 (gate_review.md)
WRONG_PSC = PWM_C.replace("TIM1->PSC = 0;", "TIM1->PSC = 1;")                       # 10 kHz


def test_c1_explicit_null_options_fall_back_to_their_defaults():
    req = {**R_PWM, "tol_pct": None, "duty_tol_pp": None}
    assert errors(g2(WRONG_PSC, [req])) == ["G2-FREQ"]
    assert ok(g2(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8580;"), [req]))           # -0,94 %: dung sai mặc định 1 %
    assert errors(g2(WRONG_PSC, [{**R_PWM, "freq_hz": None}])) == []                       # không có tần số mục tiêu -> không kiểm tần số
    for typ, extra in (("uart", {"instance": "USART2", "baud": 9600, "tol_pct": None}), ("i2c", {"instance": "I2C3", "scl_hz": 100000, "tol_pct": None})):
        g2(UART_C if typ == "uart" else I2C_C, [{"id": "RX", "type": typ, **extra}], initial="reset")


def test_c1_a_requirement_start_state_typo_fails_closed_with_a_fix_hint():
    res = g2(WRONG_PSC, [{**R_PWM, "initial": "170mhz"}])
    assert errors(res) == ["G2-INITIAL"]
    f = res.findings[0]
    assert "170mhz" in f.actual and "R1" in f.hint_source and "set_requirements" in f.hint_source


def test_c1_a_failed_agent_simulation_is_not_inherited():
    good = obs("simulate_register_writes", {"ok": True, "effects": [], "violations": []}, chip="stm32g474", ops=[], initial="reset")
    bad = obs("simulate_register_writes", {"error": "ValueError: unknown initial state 'sysclk_170mhz'"}, chip="stm32g474", ops=[], initial="sysclk_170mhz")
    res = g2(WRONG_PSC, [R_PWM], initial="reset", observations=[good, bad])
    assert errors(res) == ["G2-FREQ"] and res.details["start"] == {"initial": "reset", "hse_hz": None, "source": "agent_simulation"}


@pytest.mark.parametrize("reqs", [[R_PWM], None])
def test_c1_a_loop_unrolled_beyond_the_simulator_limit_is_unsupported(reqs):
    code = WRONG_PSC.replace("TIM1->PSC = 1;", "for (int i = 0; i < 3000; i++) { TIM1->CCR2 = 1; }\n    TIM1->PSC = 1;")
    rec = Recorder()
    res = g2(code, reqs, call=rec)
    assert errors(res) == ["G2-UNSUPPORTED"] and "3011" in res.findings[0].actual and "loop" in res.findings[0].hint_source
    assert "simulate_register_writes" not in rec.names()                                    # không gọi một lần mô phỏng chắc chắn bị từ chối


def test_c2_code_that_configures_the_clock_itself_is_simulated_from_reset():
    req = {"id": "REQ-PWM-PA8", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 0.1}
    res = g2(D1_DRAFT1_C, [req], initial=CLK170)
    assert ok(res) and "G2-SIM-FLASH-WS" not in codes(res)
    assert res.details["start"] == {"initial": "reset", "hse_hz": None, "source": "code_configures_clock"}


def test_c2_a_start_state_dict_with_ops_is_never_inherited_from_the_agent():
    launder = {"preset": CLK170, "ops": [{"op": "set_bits", "reg": "RCC_APB2ENR", "mask": 1 << 11}, {"op": "set_bits", "reg": "TIM1_BDTR", "mask": 1 << 15}]}
    agent_sim = obs("simulate_register_writes", {"ok": True, "effects": [], "violations": []}, chip="stm32g474", ops=[], initial=launder)
    code = PWM_C.replace("    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;\n", "").replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", "")
    res = g2(code, [R_PWM], initial=launder, observations=[agent_sim])
    assert "G2-SIM-CLK-GATE" in errors(res) and res.details["start"]["source"] == "default"


def test_c2_a_requirement_preset_dict_is_used_without_its_ops():
    req = {**R_PWM, "initial": {"preset": CLK170, "ops": [{"op": "set_bits", "reg": "TIM1_BDTR", "mask": 1 << 15}]}}
    res = g2(PWM_C.replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", ""), [req], initial="reset")
    assert errors(res) == ["G2-SIM-TIM-MOE"] and res.details["start"] == {"initial": CLK170, "hse_hz": None, "source": "requirement"}


def test_i1_a_satisfied_requirement_is_rechecked_when_the_code_has_an_effect_of_its_kind():
    done = {**R_PWM, "status": "satisfied", "evidence": "sim#1"}
    assert errors(g2(PWM_PA9_C, [done])) == ["G2-PIN"]
    uart_done = {**R_UART, "status": "satisfied", "evidence": "sim#2"}
    usart1 = UART_C.replace("USART2", "USART1").replace("RCC->APB1ENR1 |= RCC_APB1ENR1_USART1EN", "RCC->APB2ENR |= RCC_APB2ENR_USART1EN")
    assert errors(g2(usart1, [uart_done], initial="reset")) == ["G2-NO-EFFECT"]


def test_i1_a_requirement_set_in_this_turn_is_always_checked():
    done = {**R_PWM, "status": "satisfied", "evidence": "sim#1"}
    set_now = obs("set_requirements", {"ok": True, "version": 4, "requirements": [done]}, requirements=[done])
    res = g2(UART_C, [R_UART, done], initial="reset", observations=[set_now])
    assert errors(res) == ["G2-NO-EFFECT"] and res.findings[0].where.startswith("requirement R1")


def test_i6_register_snippets_without_requirements_report_end_of_program_and_clock_gate_as_warnings():
    gpio = ("```c\nRCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;\nGPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8) | GPIO_MODER_MODE8_1;\n"
            "GPIOA->AFR[1] = (GPIOA->AFR[1] & ~GPIO_AFRH_AFSEL8) | (6U << GPIO_AFRH_AFSEL8_Pos);\n```\n")
    res = g2(None, None, initial="reset", answer=gpio)
    assert ok(res)
    res = g2(None, None, initial="reset", answer="```c\nTIM1->BDTR |= TIM_BDTR_MOE;\n```\n")
    assert ok(res) and [(f.code, f.severity) for f in res.findings] == [("G2-SIM-CLK-GATE", "warning")]


def test_requirement_ids_with_spaces_are_quoted_in_where():
    res = g2(WRONG_PSC, [{**R_PWM, "id": "PWM PA8"}])
    assert res.findings[0].where == 'requirement "PWM PA8" (PA8 PWM)'


# ================================================================================================ fix round 2 (re-review)
R2_I2C = {"id": "R2", "type": "i2c", "instance": "I2C3", "scl_hz": 100000, "scl_pin": "PC8", "sda_pin": "PC9"}


def _turn2(srv, resent):
    """Lượt 1: R1 (PWM PA8) đã satisfied. Lượt 2: agent gửi lại `resent` bằng set_requirements; câu trả lời chỉ có code I2C3."""
    srv.set_target("stm32g474", "LQFP64", 3.3)
    assert srv.set_requirements([{**R_PWM, "status": "satisfied", "evidence": "sim#1"}])["ok"]
    r = srv.set_requirements(resent)
    assert r["ok"]
    current = srv.get_board_state(section="requirements")["data"]
    return current, [obs("set_requirements", r, requirements=resent)]


def test_i4_resending_an_unchanged_requirement_with_status_or_evidence_does_not_force_a_recheck(board):
    current, observations = _turn2(board, [{**R_PWM, "status": "satisfied", "evidence": "sim#1b"}, {**R2_I2C, "status": "satisfied", "evidence": "sim#2"}])
    res = g2(I2C_C, current, initial="reset", observations=observations)
    assert errors(res) == [] and res.details["not_rechecked"] == ["R1"]


def test_i4_a_requirement_whose_specification_changed_this_turn_is_checked(board):
    current, observations = _turn2(board, [{**R_PWM, "freq_hz": 25000, "status": "satisfied", "evidence": "sim#1"}, {**R2_I2C, "status": "satisfied"}])
    res = g2(I2C_C, current, initial="reset", observations=observations)
    assert errors(res) == ["G2-NO-EFFECT"] and res.findings[0].where.startswith("requirement R1")


def test_i4_without_a_known_earlier_state_a_resent_requirement_is_checked():
    done = {**R_PWM, "status": "satisfied", "evidence": "sim#1"}
    set_now = obs("set_requirements", {"ok": True, "requirements": [done]}, requirements=[done])           # không có "version"
    assert errors(g2(UART_C, [R_UART, done], initial="reset", observations=[set_now])) == ["G2-NO-EFFECT"]


@pytest.mark.parametrize("op,configures", [({"op": "set_bits", "reg": "RCC_PLLCFGR", "mask": 1 << 20}, False),          # PLLQEN
                                           ({"op": "set_bits", "reg": "RCC_PLLCFGR", "mask": 1 << 16}, False),          # PLLPEN
                                           ({"op": "modify", "reg": "RCC_PLLCFGR", "mask": 0xF << 4, "value": 3 << 4}, True),   # PLLM
                                           ({"op": "set_bits", "reg": "RCC_PLLCFGR", "mask": 1 << 24}, True),           # PLLREN
                                           ({"op": "rmw", "reg": "RCC_PLLCFGR", "and": ~(0x7F << 8) & 0xFFFFFFFF, "or": 85 << 8}, True)])   # PLLN
def test_m1_only_the_pll_source_dividers_and_r_output_count_as_configuring_the_clock(op, configures):
    assert (functional.resolve_start(None, [op], [], CLK170, None)[2] == "code_configures_clock") is configures
