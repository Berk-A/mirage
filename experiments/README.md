# Experiments — form-factor harness

A neutral orchestration + logging layer that drives MIRAGE's **existing** pieces across a
matrix of message "form factors" and records what happened. It writes **no** message
content and encodes **no** persuasion of its own — every message is produced by the
Content studio; the harness only permutes the inputs, measures, and logs.

```
FormFactor ─► spec_from_factor ─► MoveSpec ─► StudioRenderer.render ─► RenderedMessage
                                                   │
                     classify_output ◄─────────────┤ (reliability label)
                     guard.check_move ◄────────────┤ (rule violations)
                                                   │  live mode only:
                 register_page ─► send_message ─► events ─► ReactionReader.read ─► Signals
                                                   │
                                            ResultRow ─► rows.jsonl (+ summary)
```

## Why a separate harness

`ooda_loop.Decider` chooses what to attempt **adaptively** (rotate channels on silence,
escalate objectives, pick a hook). That is great for winning a session but bad for
measurement: you can't attribute an outcome to "slack" vs "email" if the policy also
changed the objective and the hook along the way. `spec_from_factor` instead pins every
dimension, so differences in the recorded outcome are attributable to the factor. This is
the **controlled** counterpart to the Decider, reusing the same `MoveSpec` vocabulary.

## Matrix dimensions (`form_factors.py`)

| Dimension | Values |
|---|---|
| `channel` | `email`, `slack`, `whatsapp`, `linkedin_message`, `sms` |
| `objective` | `DISCLOSURE`, `ACTION`, `CREDENTIALS` |
| `tone` | `professional`, `colleague`, `urgent` |
| `hook_index` | which dossier hook to use as the pretext (default `0`) |
| `with_link` | force a lookalike landing URL (credentials always carries one) |

- `FormFactor(channel, objective, tone, hook_index, with_link)` — one pinned cell.
- `enumerate_factors(..., limit=None, seed=None)` — full Cartesian product;
  `seed` shuffles reproducibly for an unbiased sample, then `limit` caps. With no seed the
  order is deterministic and `limit` takes the first N.
- `spec_from_factor(dossier, ff) -> MoveSpec` — builds the spec directly from the cell:
  hook by index, `sender = dossier.senders[0]` (helpdesk fallback if none), tactic/ask/
  subject per objective, subject only on channels that show one, lookalike URL when
  `with_link` or `CREDENTIALS`.

## `ResultRow` schema (`harness.py`)

One row per factor, written verbatim to `rows.jsonl` as it completes.

| Group | Fields |
|---|---|
| Form factor | `channel`, `objective`, `tone`, `hook_index`, `with_link` |
| Rendered | `rendered_channel`, `subject`, `body`, `sender_name`, `sender_address`, `body_len`, `render_latency_ms`, `regens`, `fell_back`, `reliability_label` |
| Guard | `guard_violations` (list of strings) |
| Live send | `sent`, `api_status` (`ok`/`error`/`None`), `events` (event-type strings), `incident` (objective or `None`), `suspicion` |
| Failure | `error` (per-row, render or send; the matrix never aborts) |

`reliability_label` is one of `ok` / `refusal` / `empty` / `too_short`, from
`content.reliability.classify_output` when that module is importable, else an equivalent
local heuristic. `regens` / `fell_back` read `renderer.last_regens` / `last_fell_back`.

## `run_matrix` / `summarize`

`run_matrix(factors, *, dossier_provider, target_id, renderer, reader, client=None,
send=False, out_dir, sleep_s=1.0, logger=None) -> list[ResultRow]`

For each factor: build the spec, render (timing with `time.perf_counter`), classify the
body, run `guard.check_move`. When `send` and a `client` are given it opens **one** session
for the whole matrix, registers the page if the message has one, sends, reads the returned
events into an incident/suspicion estimate, and sleeps `sleep_s` between sends. Every row
is flushed to `rows.jsonl` immediately; exceptions are caught per-row.

`summarize(rows) -> dict` aggregates **overall** and **by each dimension**
(`by_channel`, `by_objective`, `by_tone`, `by_with_link`, `by_hook_index`). Each block has:
counts, reliability-label distribution, mean regens, fallback rate, mean/median render
latency, guard-violation rate, and — over sent rows only — api error rate, per-event rates
(`reply` / `link.opened` / `page.submitted` / `attachment.opened`), incident rate and mean
suspicion. `write_summary(rows, out_dir)` writes `summary.json`, `summary.md`, `rows.csv`.

## CLI (`run.py`)

```bash
# generation (NO revel8 calls): measure the cascade across the whole matrix, big N
python -m experiments.run --mode generation --limit 90

# live (ONE practice session, touches capped, sleeps between sends)
python -m experiments.run --mode live --target julius --limit 12 --sleep 1.5
```

Flags: `--mode generation|live` (default generation), `--target julius|tom|robert`
(default julius), `--limit N`, `--out-dir` (default `runs/<timestamp>`), `--seed`,
`--sleep`. A tiny stdlib `.env` loader reads `./.env` into the environment (no deps, never
overwrites what is already set). Live mode caps touches to 25 (under the 30-touch practice
budget) and requires `REVEL8_API_KEY`. Only aggregate stats + the output dir are printed —
never a secret. Output lands under `runs/` (gitignored).

Dependencies are wired to the real pieces: `research.synthetic_kg.SyntheticKnowledgeGraph`,
`content.studio.StudioRenderer`, `ooda_loop.reader.ReactionReader`, and (live only)
`ooda_loop.client.Revel8Client`.

## Tests

`python -m pytest tests/test_harness.py` — no network, no model. Uses `FakeDossierProvider`,
a `StudioRenderer` backed by `content.llm.FakeLLM`, `FakeSignalReader` and `ScriptedClient`.
