"""Tests for the experiment harness. No network, no model.

Everything runs against the in-memory fakes in `core.fakes`, plus the real
`StudioRenderer` driven by the offline `FakeLLM` (so the real render -> critic ->
humanizer cascade and its instrumentation are exercised without a served model).
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from core.fakes import FakeDossierProvider, FakeSignalReader, ScriptedClient
from core.models import (
    Dossier,
    Event,
    EventType,
    Hook,
    MoveSpec,
    Objective,
    Sender,
    Vendor,
)
from content.llm import FakeLLM
from content.studio import StudioRenderer
from experiments.form_factors import (
    CHANNELS,
    OBJECTIVES,
    TONES,
    FormFactor,
    enumerate_factors,
    spec_from_factor,
)
from experiments.harness import (
    RELIABILITY_LABELS,
    ResultRow,
    classify_output,
    run_matrix,
    summarize,
    write_summary,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def dossier() -> Dossier:
    return Dossier(
        target_id="julius",
        display_name="Julius Muth",
        role="Co-Founder",
        archetype="founder/product",
        hooks=(
            Hook(topic="speaker logistics", detail="talk on Thursday", confidence=0.8),
            Hook(topic="Q4 roadmap", detail="roadmap review", confidence=0.6),
        ),
        senders=(Sender(name="Lena Hofer", address="lena.hofer@eventcrew-muc.de"),),
        vendors=(Vendor(name="Notion", login_url="https://notion.example/login"),),
    )


@pytest.fixture
def provider(dossier) -> FakeDossierProvider:
    return FakeDossierProvider(dossier)


def _studio() -> StudioRenderer:
    # FakeLLM with no args echoes a deterministic, non-empty draft from the prompt.
    return StudioRenderer(FakeLLM())


# --------------------------------------------------------------------------- #
# form_factors
# --------------------------------------------------------------------------- #
def test_enumerate_full_product():
    factors = enumerate_factors(hook_indices=(0,), with_link=(False, True))
    assert len(factors) == len(CHANNELS) * len(OBJECTIVES) * len(TONES) * 1 * 2
    assert all(isinstance(f, FormFactor) for f in factors)


def test_enumerate_limit_caps_without_seed():
    factors = enumerate_factors(limit=5)
    assert len(factors) == 5
    # Deterministic order when no seed is given.
    assert factors == enumerate_factors(limit=5)


def test_enumerate_seed_samples_reproducibly():
    a = enumerate_factors(limit=7, seed=42)
    b = enumerate_factors(limit=7, seed=42)
    c = enumerate_factors(limit=7, seed=43)
    assert a == b
    assert len(a) == 7
    assert a != c  # a different seed draws a different sample (overwhelmingly likely)


def test_spec_from_factor_valid_for_each_objective(dossier):
    for obj in OBJECTIVES:
        ff = FormFactor(channel="email", objective=obj, tone="professional",
                        hook_index=0, with_link=False)
        spec = spec_from_factor(dossier, ff)
        assert isinstance(spec, MoveSpec)
        assert spec.objective is obj
        assert spec.channel == "email"
        assert spec.tone == "professional"
        assert spec.ask
        assert spec.sender == dossier.senders[0]
        # Email carries a subject.
        assert spec.subject
        # Credentials always needs a landing URL; the others only when with_link.
        if obj is Objective.CREDENTIALS:
            assert spec.url
        else:
            assert spec.url is None


def test_spec_with_link_forces_url_on_non_credentials(dossier):
    ff = FormFactor(channel="slack", objective=Objective.DISCLOSURE, tone="urgent",
                    hook_index=0, with_link=True)
    spec = spec_from_factor(dossier, ff)
    assert spec.url  # with_link forces a lookalike URL
    assert spec.subject is None  # slack has no subject line


def test_spec_hook_index_out_of_range_is_safe(dossier):
    ff = FormFactor(channel="email", objective=Objective.ACTION, tone="colleague",
                    hook_index=99, with_link=False)
    spec = spec_from_factor(dossier, ff)  # must not raise
    assert isinstance(spec, MoveSpec)


# --------------------------------------------------------------------------- #
# classify_output
# --------------------------------------------------------------------------- #
def test_classify_output_labels():
    assert classify_output("") == "empty"
    assert classify_output("   ") == "empty"
    assert classify_output("too short") == "too_short"
    assert classify_output("As an AI language model, I cannot help with that.") == "refusal"
    assert classify_output("Hi Julius, could you confirm the room number for Thursday?") == "ok"
    assert set(RELIABILITY_LABELS) == {"ok", "refusal", "empty", "too_short"}


# --------------------------------------------------------------------------- #
# run_matrix — generation (send=False)
# --------------------------------------------------------------------------- #
def test_run_matrix_generation_one_row_per_factor(provider, tmp_path):
    factors = enumerate_factors(limit=6, seed=1)
    rows = run_matrix(
        factors,
        dossier_provider=provider,
        target_id="julius",
        renderer=_studio(),
        reader=FakeSignalReader(),
        client=None,
        send=False,
        out_dir=str(tmp_path),
        sleep_s=0.0,
    )
    assert len(rows) == len(factors)
    assert all(isinstance(r, ResultRow) for r in rows)
    assert all(not r.sent for r in rows)
    assert all(r.reliability_label in RELIABILITY_LABELS for r in rows)
    assert all(r.body for r in rows)  # the studio always ships a non-empty body

    # JSONL written, one line per factor, each a full record incl. the message body.
    jsonl = tmp_path / "rows.jsonl"
    assert jsonl.exists()
    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(factors)
    first = json.loads(lines[0])
    assert "body" in first and "channel" in first and "reliability_label" in first


# --------------------------------------------------------------------------- #
# run_matrix — live (send=True)
# --------------------------------------------------------------------------- #
def test_run_matrix_live_records_incident(provider, tmp_path):
    # One credentials factor whose message carries a page; script a page.submitted back.
    factors = [
        FormFactor(channel="email", objective=Objective.CREDENTIALS, tone="professional",
                   hook_index=0, with_link=True),
    ]
    page_submit = Event(id="e1", type=EventType.PAGE_SUBMITTED, page_id="p_fake1",
                        fields=("email", "password"))
    client = ScriptedClient(script=[[page_submit]])

    rows = run_matrix(
        factors,
        dossier_provider=provider,
        target_id="julius",
        renderer=_studio(),
        reader=FakeSignalReader(),
        client=client,
        send=True,
        out_dir=str(tmp_path),
        sleep_s=0.0,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.sent is True
    assert row.api_status == "ok"
    assert EventType.PAGE_SUBMITTED.value in row.events
    assert row.incident == Objective.CREDENTIALS.value
    assert row.suspicion is not None

    # The client opened one session and registered the page before sending.
    assert len(client.sent) == 1
    assert len(client.pages) == 1


# --------------------------------------------------------------------------- #
# summarize + write_summary
# --------------------------------------------------------------------------- #
def test_summarize_rates(provider, tmp_path):
    factors = enumerate_factors(limit=8, seed=2)
    rows = run_matrix(
        factors,
        dossier_provider=provider,
        target_id="julius",
        renderer=_studio(),
        reader=FakeSignalReader(),
        send=False,
        out_dir=str(tmp_path),
        sleep_s=0.0,
    )
    summary = summarize(rows)

    overall = summary["overall"]
    assert overall["count"] == len(factors)
    # Reliability distribution is a proper distribution over the documented labels.
    rel = overall["reliability"]
    assert set(rel) == set(RELIABILITY_LABELS)
    assert abs(sum(rel.values()) - 1.0) < 1e-9
    # FakeLLM output is non-empty and clean -> every row classifies "ok".
    assert rel["ok"] == 1.0
    assert 0.0 <= overall["fell_back_rate"] <= 1.0
    assert 0.0 <= overall["guard_violation_rate"] <= 1.0
    assert "render_latency_ms_mean" in overall
    assert "render_latency_ms_median" in overall
    # Nothing sent in generation mode: no live metrics block.
    assert overall["sent_count"] == 0
    assert "incident_rate" not in overall

    # Breakdown keys present for every dimension.
    for dim in ("by_channel", "by_objective", "by_tone", "by_with_link", "by_hook_index"):
        assert dim in summary
    # Per-dimension counts sum back to the total.
    assert sum(g["count"] for g in summary["by_channel"].values()) == len(factors)


def test_summarize_live_metrics(provider, tmp_path):
    factors = [
        FormFactor(channel="email", objective=Objective.CREDENTIALS, tone="professional",
                   hook_index=0, with_link=True),
        FormFactor(channel="slack", objective=Objective.DISCLOSURE, tone="urgent",
                   hook_index=0, with_link=False),
    ]
    page_submit = Event(id="e1", type=EventType.PAGE_SUBMITTED, page_id="p_fake1",
                        fields=("email", "password"))
    # First send -> page.submitted (incident); second -> silence.
    client = ScriptedClient(script=[[page_submit], []])

    rows = run_matrix(
        factors,
        dossier_provider=provider,
        target_id="julius",
        renderer=_studio(),
        reader=FakeSignalReader(),
        client=client,
        send=True,
        out_dir=str(tmp_path),
        sleep_s=0.0,
    )
    overall = summarize(rows)["overall"]
    assert overall["sent_count"] == 2
    assert overall["api_error_rate"] == 0.0
    assert overall["incident_rate"] == 0.5  # one of two sends landed an incident
    assert overall["event_rates"][EventType.PAGE_SUBMITTED.value] == 0.5
    assert "suspicion_mean" in overall


def test_write_summary_outputs(provider, tmp_path):
    factors = enumerate_factors(limit=5, seed=3)
    rows = run_matrix(
        factors,
        dossier_provider=provider,
        target_id="julius",
        renderer=_studio(),
        reader=FakeSignalReader(),
        send=False,
        out_dir=str(tmp_path),
        sleep_s=0.0,
    )
    write_summary(rows, str(tmp_path))

    for name in ("summary.json", "summary.md", "rows.csv"):
        assert (tmp_path / name).exists(), name

    data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert data["overall"]["count"] == len(factors)

    with open(tmp_path / "rows.csv", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == len(factors)
    assert "reliability_label" in csv_rows[0]
    assert "guard_violations" in csv_rows[0]
