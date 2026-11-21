"""OSINT collectors for the reachable (open-tier) sources.

Each collector implements `research.sources.Collector`: seed → list[RawDoc]. They cover
the sources that answer to a plain HTTP fetch (public web pages, GitHub's public API,
RSS/Atom feeds, conference/talk pages). Login-walled sources (LinkedIn, Instagram, X)
need a scraping-API or headless backend — see research/ASSESSMENT.md — and would be
added here behind the same protocol with no change to the pipeline.
"""
from .feeds import FeedCollector
from .github import GitHubCollector
from .web import HttpFetcher, WebCollector

__all__ = ["WebCollector", "GitHubCollector", "FeedCollector", "HttpFetcher"]
