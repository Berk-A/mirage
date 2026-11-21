"""Gated live collector test — hits the real public web.

Skipped unless RUN_LIVE_RESEARCH=1, so the default suite (and CI) never depends on the
network. Run it with:  RUN_LIVE_RESEARCH=1 .venv/bin/pytest tests/test_research_live.py
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RESEARCH") != "1",
    reason="set RUN_LIVE_RESEARCH=1 to run the live OSINT collector test (needs network)",
)


def test_live_dossier_for_a_real_founder():
    from research.seeds import default_provider

    provider = default_provider(as_of="2026-11-21")
    dossier = provider.get_dossier("julius")

    # Real, provenance-stamped facts came back off the public web.
    assert dossier.facts, "expected at least one fact from public sources"
    for fact in dossier.facts:
        assert fact.source_url.startswith("https://")
        assert fact.observed_date
        assert 0.0 <= fact.confidence <= 1.0

    # The authoritative role/identity is intact and a true claim grounds.
    assert dossier.display_name == "Julius Muth"
    assert dossier.archetype == "executive_founder"
    assert provider.verify("Julius Muth works at revel8.", target_id="julius") is not None
    assert provider.verify("Julius Muth owns a private island.", target_id="julius") is None
