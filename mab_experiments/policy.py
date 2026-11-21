"""Adapter that lets a `ContextualBandit` drive the Decider's angle selection.

Inject it into `ooda_loop.decider.Decider(policy=...)` to replace the fixed
`_pick_*` seams with Thompson-sampled arms, and let the OODA loop's Orient step
update it after each observed contact. This keeps the bandit (mab_experiments)
out of ooda_loop's import graph: ooda_loop depends only on a structural
`AnglePolicy` Protocol and hands outcomes back as a plain `core.models.Outcome`,
so the loop never imports `Arm`, `RewardRecord` or the reward function directly.
"""
from __future__ import annotations

from core.models import Outcome
from mab_experiments.bandit import Arm, ContextualBandit
from mab_experiments.reward import RewardRecord


class BanditPolicy:
    """Thin, stateful bridge between the loop and one `ContextualBandit`."""

    def __init__(self, bandit: ContextualBandit) -> None:
        self.bandit = bandit

    def select(self, archetype: str) -> Arm:
        """Sample the arm to try next for this archetype context."""
        return self.bandit.select(archetype)

    def update(
        self,
        archetype: str,
        arm: Arm,
        outcome: Outcome,
        events: tuple[str, ...] = (),
        *,
        refused: bool = False,
        on_topic: bool = False,
        wrong_facts: int = 0,
    ) -> None:
        """Score the contact with reward.py and update the arm's posterior.

        `on_topic` and `wrong_facts` are rubric-private labels the live API does
        not provide; they default to the honest "unknown" values and are only
        passed when a contact has been independently labelled.
        """
        self.bandit.update_outcome(
            archetype,
            arm,
            RewardRecord(outcome, tuple(events), on_topic=on_topic,
                         refused=refused, wrong_facts=wrong_facts),
        )

    def playbook(self) -> dict[str, Arm]:
        """Posterior-mean winning arm per archetype, to seed scored runs."""
        return self.bandit.playbook()
