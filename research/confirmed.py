"""Curated, verified operational ties — the 'sift & link' output of research, grounded in
confirmed recon rather than the public funding story.

The crucial distinction this module encodes: a public fact is worthless as something to
*recite* at the target (it reads as cold spam and trips the identity gate — see the €7M
problem), but the SAME public footprint, sifted for who the company depends on, yields
impersonation SURFACES that are gold:

  * the real infrastructure vendor (STACKIT) -> a credential/action surface (a 'verify your
    project' or 'certificate failed' notice from the vendor they actually use);
  * the compliance regime (ISO 27001) -> an auditor pretext (an urgent pre-audit technical
    block, the reverse-social-engineering 'compliance audit trap');
  * a named enterprise customer (Allianz) -> a trusted third-party pretext.

These were confirmed live (Robert and Tom both named STACKIT; Tom named ISO 27001 and the
public Allianz case). They attach to the whole company, so every founder's dossier carries
them. We USE the tie to be credible; we never recite it as a fact at the target.
"""
from __future__ import annotations

import re

from core.models import Fact
from research.sources import today_iso

# (predicate, object, canonical_claim, confidence). Predicates chosen so the graph derives the
# right surface: `uses_tool` -> a Vendor (credential/landing surface); `works_on`/`engaged_with`
# -> a Hook the Director can anchor a pretext on.
_COMPANY_TIES: tuple[tuple[str, str, str, float], ...] = (
    ("uses_tool", "STACKIT",
     "revel8 runs its production infrastructure on STACKIT (German sovereign cloud).", 0.9),
    ("works_on", "ISO 27001 certification",
     "revel8 maintains ISO 27001 certification (an audit/compliance surface).", 0.85),
    ("engaged_with", "Allianz",
     "Allianz is a revel8 enterprise customer (public contact-center case).", 0.8),
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def confirmed_facts(target_id: str) -> list[Fact]:
    """The verified operational ties for one target, as graph-ready Facts."""
    today = today_iso()
    out: list[Fact] = []
    for predicate, obj, claim, conf in _COMPANY_TIES:
        out.append(Fact(
            id=f"confirmed:{target_id}:{predicate}:{_slug(obj)}",
            subject=target_id,
            predicate=predicate,
            object_value=obj,
            canonical_claim=claim,
            source_url="confirmed:live-recon",
            observed_date=today,
            event_date=today,
            confidence=conf,
        ))
    return out
