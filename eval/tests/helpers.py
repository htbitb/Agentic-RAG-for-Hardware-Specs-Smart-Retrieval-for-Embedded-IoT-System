from eval.schema import RunResult, Task, TurnResult


def mk_task(expected=None, graders=("exact",), category="C1", question="What is X?", tid="T-1", **kw):
    return Task(id=tid, category=category, split="dev", turns=[{"user": question}], graders=list(graders),
                expected=expected or {}, **kw)


def mk_run(answer, system="S0", sources=None, trace=None, task_id="T-1", files=None):
    tr = list(trace or [])
    if sources is not None:
        tr.append({"type": "sources", "turn": 0, "sources": sources})
    return RunResult(system=system, variant="", task_id=task_id, seed=0, turns=[TurnResult(answer=answer)],
                     final_answer=answer, trace=tr, files=files or {})
