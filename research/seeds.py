"""Public-OSINT seeds for the revel8 practice founders.

Everything here is public and non-sensitive: names/roles from the scenario, and starting
URLs discovered from the open web (investor portfolio, public job posts). They are entry
*points* for collection, not facts — facts come out of `extract` with provenance. The
authorized sandbox: the twins are of real people who consented, and OSINT is the public
web (see docs/target-api.md).

Practice has curated public URLs. Other visible scenario rosters are converted into
seeds at runtime and can use the optional Brave Search collector for public URLs.
Private or login-walled personal data is outside this source set.
"""
from __future__ import annotations

import os

from core.models import Scenario
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

# Eval roster seeds. The scenario gives name + role only (no scenario-level company), so we
# seed the company per id — this scopes the search queries AND feeds the company-corroboration
# gate that kills namesake hallucinations. Jonas is a revel8 employee, so the revel8 public
# pages and founder colleagues apply; Patrick (VC) and Titus (founder) are external, so their
# URLs are left to live discovery rather than guessed.
EVAL_SEEDS: tuple[Seed, ...] = (
    Seed(
        target_id="jonas",
        name="Jonas Haas",
        role="Head of Customer Operations, revel8",
        company=COMPANY,
        aliases=("Jonas", "Haas"),
        urls=_COMPANY_URLS,
        colleagues=("Julius Muth", "Tom Müller", "Robert Seilbeck"),
        unlock_urls=_COMPANY_UNLOCK_URLS,
    ),
    Seed(
        target_id="patrick",
        name="Patrick Hermann",
        role="Partner & DACH VC Lead, Fortino Ventures (Munich)",
        company="Fortino Ventures",
        aliases=("Patrick", "Hermann"),
    ),
    Seed(
        target_id="titus",
        name="Titus von Pachelbel-Gehag",
        role="Founder & CEO, DialedIn (B2B sales recruiting, Berlin)",
        company="DialedIn",
        aliases=("Titus", "Pachelbel", "Gehag", "Pachelbel-Gehag", "von Pachelbel-Gehag"),
    ),
)

SEEDS_BY_ID = {s.target_id: s for s in (*PRACTICE_SEEDS, *EVAL_SEEDS)}


def _as_tuple(value) -> tuple[str, ...]:
    """Accept a single string, an iterable of strings, or None → a clean str tuple.

    Lets the factory be called with either `linkedin="in/jmuth"` or
    `linkedin=("in/jmuth", ...)` without the caller worrying about wrapping.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    out: list[str] = []
    for item in value:
        item = str(item).strip()
        if item and item not in out:
            out.append(item)
    return tuple(out)


def _derive_aliases(name: str, extra=()) -> tuple[str, ...]:
    """First name, last name, and any explicit extras — the hooks entity resolution
    uses to tie 'Julius', 'Muth' and 'Julius Muth' to the same person."""
    parts = [p for p in (name or "").split() if len(p) > 2]
    return tuple(dict.fromkeys([*parts, *_as_tuple(extra)]))


def target_seed(
    target_id: str,
    name: str,
    *,
    role: str = "",
    company: str = "",
    urls=(),
    github=(),
    domains=(),
    feeds=(),
    aliases=(),
    colleagues=(),
    unlock_urls=(),
    linkedin=(),
    facebook=(),
    instagram=(),
    websites=(),
) -> Seed:
    """Build a research `Seed` for an ARBITRARY target from whatever public entry points
    you have — a name plus any handles, profile URLs and a personal site — instead of the
    hardcoded practice roster. Every list input accepts a bare string or an iterable, and
    aliases are auto-derived from the name (explicit `aliases` are added on top).

    Example:
        seed = target_seed("ada", "Ada Lovelace", company="Analytical Engines",
                           linkedin="in/adalovelace", instagram="ada.builds",
                           websites="https://ada.example")
        provider = default_provider(seeds=(seed,))
        dossier = provider.get_dossier("ada")
    """
    return Seed(
        target_id=target_id,
        name=name,
        role=role,
        company=company,
        urls=_as_tuple(urls),
        github=_as_tuple(github),
        domains=_as_tuple(domains),
        feeds=_as_tuple(feeds),
        aliases=_derive_aliases(name, aliases),
        colleagues=_as_tuple(colleagues),
        unlock_urls=_as_tuple(unlock_urls),
        linkedin=_as_tuple(linkedin),
        facebook=_as_tuple(facebook),
        instagram=_as_tuple(instagram),
        websites=_as_tuple(websites),
    )


def seeds_from_scenario(scenario: Scenario) -> tuple[Seed, ...]:
    """Build target seeds from the roster returned by the challenge API.

    The scenario is the authority for which people are in scope. Only that roster is
    turned into research seeds, including for a newly opened eval scenario.
    """
    out: list[Seed] = []
    for target in scenario.targets:
        if not target.id:
            continue
        known = SEEDS_BY_ID.get(target.id)
        aliases = tuple(dict.fromkeys(
            [part for part in target.name.split() if len(part) > 2]
            + (list(known.aliases) if known else [])
        ))
        colleagues = tuple(
            other.name for other in scenario.targets
            if other.id != target.id and other.name
        )
        out.append(Seed(
            target_id=target.id,
            name=target.name or target.id,
            role=target.role or (known.role if known else ""),
            company=scenario.company or (known.company if known else ""),
            urls=known.urls if known else (),
            github=known.github if known else (),
            domains=known.domains if known else (),
            feeds=known.feeds if known else (),
            aliases=aliases,
            colleagues=colleagues or (known.colleagues if known else ()),
            unlock_urls=known.unlock_urls if known else (),
            linkedin=known.linkedin if known else (),
            facebook=known.facebook if known else (),
            instagram=known.instagram if known else (),
            websites=known.websites if known else (),
        ))
    return tuple(out)


def default_provider(as_of: str | None = None, *, use_brightdata: bool | None = None,
                     use_llm: bool | None = None, seeds: tuple[Seed, ...] | None = None):
    """A `GraphResearchProvider` over the practice (or supplied scenario) seeds.

    Open-tier collectors always run. The Bright Data Web Unlocker collector is added when
    a backend is usable (`bdata login` done, or BRIGHTDATA_API_KEY set) — pass
    `use_brightdata=False` to force the open-tier-only pipeline, `True` to require it.
    Imported lazily so `research.seeds` stays cheap to import.
    """
    from research.collectors import (
        BraveSearchCollector,
        BrightDataCollector,
        FacebookCollector,
        FeedCollector,
        GitHubCollector,
        HoleheCollector,
        InstagramCollector,
        LinkedInCollector,
        MaigretCollector,
        SerpApiDiscoveryCollector,
        WebCollector,
        WebsiteCollector,
        brightdata_available,
        holehe_available,
        maigret_available,
        serpapi_available,
    )
    from research.pipeline import GraphResearchProvider

    import os
    collectors: list = []
    # Discovery runs FIRST: it finds the URLs the rest of the funnel can't. Gated on a
    # SerpAPI key so offline/no-key runs fall back cleanly to the open-tier collectors.
    if serpapi_available():
        collectors.append(SerpApiDiscoveryCollector())
    collectors += [WebCollector(), GitHubCollector(), FeedCollector()]
    if os.environ.get("BRAVE_SEARCH_API_KEY"):
        collectors.append(BraveSearchCollector())
    if use_brightdata is None:
        use_brightdata = brightdata_available()
    if use_brightdata:
        # All four Bright Data-backed collectors share the same backend gate as the Web
        # Unlocker, so offline / no-key runs add none of them and stay identical.
        collectors.append(BrightDataCollector())
        collectors.append(WebsiteCollector())
        collectors.append(LinkedInCollector())
        collectors.append(FacebookCollector())
        collectors.append(InstagramCollector())
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
    return GraphResearchProvider(
        PRACTICE_SEEDS if seeds is None else seeds, collectors, as_of=as_of, llm=llm,
        extra_facts_for=confirmed_facts)
