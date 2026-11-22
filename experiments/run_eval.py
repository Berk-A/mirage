"""One command to participate in an eval run (or a practice e2e).

The scored eval is up to 3 tries of 10 touches per target. This wrapper runs the full MIRAGE
agent (model brain + transactional incident engine) against the OPEN eval scenario, once per
try, writing the run artifacts the portal reads. The persistent StrategyLedger carries across
tries so each one deliberately varies strategy/persona/world.

    scripts/eval.sh                    # one eval try against the whole eval roster
    scripts/eval.sh --tries 3          # the full 3-try eval
    scripts/eval.sh --scenario practice --targets julius   # a practice e2e, same engine

Everything after the known flags is passed straight through to experiments.run_ooda.
"""
from __future__ import annotations

import argparse
import sys

from experiments import run_ooda


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(description="Run an eval try (or a practice e2e).")
    ap.add_argument("--tries", type=int, default=1,
                    help="how many back-to-back sessions to run (the eval allows up to 3)")
    args, passthrough = ap.parse_known_args(argv)

    # Default to the eval scenario; honour an explicit --scenario for practice e2e.
    base = list(passthrough)
    if not any(a == "--scenario" for a in passthrough):
        base = ["--scenario", "eval", *passthrough]
    scenario = base[base.index("--scenario") + 1] if "--scenario" in base else "eval"

    worst_rc = 0
    for i in range(max(1, args.tries)):
        print(f"\n{'#' * 64}\n#  MIRAGE {scenario.upper()} — try {i + 1}/{args.tries} "
              f"(model brain + transactional engine)\n{'#' * 64}", flush=True)
        rc = run_ooda.main(base)
        worst_rc = rc or worst_rc
        if rc == 2:
            # run_ooda already printed WHY (eval not open, no roster, bad targets): stop early,
            # a second try would hit the same wall.
            print("\n[run_eval] stopping: the scenario is not runnable right now (see above).",
                  flush=True)
            break
    return worst_rc


if __name__ == "__main__":
    raise SystemExit(main())
