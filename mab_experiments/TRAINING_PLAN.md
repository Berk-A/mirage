# Self-play and writer adaptation

## Data and scoring

Run the OODA runner and form-factor harness against the consented simulator. Keep
`runs/` local and gitignored. Load JSONL with `load_observations` and explicit
target→archetype, hook-index→hook-type and sender→sender-type mappings. The raw logs
do not contain all those labels. Join OODA touches to `summary.json` by target and
touch number. Skip generation-only harness rows and unlabeled OODA touches. Add
`archetype`, `objective`, `tone`, `hook_type`, `sender_type`, `on_topic`, and
`wrong_facts` to future logs when known; the API does not provide the last two.
Unknown labels stay unknown. Do not treat a link open as a proven incident or
infer the target's private topic from engagement.

Score each contact with `reward.py`: incident +10 for any of the three objectives;
speed +3 / contacts to the *first* incident; verified topic +2; reply +0.5; link
opened +0.3; refusal -1; suspicion -2×probability; wrong fact -2 per claim.
This is a proxy for the 25 Results + 10 Targeting points, not the actual hidden
grader. Inspect false positives in the OODA reaction reader before trusting labels.

## Preference construction

Split by **target or session before pairing**, so variants of a held-out twin do
not leak into train. Within the training set, group by archetype + objective,
sort by the shared reward and pair different messages with a gap of at least 1.
Keep a bounded number of disjoint high/low pairs per group to avoid quadratic
replication of a small sample. Prefer same channel and comparable state when
metadata permits; the present logs lack full state. The pair prompt must include
only state common to chosen and rejected. Preserve source IDs and inspect the
pair for factual mismatches. Export conversational `prompt`, `chosen`, `rejected`
lists of `{role, content}`; do not include the measured reward in model input.

## QLoRA/DPO run

Base writer: `huihui-ai/Qwen2.5-14B-Instruct-abliterated`, already served by vLLM.
Train adapters offline using the optional `.[training]` extra (TRL, PEFT,
Datasets, Transformers, Accelerate, bitsandbytes). Apply the tokenizer's own chat
template to the conversational pair format. Start with 4-bit NF4 QLoRA,
BF16 compute if supported, LoRA rank 16, alpha 32 on attention and MLP linear
layers, dropout 0.05. DPO beta 0.1, learning rate 5e-6, 1–2 epochs, effective
batch 16 via accumulation; cap sequence length to fit memory. Freeze a reference
adapter or use a precomputed reference log probability. The 48 GB Radeon may need
ROCm-supported quantization instead of bitsandbytes; validate a one-batch smoke
run and memory before committing to the full DPO job. No heavy training package
is imported by the loader, reward or bandit tests.

Illustrative **12 GPU-hour budget**: 6 h simulator self-play and labeling,
4 h DPO training plus one-batch validation, 2 h held-back evaluation and
rollback/redeploy checks. API practice rate limits may dominate self-play;
reserve genuinely held-out targets and sessions. If fewer than dozens of
reliable, distinct pairs survive, keep the base writer and use the bandit alone.

## Evaluate and redeploy

Loop: self-play → label → form pairs → DPO → evaluate → redeploy adapter to vLLM.
Compare base and adapter under the same frozen policy and touch budget on
held-out sessions: incident rate, mean reward, first-incident contacts, verified
topic rate, wrong-fact count and suspicion. Report confidence intervals by
session, not by duplicated message. Redeploy only if held-out incident rate and
mean reward improve without worse factual errors; preserve the base adapter for
rollback. Export `ContextualBandit.playbook()` posterior-mean arms by archetype
to seed scoring runs; never key policy by a practice target's identity.
