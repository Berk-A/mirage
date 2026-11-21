from __future__ import annotations

import re
from typing import Iterable

from core.models import Dossier, Fact


class ResearchCatalog:
    """Offline catalog implementing the existing dossier and grounding seams."""

    def __init__(self, dossiers: Iterable[Dossier]) -> None:
        self._dossiers: dict[str, Dossier] = {}
        self._facts: dict[str, Fact] = {}

        for dossier in dossiers:
            if not dossier.target_id:
                raise ValueError("dossier target_id is required")
            if dossier.target_id in self._dossiers:
                raise ValueError(f"duplicate target_id: {dossier.target_id}")

            self._dossiers[dossier.target_id] = dossier

            for fact in dossier.facts:
                if not fact.id or not fact.canonical_claim.strip():
                    raise ValueError("each fact needs an id and canonical_claim")
                if not fact.source_url.startswith(("fixture://", "https://")):
                    raise ValueError(f"invalid source URL for fact {fact.id}")
                if not fact.observed_date:
                    raise ValueError(f"missing observed_date for fact {fact.id}")
                if not 0.0 <= fact.confidence <= 1.0:
                    raise ValueError(f"confidence out of range for fact {fact.id}")
                if fact.id in self._facts:
                    raise ValueError(f"duplicate fact id: {fact.id}")

                self._facts[fact.id] = fact

    def get_dossier(
        self, target_id: str, *, scenario_id: str = "practice"
    ) -> Dossier:
        # scenario_id is accepted to match DossierProvider.
        del scenario_id
        return self._dossiers[target_id]

    def get_fact(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def ground(self, claim_text: str, *, target_id: str) -> dict:
        """Match only an exact approved fixture claim; do not infer paraphrases."""
        wanted = self._normalize(claim_text)
        dossier = self.get_dossier(target_id)
        matches = [
            fact for fact in dossier.facts
            if self._normalize(fact.canonical_claim) == wanted
        ]

        return {
            "supported": bool(matches),
            "node_ids": [fact.id for fact in matches],
            "evidence": [
                {
                    "id": fact.id,
                    "text": fact.canonical_claim,
                    "source_url": fact.source_url,
                    "event_date": fact.event_date,
                }
                for fact in matches
            ],
            "confidence": max(
                (fact.confidence for fact in matches),
                default=0.0,
            ),
        }

    def verify(self, claim_text: str, *, target_id: str) -> str | None:
        """Adapter for the existing GroundingProvider protocol."""
        result = self.ground(claim_text, target_id=target_id)
        return result["node_ids"][0] if result["supported"] else None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().casefold())