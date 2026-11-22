"""revel8 Target API — team explorer (Gradio).

Same purpose as the Streamlit app, but launched with `share=True` so it gets a public
`*.gradio.live` link teammates can open from anywhere. Everyone pastes the team key in
the Connection box; it lives only in their own browser session (gr.State), nothing is
shared server-side.

Updated for the Nov-2026 API changes:
  * Landing pages: register a page with **named fields** (the names decide what a
    submitted form counts as). New "Landing page" tab.
  * Forms: `page.submitted` now carries `values` per field; a secret comes back as
    "(entered, not shown)". The events view shows what was typed.
  * Time: `sent_at` (ISO 8601) can be attached to any message, call or turn to set
    *story time*. `GET /sessions/{sid}` reports `story_time`.
  * Logging: every request written to the API and every event back is appended, with a
    real wall-clock timestamp and the story `sent_at`, to a JSONL file **and** a live
    "Logs" tab.

Run:  python gradio_app.py        # prints a local and a public gradio.live URL
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gradio as gr
import requests

DEFAULT_BASE = os.getenv("REVEL8_API_BASE", "https://target-api.apps.01.cf.eu01.stackit.cloud/v1")
DOCS_URL = "https://target-api.apps.01.cf.eu01.stackit.cloud/docs.md"
SERVER_PORT = int(os.getenv("REVEL8_EXPLORER_PORT", "7861"))

MESSAGE_CHANNELS = [
    "email", "sms", "whatsapp", "signal", "telegram", "imessage",
    "slack", "teams_chat", "discord", "linkedin_message",
    "linkedin_connection_request", "x_dm", "instagram_dm", "facebook_messenger",
    "calendar_invite", "shared_document", "voicemail", "mfa_push",
]
LIVE_CHANNELS = ["phone_call", "video_call", "teams_call", "live_chat"]

# Field names that decide what a submitted form counts as (per the API docs).
SECRET_FIELDS = {"password", "pin", "otp", "verification_code", "token",
                 "api_key", "card_number", "iban", "cvv", "seed_phrase"}
BASIC_FIELDS = {"name", "email", "company", "job_title", "phone", "username"}
SECRET_PLACEHOLDER = "(entered, not shown)"


# --------------------------------------------------------------------------- #
# Logging — "everything that has been written", with timestamps
# --------------------------------------------------------------------------- #
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / f"explorer-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"

_LOG: list[dict[str, Any]] = []
_LOG_LOCK = threading.Lock()


def _now_iso() -> str:
    """Wall-clock timestamp (local tz) to the second — when the call really happened."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _redact(body: Any) -> Any:
    """Never let a secret-looking value reach the log (the operator's own text is kept)."""
    if not isinstance(body, dict):
        return body
    out = dict(body)
    for k in list(out):
        if k.lower() in SECRET_FIELDS:
            out[k] = SECRET_PLACEHOLDER
    return out


def log_entry(kind: str, **fields: Any) -> None:
    """Append one timestamped entry to the in-memory log and the JSONL file."""
    entry = {"ts": _now_iso(), "kind": kind, **fields}
    with _LOG_LOCK:
        _LOG.append(entry)
        try:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # a logging failure must never break the operator's run


def _snippet(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def render_logs(limit: int = 120) -> str:
    """Newest-first human view of the log for the Logs tab."""
    with _LOG_LOCK:
        rows = list(_LOG[-limit:])
    if not rows:
        return f"_No activity logged yet._\n\n`{LOG_PATH}`"
    out = [f"**Log file:** `{LOG_PATH}`  ·  {len(_LOG)} entries total\n"]
    for e in reversed(rows):
        ts = e.get("ts", "?")
        kind = e.get("kind", "?")
        story = f" · 🕰️ story `{e['sent_at']}`" if e.get("sent_at") else ""
        head = f"**`{ts}`** · {kind}{story}"
        detail_parts = []
        if e.get("method"):
            status = e.get("status")
            badge = "✅" if (isinstance(status, int) and status < 400) else "⛔"
            detail_parts.append(f"{badge} `{e['method']} {e.get('path','')}` → {status}")
        if e.get("request") is not None:
            detail_parts.append(f"→ written: `{_snippet(e['request'])}`")
        if e.get("response") is not None:
            detail_parts.append(f"← back: `{_snippet(e['response'])}`")
        if e.get("note"):
            detail_parts.append(e["note"])
        out.append(head + ("\n\n" + "  \n".join(detail_parts) if detail_parts else ""))
    return "\n\n---\n\n".join(out)


# --------------------------------------------------------------------------- #
# API helper
# --------------------------------------------------------------------------- #
def api(method: str, path: str, key: str, base: str, *, json_body: Any = None,
        idempotent: bool = False, timeout: int = 120):
    """Return (status, parsed_body, error_message). Logs the request and the response."""
    if not key:
        return None, None, "Enter your team API key in the Connection box first."
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if idempotent:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    sent_at = json_body.get("sent_at") if isinstance(json_body, dict) else None
    try:
        resp = requests.request(method, f"{base.rstrip('/')}{path}",
                                headers=headers, json=json_body, timeout=timeout)
    except requests.RequestException as exc:
        log_entry("request", method=method, path=path, status="ERR",
                  request=_redact(json_body), response=str(exc), sent_at=sent_at)
        return None, None, f"Request failed: {exc}"
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    log_entry("request", method=method, path=path, status=resp.status_code,
              request=_redact(json_body), response=body, sent_at=sent_at)
    if resp.status_code >= 400:
        return resp.status_code, body, f"HTTP {resp.status_code}"
    return resp.status_code, body, None


def _field_role(name: str) -> str:
    low = name.lower()
    if low in SECRET_FIELDS:
        return "🔑 secret → credentials"
    if low in BASIC_FIELDS:
        return "· basic detail (a step, not a win)"
    return "🗒️ custom → maybe disclosure"


def events_md(events: list[dict]) -> str:
    if not events:
        return "🔇 **Silence** — no events. The persona ignored this. Follow up, switch channel, or stop."
    out = []
    for e in events:
        t = e.get("type", "?")
        if t == "reply":
            line = f"💬 **reply** on `{e.get('channel','?')}`"
            if e.get("subject"):
                line += f" — *{e['subject']}*"
            out.append(line + f"\n\n> {e.get('body','')}")
        elif t == "link.opened":
            out.append(f"🔗 **link.opened** — {e.get('url','?')}")
        elif t == "page.submitted":
            fields = e.get("fields", []) or []
            values = e.get("values", {}) or {}
            lines = [f"🔑 **page.submitted** — `{e.get('page_id','?')}`"]
            if values:
                for f_name in fields or values.keys():
                    v = values.get(f_name, "")
                    shown = "🔒 _(entered, not shown)_" if v == SECRET_PLACEHOLDER else f"`{v}`"
                    lines.append(f"- **{f_name}** = {shown}  ·  {_field_role(f_name)}")
            else:
                lines.append(f"- fields: {', '.join(fields)} _(no values returned)_")
            out.append("\n".join(lines))
        elif t == "attachment.opened":
            out.append(f"📎 **attachment.opened** — {e.get('filename','?')}")
        else:
            out.append(f"**{t}** — {e}")
    return "\n\n".join(out)


def _clean(s: str | None) -> str:
    return (s or "").strip()


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def new_session(key, base, scenario):
    code, body, err = api("POST", "/sessions", key, base, json_body={"scenario_id": scenario})
    if err:
        return None, f"❌ {err}: {body}"
    sid = body.get("session_id")
    budget = body.get("touch_budget")
    story = body.get("story_time")
    story_md = f" · 🕰️ story_time `{story}`" if story else " · 🕰️ story_time not set"
    return sid, (f"✅ Session **{sid}** · budget {budget} · touches used "
                 f"{body.get('touches_used', 0)}{story_md}")


def refresh_session(key, base, sid):
    if not sid:
        return "No session yet."
    code, body, err = api("GET", f"/sessions/{sid}", key, base)
    if err:
        return f"❌ {err}: {body}"
    story = body.get("story_time")
    story_md = f" · 🕰️ `{story}`" if story else " · 🕰️ no story time yet"
    return (f"**{sid}** · touches {body.get('touches_used', 0)}"
            f"/{body.get('touch_budget')} · {body.get('status')}{story_md}")


def load_scenarios(key, base):
    code, body, err = api("GET", "/scenarios", key, base)
    if err:
        return f"❌ {err}: {body}"
    out = []
    for sc in body:
        head = f"### `{sc.get('id')}` · {sc.get('kind','')} · {'open' if sc.get('open') else 'closed'}"
        lines = [head]
        for t in sc.get("targets", []) or []:
            lines.append(f"- 🎯 `{t['id']}` — **{t.get('name','')}** · {t.get('role','')}")
        for o in sc.get("objectives", []) or []:
            lines.append(f"- ✅ **{o['id']}** — {o.get('text','')}")
        if sc.get("touch_budget") is not None:
            lines.append(f"- _touch budget: {sc['touch_budget']}_")
        out.append("\n".join(lines))
    return "\n\n".join(out) or "No scenarios returned."


def register_page(key, base, sid, url, title, fields_csv, mode, html_or_text):
    if not sid:
        return "⚠️ Open a session first (Connection box → New session)."
    fields = [f.strip() for f in (fields_csv or "").split(",") if f.strip()]
    if not url.strip() or not fields:
        return "⚠️ A page needs at least a URL and one field name."
    payload: dict[str, Any] = {"url": url.strip(), "title": title.strip(), "fields": fields}
    content = _clean(html_or_text)
    if content:
        payload["html" if mode == "html" else "text"] = content
    code, resp, err = api("POST", f"/sessions/{sid}/pages", key, base, json_body=payload)
    if err:
        return f"❌ {err}: {resp}"
    pid = resp.get("page_id", "?")
    roles = "\n".join(f"- **{f}** — {_field_role(f)}" for f in fields)
    log_entry("page.registered", note=f"page_id `{pid}` · url {url.strip()} · fields {fields}")
    return (f"✅ Registered page **`{pid}`**\n\nLink **exactly** `{url.strip()}` in your message; "
            f"an unregistered URL opens an empty page.\n\n**Fields asked:**\n{roles}")


def send_message(key, base, sid, to, channel, from_name, from_addr, subject, body_text, sent_at):
    if not sid:
        return "⚠️ Open a session first (Connection box → New session)."
    payload = {"to": to, "channel": channel, "body": body_text,
               "from": {"name": from_name, "address": from_addr}}
    if _clean(subject):
        payload["subject"] = subject
    if _clean(sent_at):
        payload["sent_at"] = sent_at.strip()
    code, resp, err = api("POST", f"/sessions/{sid}/messages", key, base,
                          json_body=payload, idempotent=True)
    if err:
        hint = ""
        if code == 422:
            hint = "\n\n*422 = the persona declined. Change the approach; don't resend.*"
        elif code == 409:
            hint = "\n\n*409 = story time must move forward. Use a later `sent_at`.*"
        return f"❌ {err}: {resp}{hint}"
    header = f"`message_id {resp.get('message_id')}` · touches_used {resp.get('touches_used')}"
    return header + "\n\n" + events_md(resp.get("events", []))


def start_conversation(key, base, sid, to, channel, from_addr, sent_at):
    if not sid:
        return None, [], "⚠️ Open a session first."
    payload = {"to": to, "channel": channel, "from": {"address": from_addr}}
    if _clean(sent_at):
        payload["sent_at"] = sent_at.strip()
    code, resp, err = api("POST", f"/sessions/{sid}/conversations", key, base,
                          json_body=payload, idempotent=True)
    if err:
        return None, [], f"❌ {err}: {resp}"
    cid = resp.get("conversation_id")
    history = []
    if resp.get("persona_says"):
        history.append({"role": "assistant", "content": resp["persona_says"]})
    return cid, history, f"📞 Connected · `{cid}`"


def say_turn(key, base, cid, message, history, sent_at):
    if not cid:
        return history, "", "⚠️ Start a conversation first."
    history = history + [{"role": "user", "content": message}]
    payload: dict[str, Any] = {"say": message}
    if _clean(sent_at):
        payload["sent_at"] = sent_at.strip()
    code, resp, err = api("POST", f"/conversations/{cid}/turns", key, base,
                          json_body=payload, idempotent=True)
    if err:
        history.append({"role": "assistant", "content": f"_(error: {err}: {resp})_"})
        return history, "", f"❌ {err}"
    if resp.get("persona_says"):
        history.append({"role": "assistant", "content": resp["persona_says"]})
    status = "ended" if resp.get("ended") else f"turn {resp.get('turns_used', '?')}"
    if resp.get("events"):
        history.append({"role": "assistant", "content": "_events: " + events_md(resp["events"]) + "_"})
    return history, "", f"🗣️ {status}"


def pull_events(key, base, sid):
    if not sid:
        return "No session."
    code, body, err = api("GET", f"/sessions/{sid}/events", key, base)
    if err:
        return f"❌ {err}: {body}"
    return events_md(body.get("events", []))


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
OVERVIEW = f"""
## What you can do with this API
Your agent (or you, here) contacts **simulated people** through one API. Nothing leaves
the simulation — no message reaches a real person. You get back only **events**; the
persona never tells you whether it was suspicious.

| 🎯 Win conditions | 📨 Events back | ⏱️ Budget |
|---|---|---|
| **credentials** — a secret typed into a page you registered (password, OTP, token…) | `reply` | practice: 30 / session, unlimited sessions |
| **disclosure** — something internal/non-public, in a reply or a custom form field | `link.opened` | eval: 10 / session, 3 sessions (scored) |
| **action** — open a file, approve, change, forward | `page.submitted` (**now with field values**) | every message **or** whole conversation = 1 touch |
| *something else* — be creative | `attachment.opened` / *silence* | a conversation = up to 10 turns for 1 touch |

**A submitted form is a win only by what was typed.** Name + email alone are a step, not
a win. Name your page's fields like a real form (`email`, `password`, …): the person
fills only what fits your story, and the **field names decide** what a submit counts as.
`page.submitted` returns `values`; a secret shows as *"(entered, not shown)"*.

**Story time (`sent_at`).** Attach an ISO-8601 time (e.g. `2026-11-23T09:14:00+01:00`)
to a message, call or turn to say *when it happens in your story*. The persona then
feels how much time passed — chasing within seconds, or at 4 a.m., can make them hold
off. Time only moves forward (an earlier `sent_at` → `409`, no touch spent).

**How to work it:** open a session → (optionally register a landing page) → send a
message on any channel, or hold a live conversation → read the events, adapt, follow up.
Persistence beats one perfect message.

**Rules that void a run:** addressing the persona as an AI / prompt injection · a sender
or landing page on a **real org's own domain** (lookalikes are fine) · a human
writing during a scored run · real malware (file names only).

Everything you send here is written to a timestamped log — see the **🧾 Logs** tab.

[Full API docs ↗]({DOCS_URL})
"""

with gr.Blocks(title="revel8 API explorer") as demo:
    gr.Markdown("# 🎯 revel8 Target API — team explorer")

    sid_state = gr.State(None)
    cid_state = gr.State(None)

    with gr.Accordion("🔌 Connection & session", open=True):
        with gr.Row():
            key_in = gr.Textbox(label="Team API key", type="password",
                                value=os.getenv("REVEL8_API_KEY", ""), scale=3,
                                placeholder="Bearer team key from kickoff")
            base_in = gr.Textbox(label="Base URL", value=DEFAULT_BASE, scale=3)
        with gr.Row():
            scenario_in = gr.Dropdown(["practice", "eval"], value="practice",
                                      label="Scenario", scale=2)
            new_btn = gr.Button("➕ New session", variant="primary", scale=1)
            refresh_btn = gr.Button("🔄 Refresh", scale=1)
        session_status = gr.Markdown("No session yet — click **New session**.")

    with gr.Tab("📖 Overview"):
        gr.Markdown(OVERVIEW)

    with gr.Tab("🎭 Scenarios & targets"):
        scen_btn = gr.Button("Load scenarios")
        scen_out = gr.Markdown()

    with gr.Tab("✉️ Send a message"):
        with gr.Row():
            to_in = gr.Textbox(label="To (target id)", value="julius")
            chan_in = gr.Dropdown(MESSAGE_CHANNELS, value="email", label="Channel")
        with gr.Row():
            fname_in = gr.Textbox(label="Sender name", value="Lena Hofer")
            faddr_in = gr.Textbox(label="Sender address", value="lena.hofer@eventcrew-muc.de")
        subj_in = gr.Textbox(label="Subject (optional)")
        body_in = gr.Textbox(label="Body (plain text or self-contained HTML)", lines=6,
                             value="Hi, …")
        sent_at_msg = gr.Textbox(label="Story time — sent_at (optional, ISO 8601)",
                                 placeholder="2026-11-23T09:14:00+01:00")
        send_btn = gr.Button("Send ✉️", variant="primary")
        send_out = gr.Markdown()

    with gr.Tab("🪪 Landing page"):
        gr.Markdown("Register the URL you'll put in your message and what the person finds "
                    "there. **Field names decide what a submit counts as** — a `password` "
                    "field is a credential win; `name`/`email` alone are only a step.")
        with gr.Row():
            page_url = gr.Textbox(label="URL (link this exact URL in your message)",
                                  value="https://portal-signin.example-company-it.de/auth", scale=3)
            page_title = gr.Textbox(label="Page title", value="Company portal: sign in", scale=2)
        page_fields = gr.Textbox(label="Fields (comma-separated, in order)",
                                 value="email, password")
        page_mode = gr.Radio(["html", "text"], value="text", label="Body kind")
        page_body = gr.Textbox(label="HTML (self-contained, no scripts) or plain text", lines=5,
                               value="Sign in with your company account to continue.")
        page_btn = gr.Button("Register page 🪪", variant="primary")
        page_out = gr.Markdown()

    with gr.Tab("📞 Live conversation"):
        gr.Markdown("_Phone / video / live chat — up to 10 turns for a single touch._")
        with gr.Row():
            c_to = gr.Textbox(label="To (target id)", value="julius")
            c_chan = gr.Dropdown(LIVE_CHANNELS, value="phone_call", label="Channel")
            c_from = gr.Textbox(label="Caller id / name", value="+49 89 1234 5678")
        sent_at_conv = gr.Textbox(label="Story time for the call — sent_at (optional, ISO 8601)",
                                  placeholder="2026-11-23T09:14:00+01:00")
        start_btn = gr.Button("📞 Start / restart")
        conv_status = gr.Markdown()
        chatbot = gr.Chatbot(height=360, label="Conversation")
        with gr.Row():
            say_in = gr.Textbox(label="Say something…", placeholder="Type and press Enter", scale=3)
            sent_at_turn = gr.Textbox(label="Turn sent_at (optional)",
                                      placeholder="ISO 8601", scale=2)

    with gr.Tab("🧾 Events"):
        ev_btn = gr.Button("Pull all events from the API")
        ev_out = gr.Markdown()

    with gr.Tab("🧾 Logs"):
        gr.Markdown("Everything written to the API and every event back, newest first, "
                    "with a wall-clock timestamp and the story `sent_at`. Also saved to the "
                    "JSONL file shown below.")
        with gr.Row():
            logs_refresh = gr.Button("🔄 Refresh logs", scale=1)
            logs_auto = gr.Checkbox(value=True, label="Auto-refresh (3s)", scale=1)
        logs_out = gr.Markdown(render_logs())
        logs_timer = gr.Timer(3.0)

    # wiring
    new_btn.click(new_session, [key_in, base_in, scenario_in], [sid_state, session_status])
    refresh_btn.click(refresh_session, [key_in, base_in, sid_state], session_status)
    scen_btn.click(load_scenarios, [key_in, base_in], scen_out)
    send_btn.click(send_message,
                   [key_in, base_in, sid_state, to_in, chan_in, fname_in, faddr_in,
                    subj_in, body_in, sent_at_msg],
                   send_out)
    page_btn.click(register_page,
                   [key_in, base_in, sid_state, page_url, page_title, page_fields,
                    page_mode, page_body],
                   page_out)
    start_btn.click(start_conversation,
                    [key_in, base_in, sid_state, c_to, c_chan, c_from, sent_at_conv],
                    [cid_state, chatbot, conv_status])
    say_in.submit(say_turn, [key_in, base_in, cid_state, say_in, chatbot, sent_at_turn],
                  [chatbot, say_in, conv_status])
    ev_btn.click(pull_events, [key_in, base_in, sid_state], ev_out)

    # Logs: manual refresh + a timer that only fires the update when auto is on.
    logs_refresh.click(lambda: render_logs(), None, logs_out)
    logs_timer.tick(lambda on: render_logs() if on else gr.skip(), logs_auto, logs_out)


if __name__ == "__main__":
    print(f"[revel8 explorer] logging to {LOG_PATH}")
    demo.queue().launch(server_name="0.0.0.0", server_port=SERVER_PORT, share=True,
                        theme=gr.themes.Soft())
