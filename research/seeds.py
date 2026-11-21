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

PRACTICE_SEEDS: tuple[Seed, ...] = (
    Seed(
        target_id="julius",
        name="Julius Muth",
        role="Co-Founder & Co-CEO, revel8 (business and go-to-market)",
        company=COMPANY,
        aliases=("Julius", "Muth"),
        urls=_COMPANY_URLS,
        colleagues=("Tom Müller", "Robert Seilbeck"),
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
    ),
    Seed(
        target_id="robert",
        name="Robert Seilbeck",
        role="Co-Founder & CTO, revel8",
        company=COMPANY,
        aliases=("Robert", "Seilbeck"),
        urls=_COMPANY_URLS,
        colleagues=("Julius Muth", "Tom Müller"),
    ),
)

SEEDS_BY_ID = {s.target_id: s for s in PRACTICE_SEEDS}


def default_provider(as_of: str | None = None):
    """A `GraphResearchProvider` over the practice seeds with the open-tier collectors.
    Imported lazily so `research.seeds` stays cheap to import."""
    from research.collectors import FeedCollector, GitHubCollector, WebCollector
    from research.pipeline import GraphResearchProvider

    collectors = [WebCollector(), GitHubCollector(), FeedCollector()]
    return GraphResearchProvider(PRACTICE_SEEDS, collectors, as_of=as_of)
