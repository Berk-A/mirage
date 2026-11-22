"""Unit tests for the generalized social-footprint collectors (LinkedIn / Facebook /
Instagram / personal websites) and the arbitrary-target Seed path.

No test here touches the network: every collector's transport seam is injected. These
cover collection, URL normalisation, graceful degradation, the on-disk cache, structured
extraction (identity-guarded), the plain→Bright Data website fallback, and that an
arbitrary target researched via `target_seed` flows end-to-end into a grounded dossier.
"""
from __future__ import annotations

from research.collectors.social import (
    FacebookCollector,
    InstagramCollector,
    LinkedInCollector,
)
from research.collectors.web import FetchResult
from research.collectors.website import WebsiteCollector
from research.extract import extract
from research.pipeline import GraphResearchProvider, build_graph
from research.seeds import default_provider, target_seed
from research.sources import RateLimiter, RawDoc, RobotsCache, Seed


def _no_wait_rl() -> RateLimiter:
    return RateLimiter(min_interval=0.0, clock=lambda: 0.0, sleeper=lambda s: None)


def _seed(**kw) -> Seed:
    base = dict(target_id="julius", name="Julius Muth", role="Co-Founder & Co-CEO",
                company="revel8", aliases=("Julius", "Muth"),
                colleagues=("Tom Müller", "Robert Seilbeck"))
    base.update(kw)
    return Seed(**base)


_LI_RECORD = {
    "name": "Julius Muth",
    "title": "Co-Founder & Co-CEO at revel8",
    "company": "revel8",
    "location": "Berlin, Germany",
    "headline": "Fighting AI-powered cyberattacks",
    "url": "https://www.linkedin.com/in/jmuth",
    "posts": [
        {"text": "Thrilled to announce our €7M seed round to fight AI phishing!",
         "date": "2025-09-25"},
        {"text": "Great chatting at the WHU founder panel.", "date": "2025-10-10"},
    ],
}


# --------------------------------------------------------------------------- #
# Social collectors
# --------------------------------------------------------------------------- #
def test_linkedin_collector_renders_rawdoc_with_structured_meta():
    calls: list[tuple[str, str]] = []

    def scrape(platform, url):
        calls.append((platform, url))
        return _LI_RECORD

    docs = LinkedInCollector(scrape, rate_limiter=_no_wait_rl(), cache_dir=None).collect(
        _seed(linkedin=("jmuth",))
    )
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source_type == "linkedin"
    assert calls == [("linkedin", "https://www.linkedin.com/in/jmuth")]
    assert doc.meta["platform"] == "linkedin"
    assert doc.meta["fields"]["title"] == "Co-Founder & Co-CEO at revel8"
    assert len(doc.meta["posts"]) == 2
    assert "Julius Muth" in doc.text
    assert doc.published_date == "2025-10-10"  # latest dated post


def test_linkedin_url_normalisation_variants():
    coll = LinkedInCollector(lambda p, u: None, cache_dir=None)
    assert coll.profile_url("jmuth") == "https://www.linkedin.com/in/jmuth"
    assert coll.profile_url("in/jmuth") == "https://www.linkedin.com/in/jmuth"
    assert (coll.profile_url("https://linkedin.com/in/x/")
            == "https://linkedin.com/in/x/")
    assert (coll.profile_url("linkedin.com/in/x")
            == "https://linkedin.com/in/x")


def test_instagram_and_facebook_normalise_bare_handles():
    ig = InstagramCollector(lambda p, u: None, cache_dir=None)
    fb = FacebookCollector(lambda p, u: None, cache_dir=None)
    assert ig.profile_url("ada.builds") == "https://www.instagram.com/ada.builds"
    assert fb.profile_url("ada.builds") == "https://www.facebook.com/ada.builds"


def test_social_collector_degrades_to_empty_on_none_and_exception():
    assert LinkedInCollector(lambda p, u: None, rate_limiter=_no_wait_rl(),
                             cache_dir=None).collect(_seed(linkedin=("x",))) == []

    def boom(platform, url):
        raise RuntimeError("backend down")

    coll = LinkedInCollector(boom, rate_limiter=_no_wait_rl(), cache_dir=None)
    assert coll.collect(_seed(linkedin=("x",))) == []
    assert coll.last_warnings  # recorded a warning, did not crash


def test_social_collector_respects_max_profiles_cap():
    calls: list[str] = []

    def scrape(platform, url):
        calls.append(url)
        return {"name": "Julius Muth", "title": "CEO"}

    LinkedInCollector(scrape, rate_limiter=_no_wait_rl(), cache_dir=None,
                      max_profiles=2).collect(_seed(linkedin=("a", "b", "c", "d")))
    assert len(calls) == 2


def test_social_collector_uses_disk_cache(tmp_path):
    calls: list[str] = []

    def scrape(platform, url):
        calls.append(url)
        return _LI_RECORD

    seed = _seed(linkedin=("jmuth",))
    coll = LinkedInCollector(scrape, rate_limiter=_no_wait_rl(), cache_dir=str(tmp_path))
    first = coll.collect(seed)
    second = coll.collect(seed)  # should hit the cache, not re-scrape
    assert len(first) == 1 and len(second) == 1
    assert calls == ["https://www.linkedin.com/in/jmuth"]  # scraped exactly once


# --------------------------------------------------------------------------- #
# Structured extraction (identity-guarded)
# --------------------------------------------------------------------------- #
def _social_doc(fields, posts=(), platform="linkedin") -> RawDoc:
    return RawDoc(
        url="https://www.linkedin.com/in/jmuth", text="rendered", source_type=platform,
        meta={"platform": platform, "kind": "profile",
              "fields": fields, "posts": list(posts)},
    )


def test_extract_social_emits_role_company_and_dated_hook():
    doc = _social_doc(
        {"name": "Julius Muth", "title": "Co-Founder & Co-CEO at revel8",
         "company": "revel8"},
        posts=[{"text": "We raised our €7M seed round!", "date": "2025-09-25"}],
    )
    facts = extract(doc, _seed())
    preds = {f.predicate for f in facts}
    assert "role_is" in preds and "works_at" in preds and "engaged_with" in preds
    role = next(f for f in facts if f.predicate == "role_is")
    assert role.object_value == "Co-Founder & Co-CEO"  # employer suffix stripped
    assert role.confidence >= 0.8
    hook = next(f for f in facts if f.predicate == "engaged_with")
    assert hook.event_date == "2025-09-25"
    assert "2025-09-25" in hook.canonical_claim


def test_extract_social_emits_nothing_when_name_mismatches_target():
    doc = _social_doc({"name": "Someone Else", "title": "CEO", "company": "AcmeCorp"})
    assert extract(doc, _seed()) == []


def test_extract_social_skips_undated_posts_for_hooks():
    doc = _social_doc(
        {"name": "Julius Muth", "company": "revel8"},
        posts=[{"text": "no date here"}],
    )
    facts = extract(doc, _seed())
    assert {f.predicate for f in facts} == {"works_at"}  # no hook without a date


# --------------------------------------------------------------------------- #
# Website collector (plain → Bright Data fallback)
# --------------------------------------------------------------------------- #
class _FakeHttp:
    def __init__(self, pages):
        self._pages = pages

    def get(self, url):
        return self._pages.get(url, FetchResult(url=url, status=404, text=""))


def _open_robots():
    return RobotsCache(fetcher=lambda url: "")  # fail-open allow


def test_website_collector_plain_fetch_path():
    url = "https://ada.example/"
    html = "<html><title>Ada</title><body><p>About Ada Lovelace.</p></body></html>"
    coll = WebsiteCollector(
        _FakeHttp({url: FetchResult(url=url, status=200, text=html, content_type="text/html")}),
        scrape=lambda u: (0, ""),  # fallback must not be needed
        robots=_open_robots(), rate_limiter=_no_wait_rl(),
    )
    docs = coll.collect(Seed(target_id="ada", name="Ada Lovelace", websites=(url,)))
    assert len(docs) == 1
    assert docs[0].meta["via"] == "plain_fetch"
    assert "Ada Lovelace" in docs[0].text


def test_website_collector_falls_back_to_brightdata_when_plain_blocked():
    url = "https://blocked.example/"
    html = "<html><title>Blocked</title><body><p>JS-rendered content here.</p></body></html>"
    coll = WebsiteCollector(
        _FakeHttp({url: FetchResult(url=url, status=403, text="")}),  # plain blocked
        scrape=lambda u: (200, html),  # unlocker succeeds
        robots=_open_robots(), rate_limiter=_no_wait_rl(),
    )
    docs = coll.collect(Seed(target_id="x", name="X", websites=(url,)))
    assert len(docs) == 1
    assert docs[0].meta["via"] == "brightdata_scrape"
    assert "JS-rendered" in docs[0].text


def test_website_collector_total_failure_is_empty():
    url = "https://dead.example/"
    coll = WebsiteCollector(
        _FakeHttp({url: FetchResult(url=url, status=500, text="")}),
        scrape=lambda u: (0, ""),
        robots=_open_robots(), rate_limiter=_no_wait_rl(),
    )
    assert coll.collect(Seed(target_id="x", name="X", websites=(url,))) == []


# --------------------------------------------------------------------------- #
# Generalized arbitrary-target Seed path
# --------------------------------------------------------------------------- #
def test_target_seed_factory_normalises_inputs():
    seed = target_seed(
        "ada", "Ada Lovelace", company="Analytical Engines",
        linkedin="in/adalovelace", instagram="ada.builds",
        websites="https://ada.example", colleagues=("Charles Babbage",),
    )
    assert seed.linkedin == ("in/adalovelace",)      # bare string → tuple
    assert seed.instagram == ("ada.builds",)
    assert seed.websites == ("https://ada.example",)
    assert "Ada" in seed.aliases and "Lovelace" in seed.aliases  # auto-derived


def test_arbitrary_target_flows_end_to_end_into_a_grounded_dossier():
    seed = target_seed("ada", "Ada Lovelace", linkedin="adalovelace")
    record = {
        "name": "Ada Lovelace", "title": "Founder at Analytical Engines",
        "company": "Analytical Engines",
        "posts": [{"text": "Launching our new compute engine today!",
                   "date": "2025-11-01"}],
    }
    collector = LinkedInCollector(lambda p, u: record, rate_limiter=_no_wait_rl(),
                                  cache_dir=None)
    provider = GraphResearchProvider((seed,), (collector,), as_of="2025-11-20")
    dossier = provider.get_dossier("ada")

    assert dossier.role == "Founder"              # LinkedIn title became the role
    assert dossier.archetype == "executive_founder"
    assert dossier.hooks                           # dated post → a recency hook
    hook_claim = dossier.hooks[0].detail
    assert provider.verify(hook_claim, target_id="ada")  # the shipped hook grounds


def test_default_provider_gating_adds_social_only_with_brightdata():
    with_bd = default_provider(use_brightdata=True)
    without_bd = default_provider(use_brightdata=False)
    types_with = {type(c).__name__ for c in with_bd._collectors}
    types_without = {type(c).__name__ for c in without_bd._collectors}
    for name in ("LinkedInCollector", "FacebookCollector", "InstagramCollector",
                 "WebsiteCollector"):
        assert name in types_with
        assert name not in types_without
