"""REPLAN_REQUIRED, ngân sách tự sửa, ESCALATED (D32), ngân sách run và cờ ablation A1–A4 trên vòng lặp thật."""
import time

import pytest

from agent.scripted import calls, say, tool
from runtime_fakes import FakeGate, fail, ok
from runtime_helpers import build, of, sid, types

PLAN = [{"id": "s1", "title": "pick another pin", "status": "doing"}]
SIM_BAD = {"chip": "stm32g474", "ops": [{"op": "write", "reg": "TIM1_PSC", "value": 0}], "initial": "reset"}      # ghi TIM1 khi TIM1EN = 0 => lỗi cổng clock


# ---------------------------------------------------------------- phản hồi cục bộ và ngân sách tự sửa
def test_the_same_gate_code_beyond_the_repair_budget_escalates_with_the_best_draft(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say("draft 1"), say("draft 2"), say("draft 3"), say("draft 4"), say("never")], gate=gate).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and len(gate.contexts) == 4 and out["usage"]["llm_calls"] == 4
    esc = of(out, "escalated")[0]
    assert esc["reason"] == "repeated_error" and esc["code"] == "G2-FREQ"
    assert out["answer"].startswith("draft 4") and "Not fully verified" in out["answer"] and "G2-FREQ" in out["answer"] and "What was tried" in out["answer"]
    assert "step budget exhausted" not in out["answer"].lower() and out["escalation"]["reason"] == "repeated_error"
    assert [f["accepted"] for f in of(out, "finish")] == [False] * 4 and types(out)[-1] == "done" and of(out, "done")[0]["status"] == "escalated"


def test_the_best_candidate_is_the_one_with_the_fewest_failing_codes(tmp_path):
    gate = FakeGate([fail("A", "B"), fail("A"), fail("A", "C", "D"), fail("A", "B")])
    out = build(tmp_path, [say(f"draft {i}") for i in range(1, 6)], gate=gate).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and out["answer"].startswith("draft 2")


def test_with_reflection_off_the_first_gate_failure_escalates(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say("only draft"), say("never")], gate=gate, ablations="A4").ask("goal", session_id=sid())
    assert out["status"] == "escalated" and len(gate.contexts) == 1 and out["answer"].startswith("only draft")
    assert of(out, "escalated")[0]["reason"] == "repeated_error" and of(out, "run_started")[0]["ablations"] == ["A4"]


def test_a_failure_then_a_pass_does_not_escalate_and_counters_are_kept(tmp_path):
    rt = build(tmp_path, [say("d1"), say("d2")], gate=FakeGate([fail("G2-FREQ"), ok()]))
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "answered" and rt.store.load(out["run_id"]).iteration_counters == {"G2-FREQ": 1}


def test_a_gate_that_crashes_fails_closed_and_never_accepts(tmp_path):
    class Crashing:
        def run(self, ctx):
            raise RuntimeError("gate bug")

    pytest.importorskip("agent.gate.types")
    out = build(tmp_path, [say("a"), say("b"), say("c"), say("d"), say("e")], gate=Crashing()).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and of(out, "escalated")[0]["code"] == "GATE-INTERNAL-ERROR"


# ---------------------------------------------------------------- REPLAN_REQUIRED
def test_a_structural_gate_failure_requires_a_new_plan_before_any_other_action(tmp_path):
    seen = {}

    def second(messages, tools):
        seen["user"] = [m["content"] for m in messages if m["role"] == "user"][-1]
        return tool("list_chips")

    def third(messages, tools):
        seen["blocked"] = [m["content"] for m in messages if m["role"] == "tool"][-1]
        return tool("update_plan", steps=PLAN, rationale="design problem")

    gate = FakeGate([fail("DRC-PIN-01", gate="G3", kind="structural"), ok()])
    out = build(tmp_path, [say("draft"), second, third, tool("list_chips"), say("final")], gate=gate).ask("goal", session_id=sid())
    assert out["status"] == "answered" and out["answer"] == "final"
    assert of(out, "replan_required")[0]["code"] == "DRC-PIN-01"
    assert "REPLAN_REQUIRED" in seen["user"] and "update_plan" in seen["user"]
    assert "REPLAN_REQUIRED" in seen["blocked"] and "NOT executed" in seen["blocked"]
    assert of(out, "plan_updated")[0]["after_replan"] is True
    executed = [e for e in of(out, "tool_call") if e["tool"] == "list_chips" and e["ok"]]
    assert len(executed) == 1                                                  # lần gọi đầu bị chặn, lần sau update_plan mới chạy


def test_a_structural_failure_of_an_explicit_finish_announces_the_replan_after_the_tool_result(tmp_path):
    seen = {}

    def second(messages, tools):
        seen["tail"] = [(m["role"], m["content"][:30]) for m in messages[-2:]]
        return tool("update_plan", steps=PLAN)

    gate = FakeGate([fail("DRC-CLK-01", gate="G3", kind="structural"), ok()])
    out = build(tmp_path, [tool("finish", summary="v1"), second, tool("finish", summary="v2")], gate=gate).ask("goal", session_id=sid())
    assert seen["tail"][0][0] == "tool" and seen["tail"][1][0] == "user" and seen["tail"][1][1].startswith("REPLAN_REQUIRED")
    assert out["answer"] == "v2"


def test_a_local_failure_does_not_trigger_a_replan(tmp_path):
    out = build(tmp_path, [say("a"), say("b")], gate=FakeGate([fail("G2-DUTY"), ok()])).ask("goal", session_id=sid())
    assert of(out, "replan_required") == [] and out["status"] == "answered"


def test_without_the_planner_there_is_no_update_plan_no_replan_and_no_blocking(tmp_path):
    from agent.scripted import ScriptedPolicy
    policy = ScriptedPolicy([say("draft"), tool("list_chips"), tool("update_plan", steps=PLAN), say("final")])
    gate = FakeGate([fail("DRC-PIN-01", gate="G3", kind="structural"), ok()])
    out = build(tmp_path, [], policy=policy, gate=gate, ablations="A1").ask("goal", session_id=sid())
    assert all("update_plan" not in names for names in policy.offered) and "finish" in policy.offered[0]
    assert of(out, "replan_required") == [] and of(out, "plan_updated") == []
    ok_calls = [e["tool"] for e in of(out, "tool_call") if e["ok"]]
    assert "list_chips" in ok_calls                                            # không bị chặn
    bad = [e for e in of(out, "tool_call") if e["tool"] == "update_plan"]
    assert bad and not bad[0]["ok"]                                            # gọi tool đã ẩn => lỗi "not available"
    assert out["answer"] == "final"


def test_a_board_refusal_is_structural_it_requires_a_replan_and_names_the_pin(tmp_path):
    steps = [calls(("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}),
                   ("set_requirements", {"requirements": [{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25}]}),
                   ("allocate_pin", {"pin": "PA8", "signal": "TIM1_CH1", "owner": "R1-pwm"})),
             tool("allocate_pin", pin="PA8", signal="I2C3_SCL", owner="R2-i2c"),
             tool("list_chips"),
             tool("update_plan", steps=PLAN),
             tool("allocate_pin", pin="PC8", signal="I2C3_SCL", owner="R2-i2c"),
             say("done")]
    rt = build(tmp_path, steps)
    out = rt.ask("goal", session_id=sid())
    rp = of(out, "replan_required")
    assert len(rp) == 1 and rp[0]["code"] == "CONFLICT:PA8"
    muts = of(out, "board_mutation")
    assert [m["ok"] for m in muts] == [True, True, True, False, True] and muts[3]["code"] == "CONFLICT"
    assert rt.store.load(out["run_id"]).iteration_counters == {"CONFLICT:PA8": 1}
    assert [e["ok"] for e in of(out, "tool_call") if e["tool"] == "list_chips"] == [False]       # bị chặn khi đang chờ replan
    assert out["board_state"]["pins"]["PC8"]["signal"] == "I2C3_SCL"


def test_repeating_the_same_board_refusal_escalates_and_asks_for_a_wrapup_when_there_is_no_draft(tmp_path):
    setup = calls(("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}),
                  ("allocate_pin", {"pin": "PA8", "signal": "TIM1_CH1", "owner": "R1-pwm"}))
    bad = tool("allocate_pin", pin="PA8", signal="I2C3_SCL", owner="R2-i2c")
    seen = {}

    def wrapup(messages, tools):
        seen["tools"], seen["last"] = list(tools), messages[-1]["content"]
        return say("Best effort: use PC8 for SCL.\n```c\nI2C3->CR1 = 0;\n```")

    out = build(tmp_path, [setup, bad, bad, bad, bad, wrapup], ablations="A1").ask("goal", session_id=sid())
    assert out["status"] == "escalated" and of(out, "escalated")[0]["code"] == "CONFLICT:PA8"
    assert seen["tools"] == [] and "WITHOUT calling any tool" in seen["last"]
    assert out["answer"].startswith("Best effort: use PC8") and "Not fully verified" in out["answer"] and "recurring problems: CONFLICT:PA8 x4" in out["answer"]
    assert out["usage"]["llm_calls"] == 6


def test_repeated_simulator_errors_count_toward_the_same_budget(tmp_path):
    sim = tool("simulate_register_writes", **SIM_BAD)
    out = build(tmp_path, [sim, sim, sim, sim, say("wrap-up text")]).ask("goal", session_id=sid())
    sims = of(out, "sim_result")
    assert len(sims) == 4 and all(not s["pass"] and s["source"] == "agent" and "SIM-CLK-GATE" in s["violations"] for s in sims)
    assert out["status"] == "escalated" and of(out, "escalated")[0]["code"] == "SIM-CLK-GATE"


def test_the_initial_state_used_for_the_gate_follows_the_agents_last_simulation(tmp_path):
    gate = FakeGate()
    ok_sim = {"chip": "stm32g474", "ops": [], "initial": "sysclk_170mhz_pll_hsi16_apb_div1", "hse_hz": 8000000}
    build(tmp_path, [tool("simulate_register_writes", **ok_sim), say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].initial == "sysclk_170mhz_pll_hsi16_apb_div1" and gate.contexts[0].hse_hz == 8000000


# ---------------------------------------------------------------- ngân sách của run
def test_step_budget_exhaustion_returns_a_best_effort_answer_never_an_empty_message(tmp_path):
    out = build(tmp_path, [tool("list_chips"), tool("list_chips"), tool("list_chips"), say("wrap-up answer")], budgets={"steps": 3}).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and of(out, "escalated")[0]["reason"] == "budget:steps"
    assert out["answer"].startswith("wrap-up answer") and "steps limit" in out["answer"] and "step budget exhausted" not in out["answer"].lower()


def test_exhaustion_without_a_wrapup_falls_back_to_the_plan_and_board_summary(tmp_path):
    steps = [tool("update_plan", steps=PLAN), tool("set_target", chip="stm32g474", package="LQFP64", vdd=3.3), tool("list_chips")]
    out = build(tmp_path, steps, budgets={"steps": 3}, escalate_wrapup=False).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and "pick another pin" in out["answer"] and "stm32g474" in out["answer"] and "Not fully verified" in out["answer"]


def test_a_draft_that_failed_the_gate_is_returned_when_the_budget_runs_out(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say("candidate"), tool("list_chips"), tool("list_chips")], gate=gate, budgets={"steps": 3}).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and out["answer"].startswith("candidate") and of(out, "escalated")[0]["reason"] == "budget:steps"
    assert out["usage"]["llm_calls"] == 3                                      # có bản nháp => không tốn thêm lời gọi tóm tắt


def test_token_budget_is_enforced(tmp_path):
    out = build(tmp_path, [tool("list_chips"), say("wrap-up")], budgets={"tokens": 100}).ask("goal", session_id=sid())
    assert of(out, "escalated")[0]["reason"] == "budget:tokens"


def test_wall_clock_budget_is_enforced_and_skips_the_extra_llm_call(tmp_path):
    def slow(messages, tools):
        time.sleep(0.05)
        return tool("list_chips")

    out = build(tmp_path, [slow, say("should not be called")], budgets={"wall_s": 0.01}).ask("goal", session_id=sid())
    assert of(out, "escalated")[0]["reason"] == "budget:wall_s" and out["usage"]["llm_calls"] == 1
    assert "could not produce a verified answer" in out["answer"]


# ---------------------------------------------------------------- cờ ablation: tool nào bị ẩn
@pytest.mark.parametrize("flag,hidden,shown", [
    ("A1", {"update_plan"}, {"finish", "set_target", "simulate_register_writes", "search_manual"}),
    ("A2", {"set_target", "get_board_state", "run_drc", "allocate_pin", "set_requirements", "set_clock_config"}, {"update_plan", "finish", "simulate_register_writes", "get_register_bitfields"}),
    ("A3", {"simulate_register_writes", "solve_timer_config", "analyze_c_code", "compile_check"}, {"update_plan", "finish", "set_target", "run_drc", "search_manual"}),
    ("A4", set(), {"update_plan", "finish", "set_target", "simulate_register_writes"}),
])
def test_each_ablation_hides_exactly_its_tools(tmp_path, flag, hidden, shown):
    from agent.scripted import ScriptedPolicy
    policy = ScriptedPolicy([say("x")])
    build(tmp_path, [], policy=policy, ablations=flag).ask("goal", session_id=sid())
    names = set(policy.offered[0])
    assert not hidden & names and shown <= names


def test_without_the_board_state_the_context_has_no_board_and_the_final_snapshot_is_none(tmp_path):
    out = build(tmp_path, [say("x")], ablations="A2").ask("goal", session_id=sid())
    assert out["board_state"] is None


# ---------------------------------------------------------------- trạng thái khởi đầu truyền cho Gate (sửa sau review Gate: C2/C1)
def test_a_failed_simulation_does_not_set_the_start_state(tmp_path):
    gate = FakeGate()
    good = {"chip": "stm32g474", "ops": [], "initial": "sysclk_170mhz_pll_hsi16_apb_div1"}
    bad = {"chip": "stm32g474", "ops": [], "initial": "170mhz-typo"}
    build(tmp_path, [tool("simulate_register_writes", **good), tool("simulate_register_writes", **bad), say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].initial == "sysclk_170mhz_pll_hsi16_apb_div1"


def test_only_the_preset_name_and_hse_are_inherited_never_the_agents_extra_ops(tmp_path):
    gate = FakeGate()
    init = {"preset": "sysclk_170mhz_pll_hsi16_apb_div1", "hse_hz": 8000000, "ops": [{"op": "set_bits", "reg": "TIM1_BDTR", "mask": 32768}]}
    build(tmp_path, [tool("simulate_register_writes", chip="stm32g474", ops=[], initial=init), say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].initial == "sysclk_170mhz_pll_hsi16_apb_div1" and gate.contexts[0].hse_hz == 8000000


def test_the_start_state_chosen_by_the_gate_is_traced_in_the_gate_result(tmp_path):
    from runtime_fakes import FakeReport
    rep = FakeReport(details={"start": {"initial": "reset", "hse_hz": None, "source": "code_configures_clock"}})
    out = build(tmp_path, [say("answer")], gate=FakeGate([rep])).ask("goal", session_id=sid())
    assert of(out, "gate_result")[0]["start"] == {"initial": "reset", "hse_hz": None, "source": "code_configures_clock"}


def test_g1_failures_are_counted_per_claim_so_new_claims_do_not_exhaust_the_repair_budget(tmp_path):
    from runtime_fakes import FakeFinding, FakeReport
    def g1(claim):
        f = FakeFinding("G1-V1", gate="G1", where=f'answer: "{claim}"')
        return FakeReport([f], {"G1": "fail", "G2": "pass", "G3": "na", "G4": "pass", "G5": "skipped"})
    gate = FakeGate([g1("4.0 V"), g1("5.5 V"), g1("3.6 V"), g1("1.8 V"), g1("2.5 V"), ok()])
    rt = build(tmp_path, [say(f"d{i}") for i in range(6)], gate=gate)
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "answered"                                         # 5 lời khẳng định khác nhau không phải "cùng một lỗi lặp lại"
    counters = rt.store.load(out["run_id"]).iteration_counters
    assert counters['G1-V1:answer: "4.0 V"'] == 1 and len(counters) == 5
    # nhưng cùng một lời khẳng định lặp lại thì tính
    gate2 = FakeGate([g1("4.0 V")])
    out2 = build(tmp_path / "x", [say(f"d{i}") for i in range(6)], gate=gate2).ask("goal", session_id=sid())
    assert out2["status"] == "escalated" and of(out2, "escalated")[0]["code"] == 'G1-V1:answer: "4.0 V"'


# ---------------------------------------------------------------- chip truyền cho Gate (pilot: mã nRF52840 bị phân tích như STM32G474)
def test_the_gate_gets_the_chip_of_the_board_target(tmp_path):
    gate = FakeGate()
    build(tmp_path, [tool("set_target", chip="esp32", package=None, vdd=3.3), say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].chip == "esp32"


def test_without_a_board_target_the_chip_comes_from_the_agents_last_tool_call(tmp_path):
    gate = FakeGate()
    build(tmp_path, [tool("get_register_bitfields", chip="nrf52840", peripheral="SAADC"), say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].chip == "nrf52840"


def test_without_any_hint_the_chip_is_unset(tmp_path):
    gate = FakeGate()
    build(tmp_path, [say("answer")], gate=gate).ask("goal", session_id=sid())
    assert gate.contexts[0].chip is None


def test_the_token_budget_default_does_not_bind_before_the_step_budget():
    from agent.runtime.state import Budgets
    b = Budgets()
    assert b.steps == 40 and b.tokens >= 1_500_000


# ---------------------------------------------------------------- thông báo ngân sách (pilot: run hết 40 bước/420 s khi vẫn đang tra cứu, chưa có bản nháp nào)
def test_a_budget_notice_tells_the_agent_to_finalise_when_three_quarters_of_the_steps_are_used(tmp_path):
    seen = {}

    def probe(messages, tools):
        seen.setdefault("users", []).append([m["content"][:30] for m in messages if m["role"] == "user"])
        return tool("list_chips")

    steps = [probe] * 7 + [say("final answer under the notice")]
    out = build(tmp_path, steps, budgets={"steps": 8}).ask("goal", session_id=sid())
    notices = of(out, "budget_notice")
    assert len(notices) == 1 and notices[0]["dimension"] == "steps" and notices[0]["used"] == 6 and notices[0]["limit"] == 8
    before = [u for u in seen["users"][:6]]
    assert not any(any(x.startswith("BUDGET NOTICE") for x in us) for us in before)               # chưa có thông báo trước bước 7
    assert any(x.startswith("BUDGET NOTICE") for x in seen["users"][6])                              # có ở lần gọi LLM thứ 7
    assert out["status"] == "answered" and out["answer"] == "final answer under the notice"


def test_the_notice_is_sent_once_and_also_on_the_wall_clock(tmp_path, monkeypatch):
    import types as _t
    from agent.runtime import loop as loop_mod
    ticks = iter(range(10_000))
    monkeypatch.setattr(loop_mod, "time", _t.SimpleNamespace(monotonic=lambda: float(next(ticks)), time=time.time))        # đồng hồ giả: mỗi checkpoint trôi 1 giây
    out = build(tmp_path, [tool("list_chips")] * 12 + [say("done")], budgets={"steps": 40, "wall_s": 20}).ask("goal", session_id=sid())
    n = of(out, "budget_notice")
    assert len(n) == 1 and n[0]["dimension"] == "wall_s" and n[0]["used"] >= 15


def test_no_notice_when_the_run_finishes_early(tmp_path):
    out = build(tmp_path, [tool("list_chips"), say("done")], budgets={"steps": 40}).ask("goal", session_id=sid())
    assert of(out, "budget_notice") == []
