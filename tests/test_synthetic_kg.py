"""Tests for the synthetic knowledge graph (research.synthetic_kg).

These lock the Protocol conformance and the dossier/grounding contracts the OODA
loop depends on, against CLEARLY-SYNTHETIC fabricated test data.
"""
from __future__ import annotations

import pytest

from core.interfaces import DossierProvider, GroundingProvider
from core.models import Dossier
from research.synthetic_kg import GRAPH, SyntheticKnowledgeGraph, dossiers

FOUNDERS = ("julius", "tom", "robert")


@pytest.fixture()
def kg() -> SyntheticKnowledgeGraph:
    return SyntheticKnowledgeGraph()


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #
def test_conforms_to_dossier_provider(kg: SyntheticKnowledgeGraph) -> None:
    assert isinstance(kg, DossierProvider)


def test_conforms_to_grounding_provider(kg: SyntheticKnowledgeGraph) -> None:
    assert isinstance(kg, GroundingProvider)


# --------------------------------------------------------------------------- #
# Per-founder dossiers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("target_id", FOUNDERS)
def test_founder_dossier_is_populated(kg: SyntheticKnowledgeGraph, target_id: str) -> None:
    d = kg.get_dossier(target_id)
    assert isinstance(d, Dossier)
    assert d.target_id == target_id
    assert d.display_name
    assert d.role
    assert d.archetype  # non-empty archetype
    assert len(d.hooks) >= 1
    assert len(d.senders) >= 1
    assert len(d.vendors) >= 1


@pytest.mark.parametrize("target_id", FOUNDERS)
def test_hooks_are_recency_ranked(kg: SyntheticKnowledgeGraph, target_id: str) -> None:
    dates = [h.date for h in kg.get_dossier(target_id).hooks]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.parametrize("target_id", FOUNDERS)
def test_hooks_carry_provenance(kg: SyntheticKnowledgeGraph, target_id: str) -> None:
    for h in kg.get_dossier(target_id).hooks:
        assert h.topic
        assert h.source_url.startswith("http")
        assert h.date
        assert 0.0 <= h.confidence <= 1.0


@pytest.mark.parametrize("target_id", FOUNDERS)
def test_sender_addresses_are_not_on_revel8_domain(kg: SyntheticKnowledgeGraph, target_id: str) -> None:
    for s in kg.get_dossier(target_id).senders:
        assert s.address  # a reachable handle/address
        assert "revel8" not in s.address.lower()


def test_dossiers_helper_returns_all_three_founders() -> None:
    all_d = dossiers()
    assert {d.target_id for d in all_d} == set(FOUNDERS)


# --------------------------------------------------------------------------- #
# Grounding (verify)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("target_id", FOUNDERS)
def test_verify_grounds_a_known_hook(kg: SyntheticKnowledgeGraph, target_id: str) -> None:
    topic = kg.get_dossier(target_id).hooks[0].topic
    node_id = kg.verify(topic, target_id=target_id)
    assert node_id is not None
    assert isinstance(node_id, str)
    assert node_id in GRAPH.nodes


def test_verify_rejects_unknown_claim(kg: SyntheticKnowledgeGraph) -> None:
    assert kg.verify("the sky is green", target_id="julius") is None


# --------------------------------------------------------------------------- #
# Unknown target -> usable, no crash
# --------------------------------------------------------------------------- #
def test_unknown_target_returns_usable_dossier(kg: SyntheticKnowledgeGraph) -> None:
    d = kg.get_dossier("someone_unknown")
    assert isinstance(d, Dossier)
    assert d.target_id == "someone_unknown"
    assert d.archetype  # still non-empty / usable


# --------------------------------------------------------------------------- #
# Graph structure is inspectable
# --------------------------------------------------------------------------- #
def test_graph_is_inspectable() -> None:
    assert GRAPH.nodes
    assert GRAPH.edges
    for e in GRAPH.edges:
        assert e.src in GRAPH.nodes
        assert e.dst in GRAPH.nodes
        assert e.source_url.startswith("http")
        assert e.date
        assert 0.0 <= e.confidence <= 1.0
