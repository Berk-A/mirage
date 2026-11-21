"""Fetch a company's real logo so a sender's email/landing page can carry its brand —
credibility is trust, and a branded header reads as a reliable source. Public endpoints
only; every path is best-effort (any failure returns None and the renderer falls back to
a wordmark badge). No API keys required."""
from __future__ import annotations

import re
from typing import Optional

import requests

# Clearbit returns a proper logo; Google's favicon service is the fallback (always
# something, if only the site's favicon). Both are public and keyless.
_CLEARBIT = "https://logo.clearbit.com/{domain}?size=128&format=png"
_FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"


def company_from_address(address: str) -> str:
    """The org an email address speaks for — the domain's first label, with a lookalike/
    org suffix stripped (revel8-team.de -> 'revel8', eventcrew-muc.de -> 'eventcrew')."""
    if not address or "@" not in address:
        return ""
    label = address.split("@", 1)[1].split(".")[0]
    label = re.sub(r"-(team|muc|hq|corp|group|labs?|inc|io|co)$", "", label)
    return label.replace("-", " ").strip()


def _domain_guesses(company_or_domain: str) -> list[str]:
    """If given a domain, use it; else guess common TLDs from the company name."""
    s = company_or_domain.strip().lower()
    if "." in s and " " not in s:
        return [s]
    slug = re.sub(r"[^a-z0-9]", "", s)
    if not slug:
        return []
    return [f"{slug}.{tld}" for tld in ("ai", "com", "io", "co", "de")]


def fetch_company_logo(company_or_domain: str, *,
                       timeout: float = 12) -> Optional[tuple[bytes, str]]:
    """Return (image_bytes, content_type) for the company's logo, or None. Tries Clearbit
    (a real logo) then the favicon service, across a few domain guesses. Best-effort: never
    raises, never blocks the loop — the caller treats None as 'use the wordmark'."""
    for domain in _domain_guesses(company_or_domain):
        try:
            r = requests.get(_CLEARBIT.format(domain=domain), timeout=timeout)
            ctype = r.headers.get("content-type", "")
            if r.ok and r.content and ctype.startswith("image") and len(r.content) > 300:
                return r.content, ctype.split(";")[0] or "image/png"
        except requests.RequestException:
            pass
    for domain in _domain_guesses(company_or_domain):
        try:
            r = requests.get(_FAVICON.format(domain=domain), timeout=timeout)
            if r.ok and r.content and len(r.content) > 300:
                return r.content, "image/png"
        except requests.RequestException:
            pass
    return None
