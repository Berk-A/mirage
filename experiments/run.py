"""CLI for the experiment harness.

    # generation (no API calls): measure the cascade across the whole matrix, big N
    .venv/bin/python -m experiments.run --mode generation --limit 90

    # live (one practice session): send a capped, sampled subset and read reactions
    set -a; source .env; set +a
    .venv/bin/python -m experiments.run --mode live --target julius --limit 12 --sleep 1.5

Generation mode makes zero revel8 calls, so it is safe to run repeatedly at scale. Live
mode opens exactly one practice session per run, caps touches to stay well inside the
30-touch budget, and sleeps between sends to respect the 60 req/min limit. Only aggregate
stats and the output directory are printed — never any secret.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from experiments.form_factors import enumerate_factors
from experiments.harness import run_matrix, write_summary

# A practice session has a 30-touch budget; stay comfortably under it in live mode.
LIVE_TOUCH_CAP = 25
_VALID_TARGETS = ("julius", "tom", "robert")


# --------------------------------------------------------------------------- #
# Tiny stdlib .env loader (no external deps)
# --------------------------------------------------------------------------- #
def load_env(path: str = ".env") -> None:
    """Parse simple ``KEY=VALUE`` lines from ``path`` into ``os.environ`` without
    overwriting values already set. Ignores blanks, ``#`` comments and malformed lines,
    and strips one layer of surrounding quotes. No interpolation, no export parsing."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[len("export "):].strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


# --------------------------------------------------------------------------- #
# Dependency wiring
# --------------------------------------------------------------------------- #
def _build_dossier_provider():
    """The research knowledge graph. Delivered in parallel; imported lazily so the CLI
    still loads (and `--help` works) before that module exists."""
    from research.synthetic_kg import SyntheticKnowledgeGraph
    return SyntheticKnowledgeGraph()


def _build_renderer():
    from content.studio import StudioRenderer
    return StudioRenderer()


def _build_reader():
    from ooda_loop.reader import ReactionReader
    return ReactionReader()


def _build_client():
    from ooda_loop.client import Revel8Client
    return Revel8Client()


# --------------------------------------------------------------------------- #
# Printing (aggregate only; never secrets)
# --------------------------------------------------------------------------- #
def _print_summary(summary: dict, out_dir: str) -> None:
    overall = summary["overall"]
    print("\n== overall ==")
    print(f"  factors:              {overall.get('count', 0)}")
    rel = overall.get("reliability", {})
    if rel:
        print(
            "  reliability:          "
            + ", ".join(f"{k} {v:.2f}" for k, v in rel.items())
        )
    print(f"  mean regens:          {overall.get('mean_regens', 0):.2f}")
    print(f"  fell_back rate:       {overall.get('fell_back_rate', 0):.2f}")
    print(f"  render latency ms:    mean {overall.get('render_latency_ms_mean', 0):.1f}, "
          f"median {overall.get('render_latency_ms_median', 0):.1f}")
    print(f"  guard violation rate: {overall.get('guard_violation_rate', 0):.2f}")
    if overall.get("sent_count"):
        print(f"  sent:                 {overall['sent_count']}")
        print(f"  api error rate:       {overall.get('api_error_rate', 0):.2f}")
        print(f"  incident rate:        {overall.get('incident_rate', 0):.2f}")
        print(f"  suspicion mean:       {overall.get('suspicion_mean', 0):.2f}")
        er = overall.get("event_rates", {})
        if er:
            print("  event rates:          "
                  + ", ".join(f"{k} {v:.2f}" for k, v in er.items()))
    print(f"\noutput: {out_dir}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MIRAGE form-factor experiment harness.")
    p.add_argument("--mode", choices=("generation", "live"), default="generation",
                   help="generation = no API calls (default); live = send one session")
    p.add_argument("--target", choices=_VALID_TARGETS, default="julius")
    p.add_argument("--limit", type=int, default=None,
                   help="cap the number of factors (sampled when --seed is given)")
    p.add_argument("--out-dir", default=None,
                   help="output dir (default: runs/<timestamp>)")
    p.add_argument("--seed", type=int, default=None,
                   help="shuffle the matrix reproducibly before applying --limit")
    p.add_argument("--sleep", type=float, default=1.0,
                   help="seconds between live sends (live mode only)")
    args = p.parse_args(argv)

    load_env()

    out_dir = args.out_dir or os.path.join(
        "runs", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    send = args.mode == "live"

    limit = args.limit
    if send:
        # Never let a live run exceed the touch budget, whatever --limit asked for.
        limit = min(limit, LIVE_TOUCH_CAP) if limit is not None else LIVE_TOUCH_CAP

    factors = enumerate_factors(limit=limit, seed=args.seed)

    try:
        dossier_provider = _build_dossier_provider()
        renderer = _build_renderer()
        reader = _build_reader()
    except Exception as exc:  # noqa: BLE001 - a missing sibling module is a clear message
        print(f"Could not wire dependencies: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("(research.synthetic_kg / content.studio must be importable.)", file=sys.stderr)
        return 2

    client = None
    if send:
        if not os.getenv("REVEL8_API_KEY"):
            print("REVEL8_API_KEY not set. Add it to .env or the environment.",
                  file=sys.stderr)
            return 2
        client = _build_client()

    print(f"mode={args.mode} target={args.target} factors={len(factors)} "
          f"seed={args.seed} out={out_dir}")

    rows = run_matrix(
        factors,
        dossier_provider=dossier_provider,
        target_id=args.target,
        renderer=renderer,
        reader=reader,
        client=client,
        send=send,
        out_dir=out_dir,
        sleep_s=args.sleep,
        logger=(lambda m: print(m)) if send else None,
    )

    summary = write_summary(rows, out_dir)
    _print_summary(summary, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
