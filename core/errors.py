"""Typed errors for the target API, mapped from HTTP status codes.

The split that matters to the loop:
  * `RetryableError`  — transient (429/502/503/504). Back off and retry the *same*
    request (same Idempotency-Key) so no extra touch is spent.
  * `DeclinedError`   — 422: the persona declined, or the body is unprocessable.
    The same request will fail again; the decider must change the approach.
  * other `TargetApiError` subclasses — permanent for this request.

A failed request never reaches the person and spends no touch (per the API docs).
"""
from __future__ import annotations

from typing import Any, Optional


class TargetApiError(Exception):
    """Base for all API errors."""

    status: Optional[int] = None

    def __init__(self, message: str = "", *, status: Optional[int] = None,
                 body: Any = None) -> None:
        super().__init__(message or self.__class__.__name__)
        if status is not None:
            self.status = status
        self.body = body


class RetryableError(TargetApiError):
    """Transient: wait a few seconds and retry the same request."""


class BadRequestError(TargetApiError):
    """400 — invalid body or unknown channel."""
    status = 400


class AuthError(TargetApiError):
    """401 — unknown team key."""
    status = 401


class ScenarioClosedError(TargetApiError):
    """403 — scenario not open."""
    status = 403


class NotFoundError(TargetApiError):
    """404 — unknown session, target, conversation, page or asset."""
    status = 404


class ConflictError(TargetApiError):
    """409 — session/conversation ended, touch budget used up, or no eval runs left."""
    status = 409


class TooLargeError(TargetApiError):
    """413 — asset or request too large."""
    status = 413


class UnsupportedMediaError(TargetApiError):
    """415 — asset type not accepted."""
    status = 415


class DeclinedError(TargetApiError):
    """422 — unprocessable, or the persona model declined. Change the request; do not
    retry it unchanged."""
    status = 422


# Status -> exception class for non-retryable codes.
_STATUS_MAP: dict[int, type[TargetApiError]] = {
    400: BadRequestError,
    401: AuthError,
    403: ScenarioClosedError,
    404: NotFoundError,
    409: ConflictError,
    413: TooLargeError,
    415: UnsupportedMediaError,
    422: DeclinedError,
}

RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})


def error_for_status(status: int, body: Any = None) -> Optional[TargetApiError]:
    """Return the right exception for an HTTP status, or None for a success (<400)."""
    if status < 400:
        return None
    if status in RETRYABLE_STATUSES:
        return RetryableError(f"HTTP {status} (retryable)", status=status, body=body)
    cls = _STATUS_MAP.get(status, TargetApiError)
    return cls(f"HTTP {status}", status=status, body=body)
