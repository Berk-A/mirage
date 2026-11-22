"""Structured social-profile collectors — LinkedIn, Facebook, Instagram.

These reach the login-walled, bot-blocked platforms that a plain fetch (and even the
Web Unlocker's raw HTML) can't turn into clean facts. They use Bright Data's *structured*
scrapers (`bdata pipelines`, the `data-feeds` skill): one record per profile URL, already
parsed into fields (name, headline, current title/company, location, recent posts). The
collector normalises that platform-specific JSON into one shape, renders it to a readable
`RawDoc`, and stamps the structured fields into `RawDoc.meta` so `extract._extract_social`
can emit *high-confidence* identity/role facts and dated activity hooks — the specific,
cross-checkable intel the open-tier press pages can't give.

Design parity with the rest of the collector set:
  * injectable transport seam `scrape(platform, url) -> dict | None`, so unit tests need
    no network, no Bright Data account, no keys;
  * degrade to `[]` on ANY failure (a dead platform must never sink a run);
  * per-host rate limiting + a small per-collect cap so one `collect()` stays well under
    ~30s even when a profile scrape is slow;
  * an optional on-disk cache under `runs/osint_cache` (the structured scrapers are billed
    per record, so a replayed run should not re-scrape). Only public profile data is
    cached — never credentials or private contact details.

The whole tier is gated on a usable Bright Data backend exactly like `BrightDataCollector`
(`social_available()` == `brightdata_available()`), so offline / no-key runs never add it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional

from research.sources import Collector, RateLimiter, RawDoc, Seed, parse_http_date

# scrape(platform, url) -> normalised record dict, or None when unreachable/blocked.
#
# The normalised record is a flat, platform-agnostic shape (any key may be missing):
#   {
#     "name": str, "headline": str, "title": str, "company": str, "location": str,
#     "url": str, "followers": int | None,
#     "posts": [ {"text": str, "date": "YYYY-MM-DD" | None, "url": str}, ... ],
#   }
ScrapeFn = Callable[[str, str], Optional[dict]]

DEFAULT_CACHE_DIR = os.path.join("runs", "osint_cache")


# --------------------------------------------------------------------------- #
# Collector
# --------------------------------------------------------------------------- #
class SocialProfileCollector:
    """Base for the per-platform structured-profile collectors.

    Subclasses set `platform`, `source_type`, `seed_field`, `profile_base` and
    `platform_label`; the collection/rendering/caching machinery is shared.
    """

    platform: str = "social"
    source_type: str = "social"
    seed_field: str = ""
    profile_base: str = ""
    platform_label: str = "social media"

    def __init__(
        self,
        scrape: Optional[ScrapeFn] = None,
        *,
        rate_limiter: Optional[RateLimiter] = None,
        cache_dir: Optional[str] = DEFAULT_CACHE_DIR,
        max_profiles: int = 3,
        max_posts: int = 5,
    ):
        self._scrape = scrape if scrape is not None else cli_pipeline_scrape
        self._rl = rate_limiter if rate_limiter is not None else RateLimiter(min_interval=1.0)
        self._cache = _DiskCache(cache_dir, self.platform) if cache_dir else None
        self._max_profiles = max(1, int(max_profiles))
        self._max_posts = max(0, int(max_posts))
        self.last_warnings: list[str] = []

    # -- public API ------------------------------------------------------- #
    def collect(self, seed: Seed) -> list[RawDoc]:
        self.last_warnings = []
        handles = getattr(seed, self.seed_field, ()) or ()
        docs: list[RawDoc] = []
        seen: set[str] = set()
        for handle in handles[: self._max_profiles]:
            url = self.profile_url(handle)
            if not url or url in seen:
                continue
            seen.add(url)
            doc = self._collect_one(url)
            if doc is not None:
                docs.append(doc)
        return docs

    def profile_url(self, handle: str) -> str:
        """Normalise a bare handle or a full profile URL to a canonical profile URL."""
        h = (handle or "").strip()
        if not h:
            return ""
        if h.startswith(("http://", "https://")):
            return h
        if self.platform in h.lower():  # e.g. "linkedin.com/in/x" without a scheme
            return f"https://{h.lstrip('/')}"
        return f"{self.profile_base}{h.strip('/')}"

    # -- internals -------------------------------------------------------- #
    def _collect_one(self, url: str) -> Optional[RawDoc]:
        record = self._cache.get(url) if self._cache else None
        if record is None:
            self._rl.wait(url)
            try:
                record = self._scrape(self.platform, url)
            except Exception as exc:  # a down backend must never sink the run
                self.last_warnings.append(
                    f"{self.platform} scrape failed ({type(exc).__name__})"
                )
                return None
            if not isinstance(record, dict) or not record:
                return None
            if self._cache:
                self._cache.set(url, record)
        return self._render(record, url)

    def _render(self, record: Mapping[str, object], url: str) -> Optional[RawDoc]:
        fields = _clean_fields(record)
        posts = _clean_posts(record.get("posts"), self._max_posts)
        text = _render_text(fields, posts, self.platform_label)
        if not text:
            return None
        published = _latest_post_date(posts)
        return RawDoc(
            url=str(fields.get("url") or url),
            text=text,
            source_type=self.source_type,
            title=f"{self.platform_label} profile: {fields.get('name') or url}",
            published_date=published,
            meta={
                "platform": self.platform,
                "kind": "profile",
                "fields": fields,
                "posts": posts,
            },
        )


class LinkedInCollector(SocialProfileCollector):
    platform = "linkedin"
    source_type = "linkedin"
    seed_field = "linkedin"
    profile_base = "https://www.linkedin.com/in/"
    platform_label = "LinkedIn"

    def profile_url(self, handle: str) -> str:
        h = (handle or "").strip()
        if h and not h.startswith(("http://", "https://")) and "linkedin.com" not in h.lower():
            h = h[3:] if h.lower().startswith("in/") else h  # accept "in/jmuth" or "jmuth"
            return f"{self.profile_base}{h.strip('/')}"
        return super().profile_url(handle)


class FacebookCollector(SocialProfileCollector):
    platform = "facebook"
    source_type = "facebook"
    seed_field = "facebook"
    profile_base = "https://www.facebook.com/"
    platform_label = "Facebook"


class InstagramCollector(SocialProfileCollector):
    platform = "instagram"
    source_type = "instagram"
    seed_field = "instagram"
    profile_base = "https://www.instagram.com/"
    platform_label = "Instagram"


SOCIAL_SOURCE_TYPES = frozenset({"linkedin", "facebook", "instagram"})


def social_available(*, bdata: str = "bdata") -> bool:
    """True when a Bright Data backend can run the structured scrapers (CLI or API key)."""
    return shutil.which(bdata) is not None or bool(os.environ.get("BRIGHTDATA_API_KEY"))


# --------------------------------------------------------------------------- #
# Record normalisation (tolerant — any key may be absent)
# --------------------------------------------------------------------------- #
def _clean_fields(record: Mapping[str, object]) -> dict:
    out: dict[str, object] = {}
    for key in ("name", "headline", "title", "company", "location", "url"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    followers = record.get("followers")
    if isinstance(followers, int):
        out["followers"] = followers
    return out


def _clean_posts(posts: object, max_posts: int) -> list[dict]:
    if not isinstance(posts, (list, tuple)) or max_posts <= 0:
        return []
    out: list[dict] = []
    for post in posts:
        if not isinstance(post, Mapping):
            continue
        text = post.get("text") or post.get("caption") or post.get("title")
        if not isinstance(text, str) or not text.strip():
            continue
        entry: dict[str, object] = {"text": " ".join(text.split())[:400]}
        raw_date = (post.get("date") or post.get("created_at") or post.get("datetime")
                    or post.get("published") or post.get("time") or "")
        date = parse_http_date(str(raw_date)) or None
        if date:
            entry["date"] = date
        link = post.get("url") or post.get("link")
        if isinstance(link, str) and link.strip():
            entry["url"] = link.strip()
        out.append(entry)
        if len(out) >= max_posts:
            break
    return out


def _render_text(fields: Mapping[str, object], posts: list[dict], label: str) -> str:
    parts: list[str] = []
    name = fields.get("name")
    if name:
        parts.append(f"{label} profile of {name}.")
    for key, prefix in (
        ("title", "Title"),
        ("company", "Company"),
        ("headline", "Headline"),
        ("location", "Location"),
    ):
        value = fields.get(key)
        if value:
            parts.append(f"{prefix}: {value}.")
    for post in posts:
        date = f" ({post['date']})" if post.get("date") else ""
        parts.append(f"Post{date}: {post['text']}")
    return " ".join(parts).strip()


def _latest_post_date(posts: list[dict]) -> Optional[str]:
    dates = [p["date"] for p in posts if p.get("date")]
    return max(dates) if dates else None


# --------------------------------------------------------------------------- #
# On-disk cache (billed scrapers → never re-scrape on replay; public data only)
# --------------------------------------------------------------------------- #
class _DiskCache:
    def __init__(self, base_dir: str, platform: str):
        self._dir = Path(base_dir) / platform

    def _path(self, url: str) -> Path:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return self._dir / f"{key}.json"

    def get(self, url: str) -> Optional[dict]:
        try:
            path = self._path(url)
            if not path.exists():
                return None
            with path.open("r", encoding="utf-8") as fh:
                obj = json.load(fh)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def set(self, url: str, record: Mapping[str, object]) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._path(url).open("w", encoding="utf-8") as fh:
                json.dump(record, fh)
        except Exception:
            pass  # cache is best-effort; a write failure must never sink the run


# --------------------------------------------------------------------------- #
# Default live transport. Two Bright Data CLI generations are in the wild and we support
# both, trying the one installed here first:
#   * v0.3.x — fixed pipeline *types*:  `bdata pipelines <type> <url> --format json`
#   * v0.4.0+ — dataset + method:        `bdata pipelines run <dataset> collect_by_url <url>`
# Best-effort + fully degrading: the unit tests never reach this (they inject a fake
# `scrape`); a wrong guess or a down backend just yields no docs, never a crash.
# --------------------------------------------------------------------------- #
# v0.3.x fixed pipeline type per platform (from `bdata pipelines list`). Facebook has NO
# person-profile scraper in the catalog, so it stays unmapped → the live path returns
# None and the collector degrades (the collector + extraction still work on any newer CLI
# or dataset that does expose one, via an injected transport). Overridable by env.
_PIPELINE_TYPE = {
    "linkedin": "linkedin_person_profile",
    "instagram": "instagram_profiles",
}
_TYPE_ENV = {
    "linkedin": "BRIGHTDATA_LINKEDIN_PIPELINE",
    "facebook": "BRIGHTDATA_FACEBOOK_PIPELINE",
    "instagram": "BRIGHTDATA_INSTAGRAM_PIPELINE",
}
_SEARCH_QUERY = {
    "linkedin": "linkedin profiles",
    "facebook": "facebook profiles",
    "instagram": "instagram profiles",
}
_dataset_cache: dict[str, Optional[str]] = {}


def cli_pipeline_scrape(
    platform: str, url: str, *, bdata: str = "bdata", timeout: float = 60.0
) -> Optional[dict]:
    """Scrape one profile via the Bright Data structured scrapers using the stored login."""
    if shutil.which(bdata) is None:
        return None
    record = _run_fixed_type(platform, url, bdata=bdata, timeout=timeout)
    if record is None:  # newer CLI removed fixed types → try the dataset/method interface
        record = _run_dataset_method(platform, url, bdata=bdata, timeout=timeout)
    if not isinstance(record, dict) or record.get("error"):
        return None
    return _normalise_platform_record(platform, record, url)


def _parse_first_record(stdout: str) -> Optional[dict]:
    try:
        data = json.loads(stdout)
    except Exception:
        return None
    record = data[0] if isinstance(data, list) and data else data
    return record if isinstance(record, dict) else None


def _run_fixed_type(
    platform: str, url: str, *, bdata: str = "bdata", timeout: float = 60.0
) -> Optional[dict]:
    """v0.3.x: `bdata pipelines <type> <url> --format json`."""
    ptype = os.environ.get(_TYPE_ENV.get(platform, "")) or _PIPELINE_TYPE.get(platform)
    if not ptype:
        return None
    try:
        proc = subprocess.run(
            [bdata, "pipelines", ptype, url, "--format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return _parse_first_record(proc.stdout)
    except Exception:
        return None


def _run_dataset_method(
    platform: str, url: str, *, bdata: str = "bdata", timeout: float = 60.0
) -> Optional[dict]:
    """v0.4.0+: resolve a dataset id, then `bdata pipelines run <dataset> collect_by_url`."""
    dataset = _resolve_dataset(platform, bdata=bdata)
    if not dataset:
        return None
    try:
        proc = subprocess.run(
            [bdata, "pipelines", "run", dataset, "collect_by_url", url, "--format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return _parse_first_record(proc.stdout)
    except Exception:
        return None


def _resolve_dataset(platform: str, *, bdata: str = "bdata") -> Optional[str]:
    if platform in _dataset_cache:
        return _dataset_cache[platform]
    dataset: Optional[str] = None
    try:
        proc = subprocess.run(
            [bdata, "pipelines", "search", _SEARCH_QUERY[platform], "--json"],
            capture_output=True, text=True, timeout=20.0,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            rows = json.loads(proc.stdout)
            for row in rows if isinstance(rows, list) else []:
                methods = row.get("collection_methods") or []
                if platform in str(row.get("domain", "")).lower() and "collect_by_url" in methods:
                    dataset = str(row.get("dataset_id") or "") or None
                    break
    except Exception:
        dataset = None
    _dataset_cache[platform] = dataset
    return dataset


def _normalise_platform_record(platform: str, rec: Mapping[str, object], url: str) -> dict:
    """Map a platform's Bright Data JSON onto our flat record shape. Tolerant of missing
    keys and of the schema drift these datasets are prone to."""
    def first(*keys):
        for key in keys:
            value = rec.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, Mapping):  # e.g. current_company: {"name": ...}
                inner = value.get("name")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return ""

    out: dict[str, object] = {"url": first("input_url", "url") or url}
    out["name"] = first("name", "full_name", "account", "title")
    out["headline"] = first("headline", "position", "biography", "about", "bio")
    # The cleanest title is current_company.title ("Chairman and CEO"); `position` carries
    # the employer suffix ("... at Microsoft"), stripped downstream anyway.
    cc = rec.get("current_company")
    cc_title = cc.get("title") if isinstance(cc, Mapping) else None
    out["title"] = ((cc_title or "").strip() if isinstance(cc_title, str) else "") or first(
        "title", "position", "job_title", "current_title"
    )
    out["company"] = first("company", "current_company", "current_company_name", "employer")
    out["location"] = first("location", "city", "country")
    followers = rec.get("followers") or rec.get("followers_count")
    if isinstance(followers, int):
        out["followers"] = followers
    raw_posts = rec.get("posts") or rec.get("activity") or rec.get("recent_posts") or []
    posts: list[dict] = []
    if isinstance(raw_posts, list):
        for post in raw_posts[:10]:
            if isinstance(post, Mapping):
                posts.append(dict(post))
            elif isinstance(post, str) and post.strip():
                posts.append({"text": post})
    out["posts"] = posts
    return {k: v for k, v in out.items() if v not in ("", None)}


_: type[Collector] = LinkedInCollector
