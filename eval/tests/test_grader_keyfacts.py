import pytest

from eval.graders import keyfacts
from eval.tests.helpers import mk_run, mk_task


def grade(answer, facts, forbidden=None):
    exp = {"keyfacts": facts}
    if forbidden is not None:
        exp["forbidden"] = forbidden
    return keyfacts.grade(mk_task(exp, graders=("keyfacts",), category="C2"), mk_run(answer), ctx=None)


AF = {"attribute": "af", "value": "AF6", "kind": "text"}
TIM = {"attribute": "timer", "value": "TIM1_CH1", "kind": "text", "aliases": ["TIM1 channel 1"]}
VMAX = {"attribute": "vdd_abs_max", "value": 4.0, "unit": "V", "tol_pct": 1}


def test_all_facts_present_passes_with_f1_one():
    r = grade("PA8 uses AF6 for TIM1_CH1.", [AF, TIM])
    assert r["pass"] and r["score"] == 1.0 and r["details"]["recall"] == 1.0 and r["details"]["precision"] == 1.0


def test_missing_fact_fails_and_reports_recall():
    r = grade("PA8 uses AF6.", [AF, TIM])
    assert not r["pass"] and r["details"]["recall"] == 0.5
    assert any(x.startswith("missing_fact") and "timer" in x for x in r["reasons"])


def test_text_alias_and_case_and_punctuation_insensitive():
    assert grade("it maps to tim1 channel 1 (af6)", [AF, TIM])["pass"]


def test_unit_conversion_and_tolerance():
    assert grade("Absolute maximum VDD is 4000 mV.", [VMAX])["pass"]
    assert grade("Absolute maximum VDD is 4.03 V.", [VMAX])["pass"]                # 0.75% < tol 1%
    assert grade("Absolute maximum VDD is 4.1 V.", [VMAX])["pass"] is False        # 2.5% > tol 1%
    assert grade("Absolute maximum VDD is 4.1 V.", [{**VMAX, "tol_pct": 3}])["pass"]


def test_forbidden_value_is_a_hallucination_even_when_facts_present():
    r = grade("PA8 uses AF6; actually AF2 also works.", [AF], forbidden=[{"attribute": "af", "value": "AF2", "kind": "text"}])
    assert not r["pass"] and r["details"]["hallucination"] is True and r["details"]["precision"] < 1.0
    assert any(x.startswith("hallucinated_value") for x in r["reasons"])


def test_hex_fact():
    f = {"attribute": "addr", "value": "0x40012C00", "kind": "hex"}
    assert grade("TIM1 base is 0x4001 2C00", [f])["pass"]
    assert not grade("TIM1 base is 0x40012D00", [f])["pass"]


def test_plain_number_without_unit():
    f = {"attribute": "psc", "value": 169}
    assert grade("Set PSC to 169.", [f])["pass"] and not grade("Set PSC to 170.", [f])["pass"]


def test_abstention_scores_zero():
    r = grade("Insufficient evidence in the documents.", [AF])
    assert r["score"] == 0.0 and any(x.startswith("abstained") for x in r["reasons"])


def test_requires_facts():
    with pytest.raises(ValueError):
        keyfacts.grade(mk_task({}, graders=("keyfacts",)), mk_run("x"), ctx=None)


# ---- review finding 8 (common.py) --------------------------------------------------------------------------
def test_zero_padded_af_numbers_match():
    assert grade("PB6 uses AF02.", [{"attribute": "af", "value": "AF2"}])["pass"]


def test_plain_number_fact_is_not_satisfied_by_a_table_or_section_number():
    f = {"attribute": "m", "value": 26}
    assert not grade("See Table 26 for details.", [f])["pass"]
    assert grade("The highest HCLK is 26 MHz.", [f])["pass"]
    assert not grade("Section 26.", [f])["pass"]


# ---- review D12: giữ `unit` trong keyfact, sửa phía grader ------------------------------------------------------
def test_range_with_trailing_unit_satisfies_every_quantity_fact():
    facts = [{"attribute": "vdd_max", "value": 3.6, "unit": "V"}, {"attribute": "vdd_min", "value": 2.3, "unit": "V"},
             {"attribute": "vdd_min_flash", "value": 3.0, "unit": "V"}]
    for ans in ("2.3-3.6 V without flash, 3.0-3.6 V with flash", "2.3–3.6 V without flash, 3.0–3.6 V with flash",
                "2.3 to 3.6 V (3.0 V if the chip has in-package flash)"):
        assert grade(ans, facts)["pass"], ans
    assert not grade("1.8-3.3 V", facts)["pass"]


def test_slash_list_with_trailing_unit_satisfies_every_quantity_fact():
    facts = [{"attribute": f"pll_{v}", "value": v, "unit": "MHz"} for v in (80, 160, 240)]
    assert grade("From the PLL the CPU runs at 80/160/240 MHz.", facts)["pass"]
    assert not grade("From the PLL the CPU runs at 40/80/120 MHz.", facts)["pass"]
