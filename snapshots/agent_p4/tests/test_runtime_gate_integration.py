"""Runtime v3 + Gate THẬT + ToolHub thật + ScriptedPolicy: kịch bản D1 (mô phỏng/ Gate bắt lỗi -> sửa -> qua) mà không tốn API."""
import pytest

from agent.gate import Gate
from agent.runtime.flags import Ablations
from agent.scripted import calls, say, tool
from runtime_helpers import build, of, sid, types

GOOD = """```c
#include "stm32g4xx.h"
int main(void) {
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    GPIOA->MODER &= ~GPIO_MODER_MODE8; GPIOA->MODER |= GPIO_MODER_MODE8_1;
    GPIOA->AFR[1] &= ~(0xFu << 0); GPIOA->AFR[1] |= (6u << 0);
    TIM1->PSC = 0; TIM1->ARR = 8499; TIM1->CCR1 = 2125;
    TIM1->CCMR1 |= (6u << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;
    TIM1->CCER |= TIM_CCER_CC1E;
    TIM1->BDTR |= TIM_BDTR_MOE;
    TIM1->CR1 |= TIM_CR1_CEN;
    while (1) {}
}
```"""
NO_MOE = GOOD.replace("    TIM1->BDTR |= TIM_BDTR_MOE;\n", "")
START = "sysclk_170mhz_pll_hsi16_apb_div1"
SETUP = calls(("set_target", {"chip": "stm32g474", "package": "LQFP64", "vdd": 3.3}),
              ("set_requirements", {"requirements": [{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1}]}),
              ("allocate_pin", {"pin": "PA8", "signal": "TIM1_CH1", "owner": "R1-pwm"}))
SATISFY = tool("set_requirements", requirements=[{"id": "R1", "type": "pwm", "pin": "PA8", "signal": "TIM1_CH1", "freq_hz": 20000, "duty_pct": 25, "tol_pct": 1,
                                                  "status": "satisfied", "evidence": "sim#1"}])
SIM = tool("simulate_register_writes", chip="stm32g474", ops=[], initial=START)
ANSWER = "PA8 carries TIM1_CH1 (AF6). The timer clock is 170 MHz, so PSC = 0 and ARR = 8499 give 20 kHz and CCR1 = 2125 gives a duty cycle of 25 %.\n\n" + GOOD


def test_a_missing_main_output_enable_is_caught_by_the_real_gate_and_fixed(tmp_path):
    seen = {}

    def after_fail(messages, tools):
        seen["feedback"] = [m["content"] for m in messages if m["role"] == "tool"][-1]
        return tool("finish", summary=ANSWER)

    from agent.scripted import ScriptedPolicy
    policy = ScriptedPolicy([SETUP, SIM, SATISFY, tool("finish", summary=ANSWER.replace(GOOD, NO_MOE)), after_fail])
    rt = build(tmp_path, [], policy=policy, gate=_real_gate())
    out = rt.ask("Configure PWM 20 kHz duty 25% on PA8 of an STM32G474 at 170 MHz (PLL from HSI16, APB prescalers 1). CMSIS register code.", session_id=sid())
    assert out["status"] == "answered" and GOOD in out["answer"]
    gates = of(out, "gate_result")
    assert [g["passed"] for g in gates] == [False, True]
    assert "G2-SIM-TIM-MOE" in [f["code"] for f in gates[0]["findings"]]
    sims = [e for e in of(out, "sim_result") if e["source"] == "gate"]
    assert sims[0]["pass"] is False and "SIM-TIM-MOE" in sims[0]["violations"] and sims[1]["pass"] is True
    assert any(e["pin"] == "PA8" and abs(e["pwm_hz"] - 20000) < 1 and abs(e["duty_pct"] - 25) < 0.01 for e in sims[1]["effects"])
    assert "G2-SIM-TIM-MOE" in seen["feedback"] and "hint_source" in seen["feedback"]
    fin = of(out, "finish")
    assert [f["accepted"] for f in fin] == [False, True] and fin[1]["gate"]["G2"] == "pass"


def test_an_unverified_number_in_the_prose_is_rejected_by_g1_then_accepted_after_citing_the_tool_result(tmp_path):
    from agent.scripted import ScriptedPolicy
    wrong = ANSWER.replace("170 MHz", "168 MHz")
    policy = ScriptedPolicy([SETUP, SIM, SATISFY, tool("finish", summary=wrong), tool("finish", summary=ANSWER)])
    out = build(tmp_path, [], policy=policy, gate=_real_gate()).ask("PWM 20 kHz duty 25% on PA8, STM32G474 at 170 MHz. CMSIS code.", session_id=sid())
    gates = of(out, "gate_result")
    assert gates[0]["passed"] is False and any(f["code"] == "G1-V1" for f in gates[0]["findings"]) and out["status"] == "answered"


def test_an_open_requirement_blocks_the_finish_until_it_is_marked_satisfied(tmp_path):
    from agent.scripted import ScriptedPolicy
    policy = ScriptedPolicy([SETUP, SIM, tool("finish", summary=ANSWER), SATISFY, tool("finish", summary=ANSWER)])
    out = build(tmp_path, [], policy=policy, gate=_real_gate()).ask("PWM 20 kHz duty 25% on PA8, STM32G474 at 170 MHz. CMSIS code.", session_id=sid())
    gates = of(out, "gate_result")
    assert "DRC-REQ-01" in [f["code"] for f in gates[0]["findings"]] and gates[1]["passed"] is True


def test_repeating_the_same_unfixed_code_escalates_with_the_unmet_requirement_listed(tmp_path):
    from agent.scripted import ScriptedPolicy
    bad = tool("finish", summary=ANSWER.replace(GOOD, NO_MOE))
    policy = ScriptedPolicy([SETUP, SIM, SATISFY, bad, bad, bad, bad])
    out = build(tmp_path, [], policy=policy, gate=_real_gate()).ask("PWM 20 kHz duty 25% on PA8, STM32G474 at 170 MHz. CMSIS code.", session_id=sid())
    assert out["status"] == "escalated" and "G2-SIM-TIM-MOE" in out["answer"] and "Not fully verified" in out["answer"]
    unmet = out["escalation"]["unmet_requirements"]
    assert unmet and unmet[0]["id"] == "R1" and "G2-SIM-TIM-MOE" in unmet[0]["codes"]            # đã đánh dấu satisfied nhưng mô phỏng của câu trả lời trượt => chưa kiểm chứng
    assert "R1:" in out["answer"] and "pin=PA8" in out["answer"]


def test_with_the_sandbox_ablated_the_gate_does_not_simulate_and_the_missing_moe_passes_unnoticed(tmp_path):
    """A3: G2 tắt, G1 quay về verifier v1; không có công cụ nào bắt thiếu MOE — đúng ý nghĩa của ablation (chỉ để kiểm cờ nối đúng)."""
    from agent.scripted import ScriptedPolicy
    policy = ScriptedPolicy([tool("finish", summary="The 170 MHz clock gives PWM, TIM1 needs BDTR.MOE.\n\n" + NO_MOE)])
    out = build(tmp_path, [], policy=policy, gate=_real_gate("A3"), ablations="A3").ask("PWM on PA8 at 170 MHz", session_id=sid())
    g = of(out, "gate_result")[0]
    assert g["gates"]["G2"] == "off" and g["gates"]["G5"] == "off"
    assert not [e for e in of(out, "tool_call") if e["tool"] in ("simulate_register_writes", "analyze_c_code") and e["internal"]]


def _real_gate(ablations=""):
    abl = Ablations.from_codes(ablations)
    holder = {}

    class Lazy:
        """Gate thật gọi tool qua hub của runtime (runtime.gate_call) — runtime chưa tồn tại lúc dựng gate, nên gắn muộn."""

        def run(self, ctx):
            return holder["gate"].run(ctx)

    lazy = Lazy()
    lazy.attach = lambda rt: holder.__setitem__("gate", Gate(rt.gate_call, abl.gate_flags()))
    return lazy
