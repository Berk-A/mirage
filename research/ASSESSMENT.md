# Research side — gap report & build plan

*As of 2026-11-21. Branch `claude/knowledge-graph-c9cc5f`, based on `origin/main` @ cf33a54.*

The research side turns **OSINT on a target → a provenance-stamped knowledge graph →
a `Dossier`** that the OODA loop attacks from. This file is the gap report the task
asked for: what the pushed code already has, what's missing, and the concrete
API/infra recommendations. The build that follows it is described at the end.

---

## 1. What main already has

`research/catalog.py` ships `ResearchCatalog` — a **serving + grounding layer**, not a
collector. It is the *sink* of the pipeline, well-made and tested:

- Implements the two seams the loop needs: `DossierProvider.get_dossier(target_id, *,
  scenario_id)` and `GroundingProvider.verify(claim_text, *, target_id)` (plus
  `get_fact` and a richer `ground()` that returns evidence).
- Takes **pre-authored `Dossier` objects** and validates every `Fact`: non-empty id +
  canonical_claim, `source_url` must start `fixture://` or `https://`, an
  `observed_date`, confidence in `[0,1]`, no duplicate fact ids.
- Grounding is **exact-match only** (whitespace/case-normalised) — it deliberately
  rejects paraphrases so nothing ungrounded ships. This protects the two score levers
  the rubric calls out: **wrong-facts (−up to 5)** and **craft detail-accuracy**.
- `core/models.py` already defines the whole target vocabulary: `Dossier` (with
  `hooks`, `senders`, `vendors`, `facts`, `archetype`, `as_of`, `gaps`), `Fact`
  (= a provenance-stamped graph edge: subject/predicate/object_value + canonical_claim
  + source_url + observed_date + event_date + confidence), `Hook`, `Sender`, `Vendor`.
- `tests/test_research.py` covers the contracts over a hand-authored fixture dossier.

**How the loop consumes a `Dossier`** (verified in `ooda_loop/` + `content/`), which
pins what the pipeline must actually produce:

- `decider._pick_sender` → `dossier.senders[0]`.
- `decider._pick_hook` → `dossier.hooks` sorted by `confidence`, skipping used topics;
  the chosen `hook.detail` **becomes the `Claim.text`** that the orchestrator then runs
  through `grounding.verify(...)`. → **hooks must be worded as grounded facts**, or they
  get dropped before sending.
- `decider._lookalike_login` / `content/pages.build_login_page` → `dossier.vendors[0]`
  (the believable landing-page surface).
- `orchestrator` → `dossier.archetype` is the bandit context; `display_name`/`role`
  feed the content studio prompts.

### Verdict

Main has the **contract and the serving/grounding tail**. It has **no OSINT, no graph,
and no way to turn public data into a `Dossier`** — today the catalog is fed by hand.
The synthetic stub the main session is building (`research/synthetic_kg.py`, not yet on
main) is also hand-authored input for experiments. This branch builds the **real
source** that produces `Dossier`s behind the same interface, so it drops in for the
stub with no loop change.

---

## 2. Gap table

| Pipeline stage | On main | This branch builds |
|---|---|---|
| **Collectors / OSINT** | none | web (personal/company pages), GitHub API, RSS/news, conference/talk pages — each → `RawDoc(url, fetched_date, text, source_type)` |
| **Extraction → triples** | none | `RawDoc` → typed `Fact` triples, each stamped source_url + observed_date + event_date + confidence |
| **Entity resolution / dedup** | none | name/alias canonicalisation, triple dedup, confidence merge |
| **Graph store** | none | `KnowledgeGraph` over NetworkX; typed nodes (Person/Org/Project/Event/Tool/Topic/Handle); facts as edges |
| **Derived views** | none | recency ranker → `hooks`; one-hop shared-Project → `senders`; Tool/Vendor nodes → `vendors` |
| **build_dossier** | none | `collect → extract → graph → derive → Dossier` |
| **Serving** | `ResearchCatalog` ✓ | reused as-is (dossier serving) |
| **Grounding** | exact-match ✓ | graph-backed `verify()` (exact canonical, conservative) |

### Sources covered vs missing

- **Covered now (open tier, no headless browser):** personal & company websites,
  GitHub (public API), conference/talk/agenda pages, RSS/Atom news & blog feeds,
  company "about/team" pages. These give role, current projects, tools/stack, talks,
  and some of the people around the target — enough for a first real `Dossier`.
- **Missing / needs infra (blocked tier):** **LinkedIn** (richest role/project/"around
  them" source — login wall + aggressive bot detection), **Instagram**, **X/Twitter**,
  **Facebook** (all login-walled). Also **URL discovery** — the scenario gives only a
  name + role, no URLs, so finding the seed pages needs web search.

---

## 3. External APIs / infrastructure — assessment & recommendation

The scenario roster is read from the challenge API at runtime; the eval roster can vary
and remain hidden until the scoring window opens. Keep collection limited to publicly
accessible sources about those in-scope simulation targets.

| Capability | Needed? | For which sources | Cheapest adequate option |
|---|---|---|---|
| **Web-search API** | **Recommended** | URL discovery for newly visible scenario targets | Brave Search API; without a key, practice uses curated URLs and the graph reports its coverage gaps. |
| **Headless browser** (Playwright/Selenium) | **Not in MVP; later, limited** | JS-rendered public pages (some talk/agenda SPAs) | **Playwright** (free). *Not* worth self-hosting against LinkedIn/IG/X — they detect headless and still require login. |
| **Captcha solver** | **No** | — | Skip. Only if you self-host LinkedIn/IG scraping, and you shouldn't — use a scraping API that solves them internally. (If ever: CapSolver/2Captcha ≈ $1–3 / 1000.) |
| **Rotating proxies / scraping API** | **Optional, for public pages only** | Public company pages that block a plain fetch | Bright Data Web Unlocker for explicitly seeded public URLs. Do not collect from access-controlled personal accounts. |
| **GitHub API** | **Yes (no paid infra)** | repos, languages, org, activity → tools/projects | Public API; unauth 60 req/hr. Add an optional `GITHUB_TOKEN` for 5000 req/hr. |

**Bottom line:**
- **MVP (this branch): zero paid infra.** Direct `requests` over the open tier
  (personal/company sites, GitHub API, RSS, talk pages) already emits a real,
  provenance-stamped `Dossier`. Collectors are written behind a `Collector` protocol so
  a Bright Data / headless backend slots in per-source with no pipeline change.
- **For broader public coverage:** configure the search API and add reputable public
  company, event, speaker and professional-profile URLs as results arrive. Keep source
  dates and confidence attached; an article date alone does not prove attendance.
- **Headless + captcha: not recommended** — higher operational cost than a managed
  scraping API and still blocked by login walls on the sites that matter.

### Sites that realistically block naive scraping
LinkedIn, Instagram, X/Twitter, Facebook (login walls + bot detection); many sites
behind Cloudflare/DataDome challenge pages. **Open to a plain fetch:** personal &
company sites, GitHub (API), most conference/agenda sites, RSS/Atom feeds, YouTube
(API), Medium/Substack blogs, Crunchbase (partial), press releases.

### Secrets / keys (placeholders added to `.env.example`, never commit real keys)
- `BRIGHTDATA_API_KEY` — optional Web Unlocker for explicitly seeded public pages.
- `GITHUB_TOKEN` — optional, raises GitHub rate limit 60→5000 req/hr.
- `BRAVE_SEARCH_API_KEY` *(or `SERP_API_KEY`)` — optional web-search for URL discovery
  (or use Bright Data SERP instead).
- Existing `REVEL8_API_KEY` / `REVEL8_API_BASE` are unchanged (target API, not research).

---

## 4. What this branch builds (MVP, iterating)

```
seeds → collectors ─► RawDoc ─► extract ─► Fact triples ─► KnowledgeGraph (NetworkX)
                                            (+ entity resolution / dedup)
                                                   │
                      derive views ◄───────────────┘
            recency→hooks · shared-project→senders · tool→vendors
                                                   │
                                        build_dossier() → Dossier
                                                   │
                              ResearchCatalog (serve) + graph-backed verify()
```

Module layout under `research/`:
- `sources.py` — `RawDoc` + robots/rate-limit helpers; `Collector` protocol.
- `collectors/` — `web.py`, `github.py`, `feeds.py` (open tier). Bright Data / headless
  are future backends behind the same protocol.
- `extract.py` — `RawDoc` → `[Fact]` (heuristic, provenance-stamped, conservative
  confidence).
- `graph.py` — `KnowledgeGraph` (NetworkX) + entity resolution + the three derived views.
- `pipeline.py` — `build_dossier(seed, collectors=...) -> Dossier`; `GraphResearchProvider`
  implementing `DossierProvider` + `GroundingProvider` over the live graph.
- `seeds.py` — public-OSINT seeds for Julius Muth / Tom Müller / Robert Seilbeck.

**Done** = this file committed + a first working pipeline that emits a `Dossier` for at
least one founder from real public data, every fact provenance-stamped, tests green
(network mocked in unit tests, a gated live collector test skipped without network).

### New dependencies
`networkx` (graph), `feedparser` (RSS/Atom), `beautifulsoup4` (HTML → text). Added to
`pyproject.toml`. Embeddings are left as a lightweight lexical-similarity hook (no model
download) per "don't over-build".
