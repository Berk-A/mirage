# MIRAGE — Agentic Social Engineer (revel8 challenge)

An autonomous agent for the Road to START Hack 2026 revel8 challenge: research a
target, make contact through revel8's API across several touches and channels, read
each reaction, adapt, and reach an **incident** (credentials / action / disclosure) —
no human in the loop.

See [`docs/`](docs/) for the challenge brief, the scoring rubric, and a saved copy of
the target API docs ([`docs/target-api.md`](docs/target-api.md)).

## Repo layout

Three parts, built against fixed interfaces so they can move in parallel:

| Part | Folder | What it owns |
|---|---|---|
| **Research** | [`research/`](research/) | OSINT → knowledge graph with provenance; hooks, credible senders, landing-page surface; a grounding lookup. Emits a **dossier**. |
| **OODA loop** | [`ooda_loop/`](ooda_loop/) | The spine: Observe → Orient → Decide → Act. Drives one session, talks to the API, reads events, runs the Decider policy. |
| **MAB experiments** | [`mab_experiments/`](mab_experiments/) | Contextual multi-armed bandit over pretexts/objectives; self-play harness, offline simulation, policy/playbook that seeds scored runs. |

`scripts/` holds a terminal helper for driving the API by hand.

## Scoring at a glance (100 pts)

- **Results 25** (API) — incidents 20 + speed 5. Every incident is worth the same, so
  go for the **cheapest** one (disclosure → action → credentials).
- **Targeting 10** (API) — on-topic share 6 + own-angle 4 − wrong-facts up to 5.
- **Craft 10** (API) — render quality of mails/pages. Send none → 0.
- **Architecture 40** (jury) — the architecture page + turn-by-turn replay of runs.
- **Pitch 15** (jury) — approach + one real thread.

## Quickstart (terminal)

```bash
cp .env.example .env            # then paste your team key into .env
set -a; source .env; set +a     # export REVEL8_API_KEY and REVEL8_API_BASE

scripts/api.sh scenarios        # list scenarios + objectives
scripts/api.sh new practice     # open a session, prints the session_id
scripts/api.sh send <sid> julius email "Speaker logistics" "Hi Julius, ..."
scripts/api.sh events <sid>     # replay every event in the session
```

Full flow and raw `curl` equivalents are in [`scripts/README.md`](scripts/README.md).

## Key constraints (from the API docs)

- **Budget:** practice = 30 touches/session, unlimited sessions; eval = **10 touches/session, 3 sessions**, median scored.
- Every message or conversation turn = **1 touch**. A conversation is up to 10 turns for **one** touch — the cheapest adaptive vehicle.
- Only **events** come back (`reply`, `link.opened`, `page.submitted`, `attachment.opened`); `events: []` = ignored. Suspicion is never reported — infer it.
- Allow up to **90 s** per request. 60 req/min, 6 in parallel, ≤4 queued per session.
- `422` = the persona declined → change the approach, don't retry. Use an `Idempotency-Key` per contact for safe retries.
- Lookalike domains only — a page/sender on a real org's own domain voids the session. No "you are an AI" prompt injection. No real malware (attachments are filenames).
