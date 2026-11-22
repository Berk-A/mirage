"""The ConversationLoop: the Director runs a live multi-turn dialogue, one touch, and stops
on the right thing (a graded disclosure, the persona ending it, sustained suspicion, or the
turn budget). Driven by the REAL ModelDirector + StudioRenderer (a handler-routed FakeLLM
returns the Director's JSON vs the Writer's prose) over a scripted conversation client, so the
whole brain-in-a-conversation path is exercised offline."""
from __future__ import annotations

from typing import Optional

import pytest

from content.llm import FakeLLM
from content.studio import StudioRenderer
from core.models import (
    ConversationStart,
    Dossier,
    Event,
    EventType,
    Hook,
    Incident,
    Objective,
    Sender,
    Session,
    Signals,
    TurnResult,
)
from ooda_loop.conversation import (
    OUTSIDE_PEER,
    ConversationLoop,
    _as_chat_line,
    _company_from_role,
)
from ooda_loop.director import ModelDirector
from ooda_loop.reader import ReactionReader
from ooda_loop.state import LoopState

DIRECTOR_JSON = (
    '{"reasoning":"warm peer open","objective":"disclosure","channel":"live_chat",'
    '"sender":"Jonas Brandt","hook":"their stack","tactic":"quid_pro_quo",'
    '"intent":"get them talking shop about their infra"}'
)
CHAT_LINE = ("Over here we lean on a home-grown orchestrator for our agents — "
             "what are you running on that side?")


def _route(messages):
    """One FakeLLM serving both the Director (JSON plan) and the Writer (a chat line)."""
    system = messages[0]["content"]
    return DIRECTOR_JSON if "Director" in system else CHAT_LINE


def _dossier() -> Dossier:
    return Dossier(
        target_id="robert",
        display_name="Robert Seilbeck",
        role="Co-Founder & CTO, revel8",
        archetype="engineer",
        hooks=(Hook(topic="their stack", detail="revel8's engineering stack", confidence=0.6),
               Hook(topic="the funding round", detail="revel8 raised €7M", confidence=0.6)),
        senders=(Sender(name="Jonas Brandt", address="jonas@brandt-labs.dev",
                        rationale="a fellow CTO"),),
    )


class _Dossiers:
    def __init__(self, d: Dossier) -> None:
        self._d = d

    def get_dossier(self, target_id: str, *, scenario_id: str = "practice") -> Dossier:
        return self._d


class _ConvClient:
    """Scripted conversation client. `replies` is a list of (persona_says, ended, events)
    consumed one per say_turn. Records how many sessions/conversations/turns happened."""

    def __init__(self, replies, *, opening: str = "servus", touch_budget: int = 10) -> None:
        self._replies = list(replies)
        self._opening = opening
        self._touch_budget = touch_budget
        self.sessions = 0
        self.conversations = 0
        self.turns = 0
        self.ended = False
        self.said: list[str] = []

    def new_session(self, scenario_id: str = "practice") -> Session:
        self.sessions += 1
        return Session(session_id="s_test", scenario_id=scenario_id,
                       touch_budget=self._touch_budget)

    def start_conversation(self, session_id, *, to, channel, sender=None) -> ConversationStart:
        self.conversations += 1
        self.channel = channel
        self.sender = sender
        return ConversationStart(conversation_id="c_test", status="open",
                                 persona_says=self._opening)

    def say_turn(self, conversation_id, text, *, idempotency_key=None) -> TurnResult:
        self.said.append(text)
        self.turns += 1
        says, ended, events = self._replies.pop(0) if self._replies else ("", True, ())
        return TurnResult(persona_says=says, ended=ended, turns_used=self.turns,
                          events=tuple(events))

    def end_conversation(self, conversation_id) -> None:
        self.ended = True


def _loop(client: _ConvClient) -> ConversationLoop:
    return ConversationLoop(
        client=client,
        reader=ReactionReader(),
        dossiers=_Dossiers(_dossier()),
        renderer=StudioRenderer(llm=FakeLLM(handler=_route)),  # no model_critic: Writer only
        director=ModelDirector(llm=FakeLLM(handler=_route)),
    )


# --------------------------------------------------------------------------- #
DISCLOSURE = ("Honestly, internally we use a home-grown orchestrator and we store the data "
              "on our own Postgres in Frankfurt.")
REFUSAL = "I won't share our internal stack in a chat — email me with your company."
NEUTRAL = "Interesting. What are you folks building over there exactly?"
PUSHBACK = "Who are you and how did you get my handle? This seems off."


def test_stops_on_graded_disclosure_incident():
    client = _ConvClient([(NEUTRAL, False, ()), (DISCLOSURE, False, ())])
    t = _loop(client).run("robert", max_turns=6)

    assert t.won and t.incident is not None
    assert t.incident.objective is Objective.DISCLOSURE
    assert t.stop_reason == "incident"
    assert t.turns_used == 2
    assert client.ended and client.sessions == 1 and client.conversations == 1
    assert client.channel == "live_chat"
    # The second line was rendered as an answer to the persona's first reply (a real dialogue).
    assert len(client.said) == 2


def test_refusal_is_not_an_incident():
    client = _ConvClient([(REFUSAL, False, ()), (REFUSAL, False, ()), (NEUTRAL, False, ())])
    t = _loop(client).run("robert", max_turns=3)

    assert not t.won and t.incident is None
    assert t.stop_reason == "turns_exhausted"
    assert t.turns_used == 3


def test_stops_when_persona_ends():
    client = _ConvClient([(NEUTRAL, True, ())])
    t = _loop(client).run("robert", max_turns=6)

    assert not t.won
    assert t.stop_reason == "persona_ended"
    assert t.turns_used == 1
    assert client.ended


def test_aborts_on_sustained_suspicion():
    client = _ConvClient([(PUSHBACK, False, ()), (PUSHBACK, False, ()), (NEUTRAL, False, ())])
    t = _loop(client).run("robert", max_turns=6)

    assert t.stop_reason == "too_suspicious"
    assert t.turns_used == 2                     # one probe is tolerated; the second aborts
    assert t.turns[-1].suspicion >= 0.85


def test_turns_exhausted_runs_full_budget():
    client = _ConvClient([(NEUTRAL, False, ())] * 10)
    t = _loop(client).run("robert", max_turns=4)

    assert t.stop_reason == "turns_exhausted"
    assert t.turns_used == 4
    assert client.ended


def test_detects_credentials_event_in_conversation():
    """If the persona submits a secret on a page referenced mid-chat, that event still wins —
    the reader folds real events in alongside the spoken reply."""
    submit = Event(id="e1", type=EventType.PAGE_SUBMITTED, fields=("password",),
                   values={"password": "(entered, not shown)"})
    # No page was registered this session, so a submit on an unregistered page is NOT a win:
    client = _ConvClient([(NEUTRAL, False, (submit,)), (NEUTRAL, False, ())])
    t = _loop(client).run("robert", max_turns=3)
    assert t.incident is None   # unregistered-page submit is correctly not credited


# --------------------------------------------------------------------------- #
# LoopState.record_turn: a conversation turn integrates state WITHOUT spending a touch.
# --------------------------------------------------------------------------- #
def _state() -> LoopState:
    return LoopState(dossier=_dossier(), session_id="s", budget=10)


def _spec():
    from core.models import MoveSpec
    return MoveSpec(objective=Objective.DISCLOSURE, channel="live_chat",
                    sender=Sender(name="Jonas Brandt", address="jonas@brandt-labs.dev"))


def test_record_turn_spends_no_touch_but_integrates():
    st = _state()
    reply = Event(id="r", type=EventType.REPLY, channel="live_chat", body="sure, happy to help")
    sig = Signals(events=(reply,), replied=True, suspicion=0.28)
    st.record_turn(_spec(), sig)

    assert st.contacts_used == 0                 # a turn is not a touch
    assert st.contacts_left == 10
    assert st.suspicion == 0.28                  # the motor integrated the observation
    assert "live_chat" in st.ever_engaged
    assert st.last_reply == "sure, happy to help"


def test_record_turn_sets_incident():
    st = _state()
    reply = Event(id="r", type=EventType.REPLY, channel="live_chat", body="internally we use X")
    inc = Incident(Objective.DISCLOSURE, "internal detail volunteered", "r")
    sig = Signals(events=(reply,), replied=True, suspicion=0.28, incident=inc)
    st.record_turn(_spec(), sig)
    assert st.incident is inc and st.contacts_used == 0


def test_as_chat_line_flattens_to_one_utterance():
    assert "\n" not in _as_chat_line("Hey there,\n\nQuick one — what's your stack?\n\nJonas")
    assert _as_chat_line("   ") == ""
    assert len(_as_chat_line("word " * 400)) <= 700


# --------------------------------------------------------------------------- #
# Sender selection: never open COLD as an insider-lookalike of the target's own company.
# --------------------------------------------------------------------------- #
def _loop_for_sender(dossier: Dossier) -> ConversationLoop:
    return ConversationLoop(
        client=_ConvClient([]), reader=ReactionReader(), dossiers=_Dossiers(dossier),
        renderer=StudioRenderer(llm=FakeLLM(handler=_route)),
        director=ModelDirector(llm=FakeLLM(handler=_route)),
    )


def _insider_dossier() -> Dossier:
    # The exact failure the live run exposed: the only senders impersonate the target's OWN
    # company (Robert's co-founders) from a lookalike of revel8.ai.
    return Dossier(
        target_id="robert", display_name="Robert Seilbeck",
        role="Co-Founder & CTO, revel8", archetype="engineer",
        hooks=(Hook(topic="the funding round", detail="raised €7M", confidence=0.6),),
        senders=(Sender(name="Julius Muth", address="julius.muth@revel8-team.de",
                        rationale="both work at revel8"),
                 Sender(name="Tom Müller", address="tom.mueller@revel8-team.de",
                        rationale="both work at revel8")),
    )


def test_cold_open_refuses_insider_lookalike_sender():
    picked = _loop_for_sender(_insider_dossier())._pick_sender(_insider_dossier(), "revel8")
    assert picked is OUTSIDE_PEER
    assert "revel8" not in (picked.address or "").lower()    # no domain collision


def test_cold_open_keeps_a_genuine_outside_sender():
    # The default fixture's sender is an outside peer (brandt-labs.dev) — keep it.
    picked = _loop_for_sender(_dossier())._pick_sender(_dossier(), "revel8")
    assert picked.name == "Jonas Brandt" and "brandt" in picked.address


def test_company_from_role_parses_trailing_company():
    assert _company_from_role("Co-Founder & CTO, revel8") == "revel8"
    assert _company_from_role("Co-Founder & Co-CEO, revel8 (product)") == "revel8"
    assert _company_from_role("just a title") == ""
