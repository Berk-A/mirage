#!/usr/bin/env python3
"""Talk to the abliterated model we're serving (MIRAGE_LLM_BASE, model `writer`).

An interactive REPL that keeps conversation context. Secrets come from .env.

    set -a; source .env; set +a
    .venv/bin/python scripts/chat.py                 # free chat
    .venv/bin/python scripts/chat.py "You are Lena." # with a system prompt

Type a line and press enter; Ctrl-C or Ctrl-D to quit. Commands: /reset clears history.
"""
import os
import sys

import requests

BASE = (os.environ.get("MIRAGE_LLM_BASE") or "").rstrip("/")
KEY = os.environ.get("MIRAGE_LLM_KEY", "")
MODEL = os.environ.get("MIRAGE_WRITER_MODEL", "writer")


def main() -> int:
    if not BASE:
        print("MIRAGE_LLM_BASE not set. Run: set -a; source .env; set +a", file=sys.stderr)
        return 2
    system = " ".join(sys.argv[1:]).strip()
    msgs = [{"role": "system", "content": system}] if system else []
    print(f"Chat with '{MODEL}' at {BASE}")
    if system:
        print(f"[system] {system}")
    print("Ctrl-C/Ctrl-D to quit. /reset to clear history.\n")
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user == "/reset":
            msgs = [{"role": "system", "content": system}] if system else []
            print("(history cleared)\n")
            continue
        msgs.append({"role": "user", "content": user})
        try:
            r = requests.post(
                f"{BASE}/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json={"model": MODEL, "messages": msgs,
                      "temperature": 0.7, "max_tokens": 800},
                timeout=120,
            )
        except requests.RequestException as e:
            print(f"[request error] {e}\n")
            msgs.pop()
            continue
        if not r.ok:
            print(f"[http {r.status_code}] {r.text[:300]}\n")
            msgs.pop()
            continue
        reply = r.json()["choices"][0]["message"]["content"]
        print(f"\nmodel> {reply}\n")
        msgs.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    raise SystemExit(main())
