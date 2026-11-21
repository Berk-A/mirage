# Research

OSINT → a **knowledge graph with provenance** → a **dossier** the rest of the agent
attacks from.

## Mission

Given one target from a challenge API scenario, emit a provenance-backed dossier from
public sources. Report source gaps; a coverage article is not evidence of attendance.

## What it produces

- **Knowledge graph** — typed triples with provenance. Nodes: Person, Org, Project,
  Event, Artifact, Topic, Handle/Channel, Tool/Vendor. Edges (`works_at`, `spoke_at`,
  `uses_tool`, `reports_to`, ...) each stamped with **date + source URL + confidence**.
- **Derived views:**
  - *Recency ranker* over timestamped edges → current hooks.
  - *One-hop over shared Project* → credible senders.
  - *Tool/Vendor nodes* → believable landing-page surface (something they actually use).
- **Grounding lookup** — `verify(claim) -> node_id | None`, called before anything ships.
  Protects two score levers: wrong-facts (−5) and craft detail-accuracy.

## Why it matters to the score

A generic attack gets ignored; so does one that gets facts wrong (API docs are explicit).
Targeting is 10 pts and wrong facts cost up to 5. Grounding is load-bearing, not polish.

## Interface (draft — lock at hour 0)

```
build_dossier(seed) -> Dossier           # the deliverable
Dossier.hooks            : [Hook]         # recency-ranked, each with source+date
Dossier.senders          : [Sender]       # credible, from shared projects
Dossier.landing_surface  : [Vendor]       # tools they use
grounding.verify(claim)  -> node_id | None
```

## Stack

NetworkX + a triple store + embeddings for fuzzy retrieval is enough for a handful of
targets and stays replayable for the jury. Reach for a graph DB only if path queries
get deep.

## Status

- [x] Dossier schema locked (`core.models.Dossier`/`Fact`/`Hook`/`Sender`/`Vendor`)
- [x] OSINT collectors — open tier: web, GitHub, RSS/feeds (`research/collectors/`).
      Blocked tier: Bright Data Web Unlocker collector (`collectors/brightdata.py`) —
      reaches JS/bot-blocked pages (seedtable, revel8.ai) via the CLI's stored login or
      the REST API; added to the pipeline automatically when a backend is available.
- [x] Extraction → typed triples + entity resolution/dedup (`extract.py`, `graph.py`)
- [x] Derived views — recency→hooks, shared-project→senders, tools→vendors (`graph.py`)
- [x] Grounding lookup — `GraphResearchProvider.verify` / `KnowledgeGraph.ground`

See **`ASSESSMENT.md`** for the gap report + the API/infra recommendations
(headless browser / captcha / proxies / search — needed or not, and the cheapest
adequate option for each).

## How it fits together

```
research/
  sources.py      RawDoc + Collector protocol + robots/rate-limit
  collectors/     web.py · github.py · feeds.py (open tier) · brightdata.py (blocked tier)
  extract.py      RawDoc -> provenance-stamped Fact triples (conservative)
  graph.py        KnowledgeGraph (NetworkX) + entity resolution + derived views + ground()
  pipeline.py     build_dossier() + GraphResearchProvider (DossierProvider+GroundingProvider)
  seeds.py        scenario-roster seeds plus curated practice URLs
  catalog.py      ResearchCatalog — offline serving/validation snapshot (existing)
```

`GraphResearchProvider` is a drop-in for the OODA loop's `DossierProvider` /
`GroundingProvider`, replacing the synthetic KG stub with the same interface. Live
collection is gated behind a network test (`RUN_LIVE_RESEARCH=1`); unit tests mock the
network.
