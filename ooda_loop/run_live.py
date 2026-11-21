"""Live plumbing smoke test: drive one real practice session end-to-end.

Defaults to the cheap transport check — real API client/reader/memory, but a
`FakeDossierProvider` + `FakeRenderer` — so it verifies the *pipeline* (auth, send,
event parsing, suspicion/incident reading, the replay journal) without model or crawl
cost. The research KG and the content studio DO exist: pass `--provider real` to wire
the live OSINT `GraphResearchProvider`, and `--renderer studio` for the abliterated
writer (needs a served model at MIRAGE_LLM_BASE). For the full real run with the
recording/caching harness, prefer `experiments/run_ooda.py --provider real`.

Keep `--max-contacts` small; practice sessions are unlimited but each costs touches.

    set -a; source .env; set +a
    .venv/bin/python -m ooda_loop.run_live --target julius --max-contacts 3
    .venv/bin/python -m ooda_loop.run_live --target tom --provider real --renderer studio
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


def _build_renderer(kind: str):
    """`fake` = neutral placeholder text (no model). `studio` = the real Content studio
    (needs a served OpenAI-compatible model at MIRAGE_LLM_BASE, e.g. vLLM)."""
    if kind == "studio":
        from content.llm import OpenAICompatLLM
        from content.studio import StudioRenderer
        return StudioRenderer(OpenAICompatLLM())
    return FakeRenderer()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live OODA pipeline smoke test.")
    p.add_argument("--target", default="julius", help="target id (julius/tom/robert)")
    p.add_argument("--scenario", default="practice")
    p.add_argument("--max-contacts", type=int, default=3)
    p.add_argument("--journal-dir", default="runs")
    p.add_argument("--renderer", choices=("fake", "studio"), default="fake",
                   help="'studio' uses the real Content studio (needs a served model)")
    p.add_argument("--provider", choices=("fake", "real"), default="fake",
                   help="'real' wires the live OSINT GraphResearchProvider + its grounding")
    args = p.parse_args(argv)

    if not os.getenv("REVEL8_API_KEY"):
        print("REVEL8_API_KEY not set. Run: set -a; source .env; set +a", file=sys.stderr)
        return 2

    if args.provider == "real":
        from research.seeds import default_provider
        prov = default_provider()            # GraphResearchProvider: Dossier + Grounding
        dossiers, grounding = prov, prov
    else:
        dossiers, grounding = FakeDossierProvider(), FakeGrounding(default="n_live")

    loop = OodaLoop(
        client=Revel8Client(),
        reader=ReactionReader(),
        memory=ThreeTierMemory(path=args.journal_dir),
        dossiers=dossiers,
        renderer=_build_renderer(args.renderer),
        decider=Decider(),
        grounding=grounding,
    )

    print(f"Running up to {args.max_contacts} contact(s) against '{args.target}' "
          f"(scenario={args.scenario}, renderer={args.renderer}, provider={args.provider})...\n")
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
