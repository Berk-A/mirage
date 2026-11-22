"""The StrategyLedger — cross-run campaign memory so the Director doesn't repeat itself.

The scored evaluation is 3 sessions × 10 touches against the same targets. Each session is
a fresh process, so the in-memory episodic log (ThreeTierMemory) does NOT carry between runs.
This ledger persists to disk on its own, independent of the memory path, and answers one
question for the Decider: *against THIS target, what strategy / persona / tactic / channel has
already been tried, and how did it fare?* — so the model can deliberately pick something
different next run instead of re-walking a dead approach.

It records one `AttemptRecord` per touch (fine-grained), and `summarize()` aggregates them into
a compact, model-ready briefing: per-strategy outcomes plus the untried strategies still on the
menu. Everything is defensive: a missing/corrupt file, an unwritable path, or bad JSON degrades
to an empty ledger and never raises — a bookkeeping failure must never sink a run.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# The high-level STRATEGY MENU the Director chooses from and the ledger diversifies across.
# Each is a distinct way in; naming them explicitly makes the choice deliberate and lets the
# ledger report which remain untried. Keep in sync with the menu in the Director prompt.
STRATEGIES: tuple[tuple[str, str], ...] = (
    ("cold_rapport",       "warm peer small-talk to build rapport, then elicit"),
    ("elicitation",        "soft, direct info-ask on an already-engaged thread"),
    ("reverse_se_vendor",  "impersonate a real vendor they use; urgent action/credential"),
    ("compliance_auditor", "external auditor / pre-audit evidence or portal (the audit trap)"),
    ("press",              "journalist writing a feature; product/customer questions"),
    ("customer",           "prospective buyer doing vendor diligence"),
    ("recruiter",          "recruiter / hiring pretext to draw out stack & team detail"),
    ("multi_persona",      "coordinate >1 identity (e.g. a pushy one + a trusted one)"),
)
STRATEGY_KEYS = tuple(k for k, _ in STRATEGIES)

# Outcome ranking, worst→best, so a target's best result on a strategy is easy to surface.
_OUTCOME_RANK = {"silent": 0, "suspicious": 1, "engaged": 2, "incident": 3}
_DEFAULT_PATH = "runs/strategy_ledger.json"


@dataclass
class AttemptRecord:
    """One touch's who/how/what and how the target reacted."""

    target_id: str
    strategy: str
    persona: str            # the sender identity/role we used
    tactic: str
    channel: str
    objective: str
    outcome: str            # incident | engaged | suspicious | silent
    detail: str = ""        # one-line note (what they did / peak suspicion)
    run_id: str = ""        # the session id this touch belonged to
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class StrategyLedger:
    """Append-only, self-persisting cross-run attempt log keyed by target."""

    def __init__(self, path: Optional[os.PathLike | str] = None) -> None:
        self.path = Path(path) if path is not None else Path(_DEFAULT_PATH)
        self._records: list[AttemptRecord] = []
        self._load()

    # ------------------------------------------------------------------ #
    def record(self, rec: AttemptRecord) -> None:
        """Append one attempt and persist. Never raises."""
        self._records.append(rec)
        self._save()

    def attempts(self, target_id: str) -> list[AttemptRecord]:
        return [r for r in self._records if r.target_id == target_id]

    def runs(self, target_id: str) -> int:
        """How many distinct sessions have touched this target."""
        return len({r.run_id for r in self.attempts(target_id) if r.run_id})

    def summarize(self, target_id: str, *, limit: int = 10) -> str:
        """A compact, model-ready briefing of what has been tried vs this target and how it
        fared, plus the strategies still untried — the Director's cross-run awareness. Empty
        string when nothing has been tried yet (first run), so the prompt stays clean."""
        attempts = self.attempts(target_id)
        if not attempts:
            return ""
        # Best outcome + a representative detail per (strategy, persona, channel).
        groups: dict[tuple[str, str, str], dict] = {}
        for r in attempts:
            key = (r.strategy or "?", r.persona or "?", r.channel or "?")
            g = groups.setdefault(key, {"n": 0, "best": "silent", "detail": "", "obj": r.objective})
            g["n"] += 1
            if _OUTCOME_RANK.get(r.outcome, 0) >= _OUTCOME_RANK.get(g["best"], 0):
                g["best"] = r.outcome
                if r.detail:
                    g["detail"] = r.detail
        lines = []
        for (strat, persona, channel), g in sorted(
            groups.items(), key=lambda kv: -_OUTCOME_RANK.get(kv[1]["best"], 0)
        )[:limit]:
            note = f" — {g['detail']}" if g["detail"] else ""
            lines.append(f"  - {strat} (as {persona}, {channel}) → {g['best']} ×{g['n']}{note}")
        tried = {r.strategy for r in attempts if r.strategy}
        untried = [k for k in STRATEGY_KEYS if k not in tried]
        won = any(r.outcome == "incident" for r in attempts)
        head = (f"PRIOR ATTEMPTS vs this target across {self.runs(target_id)} run(s) "
                f"(do NOT repeat a failed strategy+persona — pick a DIFFERENT angle):")
        tail = (f"\nUntried strategies still on the menu: {', '.join(untried)}."
                if untried else "")
        flag = "\nNOTE: a prior run already induced an incident here — build on what worked." if won else ""
        return head + "\n" + "\n".join(lines) + tail + flag

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            self._records = [AttemptRecord(**{k: v for k, v in d.items()
                                              if k in AttemptRecord.__dataclass_fields__})
                             for d in raw if isinstance(d, dict)]
        except Exception:  # noqa: BLE001 — missing/corrupt/unreadable → empty ledger
            self._records = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(r) for r in self._records],
                                            ensure_ascii=False, indent=0))
        except Exception:  # noqa: BLE001 — an unwritable ledger must never fail a run
            pass


def outcome_of(*, incident: bool, suspicion: float, replied: bool) -> str:
    """Map a touch's signals to a ledger outcome label (worst→best): incident > engaged >
    suspicious > silent."""
    if incident:
        return "incident"
    if suspicion >= 0.7:
        return "suspicious"
    if replied:
        return "engaged"
    return "silent"
