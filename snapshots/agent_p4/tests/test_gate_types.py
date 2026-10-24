"""Gate v3 — kiểu dữ liệu (P4_interfaces §2.1): Finding đủ năm trường, GateReport.passed / failed_codes / feedback."""
import json

import pytest

from agent.gate.types import Finding, GateReport


def F(code, severity="error", gate="G2", kind="local", **kw):
    base = dict(gate=gate, code=code, where="requirement R1 (PA8 PWM)", expected="20000 Hz ±1%", actual="19000 Hz",
                hint_source="solve_timer_config", severity=severity, kind=kind)
    base.update(kw)
    return Finding(**base)


def test_finding_to_dict_has_every_field_and_is_json_serialisable():
    d = F("G2-FREQ").to_dict()
    assert d == {"gate": "G2", "code": "G2-FREQ", "where": "requirement R1 (PA8 PWM)", "expected": "20000 Hz ±1%", "actual": "19000 Hz",
                 "hint_source": "solve_timer_config", "severity": "error", "kind": "local", "waivable": False}
    json.dumps(d)


def test_finding_is_immutable():
    with pytest.raises(Exception):
        F("G2-FREQ").code = "x"


def test_passed_is_false_with_an_error_finding():
    r = GateReport(gates={"G1": "pass", "G2": "pass"}, findings=[F("G2-FREQ")], sim=None, details={})
    assert r.passed is False


def test_passed_is_false_when_a_gate_failed_even_without_findings():
    assert GateReport(gates={"G1": "fail"}, findings=[], sim=None, details={}).passed is False


def test_unknown_and_warning_findings_do_not_block():
    r = GateReport(gates={"G3": "pass", "G5": "skipped"}, findings=[F("DRC-PWR-01", "unknown", "G3"), F("G2-NO-CODE", "warning"),
                                                                    F("G5-SKIPPED", "unknown", "G5")], sim=None, details={})
    assert r.passed is True and r.errors() == [] and r.failed_codes() == []


def test_failed_codes_are_unique_and_keep_the_first_occurrence_order():
    r = GateReport(gates={}, findings=[F("G2-SIM-TIM-MOE"), F("G1-V1", gate="G1"), F("G2-SIM-TIM-MOE"), F("DRC-PWR-01", "unknown")],
                   sim=None, details={})
    assert r.failed_codes() == ["G2-SIM-TIM-MOE", "G1-V1"]
    assert [f.code for f in r.errors()] == ["G2-SIM-TIM-MOE", "G1-V1", "G2-SIM-TIM-MOE"]


def test_feedback_lists_only_errors_then_unknowns_capped_at_eight():
    fs = [F("G2-NO-CODE", "warning")] + [F("G5-SKIPPED", "unknown", "G5")] + [F(f"G2-E{i}") for i in range(9)]
    fb = GateReport(gates={"G2": "fail"}, findings=fs, sim=None, details={}).feedback()
    assert fb["passed"] is False and fb["gates"] == {"G2": "fail"}
    assert len(fb["findings"]) == 8
    assert [f["code"] for f in fb["findings"]] == [f"G2-E{i}" for i in range(8)]          # errors first; unknown pushed out by the cap
    assert all(set(f) >= {"code", "where", "expected", "actual", "hint_source", "gate", "severity", "kind"} for f in fb["findings"])
    assert isinstance(fb["hint"], str) and fb["hint"]


def test_feedback_keeps_unknowns_after_errors_when_there_is_room():
    fb = GateReport(gates={}, findings=[F("G5-SKIPPED", "unknown", "G5"), F("G2-FREQ")], sim=None, details={}).feedback()
    assert [f["code"] for f in fb["findings"]] == ["G2-FREQ", "G5-SKIPPED"]


def test_feedback_hint_asks_for_a_replan_only_when_a_structural_error_exists():
    local = GateReport(gates={"G2": "fail"}, findings=[F("G2-FREQ")], sim=None, details={}).feedback()["hint"]
    structural = GateReport(gates={"G3": "fail"}, findings=[F("DRC-PIN-01", gate="G3", kind="structural")], sim=None, details={}).feedback()["hint"]
    assert "update_plan" not in local and "update_plan" in structural


def test_feedback_hint_mentions_waivers_only_for_waivable_errors():
    w = GateReport(gates={"G2": "fail"}, findings=[F("G2-UNMODELED", waivable=True)], sim=None, details={}).feedback()["hint"]
    n = GateReport(gates={"G2": "fail"}, findings=[F("G2-FREQ")], sim=None, details={}).feedback()["hint"]
    assert "waived_requirements" in w and "waived_requirements" not in n


def test_feedback_hint_on_pass_names_gates_that_were_not_verified():
    hint = GateReport(gates={"G1": "pass", "G5": "skipped", "G3": "off"}, findings=[], sim=None, details={}).feedback()["hint"]
    assert "G5" in hint and "G1" not in hint


def test_report_to_dict_is_json_serialisable_and_complete():
    r = GateReport(gates={"G1": "pass"}, findings=[F("G2-FREQ")], sim={"ok": True, "violations": []}, details={"claims_checked": 3})
    d = json.loads(json.dumps(r.to_dict()))
    assert d["passed"] is False and d["gates"] == {"G1": "pass"} and d["sim"] == {"ok": True, "violations": []}
    assert d["findings"][0]["code"] == "G2-FREQ" and d["details"] == {"claims_checked": 3} and d["failed_codes"] == ["G2-FREQ"]


def test_tool_error_recognises_hub_sandbox_and_board_state_failures_only():
    from agent.gate.types import tool_error
    assert tool_error({"error": "timed out after 60 s"}) == "timed out after 60 s"
    assert tool_error({"ok": False, "error": {"code": "NO_SUCH_SECTION", "message": "unknown section"}}) == "NO_SUCH_SECTION: unknown section"
    assert tool_error("boom") == "unexpected result type str"
    assert tool_error({"ok": True, "data": []}) is None and tool_error({"status": "ok", "errors": []}) is None


def test_requirement_reference_keeps_simple_ids_bare_and_quotes_ids_with_spaces():
    from agent.gate.types import requirement_id, requirement_ref
    assert requirement_ref("R1") == "requirement R1" and requirement_id("requirement R1 (PA8 PWM)") == "R1"
    assert requirement_ref("PWM PA8") == 'requirement "PWM PA8"' and requirement_id('requirement "PWM PA8" (PA8 PWM)') == "PWM PA8"
    assert requirement_id('requirement "a \\"b\\" c"') == 'a "b" c' and requirement_id("code block 1, line 3") is None
