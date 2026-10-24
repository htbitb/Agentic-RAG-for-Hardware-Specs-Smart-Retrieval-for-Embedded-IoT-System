"""D22: `pytest agent/tests` không bao giờ gọi LLM/mạng thật.

Sự cố P1: `config._load_dotenv` ghi đè biến môi trường rỗng bằng giá trị trong `.env`, nên test dùng SimulatedLLM đã gọi Gemini thật.
Cơ chế: `AGENT_DOTENV=0` tắt nạp `.env` (conftest đặt trước khi import config) + chốt chặn socket cho mọi test.
Hành vi khi chạy thật (không đặt AGENT_DOTENV) giữ nguyên.
"""
import os
import socket

import pytest

import config


def _write_env(tmp_path, body):
    (tmp_path / ".env").write_text(body, encoding="utf-8")
    return tmp_path


def test_agent_dotenv_zero_disables_loading_the_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", _write_env(tmp_path, "P2_SENTINEL_KEY=leaked\n"))
    monkeypatch.delenv("P2_SENTINEL_KEY", raising=False)
    monkeypatch.setenv("AGENT_DOTENV", "0")
    config._load_dotenv()
    assert "P2_SENTINEL_KEY" not in os.environ


def test_agent_dotenv_zero_does_not_override_an_empty_variable(tmp_path, monkeypatch):
    # đúng kịch bản sự cố: biến được đặt RỖNG để tắt LLM, .env chứa giá trị thật
    monkeypatch.setattr(config, "ROOT", _write_env(tmp_path, "P2_SENTINEL_KEY=leaked\n"))
    monkeypatch.setenv("P2_SENTINEL_KEY", "")
    monkeypatch.setenv("AGENT_DOTENV", "0")
    config._load_dotenv()
    assert os.environ["P2_SENTINEL_KEY"] == ""


def test_dotenv_is_still_loaded_when_the_switch_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", _write_env(tmp_path, "P2_SENTINEL_KEY=from_file\n"))
    monkeypatch.delenv("P2_SENTINEL_KEY", raising=False)
    monkeypatch.delenv("AGENT_DOTENV", raising=False)
    try:
        config._load_dotenv()
        assert os.environ.get("P2_SENTINEL_KEY") == "from_file"
    finally:
        os.environ.pop("P2_SENTINEL_KEY", None)


@pytest.mark.parametrize("value", ["1", "", "true"])
def test_only_the_value_zero_turns_loading_off(tmp_path, monkeypatch, value):
    monkeypatch.setattr(config, "ROOT", _write_env(tmp_path, "P2_SENTINEL_KEY=from_file\n"))
    monkeypatch.delenv("P2_SENTINEL_KEY", raising=False)
    monkeypatch.setenv("AGENT_DOTENV", value)
    try:
        config._load_dotenv()
        assert os.environ.get("P2_SENTINEL_KEY") == "from_file"
    finally:
        os.environ.pop("P2_SENTINEL_KEY", None)


def test_the_test_session_runs_with_dotenv_off_and_no_llm_key():
    assert os.environ.get("AGENT_DOTENV") == "0"
    assert config.LLM_API_KEY == ""            # => agent.llm.make_llm() không bao giờ tạo OpenAICompatLLM trong test


def test_non_loopback_connections_are_blocked():
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="network access is blocked"):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()


def test_loopback_is_still_allowed_for_local_servers():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        cli = socket.create_connection(srv.getsockname(), timeout=2)
        cli.close()
    finally:
        srv.close()
