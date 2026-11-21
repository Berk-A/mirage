"""Live plumbing smoke test: drive one real practice session end-to-end.

This wires the REAL API client, reader and memory, but still uses the placeholder
`FakeDossierProvider` and `FakeRenderer`. So it verifies the *pipeline* — auth, send,
event parsing, suspicion/incident reading, the replay journal — NOT attack efficacy.
Real incidents need the research dossier and the content studio (not built yet), so
expect silence/low engagement from the neutral placeholder messages.

Keep `--max-contacts` small; practice sessions are unlimited but each costs touches.

    set -a; source .env; set +a
    .venv/bin/python -m ooda_loop.run_live --target julius --max-contacts 3
"""
from __future__ import annotations

import argparse
import os
import sys

from core.fakes import FakeDossierProvider, FakeGrounding, FakeRenderer
from ooda_loop.client import Revel8Client
from ooda_loop.decider import Decider
from ooda_loop.memory import ThreeTierMemory
from ooda_loop.orchestrator import OodaLoop
from ooda_loop.reader import ReactionReader


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live OODA pipeline smoke test.")
    p.add_argument("--target", default="julius", help="target id (julius/tom/robert)")
    p.add_argument("--scenario", default="practice")
    p.add_argument("--max-contacts", type=int, default=3)
    p.add_argument("--journal-dir", default="runs")
    args = p.parse_args(argv)

    if not os.getenv("REVEL8_API_KEY"):
        print("REVEL8_API_KEY not set. Run: set -a; source .env; set +a", file=sys.stderr)
        return 2

    loop = OodaLoop(
        client=Revel8Client(),
        reader=ReactionReader(),
        memory=ThreeTierMemory(path=args.journal_dir),
        dossiers=FakeDossierProvider(),   # placeholder until research lands
        renderer=FakeRenderer(),          # placeholder until the content studio lands
        decider=Decider(),
        grounding=FakeGrounding(default="n_live"),
    )

    print(f"Running up to {args.max_contacts} contact(s) against '{args.target}' "
          f"(scenario={args.scenario}) with placeholder renderer/dossier...\n")
    t = loop.run_session(args.target, scenario_id=args.scenario,
                         max_contacts=args.max_contacts)

    print(f"session={t.session_id}  contacts={t.contacts_used}  won={t.won}  "
          f"stop={t.stop_reason}")
    if t.incident:
        print(f"incident: {t.incident.objective.value} — {t.incident.evidence}")
    print("\n-- contacts --")
    for i, c in enumerate(t.contacts, 1):
        inc = c.incident.objective.value if c.incident else "-"
        print(f"{i}. {c.objective.value:11s} via {c.channel:16s} "
              f"suspicion={c.suspicion:.2f}  incident={inc}")
    print(f"\njournal: {len(t.journal)} records (also written under {args.journal_dir}/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
