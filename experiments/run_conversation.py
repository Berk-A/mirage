"""Live conversation runs: the Director drives a multi-turn dialogue per target (the
highest-leverage win vehicle — one touch, up to N adaptive turns). This is the system
entrypoint that replaces the ad-hoc hunt scripts: the real `ConversationLoop` wired to the
real brain (model Director + model Critic), a strict LLM disclosure judge, and the
LLM-researched dossiers. Every turn (our line, the persona's reply, the running suspicion,
and any incident) is logged to JSONL and printed as a readable trace.

    set -a; source .env; set +a
    .venv/bin/python -m experiments.run_conversation --targets robert,tom,julius \
        --channel live_chat --max-turns 10
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib


def load_env(path: str = ".env") -> None:
    p = pathlib.Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def build_loop():
    """Assemble the real ConversationLoop: live client, model brain + critic, strict judge,
    LLM-researched dossiers."""
    from content.critic import ModelCritic
    from content.llm import OpenAICompatLLM
    from content.studio import StudioRenderer
    from ooda_loop.client import Revel8Client
    from ooda_loop.conversation import ConversationLoop
    from ooda_loop.director import ModelDirector
    from ooda_loop.grading import HeuristicDisclosureGrader, LLMDisclosureGrader
    from ooda_loop.ledger import StrategyLedger
    from ooda_loop.reader import ReactionReader
    from research.seeds import default_provider

    llm = OpenAICompatLLM()
    # A strict served-model disclosure judge (heuristic fallback) — a reply only wins when the
    # model agrees it volunteered a non-public internal fact (refusals/public info excluded).
    grader = LLMDisclosureGrader(llm, fallback=HeuristicDisclosureGrader())
    renderer = StudioRenderer(llm=llm, model_critic=ModelCritic(llm))
    director = ModelDirector(llm=llm)
    return ConversationLoop(
        client=Revel8Client(),
        reader=ReactionReader(disclosure_grader=grader),
        dossiers=default_provider(),
        renderer=renderer,
        director=director,
        ledger=StrategyLedger(),
    )


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--targets", default="robert,tom,julius",
                    help="comma-separated target ids")
    ap.add_argument("--channel", default="live_chat")
    ap.add_argument("--max-turns", type=int, default=10)
    ap.add_argument("--scenario", default="practice")
    # Override the opening identity to try a specific LEVER (a prospective customer, a
    # journalist, a recruiter, ...). Name-only + a concrete role in the rationale keeps it
    # guard-safe (no domain collision / real-org void) and stops the Writer confabulating one.
    ap.add_argument("--sender-name", default=None,
                    help="opening identity name (applied to every target this run)")
    ap.add_argument("--sender-rationale", default=None,
                    help="who that identity is — a concrete external role the Writer stays in")
    args = ap.parse_args()

    lever_sender = None
    if args.sender_name:
        from core.models import Sender
        lever_sender = Sender(name=args.sender_name, address="",
                              rationale=args.sender_rationale or "")

    runs = pathlib.Path("runs")
    runs.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = runs / f"conversation_{stamp}.jsonl"
    loop = build_loop()

    from research.seeds import SEEDS_BY_ID

    with open(log_path, "a") as log:
        for target in [t.strip() for t in args.targets.split(",") if t.strip()]:
            print(f"\n{'='*70}\n{target.upper()} — {args.channel}, up to {args.max_turns} turns\n{'='*70}")
            # Pass the target's real company so the loop refuses to open as an insider-lookalike
            # (a spoof of the target's OWN domain) — the identity a security-aware target spots.
            seed = SEEDS_BY_ID.get(target)
            t = loop.run(target, scenario_id=args.scenario, channel=args.channel,
                         max_turns=args.max_turns, sender=lever_sender,
                         target_company=(seed.company if seed else None))
            for i, turn in enumerate(t.turns):
                print(f"\n  [turn {i} | suspicion {turn.suspicion:.2f}]")
                if turn.reasoning:
                    print(f"  director: {turn.reasoning}")
                print(f"  US:   {turn.our_line}")
                print(f"  THEM: {turn.persona_says or '(silence)'}")
                if turn.incident is not None:
                    print(f"  >>> INCIDENT: {turn.incident.objective.value} — {turn.incident.evidence}")
            verdict = (f"INCIDENT ({t.incident.objective.value})" if t.won
                       else f"no incident [{t.stop_reason}]")
            print(f"\n  == {target}: {verdict} after {t.turns_used} turns ==")
            log.write(json.dumps({
                "target": target, "channel": t.channel, "sender": t.sender,
                "conversation_id": t.conversation_id, "stop_reason": t.stop_reason,
                "turns_used": t.turns_used, "won": t.won,
                "incident": (t.incident.objective.value if t.won else None),
                "turns": [{"us": tn.our_line, "them": tn.persona_says,
                           "suspicion": tn.suspicion, "reasoning": tn.reasoning,
                           "incident": (tn.incident.objective.value if tn.incident else None)}
                          for tn in t.turns],
            }, ensure_ascii=False) + "\n")
    print(f"\nlogged → {log_path}")


if __name__ == "__main__":
    main()
