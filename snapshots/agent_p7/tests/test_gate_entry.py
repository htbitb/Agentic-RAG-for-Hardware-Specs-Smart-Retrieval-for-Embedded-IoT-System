"""Gate v3 — điểm vào (P4_interfaces §2.2): Gate(call, flags).run(GateContext) -> GateReport. Tích hợp với Board State / analyzer / simulator /
compiler thật; cờ ablation đổi hành vi thật; tool lỗi không bao giờ làm Gate ném lỗi và không bao giờ thành pass; Gate chỉ đọc, tất định."""
import json

import pytest

import agent.gate as gate_pkg
from agent.gate import Gate, GateContext, GateFlags, GateReport
from test_gate_support import CLK170, D1_DRAFT1_C, PWM_C, UART_C, Recorder, board, fenced, obs  # noqa: F401  (fixture)

READ_ONLY = {"get_board_state", "run_drc", "analyze_c_code", "simulate_register_writes", "compile_check", "get_electrical_specs", "get_clock_limits"}
R1 = {"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1.0}
QUESTION = "STM32G474 at 170 MHz: generate CMSIS code for a 20 kHz, 25 % PWM on PA8."
PROSE = ("PA8 carries TIM1_CH1 on AF6 [STM32G474_Datasheet p.73]. With TIM1 clocked at 170 MHz, PSC = 0 and ARR = 8499 give "
         "170 MHz / 8500 = 20 kHz; CCR1 = 2125 gives 25 % duty.\n\n")


@pytest.fixture(scope="module")
def pin_obs():
    from mcp_servers import hw_knowledge_server as hk
    return obs("query_pin_alternate_function", hk.query_pin_alternate_function("stm32g474", "PA8"), chip="stm32g474", pin="PA8")


def d1_board(srv, status="satisfied", extra_reqs=(), enabled=()):
    assert srv.set_target("stm32g474", "LQFP64", 3.3)["ok"]
    assert srv.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2},
                                 "enabled_peripherals": ["GPIOA", "TIM1", *enabled]})["ok"]
    reqs = [{**R1, "status": status, **({"evidence": "sim#1"} if status == "satisfied" else {})}, *extra_reqs]
    assert srv.set_requirements(reqs)["ok"]
    assert srv.allocate_pin("PA8", "TIM1_CH1", "R1-pwm")["ok"]


def ctx_for(code=PWM_C, prose=PROSE, observations=(), **kw):
    return GateContext(answer=prose + fenced(code), user_texts=[QUESTION], observations=list(observations), **kw)


def run(ctx, flags=None, call=None):
    call = call or Recorder()
    return Gate(call, flags).run(ctx), call


# ------------------------------------------------------------------------------------------------ kịch bản D1
def test_correct_d1_answer_passes_every_gate(board, pin_obs):
    d1_board(board)
    report, call = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.passed, report.feedback()
    assert report.gates == {"G1": "pass", "G2": "pass", "G3": "pass", "G4": "pass", "G5": "pass"}
    assert [f for f in report.findings if f.severity in ("error", "unknown")] == []
    assert report.sim["effects"][0]["pwm_hz"] == 20000.0 and report.details["requirements_checked"] == 1
    assert set(call.names()) <= READ_ONLY
    json.dumps(report.to_dict())


def test_wrong_arr_fails_g2_with_typed_feedback(board, pin_obs):
    d1_board(board)
    report, _ = run(ctx_for(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), observations=[pin_obs], initial=CLK170))
    assert not report.passed and report.gates["G2"] == "fail" and report.failed_codes() == ["G2-FREQ"]
    fb = report.feedback()
    assert fb["passed"] is False and fb["findings"][0]["code"] == "G2-FREQ" and fb["findings"][0]["expected"] == "20000 Hz ±1%"


def test_the_agents_simulation_never_sets_the_start_state_and_a_mismatch_with_the_users_is_reported(board, pin_obs):
    d1_board(board)
    agent_sim = obs("simulate_register_writes", {"ok": True, "effects": [], "violations": []}, chip="stm32g474", ops=[], initial=CLK170)
    assert run(ctx_for(observations=[pin_obs, agent_sim]))[0].gates["G2"] == "fail"       # D36: không ai nêu 170 MHz => "reset": TIM1 chạy ở 16 MHz, preset của agent bị bỏ qua
    user = {"initial": CLK170, "hse_hz": None, "source": "user_text"}
    c = ctx_for(observations=[pin_obs, agent_sim], initial=CLK170)
    c.start = user
    rep, _ = run(c)
    assert rep.gates["G2"] == "pass" and rep.details["start"]["source"] == "user_text"
    other = obs("simulate_register_writes", {"ok": True, "effects": [], "violations": []}, chip="stm32g474", ops=[], initial="reset")
    c = ctx_for(observations=[pin_obs, other], initial=CLK170)
    c.start = user
    rep, _ = run(c)
    assert "G2-START-MISMATCH" in rep.failed_codes() and rep.gates["G2"] == "fail"


def test_the_gate_is_read_only_and_deterministic(board, pin_obs):
    d1_board(board)
    head = board.get_board_state()["head"]
    c = ctx_for(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), observations=[pin_obs], initial=CLK170)
    a, call = run(c)
    b, _ = run(c)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    assert board.get_board_state()["head"] == head and set(call.names()) <= READ_ONLY


def test_the_gate_refuses_to_call_a_state_mutating_tool(board, monkeypatch):
    d1_board(board)
    seen = {}

    def sneaky(call, state, err):
        seen["res"] = call("set_requirements", {"requirements": []})
        return gate_pkg.drc_gate.DrcResult("pass", [])
    monkeypatch.setattr(gate_pkg.drc_gate, "run", sneaky)
    _, call = run(ctx_for())
    assert "error" in seen["res"] and "set_requirements" not in call.names()


def test_structural_board_errors_ask_for_a_replan(board, pin_obs):
    d1_board(board, extra_reqs=[{"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PA8", "sda_pin": "PC9", "status": "satisfied", "evidence": "x"}])
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.gates["G3"] == "fail" and "DRC-PIN-01" in report.failed_codes()
    assert any(f.kind == "structural" for f in report.errors()) and "update_plan" in report.feedback()["hint"]


def test_without_a_target_g3_is_not_applicable(board, pin_obs):
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.gates["G3"] == "na"


# ------------------------------------------------------------------------------------------------ cờ ablation
@pytest.mark.parametrize("gate,tools", [("g1", set()), ("g2", {"analyze_c_code", "simulate_register_writes"}), ("g5", {"compile_check"})])
def test_each_gate_flag_turns_its_gate_off(board, pin_obs, gate, tools):
    d1_board(board)
    report, call = run(ctx_for(observations=[pin_obs], initial=CLK170), GateFlags(**{gate: False}))
    assert report.gates[gate.upper()] == "off" and not tools & set(call.names())


def test_g3_flag_off_keeps_drc_findings_away_from_the_agent(board, pin_obs):
    d1_board(board, status="pending")
    on, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    off, _ = run(ctx_for(observations=[pin_obs], initial=CLK170), GateFlags(g3=False))
    assert "DRC-REQ-01" in on.failed_codes() and off.gates["G3"] == "off" and "DRC-REQ-01" not in off.failed_codes()


def test_g4_flag_off_lets_an_unsafe_recommendation_through(board, pin_obs):
    d1_board(board)
    c = ctx_for(prose=PROSE + "For more margin, apply 5 V to VDD.\n\n", observations=[pin_obs], initial=CLK170)
    assert "G4-ABS-MAX" in run(c)[0].failed_codes()
    off, _ = run(c, GateFlags(g4=False))
    assert off.gates["G4"] == "off" and "G4-ABS-MAX" not in off.failed_codes()


def test_every_flag_off_means_no_tool_call_and_every_gate_off(board, pin_obs):
    d1_board(board)
    report, call = run(ctx_for(observations=[pin_obs]), GateFlags(g1=False, g2=False, g3=False, g4=False, g5=False))
    assert set(report.gates.values()) == {"off"} and call.names() == [] and report.passed


def test_board_flag_off_reads_no_board_state_and_checks_only_code_level_violations(board, pin_obs):
    d1_board(board, extra_reqs=[{"id": "R9", "type": "uart", "instance": "USART1", "baud": 115200}])   # R9 sẽ trượt nếu đọc requirement
    report, call = run(ctx_for(observations=[pin_obs], initial=CLK170), GateFlags(board=False))
    assert not {"get_board_state", "run_drc"} & set(call.names())
    assert report.gates["G3"] == "off" and report.gates["G2"] == "pass" and report.details["requirements_checked"] == 0
    bad, _ = run(ctx_for(PWM_C.replace("    TIM1->BDTR = TIM_BDTR_MOE;\n", ""), observations=[pin_obs], initial=CLK170), GateFlags(board=False))
    assert bad.failed_codes() == ["G2-SIM-TIM-MOE"]


def test_strict_v1_provenance_switches_g1_to_the_v1_verifier():
    ans = "USART2 runs from PCLK1 = 16 MHz, so BRR = 0x683 gives 9598 baud.\n\n" + fenced(UART_C)
    sim = obs("simulate_register_writes", Recorder()("simulate_register_writes", {
        "chip": "stm32g474", "ops": Recorder()("analyze_c_code", {"code": UART_C})["ops"]}))
    c = GateContext(answer=ans, user_texts=["USART2 at 9600 baud from HSI16 (16 MHz)."], observations=[sim])
    flags = dict(g2=False, g3=False, g4=False, g5=False, board=False)
    new, _ = run(c, GateFlags(**flags))
    old, _ = run(c, GateFlags(**flags, strict_v1_provenance=True))
    assert new.gates["G1"] == "pass" and new.details["G1"]["mode"] == "v3"
    assert old.gates["G1"] == "fail" and old.details["G1"]["mode"] == "v1" and "G1-V2" in old.failed_codes()


# ------------------------------------------------------------------------------------------------ miễn trừ (finish waived_requirements)
SPI = {"id": "R5", "type": "spi", "instance": "SPI1"}


def test_a_waivable_finding_with_a_reason_becomes_a_warning(board, pin_obs):
    d1_board(board, extra_reqs=[{**SPI, "status": "waived", "waiver_reason": "checked on the bench"}], enabled=["SPI1"])
    c = ctx_for(observations=[pin_obs], initial=CLK170, waived=[{"id": "R5", "reason": "SPI is not simulated; checked on the bench"}])
    report, _ = run(c)
    f = next(f for f in report.findings if f.code == "G2-UNMODELED")
    assert f.severity == "warning" and report.gates["G2"] == "skipped" and report.passed           # I7: miễn trừ => không bao giờ "pass"
    assert report.details["waived"] == [{"id": "R5", "code": "G2-UNMODELED", "where": f.where, "reason": "SPI is not simulated; checked on the bench"}]


def test_a_waiver_without_a_reason_is_rejected(board, pin_obs):
    d1_board(board, extra_reqs=[{**SPI, "status": "waived", "waiver_reason": "bench"}], enabled=["SPI1"])
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170, waived=[{"id": "R5", "reason": "  "}]))
    assert "G2-UNMODELED" in report.failed_codes() and report.details["waivers_rejected"][0]["id"] == "R5"


def test_a_non_waivable_code_stays_an_error_with_a_note(board, pin_obs):
    d1_board(board)
    c = ctx_for(PWM_C.replace("TIM1->ARR = 8499;", "TIM1->ARR = 8399;"), observations=[pin_obs], initial=CLK170,
                waived=[{"id": "R1", "reason": "close enough"}])
    report, _ = run(c)
    f = next(f for f in report.findings if f.code == "G2-FREQ")
    assert f.severity == "error" and "cannot be waived" in f.actual and report.details["waivers_rejected"][0]["code"] == "G2-FREQ"


def test_the_waivable_list_comes_from_the_flags(board, pin_obs):
    d1_board(board, extra_reqs=[{**SPI, "status": "waived", "waiver_reason": "bench"}], enabled=["SPI1"])
    c = ctx_for(observations=[pin_obs], initial=CLK170, waived=[{"id": "R5", "reason": "bench"}])
    report, _ = run(c, GateFlags(waivable=()))
    f = next(f for f in report.findings if f.code == "G2-UNMODELED")
    assert f.severity == "error" and f.waivable is False and not report.passed


def test_a_skipped_compilation_can_be_waived_by_its_code(board, pin_obs):
    d1_board(board)
    skipped = {"status": "skipped", "reason": "clang is not installed on this machine", "errors": [], "warnings": []}
    c = ctx_for(observations=[pin_obs], initial=CLK170, waived=[{"id": "G5-SKIPPED", "reason": "no toolchain on this runner"}])
    report, _ = run(c, call=Recorder({"compile_check": skipped}))
    assert report.gates["G5"] == "skipped" and next(f for f in report.findings if f.code == "G5-SKIPPED").severity == "warning"


# ------------------------------------------------------------------------------------------------ lỗi tool / lỗi nội bộ: không ném, không pass
def test_every_tool_raising_still_returns_a_report_without_any_pass_from_tools(pin_obs):
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170), call=Recorder({n: RuntimeError("connection reset") for n in READ_ONLY}))
    assert isinstance(report, GateReport)
    assert report.gates["G2"] == report.gates["G3"] == report.gates["G5"] == "skipped"
    assert all(f.severity in ("unknown", "warning") for f in report.findings if f.gate != "G1")
    assert all(c["ok"] is False for c in report.details["calls"])


def test_an_internal_bug_in_one_gate_is_contained_and_fails_closed_when_code_meets_a_requirement(board, pin_obs, monkeypatch):
    """C1: code + requirement mô phỏng được => lỗi nội bộ của G2 là ERROR (fail closed); các cổng khác vẫn chạy."""
    d1_board(board)
    monkeypatch.setattr(gate_pkg.functional, "run", lambda *a, **k: 1 / 0)
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.gates["G2"] == "fail" and report.gates["G3"] == "pass" and not report.passed
    f = next(f for f in report.findings if f.gate == "G2")
    assert f.code == "G2-INTERNAL-ERROR" and f.severity == "error" and "ZeroDivisionError" in f.actual


def test_an_internal_bug_without_a_modelable_requirement_is_unknown(board, pin_obs, monkeypatch):
    board.set_target("stm32g474", "LQFP64", 3.3)
    monkeypatch.setattr(gate_pkg.functional, "run", lambda *a, **k: 1 / 0)
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.gates["G2"] == "skipped" and next(f for f in report.findings if f.gate == "G2").severity == "unknown"


def test_context_defaults_and_chip_from_the_board(board):
    board.set_target("stm32g474", "LQFP64", 3.3)
    c = GateContext(answer="No code here.", user_texts=["hello"], observations=[])
    assert c.prior_answers == () and c.waived == () and c.chip is None and c.initial == "reset" and c.hse_hz is None
    report, _ = run(c)
    assert report.gates["G2"] == "na" and report.gates["G5"] == "na"


# ================================================================================================ fix round 1 (gate_review.md)
D1_GOAL = "Trên STM32G474 chạy 170 MHz, tạo PWM 20 kHz, duty 25% ở PA8 để điều khiển driver động cơ. Sinh code CMSIS."
D1_PROSE = ("### PWM 20 kHz, duty 25% trên PA8\n\n* Hệ thống chạy ở **170 MHz**; xung nhịp TIM1 là **$f_{\\text{TIM1CLK}} = 170\\text{ MHz}$**.\n"
            "* PA8 dùng AF6 = TIM1_CH1 [STM32G474_Datasheet p.73].\n"
            "* $N = \\frac{170\\,000\\,000}{20\\,000} = 8500$, $\\text{PSC} = 0$, $\\text{ARR} = 8500 - 1 = 8499$, $\\text{CCR1} = 2125$.\n"
            "* Tần số thực tế: $20.000\\text{ kHz}$.\n\n")
CMS = PWM_C.replace("TIM1->CR1 = TIM_CR1_CEN;", "TIM1->CR1 = TIM_CR1_CEN | TIM_CR1_CMS_0;")      # canh giữa: không mô hình hoá


def test_c2_the_real_d1_draft_that_configures_its_clock_passes_and_reports_its_start_state(board, pin_obs):
    d1_board(board)
    c = GateContext(answer=D1_PROSE + fenced(D1_DRAFT1_C), user_texts=[D1_GOAL], observations=[pin_obs], initial=CLK170)
    report, _ = run(c)
    assert report.passed and report.gates["G2"] == "pass", report.feedback()
    assert report.details["start"] == {"initial": "reset", "hse_hz": None, "source": "code_configures_clock"}
    assert "G2-SIM-FLASH-WS" not in [f.code for f in report.findings]


def test_c2_the_start_state_of_a_plain_program_and_its_source_are_reported(board, pin_obs):
    d1_board(board)
    report, _ = run(ctx_for(observations=[pin_obs], initial=CLK170))
    assert report.details["start"] == {"initial": CLK170, "hse_hz": None, "source": "context"}


def test_i7_a_code_level_waiver_no_longer_waives_unmodeled_requirements(board, pin_obs):
    d1_board(board)
    report, _ = run(ctx_for(CMS, observations=[pin_obs], initial=CLK170, waived=[{"id": "G2-UNMODELED", "reason": "not modeled"}]))
    assert "G2-UNMODELED" in report.failed_codes() and report.gates["G2"] == "fail"
    assert report.details["waivers_rejected"][0]["id"] == "G2-UNMODELED"


def test_i7_a_requirement_waiver_passes_the_answer_but_g2_is_skipped(board, pin_obs):
    d1_board(board)
    report, _ = run(ctx_for(CMS, observations=[pin_obs], initial=CLK170, waived=[{"id": "R1", "reason": "centre-aligned mode is not modeled"}]))
    assert report.passed and report.gates["G2"] == "skipped" and report.details["waived"][0]["id"] == "R1"


def test_i7_a_requirement_not_rechecked_makes_g2_skipped(board):
    uart = {"id": "R2", "type": "uart", "instance": "USART2", "baud": 9600, "status": "satisfied", "evidence": "sim#2"}
    d1_board(board, extra_reqs=[uart], enabled=["USART2"])
    set_now = obs("set_requirements", {"ok": True, "requirements": [uart]}, requirements=[uart])
    c = GateContext(answer="USART2 at 9600 baud.\n\n" + fenced(UART_C), user_texts=["Add USART2 at 9600 baud from HSI16."], observations=[set_now])
    report, _ = run(c)
    assert report.passed and report.gates["G2"] == "skipped" and report.details["not_rechecked"] == ["R1"]


def test_requirement_ids_with_spaces_are_quoted_in_where_and_can_be_waived(board, pin_obs):
    board.set_target("stm32g474", "LQFP64", 3.3)
    board.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2}, "enabled_peripherals": ["GPIOA", "TIM1"]})
    assert board.set_requirements([{**R1, "id": "PWM PA8", "status": "satisfied", "evidence": "sim#1"}])["ok"]
    report, _ = run(ctx_for(CMS, observations=[pin_obs], initial=CLK170, waived=[{"id": "PWM PA8", "reason": "centre-aligned mode is not modeled"}]))
    f = next(f for f in report.findings if f.code == "G2-UNMODELED")
    assert f.where == 'requirement "PWM PA8" (PA8 PWM)' and f.severity == "warning" and report.details["waived"][0]["id"] == "PWM PA8"


# ================================================================================================ fix round 2 (m4): mọi cổng đóng khi lỗi nội bộ
@pytest.mark.parametrize("module,attr,gate", [("provenance", "check", "G1"), ("compile_gate", "run", "G5"), ("safety", "run", "G4"), ("drc_gate", "run", "G3")])
def test_m4_an_internal_error_fails_closed_when_the_gate_had_something_to_check(board, pin_obs, monkeypatch, module, attr, gate):
    d1_board(board)
    monkeypatch.setattr(getattr(gate_pkg, module), attr, lambda *a, **k: 1 / 0)
    report, _ = run(ctx_for(prose=PROSE + "VDD stays at 3.3 V.\n\n", observations=[pin_obs], initial=CLK170))
    f = next(f for f in report.findings if f.gate == gate)
    assert f.code == f"{gate}-INTERNAL-ERROR" and f.severity == "error" and report.gates[gate] == "fail" and not report.passed


def test_m4_an_internal_error_with_nothing_to_check_stays_unknown(monkeypatch):
    monkeypatch.setattr(gate_pkg.provenance, "check", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(gate_pkg.compile_gate, "run", lambda *a, **k: 1 / 0)
    report, _ = run(GateContext(answer="Hello, nothing measurable here.", user_texts=["hi"], observations=[]), GateFlags(board=False))
    assert {f.gate: f.severity for f in report.findings if f.code.endswith("INTERNAL-ERROR")} == {"G1": "unknown", "G5": "unknown"}
