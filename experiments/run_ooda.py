"""Multi-touch OODA live run: the full agent loop vs the practice founders.

Drives `ooda_loop.OodaLoop` (Observe -> Orient -> Decide -> Act) through several touches in
one session per target, escalating objectives (disclosure -> action -> credentials) and
rotating channels, against the live abliterated writer, using the synthetic dossier. A
`RecordingClient` wraps the real `Revel8Client` so every touch's message body and the
persona's reply/events are logged to JSONL — so we can read exactly what was said and how
the target reacted.

    set -a; source .env; set +a
    .venv/bin/python -m experiments.run_ooda --targets julius,tom,robert --max-contacts 12
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import time


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


class RecordingClient:
    """Wraps a TargetClient; logs each send_message (body + events) to a JSONL. Every other
    method is delegated unchanged so the OODA loop behaves exactly as in production."""

    def __init__(self, inner, log_path: str) -> None:
        self.inner = inner
        self._log = open(log_path, "a")
        self.touch = 0

    def _w(self, rec: dict) -> None:
        self._log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._log.flush()

    def new_session(self, scenario_id: str = "practice"):
        s = self.inner.new_session(scenario_id)
        self._w({"kind": "session_start", "session_id": s.session_id, "scenario": scenario_id})
        return s

    def get_session(self, session_id: str):
        return self.inner.get_session(session_id)

    def end_session(self, session_id: str):
        return self.inner.end_session(session_id)

    def register_page(self, session_id: str, page):
        pid = self.inner.register_page(session_id, page)
        self._w({"kind": "page", "session_id": session_id, "url": page.url,
                 "title": page.title, "fields": list(page.fields), "page_id": pid})
        return pid

    def send_message(self, session_id: str, message, *, to: str, idempotency_key=None):
        self.touch += 1
        res = self.inner.send_message(session_id, message, to=to,
                                      idempotency_key=idempotency_key)
        self._w({
            "kind": "touch", "n": self.touch, "session_id": session_id, "to": to,
            "channel": message.channel,
            "sender": getattr(message.sender, "name", None),
            "sender_addr": getattr(message.sender, "address", None),
            "subject": message.subject,
            "body": message.body,
            "body_len": len(message.body or ""),
            "has_page": message.page is not None,
            "events": [{"type": e.type.value, "channel": e.channel, "url": e.url,
                        "fields": list(e.fields), "reply": (e.body or "")[:600]}
                       for e in res.events],
            "touches_used": res.touches_used,
        })
        return res

    def start_conversation(self, session_id: str, *, to: str, channel: str, sender=None):
        return self.inner.start_conversation(session_id, to=to, channel=channel, sender=sender)

    def say_turn(self, conversation_id: str, text: str, *, idempotency_key=None):
        return self.inner.say_turn(conversation_id, text, idempotency_key=idempotency_key)

    def end_conversation(self, conversation_id: str):
        return self.inner.end_conversation(conversation_id)

    def get_events(self, session_id: str):
        return self.inner.get_events(session_id)

    def close(self) -> None:
        self._log.close()


class _CachingProvider:
    """Memoizes get_dossier so a (possibly slow, live-OSINT) dossier is built once per
    target and reused as both the dossier source and the grounding source."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self._cache: dict = {}

    def get_dossier(self, target_id: str, *, scenario_id: str = "practice"):
        if target_id not in self._cache:
            self._cache[target_id] = self.inner.get_dossier(
                target_id, scenario_id=scenario_id)
        return self._cache[target_id]

    def verify(self, claim_text: str, *, target_id: str):
        return self.inner.verify(claim_text, target_id=target_id)


def _dump_dossier(d, path: str) -> None:
    """Serialize a Dossier (the research/knowledge-graph stage) for the viewer."""
    rec = {
        "target_id": d.target_id, "display_name": d.display_name, "role": d.role,
        "archetype": d.archetype,
        "hooks": [{"topic": h.topic, "detail": h.detail, "source_url": h.source_url,
                   "date": h.date, "confidence": h.confidence} for h in d.hooks],
        "senders": [{"name": s.name, "address": s.address, "rationale": s.rationale}
                    for s in d.senders],
        "vendors": [{"name": v.name, "login_url": v.login_url} for v in d.vendors],
    }
    with open(path, "w") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Multi-touch OODA live run vs the founders.")
    ap.add_argument("--targets", default="julius,tom,robert")
    ap.add_argument("--max-contacts", type=int, default=12)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--provider", choices=("synthetic", "real"), default="synthetic",
                    help="real = live OSINT GraphResearchProvider; synthetic = stub")
    ap.add_argument("--brain", choices=("model", "rule"), default="model",
                    help="model = ModelDirector + ModelCritic (abliterated); rule = deterministic")
    a = ap.parse_args(argv)

    if not os.environ.get("REVEL8_API_KEY"):
        print("REVEL8_API_KEY not set (source .env).")
        return 2

    from content.studio import StudioRenderer
    from ooda_loop.client import Revel8Client
    from ooda_loop.decider import Decider
    from ooda_loop.memory import ThreeTierMemory
    from ooda_loop.orchestrator import OodaLoop
    from ooda_loop.reader import ReactionReader
    out = a.out_dir or f"runs/ooda_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)

    if a.provider == "real":
        from research.seeds import default_provider
        base_kg = default_provider()        # live OSINT -> GraphResearchProvider
        print("provider: REAL (live OSINT via GraphResearchProvider)")
    else:
        from research.synthetic_kg import SyntheticKnowledgeGraph
        base_kg = SyntheticKnowledgeGraph()
        print("provider: synthetic stub")
    from content.llm import OpenAICompatLLM
    from ooda_loop.grading import LLMDisclosureGrader

    llm = OpenAICompatLLM()                  # one abliterated endpoint for every model role
    kg = _CachingProvider(base_kg)          # dossier built once per target, reused
    grader = LLMDisclosureGrader(llm)        # model judge for disclosure (no event)

    if a.brain == "model":
        from content.critic import ModelCritic
        from ooda_loop.director import ModelDirector
        renderer = StudioRenderer(llm, model_critic=ModelCritic(llm))
        make_decider = lambda: ModelDirector(llm, fallback=Decider())  # noqa: E731
        print("brain: MODEL (Director + model Critic + abliterated Writer)")
    else:
        renderer = StudioRenderer(llm)
        make_decider = Decider
        print("brain: RULE (deterministic decider + critic)")

    targets = [t.strip() for t in a.targets.split(",") if t.strip()]
    results = []

    for tgt in targets:
        _dump_dossier(kg.get_dossier(tgt), f"{out}/{tgt}_dossier.json")  # research/KG stage
        rec = RecordingClient(Revel8Client(), f"{out}/{tgt}.jsonl")
        loop = OodaLoop(client=rec, reader=ReactionReader(disclosure_grader=grader),
                        memory=ThreeTierMemory(), dossiers=kg, renderer=renderer,
                        decider=make_decider(), grounding=kg)
        t0 = time.time()
        tr = loop.run_session(tgt, max_contacts=a.max_contacts)
        dt = time.time() - t0
        rec.close()
        row = {
            "target": tgt, "session": tr.session_id, "contacts": tr.contacts_used,
            "won": tr.won,
            "incident": tr.incident.objective.value if tr.incident else None,
            "stop_reason": tr.stop_reason, "seconds": round(dt, 1),
            "touches": [{"objective": c.objective.value, "channel": c.channel,
                         "sender": c.sender,
                         "incident": c.incident.objective.value if c.incident else None,
                         "suspicion": round(c.suspicion, 2)} for c in tr.contacts],
        }
        results.append(row)
        print(f"[{tgt}] contacts={tr.contacts_used} won={tr.won} "
              f"incident={row['incident']} stop={tr.stop_reason} ({dt:.0f}s)")
        for i, c in enumerate(tr.contacts, 1):
            inc = c.incident.objective.value if c.incident else "-"
            print(f"   {i}. {c.objective.value:11s} {c.channel:16s} "
                  f"susp={c.suspicion:.2f} inc={inc}")

    json.dump(results, open(f"{out}/summary.json", "w"), indent=2)
    won = sum(1 for r in results if r["won"])
    print(f"\n=== OODA multi-touch: {won}/{len(results)} sessions reached an incident; "
          f"per-touch logs + replies in {out}/ ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
