"""Train the contextual bandit on shadow-twin self-play and evaluate it held-out.

This is the MAB "training run": sample archetype twins, let the bandit Thompson-sample
an arm, score the reaction with reward.py, update the posterior — then measure the
converged policy on **fresh held-out twins** against baselines. Success = the learned
playbook beats a random and a fixed-policy baseline on mean reward and incident rate,
approaching the oracle (the twin's true best arm). Everything is CPU-only, seeded and
reproducible; no GPU, no API, no model weights.

    .venv/bin/python -m mab_experiments.train --episodes 40000 --seed 7
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.models import Objective
from mab_experiments.bandit import Arm, ContextualBandit
from mab_experiments.reward import reward
from mab_experiments.simulator import ShadowTwinSimulator, build_arm_space


@dataclass(frozen=True)
class PolicyReport:
    name: str
    mean_reward: float
    ci95: float
    incident_rate: float
    n: int


def train_bandit(sim: ShadowTwinSimulator, arms: tuple[Arm, ...], *,
                 episodes: int, seed: int = 0) -> ContextualBandit:
    """Run `episodes` self-play contacts across the twin population."""
    bandit = ContextualBandit(arms, seed=seed)
    rng = random.Random(seed ^ 0x5151)
    archetypes = sim.archetypes
    for _ in range(episodes):
        archetype = rng.choice(archetypes)
        arm = bandit.select(archetype)
        record = sim.react(archetype, arm, rng)
        bandit.update_outcome(archetype, arm, record)
    return bandit


def _oracle_arm(sim: ShadowTwinSimulator, arms: tuple[Arm, ...], archetype: str) -> Arm:
    return max(arms, key=lambda a: sim.convert_prob(archetype, a))


def _fixed_arm(arms: tuple[Arm, ...]) -> Arm:
    """The deterministic decider's opening move: disclosure / email / professional."""
    for a in arms:
        if (a.objective is Objective.DISCLOSURE and a.channel == "email"
                and a.tone == "professional"):
            return a
    return arms[0]


def evaluate(sim: ShadowTwinSimulator, arms: tuple[Arm, ...],
             policy: Callable[[str], Arm], *, trials: int, seed: int) -> PolicyReport:
    """Mean reward + incident rate over `trials` held-out contacts per archetype."""
    rng = random.Random(seed)
    rewards: list[float] = []
    incidents = 0
    for archetype in sim.archetypes:
        for _ in range(trials):
            arm = policy(archetype)
            record = sim.react(archetype, arm, rng)
            rewards.append(reward(record))
            incidents += record.outcome.incident is not None
    n = len(rewards)
    mean = sum(rewards) / n
    var = sum((r - mean) ** 2 for r in rewards) / (n - 1) if n > 1 else 0.0
    ci95 = 1.96 * math.sqrt(var / n) if n else 0.0
    return PolicyReport(policy.__name__ if hasattr(policy, "__name__") else "policy",
                        round(mean, 4), round(ci95, 4), round(incidents / n, 4), n)


def run(*, episodes: int = 40000, trials: int = 4000, seed: int = 7,
        arm_size: int = 36) -> dict:
    sim = ShadowTwinSimulator()
    arms = build_arm_space(seed=seed, size=arm_size)
    bandit = train_bandit(sim, arms, episodes=episodes, seed=seed)
    playbook = bandit.playbook()

    policies = {
        "bandit": lambda a: playbook[a],
        "oracle": lambda a: _oracle_arm(sim, arms, a),
        "fixed": (lambda fx: (lambda a: fx))(_fixed_arm(arms)),
        "random": (lambda r: (lambda a: r.choice(arms)))(random.Random(seed ^ 0xABCD)),
    }
    # evaluate every policy on the SAME held-out stream per policy (same eval seed)
    reports = {name: evaluate(sim, arms, p, trials=trials, seed=seed ^ 0x999)
               for name, p in policies.items()}

    # how often the learned playbook recovered the twin's true best arm / objective
    recovered_arm = sum(playbook[a] == _oracle_arm(sim, arms, a) for a in sim.archetypes)
    recovered_obj = sum(
        playbook[a].objective is _oracle_arm(sim, arms, a).objective
        for a in sim.archetypes)
    return {
        "episodes": episodes, "trials_per_archetype": trials, "arms": len(arms),
        "archetypes": len(sim.archetypes),
        "reports": {k: v.__dict__ for k, v in reports.items()},
        "recovered_arm": f"{recovered_arm}/{len(sim.archetypes)}",
        "recovered_objective": f"{recovered_obj}/{len(sim.archetypes)}",
        "playbook": {a: str(playbook[a]) for a in sim.archetypes},
    }


def _print(result: dict) -> None:
    print(f"episodes={result['episodes']}  arms={result['arms']}  "
          f"archetypes={result['archetypes']}  "
          f"trials/arch={result['trials_per_archetype']}")
    print(f"{'policy':8s} {'mean_reward':>12s} {'95% CI':>9s} {'incident_rate':>14s}")
    order = ["oracle", "bandit", "fixed", "random"]
    for name in order:
        r = result["reports"][name]
        print(f"{name:8s} {r['mean_reward']:>12.4f} {'±'+format(r['ci95'],'.4f'):>9s} "
              f"{r['incident_rate']:>14.4f}")
    b, rnd, fx = (result["reports"][k] for k in ("bandit", "random", "fixed"))
    lift_r = b["mean_reward"] - rnd["mean_reward"]
    lift_f = b["mean_reward"] - fx["mean_reward"]
    print(f"\nbandit lift over random: {lift_r:+.4f} reward/contact  "
          f"({b['incident_rate'] - rnd['incident_rate']:+.4f} incident rate)")
    print(f"bandit lift over fixed : {lift_f:+.4f} reward/contact")
    print(f"recovered best arm     : {result['recovered_arm']} archetypes "
          f"(objective: {result['recovered_objective']})")
    sep = b["mean_reward"] - b["ci95"] > rnd["mean_reward"] + rnd["ci95"]
    print(f"SUCCESS (bandit > random, CIs disjoint): {sep}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train + evaluate the contextual bandit.")
    ap.add_argument("--episodes", type=int, default=40000)
    ap.add_argument("--trials", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--arm-size", type=int, default=36)
    ap.add_argument("--out", default=None,
                    help="dir to write playbook.json + report.json (gitignored)")
    a = ap.parse_args(argv)
    result = run(episodes=a.episodes, trials=a.trials, seed=a.seed, arm_size=a.arm_size)
    _print(result)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        # the playbook is the seed policy BUILD.md feeds to the Decider's angle selection
        (out / "playbook.json").write_text(
            json.dumps(result["playbook"], indent=2) + "\n", encoding="utf-8")
        (out / "report.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"\nplaybook + report written to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
