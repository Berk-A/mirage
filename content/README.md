# Content studio

Turns a neutral `MoveSpec` (the decider's output) into a vetted, ready-to-send
message. This is the concrete `Renderer` (`core.interfaces.Renderer`) and the only part
that calls a model — everything upstream (targeting, objective, grounded claims) is
already decided.

Authorized context: the revel8 "Agentic Social Engineer" challenge. Targets are AI
personas in a closed simulation; nothing rendered here reaches a real person or channel.

## Cascade

```
MoveSpec ─► Writer ─► Critic ──issues──► Writer.rewrite ─┐ (capped)
                        │ ok                             │
                        ▼                                │
                    Humanizer ─► RenderedMessage ◄───────┘
```

- **Writer** (`studio.Writer`) — renders the spec into text via the LLM. The prompt
  (`prompts.py`) forbids inventing facts beyond the enumerated `claims` and forbids any
  AI/meta mention. Falls back to a template if the model returns nothing.
- **Critic** (`studio.Critic`) — deterministic gate: AI/meta leaks, prompt-injection
  phrasing, template artifacts, and the **last-mile link check** (the only URL allowed
  is the registered landing page). Triggers a bounded regenerate.
- **Humanizer** (`studio.Humanizer`) — strips AI-tells (stock openers, formal sign-offs
  on chat channels) so the text reads human. Pure Python, no model.
- **Pages** (`pages.py`) — inline-styled, script-free email HTML and landing pages, per
  the API's craft rules.

## Models

The `LLM` seam (`llm.py`) is OpenAI-compatible, so a local **vLLM** server is the
target — no OpenAI/Claude key. In MIRAGE the writer is the abliterated model and the
critic a smaller one; here they are just endpoints configured by env:

| Env | Default | Meaning |
|---|---|---|
| `MIRAGE_LLM_BASE` | `http://localhost:8000/v1` | OpenAI-compatible base URL |
| `MIRAGE_LLM_KEY` | `EMPTY` | ignored by vLLM |
| `MIRAGE_WRITER_MODEL` | `writer` | served model name for the writer |
| `MIRAGE_CRITIC_MODEL` | `critic` | served model name for the critic |

`FakeLLM` makes the whole studio testable offline (see `tests/test_content.py`).

## Run it in the loop

```bash
.venv/bin/python -m ooda_loop.run_live --renderer studio --target julius --max-contacts 3
```

Without `--renderer studio` the loop uses the neutral `FakeRenderer`.

## Status

- [x] LLM seam (OpenAI-compatible + fake)
- [x] Writer / Critic / Humanizer cascade
- [x] Landing-page + email HTML builders
- [x] `StudioRenderer` implements `Renderer`; 11 tests green
- [ ] Director stage (strategy refinement of the move-spec) — currently the Decider owns this
- [ ] Craft self-scoring loop against the 4 jury axes
- [ ] Model-backed critic (grounded claim re-extraction) on top of the deterministic one
- [ ] Wire to real abliterated weights via vLLM
