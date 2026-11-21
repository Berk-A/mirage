"""The knowledge graph: facts become typed nodes + provenance-stamped edges, with
entity resolution, and the three derived views the dossier needs.

Nodes are typed (`Person`, `Org`, `Project`, `Event`, `Tool`, `Topic`, `Handle`). An
edge is one `Fact`; duplicate facts (same subject/predicate/object from different
sources) are merged — max confidence, most recent event, all sources kept — which is the
entity-resolution/dedup step. NetworkX holds the structure so path queries stay cheap.

Derived views (all read-only over the merged edges):
  * `recent_hooks()`  — timestamped interest/event edges, newest+most-confident first.
  * `credible_senders()` — people one hop from the target over a shared Project/Org.
  * `vendor_surface()` — Tool nodes → the believable landing-page surface.

`ground(claim)` matches a claim back to a fact id, conservatively (exact normalised
claim, or a very-high-overlap fallback), because a wrong grounding costs score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Optional

import networkx as nx

from core.models import Fact, Hook, Sender, Vendor

# predicate -> the node type of its object
_OBJECT_TYPE = {
    "role_is": "Role",
    "works_at": "Org",
    "uses_tool": "Tool",
    "uses_language": "Language",
    "works_on": "Project",
    "engaged_with": "Topic",
    "interested_in": "Topic",
    "spoke_at": "Event",
    "colleague_of": "Person",
    "knows": "Person",
}

# predicates whose objects are "what matters right now" (hook material)
_HOOK_PREDICATES = {"engaged_with", "interested_in", "works_on", "spoke_at"}
# predicates that connect the target to a person (credible-sender material)
_PERSON_PREDICATES = {"colleague_of", "knows"}

_VENDOR_LOGIN = {
    "GitHub": "github.com", "GitLab": "gitlab.com", "Slack": "slack.com",
    "Notion": "notion.so", "Figma": "figma.com", "Linear": "linear.app",
    "Jira": "atlassian.net", "Atlassian": "atlassian.net", "AWS": "aws.amazon.com",
    "Google Cloud": "cloud.google.com", "Microsoft Azure": "portal.azure.com",
    "STACKIT": "stackit.cloud", "Salesforce": "salesforce.com", "HubSpot": "hubspot.com",
    "Stripe": "stripe.com", "Docker": "docker.com", "Datadog": "datadoghq.com",
    "Sentry": "sentry.io", "Vercel": "vercel.com", "Cloudflare": "cloudflare.com",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _node_id(node_type: str, name: str) -> str:
    return f"{node_type}:{_norm(name)}"


@dataclass
class _Edge:
    """A merged fact. Keeps the strongest confidence, the latest event, and every
    source that attested it."""

    fact: Fact
    sources: list[str] = field(default_factory=list)

    def merge(self, other: Fact) -> None:
        best_conf = max(self.fact.confidence, other.confidence)
        latest_event = _max_date(self.fact.event_date, other.event_date)
        latest_obs = _max_date(self.fact.observed_date, other.observed_date) or self.fact.observed_date
        # keep the claim of whichever had higher confidence
        claim = self.fact.canonical_claim if self.fact.confidence >= other.confidence else other.canonical_claim
        self.fact = Fact(
            id=self.fact.id,
            subject=self.fact.subject,
            predicate=self.fact.predicate,
            object_value=self.fact.object_value,
            canonical_claim=claim,
            source_url=self.fact.source_url,
            observed_date=latest_obs,
            event_date=latest_event,
            confidence=best_conf,
        )
        if other.source_url and other.source_url not in self.sources:
            self.sources.append(other.source_url)


def _max_date(a: Optional[str], b: Optional[str]) -> Optional[str]:
    vals = [d for d in (a, b) if d]
    return max(vals) if vals else None


class KnowledgeGraph:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()
        self._edges: dict[str, _Edge] = {}  # semantic key -> merged edge

    # ---- build --------------------------------------------------------- #
    def add_person(self, target_id: str, *, name: str = "", role: str = "") -> None:
        nid = _node_id("Person", target_id)
        self.g.add_node(nid, type="Person", name=name or target_id, target_id=target_id, role=role)

    def add_fact(self, fact: Fact) -> None:
        key = f"{fact.subject}|{fact.predicate}|{_norm(fact.object_value)}"
        if key in self._edges:
            self._edges[key].merge(fact)
            merged = self._edges[key].fact
            self._apply_edge(merged, self._edges[key].sources)
            return
        self._edges[key] = _Edge(fact=fact, sources=[fact.source_url] if fact.source_url else [])
        self._apply_edge(fact, self._edges[key].sources)

    def add_facts(self, facts: Iterable[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def _apply_edge(self, fact: Fact, sources: list[str]) -> None:
        subj = _node_id("Person", fact.subject)
        if subj not in self.g:
            self.g.add_node(subj, type="Person", name=fact.subject, target_id=fact.subject)
        obj_type = _OBJECT_TYPE.get(fact.predicate, "Topic")
        obj = _node_id(obj_type, fact.object_value)
        if obj not in self.g:
            self.g.add_node(obj, type=obj_type, name=fact.object_value)
        self.g.add_edge(
            subj, obj, key=fact.id,
            predicate=fact.predicate,
            fact_id=fact.id,
            canonical_claim=fact.canonical_claim,
            confidence=fact.confidence,
            event_date=fact.event_date,
            observed_date=fact.observed_date,
            sources=list(sources),
        )

    # ---- access -------------------------------------------------------- #
    @property
    def facts(self) -> list[Fact]:
        return [e.fact for e in self._edges.values()]

    def facts_for(self, target_id: str) -> list[Fact]:
        return [f for f in self.facts if f.subject == target_id]

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        for f in self.facts:
            if f.id == fact_id:
                return f
        return None

    def nodes_of_type(self, node_type: str) -> list[dict]:
        return [data for _, data in self.g.nodes(data=True) if data.get("type") == node_type]

    def role_of(self, target_id: str) -> str:
        for f in self.facts_for(target_id):
            if f.predicate == "role_is":
                return f.object_value
        node = self.g.nodes.get(_node_id("Person", target_id), {})
        return node.get("role", "")

    # ---- derived views ------------------------------------------------- #
    def recent_hooks(self, target_id: str, *, limit: int = 5) -> list[Hook]:
        """Timestamped interest/project/event edges → current hooks, newest + most
        confident first. `detail` carries the canonical claim verbatim so the claim the
        decider ships can be grounded by `ground()`."""
        cands = [
            f for f in self.facts_for(target_id) if f.predicate in _HOOK_PREDICATES
        ]
        cands.sort(key=lambda f: (f.event_date or "", f.confidence), reverse=True)
        hooks: list[Hook] = []
        seen: set[str] = set()
        for f in cands:
            topic = f.object_value
            if topic.lower() in seen:
                continue
            seen.add(topic.lower())
            hooks.append(
                Hook(
                    topic=topic,
                    detail=f.canonical_claim,
                    source_url=f.source_url,
                    date=f.event_date or f.observed_date,
                    confidence=round(f.confidence, 3),
                )
            )
            if len(hooks) >= limit:
                break
        return hooks

    def credible_senders(self, target_id: str, *, limit: int = 5) -> list[Sender]:
        """People one hop from the target over a shared Project/Org, plus any explicit
        colleague edges. Address is left blank: it is a claim the decider/renderer
        chooses, and we never carry a real person's contact details."""
        senders: list[Sender] = []
        seen: set[str] = set()

        # explicit colleague/knows edges
        for f in self.facts_for(target_id):
            if f.predicate in _PERSON_PREDICATES:
                name = f.object_value
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                senders.append(
                    Sender(name=name, address="", rationale=f.canonical_claim)
                )

        # one-hop over shared Project/Org nodes to other Person nodes
        subj = _node_id("Person", target_id)
        if subj in self.g:
            for shared in self.g.successors(subj):
                stype = self.g.nodes[shared].get("type")
                if stype not in ("Project", "Org"):
                    continue
                shared_name = self.g.nodes[shared].get("name", "")
                for other in self.g.predecessors(shared):
                    odata = self.g.nodes[other]
                    if odata.get("type") != "Person" or other == subj:
                        continue
                    name = odata.get("name", "")
                    if not name or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    senders.append(
                        Sender(
                            name=name,
                            address="",
                            rationale=f"Shares {stype.lower()} {shared_name} with the target.",
                        )
                    )
                    if len(senders) >= limit:
                        return senders
        return senders[:limit]

    def vendor_surface(self, target_id: str, *, limit: int = 5) -> list[Vendor]:
        """Tool nodes the target uses → the believable landing-page surface, ranked by
        how strongly/recently attested."""
        tools: dict[str, tuple[float, str]] = {}
        for f in self.facts_for(target_id):
            if f.predicate != "uses_tool":
                continue
            name = f.object_value
            score = f.confidence + (0.1 if f.event_date else 0.0)
            if name not in tools or score > tools[name][0]:
                tools[name] = (score, f.event_date or "")
        ranked = sorted(tools.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
        out: list[Vendor] = []
        for name, _ in ranked[:limit]:
            out.append(Vendor(name=name, login_url=_vendor_login_url(name)))
        return out

    # ---- grounding ----------------------------------------------------- #
    def ground(self, claim_text: str, *, target_id: str, min_ratio: float = 0.93) -> Optional[str]:
        """Return the fact id backing a claim, or None. Exact normalised match first;
        then a very-high-overlap fallback (guards against paraphrase drift while still
        refusing anything it is not confident about)."""
        wanted = _norm(claim_text)
        facts = self.facts_for(target_id)
        for f in facts:
            if _norm(f.canonical_claim) == wanted:
                return f.id
        best_id, best_ratio = None, 0.0
        for f in facts:
            ratio = SequenceMatcher(None, wanted, _norm(f.canonical_claim)).ratio()
            if ratio > best_ratio:
                best_id, best_ratio = f.id, ratio
        return best_id if best_ratio >= min_ratio else None


def _vendor_login_url(name: str) -> str:
    host = _VENDOR_LOGIN.get(name)
    return f"https://{host}" if host else ""
