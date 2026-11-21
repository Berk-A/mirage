"""Tests for ooda_loop.memory.ThreeTierMemory.

Covers the three tiers and the tamper-evident journal:
  * Protocol conformance (isinstance against the @runtime_checkable Memory).
  * working tier: claim insertion order, suspicion get/set + default.
  * episodic tier: record_outcome, outcomes archetype filtering, stats helper.
  * journal tier: append + replay ordering, sequence numbers, timestamps,
    plain-dict records, and the hash chain (final_hash moves, verify_chain True).
  * optional disk persistence: a JSONL round-trip through tmp_path.
"""
from __future__ import annotations

import json

import pytest

from core.interfaces import Memory
from core.models import Incident, Objective, Outcome
from ooda_loop.memory import ThreeTierMemory


# --------------------------------------------------------------------------- #
# Conformance
# --------------------------------------------------------------------------- #
def test_conforms_to_memory_protocol():
    assert isinstance(ThreeTierMemory(), Memory)


# --------------------------------------------------------------------------- #
# Working tier
# --------------------------------------------------------------------------- #
def test_claims_preserve_insertion_order_per_session():
    m = ThreeTierMemory()
    m.add_claim("s1", "alpha")
    m.add_claim("s1", "bravo")
    m.add_claim("s1", "charlie")
    m.add_claim("s2", "other")

    assert m.claims("s1") == ("alpha", "bravo", "charlie")
    assert m.claims("s2") == ("other",)
    # Unknown session -> empty, not an error.
    assert m.claims("nope") == ()


def test_suspicion_get_set_and_default():
    m = ThreeTierMemory()
    assert m.get_suspicion("s1") == 0.0  # default when unset
    m.set_suspicion("s1", 0.7)
    assert m.get_suspicion("s1") == 0.7
    m.set_suspicion("s1", 0.2)  # overwrite, not accumulate
    assert m.get_suspicion("s1") == 0.2
    assert m.get_suspicion("s2") == 0.0  # isolated per session


# --------------------------------------------------------------------------- #
# Episodic tier
# --------------------------------------------------------------------------- #
def _outcome(success, archetype="busy_exec", arm="invoice", suspicion=0.1, contacts=1):
    return Outcome(
        objective=Objective.ACTION,
        success=success,
        archetype=archetype,
        arm=arm,
        channel="email",
        contacts_used=contacts,
        suspicion=suspicion,
    )


def test_record_outcome_and_filter_by_archetype():
    m = ThreeTierMemory()
    m.record_outcome(_outcome(True, archetype="busy_exec"))
    m.record_outcome(_outcome(False, archetype="busy_exec"))
    m.record_outcome(_outcome(True, archetype="new_hire"))

    assert len(m.outcomes()) == 3  # all
    busy = m.outcomes(archetype="busy_exec")
    assert len(busy) == 2
    assert all(o.archetype == "busy_exec" for o in busy)
    assert m.outcomes(archetype="missing") == ()


def test_stats_and_success_rate_helpers():
    m = ThreeTierMemory()
    # busy_exec/invoice: 2 of 3 succeed
    m.record_outcome(_outcome(True, "busy_exec", "invoice", suspicion=0.2, contacts=1))
    m.record_outcome(_outcome(True, "busy_exec", "invoice", suspicion=0.4, contacts=3))
    m.record_outcome(_outcome(False, "busy_exec", "invoice", suspicion=0.6, contacts=2))
    # busy_exec/reset: 0 of 1
    m.record_outcome(_outcome(False, "busy_exec", "reset"))

    # success_rate over the whole episodic log.
    assert m.success_rate() == pytest.approx(2 / 4)
    # filtered by archetype.
    assert m.success_rate(archetype="busy_exec") == pytest.approx(2 / 4)
    # filtered by arm within archetype.
    assert m.success_rate(archetype="busy_exec", arm="invoice") == pytest.approx(2 / 3)
    assert m.success_rate(archetype="busy_exec", arm="reset") == pytest.approx(0.0)
    # No data -> 0.0, never a ZeroDivisionError.
    assert m.success_rate(archetype="ghost") == 0.0

    st = m.stats(archetype="busy_exec", arm="invoice")
    assert st["n"] == 3
    assert st["successes"] == 2
    assert st["success_rate"] == pytest.approx(2 / 3)
    assert st["avg_suspicion"] == pytest.approx((0.2 + 0.4 + 0.6) / 3)
    assert st["avg_contacts"] == pytest.approx((1 + 3 + 2) / 3)

    empty = m.stats(archetype="ghost")
    assert empty["n"] == 0 and empty["success_rate"] == 0.0


# --------------------------------------------------------------------------- #
# Journal tier + hash chain
# --------------------------------------------------------------------------- #
def test_journal_append_and_replay_ordering_with_sequence():
    m = ThreeTierMemory()
    m.journal("s1", "observe", {"events": 2})
    m.journal("s1", "decide", {"objective": "action"})
    m.journal("s1", "act", {"message_id": "m1"})
    m.journal("s2", "observe", {"events": 0})

    rec = m.replay("s1")
    assert [r["kind"] for r in rec] == ["observe", "decide", "act"]
    assert [r["seq"] for r in rec] == [1, 2, 3]  # monotonic, per session
    # plain dicts, carrying payload + timestamp.
    assert all(isinstance(r, dict) for r in rec)
    assert rec[0]["payload"] == {"events": 2}
    assert all("ts" in r for r in rec)
    # timestamps non-decreasing.
    assert [r["ts"] for r in rec] == sorted(r["ts"] for r in rec)
    # session isolation.
    assert [r["seq"] for r in m.replay("s2")] == [1]
    assert m.replay("unknown") == ()


def test_hash_chain_grows_and_verifies():
    m = ThreeTierMemory()
    assert m.verify_chain("s1") is True  # empty chain is trivially valid

    m.journal("s1", "observe", {"n": 1})
    h1 = m.final_hash("s1")
    m.journal("s1", "act", {"n": 2})
    h2 = m.final_hash("s1")

    assert h1 and h2 and h1 != h2  # final hash advances with each record
    assert m.verify_chain("s1") is True

    # each record stores its own hash and the previous one, forming a chain.
    rec = m.replay("s1")
    assert rec[0]["prev_hash"] == m.GENESIS_HASH
    assert rec[1]["prev_hash"] == rec[0]["hash"]
    assert rec[1]["hash"] == h2


def test_verify_chain_detects_tampering():
    m = ThreeTierMemory()
    m.journal("s1", "observe", {"n": 1})
    m.journal("s1", "act", {"amount": 10})
    assert m.verify_chain("s1") is True

    # Tamper with a stored payload after the fact; the chain must notice.
    m._journal["s1"][1]["payload"]["amount"] = 9999
    assert m.verify_chain("s1") is False


# --------------------------------------------------------------------------- #
# Optional disk persistence
# --------------------------------------------------------------------------- #
def test_journal_persists_to_disk_and_reloads(tmp_path):
    path = tmp_path / "journal.jsonl"
    m = ThreeTierMemory(path=path)
    m.journal("s1", "observe", {"n": 1})
    m.journal("s1", "act", {"message_id": "m1"})
    m.journal("s2", "observe", {"n": 0})

    # File is written as append-only JSONL, one record per line.
    lines = path.read_text().splitlines()
    assert len(lines) == 3
    assert all(json.loads(line)["seq"] >= 1 for line in lines)

    # A fresh instance over the same path recovers the journal and chain.
    m2 = ThreeTierMemory(path=path)
    assert [r["kind"] for r in m2.replay("s1")] == ["observe", "act"]
    assert [r["seq"] for r in m2.replay("s1")] == [1, 2]
    assert m2.final_hash("s1") == m.final_hash("s1")
    assert m2.verify_chain("s1") is True

    # Appending after reload keeps the chain continuous.
    m2.journal("s1", "end", {"status": "done"})
    assert [r["seq"] for r in m2.replay("s1")] == [1, 2, 3]
    assert m2.verify_chain("s1") is True


def test_path_as_directory_round_trip(tmp_path):
    m = ThreeTierMemory(path=tmp_path)  # directory -> default journal file inside
    m.journal("s1", "observe", {"n": 1})
    m2 = ThreeTierMemory(path=tmp_path)
    assert [r["kind"] for r in m2.replay("s1")] == ["observe"]
    assert m2.verify_chain("s1") is True
