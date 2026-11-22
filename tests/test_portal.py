"""Tests for the portal data/binding layer (portal.data).

Pure reads over a synthetic runs directory — no HTTP, no network. Guards the shapes the
frontend binds to so the artifact->API mapping can't silently rot.
"""
from __future__ import annotations

import json

import pytest

from portal import data


@pytest.fixture()
def runs(tmp_path, monkeypatch):
    """A minimal runs dir in the exact artifact shapes run_ooda / the loop write."""
    monkeypatch.setenv("MIRAGE_RUNS_DIR", str(tmp_path))

    run = tmp_path / "ooda_20260101_000000"
    run.mkdir()
    (run / "summary.json").write_text(json.dumps([{
        "target": "ada", "session": "s_ada1", "contacts": 2, "won": True,
        "incident": "disclosure", "stop_reason": "incident", "seconds": 12.3,
        "touches": [
            {"objective": "disclosure", "channel": "email", "sender": "Grace H",
             "incident": "disclosure", "suspicion": 0.6},
            {"objective": "disclosure", "channel": "email", "sender": "Grace H",
             "incident": None, "suspicion": 0.4},
        ],
    }]))
    (run / "ada.jsonl").write_text("\n".join([
        json.dumps({"kind": "session_start", "session_id": "s_ada1"}),
        json.dumps({"kind": "touch", "n": 1, "channel": "email", "sender": "Grace H",
                    "sender_addr": "grace@x.test", "subject": "Hi", "body": "hello",
                    "events": [{"type": "reply", "channel": "email", "reply": "who?"}]}),
        json.dumps({"kind": "touch", "n": 2, "channel": "email", "sender": "Grace H",
                    "subject": "", "body": "follow up", "events": []}),
    ]))
    (run / "ada_dossier.json").write_text(json.dumps({
        "target_id": "ada", "display_name": "Ada Lovelace",
        "role": "Head of Engineering", "archetype": "technical_leader",
        "hooks": [{"topic": "the compiler launch", "detail": "On 2026-01-01 ...",
                   "source_url": "https://x.test/a", "date": "2026-01-01", "confidence": 0.7}],
        "senders": [{"name": "Grace H", "address": "grace@x.test", "rationale": "colleague"}],
        "vendors": [{"name": "SomeVendor"}],
    }))
    (tmp_path / "strategy_ledger.json").write_text(json.dumps([
        {"target_id": "ada", "strategy": "press", "persona": "Reporter",
         "tactic": "plain", "channel": "email", "objective": "disclosure",
         "outcome": "engaged", "detail": "replied", "run_id": "s_ada1",
         "ts": "2026-01-01T00:00:00+00:00"},
    ]))
    return tmp_path


def test_overview_binds_real_shapes(runs):
    ov = data.overview()
    assert ov["has_data"] is True
    assert ov["cards"]["sessions"] == 1
    assert ov["cards"]["win_rate"] == 1.0  # incident=disclosure -> objective reached
    assert ov["outcomes"] == {"credentials": 0, "disclosure": 1, "action": 0, "none": 0}
    assert ov["cards"]["avg_turns"] == 2.0
    # end-of-session skepticism is the last touch's suspicion
    assert ov["session_log"][0]["skepticism"] == 0.4
    twin = ov["twins"][0]
    assert twin["persona"] == "ada"
    assert twin["name"] == "Ada Lovelace"
    assert "the compiler launch" in twin["topics"]
    assert {"id": "ada", "name": "Ada Lovelace"} in ov["personas"]
    assert "email" in ov["channels"]


def test_overview_persona_filter(runs):
    assert data.overview(persona="ada")["cards"]["sessions"] == 1
    empty = data.overview(persona="nobody")
    assert empty["cards"]["sessions"] == 0
    assert empty["has_data"] is True  # unfiltered data still exists


def test_session_replay_timeline(runs):
    rep = data.session_replay("ooda_20260101_000000", "ada")
    kinds = [s["kind"] for s in rep["timeline"]]
    assert kinds == ["SENT", "REPLY", "SENT", "SILENCE"]
    assert rep["persona_name"] == "Ada Lovelace"
    assert rep["sender"] == "grace@x.test"
    assert rep["timeline"][1]["text"] == "who?"
    assert data.session_replay("missing", "ada") is None


def test_dossiers(runs):
    ds = data.dossiers()
    assert len(ds) == 1
    assert ds[0]["display_name"] == "Ada Lovelace"
    assert ds[0]["hooks"][0]["topic"] == "the compiler launch"
    assert ds[0]["last_run"] == "ooda_20260101_000000"


def test_ledger(runs):
    lg = data.ledger()
    assert lg["exists"] is True
    assert lg["total_records"] == 1
    t = lg["targets"][0]
    assert t["target"] == "ada"
    assert t["groups"][0]["strategy"] == "press"
    assert t["groups"][0]["best"] == "engaged"
    assert "press" not in t["untried"]
    assert "recruiter" in t["untried"]


def test_level_bands():
    assert data.level_of(0.1) == "Low"
    assert data.level_of(0.5) == "Medium"
    assert data.level_of(0.9) == "High"


def test_no_data_degrades(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRAGE_RUNS_DIR", str(tmp_path / "does_not_exist"))
    ov = data.overview()
    assert ov["has_data"] is False
    assert ov["cards"]["sessions"] == 0
    assert data.ledger()["exists"] is False
