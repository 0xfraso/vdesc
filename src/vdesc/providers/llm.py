"""Generic OpenAI-compatible chat client.

One client covers any provider that speaks the OpenAI Chat Completions
protocol (z.ai, OpenAI, OpenRouter, vLLM, ...) — only base_url, model and the
API key change. Transient errors (429/5xx/timeouts/connection) are retried
with exponential backoff, honoring Retry-After when present.

Every successful call is reported through `usage_cb(label, model, usage,
elapsed_s)` so the CLI's usage ledger captures all spend in one place.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from ..util import retry_sleep


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResult:
    text: str
    usage: Usage | None
    model: str


UsageCB = Callable[[str, str, "Usage | None", float], None]


class ChatClient:
    def __init__(self, *, base_url: str, model: str, api_key: str,
                 timeout: float = 1800.0, max_attempts: int = 6,
                 label: str = "chat", usage_cb: UsageCB | None = None):
        self.model = model
        self.label = label
        self.max_attempts = max_attempts
        self._usage_cb = usage_cb
        self._client = OpenAI(base_url=base_url, api_key=api_key,
                              timeout=timeout, max_retries=0)

    def complete(self, *, system: str | None = None, user, max_attempts: int | None = None
                 ) -> ChatResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return self._send(messages, max_attempts or self.max_attempts)

    def _send(self, messages: list[dict], max_attempts: int) -> ChatResult:
        delay = 5.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            t0 = time.time()
            try:
                resp = self._client.chat.completions.create(model=self.model, messages=messages)
                usage = getattr(resp, "usage", None)
                u = Usage(usage.prompt_tokens or 0, usage.completion_tokens or 0,
                          usage.total_tokens or 0) if usage else None
                model = getattr(resp, "model", self.model) or self.model
                if self._usage_cb:
                    self._usage_cb(self.label, model, u, time.time() - t0)
                text = (resp.choices[0].message.content or "").strip()
                return ChatResult(text=text, usage=u, model=model)
            except RateLimitError as exc:
                last_exc = exc
                wait = retry_sleep(exc)
                if wait is not None:
                    time.sleep(min(wait, 120.0))
                    continue
            except (APITimeoutError, APIConnectionError) as exc:
                last_exc = exc
            except APIStatusError as exc:
                status = getattr(exc, "status_code", 0) or 0
                if status != 429 and status < 500:
                    raise  # permanent (auth, bad request, unknown model...) — do not retry
                last_exc = exc
            if attempt < max_attempts:
                time.sleep(delay)
                delay = min(delay * 2, 90.0)
        raise RuntimeError(
            f"chat call failed after {max_attempts} attempts: {last_exc}") from last_exc
