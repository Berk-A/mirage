"""Neutral channel characterization for the revel8 target API.

A measurement (not attack) harness: it sends ONE short, benign, non-deceptive
"quick coordination" probe per channel and records how the channel behaves —
HTTP acceptance, whether an event came back (reply / silence), the reply text,
latency, and any channel-specific behaviour. For live channels it opens a
conversation, says one benign opener, records how the channel presents and what
the persona says, then ends it.

Nothing here crafts a pretext: the probe is a plain scheduling-coordination note
with no links, credentials, attachments, or deception. Each probe runs in its own
fresh session so it is a clean FIRST contact (no cross-touch memory confound).

Run:
    python -m experiments.channel_recon            # all channels
    python -m experiments.channel_recon --only email,sms,phone_call

Output: runs/channel_recon/probes_<UTC>.jsonl (one row per probe) and a printed
summary. Respects rate limits: a small worker pool (<= API's 6-parallel cap),
each probe in its own session, well under 60 new sessions/hr.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.errors import TargetApiError
from core.models import LIVE_CHANNELS, MESSAGE_CHANNELS, Event, RenderedMessage, Sender
from ooda_loop.client import Revel8Client

# --------------------------------------------------------------------------- #
# Benign probe content (identical intent everywhere; shape adapted per channel)
# --------------------------------------------------------------------------- #
SENDER_NAME = "Alex Berger"
SENDER_EMAIL = "alex.berger@sync-desk.io"
SENDER_PHONE = "+49 151 2345 6789"
SENDER_HANDLE = "@alex.berger"

# Three practice founders; probes rotate across them so no single persona
# accumulates suspicion and we get a little per-archetype coverage.
TARGETS = ["julius", "tom", "robert"]
TARGET_NAME = {"julius": "Julius", "tom": "Tom", "robert": "Robert"}

# Plain, non-deceptive scheduling-coordination note.
def _note(name: str) -> str:
    return (
        f"Hi {name}, this is Alex. I'm reaching out to coordinate on a quick "
        f"scheduling matter and wanted to find the best way to reach you. When you "
        f"have a moment, what's a good time to connect? Thanks!"
    )


def _short_note(name: str) -> str:
    return f"Hi {name}, it's Alex — trying to coordinate a quick scheduling sync. When's a good time to connect?"


# How the sender presents on each channel (what `from` the channel would show).
def _sender_for(channel: str) -> Sender:
    phone = {"sms", "whatsapp", "signal", "imessage", "voicemail",
             "phone_call", "video_call"}
    handle = {"telegram", "x_dm", "instagram_dm"}
    if channel in phone:
        return Sender(name=SENDER_NAME, address=SENDER_PHONE)
    if channel in handle:
        return Sender(name=SENDER_NAME, address=SENDER_HANDLE)
    if channel in {"email", "calendar_invite", "shared_document", "mfa_push"}:
        return Sender(name=SENDER_NAME, address=SENDER_EMAIL)
    # slack, teams_chat, discord, linkedin_*, facebook_messenger, teams_call, live_chat
    return Sender(name=SENDER_NAME)


def _message_for(channel: str, target: str) -> RenderedMessage:
    """Build the benign probe for a message channel."""
    name = TARGET_NAME[target]
    sender = _sender_for(channel)
    subject: Optional[str] = None
    body: str

    if channel == "email":
        subject = "Quick scheduling coordination"
        body = _note(name)
    elif channel == "calendar_invite":
        subject = "Quick coordination sync"
        body = "Proposing a short sync to coordinate scheduling. Suggest a time that works for you."
    elif channel == "shared_document":
        body = ("Alex Berger shared a document with you: 'Scheduling notes'. "
                "It lists a couple of times to coordinate a sync.")
    elif channel == "voicemail":
        body = (f"Hi {name}, it's Alex. Just reaching out to coordinate on a quick "
                f"scheduling matter — give me a call back when you get a chance. Thanks!")
    elif channel == "mfa_push":
        # An approval prompt has no non-suspicious framing; we send the standard
        # prompt text and record the reaction. This is itself a finding.
        body = "Approve sign-in request from a new device? Tap approve to confirm it's you."
    elif channel in {"sms", "imessage"}:
        body = _short_note(name)
    else:
        body = _note(name)

    return RenderedMessage(channel=channel, body=body, sender=sender, subject=subject)


LIVE_OPENER = ("Hi, this is Alex — I'm reaching out to coordinate on a quick "
               "scheduling matter. Do you have a moment to connect?")


# --------------------------------------------------------------------------- #
# Result row
# --------------------------------------------------------------------------- #
def _events_to_dicts(events: tuple[Event, ...]) -> list[dict[str, Any]]:
    out = []
    for e in events:
        out.append({
            "id": e.id,
            "type": e.type.value if hasattr(e.type, "value") else str(e.type),
            "channel": e.channel,
            "url": e.url,
            "subject": e.subject,
            "body": e.body,
            "in_reply_to": e.in_reply_to,
        })
    return out


@dataclass
class ProbeRow:
    channel: str
    kind: str                     # "message" | "live"
    target: str
    accepted: bool                # HTTP < 400
    status: Optional[int]         # HTTP-ish status (None if accepted/exception-free)
    error_class: Optional[str]
    error_body: Any
    engaged: bool                 # any event came back (message) / persona spoke (live)
    outcome: str                  # accepted-engaged | accepted-silent | errored | ...
    reply_text: str
    event_types: list[str]
    events: list[dict[str, Any]]
    latency_s: float
    touches_used: int
    session_id: str
    persona_says: Optional[str] = None     # live: how they answer
    persona_says_turn: Optional[str] = None  # live: reply to the opener
    conversation_id: Optional[str] = None
    notes: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #
def probe_message(client: Revel8Client, channel: str, target: str) -> ProbeRow:
    msg = _message_for(channel, target)
    t0 = time.perf_counter()
    try:
        session = client.new_session("practice")
        sid = session.session_id
    except TargetApiError as exc:
        return ProbeRow(
            channel=channel, kind="message", target=target, accepted=False,
            status=getattr(exc, "status", None), error_class=type(exc).__name__,
            error_body=exc.body, engaged=False, outcome="session-error",
            reply_text="", event_types=[], events=[],
            latency_s=round(time.perf_counter() - t0, 2), touches_used=0,
            session_id="", notes="failed to open session",
        )

    try:
        res = client.send_message(sid, msg, to=target, idempotency_key=str(uuid.uuid4()))
    except TargetApiError as exc:
        return ProbeRow(
            channel=channel, kind="message", target=target, accepted=False,
            status=getattr(exc, "status", None), error_class=type(exc).__name__,
            error_body=exc.body, engaged=False, outcome="errored",
            reply_text="", event_types=[], events=[],
            latency_s=round(time.perf_counter() - t0, 2), touches_used=0,
            session_id=sid, notes=f"{type(exc).__name__}: {exc}",
        )
    latency = round(time.perf_counter() - t0, 2)

    events = res.events
    etypes = [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events]
    reply = ""
    reply_channel = None
    for e in events:
        if (e.type.value if hasattr(e.type, "value") else str(e.type)) == "reply" and e.body:
            reply = e.body
            reply_channel = e.channel
            break
    engaged = bool(events)
    outcome = "accepted-engaged" if engaged else "accepted-silent"
    notes = ""
    if reply_channel and reply_channel != channel:
        notes = f"replied on a different channel: {reply_channel}"
    return ProbeRow(
        channel=channel, kind="message", target=target, accepted=True, status=None,
        error_class=None, error_body=None, engaged=engaged, outcome=outcome,
        reply_text=reply, event_types=etypes, events=_events_to_dicts(events),
        latency_s=latency, touches_used=res.touches_used, session_id=sid, notes=notes,
    )


def probe_live(client: Revel8Client, channel: str, target: str) -> ProbeRow:
    sender = _sender_for(channel)
    t0 = time.perf_counter()
    try:
        session = client.new_session("practice")
        sid = session.session_id
    except TargetApiError as exc:
        return ProbeRow(
            channel=channel, kind="live", target=target, accepted=False,
            status=getattr(exc, "status", None), error_class=type(exc).__name__,
            error_body=exc.body, engaged=False, outcome="session-error",
            reply_text="", event_types=[], events=[],
            latency_s=round(time.perf_counter() - t0, 2), touches_used=0,
            session_id="", notes="failed to open session",
        )

    try:
        conv = client.start_conversation(sid, to=target, channel=channel, sender=sender)
    except TargetApiError as exc:
        return ProbeRow(
            channel=channel, kind="live", target=target, accepted=False,
            status=getattr(exc, "status", None), error_class=type(exc).__name__,
            error_body=exc.body, engaged=False, outcome="errored",
            reply_text="", event_types=[], events=[],
            latency_s=round(time.perf_counter() - t0, 2), touches_used=0,
            session_id=sid, notes=f"start_conversation {type(exc).__name__}: {exc}",
        )

    cid = conv.conversation_id
    persona_open = conv.persona_says
    persona_turn = None
    ended = False
    turn_events: list[dict[str, Any]] = []
    try:
        turn = client.say_turn(cid, LIVE_OPENER, idempotency_key=str(uuid.uuid4()))
        persona_turn = turn.persona_says
        ended = turn.ended
        turn_events = _events_to_dicts(turn.events)
    except TargetApiError as exc:
        persona_turn = f"[turn errored: {type(exc).__name__}: {exc}]"
    finally:
        try:
            client.end_conversation(cid)
        except TargetApiError:
            pass

    latency = round(time.perf_counter() - t0, 2)
    engaged = bool(persona_open or persona_turn)
    return ProbeRow(
        channel=channel, kind="live", target=target, accepted=True, status=None,
        error_class=None, error_body=None, engaged=engaged,
        outcome="accepted-engaged" if engaged else "accepted-silent",
        reply_text="", event_types=[e["type"] for e in turn_events],
        events=turn_events, latency_s=latency, touches_used=conv.touches_used,
        session_id=sid, persona_says=persona_open, persona_says_turn=persona_turn,
        conversation_id=cid, notes=("persona ended the call" if ended else ""),
    )


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run(only: Optional[list[str]], workers: int, out_dir: Path) -> list[ProbeRow]:
    client = Revel8Client()
    if not client.api_key:
        raise SystemExit("REVEL8_API_KEY not set — source the main checkout's .env first.")

    message_channels = sorted(MESSAGE_CHANNELS)
    live_channels = sorted(LIVE_CHANNELS)
    if only:
        message_channels = [c for c in message_channels if c in only]
        live_channels = [c for c in live_channels if c in only]

    # Assign a rotating target per channel for even distribution.
    jobs: list[tuple[str, str, str]] = []  # (kind, channel, target)
    i = 0
    for ch in message_channels:
        jobs.append(("message", ch, TARGETS[i % len(TARGETS)])); i += 1
    for ch in live_channels:
        jobs.append(("live", ch, TARGETS[i % len(TARGETS)])); i += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"probes_{stamp}.jsonl"

    rows: list[ProbeRow] = []

    def _do(job: tuple[str, str, str]) -> ProbeRow:
        kind, ch, tgt = job
        if kind == "live":
            return probe_live(client, ch, tgt)
        return probe_message(client, ch, tgt)

    print(f"Probing {len(jobs)} channels ({len(message_channels)} message, "
          f"{len(live_channels)} live) -> {out_path}")
    with open(out_path, "w") as fh, ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_do, job): job for job in jobs}
        for fut in as_completed(futs):
            row = fut.result()
            rows.append(row)
            fh.write(json.dumps(asdict(row)) + "\n")
            fh.flush()
            flag = row.outcome
            extra = ""
            if row.kind == "live" and row.persona_says:
                extra = f" | opens: {row.persona_says[:60]!r}"
            elif row.reply_text:
                extra = f" | reply: {row.reply_text[:60]!r}"
            print(f"  [{flag:>16}] {row.channel:<28} -> {row.target:<7} "
                  f"{row.latency_s:>6.1f}s{extra}")

    rows.sort(key=lambda r: (r.kind, r.channel))
    print(f"\nWrote {len(rows)} rows to {out_path}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", type=str, default="",
                    help="comma-separated channel ids to probe (default: all)")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel probes (<= API's 6-parallel cap); default 4")
    ap.add_argument("--out", type=str, default="runs/channel_recon",
                    help="output directory for the JSONL log")
    args = ap.parse_args()
    only = [c.strip() for c in args.only.split(",") if c.strip()] or None
    run(only, args.workers, Path(args.out))


if __name__ == "__main__":
    main()
