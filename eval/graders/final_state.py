"""final_state (gate, C4; D25): chấm SẢN PHẨM CUỐI của hội thoại nhiều lượt bằng `functional_sim` với NHIỀU spec (PWM + I2C + UART + clock + ràng buộc chân).

Mọi hệ (S0…S3) chấm theo cùng một cách: khối code C ở LƯỢT CUỐI — thứ người dùng thực sự nhận. Nếu lượt cuối không có code thì dùng khối code của lượt
gần nhất có code và ghi lý do (`details.fallback`); không có code ở lượt nào => `no_code`. Board State của S3 KHÔNG dùng để chấm (chỉ cho chỉ số quá trình):
chấm S3 bằng trạng thái nội bộ của chính nó là tự chấm.

expected: như functional_sim (initial, hse_hz, spec[]); ràng buộc chân của C4 nằm trong spec (`scl_not_in`, `rx_not_in`, `forbid_pins`, PWM `timer_not_in`/`any_pin`).
Mã lý do: như functional_sim (no_code, unsupported_construct, sim_violation:<mã>, wrong_pin, forbidden_pin_used, wrong_timer, wrong_freq, inactive:...).
"""
from __future__ import annotations

from eval.graders import functional_sim as fs
from eval.schema import RunResult


def source_turn(answers: list[str]) -> tuple[int | None, dict | None]:
    """(chỉ số lượt có code dùng để chấm, thông tin fallback). Lượt cuối có code => fallback None."""
    last = len(answers) - 1
    for i in range(last, -1, -1):
        if fs.extract_c_code(answers[i]).strip():
            if i == last:
                return i, None
            return i, {"from_turn": i, "reason": f"the last turn has no C code block; used the code of turn {i}"}
    return None, None


def grade(task, run, ctx) -> dict:
    if not task.expected.get("spec"):
        raise ValueError(f"{task.id}: expected.spec is required for final_state")
    answers = [t.answer for t in run.turns] or [run.final_answer]
    idx, fallback = source_turn(answers)
    if idx is None:
        res = fs._res(False, ["no_code: no turn of the conversation contains a C code block"], {"blocks": 0})
        res["details"].update(source_turn=None, fallback=None, turns=len(answers))
        return res
    shim = RunResult(system=run.system, variant=run.variant, task_id=run.task_id, seed=run.seed, final_answer=answers[idx], turns=[])
    res = fs.grade(task, shim, ctx)
    res["details"].update(source_turn=idx, fallback=fallback, turns=len(answers))
    return res
