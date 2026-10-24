"""Sửa phía grader theo review độc lập C5 (plan/reviews/review_C5.md: G8, G9, G12, G14, G15, B1) — mỗi test dùng đúng chuỗi tái hiện của reviewer."""
import copy
from pathlib import Path

import pytest
import yaml

from eval.context import GradeContext
from eval.graders import checklist, clarify, hitl
from eval.schema import RunResult, Task, TurnResult, load_tasks
from eval.sim_human import UNKNOWN_ANSWER, SimulatedHuman, detect_question
from eval.tests.helpers import mk_run
from eval.tools import verify_tasks as V

FIX = Path(__file__).parent / "fixtures" / "c5"
CTX = GradeContext(manifest=[])


def pll_task(hse=25_000_000, sysclk=150_000_000):
    return Task(id="C5-900", category="C5", split="dev", turns=[{"user": "q"}], graders=["checklist"],
                expected={"checklist": [{"id": "pll", "type": "pll", "desc": "PLL", "hse_hz": hse, "sysclk_hz": sysclk}]})


def pll_ok(text, **kw):
    r = checklist.grade(pll_task(**kw), mk_run(text), None)
    return r["pass"], r


# ------------------------------------------------------------------ G8: dạng văn xuôi / bảng của PLL (C5-006: HSE 25 MHz, M/N/R = 5/60/2 ⇒ 150 MHz)
@pytest.mark.parametrize("text", [
    "PLL M/N/R = 5/60/2 from the 25 MHz HSE.",
    "PLL (M, N, R) = (5, 60, 2).",
    "PLLM/PLLN/PLLR = 5/60/2",
    "| Parameter | Value |\n|---|---|\n| PLLM | 5 |\n| PLLN | 60 |\n| PLLR | 2 |",
    "| PLL field | Setting |\n|---|---|\n| PLLM | /5 |\n| PLLN | x60 |\n| PLLR | /2 |",
    "| **PLLM** (input divider) | 5 |\n| **PLLN** | 60 |\n| **PLLR** | 2 |",
    "| PLLM | PLLN | PLLR | SYSCLK |\n|---|---|---|---|\n| 5 | 60 | 2 | 150 MHz |",
])
def test_reviewer_pll_prose_and_table_formats_pass(text):
    ok, r = pll_ok(text)
    assert ok, (text, r["reasons"])
    d = r["details"]["pll"]["pll"]
    assert (d["m"], d["n"], d["r"]) == (5, 60, 2)


@pytest.mark.parametrize("text", [
    "PLL M/N/R = 4/60/2 from the 25 MHz HSE.",                                     # đúng dạng, sai số
    "| PLLM | 5 |\n| PLLN | 60 |\n| PLLR | 4 |",
    "| PLLM | PLLN | PLLR |\n|---|---|---|\n| 5 | 72 | 2 |",
    "| M | N | R |\n|---|---|---|\n| 5 | 60 | 2 |",                               # bảng không nhắc PLL: không đủ ngữ cảnh
])
def test_wrong_or_context_free_pll_tables_fail(text):
    assert pll_ok(text)[0] is False


def test_a_triple_does_not_leak_a_wrong_bare_r_value():
    _, r = pll_ok("PLL M/N/R = 5/60/2 from the 25 MHz HSE.")
    assert "ambiguous" not in " ".join(r["reasons"])


def test_register_write_through_a_local_variable():
    code = ("```c\nuint32_t cfg = RCC_PLLCFGR_PLLSRC_HSE | ((5U - 1U) << RCC_PLLCFGR_PLLM_Pos) | (60U << RCC_PLLCFGR_PLLN_Pos);\n"
            "cfg |= RCC_PLLCFGR_PLLREN;\nRCC->PLLCFGR = cfg;\n```")
    ok, r = pll_ok(code)
    assert ok and r["details"]["pll"]["pll"]["source"] == "register", r["reasons"]
    assert pll_ok(code.replace("(60U <<", "(72U <<"))[0] is False


# ------------------------------------------------------------------ G9: số và đơn vị của quantity
PWM = {"id": "pwm_freq", "type": "quantity", "match": "any", "unit_out": "Hz", "min": 15840, "max": 16160, "desc": "16 kHz",
       "patterns": [r"PWM[^\n]{0,60}?(?<![\d.,])(?P<v>\d{1,3}(?:[,   ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*-?\s*(?P<u>kHz|Hz)\b"]}
SLEEP = {"id": "s", "type": "quantity", "match": "any", "unit_out": "uA", "min": 11, "max": 20, "desc": "d",
         "patterns": [r"\b(?:total|sum)\b[^\n]{0,200}?(?<![\d.,])(?P<v>\d{1,3}(?:[,   ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<u>[µμu]A|nA|mA|microamps?|nanoamps?)\b"]}


@pytest.mark.parametrize("text", ["PWM frequency: 16,000 Hz.", "PWM frequency: 16 000 Hz.", "PWM frequency: 16 000 Hz.", "PWM frequency: 16 000 Hz.", "PWM at a 16-kHz rate"])
def test_thousands_separators_and_hyphenated_units(text):
    t = Task(id="C5-900", category="C5", split="dev", turns=[{"user": "q"}], graders=["checklist"], expected={"checklist": [PWM]})
    assert checklist.grade(t, mk_run(text), None)["pass"], text


@pytest.mark.parametrize("text,expected", [("Total sleep current = 11.7 microamps.", True), ("Total sleep current = 11,660 nA.", True),
                                           ("Total = 95.5 microamps", False)])
def test_spelled_out_current_units(text, expected):
    t = Task(id="C5-900", category="C5", split="dev", turns=[{"user": "q"}], graders=["checklist"], expected={"checklist": [SLEEP]})
    assert checklist.grade(t, mk_run(text), None)["pass"] is expected


# ------------------------------------------------------------------ G12: khớp từ khoá của SimulatedHuman
C5_001 = [{"id": "hse_hz", "keywords": ["HSE", "crystal", "XTAL", "external oscillator"], "required": True, "value_patterns": ["24"],
           "exclude": ["LSE", "32.768", "ESP32 module"]},
          {"id": "pwm_hz", "keywords": ["PWM frequency", "PWM input"], "required": True, "value_patterns": ["16"]}]
POLICY = {"clarify": {"hse_hz": "The crystal on the STM32's HSE pins is 24 MHz.", "pwm_hz": "The driver needs 16 kHz PWM."}}


def ask(q, hidden=C5_001):
    return SimulatedHuman(POLICY, hidden).respond({"id": "i", "kind": "clarify", "question": q})


def test_an_lse_crystal_question_no_longer_discloses_the_hse_answer():
    r = ask("What load capacitance does the 32.768 kHz LSE crystal need?")
    assert r.record["matched"] == [] and r.decision == "unknown" and r.record["necessary"] is False
    assert ask("Is the 40 MHz crystal already on the ESP32 module?").record["matched"] == []


def test_exclusions_are_per_sentence_so_a_real_hse_question_next_to_an_lse_remark_still_matches():
    r = ask("The LSE crystal is 32.768 kHz. Which crystal is fitted on the HSE pins?")
    assert r.record["matched"] == ["hse_hz"] and "24 MHz" in r.payload["answer"] and "16 kHz" not in r.payload["answer"]


def test_natural_questions_match_through_keywords_and_possessives():
    assert ask("What XTAL frequency is fitted for the STM32?").record["matched"] == ["hse_hz"]
    hidden = [{"id": "vdd", "keywords": ["nRF52840 VDD"], "required": True, "value_patterns": ["3"]}]
    r = SimulatedHuman({"clarify": {"vdd": "3.0 V"}}, hidden).respond({"kind": "clarify", "question": "What is the nRF52840's VDD?"})
    assert r.record["matched"] == ["vdd"]


def test_exclude_is_validated_by_the_schema():
    d = copy.deepcopy(yaml.safe_load((FIX / "c5_tiny.yaml").read_text(encoding="utf-8"))[0])
    d["hidden_info"][0]["exclude"] = ["LSE", "32.768"]
    assert Task.from_dict(d).hidden_info[0]["exclude"] == ["LSE", "32.768"]
    for bad in ("LSE", [""], [3]):
        d["hidden_info"][0]["exclude"] = bad
        with pytest.raises(ValueError, match="exclude"):
            Task.from_dict(d)


# ------------------------------------------------------------------ G14: khối câu hỏi của baseline
@pytest.mark.parametrize("text,must_contain", [
    ("Before I write the design, I need two details:\n- HSE crystal frequency\n- PWM frequency required by your motor driver", "HSE crystal frequency"),
    ("Two things are missing:\n1. The HSE crystal frequency\n2. The PWM frequency the driver needs", "PWM frequency the driver needs"),
    ("**Open questions**\n- What is the HSE crystal frequency?\n- What PWM frequency does the driver need?", "What is the HSE crystal frequency?"),
    ("The HSE frequency is not given; which crystal is fitted?", "which crystal is fitted?"),
    ("The HSE frequency is not specified. Which crystal is fitted on the board?", "Which crystal is fitted on the board?"),
    ("### Missing information\n- HSE crystal frequency\n- sensor supply voltage", "sensor supply voltage"),
])
def test_reviewer_question_blocks_are_detected(text, must_contain):
    q = detect_question(text)
    assert q and must_contain in q, (text, q)


@pytest.mark.parametrize("text", [
    "What happens if the HSE frequency is not given? The PLL cannot be configured.",
    "Missing pull-ups are a common I2C bug.\n- add 4.7 kΩ resistors\n- check the bus",
    "The datasheet value is unknown to many users. Why does it matter? Because the PLL input range is 2.66-16 MHz.",
    "## Steps\n- enable HSE\n- configure the PLL",
    "Known limitations:\n- no DMA\n- no low-power mode",
    "Defaults if not specified:\n- 8 MHz HSE crystal\n- 3.3 V sensor",                # mặc định do hệ tự đặt: không phải câu hỏi (tránh lộ thông tin ẩn)
    "The following features are missing:\n- a level shifter\n- I2C pull-ups",
])
def test_new_rules_do_not_flag_rhetoric_or_plain_lists(text):
    assert detect_question(text) is None, (text, detect_question(text))


def test_new_rules_keep_zero_false_positives_on_the_real_dev_answers():
    import json
    runs = Path(__file__).resolve().parents[1] / "results" / "dev_baseline_v2" / "runs.jsonl"
    if not runs.is_file():
        pytest.skip("dev_baseline_v2 not present")
    hits = [(d["system"], d["task_id"]) for d in map(json.loads, runs.read_text(encoding="utf-8").splitlines())
            for t in d["turns"] if t.get("answer") and detect_question(t["answer"])]
    assert hits == []


# ------------------------------------------------------------------ G15: câu "không biết" có kèm tiếng Anh
def test_the_unknown_answer_keeps_the_d40_wording_and_adds_an_english_gloss():
    assert UNKNOWN_ANSWER.startswith("Không biết, hãy tự chọn phương án hợp lý")
    assert "I don't know" in UNKNOWN_ANSWER and "assumption" in UNKNOWN_ANSWER


# ------------------------------------------------------------------ B1: clarify trên task đủ thông tin
def test_complete_info_runs_without_questions_are_counted_in_the_complete_half():
    t902 = load_tasks(FIX, split="test")[0]
    assert "clarify" in t902.graders and not t902.hidden_info
    rows = []
    for trace in ([], [{"type": "human_reply", "turn": 0, "kind": "text", "question": "q", "matched": [], "necessary": False, "answered": False,
                        "decision": "answer", "source": "baseline_text"}]):
        run = RunResult(system="S0", variant="", task_id=t902.id, seed=len(rows), turns=[TurnResult(answer="a")], final_answer="a", trace=trace)
        rows.append({"tsr_pass": True, "graders": {"clarify": clarify.grade(t902, run, CTX)}})
    c = hitl.clarify_aggregate(rows)["complete"]
    assert c["runs"] == 2 and c["unnecessary"] == 1 and c["unnecessary_per_run"] == 0.5


def test_verify_c5_requires_clarify_on_every_base_c5_task_but_not_on_oracle_variants():
    t = copy.deepcopy(load_tasks(FIX, split="test")[0])
    t.graders = ["checklist"]
    assert any("clarify" in p for p in V.verify_c5(t, CTX))
    o = load_tasks(FIX, oracle=True)[1]
    assert "clarify" not in o.graders and not any("clarify grader" in p for p in V.verify_c5(o, CTX))
