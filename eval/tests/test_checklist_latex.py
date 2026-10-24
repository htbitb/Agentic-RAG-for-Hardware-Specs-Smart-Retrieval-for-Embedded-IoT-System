"""checklist (P5, sau lượt C5 thật đầu tiên): chuẩn hoá TỔNG QUÁT câu trả lời trước khi chấm — LaTeX (\\mu, \\text{}, \\approx, \\times, khoảng trắng \\, \\ ,
$…$, \\frac, chỉ số dưới), nhấn mạnh markdown (** __ *…*) — áp cho mọi hệ; khối code và code inline giữ NGUYÊN từng byte.
Fixture: câu trả lời THẬT của S0 và S3@P5 copy từ eval/results/dev_baseline_v2/runs.jsonl (eval/tests/fixtures/c5/real_answers_dev_v2.json)."""
import json
from pathlib import Path

import pytest

from eval.graders import checklist
from eval.graders.checklist import normalize_answer
from eval.schema import RunResult, TurnResult, load_tasks

ROOT = Path(__file__).resolve().parents[2]
REAL = json.loads((Path(__file__).parent / "fixtures" / "c5" / "real_answers_dev_v2.json").read_text(encoding="utf-8"))
TASKS = {t.id: t for t in load_tasks(ROOT / "eval" / "tasks", categories=["C5"], oracle=True)}


def real(system, task_id, seed):
    return next(a["final_answer"] for a in REAL if (a["system"], a["task_id"], a["seed"]) == (system, task_id, seed))


def failing(task_id, answer):
    run = RunResult(system="x", variant="", task_id=task_id, seed=0, turns=[TurnResult(answer=answer)], final_answer=answer)
    r = checklist.grade(TASKS[task_id], run, None)
    return sorted(k for k, ok in r["details"]["items"].items() if not ok)


# ------------------------------------------------------------------ đơn vị chuẩn hoá (chuỗi lấy từ câu trả lời thật)
@pytest.mark.parametrize("src,want", [
    (r"**$\approx 2.73\ \mu\text{A}$**", "≈ 2.73 µA"),
    (r"**$\mathbf{4.35\text{ µA}}$**", "4.35 µA"),
    (r"$V_{\text{IH(min)}} = 0.7 \times V_{\text{DD}} = 0.7 \times 3.3\text{ V} = 2.31\text{ V}$", "V IH(min) = 0.7 × V DD = 0.7 × 3.3 V = 2.31 V"),
    (r"$$f_{\text{PLL\_IN}} = \frac{12\,\text{MHz}}{3} = 4\,\text{MHz}$$", "f PLL_IN = 12 MHz / 3 = 4 MHz"),
    (r"$2.66\text{ MHz} \le f_{\text{PLL\_IN}} \le 16\text{ MHz}$", "2.66 MHz ≤ f PLL_IN ≤ 16 MHz"),
    (r"rated for at least **$500\text{ mA}$**", "rated for at least 500 mA"),
    (r"* **PLLM**: $/4 \implies f_{\text{IN}} = 4\text{ MHz}$", "* PLLM: /4 ⇒ f IN = 4 MHz"),
    (r"$\text{PLLN} = 75 \implies f_{\text{VCO}} = 4\text{ MHz} \times 75$", "PLLN = 75 ⇒ f VCO = 4 MHz × 75"),
    (r"a $\pm 2\%$ error, $10^{-6}$", "a ± 2% error, 10^-6"),
    ("*Verification*: complies", "Verification: complies"),
])
def test_latex_and_markdown_emphasis_become_plain_text(src, want):
    assert normalize_answer(src) == want


def test_code_blocks_and_inline_code_are_left_byte_identical():
    code = "```c\nRCC->PLLCFGR = (1U << 4) | (85U << 8); /* $x$ **y** \\times */\nwhile (1) { }\n```"
    inline = "Use `FLASH_ACR_LATENCY_4WS` and `**ptr` here."
    text = f"Plan: $4\\text{{ MHz}}$\n\n{code}\n\n{inline}"
    out = normalize_answer(text)
    assert code in out and inline in out and out.startswith("Plan: 4 MHz")


def test_tables_lines_and_plain_answers_keep_their_structure():
    table = "| **Total** | | **$4.25\\text{ µA}$** | **$8.40\\text{ µA}$** |"
    assert normalize_answer(table) == "| Total | | 4.25 µA | 8.40 µA |"
    plain = "1. Enable HSE.\n2. Set PLLM = 2, PLLN = 85, PLLR = 2.\n\n- 3.3 V rail"
    assert normalize_answer(plain) == plain                                          # câu trả lời thuần văn bản không đổi
    assert normalize_answer("Price is $6 and $8.") == "Price is 6 and 8."           # '$' không phải LaTeX: chỉ bỏ ký hiệu


# ------------------------------------------------------------------ câu trả lời thật
def test_the_controller_example_s3p5_c5_008_seed0_sleep_total_now_passes():
    ans = real("S3@P5", "C5-008", 0)
    assert r"**$\approx 2.73\ \mu\text{A}$**" in ans
    assert "sleep_total" not in failing("C5-008", ans)


@pytest.mark.parametrize("system,task_id,seed,item", [
    ("S0", "C5-008", 1, "sleep_total"),                     # | **Total Sleep Current** | … | **$\mathbf{4.35\text{ µA}}$** |
    ("S0", "C5-002-O", 1, "supply_rating"),                 # at least $500\text{ mA}$
    ("S3@P5", "C5-002", 0, "supply_rating"),
    ("S0", "C5-005", 0, "pll"),                             # **PLLM**: $/4$, **PLLN**: $\times 75$, **PLLR**: $/2$
    ("S0", "C5-005-O", 0, "pll"),                           # $\text{PLLM} = 4 …$
    ("S0", "C5-005-O", 1, "vih_reason"),                    # 0.7 \times V_{\text{DD}} … 2.31\text{ V}
    ("S3@P5", "C5-005-O", 1, "pll"),                        # "2. **PLL Calculation**:" then "- Prescaler $M = 4$:" (PLL nêu ở dòng trên)
    ("S3@P5", "C5-011", 0, "pll"),
    ("S3@P5", "C5-005", 0, "vih_reason"),                   # V_{\text{IH(min)}} = 0.7 \times V_{\text{DD}} = … = 2.31\text{ V}
    ("S3@P5", "C5-005", 0, "pll"),                          # "* **PLL Parameter Synthesis**:" rồi "- Division factor **$\text{M} = 4$**:"
    ("S0", "C5-011", 2, "pll"),
])
def test_format_only_failures_of_real_answers_are_fixed(system, task_id, seed, item):
    assert item not in failing(task_id, real(system, task_id, seed))


def test_hyphenated_compounds_match_spaced_patterns_symmetrically():
    m = {"id": "c", "type": "mentions", "desc": "d", "any_of": [r"(?:logic|voltage)\s+levels?\s+(?:are\s+)?(?:directly\s+)?compatible"]}
    f = {"id": "f", "type": "forbids", "desc": "d", "patterns": [r"level\s+shifter\s+is\s+not\s+needed"]}
    from eval.schema import Task
    t = lambda item: Task(id="C5-900", category="C5", split="dev", turns=[{"user": "q"}], graders=["checklist"], expected={"checklist": [item]})
    grade = lambda item, a: checklist.grade(t(item), RunResult(system="x", variant="", task_id="C5-900", seed=0, final_answer=a), None)["pass"]
    assert grade(m, "The links are 100 % voltage-level compatible.") and grade(m, "Both links are directly logic-level compatible.")
    assert not grade(f, "A level-shifter is not needed.")                        # forbids: cũng chặt hơn đúng như vậy
    assert grade({"id": "p", "type": "mentions", "desc": "d", "any_of": [r"P-?(?:channel\s+)?MOSFET"]}, "a P-channel MOSFET")   # bản gốc vẫn được thử


@pytest.mark.parametrize("system,task_id,seed", [("S3@P5", "C5-002", 1)])
def test_real_hyphenated_compatibility_statement(system, task_id, seed):
    ans = real(system, task_id, seed)
    assert "directly logic-level compatible" in ans and "esp_link_compat" not in failing(task_id, ans)


@pytest.mark.parametrize("system,task_id,seed,item", [
    ("S0", "C5-005-O", 0, "vih_reason"),                    # V_IH,min = 0.3 × V_DD + 0.9 V = 1.89 V: công thức không có trong datasheet (GENUINE)
    ("S3@P5", "C5-005", 0, "sensor_1v8"),                   # không hỏi, giả định breakout 3.3 V (GENUINE)
])
def test_genuine_failures_stay_failures(system, task_id, seed, item):
    assert item in failing(task_id, real(system, task_id, seed))
