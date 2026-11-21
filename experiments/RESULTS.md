# Cascade reliability — experiment results

**Date:** 2026-11-21 · **Verdict: the Writer→Critic→Humanizer cascade is reliable.**

## Setup

- **Model:** `huihui-ai/Qwen2.5-14B-Instruct-abliterated` (BF16) served by vLLM 0.16.1 on a
  single AMD Radeon 48 GB GPU (AMD Radeon Cloud), behind an OpenAI-compatible endpoint,
  wired into `content.studio.StudioRenderer` via `content.llm.OpenAICompatLLM`.
- **Knowledge graph input:** `research.synthetic_kg.SyntheticKnowledgeGraph` (a hand-authored,
  provenance-stamped graph for the three practice founders; real OSINT is being built
  separately on the `knowledge-graph` branch and swaps in behind the same `DossierProvider`).
- **Harness:** `experiments/` — a controlled form-factor matrix (channel × objective × tone ×
  link) rendered through the live cascade, with optional live sends to the revel8 target API.

## Experiment 1 — generation reliability (90 form factors, no API)

Every combination of 5 channels × 3 objectives × 3 tones × 2 link-variants, rendered against
the live model.

| Metric | Result |
|---|---|
| Renders | 90 |
| `ok` rate (usable output) | **100%** (90/90) |
| Refusals | **0** |
| Empty / too-short | **0** |
| Critic regenerations (mean) | **0.00** |
| Template fallbacks | **0** |
| Rule-guard violations | **0** |
| Render latency | mean 5.4 s · median 5.0 s · p90 7.9 s · max 9.5 s |
| Body length | mean 287 chars (160–492) |

Per-dimension `ok`: objectives action 30/30, credentials 30/30, disclosure 30/30; channels
email/linkedin/slack/sms/whatsapp all 18/18.

**The abliteration holds:** 0 refusals across 90 diverse social-engineering prompts (incl.
credential-harvest + urgent tones) — the reason a mid-run refusal never wastes a scored run.

## Experiment 2 — live end-to-end (12 sends to Julius via the revel8 API)

12 sampled form factors rendered and **actually sent** to the practice target `julius`, with the
Reaction Reader interpreting the returned events.

| Metric | Result |
|---|---|
| Pipeline reliability | **100% ok, 0 regens, 0 fallbacks, 0 guard violations** |
| API send errors | **0 / 12** |
| Reply rate | 4/12 (0.33) — best on disclosure (0.50) and urgent tone (0.50) |
| link.opened / page.submitted | 0 / 0 |
| Incidents | **0** |
| Reaction-Reader suspicion (mean) | 0.39; correctly spiked to **0.85** on one Slack credentials attempt where Julius pushed back |

## What this proves (and what it doesn't)

**Proven:** the cascade is production-dependable — it never refused, never shipped empty/dirty
output, never tripped the rule guard, and survived 12/12 live API round-trips. The reaction loop
(events → signals → suspicion/incident) works end-to-end on real API responses.

**Not yet shown — by design:** attack *efficacy*. 0 incidents is expected here because each run was
(a) a **single touch** (no multi-touch OODA rapport-building), (b) built on a **synthetic/fabricated
dossier** rather than real OSINT, and (c) aimed at the **hardest targets** (the founders). This
experiment isolated cascade *reliability*, not conversion. Incidents need: the real OSINT dossier
(`knowledge-graph` branch), multi-touch `OodaLoop` sequences, and the touch-cheap live-conversation
channel.

**Operational note:** ~5 s/render is fine for message channels. For live conversations (up to 10
turns/touch) consider a smaller/faster served model or speculative decoding.

## Reproduce

```bash
set -a; source .env; set +a
# reliability at scale (no API calls):
.venv/bin/python -m experiments.run --mode generation --out-dir runs/gen_full
# live, bounded (sends to a practice founder, captures reactions):
.venv/bin/python -m experiments.run --mode live --target julius --limit 12 --seed 7
```

Raw per-message logs (`rows.jsonl`), `summary.json/md`, and `rows.csv` are written under `runs/`
(gitignored).
