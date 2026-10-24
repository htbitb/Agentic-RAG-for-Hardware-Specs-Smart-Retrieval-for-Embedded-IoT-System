"""Nạp cấu hình LLM từ agent/.env + môi trường tiến trình. KHÔNG bao giờ in/ghi giá trị khoá."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / "agent" / ".env"
_SECRET_RX = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,})")


def load_env_file(path) -> dict[str, str]:
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].strip()
        if key:
            out[key] = val
    return out


def redact(text: str, secrets=()) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[REDACTED]")
    return _SECRET_RX.sub("[REDACTED]", text)


@dataclass
class LLMConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    temperature: float
    price_in: float
    price_out: float

    @classmethod
    def load(cls, env_path=DEFAULT_ENV) -> "LLMConfig":
        f = load_env_file(env_path)
        get = lambda k, d="": (os.environ.get(k) or f.get(k) or d).strip()
        key = get("LLM_API_KEY") or get("OPENAI_API_KEY") or get("GEMINI_API_KEY")
        base = get("LLM_BASE_URL") or get("OPENAI_BASE_URL") or \
            ("https://generativelanguage.googleapis.com/v1beta/openai/" if get("GEMINI_API_KEY") else "")
        return cls(api_key=key, base_url=base, model=get("LLM_MODEL", "gemini-3.5-flash-lite"),
                   temperature=float(get("LLM_TEMPERATURE", "0.0") or 0.0),
                   price_in=float(get("PRICE_IN_PER_M", "0.075") or 0.075),
                   price_out=float(get("PRICE_OUT_PER_M", "0.30") or 0.30))

    @property
    def is_gemini(self) -> bool:
        return "generativelanguage.googleapis.com" in (self.base_url or "")

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in / 1e6 * self.price_in + tokens_out / 1e6 * self.price_out

    def public_dict(self) -> dict:
        return {"base_url": self.base_url, "model": self.model, "temperature": self.temperature,
                "price_in_per_m": self.price_in, "price_out_per_m": self.price_out, "api_key_set": bool(self.api_key)}

    def subprocess_env(self) -> dict[str, str]:
        """Biến môi trường cho tiến trình con (S1/S2). Chứa khoá -> chỉ dùng để truyền, không bao giờ in."""
        return {"LLM_API_KEY": self.api_key, "LLM_BASE_URL": self.base_url, "LLM_MODEL": self.model,
                "LLM_TEMPERATURE": str(self.temperature), "PRICE_IN_PER_M": str(self.price_in),
                "PRICE_OUT_PER_M": str(self.price_out)}
