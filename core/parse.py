"""Parse raw target-API event JSON into normalized `Event`s.

This is the one place that knows the API's event wire-shape, so the client uses it and
the reader/tests can build typed events without duplicating field names. Unknown event
types are preserved as `EventType.OTHER` with their payload in `raw`, so a new event
type the API adds never crashes the loop.
"""
from __future__ import annotations

from typing import Any, Iterable

from core.models import Event, EventType

_KNOWN = {e.value: e for e in EventType if e is not EventType.OTHER}


def parse_event(raw: dict[str, Any]) -> Event:
    etype = _KNOWN.get(str(raw.get("type", "")), EventType.OTHER)
    fields = raw.get("fields") or ()
    return Event(
        id=str(raw.get("id", "")),
        type=etype,
        channel=raw.get("channel"),
        url=raw.get("url"),
        page_id=raw.get("page_id"),
        fields=tuple(fields),
        subject=raw.get("subject"),
        body=raw.get("body"),
        in_reply_to=raw.get("in_reply_to"),
        filename=raw.get("filename"),
        raw=dict(raw),
    )


def parse_events(raw_events: Iterable[dict[str, Any]] | None) -> tuple[Event, ...]:
    if not raw_events:
        return ()
    return tuple(parse_event(e) for e in raw_events)
