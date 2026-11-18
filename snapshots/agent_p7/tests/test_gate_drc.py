"""Gate v3 — G3 Board DRC (P4_interfaces §2.3): run_drc trên Board State thật (DB tạm). error -> chặn; unknown -> báo, không chặn, không tính pass;
không có target -> na. kind: DRC-PIN-*/CLK-01/ELEC-01/PWR-01 structural; DRC-CLK-02/REQ-01 local."""
from agent.gate import drc_gate
from test_gate_support import Recorder, board  # noqa: F401  (fixture)

R1 = {"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25}


def g3(srv, call=None):
    call = call or Recorder()
    state = call("get_board_state", {})
    return drc_gate.run(call, state.get("state"), None), call


def clean_board(srv):
    assert srv.set_target("stm32g474", "LQFP64", 3.3)["ok"]
    assert srv.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2}, "enabled_peripherals": ["GPIOA", "TIM1"]})["ok"]
    assert srv.set_requirements([{**R1, "status": "satisfied", "evidence": "sim#1"}])["ok"]
    assert srv.allocate_pin("PA8", "TIM1_CH1", "R1-pwm")["ok"]


def errors(res):
    return [f for f in res.findings if f.severity == "error"]


def test_without_a_target_the_gate_is_not_applicable_and_drc_is_not_run(board):
    (res, call) = g3(board)
    assert res.status == "na" and res.findings == [] and "run_drc" not in call.names()


def test_a_clean_board_passes(board):
    clean_board(board)
    res, _ = g3(board)
    assert res.status == "pass" and res.findings == [] and res.details["unknown_codes"] == []


def test_pin_conflict_is_a_structural_error_located_on_the_pin(board):
    clean_board(board)
    board.set_requirements([{"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PA8", "sda_pin": "PC9", "status": "satisfied", "evidence": "x"}])
    res, _ = g3(board)
    f = next(f for f in errors(res) if f.code == "DRC-PIN-01")
    assert f.gate == "G3" and f.kind == "structural" and f.where == "board.pins.PA8"
    assert "PIN_CONFLICT:PA8" in f.actual and f.expected and "allocate_pin" in f.hint_source


def test_open_requirement_is_a_local_error_on_that_requirement(board):
    clean_board(board)
    board.set_requirements([{**R1, "status": "pending"}])
    res, _ = g3(board)
    f = next(f for f in errors(res) if f.code == "DRC-REQ-01")
    assert f.kind == "local" and f.where == "requirement R1" and "set_requirements" in f.hint_source


def test_missing_clock_enable_is_a_local_error(board):
    clean_board(board)
    board.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 85, "r": 2}, "enabled_peripherals": ["GPIOA"]})
    res, _ = g3(board)
    f = next(f for f in errors(res) if f.code == "DRC-CLK-02")
    assert f.kind == "local" and "TIM1" in f.where and "enabled_peripherals" in f.hint_source


def test_clock_above_the_limit_is_a_structural_error(board):
    clean_board(board)
    board.set_clock_config({"source": "PLL", "pll": {"source": "HSI16", "m": 4, "n": 100, "r": 2}, "enabled_peripherals": ["GPIOA", "TIM1"]})
    res, _ = g3(board)
    f = next(f for f in errors(res) if f.code == "DRC-CLK-01")
    assert f.kind == "structural" and f.where == "board.clock" and "set_clock_config" in f.hint_source


def test_unknown_power_budget_is_reported_but_neither_blocks_nor_counts_as_an_error(board):
    clean_board(board)
    board.add_device("U2", "BME280", 3.3, "I2C")                                        # không khai báo dòng tiêu thụ
    board.set_requirements([{"id": "P1", "type": "power", "mode": "sleep", "budget_ua": 50, "status": "satisfied", "evidence": "calc"}])
    res, _ = g3(board)
    unknown = [f for f in res.findings if f.severity == "unknown"]
    assert res.status == "pass" and errors(res) == []
    assert [f.code for f in unknown] == ["DRC-PWR-01"] and unknown[0].kind == "structural" and unknown[0].where == "board.power[sleep]"
    assert res.details["unknown_codes"] == ["POWER_UNKNOWN:sleep"]


def test_a_failing_run_drc_skips_the_gate_with_an_unknown_finding(board):
    clean_board(board)
    res, _ = g3(board, Recorder({"run_drc": {"error": "timed out after 60 s"}}))
    assert res.status == "skipped" and [f.code for f in res.findings] == ["G3-TOOL-ERROR"] and res.findings[0].severity == "unknown"


def test_unreadable_board_state_skips_the_gate():
    res = drc_gate.run(Recorder(), None, "get_board_state: database is locked")
    assert res.status == "skipped" and res.findings[0].code == "G3-TOOL-ERROR"


def test_every_drc_finding_has_the_five_fields(board):
    clean_board(board)
    board.set_requirements([{**R1, "status": "pending"}, {"id": "R2", "type": "i2c", "instance": "I2C3", "scl_pin": "PA8", "sda_pin": "PC9"}])
    res, _ = g3(board)
    assert len(res.findings) >= 3
    assert all(f.where and f.expected and f.actual and f.hint_source for f in res.findings)


def test_requirement_ids_with_spaces_are_quoted_in_where(board):
    clean_board(board)
    board.set_requirements([{**R1, "id": "PWM PA8", "status": "pending"}])
    res, _ = g3(board)
    assert any(f.code == "DRC-REQ-01" and f.where == 'requirement "PWM PA8"' for f in res.findings)
