"""functional_sim (P5): `hse_hz` khai báo trên mục spec clock được dùng cho mô phỏng như `expected.hse_hz` (task C5 có code dùng HSE)."""
import copy
from pathlib import Path

import yaml

from eval.context import GradeContext
from eval.graders import functional_sim
from eval.schema import Task
from eval.tests.helpers import mk_run

FIX = Path(__file__).parent / "fixtures" / "c5" / "c5_tiny.yaml"
CTX = GradeContext(manifest=[])


def c5_901(**spec_patch):
    d = copy.deepcopy(yaml.safe_load(FIX.read_text(encoding="utf-8"))[0])
    d["expected"]["spec"][0].update(spec_patch)
    d["expected"]["spec"][0] = {k: v for k, v in d["expected"]["spec"][0].items() if v is not None}
    return Task.from_dict(d)


def test_the_hse_frequency_of_the_clock_spec_drives_the_simulation():
    t = c5_901()
    ref = t.provenance["reference_solution"]["answer"]
    res = functional_sim.grade(t, mk_run(ref), CTX)
    assert res["pass"] is True, res["reasons"]
    assert res["details"]["clocks"]["sysclk_hz"] == 170000000


def test_without_any_hse_hz_the_same_code_cannot_be_graded():
    t = c5_901(hse_hz=None)
    res = functional_sim.grade(t, mk_run(t.provenance["reference_solution"]["answer"]), CTX)
    assert res["pass"] is False and any("SIM-CLK-UNKNOWN" in r for r in res["reasons"])


def test_a_different_crystal_gives_a_different_sysclk_and_fails():
    t = c5_901(hse_hz=16000000)
    res = functional_sim.grade(t, mk_run(t.provenance["reference_solution"]["answer"]), CTX)
    assert res["pass"] is False and any(r.startswith(("wrong_clock", "sim_violation")) for r in res["reasons"])


def test_expected_level_hse_hz_still_works_for_old_tasks():
    t = c5_901(hse_hz=None)
    t.expected["hse_hz"] = 8000000
    assert functional_sim.grade(t, mk_run(t.provenance["reference_solution"]["answer"]), CTX)["pass"] is True
