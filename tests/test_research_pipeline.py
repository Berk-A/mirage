"""Unit tests for the real research pipeline: collectors (network faked), extraction,
graph + entity resolution + derived views, and the provider seams.

No test here touches the network. The one live test lives in
`test_research_live.py` and is gated behind an env var.
"""
from __future__ import annotations

import pytest

from core.interfaces import DossierProvider, GroundingProvider
from core.models import Fact
from research.collectors.feeds import FeedCollector
from research.collectors.github import GitHubCollector
from research.collectors.web import FetchResult, WebCollector
from research.extract import extract, extract_all
from research.graph import KnowledgeGraph
from research.pipeline import GraphResearchProvider, build_dossier, build_graph
from research.sources import RateLimiter, RawDoc, RobotsCache, Seed


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeHttp:
    def __init__(self, pages: dict[str, FetchResult]):
        self._pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self._pages:
            return self._pages[url]
        return FetchResult(url=url, status=404, text="")


class FakeGitHub:
    def __init__(self, responses: dict[str, tuple[int, object]]):
        self._responses = responses

    def get_json(self, url: str):
        # longest matching prefix wins, so ".../repos?..." doesn't match the profile key
        for key in sorted(self._responses, key=len, reverse=True):
            if url.startswith(key):
                return self._responses[key]
        return 404, None


class FakeFeed:
    def __init__(self, parsed):
        self._parsed = parsed

    def parse(self, url: str):
        return self._parsed


def _seed(**kw) -> Seed:
    base = dict(target_id="julius", name="Julius Muth", role="Co-Founder & Co-CEO",
                company="revel8", aliases=("Julius", "Muth"),
                colleagues=("Tom Müller", "Robert Seilbeck"))
    base.update(kw)
    return Seed(**base)


# A permissive robots/rate-limit pair for collector tests (no network, instant).
def _open_web(http):
    robots = RobotsCache(fetcher=lambda url: "")  # empty robots → fail-open allow
    rl = RateLimiter(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda s: None)
    return WebCollector(http, robots=robots, rate_limiter=rl)


# --------------------------------------------------------------------------- #
# Collectors
# --------------------------------------------------------------------------- #
def test_web_collector_parses_title_text_and_date():
    html = """<html><head><title>revel8 raises €7M - Tech.eu</title>
      <meta property="article:published_time" content="2025-09-25T10:00:00Z"></head>
      <body><nav>menu</nav><script>var x=1;</script>
      <article><p>Julius Muth, co-founder of revel8, announced the round.</p></article>
      </body></html>"""
    url = "https://tech.eu/revel8"
    http = FakeHttp({url: FetchResult(url=url, status=200, text=html, content_type="text/html")})
    seed = _seed(urls=(url,))
    docs = _open_web(http).collect(seed)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.title == "revel8 raises €7M - Tech.eu"
    assert "Julius Muth" in doc.text
    assert "var x" not in doc.text  # scripts stripped
    assert doc.published_date == "2025-09-25"


def test_web_collector_respects_robots_disallow():
    url = "https://blocked.example/x"
    http = FakeHttp({url: FetchResult(url=url, status=200, text="<p>hi</p>")})
    robots = RobotsCache(fetcher=lambda u: "User-agent: *\nDisallow: /")
    rl = RateLimiter(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda s: None)
    wc = WebCollector(http, robots=robots, rate_limiter=rl)
    assert wc.collect(_seed(urls=(url,))) == []
    assert http.calls == []  # never even fetched


def test_github_collector_profile_and_repo():
    gh = FakeGitHub({
        "https://api.github.com/users/jmuth": (200, {
            "login": "jmuth", "name": "Julius Muth", "company": "@revel8",
            "bio": "Security founder", "updated_at": "2025-10-01T00:00:00Z",
            "public_repos": 3,
        }),
        "https://api.github.com/users/jmuth/repos": (200, [
            {"name": "phishsim", "full_name": "jmuth/phishsim", "language": "Python",
             "description": "Phishing simulation using Slack", "pushed_at": "2025-11-01T00:00:00Z",
             "html_url": "https://github.com/jmuth/phishsim", "fork": False},
        ]),
    })
    docs = GitHubCollector(gh).collect(_seed(github=("jmuth",)))
    kinds = {d.meta.get("kind") for d in docs}
    assert kinds == {"profile", "repo"}
    repo = next(d for d in docs if d.meta.get("kind") == "repo")
    assert repo.meta.get("language") == "Python"
    assert repo.published_date == "2025-11-01"


def test_feed_collector_reads_entries():
    parsed = {
        "feed": {"title": "revel8 blog"},
        "entries": [
            {"title": "We raised our seed round", "summary": "big news",
             "link": "https://revel8.example/post/1", "published": "2025-09-25T00:00:00Z"},
        ],
    }
    docs = FeedCollector(FakeFeed(parsed)).collect(_seed(feeds=("https://revel8.example/rss",)))
    assert len(docs) == 1
    assert docs[0].published_date == "2025-09-25"
    assert docs[0].source_type == "feed"


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_extract_web_role_employer_colleagues_and_hook():
    doc = RawDoc(
        url="https://tech.eu/revel8",
        text="Julius Muth, co-founder and CEO of revel8, raised funding. "
             "Co-founders Tom Müller and Robert Seilbeck joined him.",
        title="revel8 nets €7 million to fight AI-powered cyberattacks",
        published_date="2025-09-25",
        fetched_date="2026-11-21",
    )
    facts = extract(doc, _seed())
    preds = {(f.predicate, f.object_value) for f in facts}
    assert ("role_is", "Co-founder") in preds or ("role_is", "Ceo") in preds
    assert ("works_at", "revel8") in preds
    assert ("colleague_of", "Tom Müller") in preds
    assert ("colleague_of", "Robert Seilbeck") in preds
    hook_facts = [f for f in facts if f.predicate == "engaged_with"]
    assert hook_facts and hook_facts[0].object_value == "the recent funding round"
    assert hook_facts[0].event_date == "2025-09-25"
    # every fact carries provenance
    for f in facts:
        assert f.source_url.startswith("https://")
        assert f.observed_date and 0.0 <= f.confidence <= 1.0


def test_extract_web_does_not_invent_tools_from_prose():
    # "Slack" appears in unrelated prose on a page about the company; must NOT become a
    # uses_tool fact (that was a real false-positive bug: a phantom "uses Stripe").
    doc = RawDoc(
        url="https://news.example/revel8",
        text="revel8 was in the news. In other news, Slack and Stripe reported earnings. "
             "Julius Muth declined to comment.",
        title="Markets update",
        published_date="2025-09-25",
    )
    facts = extract(doc, _seed())
    assert not any(f.predicate == "uses_tool" for f in facts)


def test_extract_ignores_pages_not_about_target():
    doc = RawDoc(url="https://x.example", text="A page about unrelated things.", title="X")
    assert extract(doc, _seed()) == []


def test_extract_github_tools_and_language():
    profile = RawDoc(url="https://github.com/jmuth", text="Company: @revel8", source_type="github",
                     meta={"kind": "profile"})
    repo = RawDoc(url="https://github.com/jmuth/phishsim", text="uses Slack and AWS",
                  source_type="github", published_date="2025-11-01",
                  meta={"kind": "repo", "language": "Python", "name": "phishsim"})
    facts = extract_all([profile, repo], _seed())
    tools = {f.object_value for f in facts if f.predicate == "uses_tool"}
    langs = {f.object_value for f in facts if f.predicate == "uses_language"}
    assert "GitHub" in tools  # demonstrably uses GitHub
    assert "Slack" in tools and "AWS" in tools  # from repo description (stack signal)
    assert "Python" in langs  # language is stack, not a login surface
    assert any(f.predicate == "works_on" and f.object_value == "phishsim" for f in facts)


# --------------------------------------------------------------------------- #
# Graph: resolution + derived views + grounding
# --------------------------------------------------------------------------- #
def _fact(pred, obj, *, claim, conf=0.6, src="https://a.example", event=None, obs="2026-11-21"):
    from research.extract import _fact_id
    return Fact(id=_fact_id("julius", pred, obj, src), subject="julius", predicate=pred,
                object_value=obj, canonical_claim=claim, source_url=src,
                observed_date=obs, event_date=event, confidence=conf)


def test_graph_merges_duplicate_facts_across_sources():
    g = KnowledgeGraph()
    g.add_facts([
        _fact("works_at", "revel8", claim="Julius Muth works at revel8.", conf=0.6,
              src="https://a.example"),
        _fact("works_at", "revel8", claim="Julius Muth works at revel8.", conf=0.8,
              src="https://b.example", event="2025-09-25"),
    ])
    facts = g.facts_for("julius")
    assert len(facts) == 1  # resolved to one edge
    assert facts[0].confidence == 0.8  # strongest confidence kept
    assert facts[0].event_date == "2025-09-25"  # latest event kept


def test_recent_hooks_ranked_and_groundable():
    g = KnowledgeGraph()
    g.add_facts([
        _fact("engaged_with", "older topic", claim="old", conf=0.9, event="2024-01-01"),
        _fact("engaged_with", "the recent funding round",
              claim="On 2025-09-25, covered by tech.eu.", conf=0.5, event="2025-09-25"),
    ])
    hooks = g.recent_hooks("julius")
    assert hooks[0].topic == "the recent funding round"  # newest first
    # hook.detail is the canonical claim verbatim → grounding will match what ships
    assert g.ground(hooks[0].detail, target_id="julius") is not None


def test_credible_senders_from_colleagues():
    g = KnowledgeGraph()
    g.add_person("julius", name="Julius Muth")
    g.add_facts([
        _fact("colleague_of", "Tom Müller", claim="Julius Muth and Tom Müller both work at revel8."),
        _fact("colleague_of", "Robert Seilbeck", claim="Julius Muth and Robert Seilbeck both work at revel8."),
    ])
    names = {s.name for s in g.credible_senders("julius")}
    assert names == {"Tom Müller", "Robert Seilbeck"}


def test_vendor_surface_uses_tools_not_languages():
    g = KnowledgeGraph()
    g.add_facts([
        _fact("uses_tool", "GitHub", claim="Julius Muth has a GitHub account.", conf=0.9),
        _fact("uses_language", "Python", claim="Julius Muth works with Python.", conf=0.9),
    ])
    vendors = {v.name for v in g.vendor_surface("julius")}
    assert vendors == {"GitHub"}  # language is not a landing surface


def test_graph_ground_rejects_unsupported_claim():
    g = KnowledgeGraph()
    g.add_facts([_fact("works_at", "revel8", claim="Julius Muth works at revel8.")])
    assert g.ground("Julius Muth works at revel8.", target_id="julius") is not None
    assert g.ground("Julius Muth secretly runs a casino.", target_id="julius") is None


# --------------------------------------------------------------------------- #
# Pipeline + provider
# --------------------------------------------------------------------------- #
def _web_doc_fixture():
    html = """<html><head><title>revel8 nets €7 million to fight AI-powered cyberattacks - Tech.eu</title>
      <meta property="article:published_time" content="2025-09-25"></head>
      <body><article>Julius Muth, co-founder and CEO of revel8. Co-founders Tom Müller
      and Robert Seilbeck.</article></body></html>"""
    return html


def _provider():
    url = "https://tech.eu/revel8"
    http = FakeHttp({url: FetchResult(url=url, status=200, text=_web_doc_fixture(),
                                      content_type="text/html")})
    seed = _seed(urls=(url,))
    return GraphResearchProvider([seed], [_open_web(http)], as_of="2026-11-21"), seed


def test_build_dossier_from_fixture():
    _, seed = _provider()
    url = "https://tech.eu/revel8"
    http = FakeHttp({url: FetchResult(url=url, status=200, text=_web_doc_fixture(),
                                      content_type="text/html")})
    dossier = build_dossier(seed, [_open_web(http)], as_of="2026-11-21")
    assert dossier.target_id == "julius"
    assert dossier.role == "Co-Founder & Co-CEO"  # authoritative seed role, not shadowed
    assert dossier.archetype == "executive_founder"
    assert dossier.hooks and dossier.hooks[0].topic == "the recent funding round"
    assert {s.name for s in dossier.senders} == {"Tom Müller", "Robert Seilbeck"}
    assert dossier.facts  # provenance-stamped
    assert any("tools" in g for g in dossier.gaps)  # honest gap, no vendor source


def test_provider_satisfies_core_protocols_and_grounds():
    provider, _ = _provider()
    assert isinstance(provider, DossierProvider)
    assert isinstance(provider, GroundingProvider)
    dossier = provider.get_dossier("julius")
    assert dossier.display_name == "Julius Muth"
    # a shipped hook claim grounds; a fabrication does not
    assert provider.verify(dossier.hooks[0].detail, target_id="julius") is not None
    assert provider.verify("Julius Muth owns three yachts.", target_id="julius") is None


def test_provider_caches_and_exports_catalog():
    provider, _ = _provider()
    d1 = provider.get_dossier("julius")
    d2 = provider.get_dossier("julius")
    assert d1 is d2  # cached
    catalog = provider.as_catalog()
    assert catalog.get_dossier("julius").target_id == "julius"


def test_build_graph_survives_a_broken_collector():
    class Boom:
        source_type = "web"

        def collect(self, seed):
            raise RuntimeError("source down")

    g = build_graph(_seed(), [Boom()])
    assert g.facts_for("julius") == []  # no crash, just empty
