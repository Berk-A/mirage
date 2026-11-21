# Building the MAB + self-play + LoRA pipeline

How the learning side is built and operated, and **why it runs on a separate AMD Radeon
Cloud account** from the live writer. Read `README.md` (the bandit idea) and
`TRAINING_PLAN.md` (the DPO/QLoRA method) alongside this.

## The learning loop

```
            ┌─────────────────────── self-play ───────────────────────┐
            │                                                          │
  bandit.select(archetype) ─► MoveSpec ─► writer ─► revel8 API ─► events
            ▲                                                          │
            │                                                          ▼
   bandit.update(ctx,arm,reward) ◄── reward(record) ◄── Reaction Reader (Signals)
            │                                                          │
            │                                                   runs/*.jsonl (logs)
            ▼                                                          │
     playbook() ──► seeds scored runs            data.py ─────────────┘
                                                   │
                           load_observations ──────┤──► bandit observations
                           preference_pairs ───────┘──► DPO pairs ─► QLoRA/DPO ─► LoRA adapter ─► writer
```

Two uses of the same signal: the **bandit** learns online which pretext converts per
archetype (and exports a `playbook()` to seed Sunday's runs); **DPO** bakes the winners
into the writer's weights offline.

## Components (already on `main`)

- `bandit.py` — `ContextualBandit` (Gaussian Thompson sampling, per-**archetype**
  posteriors over `Arm(objective, channel, tone, hook_type, sender_type)`): `select`,
  `update`/`update_outcome`, `playbook`.
- `reward.py` — `reward(RewardRecord)`: rubric-shaped (incident +10, speed +3/contacts,
  on-topic +2, reply +0.5, link +0.3, refusal −1, suspicion −2×p, wrong-fact −2/claim).
- `data.py` — `load_observations(runs/)` parses the harness `rows.jsonl` and the
  `run_ooda` touch JSONL (joined to `summary.json`) into `Observation`s; `preference_pairs`
  builds disjoint high/low DPO pairs per archetype+objective; `.dpo_row()` → TRL format.
- Upstream (also on `main`): `experiments/` (form-factor harness + `run_ooda`) produce the
  logs; `ooda_loop` + `content` + `research` produce the contacts and the `archetype`.

## Why a separate Radeon account for training

**Serving and training are different workloads and must not share one account/GPU:**

| | Serving account (have it) | Training account (new) |
|---|---|---|
| Job | the live abliterated writer (vLLM Model API) | self-play at scale + DPO/QLoRA |
| GPU | 1 × 48 GB, must stay up, latency-sensitive | 2–4 GPU, bursty, long-running |
| Points | lean, must survive the scored window | heavy; isolated so it can't starve serving |
| Lifecycle | short auto-delete, always-on during runs | long auto-delete (hours–days) |

1. **Budget isolation** — a long DPO job or a self-play burst can exhaust points; that
   must never take the live writer (and a scored run) down with it.
2. **Resource isolation** — a training job + self-play rollouts would contend for the
   single serving GPU's VRAM and throughput and stall the writer mid-conversation.
3. **Lifecycle** — training wants a bigger, longer-lived Notebook instance; serving wants
   a lean, always-up 1-GPU Model API. Different shapes, different accounts.
4. **Blast radius** — an experimental/crashing training instance never touches serving.

### Setting up the training account

1. New AMD Radeon Cloud account (or sub-account) with its own point balance.
2. Deploy a **Notebook** (JupyterLab) instance, **Base** image (ROCm 7.2.1 · PyTorch ·
   vLLM), **2–4 GPU** if available (QLoRA of the 14B fits 1×48 GB, but self-play +
   training wants headroom), **auto-delete 1–3 days** (training runs long).
3. Model source **ModelScope** (in-region, reliable): `huihui-ai/Qwen2.5-14B-Instruct-abliterated`.
   Mount it read-only at `/models`, or stand up a second Model API here for self-play.
4. `pip install -e ".[training]"` (TRL, PEFT, Datasets, Transformers, Accelerate,
   bitsandbytes). **ROCm caveat:** bitsandbytes 4-bit may need a ROCm build or a ROCm
   quantizer instead — validate a **one-batch smoke run + memory check** before the full
   DPO job (see `TRAINING_PLAN.md`).

### Data flow between the two accounts

```
serving acct ──(runs/*.jsonl, logs; gitignored)──► transfer (bucket/scp) ──► training acct
training acct ──(DPO/QLoRA)──► LoRA adapter ──► transfer ──► serving acct: vLLM --lora-modules (or merge)
training acct ──(bandit.playbook())──► seeds the Decider's angle selection on scored runs
```

Never commit `runs/` or the adapter (gitignored); move them as artifacts. Keys stay in
each account's own `.env`.

## Build order

1. **Wire the bandit into the loop** — replace the Decider's `_pick_channel`/`_pick_hook`/
   tactic seams with `bandit.select(dossier.archetype) -> Arm -> MoveSpec`, and call
   `bandit.update_outcome(...)` from the OODA loop's Orient step. (The seams were built
   for exactly this; `ooda_loop/decider.py`.)
2. **Collect** — run `experiments/run_ooda.py` + the harness (serving acct) and/or the
   shadow-twin simulator (training acct) to build `runs/` logs. Respect revel8 limits
   (60 req/min, 60 new practice sessions/hr) — the **simulator is the volume source**.
3. **Build the dataset** — `load_observations(runs/)` + `preference_pairs` → DPO rows.
4. **Train** — QLoRA/DPO on the training account per `TRAINING_PLAN.md`.
5. **Evaluate + redeploy** — held-out incident rate / mean reward; ship the adapter to the
   serving writer and the `playbook()` to seed scored runs.
6. **Iterate.**

## Guardrails

- The reward is a **proxy** for the hidden grader — harden the internal grader (where two
  grader families disagree, hand-label) before trusting self-play labels.
- Split train/eval by **target or session** so a held-out twin never leaks into training.
- Reward penalises wrong facts and suspicion — keep provenance (the research dossier) and
  the reply-aware loop's "never invent facts" rule in force.
