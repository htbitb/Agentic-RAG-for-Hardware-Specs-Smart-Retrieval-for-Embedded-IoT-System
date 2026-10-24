"""build_runtime: cấu hình qua tham số/env (không sửa code khi chạy), LLM thật bắt buộc, system prompt v3 sạch (D05), cờ ablation nối với Gate."""
import re

import pytest

from agent.llm import LLMResponse
from agent.runtime.factory import PROMPT_PATH, build_runtime, load_system_prompt
from agent.scripted import ScriptedPolicy, say


class FakeReal:
    """LLM 'thật' giả lập cho test factory: simulated = False, không gọi mạng."""
    simulated = False
    name = "fake-real"

    def chat(self, messages, tools, seed=None):
        return LLMResponse("ok", [], {"in": 10, "out": 1})


def test_the_system_prompt_is_loaded_from_the_v3_file():
    assert PROMPT_PATH.name == "system_v3.md" and load_system_prompt().startswith("You are HW-Design Agent")


def test_the_system_prompt_states_the_agents_obligations_without_benchmark_specifics():
    """Brief P4 bước 4 + D05: ghi requirement trước, mô phỏng trước, không trích dẫn trong code, nêu xung đột; KHÔNG tên task / giá trị cụ thể của benchmark."""
    p = load_system_prompt()
    low = p.lower()
    assert "set_requirements" in p and "simulate" in low and "never put citations inside code" in low and "conflict" in low and "update_plan" in p and "finish" in p
    assert "cmsis" in low
    forbidden = [r"\bC[0-9]-\d{3}\b", r"\bPA\d+\b", r"\bBME280\b", r"\bI2C[0-9]\b", r"\bTIM[0-9]+\b", r"\bUSART[0-9]\b", r"\b\d+\s*kHz\b", r"\b170\s*MHz\b", r"\bPSC\b", r"\bMOE\b"]
    hits = [rx for rx in forbidden if re.search(rx, p)]
    assert not hits, hits
    assert len(p) < 6000


def test_build_runtime_refuses_a_scripted_policy_by_default(tmp_path):
    with pytest.raises(ValueError, match="simulated"):
        build_runtime(llm=ScriptedPolicy([say("x")]), checkpoint_db=tmp_path / "ck.sqlite")


def test_without_an_api_key_there_is_no_silent_fallback_to_a_simulated_llm(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        build_runtime(checkpoint_db=tmp_path / "ck.sqlite")


def test_ablations_come_from_the_argument_or_from_the_environment(tmp_path, monkeypatch):
    rt = build_runtime(llm=FakeReal(), checkpoint_db=tmp_path / "a.sqlite", ablations="A1,A3")
    try:
        assert rt.ablations.codes() == ("A1", "A3") and "hw-sandbox" not in {rt.hub.owner[n] for n in rt.hub.owner}
    finally:
        rt.close()
    monkeypatch.setenv("AGENT_ABLATIONS", "A4")
    rt = build_runtime(llm=FakeReal(), checkpoint_db=tmp_path / "b.sqlite")
    try:
        assert rt.ablations.codes() == ("A4",) and rt.max_repairs == 0
    finally:
        rt.close()


def test_budgets_and_paths_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BUDGETS", '{"steps": 7, "wall_s": 30}')
    monkeypatch.setenv("AGENT_CHECKPOINT_DB", str(tmp_path / "env.sqlite"))
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path / "trace"))
    rt = build_runtime(llm=FakeReal())
    try:
        assert rt.budgets.steps == 7 and rt.budgets.wall_s == 30 and rt.budgets.tokens == 1_500_000
        assert rt.store.path == tmp_path / "env.sqlite" and str(rt.trace_dir) == str(tmp_path / "trace")
        out = rt.ask("What is the address of TIM1_CR1?", session_id="factory-1")
        assert out["status"] == "answered" and (tmp_path / "trace" / f"{out['run_id']}.jsonl").is_file()
    finally:
        rt.close()


def test_the_gate_is_built_with_the_ablation_flags_and_calls_tools_through_the_hub(tmp_path):
    rt = build_runtime(llm=FakeReal(), checkpoint_db=tmp_path / "ck.sqlite", ablations="A3")
    try:
        assert rt.gate.flags.strict_v1_provenance is True and rt.gate.flags.g2 is False
        res = rt.gate.call("list_chips", {})
        assert "stm32g474" in str(res)
    finally:
        rt.close()


def test_gate_tool_calls_are_traced_as_internal(tmp_path):
    rt = build_runtime(llm=FakeReal(), checkpoint_db=tmp_path / "ck.sqlite")
    try:
        out = rt.ask("What is the address of TIM1_CR1?", session_id="factory-2")
        internal = [e for e in out["events"] if e["type"] == "tool_call" and e["internal"]]
        assert out["usage"]["tool_calls"] == 0 and rt.hub.stats["agent_calls"] == 0
        assert all(e["tool"] in ("get_board_state", "get_electrical_specs", "run_drc", "analyze_c_code", "simulate_register_writes", "compile_check") for e in internal)
    finally:
        rt.close()
