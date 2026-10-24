"""S0 — Direct LLM: cùng model/endpoint/temperature, không tool, không truy hồi."""
from __future__ import annotations

from eval.adapters.base import AdapterBase, FatalAdapterError
from eval.llm_cache import CacheMiss, FatalLLMError, InfraError, LLMCache, wrap_client
from eval.schema import Task, TurnResult
from eval.system_prompts import S0_PROMPT

# Prompt S0 (ngắn gọn theo brief P0) định nghĩa trong eval/system_prompts.py để chấm điểm không cần client LLM.
SYSTEM_PROMPT = S0_PROMPT


class DirectLLMAdapter(AdapterBase):
    name = "S0"

    def __init__(self, cfg, client=None, cache: LLMCache | None = None):
        super().__init__(cfg)
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url or None, timeout=90, max_retries=0)
        self.cache = cache or LLMCache("unused.sqlite", "off")
        self.client = wrap_client(client, self.cache)
        self.history: list[dict] = []

    def start(self, task: Task, seed: int) -> None:
        super().start(task, seed)
        self.cache.set_seed(seed)
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def send(self, user_msg: str) -> TurnResult:
        kw = {"model": self.cfg.model, "messages": self.history + [{"role": "user", "content": user_msg}],
              "temperature": self.cfg.temperature}
        if not self.cfg.is_gemini:            # Gemini bỏ qua seed (xem agent/agent/llm.py)
            kw["seed"] = self.seed
        try:
            resp = self.client.chat.completions.create(**kw)
        except CacheMiss:
            self.errors.append("infra:cache_miss")
            return self._record(TurnResult(answer="", status="error"))
        except FatalLLMError as exc:
            raise FatalAdapterError(f"S0: {exc}") from exc
        except InfraError as exc:
            self.errors.append(f"infra:{exc}")
            return self._record(TurnResult(answer="", status="error"))
        except Exception as exc:                # lỗi của chính hệ (không phải hạ tầng) -> tính vào TSR
            self.errors.append(f"error:{type(exc).__name__}: {str(exc)[:200]}")
            return self._record(TurnResult(answer="", status="error"))
        answer = (resp.choices[0].message.content or "").strip()
        u = resp.usage
        self.add_usage(u.prompt_tokens if u else 0, u.completion_tokens if u else 0, llm_calls=1)
        self.trace.append({"type": "llm_call", "turn": len(self.turns), "tokens_in": u.prompt_tokens if u else 0,
                           "tokens_out": u.completion_tokens if u else 0})
        self.history += [{"role": "user", "content": user_msg}, {"role": "assistant", "content": answer}]
        return self._record(TurnResult(answer=answer, status="answered"))

    def _record(self, turn: TurnResult) -> TurnResult:
        self.turns.append(turn)
        return turn
