"""Gate v3 — G1 Provenance (P4_interfaces §2.3): số/địa chỉ/trích dẫn trong VĂN XUÔI phải truy được về (a) tra cứu, (b) output solver/simulator/board,
(c) người dùng — hoặc suy ra bằng MỘT phép tính đơn giản. Hai chiều: câu đúng mà verifier v1 từ chối phải qua; câu bịa phải trượt."""
import pytest

from agent.gate import provenance as pv
from test_gate_support import CLK170, I2C_C, PWM_C, UART_C, board, fenced, obs  # noqa: F401  (fixture)


@pytest.fixture(scope="module")
def ev():
    from mcp_servers import hw_knowledge_server as hk
    from mcp_servers import hw_sandbox_server as sb
    pwm_an = sb.analyze_c_code(PWM_C)
    uart_an = sb.analyze_c_code(UART_C)
    i2c_an = sb.analyze_c_code(I2C_C)
    return {
        "pin": obs("query_pin_alternate_function", hk.query_pin_alternate_function("stm32g474", "PA8"), chip="stm32g474", pin="PA8"),
        "solver": obs("solve_timer_config", sb.solve_timer_config("stm32g474", "TIM1", 20000, 25, 1, tim_clk_hz=170_000_000)),
        "pwm_sim": obs("simulate_register_writes", sb.simulate_register_writes("stm32g474", pwm_an["ops"], initial=CLK170)),
        "uart_an": obs("analyze_c_code", uart_an),
        "uart_sim": obs("simulate_register_writes", sb.simulate_register_writes("stm32g474", uart_an["ops"])),
        "i2c_sim": obs("simulate_register_writes", sb.simulate_register_writes("stm32g474", i2c_an["ops"])),
        "vdd_abs": obs("get_electrical_specs", hk.get_electrical_specs("stm32g474", "supply voltage", category="absolute_max")),
        "brr": obs("get_register_bitfields", hk.get_register_bitfields("stm32g474", "USART2", "BRR")),
        "rcr": obs("get_register_bitfields", hk.get_register_bitfields("stm32g474", "TIM2", "RCR")),
        "manual": obs("search_manual", {"query": "USART baud rate", "results": [
            {"chunk_id": "STM32G474_RM0440:03539", "doc": "STM32G474_RM0440", "page": 1707, "page_start": 1707, "page_end": 1708,
             "text": "40.5.7 USART baud rate generation. The baud rate is programmed in the USART_BRR register."}]}),
    }


def g1(answer, user=(), observations=(), prior=(), strict=False):
    return pv.check(answer, list(user), list(observations), list(prior), strict_v1=strict)


def codes(findings):
    return [f.code for f in findings]


PWM_Q = "Generate CMSIS code for a 20 kHz, 25 % PWM on PA8 of the STM32G474 running at 170 MHz."
UART_Q = "Set up USART2 at 9600 baud on PA2/PA3; the MCU runs from HSI16 at 16 MHz."


# ------------------------------------------------------------------------------------------------ đúng => qua
def test_correct_pwm_answer_with_tool_values_and_a_returned_citation_passes(ev):
    ans = ("PA8 carries TIM1_CH1 on AF6 [STM32G474_Datasheet p.73]. With TIM1 clocked at 170 MHz, PSC = 0 and ARR = 8499 give "
           "170 MHz / 8500 = 20 kHz, and CCR1 = 2125 gives 25 % duty. The simulator confirms 20000 Hz on PA8.\n\n") + fenced(PWM_C)
    status, findings, details = g1(ans, [PWM_Q], [ev["pin"], ev["solver"], ev["pwm_sim"]])
    assert (status, findings) == ("pass", [])
    assert details["claims_checked"] == 4


def test_brr_value_computed_by_the_simulator_passes_but_the_v1_verifier_rejects_it(ev):
    ans = ("USART2 is clocked from PCLK1 = 16 MHz, so USARTDIV = 16 MHz / 9600 ≈ 1667 and BRR = 0x683; "
           "the simulated rate is 9598 baud (0.02 % error).")
    assert g1(ans, [UART_Q], [ev["uart_sim"]])[:2] == ("pass", [])
    status, findings, details = g1(ans, [UART_Q], [ev["uart_sim"]], strict=True)          # sim trả "0x00000683", không có chuỗi "0x683"
    assert status == "fail" and "G1-V2" in codes(findings) and details["mode"] == "v1"


def test_brr_computed_by_the_agent_from_user_numbers_is_accepted_as_derived():
    status, findings, details = g1("BRR = 16 MHz / 9600 = 1666.7, rounded to 0x683.", ["USART2 at 9600 baud, PCLK1 is 16 MHz."])
    assert (status, findings) == ("pass", [])
    assert any(d["claim"] == "0x683" for d in details["derived"])


def test_clock_divided_by_a_user_prescaler_passes_new_g1_but_fails_v1():
    user = ["SYSCLK is 170 MHz and the APB1 prescaler is 2."]
    ans = "PCLK1 = 170 MHz / 2 = 85 MHz, and the APB1 timers run at 2 x 85 MHz = 170 MHz."
    assert g1(ans, user)[:2] == ("pass", [])
    status, findings, _ = g1(ans, user, strict=True)
    assert status == "fail" and codes(findings)[0] == "G1-V1" and "85" in findings[0].actual


def test_a_derived_value_can_feed_the_next_step_of_the_same_answer():
    user = ["HSI16 (16 MHz) feeds the PLL with PLLM = 4 and PLLN = 85."]
    assert g1("The PLL input is 16 MHz / 4 = 4 MHz and the VCO runs at 4 MHz x 85 = 340 MHz.", user)[:2] == ("pass", [])


def test_rounded_simulator_value_passes_but_a_value_off_by_more_than_half_a_percent_fails(ev):
    """Mô phỏng: scl_hz = 108108.1 Hz. 108.5 kHz lệch 0,36 % (qua); 109 kHz lệch 0,83 % (trượt)."""
    for claim in ("108.1 kHz", "108.5 kHz"):
        assert g1(f"SCL runs at about {claim} with the minimum tSYNC.", ["I2C3 at 100 kHz"], [ev["i2c_sim"]])[:2] == ("pass", []), claim
    status, findings, _ = g1("SCL runs at about 109 kHz with the minimum tSYNC.", ["I2C3 at 100 kHz"], [ev["i2c_sim"]])
    assert status == "fail" and codes(findings) == ["G1-V1"]


def test_register_value_plus_one_is_accepted_for_hex_claims_only_within_one_count(ev):
    assert g1("The counter period is 0x2134 ticks (ARR + 1).", [PWM_Q], [ev["pwm_sim"]])[:2] == ("pass", [])
    status, findings, _ = g1("The counter period is 0x2136 ticks (ARR + 1).", [PWM_Q], [ev["pwm_sim"]])
    assert status == "fail" and codes(findings) == ["G1-V2"]


def test_32_bit_register_value_from_final_registers_is_a_value_not_an_address(ev):
    assert g1("After the writes GPIOA_MODER reads 0xABFEFFFF.", [PWM_Q], [ev["pwm_sim"]])[:2] == ("pass", [])


def test_values_inside_the_c_code_g2_analyses_are_left_to_g2(ev):
    """Fix round 1 (C3): chỉ khối C mà G2 phân tích bị bỏ qua; mã nội tuyến và khối không phải C được G1 kiểm (xem test bên dưới)."""
    code = PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8499;   /* 0xDEADBEEF, 12 V */")
    ans = "Use `TIM1->ARR = 8499` style writes; the PWM runs at 20 kHz.\n\n" + fenced(code)
    assert g1(ans, [PWM_Q], [ev["pwm_sim"]])[:2] == ("pass", [])


def test_prior_accepted_answers_count_as_evidence():
    assert g1("As before, PCLK1 stays at 85 MHz.", ["Now add a UART."], prior=["PCLK1 = 85 MHz after the APB1 divider."])[:2] == ("pass", [])


def test_abstention_is_accepted():
    status, findings, details = g1("Insufficient evidence: none of the documents I retrieved state the rise time.", ["What is the rise time?"])
    assert (status, findings) == ("pass", []) and details["abstained"] is True


# ------------------------------------------------------------------------------------------------ bịa => trượt
def test_invented_absolute_maximum_fails_while_the_datasheet_value_passes(ev):
    user = ["What is the absolute maximum supply voltage of the STM32G474?"]
    status, findings, _ = g1("The absolute maximum rating for VDD is 4.8 V [STM32G474_Datasheet p.82].", user, [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V1"]
    f = findings[0]
    assert f.where == 'answer: "4.8 V"' and "4.8 V" in f.actual and "absolute maximum rating" in f.actual and f.hint_source and f.expected
    assert g1("The absolute maximum rating for VDD is 4.0 V [STM32G474_Datasheet p.82].", user, [ev["vdd_abs"]])[:2] == ("pass", [])


def test_a_value_found_only_in_a_lookup_needs_a_citation_and_the_hint_names_the_source(ev):
    status, findings, _ = g1("The absolute maximum rating for VDD is 4.0 V.", ["What is the absolute maximum VDD?"], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V3"]
    assert "[STM32G474_Datasheet p.82]" in findings[0].hint_source


def test_citation_must_have_been_returned_by_a_tool_including_page_ranges(ev):
    status, findings, _ = g1("The absolute maximum VDD is 4.0 V [STM32G474_Datasheet p.99].", ["max VDD?"], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V3"] and "p.99" in findings[0].actual
    assert g1("BRR is described in [RM0440 p.1708].", ["baud?"], [ev["manual"]])[:2] == ("pass", [])


def test_invented_register_address_fails_while_the_returned_one_passes_case_insensitively(ev):
    status, findings, _ = g1("USART2_BRR sits at 0x40004410 [STM32G474_RM0440 p.1755].", ["Where is USART2_BRR?"], [ev["brr"]])
    assert status == "fail" and codes(findings) == ["G1-V2"] and "get_register_bitfields" in findings[0].hint_source
    for addr in ("0x4000440C", "0x4000440c"):
        assert g1(f"USART2_BRR sits at {addr} [STM32G474_RM0440 p.1755].", ["Where is USART2_BRR?"], [ev["brr"]])[:2] == ("pass", [])


def test_an_address_only_seen_in_analyzer_output_is_not_documentation(ev):
    status, findings, _ = g1("RCC_AHB2ENR is at 0x4002104C.", [UART_Q], [ev["uart_an"], ev["uart_sim"]])
    assert status == "fail" and codes(findings) == ["G1-V2"]


def test_svd_only_register_may_be_cited_by_its_svd_document(ev):
    for cite in ("[STM32G474_SVD]", "[STM32G474_SVD SVD]", "[STM32G474 SVD]"):
        assert g1(f"TIM2_RCR is at 0x40000030 {cite}.", ["TIM2 RCR?"], [ev["rcr"]])[:2] == ("pass", []), cite
    status, findings, _ = g1("USART2_BRR is at 0x4000440C [STM32G474_SVD].", ["BRR?"], [ev["brr"]])
    assert status == "fail" and codes(findings) == ["G1-V3"]


def test_unit_claim_is_not_supported_by_a_bare_integer_from_a_simulation(ev):
    """v1 chấp nhận '6 V' vì số 6 (AF6) có trong JSON mô phỏng; G1 mới đòi đúng đại lượng."""
    ans = "Drive the gate with 6 V."
    assert g1(ans, [PWM_Q], [ev["pwm_sim"]], strict=True)[0] == "fail"           # v1: còn trượt V3 (không trích dẫn)
    _, v1_findings, _ = g1(ans, [PWM_Q], [ev["pwm_sim"]], strict=True)
    assert "G1-V1" not in codes(v1_findings)
    status, findings, _ = g1(ans, [PWM_Q], [ev["pwm_sim"]])
    assert status == "fail" and codes(findings) == ["G1-V1"]


def test_agent_text_echoed_by_control_tools_is_not_evidence():
    observations = [obs("update_plan", {"ok": True, "plan": [{"id": "S1", "title": "use the 4.8 V absolute maximum"}]}),
                    obs("record_decision", {"ok": True, "decision": {"id": "D1", "question": "VDD?", "options": ["4.8 V"], "chosen": "4.8 V",
                                                                     "rationale": "4.8 V is the limit"}}),
                    obs("simulate_register_writes", {"error": "VDD 4.8 V rejected"})]
    status, findings, _ = g1("The limit is 4.8 V.", ["What is the limit?"], observations)
    assert status == "fail" and codes(findings) == ["G1-V1"]


def test_a_late_disclaimer_does_not_turn_a_design_answer_into_an_abstention():
    ans = ("Configure the PLL for 170 MHz and keep VDD at 3.3 V. The flash needs 4 wait states and the regulator must be in boost mode, "
           "so the core can reach full speed; the decoupling network should use 4.7 uF and 100 nF capacitors near each VDD pin. "
           "Keep the traces short and route the ground return under the MCU. I cannot verify the exact start-up time of the regulator.")
    status, findings, details = g1(ans, ["Run the STM32G474 at 170 MHz from 3.3 V."])
    assert status == "fail" and details["abstained"] is False and set(codes(findings)) == {"G1-V1"}


def test_operating_question_answered_only_from_absolute_maximum_facts_is_field_confusion(ev):
    status, findings, _ = g1("VDD may go up to 4.0 V [STM32G474_Datasheet p.82].", ["What is the recommended operating supply voltage?"],
                             [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V4"]


def test_strict_mode_maps_every_v1_issue_to_a_typed_finding(ev):
    status, findings, details = g1("VDD is 4.8 V at 0x40004410.", ["max VDD?"], [ev["vdd_abs"]], strict=True)
    assert status == "fail" and details["mode"] == "v1"
    assert codes(findings) == ["G1-V1", "G1-V2", "G1-V3"]
    assert all(f.gate == "G1" and f.where and f.expected and f.actual and f.hint_source for f in findings)


def test_every_new_g1_finding_is_complete_and_local(ev):
    _, findings, _ = g1("VDD is 4.8 V at 0x40004410, see [STM32G474_Datasheet p.99].", ["max VDD?"], [ev["vdd_abs"]])
    assert codes(findings) == ["G1-V1", "G1-V2", "G1-V3"]
    assert all(f.gate == "G1" and f.kind == "local" and f.severity == "error" and not f.waivable for f in findings)
    assert all(f.where and f.expected and f.actual and f.hint_source for f in findings)


def test_a_plain_limit_value_with_a_unit_column_supports_the_same_quantity_with_another_prefix():
    from mcp_servers import hw_knowledge_server as hk
    limits = obs("get_clock_limits", hk.get_clock_limits("stm32g474", "HCLK"), chip="stm32g474", parameter="HCLK")
    assert g1("HCLK may not exceed 0.17 GHz [STM32G474_Datasheet p.84].", ["max HCLK?"], [limits])[:2] == ("pass", [])


def test_a_period_register_value_is_accepted_when_its_ratio_is_written_out():
    """Fix round 1 (I2): một tỉ số chỉ được chấp nhận khi phép tính có mặt trong câu (trước đây: tỉ số hai số người dùng bất kỳ)."""
    user = ["TIM1 runs at 170 MHz and the PWM must be 20 kHz."]
    assert g1("The timer period is 170 MHz / 20 kHz = 0x2134 counts, so ARR = 0x2134 - 1 = 0x2133.", user)[:2] == ("pass", [])
    for ans in ("The timer period is 0x2134 counts.", "The timer period is 170 MHz / 20 kHz = 0x2200 counts."):
        status, findings, _ = g1(ans, user)
        assert status == "fail" and codes(findings) == ["G1-V2"], ans


@pytest.fixture(scope="module")
def d1_session(ev, tmp_path_factory):
    """Bằng chứng của một phiên D1 thật: tra chân, solver, mô phỏng, Board State (target + clock + requirement)."""
    import os
    from mcp_servers import board_state_server as bs
    old = os.environ.get("BOARD_STATE_DB")
    os.environ["BOARD_STATE_DB"] = str(tmp_path_factory.mktemp("d1") / "bs.sqlite")
    try:
        target = bs.set_target("stm32g474", "LQFP64", 3.3, project_id="d1")
        clock = bs.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2}, "apb1_div": 2,
                                     "enabled_peripherals": ["GPIOA", "TIM1"]}, project_id="d1")
        bs.set_requirements([{"id": "R1", "type": "pwm", "pin": "PA8", "freq_hz": 20000, "duty_pct": 25}], project_id="d1")
        state = bs.get_board_state(project_id="d1")
    finally:
        if old is None:
            os.environ.pop("BOARD_STATE_DB", None)
        else:
            os.environ["BOARD_STATE_DB"] = old
    return [ev["pin"], ev["solver"], ev["pwm_sim"], obs("set_target", target), obs("set_clock_config", clock), obs("get_board_state", state)]


@pytest.mark.parametrize("claim", ["The HSE crystal must be 25 MHz.", "The absolute maximum VDD is 4.5 V.", "Each I/O can source 25 mA.",
                                   "TIM1 accepts up to 200 MHz.", "The VCO may reach 400 MHz.", "Add a 100 nF capacitor.", "The pin rise time limit is 12 MHz.",
                                   "VDDA must stay below 3.0 V.", "BRR = 0x1A1.", "RCC_APB2ENR is at 0x40021060."])
def test_plausible_hallucinations_are_rejected_even_with_a_full_design_session_in_evidence(d1_session, claim):
    status, findings, _ = g1(claim, [PWM_Q], d1_session)
    assert status == "fail" and codes(findings)[0] in ("G1-V1", "G1-V2"), claim


@pytest.mark.parametrize("claim", ["PCLK1 is 85 MHz and the APB1 timers run at 170 MHz.", "The VCO runs at 340 MHz from a 4 MHz PLL input.",
                                   "The board supply is 3.3 V.", "ARR = 0x2133 and CCR1 = 0x84D.", "The PWM period is 0x2134 timer ticks."])
def test_values_computed_in_the_session_are_accepted(d1_session, claim):
    assert g1(claim, [PWM_Q], d1_session)[:2] == ("pass", []), claim


def test_a_division_written_out_in_the_sentence_is_accepted_but_the_same_value_without_it_is_not(d1_session):
    """Fix round 1 (I2): phép tính phải được VIẾT trong câu; giá trị trần không có phép tính và không có trong output có cấu trúc thì trượt."""
    user = ["Now divide APB2 by 16 for the UART."]
    assert g1("PCLK2 then becomes 170 MHz / 16 = 10.625 MHz.", user, d1_session)[:2] == ("pass", [])
    status, findings, _ = g1("PCLK2 then becomes 10.625 MHz.", user, d1_session)
    assert status == "fail" and codes(findings) == ["G1-V1"]


# ================================================================================================ fix round 1 (gate_review.md)
D1_GOAL = "Trên STM32G474 chạy 170 MHz, tạo PWM 20 kHz, duty 25% ở PA8 để điều khiển driver động cơ. Sinh code CMSIS."


@pytest.fixture(scope="module")
def d1_real(ev, tmp_path_factory):
    """Bằng chứng như phiên D1 thật: tra chân PA8, solver TIM1, set_clock_config (APB1 = APB2 = /1, flash 4 WS), mô phỏng TIM1."""
    import os
    from mcp_servers import board_state_server as bs
    old = os.environ.get("BOARD_STATE_DB")
    os.environ["BOARD_STATE_DB"] = str(tmp_path_factory.mktemp("d1r") / "bs.sqlite")
    try:
        bs.set_target("stm32g474", "LQFP64", 3.3, project_id="d1r")
        clock = bs.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2}, "ahb_div": 1, "apb1_div": 1, "apb2_div": 1,
                                     "flash_latency": 4, "voltage_range": "range1_boost", "enabled_peripherals": ["GPIOA", "TIM1"]}, project_id="d1r")
    finally:
        if old is None:
            os.environ.pop("BOARD_STATE_DB", None)
        else:
            os.environ["BOARD_STATE_DB"] = old
    return [ev["pin"], ev["solver"], obs("set_clock_config", clock), ev["pwm_sim"]]


@pytest.mark.parametrize("ans", ["The absolute maximum VDD is $V_{DD,max} = 4.6\\,\\text{V}$ [STM32G474_Datasheet p.82].",
                                 "The absolute maximum VDD is $4.6\\text{ V}$ [STM32G474_Datasheet p.82].",
                                 "The absolute maximum VDD is `4.6 V` [STM32G474_Datasheet p.82].",
                                 "Summary [STM32G474_Datasheet p.82]:\n\n```text\nVDD absolute maximum: 4.6 V\n```\n",
                                 "Summary [STM32G474_Datasheet p.82]:\n\n```\nVDD absolute maximum: 4.6 V\n```\n",
                                 "| Parameter | Max | Unit |\n|---|---|---|\n| VDD absolute maximum | 4.6 | V |\n\n[STM32G474_Datasheet p.82]",
                                 "| Parameter | Value (V) |\n|---|---|\n| VDD absolute maximum | 4.6 |\n\n[STM32G474_Datasheet p.82]"])
def test_c3_invented_value_in_latex_inline_code_text_fence_or_table_is_caught(ev, ans):
    status, findings, _ = g1(ans, ["What is the absolute maximum VDD of the STM32G474?"], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V1"] and findings[0].where == 'answer: "4.6 V"', findings


def test_c3_invented_address_in_inline_code_is_caught(ev):
    status, findings, _ = g1("TIM1 base address is `0x40013C00` [STM32G474_Datasheet p.82].", ["TIM1?"], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V2"] and findings[0].where == 'answer: "0x40013C00"'


def test_c3_correct_values_in_a_table_with_a_unit_column_pass(ev):
    ans = ("| Thông số | Min | Max | Đơn vị |\n|---|---|---|---|\n| VDD (abs. max) | -0.3 | 4.0 | V |\n\n"
           "Nguồn: [STM32G474_Datasheet p.82].")
    status, findings, details = g1(ans, ["VDD tối đa?"], [ev["vdd_abs"]])
    assert (status, findings) == ("pass", []) and details["claims_checked"] == 2


def test_c3_a_table_column_without_an_unambiguous_unit_is_left_unchecked(ev):
    ans = "| Parameter | Max |\n|---|---|\n| VDD absolute maximum | 4.6 |\n\n[STM32G474_Datasheet p.82]"
    assert g1(ans, ["VDD?"], [ev["vdd_abs"]])[2]["claims_checked"] == 0


def test_c3_the_real_d1_draft_latex_claims_are_checked_and_supported(d1_real):
    ans = ("* **Hệ thống clock**: Hệ thống chạy ở **170 MHz**. Xung nhịp cấp cho TIM1 là **$f_{\\text{TIM1CLK}} = 170\\text{ MHz}$**.\n"
           "* Chu kỳ mục tiêu: $f_{\\text{PWM}} = 20\\text{ kHz} \\implies T = 50\\ \\mu\\text{s}$.\n"
           "* $N = \\frac{f_{\\text{TIM1CLK}}}{f_{\\text{PWM}}} = \\frac{170\\,000\\,000}{20\\,000} = 8500\\text{ ticks}$.\n"
           "*(Tần số thực tế: chính xác $20.000\\text{ kHz}$; Duty thực tế: chính xác $25.0\\%$)*.\n")
    status, findings, details = g1(ans, [D1_GOAL], d1_real)
    assert (status, findings) == ("pass", []) and details["claims_checked"] == 4


@pytest.mark.parametrize("claim", ["The TIM1 kernel clock is 85 MHz.", "The resulting PWM frequency is 10 kHz.", "The resulting PWM frequency is 40 kHz.",
                                   "PCLK1 runs at 42.5 MHz.", "The HSE crystal is 8 MHz."])
def test_i2_factor_of_two_errors_are_not_blessed_by_a_divider_of_the_session(d1_real, claim):
    status, findings, _ = g1(claim, [D1_GOAL], d1_real)
    assert status == "fail" and codes(findings) == ["G1-V1"], claim


@pytest.mark.parametrize("ans", ["f = 170e6/((0+1)(8499+1)) = 20 kHz.", "With PSC = 0 and ARR = 8499, f = 170 MHz / ((PSC+1)(ARR+1)) = 20 kHz.",
                                 "HSI16: 16 MHz / 4 × 85 = 340 MHz at the VCO.", "f = 170 MHz / 8500 = 20 kHz."])
def test_i2_arithmetic_written_in_the_sentence_is_accepted(ans):
    """Fix round 2 (I-1): biểu thức VIẾT RA được tính đúng, mọi toán hạng có nguồn (ở đây: lời người dùng). Trước đây: tìm tổ hợp bất kỳ."""
    user = ["TIM1 runs at 170 MHz with PSC = 0 and ARR = 8499 (8500 counts); HSI16 is 16 MHz with PLLM = 4 and PLLN = 85. Explain the maths."]
    assert g1(ans, user)[:2] == ("pass", []), ans


def test_i2_operands_must_precede_the_result_so_a_value_cannot_witness_itself():
    status, findings, _ = g1("The HSE is 25 MHz / 1 = 25 MHz.", ["Which crystal?"])
    assert status == "fail" and [f.where for f in findings] == ['answer: "25 MHz"']


def test_i3_prior_answers_only_support_quantities_with_units_from_their_prose():
    prior = ("Độ phân giải $\\approx 13\\text{ bit}$, duty $25\\%$ (RM0440 trang 98). PCLK1 = 85 MHz.\n\n"
             "```c\nTIM1->ARR = 8499;\n```\n")
    for ans in ("The absolute maximum VDD is 13 V.", "Each GPIO can sink at most 25 mA.", "USART2 kernel clock is 98 MHz.",
                "The I/O pins tolerate 8499 mV."):
        status, findings, _ = g1(ans, ["Now add USART2 at 115200 baud."], prior=[prior])
        assert status == "fail" and codes(findings) == ["G1-V1"], ans
    assert g1("PCLK1 stays at 85 MHz.", ["Now add USART2."], prior=[prior])[:2] == ("pass", [])


def test_i3_free_text_written_into_board_state_is_not_evidence(board):  # noqa: F811
    board.set_target("stm32g474", "LQFP64", 3.3)
    r = board.set_requirements([{"id": "R9", "type": "other", "status": "satisfied", "evidence": "datasheet: VDD absolute maximum 4.6 V",
                                 "description": "supply rated 4.6 V"}])
    status, findings, _ = g1("The absolute maximum VDD is 4.6 V.", ["What is the absolute maximum VDD?"], [obs("set_requirements", r)])
    assert status == "fail" and codes(findings) == ["G1-V1"]


@pytest.mark.parametrize("ans", ["The PWM runs at 20,000 Hz.", "TIM1 is clocked at 170,000,000 Hz.", "Tần số PWM là 20.000 Hz.",
                                 "f = 170.000.000 / 8500 = 20.000 Hz."])
def test_i4_digit_grouping_is_normalised_before_matching(ev, ans):
    assert g1(ans, [PWM_Q], [ev["pwm_sim"]])[:2] == ("pass", []), ans


def test_i4_vietnamese_decimal_commas_are_read_as_decimals(ev):
    q = "Điện áp VDD tối đa tuyệt đối của STM32G474 là bao nhiêu?"
    ok = "Điện áp VDD tối đa tuyệt đối là 4,0 V [STM32G474_Datasheet p.82]."
    assert g1(ok, [q], [ev["vdd_abs"]])[:2] == ("pass", [])
    status, findings, _ = g1("Điện áp VDD tối đa tuyệt đối là 4,6 V [STM32G474_Datasheet p.82].", [q], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V1"] and findings[0].where == 'answer: "4,6 V"'


def test_i4_an_unparseable_number_gives_unknown_not_an_error():
    status, findings, _ = g1("The rails are 1,2,3 V.", ["rails?"])
    assert status == "pass" and [(f.code, f.severity) for f in findings] == [("G1-V1", "unknown")]


@pytest.mark.parametrize("cite", ["[STM32G474_RM0440, p. 1755]", "[RM0440 §40.8.5, p.1755]", "[STM32G474_RM0440 p.1754–1756]",
                                  "[STM32G474_RM0440 page 1755]"])
def test_i4_citation_forms_with_comma_section_and_range_are_recognised(ev, cite):
    assert g1(f"USART2_BRR sits at 0x4000440C {cite}.", ["Where is USART2_BRR?"], [ev["brr"]])[:2] == ("pass", []), cite


def test_i4_a_standard_rail_in_advice_is_only_a_warning_but_a_stated_fact_is_an_error(ev):
    q = ["Can I power the STM32G474 from my 5 V USB rail?"]
    for ans in ("No. The absolute maximum is 4.0 V [STM32G474_Datasheet p.82]; use a 3.3 V regulator.",
                "Không. Giá trị tối đa tuyệt đối là 4.0 V [STM32G474_Datasheet p.82]; hãy dùng LDO 3.3 V."):
        status, findings, _ = g1(ans, q, [ev["vdd_abs"]])
        assert status == "pass" and [(f.code, f.severity) for f in findings] == [("G1-V1", "warning")], ans
    status, findings, _ = g1("The board supply is 3.3 V.", ["What supply?"], [ev["vdd_abs"]])
    assert status == "fail" and [(f.code, f.severity) for f in findings] == [("G1-V1", "error")]


@pytest.mark.parametrize("ans", ["The outputs are blocked until MOE is set. The absolute maximum VDD is 4.6 V [STM32G474_Datasheet p.82].",
                                 "The board refused PA8 at first, so PA9 is used. The absolute maximum VDD is 4.6 V [STM32G474_Datasheet p.82]."])
def test_i8_an_abstain_word_does_not_switch_g1_off_when_the_answer_has_claims(ev, ans):
    status, findings, details = g1(ans, ["VDD?"], [ev["vdd_abs"]])
    assert status == "fail" and codes(findings) == ["G1-V1"] and details["abstained"] is False


def test_findings_name_the_claim_or_the_citation_in_where(ev):
    _, findings, _ = g1("VDD is 4.8 V at 0x40004410, see [STM32G474_Datasheet p.99].", ["max VDD?"], [ev["vdd_abs"]])
    assert [f.where for f in findings] == ['answer: "4.8 V"', 'answer: "0x40004410"', "answer: citation [STM32G474_Datasheet p.99]"]


def test_i3_bare_numbers_of_a_prior_answer_do_not_support_a_register_value():
    status, findings, _ = g1("The period register reads 0x2134.", ["Add a UART."], prior=["Earlier we used PSC = 0 and ARR = 8499 on TIM1."])
    assert status == "fail" and codes(findings) == ["G1-V2"]


def test_i2_rounding_is_only_against_structured_tool_outputs_not_user_numbers():
    """20,08 kHz lệch 0,4 % so với "20 kHz" của người dùng: không được coi là làm tròn (chỉ output có cấu trúc của solver/simulator/board)."""
    status, findings, _ = g1("The PWM runs at 20.08 kHz.", ["The PWM must be 20 kHz."])
    assert status == "fail" and codes(findings) == ["G1-V1"]


# ================================================================================================ fix round 2 (re-review)
@pytest.mark.parametrize("ans", ["With PSC = 0 and ARR = 8499 the PWM frequency is f = 170 MHz / (0+1) / (8499+1) = 10 kHz.",
                                 "f = 170 MHz / (1 × 8500) = 10 kHz.", "With PSC = 1, ARR = 8499 we get 170 MHz / 8500 = 40 kHz.",
                                 "PLL: 16 MHz / 4 × 85 = 340 MHz, then / 2 = 160 MHz SYSCLK.", "PLL: 16 MHz / 4 = 4 MHz, 4 MHz × 85 = 320 MHz VCO.",
                                 "The PWM period is 8500 ticks at 170 MHz, i.e. 21.25 kHz."])
def test_i1_a_written_expression_whose_value_differs_from_the_claim_fails(d1_real, ans):
    status, findings, _ = g1(ans, [D1_GOAL + " HSI16 = 16 MHz."], d1_real)
    assert status == "fail" and "G1-V1" in codes(findings), ans


def test_i1_a_continuation_after_a_result_is_evaluated_from_that_result():
    """170 MHz chỉ có nguồn qua bước tiếp nối "340 MHz, then / 2" (không có trong lời người dùng hay output tool nào)."""
    user = ["HSI16 = 16 MHz, PLLM = 4, PLLN = 85, PLLR = 2."]
    assert g1("PLL: 16 MHz / 4 × 85 = 340 MHz, then / 2 = 170 MHz SYSCLK.", user)[:2] == ("pass", [])
    status, findings, _ = g1("PLL: 16 MHz / 4 × 85 = 340 MHz, then / 2 = 160 MHz SYSCLK.", user)
    assert status == "fail" and [f.where for f in findings] == ['answer: "160 MHz"']


def test_i1_every_operand_of_a_written_expression_needs_a_source():
    status, findings, _ = g1("f = 170 MHz / ((1+1)(8499+1)) = 10 kHz.", ["TIM1 runs at 170 MHz with ARR = 8499."])        # PSC = 1 không có nguồn
    assert status == "fail" and findings[0].where == 'answer: "10 kHz"'
    assert g1("f = 170 MHz / ((1+1)(8499+1)) = 10 kHz.", ["TIM1 runs at 170 MHz with PSC = 1 and ARR = 8499."])[:2] == ("pass", [])


def test_i1_an_expression_that_cannot_be_parsed_is_not_guessed():
    status, findings, _ = g1("f = 170 MHz / ((PSC+1)(ARR+1)) = 20 kHz.", ["TIM1 runs at 170 MHz; ARR = 8499, PSC = 0."])     # PSC, ARR không được gán trong câu này
    assert status == "fail" and findings[0].where == 'answer: "20 kHz"'


def test_i1_uart_and_rounding_chains_are_evaluated():
    user = ["PCLK1 = 170 MHz; USART2 at 115200 baud."]
    assert g1("BRR = 170 MHz / 115200 = 1475.7 ≈ 0x5C4.", user)[:2] == ("pass", [])
    status, findings, _ = g1("BRR = 170 MHz / 115200 = 1475.7 ≈ 0x5C8.", user)
    assert status == "fail" and codes(findings) == ["G1-V2"]


def test_hex_plus_one_is_only_the_n_minus_one_encoding_of_a_divider_field(ev):
    status, findings, _ = g1("The period register reads 0x2132.", [PWM_Q], [ev["pwm_sim"]])             # ARR - 1: lỗi kinh điển
    assert status == "fail" and codes(findings) == ["G1-V2"]


@pytest.mark.parametrize("ans,ok", [("The timer clock is $1.7 \\times 10^{8}$ Hz.", True),
                                    ("$f = \\frac{170 \\times 10^{6}\\,\\text{Hz}}{8500} = 20\\,\\text{kHz}$", True),
                                    ("The supply current is $2.5 \\times 10^{-3}$ A.", False)])
def test_i3_latex_scientific_notation_is_one_claim(ev, ans, ok):
    status, findings, _ = g1(ans, [PWM_Q], [ev["pwm_sim"]])
    assert (status == "pass") is ok, findings
    if not ok:
        assert [f.where for f in findings] == ['answer: "2.5e-3 A"']


@pytest.mark.parametrize("ans", ["Set MOE (bit 15) in `TIM1_BDTR` [STM32G474_RM0440 p.1267], i.e. `TIM1->BDTR |= TIM_BDTR_MOE;` (mask `0x8000`).",
                                 "Set MOE (bit 15, `TIM_BDTR_MOE = 0x00008000`) in TIM1_BDTR [STM32G474_RM0440 p.1267].",
                                 "Enable the clock first (bit 11, `0x800`), then set the field mask 0xF0 [STM32G474_RM0440 p.1267]."])
def test_m2_contiguous_bit_masks_are_not_values_needing_a_source(ans):
    from mcp_servers import hw_knowledge_server as hk
    bd = obs("get_register_bitfields", hk.get_register_bitfields("stm32g474", "TIM1", "BDTR"))
    assert g1(ans, ["Which bit enables the TIM1 outputs?"], [bd])[:2] == ("pass", []), ans


def test_m2_addresses_and_other_hex_values_stay_checked():
    status, findings, _ = g1("The SRAM starts at 0x40000000 and BRR is 0x2135.", ["?"])
    assert status == "fail" and codes(findings) == ["G1-V2", "G1-V2"]


def test_m3_a_header_unit_is_not_carried_to_divider_rows_or_rows_with_their_own_unit(ev):
    ans = ("| Field | Value (MHz) | Note |\n|---|---|---|\n| f_I2CCLK | 16 | HSI16 |\n| PRESC | 1 | – |\n| SDADEL | 2 | – |\n| SCLDEL | 3 | – |\n"
           "| t_SCLL | 1.25 | µs |\n")
    status, findings, details = g1(ans, ["I2C3 at 100 kHz from HSI16."], [ev["i2c_sim"]])
    assert (status, findings) == ("pass", []) and details["claims_checked"] == 1


def test_m4_an_overflowing_number_does_not_stop_g1():
    status, findings, _ = g1("VDD max is 4.6 V, f = 1e309 Hz.", ["What is VDD max?"])
    assert status == "fail" and [(f.code, f.severity) for f in findings] == [("G1-V1", "error"), ("G1-V1", "unknown")]
