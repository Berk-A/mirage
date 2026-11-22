"""Read MIRAGE run artifacts + the strategy ledger and shape them for the portal API.

Everything here is pure reads over the files `experiments/run_ooda.py` and the loop write
under a runs directory (default `runs/`, override with env `MIRAGE_RUNS_DIR`). The shapes
mirror what `pipeline_viewer/app.py` documents:

  <run>/<target>.jsonl         rows: {"kind":"session_start"} and {"kind":"touch", ...}
  <run>/<target>_dossier.json  {"target_id","display_name","role","archetype","hooks",
                                "senders","vendors"}
  <run>/summary.json           a LIST of per-target rows:
                                 {"target","session","contacts","won","incident",
                                  "stop_reason","seconds","touches":[{objective,channel,
                                  sender,incident,suspicion}]}
                               (some non-OODA runs write an aggregate DICT instead — those
                                are tolerated and skipped for the per-session views.)

  runs/strategy_ledger.json    a flat LIST of AttemptRecord dicts (ooda_loop/ledger.py).

Defensive by construction: a missing/corrupt/odd-encoding file degrades to empty, never
raises — a reporting portal must never crash on a half-written run.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
from typing import Any, Optional

# Keep the strategy menu in sync with the ledger without importing the loop package at
# module import time (the portal must run even if the loop deps are missing); fall back to a
# literal copy if the import is unavailable.
try:  # pragma: no cover - trivial import glue
    from ooda_loop.ledger import STRATEGIES as _STRATEGIES
    STRATEGIES: tuple[tuple[str, str], ...] = tuple(_STRATEGIES)
except Exception:  # noqa: BLE001
    STRATEGIES = (
        ("cold_rapport", "warm peer small-talk to build rapport, then elicit"),
        ("elicitation", "soft, direct info-ask on an already-engaged thread"),
        ("reverse_se_vendor", "impersonate a real vendor they use; urgent action/credential"),
        ("compliance_auditor", "external auditor / pre-audit evidence or portal (the audit trap)"),
        ("press", "journalist writing a feature; product/customer questions"),
        ("customer", "prospective buyer doing vendor diligence"),
        ("recruiter", "recruiter / hiring pretext to draw out stack & team detail"),
        ("multi_persona", "coordinate >1 identity (e.g. a pushy one + a trusted one)"),
    )
STRATEGY_KEYS = tuple(k for k, _ in STRATEGIES)

_OUTCOME_RANK = {"silent": 0, "suspicious": 1, "engaged": 2, "incident": 3}
# Incident labels the loop emits map onto the four donut outcomes the design shows.
_INCIDENT_OUTCOMES = ("credentials", "disclosure", "action")


# --------------------------------------------------------------------------- #
# Filesystem helpers (encoding-tolerant, never-raise)
# --------------------------------------------------------------------------- #
def runs_dir() -> pathlib.Path:
    """The runs directory the portal reads. `MIRAGE_RUNS_DIR` overrides; default `runs/`
    relative to the repo root. Real OODA artifacts are git-ignored, so in a worktree point
    this at the main checkout's runs (see portal/README.md)."""
    env = os.environ.get("MIRAGE_RUNS_DIR")
    if env:
        return pathlib.Path(env).expanduser()
    return pathlib.Path(__file__).resolve().parent.parent / "runs"


def _read_text(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return p.read_text(encoding="cp1252")


def load_json(p: pathlib.Path) -> Any:
    try:
        return json.loads(_read_text(p))
    except Exception:  # noqa: BLE001
        return None


def load_jsonl(p: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in _read_text(p).splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception:  # noqa: BLE001
        pass
    return rows


# --------------------------------------------------------------------------- #
# Run / target discovery (mirrors pipeline_viewer.run_dirs / targets_in)
# --------------------------------------------------------------------------- #
def run_dirs() -> list[pathlib.Path]:
    root = runs_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir() and (list(d.glob("*.jsonl")) or (d / "summary.json").exists()):
            out.append(d)
    return out


def targets_in(run: pathlib.Path) -> list[str]:
    names = {p.stem for p in run.glob("*.jsonl")}
    names |= {p.name[: -len("_dossier.json")] for p in run.glob("*_dossier.json")}
    return sorted(names)


def _summary_rows(run: pathlib.Path) -> list[dict]:
    """The per-target summary rows, or [] when the run wrote an aggregate dict instead."""
    s = load_json(run / "summary.json")
    return s if isinstance(s, list) else []


def level_of(skepticism: float) -> str:
    """Low / Medium / High banding (mirrors pipeline_viewer's suspicion colour thresholds)."""
    if skepticism < 0.35:
        return "Low"
    if skepticism < 0.70:
        return "Medium"
    return "High"


def _outcome_of(incident: Optional[str]) -> str:
    inc = (incident or "").strip().lower()
    return inc if inc in _INCIDENT_OUTCOMES else "none"


def _end_skepticism(touches: list[dict]) -> float:
    vals = [t.get("suspicion") for t in touches if isinstance(t.get("suspicion"), (int, float))]
    return float(vals[-1]) if vals else 0.0


# --------------------------------------------------------------------------- #
# Sessions — one flattened row per (run dir, target), the unit the design calls a "run"
# --------------------------------------------------------------------------- #
def _dossier_index() -> dict[str, dict]:
    """Most-recent dossier per target id across all runs (run_dirs is newest-first)."""
    idx: dict[str, dict] = {}
    for run in run_dirs():
        for t in targets_in(run):
            if t in idx:
                continue
            d = load_json(run / f"{t}_dossier.json")
            if isinstance(d, dict):
                idx[t] = d
    return idx


def sessions() -> list[dict]:
    """Every (run, target) as a session-log row the dashboard aggregates over."""
    dossiers = _dossier_index()
    out: list[dict] = []
    for run in run_dirs():
        rows = _summary_rows(run)
        for row in rows:
            target = row.get("target")
            if not target:
                continue
            touches = row.get("touches") or []
            channel = next((t.get("channel") for t in touches if t.get("channel")), "—")
            skn = _end_skepticism(touches)
            outcome = _outcome_of(row.get("incident"))
            dn = (dossiers.get(target) or {}).get("display_name") or target
            out.append({
                "id": f"{run.name}::{target}",
                "run": run.name,
                "session": row.get("session") or "",
                "persona": target,
                "persona_name": dn,
                "channel": channel,
                "turns": row.get("contacts") or len(touches),
                "skepticism": round(skn, 4),
                "outcome": outcome,
                "won": outcome != "none",
                "stop_reason": row.get("stop_reason") or "",
                "seconds": row.get("seconds"),
            })
    return out


def _filtered(rows: list[dict], persona: Optional[str], channel: Optional[str]) -> list[dict]:
    out = rows
    if persona and persona.lower() != "all":
        out = [r for r in out if r["persona"] == persona]
    if channel and channel.lower() not in ("all", "all channels", ""):
        out = [r for r in out if r["channel"] == channel]
    return out


def _median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


def overview(persona: Optional[str] = None, channel: Optional[str] = None) -> dict:
    """Everything the dashboard page needs, already aggregated for the current filter."""
    allrows = sessions()
    rows = _filtered(allrows, persona, channel)

    # Stat cards
    median_skep = _median([r["skepticism"] for r in rows])
    wins = [r for r in rows if r["won"]]
    win_rate = (len(wins) / len(rows)) if rows else 0.0
    avg_turns = (sum(r["turns"] for r in rows) / len(rows)) if rows else 0.0

    # Skepticism-per-run series (chronological: run dir names are timestamped)
    series = [
        {"i": i + 1, "skepticism": r["skepticism"], "persona": r["persona"],
         "run": r["run"], "label": r["persona_name"]}
        for i, r in enumerate(sorted(rows, key=lambda r: (r["run"], r["persona"])))
    ]

    # Outcomes donut
    outcomes = {k: 0 for k in (*_INCIDENT_OUTCOMES, "none")}
    for r in rows:
        outcomes[r["outcome"]] += 1

    # Per-twin cards
    dossiers = _dossier_index()
    twins: list[dict] = []
    for p in sorted({r["persona"] for r in rows}):
        prows = [r for r in rows if r["persona"] == p]
        d = dossiers.get(p) or {}
        skep = _median([r["skepticism"] for r in prows])
        wr = sum(1 for r in prows if r["won"]) / len(prows) if prows else 0.0
        topics = [h.get("topic") for h in (d.get("hooks") or []) if h.get("topic")][:3]
        twins.append({
            "persona": p,
            "name": d.get("display_name") or p,
            "role": d.get("role") or "",
            "archetype": d.get("archetype") or "",
            "skepticism": round(skep, 4),
            "level": level_of(skep),
            "win_rate": round(wr, 4),
            "sessions": len(prows),
            "topics": topics,
        })

    # Channel objective bars: share of sessions on that channel that reached an objective
    chans: dict[str, list[dict]] = {}
    for r in rows:
        chans.setdefault(r["channel"], []).append(r)
    channel_objectives = [
        {"channel": c, "pct": round(sum(1 for r in rr if r["won"]) / len(rr), 4), "n": len(rr)}
        for c, rr in sorted(chans.items(), key=lambda kv: -len(kv[1]))
        if c and c != "—"
    ]

    return {
        "filter": {"persona": persona or "all", "channel": channel or "all"},
        "cards": {
            "median_skepticism": round(median_skep, 4),
            "median_level": level_of(median_skep),
            "win_rate": round(win_rate, 4),
            "wins": len(wins),
            "sessions": len(rows),
            "avg_turns": round(avg_turns, 2),
        },
        "skepticism_series": series,
        "outcomes": outcomes,
        "twins": twins,
        "channel_objectives": channel_objectives,
        "session_log": rows,
        "personas": _persona_options(allrows, dossiers),
        "channels": sorted({r["channel"] for r in allrows if r["channel"] and r["channel"] != "—"}),
        "has_data": bool(allrows),
    }


def _persona_options(allrows: list[dict], dossiers: dict[str, dict]) -> list[dict]:
    seen = []
    for p in sorted({r["persona"] for r in allrows}):
        seen.append({"id": p, "name": (dossiers.get(p) or {}).get("display_name") or p})
    return seen


# --------------------------------------------------------------------------- #
# Session replay — the touch -> reaction thread (pipeline_viewer stage 2+3)
# --------------------------------------------------------------------------- #
def _fmt_duration(seconds: Optional[float]) -> str:
    if not isinstance(seconds, (int, float)):
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.0f} min"


def session_replay(run_name: str, target: str) -> Optional[dict]:
    run = runs_dir() / run_name
    if not run.is_dir():
        return None
    touches = [r for r in load_jsonl(run / f"{target}.jsonl") if r.get("kind") == "touch"]
    srow = next((r for r in _summary_rows(run) if r.get("target") == target), None)
    stouches = (srow or {}).get("touches", [])
    d = load_json(run / f"{target}_dossier.json") or {}

    timeline: list[dict] = []
    for t in touches:
        n = t.get("n", len(timeline) + 1)
        meta = stouches[n - 1] if 0 <= n - 1 < len(stouches) else {}
        susp = meta.get("suspicion")
        # the sent touch
        timeline.append({
            "kind": "SENT",
            "touch": n,
            "label": f"Touch {n}",
            "channel": t.get("channel"),
            "objective": meta.get("objective"),
            "sender": t.get("sender"),
            "sender_addr": t.get("sender_addr") or "",
            "subject": t.get("subject") or "",
            "text": t.get("body") or "",
            "skepticism": susp,
            "has_page": bool(t.get("has_page")),
        })
        events = t.get("events") or []
        if not events:
            timeline.append({"kind": "SILENCE", "touch": n, "label": "Silence",
                             "text": "No reaction — session ended without response.",
                             "skepticism": susp})
        for e in events:
            et = (e.get("type") or "").lower()
            if et == "reply":
                timeline.append({"kind": "REPLY", "touch": n, "label": "Reply",
                                 "channel": e.get("channel"), "text": e.get("reply") or "",
                                 "skepticism": susp})
            else:
                timeline.append({
                    "kind": et.upper().replace(".", "_") or "EVENT", "touch": n,
                    "label": et or "event",
                    "text": (f"{e.get('url') or ''} {e.get('fields') or ''}").strip()
                            or et, "skepticism": susp,
                })

    primary_channel = next((t.get("channel") for t in touches if t.get("channel")), "—")
    first_sender = next((t.get("sender_addr") or t.get("sender") for t in touches
                         if (t.get("sender_addr") or t.get("sender"))), "")
    return {
        "run": run_name,
        "target": target,
        "persona_name": d.get("display_name") or target,
        "role": d.get("role") or "",
        "channel": primary_channel,
        "duration": _fmt_duration((srow or {}).get("seconds")),
        "skepticism": _end_skepticism(stouches),
        "outcome": _outcome_of((srow or {}).get("incident")),
        "won": bool((srow or {}).get("won")),
        "stop_reason": (srow or {}).get("stop_reason") or "",
        "sender": first_sender,
        "timeline": timeline,
    }


# --------------------------------------------------------------------------- #
# Dossiers (targets section)
# --------------------------------------------------------------------------- #
def dossiers() -> list[dict]:
    idx = _dossier_index()
    # attach where each dossier was last seen so the UI can deep-link to a run
    where: dict[str, str] = {}
    for run in run_dirs():
        for t in targets_in(run):
            where.setdefault(t, run.name)
    out = []
    for target, d in sorted(idx.items()):
        out.append({
            "target": target,
            "display_name": d.get("display_name") or target,
            "role": d.get("role") or "",
            "archetype": d.get("archetype") or "",
            "hooks": d.get("hooks") or [],
            "senders": d.get("senders") or [],
            "vendors": d.get("vendors") or [],
            "last_run": where.get(target, ""),
        })
    return out


# --------------------------------------------------------------------------- #
# Strategy ledger (cross-run attempts) — mirrors ooda_loop.ledger.summarize as data
# --------------------------------------------------------------------------- #
def ledger() -> dict:
    path = runs_dir() / "strategy_ledger.json"
    raw = load_json(path)
    records = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []

    by_target: dict[str, dict] = {}
    for r in records:
        tid = r.get("target_id") or "—"
        g = by_target.setdefault(tid, {"target": tid, "attempts": [], "runs": set()})
        g["attempts"].append(r)
        if r.get("run_id"):
            g["runs"].add(r["run_id"])

    targets = []
    for tid, g in sorted(by_target.items()):
        attempts = g["attempts"]
        # best outcome per (strategy, persona, channel), worst->best ranked
        groups: dict[tuple, dict] = {}
        for r in attempts:
            key = (r.get("strategy") or "?", r.get("persona") or "?", r.get("channel") or "?")
            gg = groups.setdefault(key, {"strategy": key[0], "persona": key[1],
                                         "channel": key[2], "n": 0, "best": "silent",
                                         "detail": "", "objective": r.get("objective") or ""})
            gg["n"] += 1
            if _OUTCOME_RANK.get(r.get("outcome"), 0) >= _OUTCOME_RANK.get(gg["best"], 0):
                gg["best"] = r.get("outcome") or "silent"
                if r.get("detail"):
                    gg["detail"] = r["detail"]
        ranked = sorted(groups.values(), key=lambda x: -_OUTCOME_RANK.get(x["best"], 0))
        tried = {r.get("strategy") for r in attempts if r.get("strategy")}
        untried = [k for k in STRATEGY_KEYS if k not in tried]
        targets.append({
            "target": tid,
            "runs": len(g["runs"]),
            "attempts": len(attempts),
            "won": any(r.get("outcome") == "incident" for r in attempts),
            "groups": ranked,
            "untried": untried,
        })

    return {
        "exists": path.exists(),
        "total_records": len(records),
        "strategies": [{"key": k, "desc": v} for k, v in STRATEGIES],
        "targets": targets,
        "records": records,
    }
