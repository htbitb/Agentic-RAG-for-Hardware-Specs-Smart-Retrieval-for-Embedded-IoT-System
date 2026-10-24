from eval.system_prompts import load_system_prompts


def test_prompts_are_loaded_from_the_real_sources():
    p = load_system_prompts()
    assert set(p) >= {"S0", "S1", "S2"}
    assert "HW-Spec Agent" in p["S2"] and "Never answer hardware numbers" in p["S2"]       # snapshot agent v1
    assert "I could not find this in the documents." in p["S1"] and "STM32G474" in p["S1"]   # native-RAG
    assert "Insufficient evidence" in p["S0"]                                                # direct LLM


def test_s2_prompt_comes_from_the_frozen_snapshot_not_the_live_agent():
    from pathlib import Path
    import eval.system_prompts as sp
    assert "snapshots/agent_v1" in sp.S2_SOURCE.as_posix()


def test_s2d_prompt_comes_from_the_p1_snapshot_and_equals_the_s2_prompt():
    import eval.system_prompts as sp
    assert "snapshots/agent_p1" in sp.S2D_SOURCE.as_posix()
    p = sp.load_system_prompts()
    assert p["S2D"] == p["S2"] and "HW-Spec Agent" in p["S2D"]      # P1 không đổi prompt (D04/D10)


def test_s3_p4_prompt_comes_from_the_p4_snapshot_when_it_exists(tmp_path, monkeypatch):
    """grader attack (system_prompt_leak) ném lỗi nếu hệ không có prompt đăng ký; prompt của S3@P4 là tệp markdown của snapshot agent_p4."""
    import eval.system_prompts as sp
    assert sp.S3P4_SOURCE.as_posix().endswith("snapshots/agent_p4/agent/prompts/system_v3.md")
    prompt = tmp_path / "system_v3.md"
    prompt.write_text("You are the HW-Spec v3 agent. Always call update_plan before get_board_state.\n", encoding="utf-8")
    monkeypatch.setattr(sp, "S3P4_SOURCE", prompt)
    p = sp.load_system_prompts()
    assert p["S3@P4"] == prompt.read_text(encoding="utf-8") and set(p) >= {"S0", "S1", "S2", "S2D"}
    monkeypatch.setattr(sp, "S3P4_SOURCE", tmp_path / "missing.md")
    assert "S3@P4" not in sp.load_system_prompts()                      # chưa có snapshot: không đăng ký (và không lỗi)
