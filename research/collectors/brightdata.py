"""Bright Data Web Unlocker collector — the blocked-tier OSINT backend.

Reaches public pages a plain fetch can't: JS-rendered SPAs (revel8.ai, Personio) and
bot-blocked sites (seedtable 403s a plain GET). The Unlocker returns the fully-rendered
HTML, which we run through the *same* extraction as the open-tier web collector — so an
unlocked page yields the same provenance-stamped `Fact`s, just from a source that was
previously unreachable.

The scrape call is an injectable seam (`scrape(url) -> (status, html)`), so this is
unit-testable with no network and no Bright Data account:
  * default  — the Bright Data CLI (`bdata scrape`), which uses the local `bdata login`
               auth, so it works with zero extra config once the user has logged in.
  * optional — the Web Unlocker REST API, when `BRIGHTDATA_API_KEY` + a zone are set
               (for deployed / non-CLI use).

Rate-limited like every collector; robots is intentionally not applied here (the whole
point of this tier is pages that block naive clients) — scope stays public pages about
consenting targets, per the authorized-sandbox rules.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

from research.collectors.web import html_to_text, meta_published_date
from research.sources import Collector, RateLimiter, RawDoc, Seed, parse_http_date

# scrape(url) -> (status, html): status 200 == usable HTML, anything else == skip.
ScrapeFn = Callable[[str], "tuple[int, str]"]

BRIGHTDATA_REQUEST_URL = "https://api.brightdata.com/request"
DEFAULT_UNLOCKER_ZONE = "cli_unlocker"


class BrightDataCollector:
    """Fetches `seed.<url_field>` via the Web Unlocker; one `RawDoc` per reachable page."""

    source_type = "web"

    def __init__(
        self,
        scrape: Optional[ScrapeFn] = None,
        *,
        url_field: str = "unlock_urls",
        source_type: str = "web",
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._scrape = scrape or cli_unlocker_scrape
        self._url_field = url_field
        self.source_type = source_type
        self._rl = rate_limiter if rate_limiter is not None else RateLimiter(min_interval=1.0)

    def collect(self, seed: Seed) -> list[RawDoc]:
        urls = getattr(seed, self._url_field, ()) or ()
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            doc = self._collect_one(url)
            if doc is not None:
                docs.append(doc)
        return docs

    def _collect_one(self, url: str) -> Optional[RawDoc]:
        self._rl.wait(url)
        try:
            status, html = self._scrape(url)
        except Exception:
            return None  # a down backend must never sink the run
        if status != 200 or not html:
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
            meta={"via": "brightdata_unlocker"},
        )


# --------------------------------------------------------------------------- #
# Default scrape transports
# --------------------------------------------------------------------------- #
def cli_unlocker_scrape(
    url: str, *, bdata: str = "bdata", timeout: float = 90.0
) -> "tuple[int, str]":
    """Scrape via the Bright Data CLI using its stored login. Writes HTML to a temp file
    (so the CLI's progress lines never pollute the output) and returns (status, html)."""
    if shutil.which(bdata) is None:
        return 0, ""
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
    tmp.close()
    try:
        proc = subprocess.run(
            [bdata, "scrape", url, "-f", "html", "-o", tmp.name],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return 0, ""
        with open(tmp.name, "r", encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        return (200, html) if html.strip() else (0, "")
    except Exception:
        return 0, ""
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def rest_unlocker_scrape(
    url: str,
    *,
    api_key: Optional[str] = None,
    zone: Optional[str] = None,
    timeout: float = 90.0,
) -> "tuple[int, str]":
    """Scrape via the Web Unlocker REST API (for deployed/non-CLI use). Needs
    BRIGHTDATA_API_KEY and a zone (env `BRIGHTDATA_UNLOCKER_ZONE`, default cli_unlocker)."""
    api_key = api_key or os.environ.get("BRIGHTDATA_API_KEY")
    zone = zone or os.environ.get("BRIGHTDATA_UNLOCKER_ZONE") or DEFAULT_UNLOCKER_ZONE
    if not api_key:
        return 0, ""
    try:
        import requests

        resp = requests.post(
            BRIGHTDATA_REQUEST_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"zone": zone, "url": url, "format": "raw"},
            timeout=timeout,
        )
        if resp.status_code != 200 or not resp.text.strip():
            return 0, ""
        return 200, resp.text
    except Exception:
        return 0, ""


def brightdata_available(*, bdata: str = "bdata") -> bool:
    """True when a Bright Data backend is usable: the CLI is on PATH, or an API key is set."""
    return shutil.which(bdata) is not None or bool(os.environ.get("BRIGHTDATA_API_KEY"))


_: type[Collector] = BrightDataCollector
