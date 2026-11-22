"""Public-OSINT seeds for the revel8 practice founders.

Everything here is public and non-sensitive: names/roles from the scenario, and starting
URLs discovered from the open web (investor portfolio, public job posts). They are entry
*points* for collection, not facts — facts come out of `extract` with provenance. The
authorized sandbox: the twins are of real people who consented, and OSINT is the public
web (see docs/target-api.md).

URL discovery is manual here; the recommended upgrade is a search API + a LinkedIn
scraping backend (see research/ASSESSMENT.md) to find current-project and
"people-around-them" pages automatically.
"""
from __future__ import annotations

from research.sources import Seed

COMPANY = "revel8"

# Open-tier public pages about revel8 — static, dated, fetchable without a headless
# browser or login. (revel8's own site and job board are JS-rendered / bot-blocked, so
# the richest first-party pages need the scraping-API backend in ASSESSMENT.md; these
# press/community pages are the reachable open tier and carry roles + a dated funding
# event that seeds the recency ranker.)
_COMPANY_URLS: tuple[str, ...] = (
    "https://tech.eu/2025/09/25/revel8-nets-eur7-million-to-fight-ai-powered-cyberattacks/",
    "https://www.whu.edu/de/news-insights/whu-magazin/artikel/why-stories-matter-revel8-cybersecurity-community/",
)

# Blocked-tier pages (JS-rendered / bot-blocked) reachable only via the Bright Data Web
# Unlocker. The seedtable company page carries a structured "Key people" section (roles
# of the founders) that a plain fetch can't see; revel8.ai is the JS-rendered homepage.
_COMPANY_UNLOCK_URLS: tuple[str, ...] = (
    "https://seedtable.com/jobs/180057",
    "https://www.revel8.ai/",
)

PRACTICE_SEEDS: tuple[Seed, ...] = (
    Seed(
        target_id="julius",
        name="Julius Muth",
        role="Co-Founder & Co-CEO, revel8 (business and go-to-market)",
        company=COMPANY,
        aliases=("Julius", "Muth"),
        urls=_COMPANY_URLS,
        colleagues=("Tom Müller", "Robert Seilbeck"),
        unlock_urls=_COMPANY_UNLOCK_URLS,
        # github/feeds: none confirmed yet — URL discovery is the recommended next step.
    ),
    Seed(
        target_id="tom",
        name="Tom Müller",
        role="Co-Founder & Co-CEO, revel8 (product)",
        company=COMPANY,
        aliases=("Tom", "Müller", "Mueller"),
        urls=_COMPANY_URLS,
        colleagues=("Julius Muth", "Robert Seilbeck"),
        unlock_urls=_COMPANY_UNLOCK_URLS,
    ),
    Seed(
        target_id="robert",
        name="Robert Seilbeck",
        role="Co-Founder & CTO, revel8",
        company=COMPANY,
        aliases=("Robert", "Seilbeck"),
        urls=_COMPANY_URLS,
        colleagues=("Julius Muth", "Tom Müller"),
        unlock_urls=_COMPANY_UNLOCK_URLS,
    ),
)

SEEDS_BY_ID = {s.target_id: s for s in PRACTICE_SEEDS}


def default_provider(as_of: str | None = None, *, use_brightdata: bool | None = None,
                     use_llm: bool | None = None):
    """A `GraphResearchProvider` over the practice seeds.

    Open-tier collectors always run. The Bright Data Web Unlocker collector is added when
    a backend is usable (`bdata login` done, or BRIGHTDATA_API_KEY set) — pass
    `use_brightdata=False` to force the open-tier-only pipeline, `True` to require it.
    Imported lazily so `research.seeds` stays cheap to import.
    """
    from research.collectors import (
        BrightDataCollector,
        FeedCollector,
        GitHubCollector,
        HoleheCollector,
        MaigretCollector,
        SerpApiDiscoveryCollector,
        WebCollector,
        brightdata_available,
        holehe_available,
        maigret_available,
        serpapi_available,
    )
    from research.pipeline import GraphResearchProvider

    collectors: list = []
    # Discovery runs FIRST: it finds the URLs the rest of the funnel can't. Gated on a
    # SerpAPI key so offline/no-key runs fall back cleanly to the open-tier collectors.
    if serpapi_available():
        collectors.append(SerpApiDiscoveryCollector())
    collectors += [WebCollector(), GitHubCollector(), FeedCollector()]
    if use_brightdata is None:
        use_brightdata = brightdata_available()
    if use_brightdata:
        collectors.append(BrightDataCollector())
    # Account-footprint collectors run LAST and only when their CLI is installed, so the
    # offline/open-tier pipeline is unchanged when the tools (or network) are absent.
    # They cache to runs/osint_cache so a re-run never re-probes.
    if holehe_available():
        collectors.append(HoleheCollector())
    if maigret_available():
        collectors.append(MaigretCollector())

    # LLM-based extraction over the crawled docs — the real research depth. Gated on a served
    # model (MIRAGE_LLM_BASE); absent -> only the regex extractor runs, so offline tests are
    # unchanged. Cached per source URL, so a rebuild doesn't re-spend model calls.
    import os
    llm = None
    if use_llm is None:
        use_llm = bool(os.environ.get("MIRAGE_LLM_BASE"))
    if use_llm:
        try:
            from content.llm import OpenAICompatLLM
            llm = OpenAICompatLLM()
        except Exception:
            llm = None

    # Curated, verified operational ties (STACKIT / ISO 27001 / Allianz) — impersonation
    # surfaces the open crawl can't reliably reach, grounded in confirmed recon.
    from research.confirmed import confirmed_facts
    return GraphResearchProvider(PRACTICE_SEEDS, collectors, as_of=as_of, llm=llm,
                                 extra_facts_for=confirmed_facts)
