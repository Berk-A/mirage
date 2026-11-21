from core.interfaces import DossierProvider, GroundingProvider
from core.models import Dossier, Fact
from research import ResearchCatalog


def make_catalog():
    fact = Fact(
        id="f_demo_1",
        subject="sample-1",
        predicate="role_is",
        object_value="Synthetic product lead",
        canonical_claim="Avery Example is a synthetic product lead.",
        source_url="fixture://sample-1/profile#role",
        observed_date="2026-11-21",
        event_date="2026-11-20",
        confidence=1.0,
    )
    dossier = Dossier(
        target_id="sample-1",
        display_name="Avery Example",
        role="Synthetic product lead",
        as_of="2026-11-21",
        facts=(fact,),
    )
    return ResearchCatalog([dossier]), fact


def test_provider_contracts_and_fact_lookup():
    catalog, fact = make_catalog()

    assert isinstance(catalog, DossierProvider)
    assert isinstance(catalog, GroundingProvider)
    assert catalog.get_dossier("sample-1").facts == (fact,)
    assert catalog.get_fact("f_demo_1") == fact


def test_ground_accepts_only_the_approved_claim():
    catalog, _ = make_catalog()

    result = catalog.ground(
        "Avery Example is a synthetic product lead.",
        target_id="sample-1",
    )
    assert result["supported"] is True
    assert result["node_ids"] == ["f_demo_1"]
    assert result["confidence"] == 1.0
    assert catalog.verify(
        "Avery Example is a synthetic product lead.",
        target_id="sample-1",
    ) == "f_demo_1"


def test_ground_rejects_unapproved_claim():
    catalog, _ = make_catalog()

    result = catalog.ground(
        "Avery Example manages the whole company.",
        target_id="sample-1",
    )
    assert result["supported"] is False
    assert result["node_ids"] == []
    assert catalog.verify(
        "Avery Example manages the whole company.",
        target_id="sample-1",
    ) is None