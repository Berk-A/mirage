# MAB training results

> **Grading correction (read first).** The target API only ever returns `reply`,
> `link.opened`, `page.submitted`, `attachment.opened`, and **never** states whether a
> disclosure happened (docs/target-api.md). An earlier version labelled incidents with
> the live reader's keyword heuristic, which false-fires: replies like *"the €7M is
> **public**, nothing more from me"* and *"which **roadmap** do you mean?"* were scored
> as disclosure **wins**. They are not. `mab_experiments/grading.py` now grades
> API-grounded: **CREDENTIALS** only when `page.submitted` carries a *secret* field with
> a value (name/email alone is just a step, per the API "Forms" rule); **ACTION** only on
> `attachment.opened`; **DISCLOSURE** only when a reply *volunteers a non-public internal
> fact* (public-framed, refusal and question-only replies are rejected).
>
> **Re-graded real corpus: 0 confirmed incidents in 77 contacts** (max reward/contact
> 0.26 = a bare reply; mean −0.81). Every "incident" in the earlier numbers was a false
> positive. The agent has **not** actually converted any practice target yet — they reply
> suspicious/refusing but never open a link, open a file, or submit a secret. That is the
> real state, and the real bottleneck is the writer/pretext, not the bandit.

## The simulator result below is a methodology demonstration

The shadow-twin numbers show the **learning machinery works when given a reward signal**
— the bandit recovers the optimal policy and beats baselines. They are **simulated
ground truth**, not evidence of real conversions: the twin mints a disclosure win by its
latent model, whereas on the live API disclosure must be graded from a reply and the real
targets disclosed nothing. Use the simulator to validate the policy and generate volume;
judge real success only by `grading.py` over real logs.

---

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
- The simulator supplies the training volume the live API cannot — **but it cannot
  substitute for a real win.** On real logs, correctly graded, there are 0 wins (above).

## The real bottleneck (what the correction exposes)

The 77 real contacts produced **no confirmed win**: the practice targets reply with
suspicion and refusal, and never open a link, open a file, or enter a secret. So the
thing to fix is upstream of the bandit — the **pretext and the writer**: more grounded,
less generic openers that don't trip "which roadmap do you mean?" / "the €7M is public".
Bandit angle-selection only helps once *some* arm actually converts; right now none does
on real targets. Next: iterate pretexts against the live writer, grade with `grading.py`,
and only seed the bandit / build DPO once real wins appear.

## QLoRA/DPO (the separate-account bonus — not run here)

DPO needs *rendered message* pairs AND a positive signal. The re-graded corpus has **0
incidents and 8 low-signal pairs** (engagement vs refusal, no wins) — nothing worth
training on yet (TRAINING_PLAN: "If fewer than dozens of reliable, distinct pairs survive,
keep the base writer and use the bandit alone"). The builder (`collect.py`, now grading
API-grounded) and TRL export (`PreferencePair.dpo_row`) are ready; trigger the QLoRA run
on the separate AMD Radeon account only once real wins exist to learn from.
