"""Gate v3 — G5 Compile (P4_interfaces §2.3): compile_check(code) -> ok = pass; error = G5-COMPILE (dòng/cột/thông điệp đầu tiên, định vị theo khối);
skipped = gate skipped + G5-SKIPPED (unknown, có thể miễn) — không bao giờ là pass, nhưng không chặn khi thiếu toolchain."""
from agent.gate import codeblocks, compile_gate
from test_gate_support import PWM_C, Recorder, fenced


def g5(answer, chip="stm32g474", call=None):
    call = call or Recorder()
    return compile_gate.run(call, codeblocks.program(answer), chip), call


def test_no_code_is_not_applicable_and_calls_nothing():
    res, call = g5("Only prose.")
    assert res.status == "na" and res.findings == [] and call.names() == []


def test_valid_cmsis_code_compiles():
    res, call = g5(fenced(PWM_C))
    assert res.status == "pass" and res.findings == [] and call.names() == ["compile_check"]


def test_a_compile_error_reports_the_first_diagnostic_located_in_its_block():
    code = PWM_C.replace("TIM1->PSC = 0;", "TIM1->PSC = ;")
    res, _ = g5("Intro\n```text\nnot code\n```\n" + fenced(code))
    assert [f.code for f in res.findings] == ["G5-COMPILE"]
    f = res.findings[0]
    assert f.severity == "error" and f.kind == "local" and not f.waivable
    assert f.where.startswith("code block 2, line 7, col ") and "expected expression" in f.actual and f.hint_source.startswith("compile_check")


def test_errors_in_a_wrapped_fragment_point_back_to_the_fragment():
    res, _ = g5("```c\nUSART2->BRR = 0x683;\nUSART2->CR1 = UNKNOWN_MACRO;\n```")
    assert res.findings[0].where.startswith("code block 1, line 2, col ") and "UNKNOWN_MACRO" in res.findings[0].actual


def test_skipped_compilation_is_unknown_and_waivable_never_a_pass():
    res, _ = g5(fenced(PWM_C), chip="esp32")
    assert res.status == "skipped" and [f.code for f in res.findings] == ["G5-SKIPPED"]
    f = res.findings[0]
    assert f.severity == "unknown" and f.waivable is True and "esp32" in f.actual


def test_a_tool_failure_is_unknown_and_skips_the_gate():
    for bad in ({"error": "timed out after 60 s"}, {"status": "weird"}):
        res, _ = g5(fenced(PWM_C), call=Recorder({"compile_check": bad}))
        assert res.status == "skipped" and [f.code for f in res.findings] == ["G5-TOOL-ERROR"] and res.findings[0].severity == "unknown"


def test_a_diagnostic_inside_a_header_names_the_header():
    fake = {"status": "error", "errors": [{"line": 12, "col": 3, "msg": "redefinition of 'x'", "kind": "compile", "file": "stm32g4xx.h"}], "warnings": []}
    res, _ = g5(fenced(PWM_C), call=Recorder({"compile_check": fake}))
    assert res.findings[0].where == "stm32g4xx.h line 12, col 3 (included by the code)"
