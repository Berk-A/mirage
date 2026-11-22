"""Run the OODA loop against a challenge scenario roster.

Drives `ooda_loop.OodaLoop` (Observe -> Orient -> Decide -> Act) through several touches in
one session per target, escalating objectives (disclosure -> action -> credentials) and
rotating channels, using the configured writer and optional public research. A
`RecordingClient` wraps the real `Revel8Client` so every touch's message body and the
persona's reply/events are logged to JSONL — so we can read exactly what was said and how
the target reacted.

    python -m experiments.run_ooda --scenario practice --provider real --max-contacts 5
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
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        value = v.strip()
        if value:
            os.environ.setdefault(k.strip(), value)


class RecordingClient:
    """Wraps a TargetClient; logs each send_message (body + events) to a JSONL. Every other
    method is delegated unchanged so the OODA loop behaves exactly as in production."""

    def __init__(self, inner, log_path: str, *, verbose: bool = False,
                 target: str = "") -> None:
        self.inner = inner
        self._log = open(log_path, "a", encoding="utf-8", errors="backslashreplace", newline="\n")
        self.touch = 0
        self.verbose = verbose
        self.target = target

    def _w(self, rec: dict) -> None:
        self._log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._log.flush()

    # -- live terminal transcript (what we write / what we get back) ---------- #
    @staticmethod
    def _wrap(text: str, indent: str = "     ") -> str:
        import textwrap
        text = (text or "").strip() or "(empty)"
        out = []
        for para in text.splitlines() or [""]:
            out.extend(textwrap.wrap(para, width=92, initial_indent=indent,
                                     subsequent_indent=indent) or [indent + ""])
        return "\n".join(out)

    def _show_message(self, *, channel, sender, sender_addr, subject, body, page, events):
        if not self.verbose:
            return
        who = f"{sender or '?'}" + (f" <{sender_addr}>" if sender_addr else "")
        print(f"\n┏━ touch {self.touch} · {self.target or '?'} · {channel} · {who}", flush=True)
        if subject:
            print(f"┃  subject: {subject}", flush=True)
        print("┃  ▶ WE WRITE:", flush=True)
        print(self._wrap(body, "┃     "), flush=True)
        if page is not None:
            fields = ",".join(getattr(page, "fields", ()) or ())
            print(f"┃     [+ landing page: {getattr(page, 'url', '')}  fields: {fields}]",
                  flush=True)
        replies = [e for e in events if (e.type.value == "reply" and (e.body or "").strip())]
        if replies:
            print("┃  ◀ THEY REPLY:", flush=True)
            for e in replies:
                print(self._wrap(e.body, "┃     "), flush=True)
        else:
            print("┃  ◀ (silence — no reply)", flush=True)
        other = [e for e in events if e.type.value != "reply"]
        if other:
            tags = []
            for e in other:
                f = ",".join(e.fields) if e.fields else ""
                tags.append(f"{e.type.value}" + (f"({f})" if f else ""))
            print(f"┃  ⚑ events: {'  '.join(tags)}", flush=True)
        print("┗" + "━" * 60, flush=True)

    def new_session(self, scenario_id: str = "practice"):
        s = self.inner.new_session(scenario_id)
        self._w({"kind": "session_start", "session_id": s.session_id, "scenario": scenario_id})
        return s

    def list_sessions(self):
        return self.inner.list_sessions()

    def list_channels(self):
        return self.inner.list_channels()

    def upload_asset(self, file_path):
        return self.inner.upload_asset(file_path)

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
            "sent_at": message.sent_at,
            "body": message.body,
            "body_len": len(message.body or ""),
            "has_page": message.page is not None,
            "events": [{"type": e.type.value, "channel": e.channel, "url": e.url,
                        "fields": list(e.fields), "values": dict(e.values),
                        "reply": (e.body or "")[:600]}
                       for e in res.events],
            "touches_used": res.touches_used,
        })
        self._show_message(channel=message.channel,
                           sender=getattr(message.sender, "name", None),
                           sender_addr=getattr(message.sender, "address", None),
                           subject=message.subject, body=message.body,
                           page=message.page, events=res.events)
        return res

    def start_conversation(self, session_id: str, *, to: str, channel: str, sender=None,
                           sent_at=None):
        result = self.inner.start_conversation(session_id, to=to, channel=channel,
                                               sender=sender, sent_at=sent_at)
        self._w({"kind": "conversation_start", "session_id": session_id,
                 "conversation_id": result.conversation_id, "to": to,
                 "channel": channel, "sent_at": sent_at,
                 "persona_says": result.persona_says})
        if self.verbose:
            print(f"\n┏━ live {channel} · {self.target or to} — conversation opens", flush=True)
            if result.persona_says:
                print("┃  ◀ THEY SAY:", flush=True)
                print(self._wrap(result.persona_says, "┃     "), flush=True)
            print("┗" + "━" * 60, flush=True)
        return result

    def say_turn(self, conversation_id: str, text: str, *, idempotency_key=None,
                 sent_at=None, attachments=None):
        result = self.inner.say_turn(conversation_id, text,
                                     idempotency_key=idempotency_key,
                                     sent_at=sent_at, attachments=attachments)
        self._w({"kind": "conversation_turn", "conversation_id": conversation_id,
                 "say": text, "sent_at": sent_at,
                 "persona_says": result.persona_says,
                 "events": [{"type": e.type.value, "url": e.url,
                             "fields": list(e.fields), "values": dict(e.values)}
                            for e in result.events]})
        if self.verbose:
            print("┃  ▶ WE SAY:", flush=True)
            print(self._wrap(text, "┃     "), flush=True)
            if result.persona_says:
                print("┃  ◀ THEY SAY:", flush=True)
                print(self._wrap(result.persona_says, "┃     "), flush=True)
            other = [e for e in result.events if e.type.value != "reply"]
            if other:
                print("┃  ⚑ events: " + "  ".join(
                    e.type.value + (f"({','.join(e.fields)})" if e.fields else "")
                    for e in other), flush=True)
        return result

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
        "facts": [{"predicate": f.predicate, "value": f.object_value,
                   "claim": f.canonical_claim, "source_url": f.source_url,
                   "observed_date": f.observed_date, "event_date": f.event_date,
                   "confidence": f.confidence} for f in d.facts],
        "gaps": list(d.gaps), "as_of": d.as_of,
        "diagnostics": dict(d.raw),
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Run MIRAGE against a challenge API scenario.")
    ap.add_argument("--scenario", default="practice",
                    help="scenario id currently visible through GET /scenarios")
    ap.add_argument("--targets", default=None,
                    help="comma-separated ids from that scenario; defaults to its visible roster")
    ap.add_argument("--max-contacts", type=int, default=None,
                    help="optional lower cap; never exceeds the scenario touch budget")
    ap.add_argument("--story-start", default=None,
                    help="optional timezone-aware ISO timestamp, e.g. 2026-11-23T09:14:00+01:00")
    ap.add_argument("--story-interval-minutes", type=int, default=60)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--provider", choices=("synthetic", "real"), default="real",
                    help="real = scenario-scoped public research; synthetic = practice stub")
    ap.add_argument("--cast", choices=("none", "audit", "vendor"), default="none",
                    help="multi-persona: run a coordinated cast (audit = auditor+coordinator; "
                         "vendor = security-ops+trust-&-safety) as the senders")
    ap.add_argument("--brain", choices=("model", "rule"), default="model",
                    help="model = ModelDirector + ModelCritic (abliterated); rule = deterministic")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="print a live transcript: each message we send and the reply/events we get")
    a = ap.parse_args(argv)

    if not os.environ.get("REVEL8_API_KEY"):
        print("REVEL8_API_KEY not set (source .env).")
        return 2
    if a.max_contacts is not None and a.max_contacts < 1:
        print("--max-contacts must be at least 1.")
        return 2
    if a.story_interval_minutes < 1:
        print("--story-interval-minutes must be at least 1.")
        return 2

    from content.studio import StudioRenderer
    from ooda_loop.client import Revel8Client
    from ooda_loop.decider import Decider
    from ooda_loop.memory import ThreeTierMemory
    from ooda_loop.orchestrator import OodaLoop
    from ooda_loop.reader import ReactionReader
    out = a.out_dir or f"runs/ooda_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)

    api = Revel8Client()
    scenarios = api.list_scenarios()
    scenario = next((row for row in scenarios if row.id == a.scenario), None)
    if scenario is None:
        print(f"Scenario {a.scenario!r} is not visible through the challenge API.")
        return 2
    if scenario.kind == "eval" and not scenario.open:
        print("The eval scenario is not open yet; no session was started.")
        return 2

    if a.provider == "real":
        from research.seeds import default_provider, seeds_from_scenario
        seeds = seeds_from_scenario(scenario)
        base_kg = default_provider(seeds=seeds)
        print("provider: REAL (live OSINT via GraphResearchProvider)")
    else:
        if a.scenario != "practice":
            print("The synthetic provider only contains practice data; use --provider real.")
            return 2
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

    # Scenario is the authority for who is in scope and the touch budget (eval is capped at 10).
    visible_ids = [t.id for t in scenario.targets]
    requested_targets = ([t.strip() for t in a.targets.split(",") if t.strip()]
                         if a.targets else visible_ids)
    if not requested_targets:
        print(f"Scenario {a.scenario!r} has no visible targets yet.")
        return 2
    unknown = sorted(set(requested_targets) - set(visible_ids))
    if unknown:
        print(f"Target ids are not in the visible scenario roster: {', '.join(unknown)}")
        return 2

    scenario_limit = scenario.touch_budget
    if scenario_limit is None:
        scenario_limit = 10 if scenario.kind == "eval" else 30
    if scenario.kind == "eval":
        scenario_limit = min(scenario_limit, 10)
    max_contacts = min(scenario_limit, a.max_contacts) if a.max_contacts else scenario_limit
    if a.max_contacts and max_contacts < a.max_contacts:
        print(f"Capping --max-contacts at the scenario limit ({max_contacts}).")

    targets = requested_targets
    results = []

    # Persistent cross-run ledger: survives across the 3 eval processes so the Director sees
    # what prior runs tried against each target and diversifies.
    from ooda_loop.ledger import StrategyLedger
    ledger = StrategyLedger()

    cast = None
    if a.cast != "none":
        from ooda_loop.personas import CASTS
        cast = CASTS[a.cast]()
        print(f"cast: {a.cast} — {', '.join(s.name for s in cast.senders)}")

    for tgt in targets:
        _dump_dossier(kg.get_dossier(tgt, scenario_id=a.scenario), f"{out}/{tgt}_dossier.json")
        rec = RecordingClient(api, f"{out}/{tgt}.jsonl", verbose=a.verbose, target=tgt)
        if a.verbose:
            print(f"\n{'='*64}\n=== {tgt} — research done, opening the campaign "
                  f"(budget {max_contacts} touches)\n{'='*64}", flush=True)
        loop = OodaLoop(client=rec, reader=ReactionReader(disclosure_grader=grader),
                        memory=ThreeTierMemory(), dossiers=kg, renderer=renderer,
                        decider=make_decider(), grounding=kg, ledger=ledger, cast=cast)
        t0 = time.time()
        tr = loop.run_session(
            tgt, scenario_id=a.scenario, max_contacts=max_contacts,
            story_start=a.story_start,
            story_interval_minutes=a.story_interval_minutes,
        )
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