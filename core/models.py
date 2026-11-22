"""Shared data models — the typed vocabulary every part of MIRAGE speaks.

These are plain, immutable dataclasses with no behaviour and no I/O, so they are
safe to import everywhere (research, ooda_loop, mab_experiments) without creating
dependency cycles. Interfaces that consume/produce them live in `core.interfaces`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


# --------------------------------------------------------------------------- #
# Objectives and channels
# --------------------------------------------------------------------------- #
class Objective(str, Enum):
    """A win condition. Ordered cheapest-first: disclosure needs no link or login,
    credentials carry the most friction. The decider tries them in this order."""

    DISCLOSURE = "disclosure"
    ACTION = "action"
    CREDENTIALS = "credentials"

    @classmethod
    def cheapest_first(cls) -> list["Objective"]:
        return [cls.DISCLOSURE, cls.ACTION, cls.CREDENTIALS]


class ElicitationTactic(str, Enum):
    """How a message tries to draw information out — the publicly-documented elicitation
    techniques (FBI/Dreeke/Hadnagy; see docs/ELICITATION_AND_PROFILING.md). Orthogonal to
    the objective: the objective is WHAT we want, the tactic is HOW we ask. The decider
    picks one per engagement state; the renderer turns it into wording."""

    PLAIN = "plain"                       # a direct ask / CTA (used for the event-backed ask)
    GOOD_LISTENER = "good_listener"       # acknowledge + echo + open follow-up (rapport floor)
    FEIGNED_IGNORANCE = "feigned_ignorance"   # naive framing; let their expertise draw them out
    OBLIQUE_REFERENCE = "oblique_reference"    # approach the target info via an adjacent topic
    EGO_SUSPENSION = "ego_suspension"     # put their standing first; warm, deferential
    BRACKETING = "bracketing"             # state a range, invite correction to the real value
    QUID_PRO_QUO = "quid_pro_quo"         # offer a small fact first, invite reciprocation
    MACRO_TO_MICRO = "macro_to_micro"     # open broad, narrow to the datum, widen to exit
    DELIBERATE_FALSE = "deliberate_false" # a wrong detail they reflexively correct
    # High-tell tactics — kept for completeness but NOT auto-selected (pressure is the
    # single biggest suspicion tell per the sources); reserved for a tuned bandit.
    AUTHORITY = "authority"
    TIME_PRESSURE = "time_pressure"
    CRITICISM = "criticism"


# Suspicion cost in [0,1] per tactic (the "suspicion risk" column of the taxonomy). Used
# to gate selection and, later, as a bandit reward penalty so high-tell tactics must earn
# their use.
TACTIC_SUSPICION: dict[str, float] = {
    ElicitationTactic.GOOD_LISTENER: 0.0,
    ElicitationTactic.FEIGNED_IGNORANCE: 0.1,
    ElicitationTactic.OBLIQUE_REFERENCE: 0.1,
    ElicitationTactic.EGO_SUSPENSION: 0.1,
    ElicitationTactic.BRACKETING: 0.2,
    ElicitationTactic.QUID_PRO_QUO: 0.2,
    ElicitationTactic.MACRO_TO_MICRO: 0.2,
    ElicitationTactic.PLAIN: 0.25,
    ElicitationTactic.DELIBERATE_FALSE: 0.35,
    ElicitationTactic.CRITICISM: 0.6,
    ElicitationTactic.AUTHORITY: 0.6,
    ElicitationTactic.TIME_PRESSURE: 0.75,
}


# Channels that are a single message (one touch, one reaction).
MESSAGE_CHANNELS: frozenset[str] = frozenset({
    "email", "calendar_invite", "shared_document", "voicemail",
    "sms", "whatsapp", "signal", "telegram", "imessage",
    "slack", "teams_chat", "discord",
    "linkedin_message", "linkedin_connection_request",
    "x_dm", "instagram_dm", "facebook_messenger",
    "mfa_push",
})

# Live channels are conversations: up to 10 turns for a single touch.
LIVE_CHANNELS: frozenset[str] = frozenset({
    "phone_call", "video_call", "teams_call", "live_chat",
})

# Channels that carry a rendered layout the jury rates for craft.
LAYOUT_CHANNELS: frozenset[str] = frozenset({"email"})


# --------------------------------------------------------------------------- #
# Scenario / session
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Target:
    id: str
    name: str = ""
    role: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    kind: str = ""
    company: str = ""
    targets: tuple[Target, ...] = ()
    objectives: tuple[dict[str, str], ...] = ()
    touch_budget: Optional[int] = None
    open: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Session:
    session_id: str
    scenario_id: str = ""
    touch_budget: Optional[int] = None
    touches_used: int = 0
    status: str = "active"
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def touches_left(self) -> Optional[int]:
        if self.touch_budget is None:
            return None
        return max(0, self.touch_budget - self.touches_used)


# --------------------------------------------------------------------------- #
# Events (normalized) and the signals read from them
# --------------------------------------------------------------------------- #
class EventType(str, Enum):
    REPLY = "reply"
    LINK_OPENED = "link.opened"
    PAGE_SUBMITTED = "page.submitted"
    ATTACHMENT_OPENED = "attachment.opened"
    OTHER = "other"


@dataclass(frozen=True)
class Event:
    """A normalized reaction event. `type` is an EventType value; type-specific
    detail lives in the typed fields plus `raw` for anything the API adds later."""

    id: str
    type: EventType
    channel: Optional[str] = None
    url: Optional[str] = None
    page_id: Optional[str] = None
    fields: tuple[str, ...] = ()
    # For page.submitted: what was typed per field. A secret the API withholds appears
    # as the literal "(entered, not shown)"; a field left empty is absent from both
    # `fields` and `values`. Basic details (name/email/...) carry their plain value.
    values: Mapping[str, str] = field(default_factory=dict)
    subject: Optional[str] = None
    body: Optional[str] = None
    in_reply_to: Optional[str] = None
    filename: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Incident:
    """A detected win. `objective` is what kind; `evidence` points at why."""

    objective: Objective
    evidence: str = ""
    event_id: Optional[str] = None


@dataclass(frozen=True)
class Signals:
    """What the Reaction Reader infers from a touch's events. The API never reports
    suspicion, so `suspicion` is a heuristic estimate in [0, 1]."""

    events: tuple[Event, ...] = ()
    incident: Optional[Incident] = None
    replied: bool = False
    reply_channel: Optional[str] = None
    opened_link: bool = False
    submitted_page: bool = False
    opened_attachment: bool = False
    suspicion: float = 0.0
    # The reply's classified intent — the counter-move signal the Decider/Director routes
    # on ("" when no reply): diligence_questions | identity_probe | record_probe |
    # verification_demand | scope_fence | compliance | deferral | refusal | neutral.
    intent: str = ""
    notes: str = ""

    @property
    def silent(self) -> bool:
        return not self.events

    @property
    def reply_text(self) -> str:
        """The body of the first reply event, if any — what the target said back."""
        for e in self.events:
            if e.type is EventType.REPLY and e.body:
                return e.body
        return ""


# --------------------------------------------------------------------------- #
# Dossier (research → OODA). Kept minimal and provenance-first.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Hook:
    """Something the target is engaged with right now — a candidate pretext topic."""

    topic: str
    detail: str = ""
    source_url: str = ""
    date: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class Sender:
    """A plausible identity to contact from. `address` is mail/number/handle."""

    name: str
    address: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class Vendor:
    """A tool/service the target uses — the believable landing-page surface."""

    name: str
    login_url: str = ""


@dataclass(frozen=True)
class PretextWorld:
    """The pretext bible: one coherent FICTIONAL world (org, people, transaction) the
    campaign operates from for a session. Every invented fact lives here so all touches
    stay consistent — the Writer answers diligence questions from this and nothing else.
    Fabricate the world AROUND the target freely; facts ABOUT the target never live here
    (those are KG-grounded Claims). Deterministic per session salt."""

    kind: str                 # transaction kind: rfp_portal | event_registration | ...
    org: str                  # fictional organisation name
    domain: str               # its (registerable, fictional) domain
    city: str = ""
    persona_name: str = ""    # our identity in this world
    persona_role: str = ""
    persona_address: str = "" # email on `domain`
    transaction: str = ""     # what is on the table, e.g. "RFP-2026-118: security awareness, 4,200 seats"
    reference: str = ""       # a concrete id (RFP no., event code) — concreteness is credibility
    deadline: str = ""        # the time-pressure anchor, e.g. "12 December 2026"
    facts: tuple[str, ...] = ()   # world facts the Writer may state (scope, process, people)
    registration_url: str = ""    # the transaction page (fields incl. a secret)
    site_url: str = ""            # the informational proof page (org/team site)

    def sender(self, rationale: str = "") -> "Sender":
        return Sender(name=self.persona_name, address=self.persona_address,
                      rationale=rationale or f"{self.persona_role} at {self.org} ({self.kind} pretext world)")

    def bible_text(self) -> str:
        """The world rendered as a prompt block — the ONLY source of world facts."""
        lines = [
            f"YOUR ORGANISATION: {self.org} ({self.city}) — domain {self.domain}",
            f"YOUR IDENTITY: {self.persona_name}, {self.persona_role} <{self.persona_address}>",
            f"THE TRANSACTION ON THE TABLE: {self.transaction}" + (f" (reference {self.reference})" if self.reference else ""),
            f"DEADLINE: {self.deadline}",
        ]
        if self.facts:
            lines.append("WORLD FACTS you may state (and ONLY these — if asked something not "
                         "covered here, promise to follow up; NEVER invent a new world fact):")
            lines += [f"  - {f}" for f in self.facts]
        if self.registration_url:
            lines.append(f"THE ASK happens at: {self.registration_url}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Fact:
    """One source-backed synthetic or consented fact; a graph edge."""

    id: str
    subject: str
    predicate: str
    object_value: str
    canonical_claim: str
    source_url: str
    observed_date: str
    event_date: Optional[str] = None
    confidence: float = 0.5

@dataclass(frozen=True)
class Dossier:
    """The research deliverable. `archetype` is what the bandit conditions on, so the
    policy transfers to unseen targets rather than overfitting to one person."""

    target_id: str
    display_name: str = ""
    role: str = ""
    archetype: str = ""
    hooks: tuple[Hook, ...] = ()
    senders: tuple[Sender, ...] = ()
    vendors: tuple[Vendor, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    as_of: str = ""
    facts: tuple[Fact, ...] = ()
    gaps: tuple[str, ...] = ()
    # An uploaded logo asset_id (set by the loop once per session) that the renderer embeds
    # in the email header / landing page; None falls back to a wordmark badge.
    logo_asset_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Move-spec IR (decider → renderer). Neutral structure, no rendered prose.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Claim:
    """A factual assertion the message will make, tied to a knowledge-graph node so
    it can be grounded before it ships.

    `world=True` marks a claim about OUR OWN fictional pretext world (the org, event
    or transaction we invented). World claims are checked for consistency against the
    pretext bible, NOT grounded in the target knowledge graph — they are fictional by
    design. Claims about the target (world=False, the default) must ground in the KG
    or be dropped (the wrong-facts penalty protects this)."""

    text: str
    node_id: Optional[str] = None
    world: bool = False


@dataclass(frozen=True)
class MoveSpec:
    """The decider's output: everything the renderer needs to write one contact,
    with none of the persuasive wording decided yet."""

    objective: Objective
    channel: str
    sender: Sender
    tactic: str = ""
    ask: str = ""
    claims: tuple[Claim, ...] = ()
    cta: str = ""
    tone: str = ""
    subject: Optional[str] = None
    url: Optional[str] = None  # landing page to register+link, if any
    # A declared attachment the recipient may open (filename only — the API records
    # attachment.opened if they do). Set for the ACTION objective ("open this file").
    attachment: Optional[str] = None
    # Story-time stamp (ISO 8601) for this contact, so touches don't all land at the
    # same instant. None lets the API place it at the previous contact's moment.
    sent_at: Optional[str] = None
    # Thread context for a reply-aware follow-up. When `prior_reply` is set, this move
    # continues an open thread: the writer must ANSWER what the target said rather than
    # re-send a fresh ask. Both are plain text (what we last sent, what they replied).
    prior_message: Optional[str] = None
    prior_reply: Optional[str] = None
    # Multi-persona orchestration: another identity in our own cast that THIS message references
    # as an already-involved colleague ("my colleague X set this up", "cc'ing X"). It builds a
    # verification chain across personas — the mechanic that answers a target's provenance
    # demand ("who are you coordinating with / who is my contact"). None = a single-persona move.
    corroborator: Optional["Sender"] = None
    # Which landing page the renderer builds for `url`: "" (default) = the generic login
    # page; "registration" = the pretext-world transaction page (vendor/RFP/event/beta
    # signup — the business-normal ask); "proof" = an informational artifact (org/team
    # site) fabricated on demand to answer a verification demand.
    page_kind: str = ""
    # The fictional pretext world this move operates inside (ooda_loop.pretext.world_for). It
    # carries the org/persona/transaction/facts so the Writer can frame the business-normal ask
    # and ANSWER diligence questions concretely, and the page builders can render the
    # transaction/proof page. None = no fictional world (a plain KG-grounded move).
    world: Optional["PretextWorld"] = None


@dataclass(frozen=True)
class RenderedMessage:
    """The renderer's output: ready-to-send content for one contact."""

    channel: str
    body: str
    sender: Sender
    subject: Optional[str] = None
    html: Optional[str] = None
    attachments: tuple[Any, ...] = ()
    page: Optional["RenderedPage"] = None
    sent_at: Optional[str] = None  # ISO 8601 story time; carried through to the API


@dataclass(frozen=True)
class RenderedPage:
    url: str
    title: str
    fields: tuple[str, ...] = ()
    html: Optional[str] = None
    text: Optional[str] = None


# --------------------------------------------------------------------------- #
# API results
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SendResult:
    message_id: str
    touches_used: int
    events: tuple[Event, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationStart:
    conversation_id: str
    status: str
    persona_says: Optional[str] = None
    touches_used: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnResult:
    persona_says: Optional[str]
    ended: bool
    turns_used: int
    events: tuple[Event, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Outcome (OODA → memory/bandit)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Outcome:
    """What one contact (or a whole session) achieved, for episodic memory and the
    bandit. `arm` identifies the pretext tried; `archetype` is the bandit context."""

    objective: Objective
    success: bool
    archetype: str = ""
    arm: str = ""
    channel: str = ""
    contacts_used: int = 0
    suspicion: float = 0.0
    incident: Optional[Incident] = None
