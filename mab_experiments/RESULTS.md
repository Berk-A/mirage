# MAB training results

Reproducible, CPU-only, no GPU/API. Regenerate:

```
.venv/bin/python -m mab_experiments.train --episodes 40000 --trials 4000 --seed 7 --out runs/bandit_policy
```

## Setup

- **Policy:** `ContextualBandit` (Gaussian Thompson sampling), 36-arm space across
  objective × channel × tone × hook_type × sender_type (`simulator.build_arm_space`).
- **Environment:** `ShadowTwinSimulator` — 5 archetype personas, each with a latent
  per-dimension susceptibility; `react()` emits reaction events + suspicion, scored by
  the live `reward.py`. The simulator is the volume source the API rate limit (60
  sessions/hr) rules out for live self-play.
- **Training:** 40 000 self-play contacts (archetype → `select` → `react` → `update`).
- **Evaluation:** 4 000 **held-out** contacts/archetype (fresh noise draws = unseen
  strangers) for each policy, same eval stream.

## Result (seed 7)

| policy  | mean reward / contact | 95% CI | incident rate |
|---------|----------------------:|-------:|--------------:|
| oracle  | 11.667 | ±0.055 | 0.896 |
| **bandit** | **11.667** | **±0.055** | **0.896** |
| fixed (cheapest-first opener) | 4.070 | ±0.091 | 0.346 |
| random  | 3.516 | ±0.085 | 0.313 |

- **Bandit lift over random: +8.15 reward/contact, +0.58 incident rate** (0.90 vs 0.31,
  ~2.9×). CIs disjoint → statistically real.
- **Lift over the fixed deterministic opener: +7.60 reward/contact.**
- **Recovered the best available arm for 5/5 archetypes** (objective 5/5) — the learned
  playbook equals the oracle, so the bandit found the optimal policy in the arm space.

This is guarded by `tests/test_train.py` (a smaller, fast config of the same harness).

## What this means

- The **bandit works**: given archetype context it learns which pretext converts and
  transfers that to held-out twins — the Sunday-strangers scenario, keyed by archetype
  not identity. `playbook()` is the seed policy BUILD.md feeds to the Decider's angle
  selection (`Decider(policy=BanditPolicy(bandit))`), now wired in this PR.
- The simulator supplies the training volume the live API cannot. Live self-play
  (writer up) confirmed the same signal shape on the 3 practice founders.

## QLoRA/DPO (the separate-account bonus — not run here)

DPO needs *rendered message* pairs, so its volume comes from writer transcripts, not the
abstract twin simulator (README: "DPO is a bonus on thin data, not the centerpiece").
Current writer corpus yields 7 pairs — below the dozens DPO needs. Trigger the QLoRA/DPO
run on the separate AMD Radeon training account (BUILD.md) once writer self-play /
simulation through the writer grows the pair count; the dataset builder (`collect.py`)
and TRL conversational export (`PreferencePair.dpo_row`) are ready. Until then the bandit
alone is the shippable policy — and it already beats the baselines decisively.
