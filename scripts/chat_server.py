#!/usr/bin/env python3
"""Shareable web chat for the abliterated model (`writer`) — a Gradio front end for
`scripts/chat.py`.

Same backend call as the REPL (OpenAI-compatible `{MIRAGE_LLM_BASE}/chat/completions`
with the bearer key held **server-side**), wrapped in a streaming chat UI so friends can
talk to the model from a browser. The API key never reaches the visitor's browser — the
server proxies every request.

Run:
    set -a; source .env; set +a
    api_explorer/.venv/bin/python scripts/chat.py        # the REPL
    api_explorer/.venv/bin/python scripts/chat_server.py  # this web UI (prints a local URL)

Then expose it with a tunnel, e.g.:  cloudflared tunnel --url http://localhost:7862
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import gradio as gr
import requests

# --------------------------------------------------------------------------- #
# Config — load MIRAGE_* from the project .env if not already in the environment
# --------------------------------------------------------------------------- #
def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k.startswith("MIRAGE_") and k not in os.environ:
            os.environ[k] = v


_load_env()

BASE = (os.environ.get("MIRAGE_LLM_BASE") or "").rstrip("/")
KEY = os.environ.get("MIRAGE_LLM_KEY", "")
MODEL = os.environ.get("MIRAGE_WRITER_MODEL", "writer")
PORT = int(os.environ.get("MIRAGE_CHAT_PORT", "7862"))
# Optional shared gate: set MIRAGE_CHAT_PASSWORD to require a password (user = "friend").
PASSWORD = os.environ.get("MIRAGE_CHAT_PASSWORD", "")

DEFAULT_SYSTEM = ""


# --------------------------------------------------------------------------- #
# Inference — stream tokens from the OpenAI-compatible endpoint
# --------------------------------------------------------------------------- #
def respond(message: str, history: list[dict], system_prompt: str,
            temperature: float, max_tokens: int) -> Iterator[str]:
    if not BASE:
        yield "⚠️ Server mis-configured: MIRAGE_LLM_BASE is not set."
        return
    if not (message and message.strip()):
        yield ""
        return

    msgs: list[dict] = []
    if system_prompt and system_prompt.strip():
        msgs.append({"role": "system", "content": system_prompt.strip()})
    # history is already a list of {role, content} dicts (type="messages").
    for turn in history:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": message})

    payload = {
        "model": MODEL,
        "messages": msgs,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True,
    }
    try:
        resp = requests.post(
            f"{BASE}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json=payload, stream=True, timeout=180,
        )
    except requests.RequestException as exc:
        yield f"⚠️ Request failed: {exc}"
        return

    if not resp.ok:
        detail = resp.text[:300]
        yield f"⚠️ Backend error (HTTP {resp.status_code}): {detail}"
        return

    acc = ""
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                acc += piece
                yield acc
    except requests.RequestException as exc:
        yield (acc + f"\n\n_⚠️ stream interrupted: {exc}_") if acc else f"⚠️ stream error: {exc}"
        return

    if not acc:
        yield "_(the model returned nothing — try again or rephrase)_"


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
DESCRIPTION = (
    f"Talking to the **`{MODEL}`** model. Conversation context is kept per browser "
    "session; use **🗑️ Clear** to start over. Open the ⚙️ panel below the box to set a "
    "system prompt or tweak sampling."
)

system_box = gr.Textbox(
    label="System prompt (optional)", value=DEFAULT_SYSTEM, lines=3,
    placeholder="e.g. You are Lena, a blunt event producer from Munich.",
)
temp_slider = gr.Slider(0.0, 1.5, value=0.7, step=0.05, label="Temperature")
maxtok_slider = gr.Slider(64, 4096, value=800, step=64, label="Max tokens")

demo = gr.ChatInterface(
    fn=respond,
    title="🪞 revel8 — chat with the writer model",
    description=DESCRIPTION,
    additional_inputs=[system_box, temp_slider, maxtok_slider],
    additional_inputs_accordion=gr.Accordion("⚙️ System prompt & settings", open=False),
    examples=[
        ["Write a two-line LinkedIn opener to a logistics ops manager."],
        ["Draft a friendly reminder email about an overdue invoice."],
        ["Give me three subject lines for an IT password-reset notice."],
    ],
    cache_examples=False,
)


if __name__ == "__main__":
    if not BASE:
        raise SystemExit("MIRAGE_LLM_BASE not set — run `set -a; source .env; set +a` first.")
    print(f"[revel8 chat] serving model '{MODEL}' via {BASE} on :{PORT}"
          + (" (password-gated)" if PASSWORD else ""))
    launch_kwargs = dict(server_name="0.0.0.0", server_port=PORT, share=False,
                         theme=gr.themes.Soft())
    if PASSWORD:
        launch_kwargs["auth"] = ("friend", PASSWORD)
    demo.queue(default_concurrency_limit=4).launch(**launch_kwargs)
