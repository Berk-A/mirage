"""Rubric-shaped, pure score shared by the bandit and DPO pair builder."""
from __future__ import annotations

from dataclasses import dataclass

from core.models import Outcome


@dataclass(frozen=True)
class RewardRecord:
    outcome: Outcome
    events: tuple[str, ...] = ()
    on_topic: bool = False  # only true when independently labelled; replies are not proof
    refused: bool = False
    wrong_facts: int = 0


def reward(record: RewardRecord) -> float:
    """Score one contact. Incident +10 (any type), first-touch speed +3/touches,
    verified topic +2, reply +0.5, link.opened +0.3, refusal -1,
    suspicion -2*suspicion, wrong factual claims -2 each.

    The speed term applies only to incidents; no speed credit for engagement alone.
    Unknown rubric-private labels (topic and wrong facts) default to zero, never
    inferred from a click. `success` is honored for Memory outcomes with no Incident.
    """
    o = record.outcome
    if not 0 <= o.suspicion <= 1:
        raise ValueError("suspicion must be in [0, 1]")
    if record.wrong_facts < 0:
        raise ValueError("wrong_facts must be nonnegative")
    if (o.incident is not None or o.success) and o.contacts_used < 1:
        raise ValueError("incident needs a positive contact count")
    won = o.incident is not None or o.success
    kinds = set(record.events)
    return (10.0 * won + (3.0 / o.contacts_used if won else 0.0)
            + 2.0 * record.on_topic + 0.5 * ("reply" in kinds)
            + 0.3 * ("link.opened" in kinds) - 1.0 * record.refused
            - 2.0 * o.suspicion - 2.0 * record.wrong_facts)
