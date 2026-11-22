"""Drive a controlled, hook-grounded live campaign against the revel8 practice API.

Authorized sandbox: the targets are AI twins in a simulation; nothing reaches a real
person (docs/target-api.md). This runner executes a plan JSON of touches in one session,
registers landing pages, sets story time, grades every reaction with the API-grounded
`confirmed_incident`, logs full reactions, and stops on a real win. It persists the
session id so a follow-up plan can continue the same thread (the person remembers it).

    set -a; source /Users/alemdar/Projects/revel8/.env; set +a
    .venv/bin/python -m experiments.live_campaign path/to/plan.json

Plan JSON:
{
  "scenario": "practice",            # or "session_id": "s_..." to continue a thread
  "out": "runs/campaign_x",          # optional; default runs/campaign_<ts>
  "steps": [
    {"to":"tom","channel":"email","from":{"name":"..","address":".."},
     "subject":"..","body":"..","sent_at":"2026-11-23T09:14:00+01:00",
     "attachments":[{"filename":"x.pdf"}],
     "page":{"url":"https://..","title":"..","fields":["email","password"],"text":".."}}
  ]
}
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import uuid

import requests

from mab_experiments.grading import confirmed_incident


def _api() -> tuple[str, dict]:
    base = os.environ.get("REVEL8_API_BASE")
    key = os.environ.get("REVEL8_API_KEY")
    if not base or not key:
        raise SystemExit("set REVEL8_API_BASE and REVEL8_API_KEY (source .env)")
    return base.rstrip("/"), {"Authorization": f"Bearer {key}"}


def new_session(scenario: str = "practice") -> str:
    base, h = _api()
    r = requests.post(f"{base}/sessions", headers=h,
                      json={"scenario_id": scenario}, timeout=30)
    r.raise_for_status()
    return r.json()["session_id"]


def register_page(sid: str, page: dict) -> str:
    base, h = _api()
    r = requests.post(f"{base}/sessions/{sid}/pages", headers=h, json=page, timeout=30)
    r.raise_for_status()
    return r.json().get("page_id", "")


def send(sid: str, step: dict) -> dict:
    base, h = _api()
    payload = {"to": step["to"], "channel": step["channel"], "body": step["body"]}
    for k in ("from", "subject", "attachments", "sent_at"):
        if step.get(k) is not None:
            payload[k] = step[k]
    key = str(uuid.uuid4())
    r = requests.post(f"{base}/sessions/{sid}/messages",
                      headers={**h, "Idempotency-Key": key}, json=payload, timeout=120)
    if r.status_code >= 400:
        raise SystemExit(f"{r.status_code}: {r.text[:400]}")
    return r.json()


def run(plan_path: str) -> str:
    plan = json.loads(pathlib.Path(plan_path).read_text())
    sid = plan.get("session_id") or new_session(plan.get("scenario", "practice"))
    target = plan["steps"][0]["to"]
    outdir = pathlib.Path(plan.get("out")
                          or f"runs/campaign_{datetime.datetime.now():%Y%m%d_%H%M%S}")
    outdir.mkdir(parents=True, exist_ok=True)
    log = open(outdir / f"{target}.jsonl", "a", encoding="utf-8")
    print(f"session={sid}  target={target}  out={outdir}")

    win = None
    for i, step in enumerate(plan["steps"], 1):
        if step.get("page"):
            step["_page_id"] = register_page(sid, step["page"])
            print(f"  registered page {step['_page_id']} {step['page']['url']}")
        res = send(sid, step)
        events = res.get("events", [])
        inc = confirmed_incident(events)
        log.write(json.dumps({
            "kind": "touch", "n": i, "session_id": sid, "to": target,
            "channel": step["channel"], "sender": (step.get("from") or {}).get("name"),
            "subject": step.get("subject"), "body": step["body"],
            "has_page": bool(step.get("page")),
            "events": events, "touches_used": res.get("touches_used"),
            "incident": inc.value if inc else None,
        }, ensure_ascii=False) + "\n")
        log.flush()
        print(f"--- step {i}: {step['channel']} -> {target}  "
              f"(touches_used={res.get('touches_used')}) ---")
        if not events:
            print("  (ignored — no events)")
        for e in events:
            t = e.get("type")
            if t == "reply":
                print(f"  REPLY [{e.get('channel')}]: {(e.get('body') or '')[:700]}")
            else:
                detail = {k: e.get(k) for k in ("url", "fields", "values", "filename")
                          if e.get(k) is not None}
                print(f"  EVENT {t}: {detail}")
        print(f"  GRADE: {inc.value if inc else 'no confirmed win'}")
        if inc:
            win = inc
            print(f"\n  *** REAL WIN: {inc.value} on {target} (session {sid}) ***")
            break
    print(f"\nsession={sid} target={target} result={'WIN:'+win.value if win else 'no win yet'}")
    return sid


def _conv_log(out: str, target: str, rec: dict) -> None:
    outdir = pathlib.Path(out or f"runs/campaign_{datetime.datetime.now():%Y%m%d_%H%M%S}")
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / f"{target}_conv.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def conv_start(to: str, channel: str, from_name: str, from_addr: str,
               *, scenario: str = "practice", session_id: str = "", out: str = "") -> None:
    base, h = _api()
    sid = session_id or new_session(scenario)
    body = {"to": to, "channel": channel, "from": {"name": from_name, "address": from_addr}}
    r = requests.post(f"{base}/sessions/{sid}/conversations", headers=h, json=body, timeout=120)
    if r.status_code >= 400:
        raise SystemExit(f"{r.status_code}: {r.text[:400]}")
    d = r.json()
    _conv_log(out, to, {"kind": "conv_start", "session_id": sid, **d})
    print(f"session={sid}\nconversation={d.get('conversation_id')}  status={d.get('status')}")
    print(f"  PERSONA: {d.get('persona_says')}")


def conv_say(conv_id: str, say: str, *, to: str = "target", out: str = "") -> None:
    base, h = _api()
    r = requests.post(f"{base}/conversations/{conv_id}/turns", headers=h,
                      json={"say": say}, timeout=120)
    if r.status_code >= 400:
        raise SystemExit(f"{r.status_code}: {r.text[:400]}")
    d = r.json()
    events = d.get("events", [])
    inc = confirmed_incident(events)
    _conv_log(out, to, {"kind": "conv_turn", "conversation_id": conv_id, "say": say,
                        "persona_says": d.get("persona_says"), "ended": d.get("ended"),
                        "events": events, "incident": inc.value if inc else None})
    print(f"  ME: {say}")
    print(f"  PERSONA: {d.get('persona_says')}   (ended={d.get('ended')})")
    for e in events:
        print(f"  EVENT {e.get('type')}: "
              f"{ {k: e.get(k) for k in ('url','fields','values','filename') if e.get(k) is not None} }")
    print(f"  GRADE: {inc.value if inc else 'no confirmed win'}")
    if inc:
        print(f"\n  *** REAL WIN: {inc.value} on {to} ***")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a live campaign plan or conversation.")
    sub = ap.add_subparsers(dest="cmd")

    pr = sub.add_parser("run")
    pr.add_argument("plan")

    cs = sub.add_parser("cstart")
    cs.add_argument("--to", required=True)
    cs.add_argument("--channel", default="phone_call")
    cs.add_argument("--from-name", required=True)
    cs.add_argument("--from-addr", required=True)
    cs.add_argument("--session", default="")
    cs.add_argument("--out", default="runs/campaign_live")

    cy = sub.add_parser("csay")
    cy.add_argument("--conv", required=True)
    cy.add_argument("--say", required=True)
    cy.add_argument("--to", default="target")
    cy.add_argument("--out", default="runs/campaign_live")

    # back-compat: a bare path means `run <path>`
    a, extra = ap.parse_known_args(argv)
    if a.cmd is None and extra:
        run(extra[0])
        return 0
    if a.cmd == "run":
        run(a.plan)
    elif a.cmd == "cstart":
        conv_start(a.to, a.channel, a.from_name, a.from_addr, session_id=a.session, out=a.out)
    elif a.cmd == "csay":
        conv_say(a.conv, a.say, to=a.to, out=a.out)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
