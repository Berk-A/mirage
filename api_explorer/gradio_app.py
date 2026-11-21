"""revel8 Target API — team explorer (Gradio).

Same purpose as the Streamlit app, but launched with `share=True` so it gets a public
`*.gradio.live` link teammates can open from anywhere. Everyone pastes the team key in
the Connection box; it lives only in their own browser session (gr.State), nothing is
shared server-side.

Run:  python gradio_app.py        # prints a local and a public gradio.live URL
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import gradio as gr
import requests

DEFAULT_BASE = os.getenv("REVEL8_API_BASE", "https://target-api.apps.01.cf.eu01.stackit.cloud/v1")
DOCS_URL = "https://target-api.apps.01.cf.eu01.stackit.cloud/docs.md"

MESSAGE_CHANNELS = [
    "email", "sms", "whatsapp", "signal", "telegram", "imessage",
    "slack", "teams_chat", "discord", "linkedin_message",
    "linkedin_connection_request", "x_dm", "instagram_dm", "facebook_messenger",
    "calendar_invite", "shared_document", "voicemail", "mfa_push",
]
LIVE_CHANNELS = ["phone_call", "video_call", "teams_call", "live_chat"]


# --------------------------------------------------------------------------- #
# API helper
# --------------------------------------------------------------------------- #
def api(method: str, path: str, key: str, base: str, *, json_body: Any = None,
        idempotent: bool = False, timeout: int = 120):
    """Return (status, parsed_body, error_message)."""
    if not key:
        return None, None, "Enter your team API key in the Connection box first."
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if idempotent:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    try:
        resp = requests.request(method, f"{base.rstrip('/')}{path}",
                                headers=headers, json=json_body, timeout=timeout)
    except requests.RequestException as exc:
        return None, None, f"Request failed: {exc}"
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    if resp.status_code >= 400:
        return resp.status_code, body, f"HTTP {resp.status_code}"
    return resp.status_code, body, None


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
            out.append(f"🔑 **page.submitted** — fields: {', '.join(e.get('fields', []))} "
                       f"(values never returned)")
        elif t == "attachment.opened":
            out.append(f"📎 **attachment.opened** — {e.get('filename','?')}")
        else:
            out.append(f"**{t}** — {e}")
    return "\n\n".join(out)


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def new_session(key, base, scenario):
    code, body, err = api("POST", "/sessions", key, base, json_body={"scenario_id": scenario})
    if err:
        return None, f"❌ {err}: {body}"
    sid = body.get("session_id")
    budget = body.get("touch_budget")
    return sid, f"✅ Session **{sid}** · budget {budget} · touches used {body.get('touches_used', 0)}"


def refresh_session(key, base, sid):
    if not sid:
        return "No session yet."
    code, body, err = api("GET", f"/sessions/{sid}", key, base)
    if err:
        return f"❌ {err}: {body}"
    return (f"**{sid}** · touches {body.get('touches_used', 0)}"
            f"/{body.get('touch_budget')} · {body.get('status')}")


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


def send_message(key, base, sid, to, channel, from_name, from_addr, subject, body_text):
    if not sid:
        return "⚠️ Open a session first (Connection box → New session)."
    payload = {"to": to, "channel": channel, "body": body_text,
               "from": {"name": from_name, "address": from_addr}}
    if subject.strip():
        payload["subject"] = subject
    code, resp, err = api("POST", f"/sessions/{sid}/messages", key, base,
                          json_body=payload, idempotent=True)
    if err:
        hint = "\n\n*422 = the persona declined. Change the approach; don't resend.*" if code == 422 else ""
        return f"❌ {err}: {resp}{hint}"
    header = f"`message_id {resp.get('message_id')}` · touches_used {resp.get('touches_used')}"
    return header + "\n\n" + events_md(resp.get("events", []))


def start_conversation(key, base, sid, to, channel, from_addr):
    if not sid:
        return None, [], "⚠️ Open a session first."
    payload = {"to": to, "channel": channel, "from": {"address": from_addr}}
    code, resp, err = api("POST", f"/sessions/{sid}/conversations", key, base,
                          json_body=payload, idempotent=True)
    if err:
        return None, [], f"❌ {err}: {resp}"
    cid = resp.get("conversation_id")
    history = []
    if resp.get("persona_says"):
        history.append({"role": "assistant", "content": resp["persona_says"]})
    return cid, history, f"📞 Connected · `{cid}`"


def say_turn(key, base, cid, message, history):
    if not cid:
        return history, "", "⚠️ Start a conversation first."
    history = history + [{"role": "user", "content": message}]
    code, resp, err = api("POST", f"/conversations/{cid}/turns", key, base,
                          json_body={"say": message}, idempotent=True)
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
| **credentials** — sign in on a page you registered | `reply` | practice: 30 / session, unlimited sessions |
| **action** — open a file, approve, change, forward | `link.opened` | eval: 10 / session, 3 sessions (scored) |
| **disclosure** — tell you something internal, non-public | `page.submitted` (field names only) | every message **or** whole conversation = 1 touch |
| *something else* — be creative | `attachment.opened` / *silence* | a conversation = up to 10 turns for 1 touch |

**How to work it:** open a session → send a message on any channel, or hold a live
conversation → read the events, adapt, follow up. Persistence beats one perfect message.

**Rules that void a run:** addressing the persona as an AI / prompt injection · a sender
or landing page on a **real org's own domain** (lookalikes are fine) · a human
writing during a scored run · real malware (file names only).

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
        send_btn = gr.Button("Send ✉️", variant="primary")
        send_out = gr.Markdown()

    with gr.Tab("📞 Live conversation"):
        gr.Markdown("_Phone / video / live chat — up to 10 turns for a single touch._")
        with gr.Row():
            c_to = gr.Textbox(label="To (target id)", value="julius")
            c_chan = gr.Dropdown(LIVE_CHANNELS, value="phone_call", label="Channel")
            c_from = gr.Textbox(label="Caller id / name", value="+49 89 1234 5678")
        start_btn = gr.Button("📞 Start / restart")
        conv_status = gr.Markdown()
        chatbot = gr.Chatbot(height=360, label="Conversation")
        say_in = gr.Textbox(label="Say something…", placeholder="Type and press Enter")

    with gr.Tab("🧾 Events"):
        ev_btn = gr.Button("Pull all events from the API")
        ev_out = gr.Markdown()

    # wiring
    new_btn.click(new_session, [key_in, base_in, scenario_in], [sid_state, session_status])
    refresh_btn.click(refresh_session, [key_in, base_in, sid_state], session_status)
    scen_btn.click(load_scenarios, [key_in, base_in], scen_out)
    send_btn.click(send_message,
                   [key_in, base_in, sid_state, to_in, chan_in, fname_in, faddr_in, subj_in, body_in],
                   send_out)
    start_btn.click(start_conversation, [key_in, base_in, sid_state, c_to, c_chan, c_from],
                    [cid_state, chatbot, conv_status])
    say_in.submit(say_turn, [key_in, base_in, cid_state, say_in, chatbot],
                  [chatbot, say_in, conv_status])
    ev_btn.click(pull_events, [key_in, base_in, sid_state], ev_out)


if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860, share=True,
                        theme=gr.themes.Soft())
