"""Three-tier memory with a tamper-evident, replayable journal.

`ThreeTierMemory` is the concrete `core.interfaces.Memory`. It keeps the three
tiers the Protocol describes distinct on purpose:

  * **working** — the per-session story ledger: the `claims` made so a later move
    never contradicts an earlier one, plus a single `suspicion` estimate per
    session. Scoped by ``session_id`` and meant to be thrown away when the
    session ends.
  * **episodic** — the cross-session `Outcome` log the bandit learns from. Beyond
    the Protocol's `record_outcome`/`outcomes`, it exposes `stats(...)` and
    `success_rate(...)` so a policy can ask "how has this (archetype, arm) done?"
    without re-implementing the aggregation.
  * **semantic** — durable facts are *not* stored here; they are delegated to the
    `DossierProvider`. There is deliberately no method for them.

Journal (verifiable replay)
---------------------------
`journal(session_id, kind, payload)` appends a record; `replay(session_id)`
returns the records as plain dicts in order. Every record carries:

  * ``seq``       — a per-session sequence number, 1-based and monotonic.
  * ``ts``        — a wall-clock timestamp (float seconds), non-decreasing.
  * ``kind``      — the caller's record kind.
  * ``payload``   — the caller's dict.
  * ``prev_hash`` — the hash of the previous record (``GENESIS_HASH`` for the first).
  * ``hash``      — ``sha256(prev_hash + canonical(seq, ts, kind, payload))``.

Because each hash commits to the previous one, altering any past record breaks
every hash after it. `final_hash(session_id)` exposes the chain head and
`verify_chain(session_id)` recomputes the whole chain and reports whether it is
intact. Hashing is stdlib-only (`hashlib` + `json`).

Persistence (optional)
----------------------
With ``path=None`` (the default) everything is in memory. Given a ``path`` (a
directory, in which case ``journal.jsonl`` is used inside it, or a file), each
journal record is also appended to disk as one JSON line, and an existing file
is loaded on construction so a crashed run can resume with its chain intact.
Only the journal is persisted; the working and episodic tiers stay in memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from typing import Optional, Sequence

from core.models import Outcome


class ThreeTierMemory:
    """In-memory (optionally disk-backed) implementation of `core.interfaces.Memory`."""

    #: prev_hash of the first record in any session's chain.
    GENESIS_HASH = "0" * 64
    #: default journal filename used when ``path`` is a directory.
    DEFAULT_JOURNAL_NAME = "journal.jsonl"

    def __init__(self, path: Optional[os.PathLike | str] = None) -> None:
        # working tier
        self._claims: dict[str, list[str]] = defaultdict(list)
        self._suspicion: dict[str, float] = {}
        # episodic tier
        self._outcomes: list[Outcome] = []
        # journal tier
        self._journal: dict[str, list[dict]] = defaultdict(list)

        # optional persistence
        self._path: Optional[str] = self._resolve_path(path)
        if self._path:
            self._load_journal()

    # ------------------------------------------------------------------ #
    # Working tier (per session)
    # ------------------------------------------------------------------ #
    def add_claim(self, session_id: str, claim: str) -> None:
        self._claims[session_id].append(claim)

    def claims(self, session_id: str) -> Sequence[str]:
        return tuple(self._claims.get(session_id, ()))

    def set_suspicion(self, session_id: str, value: float) -> None:
        self._suspicion[session_id] = float(value)

    def get_suspicion(self, session_id: str) -> float:
        return self._suspicion.get(session_id, 0.0)

    # ------------------------------------------------------------------ #
    # Episodic tier (cross session)
    # ------------------------------------------------------------------ #
    def record_outcome(self, outcome: Outcome) -> None:
        self._outcomes.append(outcome)

    def outcomes(self, *, archetype: Optional[str] = None) -> Sequence[Outcome]:
        if archetype is None:
            return tuple(self._outcomes)
        return tuple(o for o in self._outcomes if o.archetype == archetype)

    def _match(
        self, archetype: Optional[str], arm: Optional[str]
    ) -> list[Outcome]:
        return [
            o
            for o in self._outcomes
            if (archetype is None or o.archetype == archetype)
            and (arm is None or o.arm == arm)
        ]

    def stats(
        self, *, archetype: Optional[str] = None, arm: Optional[str] = None
    ) -> dict:
        """Aggregate the episodic log for an (archetype, arm) slice.

        Either filter is optional; omit both for the global picture. Returns a
        plain dict the bandit can read directly::

            {"n", "successes", "success_rate", "avg_suspicion", "avg_contacts"}

        An empty slice yields ``n == 0`` and zeroed rates (never a divide error),
        so a cold arm reads as "no evidence yet" rather than raising.
        """
        matched = self._match(archetype, arm)
        n = len(matched)
        if n == 0:
            return {
                "n": 0,
                "successes": 0,
                "success_rate": 0.0,
                "avg_suspicion": 0.0,
                "avg_contacts": 0.0,
            }
        successes = sum(1 for o in matched if o.success)
        return {
            "n": n,
            "successes": successes,
            "success_rate": successes / n,
            "avg_suspicion": sum(o.suspicion for o in matched) / n,
            "avg_contacts": sum(o.contacts_used for o in matched) / n,
        }

    def success_rate(
        self, *, archetype: Optional[str] = None, arm: Optional[str] = None
    ) -> float:
        """Fraction of successful outcomes in the (archetype, arm) slice, or 0.0
        when the slice is empty. Thin convenience over `stats`."""
        return self.stats(archetype=archetype, arm=arm)["success_rate"]

    # ------------------------------------------------------------------ #
    # Journal tier (append-only, hash-chained, for verifiable replay)
    # ------------------------------------------------------------------ #
    def journal(self, session_id: str, kind: str, payload: dict) -> None:
        chain = self._journal[session_id]
        seq = len(chain) + 1
        prev_hash = chain[-1]["hash"] if chain else self.GENESIS_HASH
        ts = self._next_ts(chain)
        record = {
            "seq": seq,
            "ts": ts,
            "kind": kind,
            "payload": dict(payload),
            "prev_hash": prev_hash,
        }
        record["hash"] = self._record_hash(prev_hash, record)
        chain.append(record)
        if self._path:
            self._append_to_disk(session_id, record)

    def replay(self, session_id: str) -> Sequence[dict]:
        # Hand back copies so callers can't mutate the chain through the result.
        return tuple(dict(r) for r in self._journal.get(session_id, ()))

    def final_hash(self, session_id: str) -> str:
        """The chain head for a session: the last record's hash, or ``GENESIS_HASH``
        if the session has no records yet."""
        chain = self._journal.get(session_id, ())
        return chain[-1]["hash"] if chain else self.GENESIS_HASH

    def verify_chain(self, session_id: str) -> bool:
        """Recompute the whole chain for a session and report whether it is intact:
        sequence numbers 1..n, each ``prev_hash`` linking to the prior record, and
        each ``hash`` matching a fresh recomputation. An empty chain is valid."""
        prev_hash = self.GENESIS_HASH
        for i, record in enumerate(self._journal.get(session_id, ()), start=1):
            if record.get("seq") != i:
                return False
            if record.get("prev_hash") != prev_hash:
                return False
            if record.get("hash") != self._record_hash(prev_hash, record):
                return False
            prev_hash = record["hash"]
        return True

    # ------------------------------------------------------------------ #
    # Hashing helpers (stdlib only)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _canonical(record: dict) -> str:
        """Deterministic serialization of a record's *content* (everything the hash
        commits to, i.e. excluding prev_hash and hash themselves)."""
        content = {
            "seq": record["seq"],
            "ts": record["ts"],
            "kind": record["kind"],
            "payload": record["payload"],
        }
        return json.dumps(content, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, default=str)

    def _record_hash(self, prev_hash: str, record: dict) -> str:
        h = hashlib.sha256()
        h.update(prev_hash.encode("utf-8"))
        h.update(self._canonical(record).encode("utf-8"))
        return h.hexdigest()

    @staticmethod
    def _next_ts(chain: list[dict]) -> float:
        """Wall-clock timestamp that never goes backwards within a session, even if
        two records land in the same clock tick."""
        ts = time.time()
        if chain and ts <= chain[-1]["ts"]:
            ts = chain[-1]["ts"]  # keep non-decreasing; seq still strictly orders
        return ts

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def _resolve_path(self, path: Optional[os.PathLike | str]) -> Optional[str]:
        if path is None:
            return None
        path = os.fspath(path)
        # A directory (existing, or a name with no file-ish extension) -> file inside.
        if os.path.isdir(path):
            return os.path.join(path, self.DEFAULT_JOURNAL_NAME)
        if not os.path.splitext(path)[1]:
            os.makedirs(path, exist_ok=True)
            return os.path.join(path, self.DEFAULT_JOURNAL_NAME)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return path

    def _append_to_disk(self, session_id: str, record: dict) -> None:
        line = json.dumps({"session_id": session_id, **record},
                          sort_keys=True, ensure_ascii=False, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _load_journal(self) -> None:
        """Repopulate the in-memory journal from an existing JSONL file, if any.
        Records are grouped by session and ordered by their stored ``seq``."""
        if not self._path or not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                session_id = rec.pop("session_id", "")
                self._journal[session_id].append(rec)
        for chain in self._journal.values():
            chain.sort(key=lambda r: r["seq"])

    def reload(self) -> None:
        """Discard the in-memory journal and reload it from disk (no-op in memory
        mode). Useful for crash recovery or re-reading after an external append."""
        self._journal = defaultdict(list)
        if self._path:
            self._load_journal()
