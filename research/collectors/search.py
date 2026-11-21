"""Search/discovery collector — the missing front of the OSINT funnel.

Every other collector needs a URL handed to it; this one *finds* the URLs. For each
seed it runs a small set of targeted SerpAPI (Google) queries built from the target's
name + company, and turns each organic result into a `RawDoc`:

  * the result title+snippet itself (``source_type="search"``) — these short snippets
    are genuinely extractable: a LinkedIn result title carries the role, a press snippet
    carries "backed by <VC>" and "raised €N", a job snippet carries the stack.
  * up to a couple of *high-value discovered pages on the company's own domain*
    (e.g. revel8.ai/*) fetched through the Bright Data Web Unlocker and reduced to
    visible text (``source_type="web"``) for the deeper first-party facts.

Both network calls are injectable seams (`search` / `unlock`), so the collector is
unit-testable with no network and no API keys. It is defensive by construction: a
missing key, an HTTP error, bad JSON, or a dead backend all degrade to `[]` (or to
fewer docs) and never raise — a starved search must never sink the run. Queries,
results and deep-fetches are all capped so one `collect()` stays well under ~30s.
"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from research.collectors.brightdata import rest_unlocker_scrape
from research.collectors.web import html_to_text, meta_published_date
from research.sources import Collector, RateLimiter, RawDoc, Seed, parse_http_date

SERPAPI_URL = "https://serpapi.com/search.json"

# search(query, api_key, num) -> list of organic-result dicts {title, link, snippet, date?}
SearchFn = Callable[..., list]
# unlock(url) -> (status, html)
UnlockFn = Callable[[str], "tuple[int, str]"]


class SerpApiDiscoveryCollector:
    """Discovers OSINT URLs for a seed via SerpAPI, then deepens the best company-domain
    hits via the Bright Data Web Unlocker. One `RawDoc` per unique result/page."""

    source_type = "search"

    def __init__(
        self,
        search: Optional[SearchFn] = None,
        unlock: Optional[UnlockFn] = None,
        *,
        api_key: Optional[str] = None,
        max_queries: int = 5,
        num: int = 8,
        max_results: int = 24,
        max_fetch: int = 2,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._search = search or serpapi_search
        self._unlock = unlock or rest_unlocker_scrape
        self._api_key = api_key  # resolved from env at collect() time when None
        self._max_queries = max_queries
        self._num = num
        self._max_results = max_results
        self._max_fetch = max_fetch
        # SerpAPI is one host and fine to hit back-to-back; small courtesy gap only.
        self._rl = rate_limiter if rate_limiter is not None else RateLimiter(min_interval=0.3)

    def collect(self, seed: Seed) -> list[RawDoc]:
        key = self._api_key or os.environ.get("SERP_API_KEY")
        if not key:
            return []
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for query in self._queries(seed)[: self._max_queries]:
            if len(docs) >= self._max_results:
                break
            for result in self._run(query, key):
                link = (result.get("link") or "").strip()
                if not link or link in seen or _is_redirect(link):
                    continue
                seen.add(link)
                title = (result.get("title") or "").strip()
                snippet = (result.get("snippet") or "").strip()
                text = f"{title}. {snippet}".strip(". ").strip()
                if not text:
                    continue
                docs.append(
                    RawDoc(
                        url=link,
                        text=f"{title}. {snippet}".strip() if snippet else title,
                        source_type="search",
                        title=title,
                        published_date=parse_http_date(result.get("date")),
                        meta={"via": "serpapi", "query": query},
                    )
                )
                if len(docs) >= self._max_results:
                    break
        # Deepen: fetch a couple of discovered first-party (company-domain) pages.
        docs.extend(self._deep_fetch(seed, [d.url for d in docs]))
        return docs

    # ---- internals ----------------------------------------------------- #
    def _run(self, query: str, key: str) -> list:
        self._rl.wait(SERPAPI_URL)
        try:
            results = self._search(query, api_key=key, num=self._num)
        except Exception:
            return []
        return results if isinstance(results, list) else []

    def _queries(self, seed: Seed) -> list[str]:
        name, company = seed.name.strip(), seed.company.strip()
        qs: list[str] = []
        if name and company:
            qs.append(f'"{name}" {company}')
            qs.append(f"{name} {company} linkedin")
            qs.append(f"{name} {company} interview OR podcast")
        if company:
            qs.append(f'{company} "we use" OR stack OR engineering OR hiring')
            qs.append(f'{company} "backed by" OR investors OR raised')
        elif name:
            qs.append(f'"{name}" interview OR podcast')
        return qs

    def _deep_fetch(self, seed: Seed, urls: list[str]) -> list[RawDoc]:
        if self._max_fetch <= 0:
            return []
        out: list[RawDoc] = []
        seen: set[str] = set()
        for url in self._company_pages(seed, urls)[: self._max_fetch]:
            if url in seen:
                continue
            seen.add(url)
            try:
                status, html = self._unlock(url)
            except Exception:
                continue
            if status != 200 or not html:
                continue
            title, text = html_to_text(html)
            if not text:
                continue
            out.append(
                RawDoc(
                    url=url,
                    text=text,
                    source_type="web",
                    title=title,
                    published_date=meta_published_date(html),
                    meta={"via": "serpapi_discovery+brightdata_unlocker"},
                )
            )
        return out

    def _company_pages(self, seed: Seed, urls: list[str]) -> list[str]:
        """Discovered URLs on the company's own domain(s), best pages first."""
        tokens = _company_tokens(seed)
        if not tokens:
            return []
        candidates: list[str] = []
        for url in urls:
            host = urlparse(url).netloc.lower()
            if not host or "linkedin." in host or "/jobs" in url:
                continue
            if any(tok in host for tok in tokens):
                candidates.append(url)
        # Prefer bio/about/team/blog/product pages (richer first-party facts).
        rich = ("author", "about", "team", "founder", "people", "blog", "news",
                "product", "company", "press")
        candidates.sort(key=lambda u: (not any(k in u.lower() for k in rich), len(u)))
        # Dedup keeping order.
        seen: set[str] = set()
        ordered = []
        for u in candidates:
            if u not in seen:
                seen.add(u)
                ordered.append(u)
        return ordered


def _is_redirect(url: str) -> bool:
    """Skip search-engine redirect/cache links (e.g. google.com/goto?url=…): they carry
    no usable provenance and can't be deep-fetched."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in {"google.com", "bing.com", "duckduckgo.com", "googleusercontent.com",
                "webcache.googleusercontent.com"}:
        return True
    if host.endswith(".google.com") or host.endswith(".googleusercontent.com"):
        return True
    return "/goto?url=" in url or "/url?q=" in url


def _company_tokens(seed: Seed) -> list[str]:
    toks: list[str] = []
    for dom in seed.domains:
        host = dom.lower().replace("https://", "").replace("http://", "").split("/")[0]
        host = host[4:] if host.startswith("www.") else host
        if host:
            toks.append(host)
    slug = re.sub(r"[^a-z0-9]", "", seed.company.lower())
    if len(slug) >= 4:
        toks.append(slug)
    return toks


# --------------------------------------------------------------------------- #
# Default transports
# --------------------------------------------------------------------------- #
def serpapi_search(
    query: str,
    *,
    api_key: Optional[str] = None,
    num: int = 8,
    engine: str = "google",
    timeout: float = 20.0,
) -> list:
    """Default SerpAPI transport: GET the search JSON, return `organic_results` (or [])."""
    api_key = api_key or os.environ.get("SERP_API_KEY")
    if not api_key:
        return []
    try:
        import requests

        resp = requests.get(
            SERPAPI_URL,
            params={"engine": engine, "num": num, "q": query, "api_key": api_key},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    results = data.get("organic_results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


def serpapi_available() -> bool:
    """True when a SerpAPI key is configured (env `SERP_API_KEY`)."""
    return bool(os.environ.get("SERP_API_KEY"))


# Keep the protocol honest at import time.
_: type[Collector] = SerpApiDiscoveryCollector
