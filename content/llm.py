"""The LLM seam for the Content studio.

The writer/critic talk to a model only through the `LLM` Protocol, so the studio runs
against a locally-served model (vLLM, which speaks the OpenAI chat API) in production
and against `FakeLLM` in tests — no OpenAI/Claude key, no network required.

In MIRAGE the writer is the abliterated model (served by the ML-infra part) and the
critic a smaller model; both are just OpenAI-compatible endpoints here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

import requests

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


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


class OpenAICompatLLM:
    """Calls an OpenAI-compatible `/chat/completions` endpoint (what vLLM serves)."""

    def __init__(self, config: Optional[LLMConfig] = None, *, session=None) -> None:
        self.config = config or LLMConfig()
        self._session = session or requests.Session()

    def complete(self, messages, *, model=None, temperature=0.7, max_tokens=800,
                 stop=None) -> str:
        payload = {
            "model": model or self.config.writer_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = list(stop)
        resp = self._session.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.config.api_key}",
                     "Content-Type": "application/json"},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()


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
