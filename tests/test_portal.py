"""Tests for the portal data/binding layer (portal.data).

Pure reads over a synthetic runs directory — no HTTP, no network. Guards the shapes the
frontend binds to AND the API-grounded outcome grading (the portal must not trust the
summary.json `incident` heuristic, which false-fires; a win needs a real API event).
"""
from __future__ import annotations

import json

import pytest

from portal import data


@pytest.fixture()
def runs(tmp_path, monkeypatch):
    """A runs dir covering the three outcome paths plus a heuristic false positive.

    - ada:   summary flags `disclosure`, but the reply only asks a question  -> NO win
    - grace: a page.submitted with a secret field                            -> credentials win
    - heidi: a reply that volunteers a non-public internal fact              -> disclosure win
    """
    monkeypatch.setenv("MIRAGE_RUNS_DIR", str(tmp_path))

    run = tmp_path / "ooda_20260101_000000"
    run.mkdir()
    (run / "summary.json").write_text(json.dumps([
        {"target": "ada", "session": "s_ada", "contacts": 2, "won": True,
         "incident": "disclosure", "stop_reason": "incident", "seconds": 12.3,
         "touches": [{"objective": "disclosure", "channel": "email", "sender": "Grace H",
                      "incident": "disclosure", "suspicion": 0.6},
                     {"objective": "disclosure", "channel": "email", "sender": "Grace H",
                      "incident": None, "suspicion": 0.4}]},
        {"target": "grace", "session": "s_grace", "contacts": 1, "won": True,
         "incident": "credentials", "stop_reason": "incident", "seconds": 9.0,
         "touches": [{"objective": "credentials", "channel": "email", "sender": "IT",
                      "incident": "credentials", "suspicion": 0.3}]},
        {"target": "heidi", "session": "s_heidi", "contacts": 1, "won": True,
         "incident": "disclosure", "stop_reason": "incident", "seconds": 7.0,
         "touches": [{"objective": "disclosure", "channel": "email", "sender": "Peer",
                      "incident": "disclosure", "suspicion": 0.5}]},
    ]))
    (run / "ada.jsonl").write_text("\n".join([
        json.dumps({"kind": "session_start", "session_id": "s_ada"}),
        json.dumps({"kind": "touch", "n": 1, "channel": "email", "sender": "Grace H",
                    "sender_addr": "grace@x.test", "subject": "Hi", "body": "hello",
                    "events": [{"type": "reply", "channel": "email",
                                "reply": "Who is this and which company are you with?"}]}),
        json.dumps({"kind": "touch", "n": 2, "channel": "email", "sender": "Grace H",
                    "subject": "", "body": "follow up", "events": []}),
    ]))
    (run / "grace.jsonl").write_text("\n".join([
        json.dumps({"kind": "session_start", "session_id": "s_grace"}),
        json.dumps({"kind": "touch", "n": 1, "channel": "email", "sender": "IT",
                    "subject": "Re-auth", "body": "please re-auth", "has_page": True,
                    "events": [
                        {"type": "link.opened", "url": "https://p.test"},
                        {"type": "page.submitted", "fields": ["email", "password"],
                         "values": {"email": "g@x.test", "password": "(entered, not shown)"}},
                    ]}),
    ]))
    (run / "heidi.jsonl").write_text("\n".join([
        json.dumps({"kind": "session_start", "session_id": "s_heidi"}),
        json.dumps({"kind": "touch", "n": 1, "channel": "email", "sender": "Peer",
                    "subject": "stack", "body": "curious about your setup",
                    "events": [{"type": "reply", "channel": "email",
                                "reply": "We migrated to AWS last quarter and run billing on our internal Postgres cluster."}]}),
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
         "outcome": "engaged", "detail": "replied", "run_id": "s_ada",
         "ts": "2026-01-01T00:00:00+00:00"},
    ]))
    return tmp_path


def test_outcomes_are_api_confirmed_not_heuristic(runs):
    ov = data.overview()
    assert ov["cards"]["sessions"] == 3
    # 2 real wins (grace credentials, heidi disclosure); ada's flagged disclosure is dropped.
    assert ov["cards"]["wins"] == 2
    assert ov["cards"]["win_rate"] == round(2 / 3, 4)
    assert ov["outcomes"] == {"credentials": 1, "disclosure": 1, "action": 0, "none": 1}
    assert ov["audit"] == {"flagged": 3, "confirmed": 2, "unconfirmed": 1, "grader": True}

    by = {r["persona"]: r for r in ov["session_log"]}
    assert by["ada"]["outcome"] == "none" and by["ada"]["won"] is False
    assert by["ada"]["flagged"] == "disclosure" and by["ada"]["unconfirmed"] is True
    assert by["grace"]["outcome"] == "credentials" and by["grace"]["won"] is True
    assert by["grace"]["unconfirmed"] is False
    assert by["heidi"]["outcome"] == "disclosure" and by["heidi"]["won"] is True


def test_api_confirmed_outcome_paths():
    cred = [{"type": "page.submitted", "fields": ["user", "password"],
             "values": {"password": "(entered, not shown)"}}]
    assert data.api_confirmed_outcome(cred) == "credentials"
    assert data.api_confirmed_outcome([{"type": "attachment.opened"}]) == "action"
    assert data.api_confirmed_outcome(
        [{"type": "reply", "reply": "We run everything on our internal Postgres cluster."}]) == "disclosure"
    # public-fact / refusal / question replies are NOT disclosures
    assert data.api_confirmed_outcome(
        [{"type": "reply", "reply": "The €7M is public anyway, ping me on Slack."}]) is None
    # a form with only name/email (no secret) is a step, not a win
    assert data.api_confirmed_outcome(
        [{"type": "page.submitted", "fields": ["name", "email"], "values": {}}]) is None
    assert data.api_confirmed_outcome([]) is None


def test_overview_persona_filter(runs):
    ada = data.overview(persona="ada")
    assert ada["cards"]["sessions"] == 1
    assert ada["cards"]["win_rate"] == 0.0  # ada's disclosure flag is not API-confirmed
    assert data.overview(persona="nobody")["cards"]["sessions"] == 0


def test_session_replay_timeline(runs):
    rep = data.session_replay("ooda_20260101_000000", "ada")
    kinds = [s["kind"] for s in rep["timeline"]]
    assert kinds == ["SENT", "REPLY", "SENT", "SILENCE"]
    assert rep["persona_name"] == "Ada Lovelace"
    assert rep["sender"] == "grace@x.test"
    assert rep["outcome"] == "none" and rep["unconfirmed"] is True and rep["flagged"] == "disclosure"
    assert data.session_replay("missing", "ada") is None

    grace = data.session_replay("ooda_20260101_000000", "grace")
    assert grace["outcome"] == "credentials" and grace["won"] is True


def test_dossiers(runs):
    ds = data.dossiers()
    assert [d["target"] for d in ds] == ["ada"]  # only ada has a dossier file
    assert ds[0]["hooks"][0]["topic"] == "the compiler launch"
    assert ds[0]["last_run"] == "ooda_20260101_000000"


def test_ledger(runs):
    lg = data.ledger()
    assert lg["exists"] is True and lg["total_records"] == 1
    t = lg["targets"][0]
    assert t["target"] == "ada" and t["groups"][0]["strategy"] == "press"
    assert "press" not in t["untried"] and "recruiter" in t["untried"]


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
