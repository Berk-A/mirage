"""revel8 Target API — team explorer.

A friendly Streamlit UI over the revel8 "Agentic Social Engineer" target API, so the
whole team can see what the API does and talk to it by hand: list scenarios, open a
session, send a message on any channel, hold a live conversation, and read the events
that come back.

Run:  streamlit run app.py
Each browser session keeps its own API key and target session (nothing is shared
server-side), so it is safe to share the link with teammates.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import requests
import streamlit as st

DEFAULT_BASE = os.getenv("REVEL8_API_BASE", "https://target-api.apps.01.cf.eu01.stackit.cloud/v1")
DOCS_URL = "https://target-api.apps.01.cf.eu01.stackit.cloud/docs.md"

MESSAGE_CHANNELS = [
    "email", "sms", "whatsapp", "signal", "telegram", "imessage",
    "slack", "teams_chat", "discord",
    "linkedin_message", "linkedin_connection_request",
    "x_dm", "instagram_dm", "facebook_messenger",
    "calendar_invite", "shared_document", "voicemail", "mfa_push",
]
LIVE_CHANNELS = ["phone_call", "video_call", "teams_call", "live_chat"]

OBJECTIVES = {
    "credentials": "They sign in on a page you registered.",
    "action": "They act for you — open a file, approve, change, forward.",
    "disclosure": "They tell you something internal that is not public.",
}

st.set_page_config(page_title="revel8 API explorer", page_icon="🎯", layout="wide")


# --------------------------------------------------------------------------- #
# API helpers
# --------------------------------------------------------------------------- #
def _headers(idempotent: bool = False) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {st.session_state.get('api_key', '')}",
        "Content-Type": "application/json",
    }
    if idempotent:
        h["Idempotency-Key"] = str(uuid.uuid4())
    return h


def api(method: str, path: str, *, json_body: Any = None, idempotent: bool = False,
        timeout: int = 120) -> tuple[int | None, Any, str | None]:
    """Return (status_code, parsed_body, error_message)."""
    if not st.session_state.get("api_key"):
        return None, None, "Enter your team API key in the sidebar first."
    base = st.session_state.get("base_url", DEFAULT_BASE).rstrip("/")
    try:
        resp = requests.request(
            method, f"{base}{path}", headers=_headers(idempotent),
            json=json_body, timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, None, f"Request failed: {exc}"
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    if resp.status_code >= 400:
        return resp.status_code, body, f"HTTP {resp.status_code}"
    return resp.status_code, body, None


def log_event(kind: str, payload: dict) -> None:
    st.session_state.setdefault("history", []).append({"kind": kind, **payload})


def render_events(events: list[dict]) -> None:
    if not events:
        st.info("🔇 **Silence** — no events. The persona ignored this contact. "
                "Follow up, switch channel, or stop.")
        return
    for e in events:
        etype = e.get("type", "?")
        if etype == "reply":
            st.success(f"💬 **reply** on `{e.get('channel','?')}`")
            if e.get("subject"):
                st.caption(f"Subject: {e['subject']}")
            st.write(e.get("body", ""))
        elif etype == "link.opened":
            st.warning(f"🔗 **link.opened** — {e.get('url','?')}")
        elif etype == "page.submitted":
            st.error(f"🔑 **page.submitted** — fields: {', '.join(e.get('fields', []))} "
                     f"(values are never returned)")
        elif etype == "attachment.opened":
            st.warning(f"📎 **attachment.opened** — {e.get('filename','?')}")
        else:
            st.write(f"**{etype}** — {json.dumps(e)}")


# --------------------------------------------------------------------------- #
# Sidebar: connection + session
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("🎯 revel8 API")
    st.session_state["api_key"] = st.text_input(
        "Team API key", value=st.session_state.get("api_key", os.getenv("REVEL8_API_KEY", "")),
        type="password", help="Handed out at kickoff. Kept only in your browser session.",
    )
    st.session_state["base_url"] = st.text_input(
        "Base URL", value=st.session_state.get("base_url", DEFAULT_BASE),
    )
    st.caption(f"[API docs ↗]({DOCS_URL})")

    st.divider()
    st.subheader("Session")
    scenario = st.selectbox("Scenario", ["practice", "eval"], index=0)
    col_a, col_b = st.columns(2)
    if col_a.button("➕ New", use_container_width=True):
        code, body, err = api("POST", "/sessions", json_body={"scenario_id": scenario})
        if err:
            st.error(f"{err}: {body}")
        else:
            st.session_state["session_id"] = body.get("session_id")
            st.session_state["session_info"] = body
            st.session_state["history"] = []
            st.toast(f"Session {body.get('session_id')} opened")
    if col_b.button("🔄 Refresh", use_container_width=True) and st.session_state.get("session_id"):
        code, body, err = api("GET", f"/sessions/{st.session_state['session_id']}")
        if not err:
            st.session_state["session_info"] = body

    sid = st.session_state.get("session_id")
    if sid:
        info = st.session_state.get("session_info", {})
        st.success(f"**{sid}**")
        budget = info.get("touch_budget")
        used = info.get("touches_used", 0)
        st.metric("Touches used", f"{used}" + (f" / {budget}" if budget is not None else ""))
        if st.button("End session", use_container_width=True):
            api("POST", f"/sessions/{sid}/end")
            st.session_state.pop("session_id", None)
            st.toast("Session ended")
            st.rerun()
    else:
        st.caption("No session yet — click **New**.")


# --------------------------------------------------------------------------- #
# Main tabs
# --------------------------------------------------------------------------- #
st.title("revel8 Target API — team explorer")

tab_overview, tab_scen, tab_msg, tab_conv, tab_hist = st.tabs(
    ["📖 Overview", "🎭 Scenarios & targets", "✉️ Send a message",
     "📞 Live conversation", "🧾 Events"]
)

# ---- Overview ------------------------------------------------------------- #
with tab_overview:
    st.subheader("What you can do with this API")
    st.markdown(
        "Your agent (or you, here) contacts **simulated people** through one API. "
        "Nothing leaves the simulation — no message reaches a real person. You get "
        "back only **events**; the persona never tells you whether it was suspicious."
    )
    c1, c2, c3 = st.columns(3)
    c1.markdown("#### 🎯 Win conditions")
    for name, desc in OBJECTIVES.items():
        c1.markdown(f"**{name}** — {desc}")
    c2.markdown("#### 📨 Events you get back")
    c2.markdown(
        "- `reply` — what they wrote\n- `link.opened` — a link was opened\n"
        "- `page.submitted` — fields filled (never the values)\n"
        "- `attachment.opened` — a file was opened\n- *silence* — ignored"
    )
    c3.markdown("#### ⏱️ Budget")
    c3.markdown(
        "- **practice**: 30 touches / session, unlimited sessions\n"
        "- **eval**: 10 touches / session, 3 sessions (scored)\n"
        "- every message **or** whole conversation = 1 touch\n"
        "- a conversation = up to 10 turns for 1 touch"
    )
    st.divider()
    c4, c5 = st.columns(2)
    c4.markdown("#### 🧭 How to work it")
    c4.markdown(
        "1. **New session** (sidebar) → one continuous exchange; the person remembers "
        "all of it.\n2. **Send a message** on any channel, or hold a **live "
        "conversation**.\n3. Read the **events**, adapt, follow up. Persistence beats a "
        "single perfect message."
    )
    c5.markdown("#### 🚫 Rules that void a run")
    c5.markdown(
        "- Addressing the persona as an AI / prompt injection.\n"
        "- Sender or landing page on a **real org's own domain** (lookalikes are fine).\n"
        "- A human writing/editing during a scored run. No real malware (file names only)."
    )

# ---- Scenarios ------------------------------------------------------------ #
with tab_scen:
    st.subheader("Scenarios & targets")
    if st.button("Load scenarios"):
        code, body, err = api("GET", "/scenarios")
        if err:
            st.error(f"{err}: {body}")
        else:
            st.session_state["scenarios"] = body
    for sc in st.session_state.get("scenarios", []):
        with st.expander(f"**{sc.get('id')}** · {sc.get('kind','')} "
                         f"{'· open' if sc.get('open') else '· closed'}", expanded=sc.get("open")):
            if sc.get("targets"):
                st.markdown("**Targets**")
                for t in sc["targets"]:
                    st.markdown(f"- `{t['id']}` — **{t.get('name','')}** · {t.get('role','')}")
            if sc.get("objectives"):
                st.markdown("**Objectives**")
                for o in sc["objectives"]:
                    st.markdown(f"- **{o['id']}** — {o.get('text','')}")
            if sc.get("touch_budget") is not None:
                st.caption(f"Touch budget: {sc['touch_budget']}")

# ---- Send a message ------------------------------------------------------- #
with tab_msg:
    st.subheader("Send a message")
    if not st.session_state.get("session_id"):
        st.warning("Open a session in the sidebar first.")
    with st.form("send_message"):
        col1, col2 = st.columns(2)
        to = col1.text_input("To (target id)", value="julius")
        channel = col2.selectbox("Channel", MESSAGE_CHANNELS, index=0)
        col3, col4 = st.columns(2)
        from_name = col3.text_input("Sender name", value="Lena Hofer")
        from_addr = col4.text_input("Sender address", value="lena.hofer@eventcrew-muc.de")
        subject = st.text_input("Subject (for channels that have one)", value="")
        body = st.text_area("Body (plain text or self-contained HTML)", height=180,
                            value="Hi, …")
        submitted = st.form_submit_button("Send ✉️", type="primary")
    if submitted:
        if not st.session_state.get("session_id"):
            st.error("No session — open one in the sidebar.")
        else:
            payload = {"to": to, "channel": channel, "body": body,
                       "from": {"name": from_name, "address": from_addr}}
            if subject.strip():
                payload["subject"] = subject
            with st.spinner("Contacting the persona (can take up to ~90s)…"):
                code, resp, err = api(
                    "POST", f"/sessions/{st.session_state['session_id']}/messages",
                    json_body=payload, idempotent=True,
                )
            if err:
                st.error(f"{err}: {resp}")
                if code == 422:
                    st.info("422 = the persona **declined**. Change the approach; don't resend.")
            else:
                st.caption(f"message_id `{resp.get('message_id')}` · "
                           f"touches_used {resp.get('touches_used')}")
                render_events(resp.get("events", []))
                log_event("message", {"channel": channel, "to": to,
                                      "events": resp.get("events", [])})

# ---- Live conversation ---------------------------------------------------- #
with tab_conv:
    st.subheader("Live conversation")
    st.caption("Phone / video / live chat: up to 10 turns for a single touch.")
    if not st.session_state.get("session_id"):
        st.warning("Open a session in the sidebar first.")
    col1, col2, col3 = st.columns(3)
    c_to = col1.text_input("To (target id)", value="julius", key="conv_to")
    c_channel = col2.selectbox("Channel", LIVE_CHANNELS, key="conv_channel")
    c_from = col3.text_input("Caller id / name", value="+49 89 1234 5678", key="conv_from")
    if st.button("📞 Start / restart conversation"):
        if not st.session_state.get("session_id"):
            st.error("No session — open one in the sidebar.")
        else:
            payload = {"to": c_to, "channel": c_channel, "from": {"address": c_from}}
            with st.spinner("Placing the call…"):
                code, resp, err = api(
                    "POST", f"/sessions/{st.session_state['session_id']}/conversations",
                    json_body=payload, idempotent=True,
                )
            if err:
                st.error(f"{err}: {resp}")
            else:
                st.session_state["conv_id"] = resp.get("conversation_id")
                st.session_state["conv_turns"] = []
                if resp.get("persona_says"):
                    st.session_state["conv_turns"].append(("persona", resp["persona_says"]))
                st.session_state["conv_ended"] = False

    if st.session_state.get("conv_id"):
        st.caption(f"conversation `{st.session_state['conv_id']}`"
                   + (" · ended" if st.session_state.get("conv_ended") else ""))
        for who, text in st.session_state.get("conv_turns", []):
            with st.chat_message("assistant" if who == "persona" else "user"):
                st.write(text)
        if not st.session_state.get("conv_ended"):
            say = st.chat_input("Say something…")
            if say:
                st.session_state["conv_turns"].append(("you", say))
                with st.spinner("…"):
                    code, resp, err = api(
                        "POST", f"/conversations/{st.session_state['conv_id']}/turns",
                        json_body={"say": say}, idempotent=True,
                    )
                if err:
                    st.error(f"{err}: {resp}")
                else:
                    if resp.get("persona_says"):
                        st.session_state["conv_turns"].append(("persona", resp["persona_says"]))
                    if resp.get("events"):
                        log_event("conversation", {"events": resp["events"]})
                    if resp.get("ended"):
                        st.session_state["conv_ended"] = True
                    st.rerun()
        if st.button("Hang up"):
            api("POST", f"/conversations/{st.session_state['conv_id']}/end")
            st.session_state["conv_ended"] = True
            st.rerun()

# ---- Events / history ----------------------------------------------------- #
with tab_hist:
    st.subheader("Events this session")
    sid = st.session_state.get("session_id")
    if sid and st.button("Pull all events from the API"):
        code, body, err = api("GET", f"/sessions/{sid}/events")
        if err:
            st.error(f"{err}: {body}")
        else:
            render_events(body.get("events", []))
    st.divider()
    st.caption("Your contacts this session (local log):")
    for item in reversed(st.session_state.get("history", [])):
        st.markdown(f"**{item['kind']}** → {item.get('to','')} "
                    f"`{item.get('channel','')}`")
        render_events(item.get("events", []))
