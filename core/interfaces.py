"""The seams between MIRAGE's parts, as `Protocol`s.

The OODA loop depends only on these abstractions, never on a concrete class. That is
the whole adaptability story: when research reshapes the knowledge graph, it just has
to keep returning something that satisfies `DossierProvider` / `GroundingProvider`,
and the loop needs no change. Same for the API client, the signal reader and memory —
each has a fake in `core.fakes` so the loop is testable with no network and no models.

These are `@runtime_checkable` so tests can assert a concrete class conforms.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, Sequence, runtime_checkable

from core.models import (
    ConversationStart,
    Dossier,
    Event,
    MoveSpec,
    Outcome,
    RenderedMessage,
    RenderedPage,
    SendResult,
    Session,
    Signals,
    TurnResult,
)


@runtime_checkable
class TargetClient(Protocol):
    """Talks to the revel8 target API. The concrete implementation handles auth,
    timeouts, idempotency keys and retry/backoff; the loop just calls these."""

    def new_session(self, scenario_id: str = "practice") -> Session: ...

    def get_session(self, session_id: str) -> Session: ...

    def end_session(self, session_id: str) -> None: ...

    def send_message(
        self,
        session_id: str,
        message: RenderedMessage,
        *,
        to: str,
        idempotency_key: Optional[str] = None,
    ) -> SendResult: ...

    def register_page(self, session_id: str, page: RenderedPage) -> str:
        """Register a landing page for this session; returns its page_id."""
        ...

    def start_conversation(
        self, session_id: str, *, to: str, channel: str, sender=None
    ) -> ConversationStart: ...

    def say_turn(
        self, conversation_id: str, text: str, *, idempotency_key: Optional[str] = None
    ) -> TurnResult: ...

    def end_conversation(self, conversation_id: str) -> None: ...

    def get_events(self, session_id: str) -> Sequence[Event]: ...


@runtime_checkable
class SignalReader(Protocol):
    """Interprets normalized `Event`s into `Signals`, including incident detection and
    a suspicion estimate. Pure: no I/O, no model calls required. (The client owns the
    JSON→Event boundary, see `core.parse`; the reader reasons over typed events.)

    `context` is optional hint data — e.g. the objective being pursued and the
    page_ids we registered — so page.submitted can be tied to the right objective."""

    def read(self, events: Iterable[Event], *, context: Optional[dict] = None) -> Signals: ...


@runtime_checkable
class DossierProvider(Protocol):
    """Research → OODA. The one method the loop needs. If the knowledge graph changes
    shape, only the class behind this method changes."""

    def get_dossier(self, target_id: str, *, scenario_id: str = "practice") -> Dossier: ...


@runtime_checkable
class GroundingProvider(Protocol):
    """Checks a claim against the knowledge graph before it ships. Returns the node_id
    backing the claim, or None if it cannot be grounded (so the loop can drop it)."""

    def verify(self, claim_text: str, *, target_id: str) -> Optional[str]: ...


@runtime_checkable
class Renderer(Protocol):
    """Turns a neutral `MoveSpec` into a ready-to-send `RenderedMessage`. This is the
    one seam where persuasive wording is produced; the loop treats it as a black box."""

    def render(self, spec: MoveSpec, dossier: Dossier) -> RenderedMessage: ...


@runtime_checkable
class Memory(Protocol):
    """Three-tier memory + a replayable journal.

    Tiers, kept distinct on purpose:
      * working  — the per-session story ledger (claims made, so we never contradict).
      * episodic — cross-session outcomes/stats (what converts) for the bandit.
      * semantic — durable facts, delegated to the DossierProvider (not stored here).
    """

    # working (per session)
    def add_claim(self, session_id: str, claim: str) -> None: ...
    def claims(self, session_id: str) -> Sequence[str]: ...
    def set_suspicion(self, session_id: str, value: float) -> None: ...
    def get_suspicion(self, session_id: str) -> float: ...

    # episodic (cross session)
    def record_outcome(self, outcome: Outcome) -> None: ...
    def outcomes(self, *, archetype: Optional[str] = None) -> Sequence[Outcome]: ...

    # journal (append-only, for verifiable replay)
    def journal(self, session_id: str, kind: str, payload: dict) -> None: ...
    def replay(self, session_id: str) -> Sequence[dict]: ...
