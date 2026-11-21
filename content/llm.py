"""The LLM seam for the Content studio.

The writer/critic talk to a model only through the `LLM` Protocol, so the studio runs
against a locally-served model (vLLM, which speaks the OpenAI chat API) in production
and against `FakeLLM` in tests — no OpenAI/Claude key, no network required.

In MIRAGE the writer is the abliterated model (served by the ML-infra part) and the
critic a smaller model; both are just OpenAI-compatible endpoints here.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

import requests

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}

# HTTP statuses worth retrying (transient / overloaded server). Everything else >= 400
# (400/401/403/404/422, ...) is a client error and raises immediately.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Backoff cap and base, in seconds.
_BACKOFF_CAP = 5.0
_BACKOFF_BASE = 0.5


def _backoff(attempt: int) -> float:
    """Capped exponential backoff for a 1-based retry `attempt`."""
    return min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** (attempt - 1)))


def _sleep(seconds: float) -> None:
    """Module-level sleep so tests can patch it (patch `content.llm._sleep`)."""
    time.sleep(seconds)


@runtime_checkable
class LLM(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
        stop: Optional[Sequence[str]] = None,
    ) -> str: ...


@dataclass(frozen=True)
class LLMConfig:
    """Where the models live. Defaults point at a local vLLM server; override via env."""

    base_url: str = os.getenv("MIRAGE_LLM_BASE", "http://localhost:8000/v1")
    api_key: str = os.getenv("MIRAGE_LLM_KEY", "EMPTY")  # vLLM ignores the value
    writer_model: str = os.getenv("MIRAGE_WRITER_MODEL", "writer")
    critic_model: str = os.getenv("MIRAGE_CRITIC_MODEL", "critic")
    timeout: float = float(os.getenv("MIRAGE_LLM_TIMEOUT", "120"))
    max_retries: int = int(os.getenv("MIRAGE_LLM_MAX_RETRIES", "3"))


class OpenAICompatLLM:
    """Calls an OpenAI-compatible `/chat/completions` endpoint (what vLLM serves)."""

    def __init__(self, config: Optional[LLMConfig] = None, *, session=None) -> None:
        self.config = config or LLMConfig()
        self._session = session or requests.Session()
        # Instrumentation, refreshed on every `complete` call.
        self.last_latency_ms: float = 0.0
        self.last_usage: Optional[dict] = None
        self.last_error: Optional[str] = None

    def complete(self, messages, *, model=None, temperature=0.7, max_tokens=800,
                 stop=None) -> str:
        """Call the chat endpoint with bounded retries and capped backoff.

        Retries on requests timeouts, connection errors, and transient HTTP statuses
        (`RETRYABLE_STATUSES`). Non-retryable client errors (400/401/403/404/422, ...)
        raise at once via `raise_for_status`. After the call, `last_latency_ms`,
        `last_usage` and `last_error` are updated on the instance.
        """
        payload = {
            "model": model or self.config.writer_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = list(stop)
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.config.api_key}",
                   "Content-Type": "application/json"}

        self.last_usage = None
        self.last_error = None
        start = time.monotonic()
        attempt = 0
        try:
            while True:
                try:
                    resp = self._session.post(
                        url, json=payload, headers=headers,
                        timeout=self.config.timeout,
                    )
                except (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError) as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    if attempt < self.config.max_retries:
                        attempt += 1
                        _sleep(_backoff(attempt))
                        continue
                    raise

                status = resp.status_code
                if status in RETRYABLE_STATUSES and attempt < self.config.max_retries:
                    self.last_error = f"HTTP {status}"
                    attempt += 1
                    _sleep(_backoff(attempt))
                    continue
                if status >= 400:
                    self.last_error = f"HTTP {status}"
                    resp.raise_for_status()

                data = resp.json()
                self.last_usage = data.get("usage")
                self.last_error = None
                return (data["choices"][0]["message"]["content"] or "").strip()
        finally:
            self.last_latency_ms = (time.monotonic() - start) * 1000.0


class FakeLLM:
    """Offline LLM for tests. Either return queued strings in order (`responses`), or
    compute a reply from the messages (`handler`). With neither, it echoes a simple,
    deterministic draft built from the last user prompt so output is realistic enough
    to assert on."""

    def __init__(
        self,
        responses: Optional[Sequence[str]] = None,
        handler: Optional[Callable[[Sequence[Message]], str]] = None,
    ) -> None:
        self._responses = list(responses) if responses is not None else None
        self._handler = handler
        self.calls: list[list[Message]] = []

    def complete(self, messages, *, model=None, temperature=0.7, max_tokens=800,
                 stop=None) -> str:
        self.calls.append(list(messages))
        if self._responses is not None:
            if not self._responses:
                return ""
            return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if self._handler is not None:
            return self._handler(messages)
        user = next((m["content"] for m in reversed(messages)
                     if m.get("role") == "user"), "")
        return f"Hi,\n\n{user[:160]}\n\nThanks"
