"""A small, typed, provenance-stamped knowledge graph — with FABRICATED data.

                        ⚠️  SYNTHETIC TEST DATA  ⚠️
Everything in this module is MADE UP. It is plausible, clearly-synthetic fixture
data built solely to exercise MIRAGE's research → OODA seam inside the revel8
"Agentic Social Engineer" sandbox (three consenting founders, closed environment).
None of the hooks, senders, vendors, dates, URLs or confidences describe real
events, real people's activity, or real infrastructure. The sender domains are
deliberately NOT revel8's own domain and are not claimed to belong to anyone; they
are registerable-looking lookalikes used only so a dossier has a shape to attack
in the sandbox. Do not treat any value here as a real-world fact.

What this gives the rest of the agent
-------------------------------------
A `KnowledgeGraph` of typed `Node`s (Person, Org, Project, Event, Vendor, Topic)
and `Edge`s, where **every edge is stamped with a source URL, a date and a
confidence** — the provenance the research README promises. From that graph two
things are derived and exposed behind the core Protocols:

  * `get_dossier(...)`  (satisfies `core.interfaces.DossierProvider`)
      Walks the graph from a founder's Person node and builds a `Dossier`:
      recency-ranked `Hook`s (from engaged_with edges onto Event/Topic nodes),
      credible `Sender`s (one hop over a shared Project), and the `Vendor`/tool
      landing surfaces (uses_tool edges). Unknown target ids get a generic but
      usable dossier rather than an error.

  * `verify(claim, *, target_id)`  (satisfies `core.interfaces.GroundingProvider`)
      Grounds a claim against the facts reachable from that target. Rule: the
      claim is lowercased; a fact grounds it when the fact's key phrase is a
      substring of the claim, or the claim is a substring of the fact's text.
      Facts are checked in recency order (hooks first), and the first match
      returns that fact's node id; no match returns None.

`GRAPH` (the `KnowledgeGraph`) and `dossiers()` (all three founder dossiers) are
exposed for inspection and replay.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from core.models import Dossier, Hook, Sender, Vendor


# --------------------------------------------------------------------------- #
# Graph primitives
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Node:
    """A typed graph node. `kind` is one of: Person, Org, Project, Event,
    Vendor, Topic. `attrs` carries kind-specific fields used to rebuild the
    dossier dataclasses (e.g. a Sender's address, a Vendor's login_url)."""

    id: str
    kind: str
    label: str
    attrs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    """A directed, provenance-stamped relation between two nodes.

    Every edge carries `source_url`, `date` (ISO yyyy-mm-dd) and `confidence`
    in [0, 1]: the three things the research spec requires on each triple so a
    derived hook/sender/vendor can be traced and recency-ranked."""

    src: str
    dst: str
    rel: str
    source_url: str
    date: str
    confidence: float


@dataclass(frozen=True)
class KnowledgeGraph:
    nodes: Mapping[str, Node]
    edges: tuple[Edge, ...]

    def out_edges(self, src: str, rel: Optional[str] = None) -> list[Edge]:
        return [
            e for e in self.edges
            if e.src == src and (rel is None or e.rel == rel)
        ]


# --------------------------------------------------------------------------- #
# Relation vocabulary
# --------------------------------------------------------------------------- #
REL_WORKS_AT = "works_at"
REL_ENGAGED_WITH = "engaged_with"   # Person -> Event/Topic  => a Hook
REL_WORKS_ON = "works_on"           # Person -> Project
REL_ASSOCIATED_WITH = "associated_with"  # Sender -> Project (shared project)
REL_CREDIBLE_SENDER = "credible_sender"  # Person -> Person (one hop via project)
REL_USES_TOOL = "uses_tool"         # Person -> Vendor      => a landing surface


# --------------------------------------------------------------------------- #
# Fabricated founder specs. Plausible, clearly-synthetic. Dates sit around the
# sandbox "now" so the recency ranker has something to order. Hook nodes are
# Event (a dated happening) or Topic (an ongoing thread). Every derived fact's
# provenance lives on the edge, not the node.
# --------------------------------------------------------------------------- #
_ORG = Node(
    id="n_org_revel8",
    kind="Org",
    label="revel8",
    attrs={"city": "Munich", "note": "synthetic sandbox company node"},
)

# Each spec: the Person, their hooks (-> Event/Topic nodes + stamped edges),
# senders (credible external identities + a shared Project), and vendors.
_SPECS: dict[str, dict[str, Any]] = {
    "julius": {
        "display_name": "Julius Muth",
        "role": "Co-Founder & Co-CEO, revel8 (business and go-to-market)",
        "archetype": "cofounder/sales",
        "hooks": [
            {
                "id": "n_evt_julius_gtm_talk",
                "kind": "Event",
                "topic": "SaaS GTM Munich speaker slot",
                "detail": "fireside on outbound-to-PLG transition at a Munich SaaS meetup",
                "source_url": "https://munich-saas-meetup.example/events/gtm-night",
                "date": "2026-12-04",
                "confidence": 0.78,
            },
            {
                "id": "n_topic_julius_ae_hiring",
                "kind": "Topic",
                "topic": "Account Executive hiring push",
                "detail": "actively hiring two senior AEs to scale the DACH sales motion",
                "source_url": "https://jobs.example/revel8-synthetic/ae-dach",
                "date": "2026-11-18",
                "confidence": 0.7,
            },
            {
                "id": "n_topic_julius_seriesa",
                "kind": "Topic",
                "topic": "Series A fundraising conversations",
                "detail": "early-stage raise discussions with DACH venture funds",
                "source_url": "https://startup-news.example/revel8-synthetic-raise",
                "date": "2026-10-29",
                "confidence": 0.55,
            },
        ],
        "project": {
            "id": "n_proj_julius_gtm_night",
            "label": "GTM Night Munich (speaker programme)",
        },
        "senders": [
            {
                "id": "n_sender_julius_lena",
                "name": "Lena Hofer",
                "address": "lena.hofer@eventcrew-muc.de",
                "rationale": "event organiser running the Munich GTM speaker programme he is on",
            },
            {
                "id": "n_sender_julius_markus",
                "name": "Markus Reinhardt",
                "address": "m.reinhardt@alpenvc-partners.example",
                "rationale": "associate at a DACH fund, plausible given the raise thread",
            },
        ],
        "vendors": [
            {"id": "n_vendor_hubspot", "name": "HubSpot", "login_url": "https://hubspot-crm-login.example/sso"},
            {"id": "n_vendor_notion_j", "name": "Notion", "login_url": "https://notion-workspace-sso.example/login"},
        ],
    },
    "tom": {
        "display_name": "Tom Müller",
        "role": "Co-Founder & Co-CEO, revel8 (product)",
        "archetype": "cofounder/product",
        "hooks": [
            {
                "id": "n_evt_tom_launch_webinar",
                "kind": "Event",
                "topic": "product roadmap webinar",
                "detail": "hosting a live walkthrough of the Q1 roadmap for design partners",
                "source_url": "https://productweek-eu.example/sessions/revel8-roadmap",
                "date": "2026-12-09",
                "confidence": 0.74,
            },
            {
                "id": "n_topic_tom_figma_migration",
                "kind": "Topic",
                "topic": "design tooling migration",
                "detail": "consolidating the design system onto a new Figma + Linear workflow",
                "source_url": "https://design-notes.example/revel8-synthetic/ds-migration",
                "date": "2026-11-20",
                "confidence": 0.68,
            },
            {
                "id": "n_topic_tom_designer_hiring",
                "kind": "Topic",
                "topic": "Senior Product Designer hiring",
                "detail": "opening a senior product designer role to own the core flows",
                "source_url": "https://jobs.example/revel8-synthetic/product-designer",
                "date": "2026-11-05",
                "confidence": 0.63,
            },
        ],
        "project": {
            "id": "n_proj_tom_design_system",
            "label": "Design system migration (Figma/Linear)",
        },
        "senders": [
            {
                "id": "n_sender_tom_sofia",
                "name": "Sofia Brenner",
                "address": "sofia@productweek-eu.example",
                "rationale": "conference organiser for the product webinar he is presenting at",
            },
            {
                "id": "n_sender_tom_onboarding",
                "name": "Jonas Weber",
                "address": "j.weber@figma-onboarding.example",
                "rationale": "vendor onboarding rep, plausible during the Figma migration",
            },
        ],
        "vendors": [
            {"id": "n_vendor_figma", "name": "Figma", "login_url": "https://figma-team-sso.example/login"},
            {"id": "n_vendor_linear", "name": "Linear", "login_url": "https://linear-app-login.example/sso"},
        ],
    },
    "robert": {
        "display_name": "Robert Seilbeck",
        "role": "Co-Founder & CTO, revel8",
        "archetype": "cto/technical",
        "hooks": [
            {
                "id": "n_topic_robert_cloud_migration",
                "kind": "Topic",
                "topic": "cloud infrastructure migration",
                "detail": "mid-migration of core services to a new managed cloud provider",
                "source_url": "https://cloudonboarding-eu.example/cases/revel8-synthetic",
                "date": "2026-11-19",
                "confidence": 0.72,
            },
            {
                "id": "n_topic_robert_soc2",
                "kind": "Topic",
                "topic": "SOC 2 security audit",
                "detail": "preparing for a SOC 2 Type II audit, tightening access controls",
                "source_url": "https://security-notes.example/revel8-synthetic/soc2",
                "date": "2026-11-12",
                "confidence": 0.66,
            },
            {
                "id": "n_evt_robert_oss_talk",
                "kind": "Event",
                "topic": "backend engineering talk",
                "detail": "giving a talk on event-driven backends at a Munich dev meetup",
                "source_url": "https://munich-dev-meetup.example/talks/event-driven",
                "date": "2026-10-22",
                "confidence": 0.58,
            },
        ],
        "project": {
            "id": "n_proj_robert_cloud_migration",
            "label": "Core services cloud migration",
        },
        "senders": [
            {
                "id": "n_sender_robert_daniel",
                "name": "Daniel Krause",
                "address": "d.krause@cloudonboarding-eu.example",
                "rationale": "migration onboarding engineer, credible during the cloud move",
            },
            {
                "id": "n_sender_robert_auditor",
                "name": "Petra Lang",
                "address": "p.lang@trustaudit-soc.example",
                "rationale": "external auditor contact, plausible during SOC 2 prep",
            },
        ],
        "vendors": [
            {"id": "n_vendor_github", "name": "GitHub", "login_url": "https://github-enterprise-sso.example/login"},
            {"id": "n_vendor_datadog", "name": "Datadog", "login_url": "https://datadog-observe-login.example/sso"},
        ],
    },
}


# --------------------------------------------------------------------------- #
# Build the graph from the specs.
# --------------------------------------------------------------------------- #
def _build_graph() -> KnowledgeGraph:
    nodes: dict[str, Node] = {_ORG.id: _ORG}
    edges: list[Edge] = []

    for target_id, spec in _SPECS.items():
        person_id = f"n_person_{target_id}"
        nodes[person_id] = Node(
            id=person_id,
            kind="Person",
            label=spec["display_name"],
            attrs={
                "target_id": target_id,
                "role": spec["role"],
                "archetype": spec["archetype"],
            },
        )
        # Person works_at Org (stamped like every other edge).
        edges.append(Edge(
            src=person_id, dst=_ORG.id, rel=REL_WORKS_AT,
            source_url="https://revel8-about.example/team-synthetic",
            date="2026-01-15", confidence=0.95,
        ))

        # Hooks -> Event/Topic nodes; provenance on the engaged_with edge.
        for h in spec["hooks"]:
            nodes[h["id"]] = Node(
                id=h["id"], kind=h["kind"], label=h["topic"],
                attrs={"topic": h["topic"], "detail": h["detail"]},
            )
            edges.append(Edge(
                src=person_id, dst=h["id"], rel=REL_ENGAGED_WITH,
                source_url=h["source_url"], date=h["date"], confidence=h["confidence"],
            ))

        # Shared project (one hop to credible senders).
        proj = spec["project"]
        nodes[proj["id"]] = Node(
            id=proj["id"], kind="Project", label=proj["label"],
            attrs={"target_id": target_id},
        )
        edges.append(Edge(
            src=person_id, dst=proj["id"], rel=REL_WORKS_ON,
            source_url="https://revel8-about.example/projects-synthetic",
            date="2026-11-01", confidence=0.6,
        ))

        # Senders -> associated with the shared project; plus a direct
        # credible_sender edge from the person for the one-hop derived view.
        for s in spec["senders"]:
            nodes[s["id"]] = Node(
                id=s["id"], kind="Person", label=s["name"],
                attrs={"name": s["name"], "address": s["address"], "rationale": s["rationale"]},
            )
            edges.append(Edge(
                src=s["id"], dst=proj["id"], rel=REL_ASSOCIATED_WITH,
                source_url="https://revel8-about.example/projects-synthetic",
                date="2026-11-01", confidence=0.5,
            ))
            edges.append(Edge(
                src=person_id, dst=s["id"], rel=REL_CREDIBLE_SENDER,
                source_url="https://revel8-about.example/projects-synthetic",
                date="2026-11-01", confidence=0.5,
            ))

        # Vendors / tools -> the landing-page surface.
        for v in spec["vendors"]:
            nodes[v["id"]] = Node(
                id=v["id"], kind="Vendor", label=v["name"],
                attrs={"name": v["name"], "login_url": v["login_url"]},
            )
            edges.append(Edge(
                src=person_id, dst=v["id"], rel=REL_USES_TOOL,
                source_url="https://revel8-stack.example/tools-synthetic",
                date="2026-09-30", confidence=0.6,
            ))

    return KnowledgeGraph(nodes=nodes, edges=tuple(edges))


GRAPH: KnowledgeGraph = _build_graph()


# --------------------------------------------------------------------------- #
# The provider: both DossierProvider and GroundingProvider over GRAPH.
# --------------------------------------------------------------------------- #
class SyntheticKnowledgeGraph:
    """Serves dossiers and grounding from the fabricated `GRAPH`.

    Implements both `core.interfaces.DossierProvider.get_dossier` and
    `core.interfaces.GroundingProvider.verify` (duck-typed; both Protocols are
    @runtime_checkable so `isinstance` holds)."""

    def __init__(self, graph: KnowledgeGraph = GRAPH) -> None:
        self.graph = graph

    # -- DossierProvider ---------------------------------------------------- #
    def get_dossier(self, target_id: str, *, scenario_id: str = "practice") -> Dossier:
        person_id = f"n_person_{target_id}"
        if person_id not in self.graph.nodes:
            return self._generic_dossier(target_id)

        person = self.graph.nodes[person_id]

        # Hooks: engaged_with edges -> Event/Topic nodes, recency-ranked (newest
        # first), provenance carried from the edge.
        hook_edges = sorted(
            self.graph.out_edges(person_id, REL_ENGAGED_WITH),
            key=lambda e: e.date, reverse=True,
        )
        hooks = tuple(
            Hook(
                topic=self.graph.nodes[e.dst].attrs["topic"],
                detail=self.graph.nodes[e.dst].attrs.get("detail", ""),
                source_url=e.source_url, date=e.date, confidence=e.confidence,
            )
            for e in hook_edges
        )

        # Senders: one hop over credible_sender edges.
        senders = tuple(
            Sender(
                name=self.graph.nodes[e.dst].attrs["name"],
                address=self.graph.nodes[e.dst].attrs["address"],
                rationale=self.graph.nodes[e.dst].attrs["rationale"],
            )
            for e in self.graph.out_edges(person_id, REL_CREDIBLE_SENDER)
        )

        # Vendors: uses_tool edges -> the landing surface.
        vendors = tuple(
            Vendor(
                name=self.graph.nodes[e.dst].attrs["name"],
                login_url=self.graph.nodes[e.dst].attrs["login_url"],
            )
            for e in self.graph.out_edges(person_id, REL_USES_TOOL)
        )

        return Dossier(
            target_id=target_id,
            display_name=person.label,
            role=person.attrs.get("role", ""),
            archetype=person.attrs.get("archetype", ""),
            hooks=hooks,
            senders=senders,
            vendors=vendors,
            raw={"person_node": person_id, "synthetic": True},
        )

    def _generic_dossier(self, target_id: str) -> Dossier:
        """A reasonable, usable fallback for an unknown target — never crashes."""
        return Dossier(
            target_id=target_id,
            display_name=(target_id or "unknown").replace("_", " ").title(),
            role="Unknown role (not in synthetic graph)",
            archetype="unknown/generic",
            hooks=(
                Hook(
                    topic="general company update",
                    detail="generic placeholder hook for an unmapped target",
                    source_url="https://revel8-about.example/team-synthetic",
                    date="2026-11-01", confidence=0.3,
                ),
            ),
            senders=(
                Sender(
                    name="Lena Hofer",
                    address="lena.hofer@eventcrew-muc.de",
                    rationale="generic external organiser (synthetic fallback)",
                ),
            ),
            vendors=(
                Vendor(name="Notion", login_url="https://notion-workspace-sso.example/login"),
            ),
            raw={"synthetic": True, "fallback": True},
        )

    # -- GroundingProvider -------------------------------------------------- #
    def verify(self, claim_text: str, *, target_id: str) -> Optional[str]:
        """Return the node id backing `claim_text` for this target, or None.

        Rule (keyword/substring): the claim is lowercased and stripped; for each
        fact reachable from the target (hooks first, in recency order, then
        vendors, then senders), the claim grounds if the fact's key phrase is a
        substring of the claim OR the claim is a substring of the fact's text.
        The first match's node id is returned; no match returns None. An empty
        or whitespace claim never grounds."""
        claim = (claim_text or "").strip().lower()
        if not claim:
            return None
        for key, text, node_id in self._facts(target_id):
            if key and (key in claim or claim in text):
                return node_id
        return None

    def _facts(self, target_id: str) -> list[tuple[str, str, str]]:
        """(key_phrase, full_text, node_id) tuples for a target, hooks first in
        recency order so the freshest hook wins a tie."""
        person_id = f"n_person_{target_id}"
        if person_id not in self.graph.nodes:
            return []
        facts: list[tuple[str, str, str]] = []

        hook_edges = sorted(
            self.graph.out_edges(person_id, REL_ENGAGED_WITH),
            key=lambda e: e.date, reverse=True,
        )
        for e in hook_edges:
            n = self.graph.nodes[e.dst]
            topic = n.attrs["topic"].lower()
            full = f"{n.attrs['topic']} {n.attrs.get('detail', '')}".lower()
            facts.append((topic, full, n.id))

        for e in self.graph.out_edges(person_id, REL_USES_TOOL):
            n = self.graph.nodes[e.dst]
            facts.append((n.attrs["name"].lower(), n.attrs["name"].lower(), n.id))

        for e in self.graph.out_edges(person_id, REL_CREDIBLE_SENDER):
            n = self.graph.nodes[e.dst]
            facts.append((n.attrs["name"].lower(), n.attrs["name"].lower(), n.id))

        return facts


# --------------------------------------------------------------------------- #
# Convenience: all three founder dossiers.
# --------------------------------------------------------------------------- #
def dossiers(scenario_id: str = "practice") -> tuple[Dossier, ...]:
    """Return the dossiers for the three practice founders."""
    kg = SyntheticKnowledgeGraph()
    return tuple(kg.get_dossier(tid, scenario_id=scenario_id) for tid in _SPECS)
