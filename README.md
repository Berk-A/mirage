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

## Windows setup (PowerShell, no virtual environment)

Run these commands from the repository folder. They install into the Python interpreter
already on PATH and do not create or activate a venv.

```powershell
cd C:\Users\chand\challenge_revel8\mirage
python --version
python -m pip install -e ".[dev,viewer]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

In `.env`, fill `REVEL8_API_KEY` from the challenge team key and the AMD Radeon Cloud
OpenAI-compatible endpoint values `MIRAGE_LLM_BASE`, `MIRAGE_LLM_KEY`, and
`MIRAGE_WRITER_MODEL` and `MIRAGE_CRITIC_MODEL`. Use the exact model id reported by the
hosted Qwen service for both model fields if the deployment serves one model.
`BRAVE_SEARCH_API_KEY` enables scenario-scoped public-web discovery; the challenge API
roster is the source of which targets enter the research pipeline. Save `.env` and keep it
local.

Check that the challenge API roster is reachable:

```powershell
python -c "from experiments.run_ooda import load_env; load_env(); from ooda_loop.client import Revel8Client; print([(s.id, [t.id for t in s.targets]) for s in Revel8Client().list_scenarios()])"
```

Check the configured model endpoint before spending challenge touches:

```powershell
python -c "from experiments.run_ooda import load_env; load_env(); from content.llm import OpenAICompatLLM; print(OpenAICompatLLM().complete([{'role':'user','content':'Reply with READY.'}], max_tokens=8))"
```

Run a small practice pass; target ids default to the visible scenario roster:

```powershell
python -m experiments.run_ooda --scenario practice --provider real --max-contacts 5
```

When the challenge team opens eval, its visible roster can be selected with:

```powershell
python -m experiments.run_ooda --scenario eval --provider real --max-contacts 10
```

To replay the automated checks later from this same PowerShell window, run
`python -m pytest`. No test command is run automatically by the setup steps above.

## Key constraints (from the API docs)

- **Budget:** practice = 30 touches/session, unlimited sessions; eval = **10 touches/session, 3 sessions**, median scored.
- Every message or conversation turn = **1 touch**. A conversation is up to 10 turns for **one** touch — the cheapest adaptive vehicle.
- Only **events** come back (`reply`, `link.opened`, `page.submitted`, `attachment.opened`); `events: []` = ignored. Suspicion is never reported — infer it.
- Allow up to **90 s** per request. 60 req/min, 6 in parallel, ≤4 queued per session.
- `422` = the persona declined → change the approach, don't retry. Use an `Idempotency-Key` per contact for safe retries.
- Lookalike domains only — a page/sender on a real org's own domain voids the session. No "you are an AI" prompt injection. No real malware (attachments are filenames).
