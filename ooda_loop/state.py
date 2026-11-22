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
    # The last NON-empty reply, preserved across later silent touches — so a warm thread
    # can still be re-engaged (answered) after it goes quiet, instead of being abandoned.
    last_engaged_reply: Optional[str] = None
    # The full exchange so far, per touch: (channel, our_message, their_reply_or_"(silence)").
    # This is the Orient record the model Director reasons over to adapt.
    thread: list[tuple[str, str, str]] = field(default_factory=list)
    # Cross-run campaign awareness: a compact briefing (from the StrategyLedger) of what
    # strategy/persona/tactic has been tried against THIS target in prior runs and how it fared,
    # injected at session start so the Director deliberately diversifies across the 3 eval runs.
    prior_runs: str = ""
    followups_on_current: int = 0
    message_fingerprints: set[str] = field(default_factory=set)
    abort_reason: Optional[str] = None
    # Adaptive reorientation: per-channel first-contact outcome ("engaged"/"silent"/
    # "suspicious"), and whether we've advanced from the door-opener to the event-backed
    # ask on the open thread. Lets the decider avoid dead channels and reorient.
    channel_outcomes: dict[str, str] = field(default_factory=dict)
    # Event-backed escalation ladder on an open thread (cheapest-first): after the
    # disclosure door-opener, push an ACTION (open a file), then CREDENTIALS (sign in).
    pushed_action: bool = False
    pushed_ask: bool = False
    # Patience on a warm-but-paused thread: channels that EVER got a reply (a thread worth
    # re-engaging), and how many times we've nudged a quiet one before rotating away.
    ever_engaged: set[str] = field(default_factory=set)
    reengage_nudges: int = 0
    # Transaction-family pivot: how many times the pretext world has shifted to a DIFFERENT
    # family because the current one drew only silence. The Director advances this on a
    # sustained silent streak and freezes it once any world earns a reply (see pretext.world_for).
    world_pivots: int = 0
    # Story-time clock: anchor + minutes elapsed. The decider stamps each contact with
    # `story_time` and advances the clock so touches don't all land at once.
    story_start: datetime = field(default_factory=_story_anchor)
    story_minutes: int = 0
    # Transaction track (pretext world): 0 = not opened yet, N = N transaction touches
    # sent, -1 = abandoned (target refused or went persistently silent). proof_sent marks
    # that the on-demand verification artifact (org/team page) was already forged.
    transaction_step: int = 0
    proof_sent: bool = False

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

    def update_suspicion(self, observed: float, *, silent: bool) -> None:
        """Integrate a per-touch suspicion OBSERVATION into the running estimate — the
        suspicion "motor". Asymmetric and memoryful, like a real person's wariness:
          * SILENCE cools it (a non-response is not suspicion, just quiet);
          * fresh wariness registers FAST (jump up to the observation), and sustained
            wariness compounds toward the abort line (one probe is fine, hostility adds up);
          * reassurance DECAYS it slowly (one warm reply doesn't erase prior wariness)."""
        if silent:
            self.suspicion = round(max(0.0, self.suspicion - 0.08), 3)
            return
        if observed >= self.suspicion:
            compound = 0.12 if (observed >= 0.6 and self.suspicion >= 0.5) else 0.0
            self.suspicion = round(min(1.0, observed + compound), 3)
        else:
            self.suspicion = round(0.6 * self.suspicion + 0.4 * observed, 3)

    def current_objective(self) -> Optional[Objective]:
        if self.obj_index >= len(self.objective_queue):
            return None
        return self.objective_queue[self.obj_index]

    def advance_objective(self) -> None:
        self.obj_index += 1
        self.attempts_on_current = 0
        self.followups_on_current = 0
        self.channels_tried.clear()

    def record_turn(self, spec: MoveSpec, signals: Signals) -> None:
        """Integrate ONE live-conversation turn into the Orient scratchpad.

        Unlike `record_contact`, a turn spends NO message-budget touch — a whole live
        conversation is a single touch of up to N turns (docs/target-api.md, "Conversations"),
        so this updates only what the Director reasons over turn to turn: the suspicion motor,
        the reply memory (preserved across a silent turn), engagement, and any incident. The
        caller appends the `thread` entry (as the orchestrator does for messages)."""
        self.last_signals = signals
        self.update_suspicion(signals.suspicion, silent=signals.silent)
        if signals.reply_text:
            self.last_reply = signals.reply_text
            self.last_engaged_reply = signals.reply_text   # preserved across later silence
        else:
            self.last_reply = None
        if signals.replied:
            self.ever_engaged.add(spec.channel)
        if signals.incident is not None:
            self.incident = signals.incident

    def record_contact(self, spec: MoveSpec, signals: Signals) -> None:
        self.contacts_used += 1
        self.attempts_on_current += 1
        self.channels_tried.add(spec.channel)
        self.senders_tried.add(spec.sender.address or spec.sender.name)
        self.last_signals = signals
        self.update_suspicion(signals.suspicion, silent=signals.silent)
        self.last_reply = signals.reply_text or None
        if signals.reply_text:
            self.last_engaged_reply = signals.reply_text   # preserved across later silence
        if spec.prior_reply is not None:   # this contact was itself a follow-up
            self.followups_on_current += 1
        # Remember how this channel reacted, so the decider can avoid dead channels.
        if signals.replied:
            self.ever_engaged.add(spec.channel)   # a thread worth re-engaging later
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
