import pytest

from eval.context import GradeContext
from eval.schema import Task
from eval.tools.verify_tasks import verify_task

MANIFEST = [{"doc_id": "D", "kind": "pdf", "aliases": [], "file": "pdfs/d.pdf", "pages": 2, "page_offset": 0}]
PAGES = {"D": ["Table 14. Voltage   characteristics  VDD - VSS  -0.3  4.0 V", "Wait states: 4 WS (5 CPU cycles) <= 170 MHz"]}
CTX = GradeContext(manifest=MANIFEST, pages=PAGES)


def task(expected, evidence, category="C2", graders=("keyfacts",)):
    return Task(id="C2-001", category=category, split="dev", turns=[{"user": "q"}], graders=list(graders), expected=expected,
                provenance={"evidence": evidence})


def test_snippet_present_ignoring_whitespace_and_case():
    t = task({"keyfacts": [{"attribute": "v", "value": 4.0, "unit": "V"}]},
             [{"doc_id": "D", "page": 1, "contains": ["table 14. voltage characteristics", "-0.3 4.0 V"]}])
    assert verify_task(t, CTX) == []


def test_missing_snippet_is_reported():
    t = task({"keyfacts": [{"attribute": "v", "value": 4.0, "unit": "V"}]},
             [{"doc_id": "D", "page": 1, "contains": ["absolute maximum 9.9 V"]}])
    assert any("snippet not found" in p for p in verify_task(t, CTX))


def test_task_without_evidence_is_rejected():
    t = Task(id="C2-002", category="C2", split="dev", turns=[{"user": "q"}], graders=["keyfacts"],
             expected={"keyfacts": [{"attribute": "a", "value": "x"}]})
    assert any("no evidence" in p for p in verify_task(t, CTX))


def test_unknown_doc_and_page_out_of_range():
    t = task({"keyfacts": [{"attribute": "a", "value": "x"}]},
             [{"doc_id": "Nope", "page": 1, "contains": ["x"]}, {"doc_id": "D", "page": 9, "contains": ["x"]}])
    probs = verify_task(t, CTX)
    assert any("unknown doc" in p for p in probs) and any("out of range" in p for p in probs)


def test_numeric_keyfact_must_appear_on_an_evidence_page():
    ok = task({"keyfacts": [{"attribute": "ws", "value": 170, "unit": "MHz"}]}, [{"doc_id": "D", "page": 2, "contains": ["4 WS"]}])
    bad = task({"keyfacts": [{"attribute": "ws", "value": 150, "unit": "MHz"}]}, [{"doc_id": "D", "page": 2, "contains": ["4 WS"]}])
    assert verify_task(ok, CTX) == []
    assert any("keyfact" in p and "not on any evidence page" in p for p in verify_task(bad, CTX))


def test_text_keyfacts_are_not_auto_checked_unless_literal():
    t = task({"keyfacts": [{"attribute": "af", "value": "AF7"}]}, [{"doc_id": "D", "page": 1, "contains": ["-0.3 4.0 V"]}])
    assert verify_task(t, CTX) == []
    t2 = task({"keyfacts": [{"attribute": "af", "value": "AF7", "literal": True}]}, [{"doc_id": "D", "page": 1, "contains": ["-0.3"]}])
    assert any("keyfact" in p for p in verify_task(t2, CTX))


def test_derived_numeric_keyfact_is_exempt_from_page_check():
    t = task({"keyfacts": [{"attribute": "diff", "value": 70, "unit": "MHz", "derived": True}]},
             [{"doc_id": "D", "page": 2, "contains": ["4 WS"]}])
    assert verify_task(t, CTX) == []
