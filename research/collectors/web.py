"""Generic public-web collector: fetch a seed's known pages (and a target's own
domains' about/team pages), return each as a `RawDoc` of readable text.

Network is isolated behind `HttpFetcher`, which unit tests replace with a dict-backed
fake. Robots.txt and per-host rate limiting are enforced here, not by every caller.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from bs4 import BeautifulSoup

from research.sources import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    Collector,
    RateLimiter,
    RawDoc,
    RobotsCache,
    Seed,
    parse_http_date,
)

# Transient HTTP statuses worth a retry (the target API doc uses the same set).
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    text: str
    content_type: str = ""
    last_modified: Optional[str] = None


class HttpFetcher:
    """The one network seam for the web/feed collectors: `.get(url) -> FetchResult`.

    Retries transient failures (connection errors + 429/5xx) with exponential backoff,
    then gives up and returns a non-200 `FetchResult` the collector treats as "skip".
    The actual single request is an injectable `transport`, so retry/timeout behaviour
    is unit-testable with no network; collector tests inject a fake `.get` and never
    reach this class at all.
    """

    def __init__(
        self,
        transport: Optional[Callable[[str, dict, float], object]] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = USER_AGENT,
        retries: int = 2,
        backoff: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._transport = transport or _requests_transport
        self._timeout = timeout
        self._ua = user_agent
        self._retries = max(0, retries)
        self._backoff = backoff
        self._sleep = sleeper

    def get(self, url: str) -> FetchResult:
        headers = {"User-Agent": self._ua}
        last: Optional[FetchResult] = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._transport(url, headers, self._timeout)
                status = int(getattr(resp, "status_code", 0))
                last = FetchResult(
                    url=str(getattr(resp, "url", url) or url),
                    status=status,
                    text=getattr(resp, "text", "") if status == 200 else "",
                    content_type=_header(resp, "Content-Type"),
                    last_modified=_header(resp, "Last-Modified"),
                )
                if status not in RETRY_STATUSES:
                    return last
            except Exception:
                last = FetchResult(url=url, status=0, text="")
            if attempt < self._retries:
                self._sleep(self._backoff * (2 ** attempt))
        return last if last is not None else FetchResult(url=url, status=0, text="")


def _requests_transport(url: str, headers: dict, timeout: float):
    import requests

    return requests.get(url, headers=headers, timeout=timeout)


def _header(resp, name: str) -> str:
    headers = getattr(resp, "headers", None)
    if not headers:
        return ""
    try:
        return headers.get(name, "") or ""
    except Exception:
        return ""


def html_to_text(html: str) -> tuple[str, str]:
    """(title, visible_text) from an HTML document. Scripts/styles/nav/footer stripped;
    whitespace collapsed. A person reads the visible text, so that is what we keep."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    text = soup.get_text(separator=" ")
    text = " ".join(text.split())
    return title, text


def meta_published_date(html: str) -> Optional[str]:
    """Pull a published date from common meta tags (article:published_time, etc.)."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "article:published_time"}),
        ("meta", {"property": "og:updated_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"itemprop": "datePublished"}),
        ("time", {"datetime": True}),
    ]
    for tag_name, attrs in candidates:
        el = soup.find(tag_name, attrs=attrs)
        if el is None:
            continue
        value = el.get("content") or el.get("datetime")
        parsed = parse_http_date(value)
        if parsed:
            return parsed
    return None


class WebCollector:
    """Fetches `seed.urls`, politely. One `RawDoc` per reachable HTML page."""

    source_type = "web"

    def __init__(
        self,
        fetcher: Optional[HttpFetcher] = None,
        *,
        robots: Optional[RobotsCache] = None,
        rate_limiter: Optional[RateLimiter] = None,
        max_bytes: int = 2_000_000,
    ):
        self._fetch = fetcher or HttpFetcher()
        self._robots = robots if robots is not None else RobotsCache()
        self._rl = rate_limiter if rate_limiter is not None else RateLimiter()
        self._max_bytes = max_bytes

    def collect(self, seed: Seed) -> list[RawDoc]:
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for url in seed.urls:
            if url in seen:
                continue
            seen.add(url)
            doc = self._collect_one(url)
            if doc is not None:
                docs.append(doc)
        return docs

    def _collect_one(self, url: str) -> Optional[RawDoc]:
        if not self._robots.allowed(url):
            return None
        self._rl.wait(url)
        try:
            result = self._fetch.get(url)
        except Exception:
            return None
        if result.status != 200 or not result.text:
            return None
        if len(result.text) > self._max_bytes:
            return None
        if "html" not in (result.content_type or "html").lower():
            # Still try to parse; many servers omit/garble content-type.
            pass
        title, text = html_to_text(result.text)
        if not text:
            return None
        published = meta_published_date(result.text) or parse_http_date(result.last_modified)
        return RawDoc(
            url=result.url or url,
            text=text,
            source_type=self.source_type,
            title=title,
            published_date=published,
        )


# Keep the protocol honest at import time.
_: type[Collector] = WebCollector
