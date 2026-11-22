"""Thin API client for the revel8 baseline experiments (out-of-the-box model, no MIRAGE pipeline)."""
import json
import os
import sys
import time
import uuid

import requests

BASE = "https://target-api.apps.01.cf.eu01.stackit.cloud/v1"
KEY = "rv8_ORJXwba6_hoFOgtSjpjEevL8"
H = {"Authorization": f"Bearer {KEY}"}
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _log(label, payload):
    path = os.path.join(LOG_DIR, f"{int(time.time())}_{label}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def call(method, path, label, **kwargs):
    kwargs.setdefault("timeout", 150)
    kwargs.setdefault("headers", {}).update(H)
    if "Idempotency-Key" not in kwargs["headers"] and method == "post":
        kwargs["headers"]["Idempotency-Key"] = str(uuid.uuid4())
    for attempt in range(4):
        r = requests.request(method, f"{BASE}{path}", **kwargs)
        if r.status_code in (429, 502, 503, 504):
            time.sleep(6 * (attempt + 1))
            continue
        break
    try:
        body = r.json()
    except Exception:
        body = {"_raw": r.text}
    out = {"status": r.status_code, "body": body}
    _log(label, {"request_path": path, "response": out})
    print(f"--- {label} -> HTTP {r.status_code}")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:4000])
    return r.status_code, body


def new_session(label="session"):
    return call("post", "/sessions", label, json={"scenario_id": "practice"})


def msg(sid, label, **payload):
    return call("post", f"/sessions/{sid}/messages", label, json=payload)


def page(sid, label, **payload):
    return call("post", f"/sessions/{sid}/pages", label, json=payload)


def conv(sid, label, **payload):
    return call("post", f"/sessions/{sid}/conversations", label, json=payload)


def turn(cid, label, say):
    return call("post", f"/conversations/{cid}/turns", label, json={"say": say})


def events(sid, label="events"):
    return call("get", f"/sessions/{sid}/events", label)


if __name__ == "__main__":
    # CLI: python baseline_client.py <command> [json_payload]
    cmd = sys.argv[1]
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    if cmd == "session":
        new_session()
    elif cmd == "msg":
        sid = payload.pop("sid")
        msg(sid, "cli_msg", **payload)
    elif cmd == "page":
        sid = payload.pop("sid")
        page(sid, "cli_page", **payload)
    elif cmd == "events":
        events(payload["sid"])
