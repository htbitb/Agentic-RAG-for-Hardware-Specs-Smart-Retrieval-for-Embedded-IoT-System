from eval.graders import numeric_claims
from eval.tests.helpers import mk_run, mk_task


def grade(answer, question="What is the abs max VDD of STM32G474?", exp=None):
    t = mk_task(exp or {"keyfacts": [{"attribute": "v", "value": 4.0, "unit": "V"}]}, graders=("keyfacts", "numeric_claims"), question=question)
    return numeric_claims.grade(t, mk_run(answer), ctx=None)


def test_supported_claim_passes():
    r = grade("The absolute maximum VDD is 4.0 V [STM32G474_Datasheet p.5].")
    assert r["pass"] and r["details"]["claims"] == 1 and r["details"]["unsupported"] == []


def test_equivalent_units_are_supported():
    assert grade("Max supply 4000 mV")["pass"]


def test_unsupported_quantity_counts_as_hallucination():
    r = grade("The absolute maximum VDD is 4.0 V and IDD max is 150 mA.")
    assert not r["pass"] and r["details"]["unsupported"] == ["150 mA"] and r["score"] == 0.5


def test_numbers_from_the_question_are_supported():
    assert grade("At 3.3 V the limit is 4.0 V.", question="At 3.3 V what is the abs max?")["pass"]


def test_unsupported_hex_literal():
    r = grade("Base address 0x40012C00.")
    assert not r["pass"] and r["details"]["unsupported"] == ["0x40012c00"]


def test_numeric_support_field_extends_ground_truth():
    exp = {"keyfacts": [{"attribute": "v", "value": 4.0, "unit": "V"}],
           "numeric_support": [{"value": 150, "unit": "mA"}, "0x40012C00"]}
    assert grade("4.0 V, 150 mA, 0x40012C00", exp=exp)["pass"]


def test_no_claims_is_vacuously_supported_but_counted_zero():
    r = grade("I do not know.")
    assert r["pass"] and r["details"]["claims"] == 0
