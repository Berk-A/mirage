# Research

OSINT → a **knowledge graph with provenance** → a **dossier** the rest of the agent
attacks from.

## Mission

Given a target seed, emit a dossier that answers: what matters to this person *right
now*, who could credibly contact them, and what they log into.

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

- [ ] Dossier schema locked
- [ ] OSINT collectors (role, projects, talks, posts, GitHub, associates)
- [ ] Extraction → typed triples + entity resolution/dedup
- [ ] Derived views (recency, senders, vendors)
- [ ] Grounding lookup
