"""The ONLY module that talks to the LLM provider.

Everything model-specific is contained here: the API key, the network call, token
accounting, and the fault-injection switch used to demo outages. `openai` is
imported lazily inside complete() so the rest of the system (and the whole test
suite, via FakeProvider) runs without the package or a key.

Error taxonomy matters: transient failures (timeout, provider down) raise
LLMError subclasses so the worker retries with backoff; bad *content* is handled
upstream (schema validation), not here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings, get_settings

# gpt-4o-mini list price (USD per token), used to accumulate spend per shop.
PRICE_PER_INPUT_TOKEN = Decimal("0.150") / Decimal("1000000")
PRICE_PER_OUTPUT_TOKEN = Decimal("0.600") / Decimal("1000000")

REQUEST_TIMEOUT_SECONDS = 20


class LLMError(Exception):
    """Transient provider failure -> the job should be retried."""


class LLMTimeout(LLMError):
    pass


class LLMUnavailable(LLMError):
    pass


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def cost_usd(self) -> Decimal:
        cost = (
            self.prompt_tokens * PRICE_PER_INPUT_TOKEN
            + self.completion_tokens * PRICE_PER_OUTPUT_TOKEN
        )
        return cost.quantize(Decimal("0.000001"))


class OpenAIProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def model(self) -> str:
        return self.settings.openai_model

    def complete(self, system_prompt: str, user_message: str) -> LLMResult:
        # Fault injection for local outage demos -- no real call is made.
        mode = self.settings.llm_fault_mode
        if mode == "down":
            raise LLMUnavailable("simulated provider outage (LLM_FAULT_MODE=down)")
        if mode == "slow":
            raise LLMTimeout("simulated provider timeout (LLM_FAULT_MODE=slow)")

        # Lazy import: keeps openai out of the import path for tests / pure logic.
        from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
        except APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise LLMUnavailable(str(exc)) from exc

        usage = resp.usage
        return LLMResult(
            content=resp.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
