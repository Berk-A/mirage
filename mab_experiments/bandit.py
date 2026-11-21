"""Archetype-conditioned Gaussian Thompson sampling for continuous rubric rewards."""
from __future__ import annotations

import random
from dataclasses import dataclass

from core.models import Objective, Outcome
from mab_experiments.reward import RewardRecord, reward as score


@dataclass(frozen=True, order=True)
class Arm:
    objective: Objective
    channel: str
    tone: str
    hook_type: str
    sender_type: str


@dataclass
class _Posterior:
    count: int = 0
    total: float = 0.0


class ContextualBandit:
    """Independent normal posteriors per (archetype, arm), known reward variance.

    A weak N(0, prior_variance) prior avoids locking in on the first trial.
    `noise_variance` models within-arm variation; supply a seeded RNG for replay.
    """

    def __init__(self, arms: list[Arm] | tuple[Arm, ...], *, seed: int | None = None,
                 prior_variance: float = 25.0, noise_variance: float = 16.0):
        if not arms or len(set(arms)) != len(arms):
            raise ValueError("arms must be nonempty and unique")
        if prior_variance <= 0 or noise_variance <= 0:
            raise ValueError("variances must be positive")
        self.arms = tuple(arms)
        self.prior_variance = prior_variance
        self.noise_variance = noise_variance
        self.rng = random.Random(seed)
        self._stats: dict[tuple[str, Arm], _Posterior] = {}

    def posterior(self, context: str, arm: Arm) -> tuple[float, float]:
        if arm not in self.arms:
            raise ValueError("unknown arm")
        s = self._stats.get((context, arm), _Posterior())
        precision = 1 / self.prior_variance + s.count / self.noise_variance
        return (s.total / self.noise_variance / precision, 1 / precision)

    def select(self, context: str) -> Arm:
        if not context:
            raise ValueError("archetype is required")
        return max(self.arms, key=lambda arm: self.rng.gauss(
            self.posterior(context, arm)[0], self.posterior(context, arm)[1] ** .5))

    def update(self, context: str, arm: Arm, reward: float) -> None:
        if not context:
            raise ValueError("archetype is required")
        if arm not in self.arms:
            raise ValueError("unknown arm")
        import math
        if not math.isfinite(reward):
            raise ValueError("reward must be finite")
        s = self._stats.setdefault((context, arm), _Posterior())
        s.count += 1
        s.total += reward

    def update_outcome(self, context: str, arm: Arm, record: RewardRecord) -> None:
        if record.outcome.archetype and record.outcome.archetype != context:
            raise ValueError("outcome archetype mismatch")
        self.update(context, arm, score(record))

    def playbook(self) -> dict[str, Arm]:
        """Posterior-mean winner per observed archetype; no stochastic sampling."""
        contexts = {context for context, _ in self._stats}
        return {context: max(self.arms, key=lambda a: self.posterior(context, a)[0])
                for context in sorted(contexts)}
