"""Personal / company website collector for arbitrary targets.

A target's own site — a personal homepage, an about/team page, a company site — is often
the richest first-party source, but many are JS-rendered or bot-blocked. This collector
generalises that: for each URL in `seed.websites` it tries a polite plain fetch first
(cheap, robots-respecting), and only on a block / failure / empty body falls back to the
Bright Data scraper (JS render + bot bypass). So one collector reaches both a static
personal blog and a JS-heavy company site, for any target, with no per-site config.

Both seams are injectable (`fetcher` and `scrape`), so unit tests exercise the plain path,
the fallback path and total failure with no network. One web `RawDoc` per reachable site,
run through the same extraction as every other web page.
"""
from __future__ import annotations

from typing import Optional

from research.collectors.brightdata import ScrapeFn, cli_unlocker_scrape
from research.collectors.web import HttpFetcher, html_to_text, meta_published_date
from research.sources import (
    Collector,
    RateLimiter,
    RawDoc,
    RobotsCache,
    Seed,
    parse_http_date,
)


class WebsiteCollector:
    """Fetch `seed.websites`, plain-first with a Bright Data fallback. One RawDoc each."""

    source_type = "web"

    def __init__(
        self,
        fetcher: Optional[HttpFetcher] = None,
        scrape: Optional[ScrapeFn] = None,
        *,
        robots: Optional[RobotsCache] = None,
        rate_limiter: Optional[RateLimiter] = None,
        seed_field: str = "websites",
        max_sites: int = 8,
        max_bytes: int = 2_000_000,
    ):
        self._fetch = fetcher or HttpFetcher()
        self._scrape = scrape if scrape is not None else cli_unlocker_scrape
        self._robots = robots if robots is not None else RobotsCache()
        self._rl = rate_limiter if rate_limiter is not None else RateLimiter()
        self._seed_field = seed_field
        self._max_sites = max(1, int(max_sites))
        self._max_bytes = max_bytes

    def collect(self, seed: Seed) -> list[RawDoc]:
        urls = getattr(seed, self._seed_field, ()) or ()
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for url in urls[: self._max_sites]:
            if not url or url in seen:
                continue
            seen.add(url)
            doc = self._collect_one(url)
            if doc is not None:
                docs.append(doc)
        return docs

    def _collect_one(self, url: str) -> Optional[RawDoc]:
        html, via = self._fetch_plain(url)
        if html is None:
            html, via = self._fetch_unlocked(url)
        if not html:
            return None
        title, text = html_to_text(html)
        if not text:
            return None
        return RawDoc(
            url=url,
            text=text,
            source_type=self.source_type,
            title=title,
            published_date=meta_published_date(html),
            meta={"via": via},
        )

    def _fetch_plain(self, url: str) -> "tuple[Optional[str], str]":
        if not self._robots.allowed(url):
            return None, ""  # robots-disallowed → let the scraper try (public OSINT)
        self._rl.wait(url)
        try:
            result = self._fetch.get(url)
        except Exception:
            return None, ""
        if result.status != 200 or not result.text:
            return None, ""
        if len(result.text) > self._max_bytes:
            return None, ""
        return result.text, "plain_fetch"

    def _fetch_unlocked(self, url: str) -> "tuple[Optional[str], str]":
        self._rl.wait(url)
        try:
            status, html = self._scrape(url)
        except Exception:
            return None, ""
        if status != 200 or not html:
            return None, ""
        return html, "brightdata_scrape"


_: type[Collector] = WebsiteCollector
