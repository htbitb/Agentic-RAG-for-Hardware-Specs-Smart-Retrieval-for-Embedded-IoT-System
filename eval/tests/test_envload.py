from eval.envload import LLMConfig, load_env_file, redact


def test_load_env_file_parses_quotes_comments_export(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nLLM_MODEL=m1\nexport LLM_BASE_URL='https://x/y/'\nLLM_TEMPERATURE=0.0 # trailing\n\nBAD LINE\nEMPTY=\n")
    d = load_env_file(f)
    assert d == {"LLM_MODEL": "m1", "LLM_BASE_URL": "https://x/y/", "LLM_TEMPERATURE": "0.0", "EMPTY": ""}


def test_missing_env_file_is_empty(tmp_path):
    assert load_env_file(tmp_path / "nope") == {}


def test_llm_config_prefers_process_env_over_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("LLM_API_KEY=filekey-123456\nLLM_MODEL=file-model\nPRICE_IN_PER_M=0.5\nPRICE_OUT_PER_M=1.5\n")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    cfg = LLMConfig.load(f)
    assert cfg.model == "env-model" and cfg.api_key == "filekey-123456"
    assert (cfg.price_in, cfg.price_out, cfg.temperature) == (0.5, 1.5, 0.0)
    assert cfg.is_gemini is False


def test_config_repr_and_dict_never_expose_the_key(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("LLM_API_KEY=SuperSecretValue123\nLLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/\n")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    cfg = LLMConfig.load(f)
    assert "SuperSecretValue123" not in repr(cfg) and "SuperSecretValue123" not in str(cfg.public_dict())
    assert cfg.is_gemini is True
    assert cfg.subprocess_env()["LLM_API_KEY"] == "SuperSecretValue123"      # chỉ truyền cho tiến trình con, không in


def test_redact_removes_real_secret_and_key_like_strings():
    text = "key=SuperSecretValue123 and sk-abcdefghijkl"
    out = redact(text, secrets=["SuperSecretValue123"])
    assert "SuperSecretValue123" not in out and "sk-abc" not in out and "[REDACTED]" in out
