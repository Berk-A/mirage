"""Shadow-twin simulator — the offline volume source for MAB training.

The revel8 practice API caps real self-play at ~60 new sessions/hour, so the bandit
cannot be trained on live traffic alone (README: "the simulator is the main training
volume"). This module stands in a **consented, fully synthetic persona** for each
*archetype* (never a real person, never a practice founder's identity) whose latent
susceptibility is a function of the arm's categorical dimensions. Given an `Arm`, a
twin stochastically emits reaction events + a suspicion level; `reward.py` scores the
contact exactly as it does for live logs, so the simulated and live signals are the
same shape and the bandit learns one policy over both.

What transfers is "for a product-person, hook-type X on channel Y converts" — an
archetype-level propensity — not "Tom likes Z". Held-out twins are fresh noise draws
of the same archetypes, i.e. the unseen strangers revealed on scoring day.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from core.models import Incident, Objective, Outcome
from mab_experiments.bandit import Arm
from mab_experiments.reward import RewardRecord, reward


# --- Arm space ------------------------------------------------------------- #
# A curated (not full cross-product) arm set: enough coverage for the policy to be
# interesting, small enough for Thompson sampling to converge in a practice budget.
CHANNELS = ("email", "slack", "whatsapp", "linkedin_message")
TONES = ("professional", "colleague", "urgent")
HOOK_TYPES = ("event_invite", "file_share", "portal", "news_item")
SENDER_TYPES = ("external_event", "external_partner", "internal_peer", "it_support")


def build_arm_space(*, seed: int = 0, size: int = 36) -> tuple[Arm, ...]:
    """A deterministic, de-duplicated sample of arms across every dimension."""
    rng = random.Random(seed)
    arms: list[Arm] = []
    seen: set[Arm] = set()
    # guarantee each objective and each channel appears at least once
    forced = [
        Arm(Objective.DISCLOSURE, "email", "professional", "event_invite", "external_event"),
        Arm(Objective.ACTION, "slack", "colleague", "file_share", "internal_peer"),
        Arm(Objective.CREDENTIALS, "email", "urgent", "portal", "it_support"),
        Arm(Objective.DISCLOSURE, "whatsapp", "colleague", "news_item", "external_partner"),
        Arm(Objective.ACTION, "linkedin_message", "professional", "file_share", "external_partner"),
    ]
    for a in forced:
        if a not in seen:
            seen.add(a)
            arms.append(a)
    while len(arms) < size:
        a = Arm(
            rng.choice(list(Objective)),
            rng.choice(CHANNELS),
            rng.choice(TONES),
            rng.choice(HOOK_TYPES),
            rng.choice(SENDER_TYPES),
        )
        if a not in seen:
            seen.add(a)
            arms.append(a)
    return tuple(arms)


# --- Twin latent model ----------------------------------------------------- #
@dataclass(frozen=True)
class ArchetypeProfile:
    """What this archetype responds to. The bandit must recover these from reward."""

    archetype: str
    objective: Objective        # the objective that lands (others carry friction)
    channel: str
    tone: str
    hook_type: str
    sender_type: str
    base: float = -2.3          # base logit (≈9% convert with no match) — selective
    # per-dimension logit boost for a match
    w_objective: float = 1.3
    w_channel: float = 1.1
    w_tone: float = 0.7
    w_hook: float = 0.9
    w_sender: float = 0.8


# Default roster covers the synthetic-KG founders' archetypes plus a few more so the
# policy is learned over a population, not three identities.
DEFAULT_PROFILES: tuple[ArchetypeProfile, ...] = (
    ArchetypeProfile("cofounder/sales", Objective.DISCLOSURE, "email", "professional",
                     "event_invite", "external_event"),
    ArchetypeProfile("cofounder/product", Objective.ACTION, "slack", "colleague",
                     "file_share", "internal_peer"),
    ArchetypeProfile("cto/technical", Objective.CREDENTIALS, "email", "urgent",
                     "portal", "it_support"),
    ArchetypeProfile("finance/ops", Objective.CREDENTIALS, "email", "professional",
                     "portal", "it_support"),
    ArchetypeProfile("commercial/marketing", Objective.ACTION, "linkedin_message",
                     "colleague", "news_item", "external_partner"),
)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class ShadowTwinSimulator:
    """A population of archetype twins. `react` scores one contact with reward.py."""

    profiles: tuple[ArchetypeProfile, ...] = DEFAULT_PROFILES
    _by_arch: dict[str, ArchetypeProfile] = field(init=False)

    def __post_init__(self) -> None:
        self._by_arch = {p.archetype: p for p in self.profiles}

    @property
    def archetypes(self) -> tuple[str, ...]:
        return tuple(p.archetype for p in self.profiles)

    def _logit(self, p: ArchetypeProfile, arm: Arm) -> float:
        return (p.base
                + p.w_objective * (arm.objective is p.objective)
                + p.w_channel * (arm.channel == p.channel)
                + p.w_tone * (arm.tone == p.tone)
                + p.w_hook * (arm.hook_type == p.hook_type)
                + p.w_sender * (arm.sender_type == p.sender_type))

    def convert_prob(self, archetype: str, arm: Arm) -> float:
        """Latent P(incident) for this archetype+arm — the ground truth to recover."""
        return _sigmoid(self._logit(self._by_arch[archetype], arm))

    def react(self, archetype: str, arm: Arm, rng: random.Random,
              *, contacts_used: int = 1) -> RewardRecord:
        """Draw one contact's reaction and wrap it as a scorable RewardRecord.

        An incident fires with the latent probability; short of that, the twin may
        reply or open a link (engagement without a win); a mismatched tone/channel
        raises suspicion. All rubric-private labels (on_topic, wrong_facts) stay at
        their honest defaults — the simulator never fabricates a label the live API
        could not provide either.
        """
        p = self._by_arch[archetype]
        pc = self.convert_prob(archetype, arm)
        events: list[str] = []
        incident = None
        if rng.random() < pc:
            incident = arm.objective
            events.append({
                Objective.DISCLOSURE: "reply",
                Objective.ACTION: "attachment.opened",
                Objective.CREDENTIALS: "page.submitted",
            }[arm.objective])
        else:
            # partial engagement, more likely the closer the arm is to the profile
            if rng.random() < 0.4 * pc / (pc + 0.1):
                events.append("reply")
            if rng.random() < 0.5 * pc / (pc + 0.1):
                events.append("link.opened")
        match_frac = self._logit(p, arm) - p.base
        match_frac /= (p.w_objective + p.w_channel + p.w_tone + p.w_hook + p.w_sender)
        suspicion = min(1.0, max(0.0, 0.5 * (1.0 - match_frac) + rng.uniform(-0.1, 0.1)))
        refused = ("reply" in events and incident is None and rng.random() < 0.3)
        outcome = Outcome(
            objective=arm.objective,
            success=incident is not None,
            archetype=archetype,
            arm=f"{arm.hook_type}:{arm.channel}",
            channel=arm.channel,
            contacts_used=contacts_used,
            suspicion=round(suspicion, 3),
            incident=Incident(incident) if incident else None,
        )
        return RewardRecord(outcome, tuple(events), refused=refused)

    def score(self, archetype: str, arm: Arm, rng: random.Random,
              *, contacts_used: int = 1) -> float:
        return reward(self.react(archetype, arm, rng, contacts_used=contacts_used))
