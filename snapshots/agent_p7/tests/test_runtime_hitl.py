"""P5 bước 4: interrupt/resume — ask_human (clarify, choice), write_config_file qua interrupt `approval`, ResumeError, giới hạn hỏi, A6, mời hỏi khi leo thang, kill tiến trình."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import config
from agent.runtime.hitl import ResumeError
from agent.scripted import ScriptedPolicy, calls, say, tool
from runtime_fakes import FakeGate, fail, ok
from runtime_helpers import build, of, sid, strip, types

ASK_HSE = tool("ask_human", kind="clarify", question="What is the HSE crystal frequency of your board?", why_needed="the PLL settings depend on it")
ASK_CHOICE = tool("ask_human", kind="choice", question="How should the 1.8 V sensor be connected?", why_needed="depends on your preference",
                  options=[{"label": "level shifter", "pros": "keeps the sensor", "cons": "extra part"}, {"label": "3.3 V sensor", "pros": "no extra part", "cons": "changes the BOM"}])
WRITE = tool("write_config_file", filename="clock.h", content="#define HSE_HZ 8000000\n")
PLAN = [{"id": "s1", "title": "revise: write a different file", "status": "doing"}]


def asked(tmp_path, steps, **kw):
    rt = build(tmp_path, steps, hitl=True, **kw)
    out = rt.ask("goal", session_id=sid())
    return rt, out


# ---------------------------------------------------------------- clarify
def test_a_clarify_question_interrupts_and_the_answer_is_recorded_and_used(tmp_path):
    gate = FakeGate()
    seen = {}

    def after(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        return say("PLL for 8 MHz")

    rt, out = asked(tmp_path, [ASK_HSE, after], gate=gate)
    assert out["status"] == "interrupted" and out["answer"] == "" and out["usage"]["asks"] == 1
    itr = out["interrupt"]
    assert itr["kind"] == "clarify" and itr["tool"] == "ask_human" and itr["id"].startswith("i_") and "HSE" in itr["question"] and itr["why_needed"] and itr["options"] is None
    assert types(out)[-1] == "interrupt_raised" and rt.store.load(out["run_id"]).status == "INTERRUPTED"
    done = rt.resume(out["run_id"], itr["id"], "answer", {"answer": "The board has an 8 MHz crystal on HSE."})
    assert done["status"] == "answered" and done["answer"] == "PLL for 8 MHz"
    assert seen["tool"]["answered"] is True and "8 MHz" in seen["tool"]["answer"]
    assert [e["type"] for e in done["events"]][0] == "resumed" and of(done, "resumed")[0]["interrupt_id"] == itr["id"] and of(done, "resumed")[0]["decision"] == "answer"
    ctx = gate.contexts[0]
    assert "The board has an 8 MHz crystal on HSE." in ctx.user_texts and ctx.hse_hz == 8_000_000 and ctx.start["hse_source"] == "user_text"
    reqs = {r["id"]: r for r in done["board_state"]["requirements"]}
    assert reqs["CLARIFY-1"]["answer"].startswith("The board has an 8 MHz") and reqs["CLARIFY-1"]["evidence"] == f"human:{itr['id']}"


def test_events_of_ask_and_resume_are_disjoint_and_together_complete(tmp_path):
    rt, out = asked(tmp_path, [ASK_HSE, say("done")])
    done = rt.resume(out["run_id"], out["interrupt"]["id"], "answer", {"answer": "8 MHz crystal on HSE"})
    seqs = [e["seq"] for e in out["events"]] + [e["seq"] for e in done["events"]]
    assert seqs == sorted(set(seqs)) and seqs[0] == 1 and len(seqs) == max(seqs)


def test_unknown_answer_tells_the_agent_to_decide_and_records_nothing(tmp_path):
    seen = {}

    def after(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        return say("assumed 8 MHz")

    rt, out = asked(tmp_path, [ASK_HSE, after])
    done = rt.resume(out["run_id"], out["interrupt"]["id"], "unknown", {})
    assert seen["tool"]["answered"] is False and "assumption" in seen["tool"]["note"] and not [r for r in done["board_state"]["requirements"] if r["id"].startswith("CLARIFY")]


@pytest.mark.parametrize("args,why", [({"kind": "clarify", "question": "q"}, "why_needed"), ({"kind": "ask", "question": "q", "why_needed": "w"}, "kind"),
                                      ({"kind": "choice", "question": "q", "why_needed": "w", "options": [{"label": "only"}]}, "options"),
                                      ({"kind": "clarify", "question": "q", "why_needed": "w", "options": [{"label": "a"}, {"label": "b"}]}, "options")])
def test_invalid_ask_human_arguments_are_an_observation_not_an_interrupt(tmp_path, args, why):
    seen = {}

    def after(messages, tools):
        seen["tool"] = [m["content"] for m in messages if m["role"] == "tool"][-1]
        return say("ok")

    rt = build(tmp_path, [tool("ask_human", **args), after], hitl=True)
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "answered" and why in seen["tool"] and out["usage"]["asks"] == 0


# ---------------------------------------------------------------- choice
def test_a_choice_interrupt_carries_the_options_and_the_decision_is_recorded_by_the_human(tmp_path):
    seen = {}

    def after(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        return say("going with the shifter")

    rt, out = asked(tmp_path, [ASK_CHOICE, after])
    itr = out["interrupt"]
    assert itr["kind"] == "choice" and [o["id"] for o in itr["options"]] == ["A", "B"] and itr["options"][0]["pros"] == "keeps the sensor"
    done = rt.resume(out["run_id"], itr["id"], "choose", {"option": "a", "comment": "we want to keep the sensor"})
    assert done["status"] == "answered" and seen["tool"]["chosen"] == "level shifter" and seen["tool"]["decision_id"] == "D1"
    dec = done["board_state"]["decisions"][0]
    assert dec["by"] == "human" and dec["chosen"] == "level shifter" and dec["options"] == ["level shifter", "3.3 V sensor"] and "keeps the sensor" in dec["rationale"]
    assert of(done, "human_decision")[0]["label"] == "level shifter"


def test_choosing_by_label_works_and_an_unknown_option_is_refused_without_consuming_the_interrupt(tmp_path):
    rt, out = asked(tmp_path, [ASK_CHOICE, say("done")])
    itr = out["interrupt"]
    with pytest.raises(ResumeError, match="option"):
        rt.resume(out["run_id"], itr["id"], "choose", {"option": "C"})
    with pytest.raises(ResumeError, match="decision"):
        rt.resume(out["run_id"], itr["id"], "approve", {})
    assert rt.store.load(out["run_id"]).status == "INTERRUPTED"
    done = rt.resume(out["run_id"], itr["id"], "choose", {"option": "3.3 V SENSOR"})
    assert done["status"] == "answered" and done["board_state"]["decisions"][0]["chosen"] == "3.3 V sensor"


# ---------------------------------------------------------------- approval
def test_write_config_file_raises_an_approval_interrupt_and_approve_writes_and_the_agent_continues(tmp_path):
    seen = {}

    def after(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        return say("saved clock.h and finished")

    rt, out = asked(tmp_path, [WRITE, after])
    itr = out["interrupt"]
    assert out["status"] == "interrupted" and itr["kind"] == "approval" and itr["tool"] == "write_config_file"
    assert itr["payload"]["filename"] == "clock.h" and "+#define HSE_HZ 8000000" in itr["payload"]["diff"] and itr["payload"]["overwrites"] is False
    assert not (config.SANDBOX_DIR / "clock.h").exists()                                       # chưa duyệt thì chưa ghi
    done = rt.resume(out["run_id"], itr["id"], "approve", {})
    assert done["status"] == "answered" and done["answer"] == "saved clock.h and finished"
    assert seen["tool"]["status"] == "executed" and seen["tool"]["filename"] == "clock.h" and str(config.SANDBOX_DIR) not in json.dumps(seen["tool"])
    assert (config.SANDBOX_DIR / "clock.h").read_text() == "#define HSE_HZ 8000000\n" and done["files"] == {"clock.h": "#define HSE_HZ 8000000\n"}
    assert of(done, "file_written")[0]["approver"] == "human"
    (config.SANDBOX_DIR / "clock.h").unlink()


def test_reject_with_feedback_becomes_an_observation_and_the_agent_must_replan(tmp_path):
    seen = {}

    def blocked(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        seen["last_user"] = [m["content"] for m in messages if m["role"] == "user"][-1]
        return tool("list_chips")                                                           # bị chặn: chưa update_plan

    rt, out = asked(tmp_path, [WRITE, blocked, tool("update_plan", steps=PLAN, rationale="user rejected"), say("revised answer")])
    itr = out["interrupt"]
    done = rt.resume(out["run_id"], itr["id"], "reject", {"feedback": "Use a .json file instead"})
    assert done["status"] == "answered" and done["answer"] == "revised answer"
    assert seen["tool"]["status"] == "rejected_by_user" and seen["tool"]["feedback"] == "Use a .json file instead" and seen["last_user"].startswith("REPLAN_REQUIRED")
    assert not (config.SANDBOX_DIR / "clock.h").exists()
    assert of(done, "replan_required")[0]["code"] == "USER_REJECTED" and of(done, "plan_updated")[0]["after_replan"] is True
    assert [e["ok"] for e in of(done, "tool_call") if e["tool"] == "list_chips"] == [False]     # bị chặn trong lúc chờ replan
    types_ = types(done)
    assert types_.index("resumed") < types_.index("replan_required") < types_.index("plan_updated")


def test_a_write_the_policy_rejects_never_asks_the_human(tmp_path):
    seen = {}

    def after(messages, tools):
        seen["tool"] = json.loads([m["content"] for m in messages if m["role"] == "tool"][-1])
        return say("ok")

    rt = build(tmp_path, [tool("write_config_file", filename="../evil.sh", content="x"), after], hitl=True)
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "answered" and seen["tool"]["status"] == "rejected_by_policy" and not of(out, "interrupt_raised")


def test_an_approval_in_the_middle_of_a_batch_runs_the_rest_after_the_resume(tmp_path):
    batch = calls(("list_chips", {}), ("write_config_file", {"filename": "clock.h", "content": "x\n"}), ("list_chips", {}))
    rt, out = asked(tmp_path, [batch, say("done")])
    st = rt.store.load(out["run_id"])
    assert out["status"] == "interrupted" and [c["name"] for c in st.pending_calls] == ["write_config_file", "list_chips"]
    done = rt.resume(out["run_id"], out["interrupt"]["id"], "approve", {})
    assert done["status"] == "answered" and [e["tool"] for e in of(done, "tool_call")] == ["write_config_file", "list_chips"]
    (config.SANDBOX_DIR / "clock.h").unlink()


# ---------------------------------------------------------------- ResumeError
def test_resume_validates_the_interrupt_and_never_runs_twice(tmp_path):
    rt, out = asked(tmp_path, [ASK_HSE, say("done")])
    run_id, itr = out["run_id"], out["interrupt"]["id"]
    with pytest.raises(ResumeError, match="waiting"):
        rt.resume(run_id)                                                                    # không có interrupt_id trên run đang chờ người
    with pytest.raises(ResumeError, match="does not match"):
        rt.resume(run_id, "i_wrong", "answer", {"answer": "x"})
    with pytest.raises(ResumeError, match="non-empty"):
        rt.resume(run_id, itr, "answer", {})
    done = rt.resume(run_id, itr, "answer", {"answer": "8 MHz"})
    assert done["status"] == "answered" and done["usage"]["llm_calls"] == 2
    with pytest.raises(ResumeError, match="already resolved"):
        rt.resume(run_id, itr, "answer", {"answer": "8 MHz"})                                # lần hai bị từ chối
    assert rt.store.load(run_id).used["llm_calls"] == 2 and len(of(rt.resume(run_id), "done")) == 1       # không chạy lại gì


def test_resume_of_an_unknown_interrupt_on_a_finished_run_is_an_error(tmp_path):
    rt = build(tmp_path, [say("done")])
    out = rt.ask("goal", session_id=sid())
    with pytest.raises(ResumeError):
        rt.resume(out["run_id"], "i_nope", "answer", {"answer": "x"})


# ---------------------------------------------------------------- giới hạn hỏi, A6
def test_the_ask_limit_turns_extra_questions_into_a_decide_yourself_observation(tmp_path):
    seen = {}

    def after(messages, tools):
        seen["tool"] = [m["content"] for m in messages if m["role"] == "tool"][-1]
        return say("assumed")

    rt = build(tmp_path, [ASK_HSE, ASK_HSE, after], hitl=True, budgets={"ask_human": 1})
    out = rt.ask("goal", session_id=sid())
    out = rt.resume(out["run_id"], out["interrupt"]["id"], "answer", {"answer": "8 MHz"})
    assert out["status"] == "answered" and "no questions left" in seen["tool"] and "assumption" in seen["tool"]
    assert of(out, "ask_limit_reached")[0]["limit"] == 1 and out["usage"]["asks"] == 1 and len(of(out, "interrupt_raised")) == 0         # (sự kiện interrupt đầu thuộc lần ask)


def test_default_ask_budget_is_three(tmp_path):
    rt = build(tmp_path, [ASK_HSE] * 4 + [say("x")], hitl=True)
    out = rt.ask("goal", session_id=sid())
    n = 1
    while out["status"] == "interrupted":
        out = rt.resume(out["run_id"], out["interrupt"]["id"], "answer", {"answer": f"a{n}"})
        n += 1
    assert out["usage"]["asks"] == 3 and n == 4


def test_a6_hides_ask_human_and_auto_approves_the_write_without_an_interrupt(tmp_path):
    pol = ScriptedPolicy([WRITE, say("done")])
    rt = build(tmp_path, [], policy=pol, ablations="A6")
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "answered" and not of(out, "interrupt_raised") and "ask_human" not in pol.offered[0] and "update_plan" in pol.offered[0]
    assert of(out, "file_written")[0]["approver"] == "auto:A6" and (config.SANDBOX_DIR / "clock.h").exists() and of(out, "run_started")[0]["ablations"] == ["A6"]
    (config.SANDBOX_DIR / "clock.h").unlink()
    from agent.runtime.flags import Ablations
    assert Ablations.from_codes("A6").variant() == "-HITL" and Ablations.from_codes("A1,A6").variant() == "-Planner-HITL"
    # ask_human gọi khi đã ẩn => "not available", không interrupt
    out = build(tmp_path, [ASK_HSE, say("ok")], ablations="A6").ask("goal", session_id=sid())
    assert out["status"] == "answered" and of(out, "tool_call")[0]["ok"] is False


def test_the_hitl_tools_are_offered_by_default(tmp_path):
    pol = ScriptedPolicy([say("x")])
    build(tmp_path, [], policy=pol, hitl=True).ask("goal", session_id=sid())
    assert "ask_human" in pol.offered[0]


# ---------------------------------------------------------------- thời gian chờ người
def test_time_spent_waiting_for_the_human_is_not_charged_to_wall_s(tmp_path):
    rt, out = asked(tmp_path, [ASK_HSE, say("done")])
    time.sleep(0.4)
    done = rt.resume(out["run_id"], out["interrupt"]["id"], "answer", {"answer": "8 MHz"})
    assert rt.store.load(done["run_id"]).used["wall_s"] < 0.3


def test_infrastructure_wait_reported_by_the_llm_is_not_charged_to_wall_s(tmp_path):
    class SlowPolicy(ScriptedPolicy):
        infra_wait_s = 0.0

        def chat(self, messages, tools, seed=None):
            time.sleep(0.3)
            self.infra_wait_s += 0.3                                                      # như LLMCache: giới hạn tốc độ/backoff
            return super().chat(messages, tools, seed)

    rt = build(tmp_path, [], policy=SlowPolicy([say("done")]))
    out = rt.ask("goal", session_id=sid())
    st = rt.store.load(out["run_id"])
    assert st.used["wall_s"] < 0.25 and st.used["infra_wait_s"] == pytest.approx(0.3, abs=0.01)
    llm = of(out, "llm_call")[0]
    assert llm["wait_s"] == pytest.approx(0.3, abs=0.01) and llm["latency_s"] >= 0.3


# ---------------------------------------------------------------- ESCALATED -> mời ask_human
def test_repeated_errors_invite_a_question_instead_of_giving_up_and_the_answer_resets_the_counters(tmp_path):
    seen = {}

    def invited(messages, tools):
        seen["invite"] = [m["content"] for m in messages if m["role"] == "user"][-1]
        return tool("ask_human", kind="clarify", question="Which pin may I use instead of PA8?", why_needed="three drafts failed the same check")

    gate = FakeGate([fail("G2-FREQ")] * 4 + [ok()])
    rt = build(tmp_path, [say("d1"), say("d2"), say("d3"), say("d4"), invited, say("d5 with the answer")], gate=gate, hitl=True)
    out = rt.ask("goal", session_id=sid())
    assert out["status"] == "interrupted" and out["interrupt"]["kind"] == "clarify" and seen["invite"].startswith("ESCALATION NOTICE")
    assert of(out, "escalation_invite")[0]["asks_left"] == 3 and not of(out, "escalated")
    done = rt.resume(out["run_id"], out["interrupt"]["id"], "answer", {"answer": "Use PB6."})
    assert done["status"] == "answered" and done["answer"] == "d5 with the answer"


def test_a_second_escalation_after_the_invitation_is_final(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say(f"d{i}") for i in range(1, 8)], gate=gate, hitl=True).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and len(gate.contexts) == 5 and len(of(out, "escalation_invite")) == 1


def test_no_invitation_when_the_ask_budget_is_exhausted_or_hitl_is_off(tmp_path):
    gate = FakeGate([fail("G2-FREQ")])
    out = build(tmp_path, [say(f"d{i}") for i in range(1, 6)], gate=gate, hitl=True, budgets={"ask_human": 0}).ask("goal", session_id=sid())
    assert out["status"] == "escalated" and len(gate.contexts) == 4 and not of(out, "escalation_invite")


# ---------------------------------------------------------------- kill tiến trình thật giữa interrupt và resume
PROBE = Path(__file__).with_name("hitl_probe.py")


def _probe(dir_, mode):
    return subprocess.run([sys.executable, "-I", str(PROBE), str(dir_), mode], capture_output=True, text=True, timeout=300)


def test_resume_in_a_new_process_after_the_old_one_was_killed_equals_the_uninterrupted_run(tmp_path):
    clean_dir, crash_dir = tmp_path / "clean", tmp_path / "crash"
    clean_dir.mkdir()
    crash_dir.mkdir()
    c = _probe(clean_dir, "clean")
    assert c.returncode == 0, c.stderr[-800:]
    k = _probe(crash_dir, "crash")
    assert k.returncode == 137, (k.returncode, k.stderr[-800:])
    first = json.loads(k.stdout.splitlines()[-1])["events"]                                  # sự kiện trả về bởi lần ask trong tiến trình đã bị kill
    r = _probe(crash_dir, "resume")
    assert r.returncode == 0, r.stderr[-800:]
    clean, resumed = json.loads(c.stdout.splitlines()[-1]), json.loads(r.stdout.splitlines()[-1])
    assert resumed["answer"] == "final answer" and resumed["asks"] == 1 and resumed["files"] == {"clock.h": "#define HSE_HZ 8000000\n"}
    drop = ("tokens_in", "tokens_out")
    norm = lambda evs: [{k: v for k, v in e.items() if k not in drop} for e in evs]
    drop_ev = ("ts", "run_id", "seq", "latency_s", "wait_s", "interrupt_id")
    stitched = [{k: v for k, v in e.items() if k not in drop_ev} for e in first] + resumed["events"]
    assert norm(stitched) == norm(clean["events"]) and resumed == {**clean, "events": resumed["events"]}
