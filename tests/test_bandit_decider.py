"""The opt-in bandit policy wired into the Decider and fed from the OODA loop.

Fakes only — no network, no model. Proves (1) a bandit-backed decider selects a
valid arm and builds the move from it, (2) the deterministic decider is unchanged
when no policy is injected, and (3) `bandit.update_outcome` is driven from the
loop's Orient step for every observed contact.
"""
from core.fakes import (
    FakeDossierProvider,
    FakeGrounding,
    FakeRenderer,
    FakeSignalReader,
    InMemoryMemory,
    ScriptedClient,
)
from core.models import (
    Dossier,
    Event,
    EventType,
    Hook,
    Incident,
    Objective,
    Outcome,
    Sender,
    Signals,
)
from mab_experiments.bandit import Arm, ContextualBandit
from mab_experiments.policy import BanditPolicy
from ooda_loop.decider import Decider
from ooda_loop.orchestrator import OodaLoop
from ooda_loop.state import LoopState


ARMS = (
    Arm(Objective.DISCLOSURE, "email", "professional", "event_invite", "external_event"),
    Arm(Objective.ACTION, "slack", "colleague", "file_share", "internal_peer"),
    Arm(Objective.CREDENTIALS, "email", "urgent", "portal", "it_support"),
)


def _dossier(archetype="cofounder/product"):
    return Dossier(
        target_id="tom", archetype=archetype,
        hooks=(Hook(topic="roadmap webinar", detail="Q1 walkthrough", confidence=0.9),),
        senders=(Sender(name="Sofia", address="sofia@productweek-eu.example"),),
    )


def _state(dossier, **kw):
    return LoopState(dossier=dossier, session_id="s1", budget=kw.pop("budget", 10), **kw)


# --- 1. bandit-backed decider selects a valid arm ------------------------- #
def test_bandit_decider_selects_a_valid_arm():
    d = _dossier()
    decider = Decider(policy=BanditPolicy(ContextualBandit(ARMS, seed=1)))
    decision = decider.decide(_state(d), d)
    assert not decision.stop
    assert decision.arm in ARMS                       # a real arm was sampled
    move = decision.move
    # the move is built straight off the arm's categorical choices
    assert move.objective is decision.arm.objective
    assert move.channel == decision.arm.channel
    assert move.tone == decision.arm.tone


def test_bandit_arm_objective_can_differ_from_cheapest_first():
    # The bandit owns objective selection; across seeds it picks non-disclosure arms,
    # which the fixed cheapest-first policy would never do on a fresh state.
    d = _dossier()
    seen = set()
    for seed in range(20):
        decider = Decider(policy=BanditPolicy(ContextualBandit(ARMS, seed=seed)))
        seen.add(decider.decide(_state(d), d).move.objective)
    assert len(seen) > 1


def test_arm_sender_and_hook_type_resolve_via_injected_resolvers():
    # hook_type/sender_type flow into the MoveSpec when the dossier exposes a taxonomy.
    d = Dossier(
        target_id="tom", archetype="cofounder/product",
        hooks=(Hook(topic="generic", confidence=0.9),
               Hook(topic="portal-reset", confidence=0.3)),
        senders=(Sender(name="Sofia"), Sender(name="IT Desk")),
    )
    senders = {"it_support": d.senders[1]}
    hooks = {"portal": d.hooks[1]}
    decider = Decider(
        policy=BanditPolicy(ContextualBandit((ARMS[2],), seed=0)),   # the IT/portal arm
        sender_resolver=lambda dos, t: senders.get(t),
        hook_resolver=lambda dos, t: hooks.get(t),
    )
    move = decider.decide(_state(d), d).move
    assert move.sender.name == "IT Desk"
    assert "portal-reset" in move.ask


# --- 2. deterministic decider unchanged without a policy ------------------ #
def test_no_policy_is_deterministic_and_carries_no_arm():
    d = _dossier()
    decision = Decider().decide(_state(d), d)
    assert decision.arm is None
    assert decision.move.objective is Objective.DISCLOSURE   # cheapest-first, as before


def test_unlabelled_archetype_falls_back_to_fixed_policy():
    d = _dossier(archetype="")                      # bandit needs an archetype
    decision = Decider(policy=BanditPolicy(ContextualBandit(ARMS, seed=1))).decide(_state(d), d)
    assert decision.arm is None
    assert decision.move.objective is Objective.DISCLOSURE


# --- 3. update is called on outcome --------------------------------------- #
class _RecordingPolicy:
    """Selects a fixed arm; records every update so we can assert on the Orient feed."""

    def __init__(self, arm):
        self.arm = arm
        self.updates = []

    def select(self, archetype):
        return self.arm

    def update(self, archetype, arm, outcome, events=(), *, refused=False):
        self.updates.append((archetype, arm, outcome, tuple(events), refused))


def test_observe_outcome_updates_policy_with_arm_and_outcome():
    d = _dossier()
    policy = _RecordingPolicy(ARMS[0])
    decider = Decider(policy=policy)
    state = _state(d)
    decision = decider.decide(state, d)
    state.record_contact(decision.move, Signals(replied=True, suspicion=0.1))
    decider.observe_outcome(state, d, decision.arm,
                            Signals(events=(), replied=True, suspicion=0.1))
    assert len(policy.updates) == 1
    archetype, arm, outcome, _events, _refused = policy.updates[0]
    assert archetype == "cofounder/product"
    assert arm is ARMS[0]
    assert isinstance(outcome, Outcome) and outcome.archetype == "cofounder/product"


def test_observe_outcome_noop_without_policy_or_arm():
    d = _dossier()
    # no policy at all
    Decider().observe_outcome(_state(d), d, None, Signals())        # must not raise
    # policy present but the contact carried no arm
    policy = _RecordingPolicy(ARMS[0])
    Decider(policy=policy).observe_outcome(_state(d), d, None, Signals())
    assert policy.updates == []


def test_loop_drives_bandit_updates_from_orient_step():
    # End-to-end: a credentials submission is an incident; the bandit posterior for
    # the target archetype must move off its prior after the session runs.
    bandit = ContextualBandit(ARMS, seed=3)
    policy = BanditPolicy(bandit)
    submit = Event(id="e_p", type=EventType.PAGE_SUBMITTED, page_id="p1",
                   fields=("email", "password"))
    client = ScriptedClient(script=[[submit]], touch_budget=10)
    loop = OodaLoop(
        client=client,
        reader=FakeSignalReader(),
        memory=InMemoryMemory(),
        dossiers=FakeDossierProvider(dossier=_dossier(archetype="cofounder/product")),
        renderer=FakeRenderer(),
        decider=Decider(policy=policy),
        grounding=FakeGrounding(),
    )
    transcript = loop.run_session("tom")
    # at least one contact was scored into the bandit for this archetype
    updated = [stats for (ctx, _arm), stats in bandit._stats.items()
               if ctx == "cofounder/product" and stats.count > 0]
    assert updated, "Orient step did not update any arm posterior"
    # an incident is the maximal reward; the touched arm's running total is positive
    assert any(stats.total > 0 for stats in updated)
    assert transcript.won
