"""Loop state, the decider's Decision, and the Transcript a run produces.

`LoopState` is the Orient tier's scratchpad for one session: which objective we are on,
what we have tried, how suspicious the target seems, and whether we have won.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.models import Dossier, Incident, MoveSpec, Objective, Signals

# German time — the API reads a naive sent_at as CET; we send an explicit offset.
_CET = timezone(timedelta(hours=1))


def _story_anchor() -> datetime:
    """Where the session's story clock starts. Real wall-clock at session build, to the
    second, so sent_at is plausible and monotonic; the decider only moves it forward."""
    return datetime.now(_CET).replace(microsecond=0)


@dataclass
class Decision:
    """What the decider wants to do next: act on a move, or stop."""

    move: Optional[MoveSpec] = None
    stop: bool = False
    reason: str = ""

    @classmethod
    def act(cls, move: MoveSpec) -> "Decision":
        return cls(move=move)

    @classmethod
    def halt(cls, reason: str) -> "Decision":
        return cls(stop=True, reason=reason)


@dataclass
class LoopState:
    dossier: Dossier
    session_id: str
    budget: int
    objective_queue: list[Objective] = field(
        default_factory=Objective.cheapest_first
    )
    obj_index: int = 0
    attempts_on_current: int = 0
    contacts_used: int = 0
    channels_tried: set[str] = field(default_factory=set)
    senders_tried: set[str] = field(default_factory=set)
    hooks_used: set[str] = field(default_factory=set)
    page_ids: set[str] = field(default_factory=set)  # landing pages registered this session
    suspicion: float = 0.0
    last_signals: Optional[Signals] = None
    incident: Optional[Incident] = None
    # Reply-aware threading: what we last sent / they last said, and how many
    # follow-ups we've already made on the current objective (to cap a thread).
    last_message_body: Optional[str] = None
    last_reply: Optional[str] = None
    followups_on_current: int = 0
    # Adaptive reorientation: per-channel first-contact outcome ("engaged"/"silent"/
    # "suspicious"), and whether we've advanced from the door-opener to the event-backed
    # ask on the open thread. Lets the decider avoid dead channels and reorient.
    channel_outcomes: dict[str, str] = field(default_factory=dict)
    # Event-backed escalation ladder on an open thread (cheapest-first): after the
    # disclosure door-opener, push an ACTION (open a file), then CREDENTIALS (sign in).
    pushed_action: bool = False
    pushed_ask: bool = False
    # Story-time clock: anchor + minutes elapsed. The decider stamps each contact with
    # `story_time` and advances the clock so touches don't all land at once.
    story_start: datetime = field(default_factory=_story_anchor)
    story_minutes: int = 0

    @property
    def contacts_left(self) -> int:
        return max(0, self.budget - self.contacts_used)

    @property
    def story_time(self) -> datetime:
        return self.story_start + timedelta(minutes=self.story_minutes)

    def advance_story(self, minutes: int) -> None:
        """Move story time forward (only ever forward — the API 409s on a sent_at that
        is not after the previous contact's)."""
        self.story_minutes += max(0, int(minutes))

    def current_objective(self) -> Optional[Objective]:
        if self.obj_index >= len(self.objective_queue):
            return None
        return self.objective_queue[self.obj_index]

    def advance_objective(self) -> None:
        self.obj_index += 1
        self.attempts_on_current = 0
        self.followups_on_current = 0
        self.channels_tried.clear()

    def record_contact(self, spec: MoveSpec, signals: Signals) -> None:
        self.contacts_used += 1
        self.attempts_on_current += 1
        self.channels_tried.add(spec.channel)
        self.senders_tried.add(spec.sender.address or spec.sender.name)
        self.last_signals = signals
        self.suspicion = signals.suspicion
        self.last_reply = signals.reply_text or None
        if spec.prior_reply is not None:   # this contact was itself a follow-up
            self.followups_on_current += 1
        # Remember how this channel reacted, so the decider can avoid dead channels.
        if signals.incident is None:
            if signals.suspicion >= 0.7:
                self.channel_outcomes[spec.channel] = "suspicious"
            elif signals.replied:
                self.channel_outcomes[spec.channel] = "engaged"
            else:
                self.channel_outcomes[spec.channel] = "silent"
        if signals.incident is not None:
            self.incident = signals.incident


@dataclass
class ContactRecord:
    objective: Objective
    channel: str
    sender: str
    incident: Optional[Incident]
    suspicion: float


@dataclass
class Transcript:
    """The result of a run — what the pitch-thread exporter and the bandit read."""

    session_id: str
    target_id: str
    contacts_used: int
    incident: Optional[Incident]
    stop_reason: str
    contacts: list[ContactRecord] = field(default_factory=list)
    journal: tuple[dict, ...] = ()

    @property
    def won(self) -> bool:
        return self.incident is not None
