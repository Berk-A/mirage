# MIRAGE control / monitoring portal

A thin web UI over the existing MIRAGE backend — run artifacts + the strategy ledger — so
the team can monitor runs, dossiers, reactions, incidents and cross-run strategy, and (opt-in)
launch a run. **No new dependencies, no build step**: a stdlib `http.server` JSON API plus a
vanilla-HTML/JS single page, served from one process.

The frontend reproduces the supplied "chroma glow" dashboard design (Plus Jakarta Sans / Inter
/ JetBrains Mono, the oklch petrol/teal/mint/ink/lavender palette). All design seams are CSS
variables at the top of `static/styles.css` — restyle there.

## Run it

```bash
# from the repo root, with the project venv
.venv/bin/python -m portal.server --port 8000
```

Then open <http://127.0.0.1:8000>.

### Pointing at the run artifacts

The real OODA run artifacts and `strategy_ledger.json` are **git-ignored**, so they live only
in the checkout where runs were produced (typically the main checkout, not a worktree). Point
the portal at that `runs/` directory with `MIRAGE_RUNS_DIR`:

```bash
MIRAGE_RUNS_DIR=/path/to/revel8/runs .venv/bin/python -m portal.server --port 8000
```

Default (no env) is `runs/` next to the repo root. The status banner at the top of the page
shows which directory is being read and how many run dirs were found.

### Fresh clone shows real data

A curated snapshot of run artifacts is committed to the repo, so **a fresh clone renders a
populated dashboard with no setup** — just `python3 -m portal.server` and open the page. Only
the slice the portal reads is tracked: per-run `summary.json`, the `<target>.jsonl` session
threads, `<target>_dossier.json`, and `strategy_ledger.json` (~780K). The rest of `runs/` —
`osint_cache`, `llm_extract_cache`, raw `conversation_*.jsonl` logs, journals, model
artifacts (~235M) — stays git-ignored. Set `MIRAGE_RUNS_DIR` to override the snapshot with
your own runs.

The snapshot is **point-in-time**: new runs produced after it was committed won't appear
until you refresh it. To refresh from a checkout where runs were produced:

```bash
# from repo root; SRC = a runs/ dir that has the fresh artifacts
SRC=/path/to/revel8/runs
rsync -am \
  --include='*/' \
  --include='*/summary.json' --include='*/*_dossier.json' --include='*/*.jsonl' \
  --include='strategy_ledger.json' --exclude='*' \
  "$SRC"/ runs/
git add -f runs/ && git commit -m "Portal: refresh committed run snapshot"
```

The `rsync` filter copies only the portal-relevant files (it skips the caches and raw logs);
`git add -f` is needed because `runs/` is git-ignored.

## What binds to what

| UI section | Backend source |
|---|---|
| Stat cards (median skepticism / win rate / sessions / avg turns) | `summary.json` rows + touch `suspicion` |
| Skepticism-per-run area chart | end-of-session `suspicion` per (run, target) |
| Outcomes donut | `summary` row `incident` → credentials / disclosure / action / none |
| Skepticism-per-AI-twin cards | `<target>_dossier.json` (role, archetype, hooks) + per-target win rate |
| Share-of-runs-by-channel bars | wins grouped by touch `channel` |
| Session log table | one row per `(run dir, target)` from `summary.json` |
| Session replay timeline | `<target>.jsonl` touches → `events` (SENT / REPLY / SILENCE), suspicion per touch |
| Targets & dossiers | all `<target>_dossier.json` (hooks w/ provenance, senders, vendors) |
| Strategy ledger | `runs/strategy_ledger.json` (mirrors `ooda_loop.ledger.summarize`) |
| New run (launch) | spawns `python -m experiments.run_ooda …` |

Design vocabulary ↔ backend: **persona / AI twin** = target, **skepticism** = touch
suspicion, **outcome** = incident label, **session replay** = the touch→reaction thread
(this mirrors `pipeline_viewer/app.py`).

## API

Read (all GET, JSON):

- `GET /api/health` — runs dir + discovered run dirs
- `GET /api/overview?persona=<id|all>&channel=<name|all>` — all dashboard aggregates
- `GET /api/session?run=<dir>&target=<id>` — one session replay (touches + reactions)
- `GET /api/dossiers` — targets & research dossiers
- `GET /api/ledger` — cross-run strategy ledger
- `GET /api/runs` — raw run-dir listing

Control (opt-in, **side-effecting**):

- `POST /api/launch` `{scenario,targets,cast,brain,max_contacts}` → `{job_id,…}`
- `GET /api/jobs` / `GET /api/jobs/<id>` → launched-run status + log tail

> ⚠️ Launch opens **new target sessions** and spends the **team-wide 60-sessions/hour** pool.
> The portal never starts a run on its own — only the "New run" dialog does, deliberately.

## Tests

```bash
.venv/bin/pytest tests/test_portal.py
```

## Notes / seams for later

- Charts are hand-drawn inline SVG (area / donut / h-bars / progress) — no chart lib. Swap for
  a library later if richer interaction is wanted.
- `static/` is pure static assets; the design can be reskinned entirely via `styles.css`
  tokens without touching `app.js` or the API.
- A chat panel (over `scripts/chat_server.py`) is a natural next addition to the launch section.
