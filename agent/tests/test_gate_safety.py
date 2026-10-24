"""Gate v3 — G4 Safety (P4_interfaces §2.3): (i) Board State: VDD > Absolute Maximum, 5 V vào chân không FT (chỉ khi DRC không báo, không nhân đôi);
(ii) mô phỏng của G2: SIM-CLK-LIMIT* -> G4-CLOCK-LIMIT; (iii) văn xuôi khuyên áp điện áp vượt Absolute Maximum (bảo thủ: warning khi không chắc)."""
import pytest

from agent.gate import codeblocks, functional, safety
from test_gate_support import Recorder, board, fenced, obs  # noqa: F401  (fixture)

PLL_C = """#include "stm32g4xx.h"
int main(void) {
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | 4U;
    RCC->PLLCFGR = (3U << RCC_PLLCFGR_PLLM_Pos) | (100U << RCC_PLLCFGR_PLLN_Pos) | RCC_PLLCFGR_PLLREN | RCC_PLLCFGR_PLLSRC_1;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) { }
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | (3U << RCC_CFGR_SW_Pos);
    while (1) { }
}"""


def g4(prose="", state=None, drc=None, fres=None, prog=None, report_drc=True, call=None, observations=(), chip="stm32g474"):
    call = call or Recorder()
    return safety.run(call, chip, prose, state, drc, fres, prog, report_drc, list(observations)), call


def state_of(srv):
    return srv.get_board_state()["state"]


def codes(res, severity=None):
    return [f.code for f in res.findings if severity is None or f.severity == severity]


# ------------------------------------------------------------------------------------------------ (i) Board State
def test_target_vdd_above_the_absolute_maximum_is_a_structural_error(board):
    board.set_target("stm32g474", "LQFP64", 5.0)                                     # set_target chỉ cảnh báo, vẫn ghi
    res, _ = g4(state=state_of(board))
    assert codes(res) == ["G4-VDD-ABS-MAX"]
    f = res.findings[0]
    assert f.severity == "error" and f.kind == "structural" and f.where == "board.targets.stm32g474.vdd"
    assert "5 V" in f.actual and "4 V" in f.expected and "p.82" in f.expected and "get_electrical_specs" in f.hint_source


@pytest.mark.parametrize("vdd", [3.3, 3.6, 4.0])
def test_target_vdd_up_to_the_absolute_maximum_is_accepted(board, vdd):
    board.set_target("stm32g474", "LQFP64", vdd)
    res, _ = g4(state=state_of(board))
    assert codes(res) == [] and res.status == "pass"


def _five_volt_net(srv, volts=5.0):
    srv.set_target("stm32g474", "LQFP64", 3.3)
    srv.add_device("U1", "SENSOR", 3.3, "digital")
    assert srv.connect("U1.OUT", "stm32g474.PA4", "digital")["ok"]                   # PA4 = TT_a: hợp lệ ở 3,3 V
    srv.add_device("U1", "SENSOR", volts, "digital")                                  # cập nhật sau khi nối: DRC mới thấy


def test_five_volts_on_a_non_ft_pin_is_left_to_drc_when_g3_reports_it(board):
    _five_volt_net(board)
    res, _ = g4(state=state_of(board), drc=board.run_drc(), report_drc=True)
    assert "G4-5V-NON-FT" not in codes(res) and res.details["five_volt_reported_by_drc"] == ["U1.OUT -> stm32g474.PA4"]


def test_five_volts_on_a_non_ft_pin_is_reported_by_g4_when_drc_findings_are_not_shown(board):
    _five_volt_net(board)
    res, call = g4(state=state_of(board), drc=None, report_drc=False)
    assert "run_drc" in call.names() and codes(res) == ["G4-5V-NON-FT"]
    f = res.findings[0]
    assert f.kind == "structural" and f.where == "board.nets[U1.OUT -> stm32g474.PA4]" and "5 V" in f.actual and "3.6 V" in f.actual


def test_a_4_2_volt_rail_into_a_non_ft_pin_counts_but_a_3_6_volt_one_does_not(board):
    _five_volt_net(board, 4.2)
    assert codes(g4(state=state_of(board), report_drc=False)[0]) == ["G4-5V-NON-FT"]


def test_a_rail_below_four_volts_is_not_a_five_volt_hazard(board):
    _five_volt_net(board, 3.6)
    assert "G4-5V-NON-FT" not in codes(g4(state=state_of(board), report_drc=False)[0])


# ------------------------------------------------------------------------------------------------ (ii) mô phỏng
def _sim(code):
    prog = codeblocks.program(fenced(code))
    return functional.run(Recorder(), prog, None, None, "stm32g474", "reset", None), prog


def test_code_that_overclocks_the_pll_is_a_clock_limit_finding_located_in_the_code():
    fres, prog = _sim(PLL_C)                                                          # 4 MHz x 100 = 400 MHz VCO, SYSCLK 200 MHz
    res, _ = g4(fres=fres, prog=prog)
    assert codes(res) == ["G4-CLOCK-LIMIT", "G4-CLOCK-LIMIT"]
    assert all(f.kind == "structural" and f.severity == "error" for f in res.findings)
    assert res.findings[0].where.startswith("code block 1, line 5") and "VCO" in res.findings[0].actual          # op 2: PLLON
    assert "set_clock_config" in res.findings[0].hint_source


def test_a_pll_inside_the_limits_is_not_a_clock_finding():
    fres, prog = _sim(PLL_C.replace("100U", "75U"))                                   # 150 MHz: trong giới hạn Range 1 normal
    assert codes(g4(fres=fres, prog=prog)[0]) == []


# ------------------------------------------------------------------------------------------------ (iii) văn xuôi
def test_advice_to_put_five_volts_on_vdd_is_an_error():
    res, _ = g4("To gain margin, apply 5 V to VDD of the STM32G474.")
    assert codes(res) == ["G4-ABS-MAX"] and res.findings[0].severity == "error" and res.findings[0].kind == "structural"
    assert "4 V" in res.findings[0].expected and res.findings[0].where.startswith('answer: "')


@pytest.mark.parametrize("sentence", ["Do not apply 5 V to VDD.", "Never connect 5 V to VDD: it exceeds the absolute maximum.",
                                      "PA9 is 5 V tolerant, so you can connect the 5 V UART there.", "Apply 3.3 V to VDD.",
                                      "The board was tested at 5 V input."])
def test_warnings_negations_and_safe_values_are_not_flagged(sentence):
    assert codes(g4(sentence)[0]) == []


def test_uncertain_cases_are_warnings_not_errors():
    assert codes(g4("Power the sensor module from 5 V.")[0], "warning") == ["G4-ABS-MAX"]                 # chưa chắc là nguồn của MCU
    assert codes(g4("Connect the 5 V output of the sensor to PA4.")[0], "warning") == ["G4-ABS-MAX"]     # chân: không biết có FT không
    assert codes(g4("Raise VDD to 3.8 V for overclocking.")[0], "warning") == ["G4-OPERATING-RANGE"]


def test_limits_already_in_the_observations_are_reused_without_a_tool_call():
    from mcp_servers import hw_knowledge_server as hk
    o = obs("get_electrical_specs", hk.get_electrical_specs("stm32g474", "supply voltage"), chip="stm32g474", parameter="supply voltage")
    res, call = g4("Apply 5 V to VDD.", observations=[o])
    assert codes(res) == ["G4-ABS-MAX"] and "get_electrical_specs" not in call.names()


def test_no_tool_call_when_the_prose_requests_no_voltage():
    res, call = g4("Set the timer to 20 kHz on PA8.")
    assert res.status == "pass" and call.names() == []


def test_a_failing_limits_lookup_is_unknown_and_skips_the_gate():
    res, _ = g4("Apply 5 V to VDD.", call=Recorder({"get_electrical_specs": {"error": "timed out after 60 s"}}))
    assert res.status == "skipped" and codes(res) == ["G4-TOOL-ERROR"] and res.findings[0].severity == "unknown"


def test_each_target_is_checked_against_its_own_chip_limits(board):
    board.set_target("stm32g474", "LQFP64", 3.3)
    board.set_target("esp32", None, 3.8)                                              # ESP32: tuyệt đối tối đa 3,6 V (STM32G474: 4,0 V)
    res, _ = g4(state=state_of(board), chip="stm32g474")
    assert codes(res) == ["G4-VDD-ABS-MAX"]
    assert res.findings[0].where == "board.targets.esp32.vdd" and "3.6 V" in res.findings[0].expected


# ================================================================================================ fix round 1 (I5): luật không phụ thuộc ngôn ngữ
@pytest.mark.parametrize("sentence", ["Bạn có thể cấp trực tiếp 5 V vào chân VDD của STM32G474.", "Hãy nối VDD của STM32G474 với nguồn 5 V từ USB.",
                                      "Bạn có thể cấp 4,5 V vào VDD của STM32G474."])
def test_i5_vietnamese_advice_above_the_absolute_maximum_is_an_error(sentence):
    res, _ = g4(sentence)
    assert [(f.code, f.severity) for f in res.findings] == [("G4-ABS-MAX", "error")], sentence
    assert res.findings[0].kind == "structural" and "4 V" in res.findings[0].expected


@pytest.mark.parametrize("sentence,severity", [("Yes: VDD = 5 V works for the STM32G474.", "warning"), ("Cấp nguồn 5 V cho cảm biến.", "warning")])
def test_i5_statements_or_non_mcu_supplies_above_the_limit_are_warnings(sentence, severity):
    assert [(f.code, f.severity) for f in g4(sentence)[0].findings] == [("G4-ABS-MAX", severity)]


@pytest.mark.parametrize("sentence", ["Không. Giá trị tối đa tuyệt đối là 4.0 V; hãy dùng LDO 3.3 V.", "Tránh cấp 5 V vào VDD của STM32G474.",
                                      "Đừng nối VDD với 5 V.", "Hãy cấp 3,3 V cho VDD của STM32G474."])
def test_i5_vietnamese_warnings_and_safe_values_are_not_flagged(sentence):
    assert g4(sentence)[0].findings == [], sentence


def test_i5_an_english_sentence_already_judged_by_the_english_rule_is_not_reported_twice():
    res, _ = g4("Power the sensor module from 5 V.")
    assert [(f.code, f.severity) for f in res.findings] == [("G4-ABS-MAX", "warning")]


def test_i5_latex_and_inline_code_are_read_too():
    res, _ = g4(codeblocks.prose("Bạn có thể cấp `5 V` vào $V_{DD}$ của STM32G474."))
    assert [(f.code, f.severity) for f in res.findings] == [("G4-ABS-MAX", "error")]


# ================================================================================================ fix round 2 (I-2)
@pytest.mark.parametrize("sentence", ["Use the 5 V USB rail and an AMS1117 LDO to supply 3.3 V to VDD of the STM32G474.",
                                      "Cấp nguồn 5 V từ USB qua LDO AMS1117 để tạo 3,3 V cho VDD của STM32G474.",
                                      "Dùng nguồn USB 5 V, hạ xuống 3.3 V bằng LDO rồi cấp cho STM32G474.",
                                      "The STM32G474 board is powered from a 12 V adapter through a buck converter to 3.3 V.",
                                      "Power the board from a 12 V adapter and use a buck converter to make 3.3 V for the STM32G474.",
                                      "Connect the 5 V sensor output to PA9 (an FT pin) of the STM32G474.",
                                      "Nối ngõ ra 5 V của cảm biến vào chân PA9 (chân FT) của STM32G474.",
                                      "Cấp 3,3 V cho VDD của STM32G474, cổng USB cung cấp 5 V."])
def test_i2_correct_power_chains_and_ft_pins_are_not_flagged(sentence):
    assert g4(sentence)[0].findings == [], sentence


def test_i2_a_regulator_that_outputs_too_much_for_vdd_is_still_an_error():
    res, _ = g4("Use a 5 V LDO to power VDD of the STM32G474.")
    assert [(f.code, f.severity) for f in res.findings] == [("G4-ABS-MAX", "error")]


def test_i2_a_5_volt_signal_on_a_pin_not_described_as_ft_is_still_reported():
    res, _ = g4("Nối ngõ ra 5 V của cảm biến vào chân PA4 của STM32G474.")
    assert [f.code for f in res.findings] == ["G4-ABS-MAX"]
