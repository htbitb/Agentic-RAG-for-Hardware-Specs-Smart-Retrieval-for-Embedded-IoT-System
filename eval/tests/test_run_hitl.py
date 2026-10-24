"""run.py (P5, plan/P5_interfaces.md §4): vòng người–hệ với adapter giả — interrupt → SimulatedHuman → resume (hệ có `resume`), quy tắc câu hỏi
văn bản cho baseline (chỉ trên task có người dùng mô phỏng), `error:hitl_loop`, cờ `--c5-oracle`, ước tính chi phí C5. Không mạng, không LLM."""
import json
from pathlib import Path

import pytest
import yaml

from eval import run as R
from eval.adapters.base import FatalAdapterError
from eval.schema import RunResult, Task, TurnResult, load_tasks
from eval.sim_human import UNKNOWN_ANSWER
from eval.tests.test_run import CFG, FakeAdapter, mk

FIX = Path(__file__).parent / "fixtures" / "c5"


def c5(**kw):
    d = yaml.safe_load((FIX / "c5_tiny.yaml").read_text(encoding="utf-8"))[0]
    d.update(kw)
    return Task.from_dict(d)


class Scripted:
    """Adapter giả: trả lần lượt các TurnResult trong `script` cho mỗi send/resume; ghi lại mọi lời gọi."""
    name, variant = "S0", ""

    def __init__(self, script, resume=False):
        self.script, self.calls, self.turns = list(script), [], []
        if resume:
            self.resume = self._resume

    def start(self, task, seed):
        self.task, self.seed, self.turns, self.calls = task, seed, [], []

    def _next(self):
        tr = self.script.pop(0) if self.script else TurnResult(answer="done")
        self.turns.append(tr)
        return tr

    def send(self, msg):
        self.calls.append(("send", msg))
        return self._next()

    def _resume(self, interrupt_id, decision, payload):
        self.calls.append(("resume", interrupt_id, decision, payload))
        return self._next()

    def finish(self):
        return RunResult(system=self.name, variant="", task_id=self.task.id, seed=self.seed, turns=self.turns, final_answer=self.turns[-1].answer,
                         trace=[{"type": "adapter", "turn": 0}])

    def close(self):
        pass


def execute(adapter, task):
    """Như Runner._execute nhưng không qua luồng / file: start → HumanLoop.turn cho mỗi lượt → finish + attach."""
    loop = R.HumanLoop(task)
    adapter.start(task, 0)
    try:
        for t in task.turns:
            loop.turn(adapter, t["user"])
    except R.HitlStop:
        pass
    return loop.attach(adapter.finish())


def replies(res):
    return [e for e in res.trace if e.get("type") == "human_reply"]


def interrupt(kind="clarify", q="What is the HSE crystal frequency?", iid="i_1", options=None):
    return TurnResult(answer="", status="interrupted", interrupt={"id": iid, "kind": kind, "tool": "ask_human", "tool_call_id": "c", "question": q,
                                                                 "why_needed": "PLL", "options": options, "payload": {}})


# ------------------------------------------------------------------ hệ có resume (S3)
def test_an_interrupt_is_answered_by_the_simulated_human_and_the_run_resumes():
    a = Scripted([interrupt(), TurnResult(answer="PLLM = 2 ...")], resume=True)
    res = execute(a, c5())
    assert a.calls == [("send", c5().turns[0]["user"]), ("resume", "i_1", "answer", {"answer": "The board has an 8 MHz crystal on HSE."})]
    (hr,) = replies(res)
    assert hr["source"] == "interrupt" and hr["kind"] == "clarify" and hr["matched"] == ["hse_hz"] and hr["necessary"] is True
    assert hr["interrupt_id"] == "i_1" and hr["turn"] == 0 and hr["decision"] == "answer"
    assert [e for e in res.trace if e["type"] == "resume_result"] == [{"type": "resume_result", "turn": 0, "interrupt_id": "i_1", "status": "answered"}]
    assert res.errors == [] and res.trace[0] == {"type": "adapter", "turn": 0}          # trace của adapter giữ nguyên, sự kiện runner nối sau


def test_choice_and_approval_interrupts_follow_the_policy():
    opts = [{"id": "A", "label": "normal range 1", "pros": "", "cons": ""}, {"id": "B", "label": "boost mode", "pros": "170 MHz", "cons": ""}]
    a = Scripted([interrupt("choice", "Which mode?", "i_1", opts), TurnResult(answer="", status="interrupted",
                  interrupt={"id": "i_2", "kind": "approval", "question": "write clock.h?", "payload": {"filename": "clock.h"}}), TurnResult(answer="ok")], resume=True)
    res = execute(a, c5())
    assert a.calls[1:] == [("resume", "i_1", "choose", {"option": "B"}), ("resume", "i_2", "approve", {})]
    assert [e["kind"] for e in replies(res)] == ["choice", "approval"]


def test_an_adapter_that_interrupts_forever_gets_error_hitl_loop_and_the_conversation_stops():
    t = c5(turns=[{"user": "first"}, {"user": "second"}])
    a = Scripted([interrupt(iid=f"i_{k}") for k in range(50)], resume=True)
    res = execute(a, t)
    limit = t.human_policy["max_answers"] + R.HITL_LOOP_MARGIN
    assert sum(1 for c in a.calls if c[0] == "resume") == limit
    assert ("send", "second") not in a.calls                                             # hệ đang kẹt: không gửi lượt tiếp
    assert any(e.startswith("error:hitl_loop") for e in res.errors)
    (loop,) = [e for e in res.trace if e["type"] == "hitl_loop"]
    assert loop["rounds"] == limit and loop["turn"] == 0
    assert sum(1 for r in replies(res) if r["answered"]) == t.human_policy["max_answers"]      # sau max_answers: unknown


def test_a_resume_that_raises_is_a_system_error_and_the_trace_is_kept():
    class Boom(Scripted):
        def _resume(self, *a):
            raise ValueError("interrupt already used")

    b = Boom([interrupt()])
    b.resume = b._resume
    res = execute(b, c5())
    assert res.errors == ["error:resume:ValueError: interrupt already used"]
    assert [e["status"] for e in res.trace if e["type"] == "resume_result"] == ["error"] and len(replies(res)) == 1


def test_a_fatal_adapter_error_during_resume_propagates():
    class Fatal(Scripted):
        def _resume(self, *a):
            raise FatalAdapterError("worker refused")

    f = Fatal([interrupt()])
    f.resume = f._resume
    with pytest.raises(FatalAdapterError):
        execute(f, c5())


def test_a_hitl_system_is_never_given_the_baseline_text_rule():
    a = Scripted([TurnResult(answer="What crystal frequency does your board use?")], resume=True)
    res = execute(a, c5())
    assert a.calls == [("send", c5().turns[0]["user"])] and replies(res) == []


def test_interrupts_on_an_old_task_are_answered_with_the_default_policy():
    a = Scripted([interrupt(), TurnResult(answer="0x48000000")], resume=True)
    res = execute(a, mk(1))
    assert a.calls[1] == ("resume", "i_1", "unknown", {"answer": UNKNOWN_ANSWER})
    assert replies(res)[0]["necessary"] is False


# ------------------------------------------------------------------ baseline (không có resume)
def test_a_baseline_question_gets_one_extra_user_turn_with_the_answer():
    a = Scripted([TurnResult(answer="Draft.\n\nWhat HSE crystal frequency does your board use?"), TurnResult(answer="final answer")])
    res = execute(a, c5())
    assert a.calls == [("send", c5().turns[0]["user"]), ("send", "The board has an 8 MHz crystal on HSE.")]
    assert [t.answer for t in res.turns] == ["Draft.\n\nWhat HSE crystal frequency does your board use?", "final answer"] and res.final_answer == "final answer"
    (hr,) = replies(res)
    assert hr["source"] == "baseline_text" and hr["kind"] == "text" and hr["turn"] == 0 and "interrupt_id" not in hr


def test_a_baseline_that_keeps_asking_gets_at_most_max_answers_extra_turns():
    a = Scripted([TurnResult(answer="Which LED colour do you want?")] * 10)
    res = execute(a, c5())
    assert len(a.calls) == 1 + c5().human_policy["max_answers"] and len(replies(res)) == 3
    assert [r["turn"] for r in replies(res)] == [0, 1, 2] and all(c[1] == UNKNOWN_ANSWER for c in a.calls[1:])


def test_a_baseline_without_a_question_or_on_an_old_task_is_unchanged():
    a = Scripted([TurnResult(answer="Here is the code.")])
    assert len(execute(a, c5()).turns) == 1 and len(a.calls) == 1
    b = Scripted([TurnResult(answer="What is your HSE frequency?")])
    res = execute(b, mk(1))                                                              # C1: không có người dùng mô phỏng
    assert len(b.calls) == 1 and replies(res) == [] and res.trace == [{"type": "adapter", "turn": 0}]


def test_a_baseline_error_turn_is_not_followed_up():
    a = Scripted([TurnResult(answer="What is your HSE?", status="error")])
    assert len(execute(a, c5()).turns) == 1


def test_complete_info_and_oracle_tasks_still_record_unnecessary_baseline_questions():
    t902 = load_tasks(FIX, split="test")[0]
    a = Scripted([TurnResult(answer="Which LED do you want to blink?"), TurnResult(answer="ok")])
    res = execute(a, t902)
    assert replies(res)[0]["necessary"] is False and a.calls[1] == ("send", UNKNOWN_ANSWER)
    oracle = load_tasks(FIX, oracle=True)[1]
    b = Scripted([TurnResult(answer="What crystal does your board use?"), TurnResult(answer="ok")])
    assert replies(execute(b, oracle))[0]["necessary"] is False


def test_multi_turn_indices_count_every_message_sent():
    t = c5(turns=[{"user": "goal"}, {"user": "now code"}])
    a = Scripted([TurnResult(answer="What is your HSE crystal?"), TurnResult(answer="plan"), TurnResult(answer="Is your sensor 1.8 V?"), TurnResult(answer="code")])
    res = execute(a, t)
    assert [c[1] for c in a.calls] == ["goal", "The board has an 8 MHz crystal on HSE.", "now code", UNKNOWN_ANSWER]
    assert [r["turn"] for r in replies(res)] == [0, 2]


# ------------------------------------------------------------------ Runner + CLI
def test_runner_writes_the_human_events_into_runs_jsonl(tmp_path):
    t = c5()
    R.Runner(tmp_path, {"S0": lambda: Scripted([TurnResult(answer="What crystal does your board use?"), TurnResult(answer="fin")])}, workers=1, rps=0).run(
        [("S0", "", t.id, 0)], {t.id: t})
    row = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert row["final_answer"] == "fin" and [e["type"] for e in row["trace"]][-1] == "human_reply" and row["errors"] == []


def test_the_old_fake_adapter_path_is_unchanged(tmp_path):
    t = mk(1, turns=("a", "b"))
    R.Runner(tmp_path, {"S0": FakeAdapter}, workers=1, rps=0).run(R.build_schedule(["S0"], [t], 1), {t.id: t})
    row = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
    assert [x["answer"] for x in row["turns"]] == ["ans:a", "ans:b"] and row["trace"] == [] and row["errors"] == []


def _dry(capsys, monkeypatch, *argv):
    real = R.load_tasks
    monkeypatch.setattr(R, "load_tasks", lambda root, **kw: real(FIX, **kw))
    monkeypatch.setenv("EVAL_LLM_RPM", "0")
    monkeypatch.setenv("EVAL_RATE_FILE", "")
    rc = R.main([*argv, "--systems", "S0", "--cache", "replay", "--split", "dev", "--seeds", "1", "--dry-run"])
    return rc, capsys.readouterr().err


def test_c5_oracle_flag_schedules_the_oracle_variants(capsys, monkeypatch):
    rc, err = _dry(capsys, monkeypatch)
    assert rc == 0 and "Lịch chạy: 1 run" in err
    rc, err = _dry(capsys, monkeypatch, "--c5-oracle")
    assert rc == 0 and "Lịch chạy: 2 run" in err


def test_cost_estimate_counts_an_extra_turn_for_hitl_tasks():
    assert R.task_turns(c5()) == 1 + R.HITL_EXTRA_TURNS and R.task_turns(mk(1, turns=("a", "b"))) == 2
    plain = R.estimate_cost(["S0"], 1, 3, CFG, n_turns=1)
    hitl = R.estimate_cost(["S0"], 1, 3, CFG, n_turns=R.task_turns(c5()))
    assert hitl["llm_calls"] > plain["llm_calls"] and hitl["usd"] > plain["usd"]
