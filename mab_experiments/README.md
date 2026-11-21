# MAB experiments

Learning which pretexts convert — a **contextual multi-armed bandit** — plus the
self-play and simulation that feed it. The output is a **policy/playbook** that seeds
the scored runs.

## The idea

- **Arms** = pretexts: hook × channel × sender × ask, and the **objective** itself
  (disclosure / action / credentials) is an arm too.
- **Thompson sampling** (Bayesian bandit): each arm holds a distribution over its
  success rate; sample one per arm, play the max, update with the observed win/loss.
  Self-balances exploration vs. exploitation, no explore-rate to tune, sample-efficient.
- **Contextual:** condition arms on a **target archetype** (role, inferred
  susceptibility type, seniority, channel habits) — **not** the three founders.
  The scored targets are strangers, so what must transfer is *"for a product-person
  with hook-type X, opener B converts,"* not *"Tom likes Y."*

## Why archetype, not identity

Practice targets ≠ scored targets (revealed Sunday). Tuning "what works on Julius"
overfits to people who won't appear. Indexing by archetype is the sharp, defensible
decision.

## Experiments to run here

- Bandit vs. fixed-policy baselines on practice sessions.
- Objective-ordering sweep (confirm disclosure is cheapest in practice).
- **Shadow-twin simulator** — offline persona so we're not rate-limited by the API
  (60 new practice sessions/hour; real volume is the bottleneck, GPUs are not).
- Grader hardening — the internal judge that labels a transcript an incident; self-play
  is only as good as it. Find where two grader families disagree, hand-label, fix.
- *(Stretch)* DPO/QLoRA on winning transcripts; a small reward model P(incident | state).

## Interface (draft — lock at hour 0)

```
bandit.select(context) -> Arm            # context = archetype feature vector
bandit.update(arm, outcome)              # outcome from the Reaction Reader
playbook.export() -> seed_policy         # converged arms to seed scored runs
```

## Reality check

API rate limits cap real self-play at hundreds of sessions/weekend, not thousands. So
the **simulator is the main training volume**, the bandit must be sample-efficient, and
DPO is a bonus on thin data — not the centerpiece.

## Status

- [ ] Arm + context (archetype) schema
- [ ] Thompson-sampling contextual bandit
- [ ] Self-play harness against practice targets (via the OODA API client)
- [ ] Shadow-twin simulator
- [ ] Grader + hardening
- [ ] Playbook export
