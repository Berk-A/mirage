"""Collection primitives: the raw document every collector returns, the `Collector`
protocol, and polite-fetch helpers (robots.txt + rate limiting).

A collector's only job is to turn a reachable public source into `RawDoc`s with a
**source URL and a fetch date**. All interpretation happens later in `extract`, so a
collector never invents facts — it just carries bytes + provenance forward.
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import urlparse

# A neutral, honest client name. We never put the user's identity in the UA (privacy),
# and we identify as an automated client so sites can rate-limit/deny us by policy.
USER_AGENT = "mirage-research-bot/0.1 (OSINT; respects robots.txt)"
DEFAULT_TIMEOUT = 15.0


def today_iso() -> str:
    return date.today().isoformat()


@dataclass(frozen=True)
class RawDoc:
    """One fetched public document, with the provenance every downstream fact inherits.

    `source_type` is a coarse tag (`web`, `github`, `feed`, `talk`, ...) so extraction
    can pick the right rules. `fetched_date` is when *we* saw it; `published_date` (when
    known) is when the source says the content is from — that one drives recency.
    """

    url: str
    text: str
    source_type: str = "web"
    title: str = ""
    fetched_date: str = field(default_factory=today_iso)
    published_date: Optional[str] = None
    meta: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class Collector(Protocol):
    """Turns a seed into raw public docs. Implementations may hit the network; unit
    tests pass a fake `fetch` or mock the transport, never the real internet."""

    source_type: str

    def collect(self, seed: "Seed") -> list[RawDoc]: ...


# Seed lives here to avoid a cycle (collectors + pipeline both need it).
@dataclass(frozen=True)
class Seed:
    """Public-OSINT entry points for one target. Everything here is public and the
    starting point for collection, never a secret. `urls` are known pages; `github`,
    `domains` and `feeds` seed the specialised collectors; `aliases` help entity
    resolution tie variants of the name together."""

    target_id: str
    name: str
    role: str = ""
    company: str = ""
    urls: tuple[str, ...] = ()
    github: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    # Publicly-known colleagues (e.g. co-founders). Co-mention on a page about the
    # target becomes a `colleague_of` edge → the most credible senders of all.
    colleagues: tuple[str, ...] = ()
    # Public pages that a plain fetch can't reach (JS-rendered / bot-blocked), routed
    # through the Bright Data Web Unlocker collector. Same extraction as `urls`.
    unlock_urls: tuple[str, ...] = ()


class RobotsCache:
    """Per-host robots.txt gate. Fail-open on fetch errors (treat as allowed) but
    honour an explicit Disallow. Keeps us a polite OSINT client, which the challenge
    requires ('respect robots/rate limits')."""

    def __init__(self, fetcher=None) -> None:
        self._cache: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._fetch = fetcher  # (url) -> text | None ; None means "could not read"

    def allowed(self, url: str, user_agent: str = USER_AGENT) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._cache:
            self._cache[host] = self._load(host)
        rp = self._cache[host]
        if rp is None:
            return True  # fail-open: no readable robots.txt
        return rp.can_fetch(user_agent, url)

    def _load(self, host: str):
        robots_url = f"{host}/robots.txt"
        text: Optional[str]
        if self._fetch is not None:
            text = self._fetch(robots_url)
        else:
            text = _default_robots_fetch(robots_url)
        if not text:
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        return rp


def _default_robots_fetch(robots_url: str) -> Optional[str]:
    try:
        import requests

        resp = requests.get(
            robots_url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


class RateLimiter:
    """Minimum interval between fetches to the same host. Injectable clock/sleeper so
    tests run instantly."""

    def __init__(self, min_interval: float = 1.0, *, clock=time.monotonic, sleeper=time.sleep):
        self._min = min_interval
        self._clock = clock
        self._sleep = sleeper
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        now = self._clock()
        last = self._last.get(host)
        if last is not None:
            gap = self._min - (now - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._clock()


def parse_http_date(value: Optional[str]) -> Optional[str]:
    """Best-effort HTTP/ISO date string → ISO date (YYYY-MM-DD), or None."""
    if not value:
        return None
    value = value.strip()
    for parser in (_parse_rfc2822, _parse_iso):
        out = parser(value)
        if out:
            return out
    return None


def _parse_rfc2822(value: str) -> Optional[str]:
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        return dt.astimezone(timezone.utc).date().isoformat()
    except Exception:
        return None


def _parse_iso(value: str) -> Optional[str]:
    try:
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date().isoformat()
    except Exception:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
        except Exception:
            return None
