"""P5 bước 1 (D37): sửa lỗi review runtime P4 — I1, I3 (khoá cache tất định), I4, I5, m1, m2, m4, m5, m6 và kiểm cặp tool_call/tool của ScriptedPolicy."""
import hashlib
import json
import re

import pytest

from agent.scripted import ScriptedPolicy, calls, say, tool
from runtime_fakes import FakeFinding, FakeGate, FakeReport, fail, ok
from runtime_helpers import build, of, sid, types

SETUP = calls(("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}),
              ("allocate_pin", {"pin": "PA8", "signal": "TIM1_CH1", "owner": "R1-pwm"}))
BAD = ("allocate_pin", {"pin": "PA8", "signal": "I2C3_SCL", "owner": "R2-i2c"})
SIM_BAD = {"chip": "stm32g474", "ops": [{"op": "write", "reg": "TIM1_PSC", "value": 0}], "initial": "reset"}


# ---------------------------------------------------------------- ScriptedPolicy kiểm cặp tool_call/tool
def test_scripted_policy_rejects_a_request_with_an_unanswered_tool_call():
    pol = ScriptedPolicy([say("x")])
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "goal"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "list_chips", "arguments": "{}"}},
                                                               {"id": "c2", "type": "function", "function": {"name": "list_chips", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{}"}]
    with pytest.raises(AssertionError, match="c2"):
        pol.chat(msgs, [])


def test_scripted_policy_rejects_a_tool_message_without_its_call_and_accepts_a_well_formed_history():
    pol = ScriptedPolicy([say("x"), say("y")])
    bad = [{"role": "user", "content": "goal"}, {"role": "tool", "tool_call_id": "zz", "content": "{}"}]
    with pytest.raises(AssertionError, match="zz"):
        pol.chat(bad, [])
    good = [{"role": "user", "content": "goal"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{}"}]
    assert ScriptedPolicy([tool("t"), say("x")]).chat(good, []).content == "x"


# ---------------------------------------------------------------- I1: escalate giữa lô tool call
def test_escalating_in_the_middle_of_a_batch_answers_every_call_before_the_wrapup(tmp_path):
    seen = {}

    def wrapup(messages, tools):                                    # ScriptedPolicy kiểm cặp ở chat(); thêm: mọi call đều có tool message
        ids = [c["id"] for m in messages if m.get("tool_calls") for c in m["tool_calls"]]
        answered = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
        seen["unanswered"] = [i for i in ids if i not in answered]
        seen["skipped"] = [c for c in answered.values() if "not executed" in c]
        return say("Best effort: use PC8.")

    batch = calls(BAD, ("list_chips", {}), ("list_chips", {}))
    out = build(tmp_path, [SETUP, tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), batch, wrapup], ablations="A1").ask("goal", session_id=sid())
    assert out["status"] == "escalated" and seen["unanswered"] == [] and len(seen["skipped"]) == 2
    assert out["answer"].startswith("Best effort")


def test_the_wrapup_receives_the_compacted_view_not_the_full_history(tmp_path):
    seen = {}

    def wrapup(messages, tools):
        seen["longest"] = max((len(m["content"]) for m in messages if m["role"] == "tool"), default=0)
        return say("Best effort.")

    long_tool = tool("get_register_bitfields", chip="stm32g474", peripheral="TIM1", register="TIM1_CR1")
    steps = [long_tool, long_tool, long_tool, SETUP, tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), wrapup]
    out = build(tmp_path, steps, ablations="A1", compact_keep=2, compact_chars=200).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and seen["longest"] < 1000


# ---------------------------------------------------------------- I4: chân trang ESCALATED không chứa mã thô
def test_the_escalation_footer_has_no_raw_error_codes(tmp_path):
    out = build(tmp_path, [SETUP, tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), say("Best effort.")],
                ablations="A1").ask("goal", session_id=sid())
    assert out["status"] == "escalated"
    footer = out["answer"].split("\n---\n", 1)[1]
    assert "CONFLICT" not in footer and "PA8" not in footer and not re.search(r"\bx\d+\b", footer) and "What was tried" in footer
    assert out["escalation"]["code"] == "CONFLICT:PA8" and "CONFLICT:PA8" in json.dumps(out["escalation"]["tried"])         # mã vẫn có trong trace/escalation
    assert of(out, "escalated")[0]["code"] == "CONFLICT:PA8"


def test_the_gate_failure_footer_names_requirements_without_codes(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say(f"draft {i}") for i in range(1, 6)], gate=gate).ask("goal", session_id=sid())
    assert out["status"] == "escalated"
    footer = out["answer"].split("\n---\n", 1)[1]
    assert "G2-FREQ" not in footer and "R1" in footer and "What was tried" in footer


# ---------------------------------------------------------------- I5: bản nháp lỗi G4 không được trả; wrap-up qua G4
def _g4_fail(code="G4-5V-NON-FT"):
    return FakeReport([FakeFinding(code, gate="G4", kind="structural", where="board.pins.PC5", expected="<= 3.6 V", actual="5 V on a non-FT pin")],
                      {"G1": "pass", "G2": "pass", "G3": "na", "G4": "fail", "G5": "skipped"})


def test_a_draft_that_failed_the_safety_gate_is_never_the_best_candidate(tmp_path):
    gate = FakeGate([_g4_fail(), fail("A", "B", "C"), fail("A", "B", "C"), fail("A", "B", "C")])
    out = build(tmp_path, [say("UNSAFE: connect the 5 V output to PC5"), say("safe draft 2"), say("safe draft 3"), say("safe draft 4"), say("never")], gate=gate,
                max_repairs=2).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and "UNSAFE" not in out["answer"] and out["answer"].startswith("safe draft")


def test_when_every_draft_failed_g4_the_fallback_states_the_safety_finding_in_words(tmp_path):
    gate = FakeGate([_g4_fail()])
    out = build(tmp_path, [say(f"UNSAFE draft {i}") for i in range(1, 7)], gate=gate, escalate_wrapup=False).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and "UNSAFE" not in out["answer"]
    assert "safety" in out["answer"].lower() and "5 V on a non-FT pin" in out["answer"]


class _SafetyGate(FakeGate):
    """FakeGate có `safety_only` (cổng G4 chạy riêng cho văn bản wrap-up): fail khi văn bản chứa 'UNSAFE'."""

    def __init__(self, reports):
        super().__init__(reports)
        self.safety_calls = []

    def safety_only(self, ctx):
        self.safety_calls.append(ctx.answer)
        return _g4_fail() if "UNSAFE" in ctx.answer else ok()


def test_the_wrapup_text_runs_through_the_safety_gate_and_a_safe_one_is_returned(tmp_path):
    gate = _SafetyGate([ok()])
    out = build(tmp_path, [SETUP, tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), say("Use PC8 instead.")],
                gate=gate, ablations="A1").ask("goal", session_id=sid())
    assert out["status"] == "escalated" and gate.safety_calls == ["Use PC8 instead."] and out["answer"].startswith("Use PC8 instead.")


def test_an_unsafe_wrapup_text_is_replaced_by_the_fallback_with_the_finding_in_words(tmp_path):
    gate = _SafetyGate([ok()])
    out = build(tmp_path, [SETUP, tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), tool(*BAD[:1], **BAD[1]), say("UNSAFE: apply 6 V to VDD, it is fine.")],
                gate=gate, ablations="A1").ask("goal", session_id=sid())
    assert out["status"] == "escalated" and "UNSAFE" not in out["answer"] and "apply 6 V" not in out["answer"]
    assert "safety" in out["answer"].lower() and "5 V on a non-FT pin" in out["answer"]


# ---------------------------------------------------------------- m1: tham số tool không phải object
@pytest.mark.parametrize("raw", [None, [], "abc", 3])
def test_tool_arguments_that_are_not_an_object_become_a_malformed_observation(tmp_path, raw):
    seen = {}

    def after(messages, tools):
        seen["tool"] = [m["content"] for m in messages if m["role"] == "tool"]
        return say("recovered")

    out = build(tmp_path, [("calls", [("list_chips", raw)]), after]).ask("goal", session_id=sid())
    assert out["status"] == "answered" and out["answer"] == "recovered" and "malformed" in seen["tool"][0]
    assert of(out, "tool_call")[0]["ok"] is False


# ---------------------------------------------------------------- m2: args_sha
def test_tool_call_events_carry_a_hash_of_the_full_arguments(tmp_path):
    a = {"code": "x" * 600 + "A", "chip": "stm32g474"}
    b = {"code": "x" * 600 + "B", "chip": "stm32g474"}
    out = build(tmp_path, [tool("analyze_c_code", **a), tool("analyze_c_code", **b), say("ok")]).ask("goal", session_id=sid())
    tcs = of(out, "tool_call")
    assert tcs[0]["args"] == tcs[1]["args"] or True                     # args bị cắt 400 ký tự có thể trùng; args_sha thì phải khác
    assert tcs[0]["args_sha"] != tcs[1]["args_sha"] and re.fullmatch(r"[0-9a-f]{16,64}", tcs[0]["args_sha"])
    canon = hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    assert tcs[0]["args_sha"] == canon[:len(tcs[0]["args_sha"])]


# ---------------------------------------------------------------- m4: sandboxed-exec chạy lại khi resume
class SimulatedKill(BaseException):
    pass


def test_a_sandboxed_exec_tool_that_was_running_when_the_process_died_is_run_again_on_resume(tmp_path):
    s = sid()
    rt1 = build(tmp_path, [tool("compile_check", code="int main(void){return 0;}", chip="stm32g474"), say("ok")])

    def die(**kw):
        raise SimulatedKill("died while the tool was running")

    rt1.hub._fn["compile_check"] = die
    with pytest.raises(SimulatedKill):
        rt1.ask("goal", session_id=s)
    st = rt1.store.load(rt1.current_run_id)
    assert st.in_flight is None and len(st.pending_calls) == 1               # không phải tool có trạng thái: không đánh dấu at-most-once
    rt2 = build(tmp_path, [tool("compile_check", code="int main(void){return 0;}", chip="stm32g474"), say("ok")], db=tmp_path / "ck.sqlite")
    out = rt2.resume(rt1.current_run_id)
    assert out["answer"] == "ok" and out["usage"]["tool_calls"] == 1 and of(out, "tool_call")[0]["tool"] == "compile_check"


# ---------------------------------------------------------------- m5: ảnh chụp Board State ở INTAKE là bằng chứng cho Gate
def test_the_intake_board_snapshot_is_an_observation_for_the_gate(tmp_path):
    s = sid()
    gate = FakeGate()
    rt = build(tmp_path, [tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), say("turn 1 done"), say("turn 2 done")], gate=gate)
    rt.ask("turn 1", session_id=s)
    rt.ask("turn 2", session_id=s)
    obs = gate.contexts[-1].observations
    snap = [o for o in obs if o["tool"] == "get_board_state"]
    assert snap and snap[0]["result"]["state"]["targets"][0]["chip"] == "stm32g474"


def test_the_intake_hardware_check_results_are_observations(tmp_path):
    rt = build(tmp_path, [say("never reached: the guardrail refuses first")])
    out = rt.ask("Apply 5 V to the VDD of the STM32G474.", session_id=sid())
    assert out["status"] == "refused"
    assert any(o["tool"] == "get_electrical_specs" for o in rt.store.load(out["run_id"]).observations)


# ---------------------------------------------------------------- m6: CLOCK_LIMIT:FLASH_WS là lỗi cục bộ
def _classify(tmp_path, violations):
    from agent.runtime.state import AgentState
    rt = build(tmp_path, [say("x")])
    state = AgentState.new(run_id="r1", project_id=sid(), goal="g", turn=0)
    rt._state = state
    rt._classify(state, "set_clock_config", {}, {"ok": True, "version": 3, "violations": [{"code": c} for c in violations]})
    return state


def test_flash_wait_state_violation_is_not_structural_and_needs_no_replan(tmp_path):
    state = _classify(tmp_path, ["CLOCK_LIMIT:FLASH_WS"])
    assert state.replan_pending is None and state.iteration_counters == {"CLOCK_LIMIT:FLASH_WS": 1}


def test_other_clock_limit_violations_stay_structural(tmp_path):
    state = _classify(tmp_path, ["CLOCK_LIMIT:SYSCLK"])
    assert state.replan_pending is not None and state.replan_pending["code"] == "CLOCK_LIMIT:SYSCLK"


# ---------------------------------------------------------------- I3: lời gọi LLM tất định theo (task, seed)
def _fingerprint(tmp_path, tag, monkeypatch):
    monkeypatch.setenv("BOARD_STATE_DB", str(tmp_path / tag / "board.sqlite"))          # như eval: mỗi run một Board State riêng
    sent = []

    def spy(messages, tools):
        sent.append(hashlib.sha256(json.dumps([messages, tools], sort_keys=True, default=str).encode()).hexdigest())
        return say("done")

    steps = [tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), tool("get_board_state"), spy]
    out = build(tmp_path / tag, steps).ask("Plan a PWM output on PA8.", session_id="C4-001-s0")
    assert out["status"] == "answered"
    return sent[0]


def test_two_runs_with_the_same_session_id_send_byte_identical_prompts(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert _fingerprint(tmp_path, "a", monkeypatch) == _fingerprint(tmp_path, "b", monkeypatch)


# ---------------------------------------------------------------- m7: ba đột biến sống sót ở review P4
def test_m7_the_session_history_is_written_once_however_often_a_finished_run_is_resumed(tmp_path):
    rt = build(tmp_path, [say("done")])
    s = sid()
    out = rt.ask("goal", session_id=s)
    rt.resume(out["run_id"])
    rt.resume(out["run_id"])
    assert len(rt.store.session(s)["history"]) == 1


def test_m7_an_escalated_answer_is_not_evidence_for_the_next_turn(tmp_path):
    gate = FakeGate([fail("G2-FREQ")] * 4 + [ok()])
    s = sid()
    pol = ScriptedPolicy([[say(f"bad {i}") for i in range(1, 5)], [say("turn 2 answer")]])
    rt = build(tmp_path, [], policy=pol, gate=gate)
    assert rt.ask("turn 1", session_id=s)["status"] == "escalated"
    rt.ask("turn 2", session_id=s)
    assert gate.contexts[-1].prior_answers == []


def test_m7_an_empty_reply_is_not_a_final_answer(tmp_path):
    out = build(tmp_path, [say(""), say("real answer")]).ask("goal", session_id=sid())
    assert out["answer"] == "real answer" and out["usage"]["llm_calls"] == 2 and len(of(out, "finish")) == 1
