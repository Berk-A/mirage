"""Optional Brave Search collector for public, challenge-authorized research.

Search results are treated only as sourced snippets. The existing extractor decides
whether a snippet supports a graph fact; search results never become facts by themselves.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import requests

from research.sources import Collector, RawDoc, Seed, parse_http_date

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchCollector:
    source_type = "web"

    def __init__(self, api_key: Optional[str] = None, *, session=None,
                 timeout: float = 20.0, results_per_query: int = 8):
        self.api_key = api_key if api_key is not None else os.environ.get("BRAVE_SEARCH_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.results_per_query = max(1, min(int(results_per_query), 20))
        self.last_warnings: list[str] = []

    def collect(self, seed: Seed) -> list[RawDoc]:
        self.last_warnings = []
        if not self.api_key:
            self.last_warnings.append("Brave Search skipped (BRAVE_SEARCH_API_KEY is unset)")
            return []
        queries = _queries(seed)
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for query in queries:
            try:
                response = self.session.get(
                    BRAVE_SEARCH_URL,
                    params={"q": query, "count": self.results_per_query},
                    headers={"X-Subscription-Token": self.api_key,
                             "Accept": "application/json"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                rows = (response.json().get("web") or {}).get("results") or ()
            except requests.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self.last_warnings.append(
                    f"Brave Search HTTP error{f' {status}' if status else ''}"
                )
                continue
            except Exception as exc:
                self.last_warnings.append(f"Brave Search failed ({type(exc).__name__})")
                continue
            for row in rows:
                url = str(row.get("url") or "").strip()
                title = str(row.get("title") or "").strip()
                description = str(row.get("description") or "").strip()
                if not url.startswith(("http://", "https://")) or url in seen:
                    continue
                if not (title or description):
                    continue
                seen.add(url)
                age = row.get("page_age")
                docs.append(RawDoc(
                    url=url,
                    title=title,
                    text=description or title,
                    source_type=self.source_type,
                    published_date=parse_http_date(str(age)) if age else None,
                    meta={"via": "brave_search", "query": query,
                          "page_age": age},
                ))
        return docs


def _queries(seed: Seed) -> tuple[str, ...]:
    person = f'"{seed.name}"'
    company = f'"{seed.company}"' if seed.company else ""
    context = " ".join(part for part in (person, company) if part)
    year = date.today().year
    return (
        context,
        f'{person} (speaker OR panel OR conference OR event OR keynote)',
        f'{person} {company} (team OR colleague OR co-founder OR partnership)',
        f'{person} {company} (upcoming OR will speak OR scheduled OR {year} OR {year + 1})',
    )


_: type[Collector] = BraveSearchCollector
