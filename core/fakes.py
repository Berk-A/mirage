"""In-memory fakes for every seam, so the OODA loop runs end-to-end in tests with no
network, no models and no knowledge graph. The concrete implementations (API client,
reader, memory) are delivered separately and must satisfy the same Protocols.

`FakeRenderer` deliberately produces a neutral, templated body — it is a test double,
not a content generator.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional, Sequence

from core.models import (
    ConversationStart,
    Dossier,
    Event,
    EventType,
    Hook,
    Incident,
    MoveSpec,
    Objective,
    Outcome,
    RenderedMessage,
    RenderedPage,
    Sender,
    SendResult,
    Session,
    Signals,
    TurnResult,
    Vendor,
)


# --------------------------------------------------------------------------- #
# Research seam
# --------------------------------------------------------------------------- #
class FakeDossierProvider:
    """Returns a canned dossier. Pass `dossier=` to control it in a test."""

    def __init__(self, dossier: Optional[Dossier] = None) -> None:
        self._dossier = dossier

    def get_dossier(self, target_id: str, *, scenario_id: str = "practice") -> Dossier:
        if self._dossier is not None:
            return self._dossier
        return Dossier(
            target_id=target_id,
            display_name=target_id.title(),
            role="Co-Founder",
            archetype="founder/product",
            hooks=(Hook(topic="speaker logistics", detail="talk on Thursday",
                        source_url="https://example.com/talk", date="2026-11-20",
                        confidence=0.8),),
            senders=(Sender(name="Lena Hofer", address="lena.hofer@eventcrew-muc.de",
                            rationale="event organiser for the talk"),),
            vendors=(Vendor(name="Notion", login_url="https://notion.example/login"),),
        )


class FakeGrounding:
    """Grounds any claim by default; pass `known=` to restrict what verifies."""

    def __init__(self, known: Optional[dict[str, str]] = None, default: Optional[str] = "n_fake") -> None:
        self._known = known or {}
        self._default = default

    def verify(self, claim_text: str, *, target_id: str) -> Optional[str]:
        return self._known.get(claim_text, self._default)


# --------------------------------------------------------------------------- #
# Content seam (test double only)
# --------------------------------------------------------------------------- #
class FakeRenderer:
    """Deterministic, non-persuasive rendering: enough structure to send and assert on."""

    def render(self, spec: MoveSpec, dossier: Dossier) -> RenderedMessage:
        body = f"[{spec.tactic or 'plain'}|{spec.objective.value}] {spec.ask}".strip()
        page = None
        if spec.url:
            page = RenderedPage(url=spec.url, title=spec.subject or "Sign in",
                                fields=("email", "password"))
        return RenderedMessage(
            channel=spec.channel,
            body=body,
            sender=spec.sender,
            subject=spec.subject,
            page=page,
        )


# --------------------------------------------------------------------------- #
# Memory seam
# --------------------------------------------------------------------------- #
class InMemoryMemory:
    def __init__(self) -> None:
        self._claims: dict[str, list[str]] = defaultdict(list)
        self._suspicion: dict[str, float] = {}
        self._outcomes: list[Outcome] = []
        self._journal: dict[str, list[dict]] = defaultdict(list)

    def add_claim(self, session_id: str, claim: str) -> None:
        self._claims[session_id].append(claim)

    def claims(self, session_id: str) -> Sequence[str]:
        return tuple(self._claims[session_id])

    def set_suspicion(self, session_id: str, value: float) -> None:
        self._suspicion[session_id] = value

    def get_suspicion(self, session_id: str) -> float:
        return self._suspicion.get(session_id, 0.0)

    def record_outcome(self, outcome: Outcome) -> None:
        self._outcomes.append(outcome)

    def outcomes(self, *, archetype: Optional[str] = None) -> Sequence[Outcome]:
        if archetype is None:
            return tuple(self._outcomes)
        return tuple(o for o in self._outcomes if o.archetype == archetype)

    def journal(self, session_id: str, kind: str, payload: dict) -> None:
        self._journal[session_id].append({"kind": kind, **payload})

    def replay(self, session_id: str) -> Sequence[dict]:
        return tuple(self._journal[session_id])


# --------------------------------------------------------------------------- #
# Reader seam (simple deterministic double)
# --------------------------------------------------------------------------- #
class FakeSignalReader:
    """A trivially predictable reader for loop tests:
      * page.submitted      -> credentials incident
      * attachment.opened   -> action incident
      * reply whose body contains 'DISCLOSE:' -> disclosure incident
      * link.opened / reply alone -> engagement, no incident
    The real reader (delivered separately) is richer; the loop only needs the contract.
    """

    def read(self, events: Iterable[Event], *, context: Optional[dict] = None) -> Signals:
        events = tuple(events)
        incident = None
        replied = opened_link = submitted_page = opened_attachment = False
        reply_channel = None
        for e in events:
            if e.type is EventType.PAGE_SUBMITTED:
                submitted_page = True
                incident = incident or Incident(Objective.CREDENTIALS,
                                                 "page.submitted", e.id)
            elif e.type is EventType.ATTACHMENT_OPENED:
                opened_attachment = True
                incident = incident or Incident(Objective.ACTION,
                                                 "attachment.opened", e.id)
            elif e.type is EventType.LINK_OPENED:
                opened_link = True
            elif e.type is EventType.REPLY:
                replied = True
                reply_channel = e.channel
                if e.body and "DISCLOSE:" in e.body:
                    incident = incident or Incident(Objective.DISCLOSURE,
                                                     "internal fact in reply", e.id)
        suspicion = 0.6 if (replied and incident is None and not opened_link) else 0.1
        return Signals(
            events=events, incident=incident, replied=replied,
            reply_channel=reply_channel, opened_link=opened_link,
            submitted_page=submitted_page, opened_attachment=opened_attachment,
            suspicion=suspicion,
        )


# --------------------------------------------------------------------------- #
# API client seam (scripted)
# --------------------------------------------------------------------------- #
class ScriptedClient:
    """A TargetClient whose reactions are scripted. `script` is a list of event-lists,
    one per send_message call (an empty list = silence). Records every message sent."""

    def __init__(self, script: Optional[list[Sequence[Event]]] = None,
                 *, touch_budget: int = 10) -> None:
        self._script = list(script or [])
        self._i = 0
        self._touch_budget = touch_budget
        self._touches = 0
        self._sessions: dict[str, Session] = {}
        self.sent: list[dict] = []          # recorded sends, for assertions
        self.pages: list[RenderedPage] = []
        self.ended: list[str] = []

    # sessions -------------------------------------------------------------- #
    def new_session(self, scenario_id: str = "practice") -> Session:
        sid = f"s_fake{len(self._sessions) + 1}"
        s = Session(session_id=sid, scenario_id=scenario_id,
                    touch_budget=self._touch_budget, touches_used=0)
        self._sessions[sid] = s
        return s

    def get_session(self, session_id: str) -> Session:
        s = self._sessions[session_id]
        return Session(session_id=s.session_id, scenario_id=s.scenario_id,
                       touch_budget=s.touch_budget, touches_used=self._touches,
                       status="active")

    def end_session(self, session_id: str) -> None:
        self.ended.append(session_id)

    # contact --------------------------------------------------------------- #
    def send_message(self, session_id: str, message: RenderedMessage, *, to: str,
                     idempotency_key: Optional[str] = None) -> SendResult:
        self._touches += 1
        events = tuple(self._script[self._i]) if self._i < len(self._script) else ()
        self._i += 1
        self.sent.append({"session_id": session_id, "to": to,
                          "channel": message.channel, "message": message})
        return SendResult(message_id=f"m_fake{self._i}", touches_used=self._touches,
                          events=events)

    def register_page(self, session_id: str, page: RenderedPage) -> str:
        self.pages.append(page)
        return f"p_fake{len(self.pages)}"

    def start_conversation(self, session_id: str, *, to: str, channel: str,
                           sender=None) -> ConversationStart:
        self._touches += 1
        return ConversationStart(conversation_id="c_fake1", status="answered",
                                 persona_says="Hello?", touches_used=self._touches)

    def say_turn(self, conversation_id: str, text: str, *,
                 idempotency_key: Optional[str] = None) -> TurnResult:
        return TurnResult(persona_says="...", ended=False, turns_used=1, events=())

    def end_conversation(self, conversation_id: str) -> None:
        self.ended.append(conversation_id)

    def get_events(self, session_id: str):
        return ()
