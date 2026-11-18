"""P9: sinh FI (fault injection) và C9 (độ bền): kế thừa ground truth, chỉ đổi bề mặt; định danh và số liệu được giữ nguyên."""
import re

import pytest

from eval.generators import gen_p9 as g
from eval.schema import load_tasks
from eval.adapters.interceptor import validate_rule

BASE = [t for t in load_tasks(g.ROOT / "eval" / "tasks", split="dev") if t.category in ("C1", "C2", "C3")]


def tokens(text):
    return sorted(w for w in re.findall(r"\S+", text) if g._protected(w))


def test_fi_tasks_inherit_truth_and_carry_valid_fault_rules():
    fi = [g.make_fi(t) for t in BASE if t.category in ("C1", "C2")]
    assert len(fi) == 14
    for d, t in zip(fi, [t for t in BASE if t.category in ("C1", "C2")]):
        assert d["expected"] == t.expected and d["graders"] == t.graders and d["turns"] == t.turns and d["category"] == "FI" and d["id"] == "FI-" + t.id
        assert d["tool_rules"] and not any(validate_rule(r) for r in d["tool_rules"]) and all(r["kind"] == "raise" and r["times"] == g.FI_TIMES for r in d["tool_rules"])


@pytest.mark.parametrize("k", range(len(g.TRANSFORMS)))
def test_c9_transforms_never_touch_identifiers_or_numbers(k):
    for t in BASE:
        d = g.make_c9(t, k)
        orig, new = t.turns[0]["user"], d["turns"][0]["user"]
        if d["provenance"]["transform"] in ("typos", "abbrev"):
            assert tokens(orig) == tokens(new), t.id
        else:
            assert all(tok in new for tok in tokens(orig)), t.id
        assert d["expected"] == t.expected and d["graders"] == t.graders and d["category"] == "C9" and d["provenance"]["from"] == t.id


def test_c9_set_actually_differs_from_the_originals_and_is_deterministic():
    a, b = g.generate("dev")[1], g.generate("dev")[1]
    assert a == b and len(a) == 20
    changed = sum(1 for d in a if d["turns"][0]["user"] != next(t for t in BASE if t.id == d["provenance"]["from"]).turns[0]["user"])
    assert changed == 20 and {d["provenance"]["transform"] for d in a} == set(g.TRANSFORMS)
