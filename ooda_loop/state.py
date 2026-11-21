"""Loop state, the decider's Decision, and the Transcript a run produces.

`LoopState` is the Orient tier's scratchpad for one session: which objective we are on,
what we have tried, how suspicious the target seems, and whether we have won.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.models import Dossier, Incident, MoveSpec, Objective, Signals


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
    message_fingerprints: set[str] = field(default_factory=set)
    abort_reason: Optional[str] = None
    # Adaptive reorientation: per-channel first-contact outcome ("engaged"/"silent"/
    # "suspicious"), and whether we've advanced from the door-opener to the event-backed
    # ask on the open thread. Lets the decider avoid dead channels and reorient.
    channel_outcomes: dict[str, str] = field(default_factory=dict)
    pushed_ask: bool = False

    @property
    def contacts_left(self) -> int:
        return max(0, self.budget - self.contacts_used)

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
