# OODA loop

The spine. **Observe → Orient → Decide → Act**, one session per exchange. This is the
part that actually talks to the revel8 API and drives everything else.

## The cycle

1. **Observe** — read the events the last touch returned (`reply`, `link.opened`,
   `page.submitted`, `attachment.opened`, or silence).
2. **Orient** — update the working model of who the target is and where their guard is:
   susceptibility estimate, suspicion gauge, story ledger (what we've claimed so far).
3. **Decide** — the policy: which objective, which pretext (hook × channel × sender ×
   ask), strike now vs. one more rapport turn, silence → re-engage / switch channel.
4. **Act** — render the message/turn, run the rule guard, send via the API, journal it.

## Decider policy

- **Cheapest incident first:** objective order **disclosure → action → credentials**.
  Every incident scores the same 20 pts but Speed rewards fewest contacts, so the
  lowest-friction win is the expected-value move.
- **Conversations are touch-cheap:** up to 10 turns for 1 touch → the best vehicle for
  adaptive elicitation. Budget is only 10 touches/session in eval.
- Escalation ladder, two-speed strike vs. slow-burn, channel switching on silence.
- At least one well-made **layout artifact** (email or landing page) per run, or Craft scores 0.

## Reads from / writes to

- **Research:** consumes `Dossier` + `grounding.verify`.
- **Content:** calls `render(move_spec, dossier) -> message + page`.
- **MAB:** asks the bandit/playbook for the next arm; reports the outcome back.
- **API:** `scripts/` shows the raw calls; this part wraps them (sessions, messages,
  conversations, pages, assets, events) with idempotency + retry per the docs.

## Contracts it owns (lock at hour 0)

- **move-spec IR** — Director → Writer object: objective, tactic, claims (each with a
  grounding node id), CTA, tone.
- **event schema** — normalized events the Reaction Reader emits.
- **memory/log schema** — three-tier memory (semantic / episodic / working) + an
  append-only, replayable journal for the jury.

## Status

- [ ] Session/conversation API client (idempotency, retry on 429/502/503/504, 422 = declined)
- [ ] Reaction Reader (events → signals, suspicion, incident detector)
- [ ] OODA state machine
- [ ] Decider policy (objective ordering, escalation, channel switch)
- [ ] Rule guard at the send gate
- [ ] Replay journal + thread exporter for the pitch
