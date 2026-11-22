"""The pipeline: `collect → extract → graph → derive → Dossier`, and the live provider
that serves it behind the two core seams.

`GraphResearchProvider` implements `core.interfaces.DossierProvider` and
`GroundingProvider` over the real graph, so it drops straight into the OODA loop in
place of the hand-authored `ResearchCatalog` / the synthetic KG stub — same methods,
same `Dossier`/`Fact` types, no loop change.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.models import Dossier, Fact
from research.catalog import ResearchCatalog
from research.extract import extract_all
from research.graph import KnowledgeGraph
from research.sources import Collector, Seed, today_iso


def build_graph(seed: Seed, collectors: Sequence[Collector], *, llm=None) -> KnowledgeGraph:
    """Run every collector, extract facts, and load them into a resolved graph. When an `llm`
    is given, also run LLM extraction over each fetched document for richer, specific facts
    (gated + cached; absent -> only the regex extractor runs, unchanged)."""
    graph = KnowledgeGraph()
    graph.add_person(seed.target_id, name=seed.name, role=seed.role)
    facts: list[Fact] = []
    for collector in collectors:
        try:
            docs = collector.collect(seed)
        except Exception:
            docs = []  # a dead source must never sink the whole run
        facts.extend(extract_all(docs, seed))
        if llm is not None:
            from research.llm_extract import extract_facts_cached
            for d in docs:
                try:
                    facts.extend(extract_facts_cached(d, seed, llm))
                except Exception:
                    pass  # a bad doc/model call must never sink the run
    graph.add_facts(facts)
    return graph


def build_dossier(
    seed: Seed,
    collectors: Sequence[Collector],
    *,
    as_of: Optional[str] = None,
    graph: Optional[KnowledgeGraph] = None,
    llm=None,
) -> Dossier:
    """Produce the research deliverable for one target from public data."""
    as_of = as_of or today_iso()
    graph = graph if graph is not None else build_graph(seed, collectors, llm=llm)

    hooks = graph.recent_hooks(seed.target_id)
    senders = graph.credible_senders(seed.target_id)
    vendors = graph.vendor_surface(seed.target_id)
    # The scenario role is authoritative ground truth; a page-extracted role only adds
    # provenance (kept as a role_is fact), so it must not shadow the seed role.
    role = seed.role or graph.role_of(seed.target_id)
    facts = tuple(graph.facts_for(seed.target_id))

    return Dossier(
        target_id=seed.target_id,
        display_name=seed.name,
        role=role,
        archetype=_archetype(role),
        hooks=tuple(hooks),
        senders=tuple(senders),
        vendors=tuple(vendors),
        as_of=as_of,
        facts=facts,
        gaps=_gaps(hooks, senders, vendors, facts),
    )


def _archetype(role: str) -> str:
    """The bandit conditions on this, so a learned policy transfers to unseen targets
    rather than overfitting to one person. Coarse on purpose."""
    r = role.lower()
    if any(k in r for k in ("cto", "chief technology", "engineer", "developer")):
        return "technical_leader"
    if any(k in r for k in ("ceo", "chief executive", "founder", "managing director")):
        return "executive_founder"
    if any(k in r for k in ("cpo", "product", "chief product")):
        return "product_leader"
    if any(k in r for k in ("cfo", "finance", "controller", "accounting")):
        return "finance"
    if any(k in r for k in ("sales", "go-to-market", "marketing", "growth")):
        return "commercial"
    return "generic"


def _gaps(hooks, senders, vendors, facts) -> tuple[str, ...]:
    gaps: list[str] = []
    if not hooks:
        gaps.append("no current hooks — add timestamped sources (feeds/talks/LinkedIn)")
    if not senders:
        gaps.append("no credible senders — need colleagues/shared projects (LinkedIn)")
    if not vendors:
        gaps.append("no known tools — add stack sources (GitHub/job posts/company blog)")
    if not facts:
        gaps.append("no facts collected — check seeds/collectors reachability")
    return tuple(gaps)


class GraphResearchProvider:
    """DossierProvider + GroundingProvider over live graphs, one per target.

    Built from seeds + a collector set. Dossiers are built lazily on first request and
    cached; `verify()` grounds against the target's graph (exact claim, then a
    conservative high-overlap fallback)."""

    def __init__(
        self,
        seeds: Iterable[Seed],
        collectors: Sequence[Collector],
        *,
        as_of: Optional[str] = None,
        llm=None,
    ):
        self._seeds = {s.target_id: s for s in seeds}
        self._collectors = list(collectors)
        self._as_of = as_of
        self._llm = llm      # optional model for LLM-based fact extraction (gated + cached)
        self._graphs: dict[str, KnowledgeGraph] = {}
        self._dossiers: dict[str, Dossier] = {}

    # -- DossierProvider ------------------------------------------------- #
    def get_dossier(self, target_id: str, *, scenario_id: str = "practice") -> Dossier:
        del scenario_id  # accepted to match the protocol; seeds are scenario-agnostic
        if target_id not in self._dossiers:
            self._build(target_id)
        return self._dossiers[target_id]

    # -- GroundingProvider ----------------------------------------------- #
    def verify(self, claim_text: str, *, target_id: str) -> Optional[str]:
        if target_id not in self._graphs:
            self._build(target_id)
        return self._graphs[target_id].ground(claim_text, target_id=target_id)

    # -- extras ---------------------------------------------------------- #
    def get_fact(self, target_id: str, fact_id: str) -> Optional[Fact]:
        if target_id not in self._graphs:
            self._build(target_id)
        return self._graphs[target_id].get_fact(fact_id)

    def graph_for(self, target_id: str) -> KnowledgeGraph:
        if target_id not in self._graphs:
            self._build(target_id)
        return self._graphs[target_id]

    def as_catalog(self) -> ResearchCatalog:
        """Materialise all seeds into an offline `ResearchCatalog` — a replayable,
        validated snapshot for experiments or for the jury (no network at replay)."""
        for tid in self._seeds:
            if tid not in self._dossiers:
                self._build(tid)
        return ResearchCatalog(self._dossiers.values())

    def _build(self, target_id: str) -> None:
        if target_id not in self._seeds:
            raise KeyError(f"no seed for target_id {target_id!r}")
        seed = self._seeds[target_id]
        graph = build_graph(seed, self._collectors, llm=self._llm)
        self._graphs[target_id] = graph
        self._dossiers[target_id] = build_dossier(
            seed, self._collectors, as_of=self._as_of, graph=graph, llm=self._llm
        )
