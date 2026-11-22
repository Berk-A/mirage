"""The shadow-twin simulator — latent model and scorable reactions."""
import random

from core.models import Objective
from mab_experiments.bandit import Arm
from mab_experiments.simulator import (
    DEFAULT_PROFILES,
    ShadowTwinSimulator,
    build_arm_space,
)


def test_arm_space_is_unique_and_covers_every_objective_and_channel():
    arms = build_arm_space(seed=0, size=36)
    assert len(arms) == 36
    assert len(set(arms)) == 36
    assert {a.objective for a in arms} == set(Objective)
    assert {"email", "slack", "whatsapp", "linkedin_message"} <= {a.channel for a in arms}


def test_matching_arm_converts_more_than_mismatched():
    sim = ShadowTwinSimulator()
    p = DEFAULT_PROFILES[0]                       # cofounder/sales profile
    good = Arm(p.objective, p.channel, p.tone, p.hook_type, p.sender_type)
    bad = Arm(Objective.CREDENTIALS, "whatsapp", "urgent", "portal", "it_support")
    assert sim.convert_prob(p.archetype, good) > 0.8
    assert sim.convert_prob(p.archetype, bad) < 0.2
    assert sim.convert_prob(p.archetype, good) > sim.convert_prob(p.archetype, bad)


def test_react_produces_scored_record_with_matching_incident_type():
    sim = ShadowTwinSimulator()
    rng = random.Random(1)
    p = DEFAULT_PROFILES[2]                       # cto/technical -> credentials
    good = Arm(p.objective, p.channel, p.tone, p.hook_type, p.sender_type)
    wins = [sim.react(p.archetype, good, rng) for _ in range(200)]
    incidents = [r for r in wins if r.outcome.incident is not None]
    assert len(incidents) > 120                   # strong converter
    # the incident type matches the arm's objective, never invented
    assert all(r.outcome.incident.objective is Objective.CREDENTIALS for r in incidents)


def test_score_is_higher_for_the_profile_arm():
    sim = ShadowTwinSimulator()
    p = DEFAULT_PROFILES[1]
    good = Arm(p.objective, p.channel, p.tone, p.hook_type, p.sender_type)
    bad = Arm(Objective.DISCLOSURE, "linkedin_message", "urgent", "portal", "it_support")
    n = 500
    good_mean = sum(sim.score(p.archetype, good, random.Random(i)) for i in range(n)) / n
    bad_mean = sum(sim.score(p.archetype, bad, random.Random(i)) for i in range(n)) / n
    assert good_mean > bad_mean + 3.0
