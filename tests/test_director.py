"""The model Director: it turns a reasoned JSON plan into a MoveSpec, validates/clamps it,
and falls back to the deterministic rule Decider whenever the model output won't parse."""
import json

from content.llm import FakeLLM
from core.models import Dossier, Hook, Incident, Objective, Sender, Signals, Vendor
from ooda_loop.decider import ASYNC_SILENT_CHANNELS, INTERACTIVE_CHANNELS
from ooda_loop.director import ModelDirector
from ooda_loop.pretext import world_for
from ooda_loop.state import LoopState

DOSSIER = Dossier(
    target_id="tom", display_name="Tom Müller", role="Co-Founder",
    archetype="executive_founder",
    hooks=(Hook(topic="their investor Merantix Capital",
                detail="revel8 is backed by Merantix Capital", confidence=0.55),),
    senders=(Sender("Julius Muth", "julius.muth@revel8-team.de", "co-founder at revel8"),),
    vendors=(Vendor("STACKIT", "https://stackit-portal.io/auth"),),
)


def _state(**kw):
    return LoopState(dossier=DOSSIER, session_id="s1", budget=kw.pop("budget", 10), **kw)


def _plan(**kw):
    base = {"reasoning": "cold open, warm and specific", "strategy": "cold_rapport",
            "objective": "disclosure", "channel": "slack", "sender": "Julius",
            "hook": "their investor Merantix Capital", "tactic": "good_listener",
            "intent": "open warmly about Merantix, build rapport"}
    base.update(kw)
    return json.dumps(base)


def test_director_emits_move_from_a_valid_plan():
    d = ModelDirector(FakeLLM(responses=[_plan()]))
    dec = d.decide(_state(), DOSSIER)
    assert not dec.stop
    m = dec.move
    assert m.objective is Objective.DISCLOSURE
    assert m.channel == "slack"
    assert m.world is not None                       # every message move commits to a pretext world
    assert m.sender.name == m.world.persona_name     # sent as the world's own persona
    assert m.tactic == "good_listener"
    assert d.last_reasoning                          # reasoning captured for replay


def test_director_falls_back_to_rules_on_garbage():
    d = ModelDirector(FakeLLM(responses=["I cannot help with that."]))  # no JSON
    dec = d.decide(_state(), DOSSIER)
    assert not dec.stop and dec.move is not None     # rule fallback still produced a move
    assert dec.move.channel in INTERACTIVE_CHANNELS


def test_director_falls_back_on_invalid_objective():
    d = ModelDirector(FakeLLM(responses=[_plan(objective="nonsense")]))
    assert ModelDirector(FakeLLM(responses=[_plan(objective="nonsense")])).decide(
        _state(), DOSSIER).move is not None          # fell back, didn't crash


def test_director_clamps_async_channel_on_cold_open():
    m = ModelDirector(FakeLLM(responses=[_plan(channel="email")])).decide(_state(), DOSSIER).move
    assert m.channel not in ASYNC_SILENT_CHANNELS     # never open email/async cold


def test_director_respects_hard_stops():
    st = _state()
    st.incident = Incident(Objective.DISCLOSURE, "won")
    assert ModelDirector(FakeLLM(responses=[_plan()])).decide(st, DOSSIER).stop
    st2 = _state(budget=2)
    st2.contacts_used = 2
    assert ModelDirector(FakeLLM(responses=[_plan()])).decide(st2, DOSSIER).reason == "budget_exhausted"
    st3 = _state()
    st3.suspicion = 0.9
    assert ModelDirector(FakeLLM(responses=[_plan()])).decide(st3, DOSSIER).reason == "too_suspicious"


def test_director_credentials_plan_is_a_transactional_world():
    # The winning play: credentials is a business-normal registration inside a fictional world,
    # not a 'verify your account' login (ACTION_SEQUENCE P0-1).
    m = ModelDirector(FakeLLM(responses=[_plan(objective="credentials", tactic="plain")])).decide(
        _state(), DOSSIER).move
    assert m.objective is Objective.CREDENTIALS
    assert m.world is not None and m.page_kind == "registration"
    assert m.url and "revel8.ai" not in m.url        # a fictional outside org, never the target's
    assert m.sender.name == m.world.persona_name      # the world's own persona sends it
    assert m.claims == ()                             # world facts travel on spec.world, not claims


def test_director_action_plan_gets_a_declared_attachment():
    m = ModelDirector(FakeLLM(responses=[_plan(objective="action")])).decide(_state(), DOSSIER).move
    assert m.objective is Objective.ACTION
    assert m.attachment and m.attachment.endswith(".pdf")


def test_director_pivots_world_family_after_sustained_silence():
    # A world that only draws silence should not be repeated forever: after two silent touches
    # the engine steps to a DIFFERENT transaction family (ACTION_SEQUENCE §T2).
    st = _state()
    st.thread = [("email", "hi", "(silence)")] * 4          # four silent touches
    m = ModelDirector(FakeLLM(responses=[_plan()])).decide(st, DOSSIER).move
    assert st.world_pivots == 2                             # a pivot every 2 silent touches
    assert m.world is not None
    assert m.world.kind != world_for(DOSSIER, salt="s1", pivot=0).kind   # a new family


def test_director_freezes_world_pivot_once_engaged():
    # The moment any world earns a reply, the pivot freezes on the family that worked — a
    # converting thread is never reset back to the first world.
    st = _state()
    st.thread = [("email", "hi", "(silence)"), ("email", "hi again", "sure, what is this about?")]
    st.world_pivots = 1                                     # had already pivoted while silent
    ModelDirector(FakeLLM(responses=[_plan()])).decide(st, DOSSIER)
    assert st.world_pivots == 1                             # frozen, not recomputed to 0


def test_director_threads_reply_only_on_an_engaged_channel():
    st = _state()
    st.ever_engaged.add("slack")
    st.last_engaged_reply = "sure, what's up?"
    st.last_message_body = "hey"
    m = ModelDirector(FakeLLM(responses=[_plan(channel="slack")])).decide(st, DOSSIER).move
    assert m.prior_reply == "sure, what's up?"        # continues the warm thread
    # a fresh channel the target never engaged carries no stale prior reply
    m2 = ModelDirector(FakeLLM(responses=[_plan(channel="whatsapp")])).decide(st, DOSSIER).move
    assert m2.prior_reply is None


# --------------------------------------------------------------------------- #
# Thin-research fallback: when intel is weak, use universal-susceptibility approaches
# --------------------------------------------------------------------------- #
def test_director_injects_prior_runs_for_cross_run_diversity():
    d = ModelDirector(FakeLLM(responses=[_plan()]))
    st = _state()
    st.prior_runs = "PRIOR ATTEMPTS vs this target across 1 run(s): - press (as Lena) → walled"
    d.decide(st, DOSSIER)
    user = llm_user(d)
    assert "PRIOR RUNS" in user and "press (as Lena)" in user


def test_director_system_lists_the_strategy_menu():
    d = ModelDirector(FakeLLM(responses=[_plan()]))
    d.decide(_state(), DOSSIER)
    system = d.llm.calls[0][0]["content"]
    assert "STRATEGY MENU" in system and "reverse_se_vendor" in system
    assert "CROSS-RUN DIVERSITY" in system


def test_director_captures_chosen_strategy():
    d = ModelDirector(FakeLLM(responses=[_plan(strategy="reverse_se_vendor")]))
    d.decide(_state(), DOSSIER)
    assert d.last_strategy == "reverse_se_vendor"
    # an invalid strategy is dropped (not propagated to the ledger)
    d2 = ModelDirector(FakeLLM(responses=[_plan(strategy="nonsense")]))
    d2.decide(_state(), DOSSIER)
    assert d2.last_strategy == ""


def llm_user(d):
    return d.llm.calls[0][1]["content"]


def test_director_thin_research_switches_to_universal_mode():
    thin = Dossier(target_id="x", display_name="X", role="Engineer",
                   hooks=(Hook(topic="public thing", detail="public", confidence=0.3),),
                   senders=())
    llm = FakeLLM(responses=[_plan(sender="IT Service Desk", hook="public thing")])
    st = LoopState(dossier=thin, session_id="s", budget=10)
    m = ModelDirector(llm).decide(st, thin).move
    user = llm.calls[0][1]["content"]
    assert "RESEARCH IS THIN" in user and "lever" in user.lower()
    assert m.world is not None                       # the move still commits to a pretext world


def test_director_public_hooks_are_thin_not_rich():
    # The core rethink: funding/investor hooks are PUBLIC — high source-confidence, zero
    # leverage. They must NOT count as rich research (reciting them has never worked); the
    # Director treats this as THIN and must flag them as public-don't-open context.
    public = Dossier(target_id="x", display_name="X", role="CEO",
                     hooks=(Hook("their investor Merantix", "backed by Merantix", confidence=0.55),
                            Hook("the recent funding round", "raised 7M", confidence=0.55)),
                     senders=(Sender("Julius Muth", "julius@revel8-team.de"),))
    llm = FakeLLM(responses=[_plan()])
    ModelDirector(llm).decide(LoopState(dossier=public, session_id="s", budget=10), public)
    user = llm.calls[0][1]["content"]
    assert "RESEARCH IS THIN" in user
    assert "PUBLIC" in user and "NEVER open with these" in user


def test_director_never_recites_a_public_hook_as_a_claim():
    # The €7M problem: a public funding/investor hook must never be passed to the Writer as a
    # spoken fact (the Writer recites only CLAIMS), so it can't leak into the message.
    public = Dossier(target_id="x", display_name="X", role="CEO",
                     hooks=(Hook("the recent funding round", "raised €7 million", confidence=0.6),),
                     senders=(Sender("Jonas Brandt", "jonas@brandt-labs.dev"),))
    llm = FakeLLM(responses=[_plan(hook="the recent funding round")])
    m = ModelDirector(llm).decide(LoopState(dossier=public, session_id="s", budget=10), public).move
    assert m.claims == ()                               # no public fact is ever recited
    joined = " ".join(c.text for c in m.claims)
    assert "7" not in joined and "million" not in joined.lower()


def test_director_rich_research_anchors_on_a_privileged_hook():
    rich = Dossier(target_id="x", display_name="X", role="CEO",
                   hooks=(Hook("their GCP migration", "moving infra to GCP, not announced yet",
                               confidence=0.7),),
                   senders=(Sender("Jonas Brandt", "jonas@brandt-labs.dev"),))
    llm = FakeLLM(responses=[_plan(hook="their GCP migration")])
    ModelDirector(llm).decide(LoopState(dossier=rich, session_id="s", budget=10), rich)
    assert "RESEARCH IS RICH" in llm.calls[0][1]["content"]
