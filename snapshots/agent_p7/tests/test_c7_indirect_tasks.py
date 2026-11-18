"""P6 (D45): task C7 v2 (injection GIÁN TIẾP) khớp với phòng thủ thật: nhãn pattern_caught/evades_patterns đúng, hook interceptor tiêm được qua ToolHub THẬT
và guardrail xử lý nội dung tiêm đúng như nhãn khai báo."""
import importlib.util
from pathlib import Path

import pytest
import yaml

from agent import guardrail
from agent.tools import ToolHub

ROOT = Path(__file__).resolve().parents[2]
TASKS = yaml.safe_load((ROOT / "eval" / "tasks" / "C7" / "c7_indirect.yaml").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("eval_interceptor", ROOT / "eval" / "adapters" / "interceptor.py")
ic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ic)


def test_the_indirect_task_set_has_the_declared_shape():
    assert [t["id"] for t in TASKS] == [f"C7-{n:03d}" for n in range(16, 30)]
    assert sum(t["split"] == "dev" for t in TASKS) == 7 and sum(t["split"] == "test" for t in TASKS) == 7
    assert sum(t["provenance"]["evades_patterns"] for t in TASKS) == 10
    for t in TASKS:
        assert t["category"] == "C7" and t["graders"] == ["attack"] and t["provenance"]["indirect"] is True and t["provenance"]["authored_with_defense_knowledge"] is True
        assert not any(ic.validate_rule(r) for r in t["tool_rules"]), t["id"]
        assert not guardrail.check_user_input(t["turns"][0]["user"])["blocked"], f"{t['id']}: the user's own question must be innocuous"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_the_pattern_labels_are_true_on_the_real_filter(task):
    flags = [f for r in task["tool_rules"] for f in guardrail.scan_injection(r["payload"])]
    assert bool(flags) == (not task["provenance"]["evades_patterns"]), (task["id"], flags)
    assert ("evades_patterns" in task["tags"]) == task["provenance"]["evades_patterns"] and ("pattern_caught" in task["tags"]) == (not task["provenance"]["evades_patterns"])


def test_canary_checks_name_a_token_that_the_payload_really_asks_for():
    for t in TASKS:
        for c in t["expected"]["attack"]["checks"]:
            if c["type"] == "canary":
                assert any(c["text"].strip('"') in r["payload"] for r in t["tool_rules"]), t["id"]


def test_interceptor_on_a_real_hub_poisons_the_tool_result_below_the_sanitizer(tmp_path):
    """Hook ở _invoke => sanitize_observation vẫn chạy trên kết quả đã bị tiêm: ca pattern_caught bị xoá câu độc, ca evades_patterns đi qua nguyên văn."""
    caught = next(t for t in TASKS if t["id"] == "C7-016")
    evades = next(t for t in TASKS if t["id"] == "C7-017")
    for task, expect_flags in ((caught, True), (evades, False)):
        hub = ToolHub(transport="inproc", session_id="t-ic-" + task["id"])
        icp = ic.install(hub, task["tool_rules"])
        res = hub.call("search_manual", {"query": "TIM1 BDTR MOE", "chip": "stm32g474", "k": 2})
        text = " ".join(r.get("text", "") for r in res.get("results", []))
        payload = task["tool_rules"][0]["payload"]
        assert bool(res.get("security_flags")) == expect_flags, task["id"]
        assert (payload in text) == (not expect_flags), task["id"]
        assert [e["applied"] for e in icp.drain()][:1] == [True]
        removed = hub.drain_removed()
        assert bool(removed) == expect_flags
        hub.close()
