"""GitHub collector over the public REST API.

A founder's GitHub tells you their stack (languages), current projects (recently
pushed repos) and sometimes their employer/bio — all public, all provenance-stamped
with the API URL + fetch date. No key needed at this volume; an optional `GITHUB_TOKEN`
raises the rate limit 60→5000 req/hr.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from research.sources import USER_AGENT, Collector, RawDoc, Seed, parse_http_date

GITHUB_API = "https://api.github.com"


class GitHubJsonFetcher:
    """Network seam for the GitHub API. `.get_json(url) -> (status, obj)`."""

    def __init__(self, *, token: Optional[str] = None, timeout: float = 15.0):
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._timeout = timeout

    def get_json(self, url: str):
        import requests

        headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = requests.get(url, headers=headers, timeout=self._timeout)
        try:
            obj = resp.json()
        except Exception:
            obj = None
        return resp.status_code, obj


class GitHubCollector:
    """One profile RawDoc + up to `max_repos` recent-repo RawDocs per handle."""

    source_type = "github"

    def __init__(self, fetcher: Optional[GitHubJsonFetcher] = None, *, max_repos: int = 10):
        self._fetch = fetcher or GitHubJsonFetcher()
        self._max_repos = max_repos

    def collect(self, seed: Seed) -> list[RawDoc]:
        docs: list[RawDoc] = []
        for handle in seed.github:
            docs.extend(self._collect_handle(handle))
        return docs

    def _collect_handle(self, handle: str) -> list[RawDoc]:
        docs: list[RawDoc] = []
        status, user = self._fetch.get_json(f"{GITHUB_API}/users/{handle}")
        if status != 200 or not isinstance(user, dict):
            return docs

        profile_text = _render_profile(user)
        docs.append(
            RawDoc(
                url=f"https://github.com/{handle}",
                text=profile_text,
                source_type=self.source_type,
                title=f"GitHub profile: {user.get('name') or handle}",
                published_date=parse_http_date(user.get("updated_at")),
                meta={"handle": handle, "kind": "profile", "raw": json.dumps(user)[:4000]},
            )
        )

        status, repos = self._fetch.get_json(
            f"{GITHUB_API}/users/{handle}/repos?sort=pushed&per_page={self._max_repos}"
        )
        if status == 200 and isinstance(repos, list):
            for repo in repos[: self._max_repos]:
                if not isinstance(repo, dict) or repo.get("fork"):
                    continue
                docs.append(
                    RawDoc(
                        url=repo.get("html_url", f"https://github.com/{handle}"),
                        text=_render_repo(repo, handle),
                        source_type=self.source_type,
                        title=f"GitHub repo: {repo.get('full_name') or repo.get('name')}",
                        published_date=parse_http_date(repo.get("pushed_at")),
                        meta={
                            "handle": handle,
                            "kind": "repo",
                            "language": repo.get("language") or "",
                            "name": repo.get("name") or "",
                        },
                    )
                )
        return docs


def _render_profile(user: dict) -> str:
    parts = [
        f"Name: {user.get('name') or ''}",
        f"Login: {user.get('login') or ''}",
        f"Company: {user.get('company') or ''}",
        f"Location: {user.get('location') or ''}",
        f"Bio: {user.get('bio') or ''}",
        f"Blog: {user.get('blog') or ''}",
        f"Public repos: {user.get('public_repos', 0)}",
    ]
    return " \n".join(p for p in parts if p.rsplit(":", 1)[-1].strip())


def _render_repo(repo: dict, handle: str) -> str:
    parts = [
        f"Repository {repo.get('name') or ''} by {handle}.",
        f"Description: {repo.get('description') or ''}",
        f"Primary language: {repo.get('language') or 'unknown'}.",
        f"Last pushed: {repo.get('pushed_at') or ''}.",
    ]
    topics = repo.get("topics")
    if isinstance(topics, list) and topics:
        parts.append(f"Topics: {', '.join(topics)}.")
    return " ".join(p for p in parts if p)


_: type[Collector] = GitHubCollector
