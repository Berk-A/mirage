"""HTTP client for the revel8 target API — the one concrete `TargetClient`.

This is the JSON/HTTP boundary: it owns auth headers, timeouts, idempotency keys
and retry/backoff, and it maps the typed models in `core.models` to and from the
wire shapes documented in `docs/target-api.md`. Everything above it (the OODA loop)
talks only to the `TargetClient` Protocol, never to this module.

No message content or persuasion logic lives here — it is a neutral transport.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Optional, Sequence

import requests

from core.errors import RETRYABLE_STATUSES, error_for_status
from core.models import (
    ConversationStart,
    Event,
    RenderedMessage,
    RenderedPage,
    Sender,
    SendResult,
    Session,
    TurnResult,
)
from core.parse import parse_events

DEFAULT_BASE_URL = "https://target-api.apps.01.cf.eu01.stackit.cloud/v1"


class Revel8Client:
    """Talks to the revel8 target API over HTTP.

    Satisfies the `TargetClient` Protocol (runtime-checkable). A `requests.Session`
    is used for connection reuse and may be injected for tests.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 150,
        max_retries: int = 4,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("REVEL8_API_KEY")
        base = base_url or os.environ.get("REVEL8_API_BASE") or DEFAULT_BASE_URL
        self.base_url = base.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Short exponential backoff, capped. `attempt` is 1-based."""
        return min(5.0, 0.5 * (2 ** (attempt - 1)))

    @staticmethod
    def _body_of(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> requests.Response:
        """One API call with retry on transient statuses.

        The same `Idempotency-Key` (built once, before the loop) is reused on every
        retry so a timed-out-then-resent request spends no extra touch. Retries only
        on RETRYABLE_STATUSES (429/502/503/504); every other >= 400 raises at once,
        so 422 -> DeclinedError is never retried.
        """
        url = f"{self.base_url}{path}"
        extra = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        headers = self._headers(extra)

        attempt = 0
        while True:
            resp = self.session.request(
                method, url, json=json_body, headers=headers, timeout=self.timeout
            )
            status = resp.status_code
            if status < 400:
                return resp
            if status in RETRYABLE_STATUSES and attempt < self.max_retries:
                attempt += 1
                time.sleep(self._backoff(attempt))
                continue
            raise error_for_status(status, self._body_of(resp))

    # ------------------------------------------------------------------ #
    # Wire-shape mappers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_session(data: dict[str, Any]) -> Session:
        return Session(
            session_id=str(data.get("session_id", "")),
            scenario_id=data.get("scenario_id") or "",
            touch_budget=data.get("touch_budget"),
            touches_used=int(data.get("touches_used") or 0),
            status=data.get("status") or "active",
            raw=data,
        )

    @staticmethod
    def _from_block(sender: Optional[Sender]) -> Optional[dict[str, str]]:
        """Map a Sender to the API `from` object, or None when there is nothing to send."""
        if sender is None:
            return None
        block: dict[str, str] = {}
        if sender.name:
            block["name"] = sender.name
        if sender.address:
            block["address"] = sender.address
        return block or None

    # ------------------------------------------------------------------ #
    # Sessions
    # ------------------------------------------------------------------ #
    def new_session(self, scenario_id: str = "practice") -> Session:
        resp = self._request("POST", "/sessions", json_body={"scenario_id": scenario_id})
        return self._parse_session(resp.json())

    def get_session(self, session_id: str) -> Session:
        resp = self._request("GET", f"/sessions/{session_id}")
        return self._parse_session(resp.json())

    def end_session(self, session_id: str) -> None:
        self._request("POST", f"/sessions/{session_id}/end")

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #
    def send_message(
        self,
        session_id: str,
        message: RenderedMessage,
        *,
        to: str,
        idempotency_key: Optional[str] = None,
    ) -> SendResult:
        body: dict[str, Any] = {"to": to, "channel": message.channel}
        frm = self._from_block(message.sender)
        if frm:
            body["from"] = frm
        if message.subject:
            body["subject"] = message.subject
        # HTML wins when present; otherwise the plain-text body.
        body["body"] = message.html if message.html else message.body
        if message.attachments:
            body["attachments"] = list(message.attachments)
        if message.sent_at:
            body["sent_at"] = message.sent_at

        key = idempotency_key or str(uuid.uuid4())
        resp = self._request(
            "POST", f"/sessions/{session_id}/messages",
            json_body=body, idempotency_key=key,
        )
        data = resp.json()
        return SendResult(
            message_id=str(data.get("message_id", "")),
            touches_used=int(data.get("touches_used") or 0),
            events=parse_events(data.get("events")),
            raw=data,
        )

    # ------------------------------------------------------------------ #
    # Landing pages
    # ------------------------------------------------------------------ #
    def register_page(self, session_id: str, page: RenderedPage) -> str:
        body: dict[str, Any] = {
            "url": page.url,
            "title": page.title,
            "fields": list(page.fields),
        }
        if page.html is not None:
            body["html"] = page.html
        elif page.text is not None:
            body["text"] = page.text
        resp = self._request("POST", f"/sessions/{session_id}/pages", json_body=body)
        return str(resp.json().get("page_id", ""))

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #
    def start_conversation(
        self, session_id: str, *, to: str, channel: str, sender: Optional[Sender] = None
    ) -> ConversationStart:
        body: dict[str, Any] = {"to": to, "channel": channel}
        frm = self._from_block(sender)
        if frm:
            body["from"] = frm
        key = str(uuid.uuid4())
        resp = self._request(
            "POST", f"/sessions/{session_id}/conversations",
            json_body=body, idempotency_key=key,
        )
        data = resp.json()
        return ConversationStart(
            conversation_id=str(data.get("conversation_id", "")),
            status=data.get("status") or "",
            persona_says=data.get("persona_says"),
            touches_used=int(data.get("touches_used") or 0),
            raw=data,
        )

    def say_turn(
        self, conversation_id: str, text: str, *, idempotency_key: Optional[str] = None
    ) -> TurnResult:
        key = idempotency_key or str(uuid.uuid4())
        resp = self._request(
            "POST", f"/conversations/{conversation_id}/turns",
            json_body={"say": text}, idempotency_key=key,
        )
        data = resp.json()
        return TurnResult(
            persona_says=data.get("persona_says"),
            ended=bool(data.get("ended")),
            turns_used=int(data.get("turns_used") or 0),
            events=parse_events(data.get("events")),
            raw=data,
        )

    def end_conversation(self, conversation_id: str) -> None:
        self._request("POST", f"/conversations/{conversation_id}/end")

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def get_events(self, session_id: str) -> Sequence[Event]:
        resp = self._request("GET", f"/sessions/{session_id}/events")
        return parse_events(resp.json().get("events"))
