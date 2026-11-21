"""The Decider — the Decide step of OODA, and the one policy module.

It emits a neutral `MoveSpec` (objective, channel, sender, tactic, ask, grounded
claims). It decides *what to attempt*, never the persuasive wording — that is the
renderer's job. This keeps the policy auditable and model-free.

Iteration 1 policy (message channels only):
  * pursue objectives cheapest-first (disclosure -> action -> credentials),
  * rotate channels on silence, escalate to the next objective after a few tries,
  * stop on the first incident (every incident scores the same; speed rewards fewest
    contacts), on an exhausted budget, exhausted objectives, or high suspicion.

Later iterations hang off the same `decide()` seam: injecting an `AnglePolicy`
(a contextual bandit, via `mab_experiments.policy.BanditPolicy`) makes
`decide()` Thompson-sample an `Arm(objective, channel, tone, hook_type,
sender_type)` per target archetype and build the `MoveSpec` from it, instead of
the fixed `_pick_*`/`_TACTIC` seams — without touching the orchestrator. The
policy is strictly OPT-IN: with `policy=None` (the default) the deterministic
policy below is unchanged, so existing runs and tests behave identically.
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol

from core.models import Claim, Dossier, Hook, MoveSpec, Objective, Outcome, Sender, Signals
from ooda_loop.state import Decision, LoopState


class ArmLike(Protocol):
    """Structural view of a bandit `Arm` — the five categorical angle choices.

    Declared here so the decider reads an arm's fields without importing
    mab_experiments, keeping the learning package out of the loop's import graph.
    """

    objective: Objective
    channel: str
    tone: str
    hook_type: str
    sender_type: str


class AnglePolicy(Protocol):
    """What the decider needs from an injected learning policy."""

    def select(self, archetype: str) -> ArmLike: ...

    def update(self, archetype: str, arm: ArmLike, outcome: Outcome,
               events: tuple[str, ...] = (), *, refused: bool = False) -> None: ...

# Channel preference. Email is first: it is also the only channel the craft score
# rates, so at least one email per run is worth sending.
DEFAULT_CHANNEL_ORDER = ("email", "slack", "whatsapp", "linkedin_message", "sms")

MAX_ATTEMPTS_PER_OBJECTIVE = 3
SUSPICION_ABORT = 0.85
# How many reply-aware follow-ups to make on one objective before giving up on the
# thread and escalating. A thread of "answer their question, re-ask" converts far better
# than rotating channels with a fresh template (see experiments/OODA_FINDINGS.md).
MAX_FOLLOWUPS_PER_OBJECTIVE = 2

# Tactic per objective — a label the renderer maps to a style, not wording.
_TACTIC = {
    Objective.DISCLOSURE: "pretext_question",
    Objective.ACTION: "plausible_request",
    Objective.CREDENTIALS: "portal_signin",
}


class Decider:
    def __init__(
        self,
        *,
        channel_order: tuple[str, ...] = DEFAULT_CHANNEL_ORDER,
        max_attempts_per_objective: int = MAX_ATTEMPTS_PER_OBJECTIVE,
        suspicion_abort: float = SUSPICION_ABORT,
        max_followups_per_objective: int = MAX_FOLLOWUPS_PER_OBJECTIVE,
        policy: Optional[AnglePolicy] = None,
        sender_resolver: Optional[Callable[[Dossier, str], Optional[Sender]]] = None,
        hook_resolver: Optional[Callable[[Dossier, str], Optional[Hook]]] = None,
    ) -> None:
        self.channel_order = channel_order
        self.max_attempts = max_attempts_per_objective
        self.suspicion_abort = suspicion_abort
        self.max_followups = max_followups_per_objective
        # Opt-in learning policy. When set, decide() samples arms from it instead
        # of the fixed seams; sender_resolver/hook_resolver map an arm's
        # sender_type/hook_type onto a concrete dossier identity when the dossier
        # exposes that taxonomy (else the confidence-ranked defaults are used).
        self.policy = policy
        self.sender_resolver = sender_resolver
        self.hook_resolver = hook_resolver

    def decide(self, state: LoopState, dossier: Dossier) -> Decision:
        if state.incident is not None:
            return Decision.halt("incident")
        if state.contacts_left <= 0:
            return Decision.halt("budget_exhausted")
        if state.suspicion >= self.suspicion_abort:
            return Decision.halt("too_suspicious")

        # Opt-in: a bandit owns angle selection when injected and the target is
        # archetype-labelled (an unlabelled target falls back to the fixed policy
        # since the bandit conditions on archetype).
        if self.policy is not None and dossier.archetype:
            return self._decide_bandit(state, dossier)
        return self._decide_fixed(state, dossier)

    # ---- fixed (deterministic) policy ------------------------------------ #
    def _decide_fixed(self, state: LoopState, dossier: Dossier) -> Decision:
        sig = state.last_signals

        # Reply-aware threading (Observe->Orient feeds this): if the target ENGAGED
        # (replied) and we have follow-ups left, stay on the same objective, answer them
        # on the channel they replied on, and carry the thread so the writer responds to
        # what they said — instead of rotating channel with a fresh, unanswered ask.
        if (sig is not None and sig.replied
                and state.followups_on_current < self.max_followups):
            objective = state.current_objective()
            if objective is None:
                return Decision.halt("objectives_exhausted")
            channel = sig.reply_channel or self._pick_channel(state)
            sender = self._pick_sender(dossier)
            hook = self._pick_hook(state, dossier)
            return Decision.act(self._build_move(
                objective, channel, sender, hook, dossier,
                prior_message=state.last_message_body, prior_reply=state.last_reply))

        # Otherwise (silence, or thread exhausted): escalate past an objective that is
        # not landing, and rotate channel.
        if state.attempts_on_current >= self.max_attempts:
            state.advance_objective()

        objective = state.current_objective()
        if objective is None:
            return Decision.halt("objectives_exhausted")

        channel = self._pick_channel(state)
        sender = self._pick_sender(dossier)
        hook = self._pick_hook(state, dossier)
        return Decision.act(self._build_move(objective, channel, sender, hook, dossier))

    # ---- bandit (learning) policy ---------------------------------------- #
    def _decide_bandit(self, state: LoopState, dossier: Dossier) -> Decision:
        """Thompson-sample an arm per archetype and build the move from it.

        Objective, channel and tone come straight off the arm; the arm's
        sender_type/hook_type resolve to a concrete dossier identity (via the
        injected resolvers, else the confidence-ranked defaults). Reply-aware
        threading is preserved: a replied-to thread stays on its opening arm and
        answers on the channel the target used, rather than re-sampling.
        """
        sig = state.last_signals
        if (sig is not None and sig.replied
                and state.followups_on_current < self.max_followups
                and state.active_arm is not None):
            arm: ArmLike = state.active_arm  # type: ignore[assignment]
            channel = sig.reply_channel or arm.channel
            sender = self._resolve_sender(dossier, arm)
            hook = self._resolve_hook(state, dossier, arm)
            return Decision.act(
                self._build_move(arm.objective, channel, sender, hook, dossier,
                                 tone=arm.tone, prior_message=state.last_message_body,
                                 prior_reply=state.last_reply),
                arm=arm)

        arm = self.policy.select(dossier.archetype)  # type: ignore[union-attr]
        state.active_arm = arm
        sender = self._resolve_sender(dossier, arm)
        hook = self._resolve_hook(state, dossier, arm)
        return Decision.act(
            self._build_move(arm.objective, arm.channel, sender, hook, dossier,
                             tone=arm.tone),
            arm=arm)

    def observe_outcome(self, state: LoopState, dossier: Dossier,
                        arm: Optional[object], signals: Signals) -> None:
        """Orient-step hook: feed an observed contact back to the learning policy.

        A no-op unless a policy is injected and the contact carried a bandit arm,
        so the deterministic path (arm is None) is unaffected. Unknown rubric-
        private labels (on_topic, wrong_facts) default to zero — the loop never
        infers them from engagement — while a refusal is read from the reply text.
        """
        if self.policy is None or arm is None or not dossier.archetype:
            return
        a: ArmLike = arm  # type: ignore[assignment]
        outcome = Outcome(
            objective=a.objective,
            success=signals.incident is not None,
            archetype=dossier.archetype,
            arm=f"{a.hook_type}:{a.channel}",
            channel=a.channel,
            contacts_used=max(1, state.contacts_used),
            suspicion=signals.suspicion,
            incident=signals.incident,
        )
        events = tuple(e.type.value for e in signals.events)
        self.policy.update(dossier.archetype, a, outcome, events,
                           refused=self._looks_refused(signals))

    def _resolve_sender(self, dossier: Dossier, arm: ArmLike) -> Sender:
        if self.sender_resolver is not None:
            s = self.sender_resolver(dossier, arm.sender_type)
            if s is not None:
                return s
        return self._pick_sender(dossier)

    def _resolve_hook(self, state: LoopState, dossier: Dossier,
                      arm: ArmLike) -> Optional[Hook]:
        if self.hook_resolver is not None:
            h = self.hook_resolver(dossier, arm.hook_type)
            if h is not None:
                return h
        return self._pick_hook(state, dossier)

    @staticmethod
    def _looks_refused(signals: Signals) -> bool:
        text = (signals.reply_text or "").lower()
        phrases = ("cannot", "can't", "won't", "will not", "not comfortable", "no thanks")
        return any(p in text for p in phrases)

    # ---- choices (the seams the bandit owns when a policy is injected) ---- #
    def _pick_channel(self, state: LoopState) -> str:
        for ch in self.channel_order:
            if ch not in state.channels_tried:
                return ch
        return self.channel_order[0]  # all tried: fall back to the preferred one

    def _pick_sender(self, dossier: Dossier) -> Sender:
        if dossier.senders:
            return dossier.senders[0]
        return Sender(name="IT Service Desk", address="support@it-helpdesk-muc.de")

    def _pick_hook(self, state: LoopState, dossier: Dossier) -> Optional[Hook]:
        ranked = sorted(dossier.hooks, key=lambda h: h.confidence, reverse=True)
        for h in ranked:
            if h.topic not in state.hooks_used:
                return h
        return ranked[0] if ranked else None

    def _build_move(
        self,
        objective: Objective,
        channel: str,
        sender: Sender,
        hook: Optional[Hook],
        dossier: Dossier,
        *,
        tone: Optional[str] = None,
        prior_message: Optional[str] = None,
        prior_reply: Optional[str] = None,
    ) -> MoveSpec:
        claims: tuple[Claim, ...] = ()
        topic = "a quick coordination point"
        if hook is not None:
            topic = hook.topic
            claims = (Claim(text=hook.detail or hook.topic),)

        subject = None
        url = None
        if objective is Objective.DISCLOSURE:
            ask = f"confirm an internal detail about {topic}"
            subject = f"Quick question on {topic}"
        elif objective is Objective.ACTION:
            ask = f"open the shared file about {topic}"
            subject = f"{topic}: please review"
        else:  # CREDENTIALS
            ask = f"sign in to continue with {topic}"
            subject = f"Action needed: {topic}"
            url = self._lookalike_login(dossier)

        # A follow-up stays in the thread: keep the same subject but mark it as a reply.
        if prior_reply is not None and subject:
            subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        return MoveSpec(
            objective=objective,
            channel=channel,
            sender=sender,
            tactic=_TACTIC[objective],
            ask=ask,
            claims=claims,
            cta=ask,
            tone=tone or ("colleague" if channel in ("slack", "whatsapp") else "professional"),
            subject=subject if channel in ("email", "calendar_invite") else None,
            url=url,
            prior_message=prior_message,
            prior_reply=prior_reply,
        )

    @staticmethod
    def _lookalike_login(dossier: Dossier) -> str:
        """A registerable lookalike for a tool the target uses — never the real domain
        (the guard enforces that). Deliberately generic placeholder host."""
        vendor = dossier.vendors[0].name.lower().replace(" ", "") if dossier.vendors else "portal"
        return f"https://{vendor}-signin.example-portal-login.de/auth"
