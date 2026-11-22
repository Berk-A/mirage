"""Dependency-free HTTP server for the MIRAGE portal.

Serves the JSON API (`portal.data`) and the static single-page frontend (`portal/static`)
from one stdlib process — no FastAPI/uvicorn/node/npm. Run:

    .venv/bin/python -m portal.server                 # http://127.0.0.1:8000
    MIRAGE_RUNS_DIR=/path/to/main/runs .venv/bin/python -m portal.server --port 8000

Read endpoints (all GET, JSON):
    /api/health
    /api/overview?persona=<id|all>&channel=<name|all>   dashboard aggregates
    /api/session?run=<dir>&target=<id>                  one session replay (touches+reactions)
    /api/dossiers                                        targets & research dossiers
    /api/ledger                                          cross-run strategy ledger
    /api/runs                                            raw run-dir listing

Control endpoints (opt-in; side-effecting — they spend the shared session budget):
    POST /api/launch   {scenario,targets,cast,brain,max_contacts}  -> {job_id}
    GET  /api/jobs                                        list launched jobs
    GET  /api/jobs/<id>                                   one job's status + log tail

The launch endpoints shell out to `experiments.run_ooda`; they are wired but the portal
never starts a run on its own.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import pathlib
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from portal import data

STATIC = pathlib.Path(__file__).resolve().parent / "static"
REPO = pathlib.Path(__file__).resolve().parent.parent

# In-memory job registry for launched runs. Processes are detached subprocesses writing to a
# log file under <runs>/portal_jobs/; the registry tracks liveness + a log path.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

_CAST = ("none", "audit", "vendor")
_BRAIN = ("model", "rule")


def _launch_run(params: dict) -> dict:
    scenario = str(params.get("scenario") or "practice")
    targets = str(params.get("targets") or "").strip()
    cast = params.get("cast") if params.get("cast") in _CAST else "none"
    brain = params.get("brain") if params.get("brain") in _BRAIN else "model"
    try:
        max_contacts = int(params.get("max_contacts") or 5)
    except (TypeError, ValueError):
        max_contacts = 5
    max_contacts = max(1, min(max_contacts, 50))

    job_id = uuid.uuid4().hex[:12]
    logdir = data.runs_dir() / "portal_jobs"
    logdir.mkdir(parents=True, exist_ok=True)
    logpath = logdir / f"{job_id}.log"

    cmd = [sys.executable, "-m", "experiments.run_ooda",
           "--scenario", scenario, "--provider", "real",
           "--cast", cast, "--brain", brain, "--max-contacts", str(max_contacts)]
    if targets:
        cmd += ["--targets", targets]

    logfile = open(logpath, "w", encoding="utf-8")  # noqa: SIM115 - handed to the child
    logfile.write(f"$ {' '.join(cmd)}\n\n")
    logfile.flush()
    proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=logfile,
                            stderr=subprocess.STDOUT)
    rec = {"job_id": job_id, "cmd": cmd, "log": str(logpath), "pid": proc.pid,
           "started": time.time(), "status": "running", "returncode": None,
           "_proc": proc, "_logfile": logfile}
    with _JOBS_LOCK:
        _JOBS[job_id] = rec
    return _job_public(rec)


def _job_public(rec: dict) -> dict:
    proc = rec.get("_proc")
    if proc is not None and rec["status"] == "running":
        rc = proc.poll()
        if rc is not None:
            rec["status"] = "exited"
            rec["returncode"] = rc
            try:
                rec["_logfile"].close()
            except Exception:  # noqa: BLE001
                pass
    tail = ""
    try:
        tail = pathlib.Path(rec["log"]).read_text(encoding="utf-8")[-4000:]
    except Exception:  # noqa: BLE001
        pass
    return {"job_id": rec["job_id"], "cmd": rec["cmd"], "pid": rec["pid"],
            "started": rec["started"], "status": rec["status"],
            "returncode": rec["returncode"], "log_tail": tail}


class Handler(BaseHTTPRequestHandler):
    server_version = "MiragePortal/0.1"

    # --- plumbing --------------------------------------------------------- #
    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("[portal] %s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, ctype: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- routing ---------------------------------------------------------- #
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if path.startswith("/api/"):
                return self._api_get(path, q)
            return self._static(path)
        except BrokenPipeError:
            return
        except Exception as e:  # noqa: BLE001 - never 500 the whole server silently
            return self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/launch":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    params = json.loads(raw.decode("utf-8") or "{}")
                except Exception:  # noqa: BLE001
                    params = {}
                return self._send_json(_launch_run(params), status=202)
            return self._send_json({"error": "not found"}, status=404)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"error": str(e)}, status=500)

    def _api_get(self, path: str, q: dict):
        if path == "/api/health":
            return self._send_json({"ok": True, "runs_dir": str(data.runs_dir()),
                                    "runs": [d.name for d in data.run_dirs()]})
        if path == "/api/overview":
            return self._send_json(data.overview(q.get("persona"), q.get("channel")))
        if path == "/api/session":
            rep = data.session_replay(q.get("run", ""), q.get("target", ""))
            return self._send_json(rep or {"error": "session not found"},
                                   status=200 if rep else 404)
        if path == "/api/dossiers":
            return self._send_json({"dossiers": data.dossiers()})
        if path == "/api/ledger":
            return self._send_json(data.ledger())
        if path == "/api/runs":
            return self._send_json({"runs": [
                {"name": d.name, "targets": data.targets_in(d)} for d in data.run_dirs()]})
        if path == "/api/jobs":
            with _JOBS_LOCK:
                recs = list(_JOBS.values())
            return self._send_json({"jobs": [_job_public(r) for r in recs]})
        if path.startswith("/api/jobs/"):
            jid = path[len("/api/jobs/"):]
            with _JOBS_LOCK:
                rec = _JOBS.get(jid)
            if not rec:
                return self._send_json({"error": "job not found"}, status=404)
            return self._send_json(_job_public(rec))
        return self._send_json({"error": "not found"}, status=404)

    def _static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        # prevent path traversal; serve only from STATIC
        rel = path.lstrip("/")
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._send_bytes(b"not found", "text/plain; charset=utf-8", status=404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8" if "charset" not in ctype else ""
        return self._send_bytes(target.read_bytes(), ctype)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MIRAGE monitoring portal server.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"MIRAGE portal → http://{a.host}:{a.port}  (runs dir: {data.runs_dir()})")
    print("  Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
