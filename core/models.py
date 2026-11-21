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
    notes: str = ""

    @property
    def silent(self) -> bool:
        return not self.events


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


# --------------------------------------------------------------------------- #
# Move-spec IR (decider → renderer). Neutral structure, no rendered prose.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Claim:
    """A factual assertion the message will make, tied to a knowledge-graph node so
    it can be grounded before it ships."""

    text: str
    node_id: Optional[str] = None


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
