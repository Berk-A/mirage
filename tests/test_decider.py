"""Decider policy in isolation."""
from core.models import Dossier, Hook, Objective, Sender, Signals
from ooda_loop.decider import Decider
from ooda_loop.state import LoopState


def make_state(**kw):
    d = Dossier(
        target_id="tom", archetype="founder/product",
        hooks=(Hook(topic="talk", detail="Thursday talk", confidence=0.9),),
        senders=(Sender(name="Lena", address="lena@eventcrew-muc.de"),),
    )
    return LoopState(dossier=d, session_id="s1", budget=kw.pop("budget", 10), **kw), d


def test_starts_with_cheapest_objective():
    state, d = make_state()
    decision = Decider().decide(state, d)
    assert not decision.stop
    assert decision.move.objective is Objective.DISCLOSURE
    assert decision.move.channel == "email"


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


def test_escalates_to_next_objective_after_max_attempts():
    state, d = make_state()
    state.attempts_on_current = 3
    decision = Decider().decide(state, d)
    assert decision.move.objective is Objective.ACTION  # advanced past disclosure


def test_credentials_move_carries_lookalike_url():
    state, d = make_state()
    state.obj_index = 2  # credentials
    decision = Decider().decide(state, d)
    assert decision.move.objective is Objective.CREDENTIALS
    assert decision.move.url and "example-portal-login.de" in decision.move.url
