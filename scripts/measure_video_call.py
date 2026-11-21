"""One-off: measure the video_call live channel by REUSING an existing session.

The full channel_recon run hit the team-wide "60 new sessions/hour" cap on the
last channel (video_call) because sibling sessions were also opening sessions.
A conversation in an ALREADY-OPEN session costs one touch and opens no new
session, so we reuse a benign julius session from the batch to characterise
video_call. It is a follow-up touch (not a clean first-contact); the row notes
that. Appends one ProbeRow to the given JSONL log.

    python scripts/measure_video_call.py runs/channel_recon/probes_<ts>.jsonl
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import asdict

import experiments.channel_recon as cr
from ooda_loop.client import Revel8Client


def main(log_path: str) -> None:
    rows = [json.loads(line) for line in open(log_path)]
    # Reuse a benign, already-open julius session (the voicemail probe was silent).
    sid = next((r["session_id"] for r in rows
                if r["target"] == "julius" and r["channel"] == "voicemail" and r["session_id"]), None)
    if not sid:
        sid = next((r["session_id"] for r in rows
                    if r["target"] == "julius" and r["session_id"]), None)
    if not sid:
        raise SystemExit("no julius session found in the log to reuse")
    print(f"reusing session {sid} for video_call -> julius")

    client = Revel8Client()
    t0 = time.perf_counter()
    conv = client.start_conversation(sid, to="julius", channel="video_call",
                                     sender=cr._sender_for("video_call"))
    turn = client.say_turn(conv.conversation_id, cr.LIVE_OPENER,
                           idempotency_key=str(uuid.uuid4()))
    client.end_conversation(conv.conversation_id)
    latency = round(time.perf_counter() - t0, 2)

    row = cr.ProbeRow(
        channel="video_call", kind="live", target="julius", accepted=True, status=None,
        error_class=None, error_body=None,
        engaged=bool(conv.persona_says or turn.persona_says), outcome="accepted-engaged",
        reply_text="", event_types=[], events=[], latency_s=latency,
        touches_used=conv.touches_used, session_id=sid, persona_says=conv.persona_says,
        persona_says_turn=turn.persona_says, conversation_id=conv.conversation_id,
        notes=("follow-up touch in an existing session, not a clean first-contact "
               "(team-wide 60 new-sessions/hr cap was saturated by sibling sessions)"),
    )
    print("opens:", repr(conv.persona_says))
    print("to-opener:", repr(turn.persona_says))
    with open(log_path, "a") as fh:
        fh.write(json.dumps(asdict(row)) + "\n")
    print("appended; total rows now:", sum(1 for _ in open(log_path)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/channel_recon/latest.jsonl")
