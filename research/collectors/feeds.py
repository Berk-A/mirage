"""RSS/Atom feed collector — blog posts, news, talk announcements.

Feeds are the cheapest *timestamped* source, which makes them the backbone of the
recency ranker: each entry carries a real published date. One `RawDoc` per entry.
"""
from __future__ import annotations

from typing import Optional

import feedparser

from research.sources import Collector, RawDoc, Seed, parse_http_date


class FeedFetcher:
    """Network seam: `.parse(url) -> feedparser-like dict`. Tests inject a fake."""

    def parse(self, url: str):
        return feedparser.parse(url)


class FeedCollector:
    source_type = "feed"

    def __init__(self, fetcher: Optional[FeedFetcher] = None, *, max_entries: int = 20):
        self._fetch = fetcher or FeedFetcher()
        self._max = max_entries

    def collect(self, seed: Seed) -> list[RawDoc]:
        docs: list[RawDoc] = []
        for feed_url in seed.feeds:
            docs.extend(self._collect_feed(feed_url))
        return docs

    def _collect_feed(self, feed_url: str) -> list[RawDoc]:
        try:
            parsed = self._fetch.parse(feed_url)
        except Exception:
            return []  # a broken feed must not sink the others
        entries = _entries(parsed)
        feed_title = _feed_title(parsed)
        docs: list[RawDoc] = []
        for entry in entries[: self._max]:
            link = _get(entry, "link") or feed_url
            title = _get(entry, "title")
            summary = _get(entry, "summary") or _get(entry, "description")
            published = parse_http_date(_get(entry, "published") or _get(entry, "updated"))
            text = " ".join(p for p in (title, summary) if p)
            if not text:
                continue
            docs.append(
                RawDoc(
                    url=link,
                    text=text,
                    source_type=self.source_type,
                    title=title or feed_title,
                    published_date=published,
                    meta={"feed": feed_url, "feed_title": feed_title},
                )
            )
        return docs


def _entries(parsed) -> list:
    if isinstance(parsed, dict):
        return parsed.get("entries", []) or []
    return getattr(parsed, "entries", []) or []


def _feed_title(parsed) -> str:
    feed = parsed.get("feed", {}) if isinstance(parsed, dict) else getattr(parsed, "feed", {})
    return _get(feed, "title")


def _get(obj, key: str) -> str:
    if obj is None:
        return ""
    if isinstance(obj, dict):
        val = obj.get(key, "")
    else:
        val = getattr(obj, key, "")
    return (val or "").strip() if isinstance(val, str) else ""


_: type[Collector] = FeedCollector
