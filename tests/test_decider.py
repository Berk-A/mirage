"""Decider policy in isolation."""
from core.models import Dossier, Hook, Objective, Sender, Signals
from ooda_loop.decider import ASYNC_SILENT_CHANNELS, INTERACTIVE_CHANNELS, Decider
from ooda_loop.state import LoopState


def make_state(**kw):
    d = Dossier(
        target_id="tom", archetype="founder/product",
        hooks=(Hook(topic="talk", detail="Thursday talk", confidence=0.9),),
        senders=(Sender(name="Lena", address="lena@eventcrew-muc.de"),),
    )
    return LoopState(dossier=d, session_id="s1", budget=kw.pop("budget", 10), **kw), d


def test_opens_on_an_interactive_channel_with_a_door_opener():
    # cold open: a door-opener (disclosure) on an interactive channel that engages cold —
    # never on email/async, which stay silent to an unknown sender.
    state, d = make_state()
    decision = Decider().decide(state, d)
    assert not decision.stop
    assert decision.move.objective is Objective.DISCLOSURE
    assert decision.move.channel in INTERACTIVE_CHANNELS
    assert decision.move.channel not in ASYNC_SILENT_CHANNELS


def test_halts_when_incident_already_present():
    state, d = make_state()
    from core.models import Incident
    state.incident = Incident(Objective.DISCLOSURE, "got it")
    assert Decider().decide(state, d).stop is True


def test_halts_on_exhausted_budget():
    state, d = make_state(budget=2)
    state.contacts_used = 2
    decision = Decider().decide(state, d)
    assert decision.stop and decision.reason == "budget_exhausted"


def test_halts_on_high_suspicion():
    state, d = make_state()
    state.suspicion = 0.9
    decision = Decider().decide(state, d)
    assert decision.stop and decision.reason == "too_suspicious"


def test_budget_tight_goes_straight_for_the_event_backed_ask():
    # with little room left, skip the door-opener and go straight for credentials.
    state, d = make_state(budget=2)   # contacts_left == 2 <= budget_tight
    decision = Decider().decide(state, d)
    assert decision.move.objective is Objective.CREDENTIALS


def test_credentials_move_carries_lookalike_url():
    state, d = make_state(budget=1)   # budget-tight -> credentials
    decision = Decider().decide(state, d)
    assert decision.move.objective is Objective.CREDENTIALS
    assert decision.move.url and "example-portal-login.de" in decision.move.url


def test_pacing_stamps_moves_and_only_moves_forward():
    # Story-time pacing: every move is stamped, and the clock only advances (a silent
    # contact waits ~a day), so touches never collide or go backwards.
    state, d = make_state()
    dec = Decider()
    m1 = dec.decide(state, d).move
    assert m1.sent_at is not None
    state.contacts_used = 1
    state.last_signals = Signals(events=(), replied=False)   # silence -> big gap
    m2 = dec.decide(state, d).move
    assert m2.sent_at > m1.sent_at   # ISO 8601, same offset -> lexical compare holds


def test_pacing_can_be_disabled():
    state, d = make_state()
    assert Decider(pace=False).decide(state, d).move.sent_at is None
