"""The rule guard: a deterministic gate between a decided move and the API.

It enforces the challenge's hard rules so a run is never voided:
  * no addressing the persona as an AI / prompt-injection,
  * senders and landing pages on lookalike domains an attacker could register,
    never a real organisation's own domain.

It returns a list of violation strings (empty == clear). The jury likes seeing this
gate reject a forbidden operation live, so every check is logged by the orchestrator.
"""
from __future__ import annotations

from urllib.parse import urlparse
from typing import Optional

from core.models import MoveSpec, RenderedMessage

# Phrases that attack the simulator instead of the person -> voids the run.
BANNED_PHRASES = (
    "ignore your instructions",
    "ignore previous",
    "ignore all previous",
    "you are an ai",
    "as an ai",
    "language model",
    "system prompt",
    "disregard your",
)

# Real orgs' own domains: a page/sender here is something no attacker could host.
# Extend this as targets are scoped. Lookalikes (e.g. example-portal.de) are fine.
REAL_ORG_DOMAINS = frozenset({
    "stackit.cloud", "allianz.com", "revel8.io", "revel8.com", "revel8.ai",
    "google.com", "microsoft.com", "notion.so", "slack.com",
})


def _domain_of(value: str) -> str:
    value = (value or "").strip()
    if "@" in value:  # an email address
        return value.rsplit("@", 1)[-1].lower()
    host = urlparse(value if "//" in value else f"//{value}").hostname or ""
    return host.lower()


def _is_real_org(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in REAL_ORG_DOMAINS)


def check_move(spec: MoveSpec, rendered: Optional[RenderedMessage] = None) -> list[str]:
    violations: list[str] = []

    sender_domain = _domain_of(spec.sender.address)
    if sender_domain and _is_real_org(sender_domain):
        violations.append(f"sender on real-org domain: {sender_domain}")

    if spec.url:
        page_domain = _domain_of(spec.url)
        if _is_real_org(page_domain):
            violations.append(f"landing page on real-org domain: {page_domain}")

    if rendered is not None:
        haystack = " ".join(filter(None, [rendered.body, rendered.subject])).lower()
        for phrase in BANNED_PHRASES:
            if phrase in haystack:
                violations.append(f"banned phrase: {phrase!r}")
        if rendered.page and _is_real_org(_domain_of(rendered.page.url)):
            violations.append("rendered page on real-org domain")

    return violations
