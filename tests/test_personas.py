"""Multi-persona orchestration: a coordinated cast + the corroborator mechanic, where one
identity references another as an already-involved colleague (the verification chain that
answers a target's 'who is my contact / who are you coordinating with' demand)."""
import json

from content.llm import FakeLLM
from content.prompts import writer_user_prompt
from core.models import Dossier, MoveSpec, Objective, Sender
from ooda_loop.director import ModelDirector
from ooda_loop.personas import CASTS, Cast, audit_cast, vendor_cast
from ooda_loop.state import LoopState


def _cast_dossier() -> Dossier:
    return Dossier(target_id="tom", display_name="Tom Müller", role="Co-Founder & Co-CEO",
                   senders=audit_cast().senders)


def _plan(**kw):
    base = {"reasoning": "the audit trap, two parties", "strategy": "multi_persona",
            "objective": "action", "channel": "email", "sender": "Katrin Vogel",
            "hook": "ISO 27001 certification", "tactic": "plain",
            "intent": "schedule the Stage 2 evidence", "corroborator": "Markus Berg"}
    base.update(kw)
    return json.dumps(base)


def _move(resp):
    d = _cast_dossier()
    return ModelDirector(FakeLLM(responses=[resp])).decide(
        LoopState(dossier=d, session_id="s", budget=10), d).move


# -- cast --------------------------------------------------------------------- #
def test_cast_relationships_and_safe_domains():
    c = audit_cast()
    assert len(c.senders) == 2
    berg = c.by_name("Berg")
    assert berg and "Berg" in berg.name
    colleague = c.colleague_of(berg)
    assert colleague and colleague.name != berg.name           # the OTHER member
    # a fictional outside org — never a lookalike of the target's own domain
    assert all("revel8" not in (s.address or "").lower() for s in c.senders)


def test_vendor_cast_is_pushy_plus_helper():
    c = vendor_cast("STACKIT")
    assert len(c.senders) == 2 and c.org.startswith("STACKIT")
    assert "stackit-status.io" in c.senders[0].address
    assert c.by_name("Daniel Roth") is not None
    assert set(CASTS) == {"audit", "vendor"}


# -- director picks a corroborator -------------------------------------------- #
def test_director_commits_to_a_world_over_a_cast_corroborator():
    # The transactional pretext world supersedes a dossier cast on the message path: the move is
    # sent as the world's OWN persona, with no bolted-on corroborator (its team lives in the
    # world facts instead). The _pick_corroborator mechanism itself is still unit-tested below.
    m = _move(_plan())
    assert m.world is not None and m.sender.name == m.world.persona_name
    assert m.corroborator is None


def test_corroborator_is_never_the_acting_sender():
    # you cannot vouch for yourself — naming the acting sender resolves to None
    m = _move(_plan(sender="Katrin Vogel", corroborator="Katrin Vogel"))
    assert m.corroborator is None


def test_corroborator_omitted_is_none():
    assert _move(_plan(corroborator="")).corroborator is None


def test_corroborator_must_be_a_known_sender():
    # an invented name (not in the cast) is never referenced
    assert _move(_plan(corroborator="Some Invented Person")).corroborator is None


# -- writer weaves it in ------------------------------------------------------ #
def test_writer_prompt_references_the_corroborator():
    c = audit_cast()
    spec = MoveSpec(objective=Objective.ACTION, channel="email", sender=c.senders[1],
                    ask="confirm the controls", corroborator=c.senders[0])
    p = writer_user_prompt(spec, _cast_dossier())
    assert "CORROBORATING COLLEAGUE" in p and "Markus Berg" in p
    assert "do NOT fabricate" in p


def test_movespec_corroborator_defaults_none():
    assert MoveSpec(objective=Objective.DISCLOSURE, channel="email",
                    sender=Sender("X")).corroborator is None
