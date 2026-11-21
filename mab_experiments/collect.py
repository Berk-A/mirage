"""Build a DPO training dataset from MIRAGE run logs.

Reads the gitignored `runs/` logs (harness `rows.jsonl` + OODA touch JSONL joined
to `summary.json`), applies the explicit target->archetype / hook-index->hook-type
/ sender->sender-type mappings the raw logs do not carry, scores every contact with
`reward.py`, builds disjoint high/low DPO preference pairs per archetype+objective,
and writes a conversational TRL JSONL plus a counts report.

The archetypes are the research dossiers' (`research/synthetic_kg.py`): the practice
founders are stand-ins for unseen scored targets, so the policy is keyed by archetype,
never by a person's identity.

    .venv/bin/python -m mab_experiments.collect \
        --runs /Users/alemdar/Projects/revel8/runs \
        --out runs/dpo_dataset

Both paths are gitignored; nothing here commits logs or datasets.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from core.models import Objective
from mab_experiments.data import Observation, load_observations, preference_pairs


# --- Explicit label mappings (the raw logs omit these) -------------------- #
# Founder id (OODA `to`) and harness folder name -> research archetype.
TARGET_ARCHETYPES: dict[str, str] = {
    "julius": "cofounder/sales",         # Julius Muth  (go-to-market)
    "tom": "cofounder/product",          # Tom Mueller  (product)
    "robert": "cto/technical",           # Robert Seilbeck (CTO)
    "live_julius": "cofounder/sales",    # harness sweep, all Lena->Julius
}
# Harness `hook_index` -> a hook-type label. Only index 0 is sent in the current
# harness logs (Julius' GTM speaker-slot hook); extend as new hooks are exercised.
HOOK_TYPES: dict[int, str] = {
    0: "event_invite",
}
# Sender display name (OODA `sender` / harness `sender_name`) -> sender-type label.
SENDER_TYPES: dict[str, str] = {
    "Lena Hofer": "external_event",      # event organiser persona (Julius)
    "Sofia Brenner": "external_partner", # partner/programme persona (Tom)
    "Daniel Krause": "it_support",       # IT/vendor persona (Robert)
}


def _reward_distribution(rewards: list[float]) -> dict:
    if not rewards:
        return {"n": 0}
    s = sorted(rewards)
    n = len(s)
    mean = sum(s) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    buckets = Counter()
    for r in rewards:
        if r < 0:
            buckets["<0"] += 1
        elif r == 0:
            buckets["0"] += 1
        elif r < 1:
            buckets["0..1"] += 1
        elif r < 5:
            buckets["1..5"] += 1
        else:
            buckets[">=5 (incident)"] += 1
    return {"n": n, "min": round(s[0], 3), "median": round(median, 3),
            "mean": round(mean, 3), "max": round(s[-1], 3), "buckets": dict(buckets)}


def summarize(observations: list[Observation], pairs, skipped: list[dict]) -> dict:
    by_arch = Counter(o.context for o in observations)
    by_obj = Counter(o.arm.objective.value for o in observations)
    by_channel = Counter(o.arm.channel for o in observations)
    unknown_tone = sum(o.arm.tone == "unknown" for o in observations)
    unknown_hook = sum(o.arm.hook_type == "unknown" for o in observations)
    unknown_sender = sum(o.arm.sender_type == "unknown" for o in observations)
    return {
        "observations": len(observations),
        "preference_pairs": len(pairs),
        "pairs_by_archetype": dict(Counter(p.context for p in pairs)),
        "observations_by_archetype": dict(by_arch),
        "observations_by_objective": dict(by_obj),
        "observations_by_channel": dict(by_channel),
        "unknown_labels": {"tone": unknown_tone, "hook_type": unknown_hook,
                           "sender_type": unknown_sender},
        "reward_distribution": _reward_distribution([o.reward for o in observations]),
        "skipped": dict(Counter(s["reason"] for s in skipped)),
        "skipped_total": len(skipped),
    }


def build(runs_dir: str | Path, out_dir: str | Path) -> dict:
    skipped: list[dict] = []
    observations = load_observations(
        runs_dir,
        target_archetypes=TARGET_ARCHETYPES,
        hook_types=HOOK_TYPES,
        sender_types=SENDER_TYPES,
        skipped=skipped,
    )
    pairs = preference_pairs(observations)
    report = summarize(observations, pairs, skipped)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset_path = out / "dpo.jsonl"
    with dataset_path.open("w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p.dpo_row(), ensure_ascii=False) + "\n")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["dataset_path"] = str(dataset_path)
    return report


def _print(report: dict) -> None:
    print(f"observations     : {report['observations']}")
    print(f"preference pairs : {report['preference_pairs']}  "
          f"{report['pairs_by_archetype']}")
    print(f"by archetype     : {report['observations_by_archetype']}")
    print(f"by objective     : {report['observations_by_objective']}")
    print(f"by channel       : {report['observations_by_channel']}")
    print(f"unknown labels   : {report['unknown_labels']}")
    print(f"reward dist      : {report['reward_distribution']}")
    print(f"skipped          : {report['skipped']} (total {report['skipped_total']})")
    print(f"dataset          : {report.get('dataset_path')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a DPO dataset from run logs.")
    ap.add_argument("--runs", default="runs/", help="runs/ directory to read (gitignored)")
    ap.add_argument("--out", default="runs/dpo_dataset", help="output dir (gitignored)")
    a = ap.parse_args(argv)
    report = build(a.runs, a.out)
    _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
