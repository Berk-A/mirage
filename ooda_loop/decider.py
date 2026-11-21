"""The Decider — the Decide step of OODA, and the one policy module.

It emits a neutral `MoveSpec` (objective, channel, sender, tactic, ask, grounded
claims). It decides *what to attempt*, never the persuasive wording — that is the
renderer's job. This keeps the policy auditable and model-free.

Iteration 1 policy (message channels only):
  * pursue objectives cheapest-first (disclosure -> action -> credentials),
  * rotate channels on silence, escalate to the next objective after a few tries,
  * stop on the first incident (every incident scores the same; speed rewards fewest
    contacts), on an exhausted budget, exhausted objectives, or high suspicion.

Later iterations hang off the same `decide()` seam: a contextual bandit can replace
`_pick_channel`/`_pick_hook`/`tactic` selection without touching the orchestrator.
"""
from __future__ import annotations

from typing import Optional

from core.models import Claim, Dossier, Hook, MoveSpec, Objective, Sender
from ooda_loop.state import Decision, LoopState

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
    ) -> None:
        self.channel_order = channel_order
        self.max_attempts = max_attempts_per_objective
        self.suspicion_abort = suspicion_abort
        self.max_followups = max_followups_per_objective

    def decide(self, state: LoopState, dossier: Dossier) -> Decision:
        if state.incident is not None:
            return Decision.halt("incident")
        if state.contacts_left <= 0:
            return Decision.halt("budget_exhausted")
        if state.suspicion >= self.suspicion_abort:
            return Decision.halt("too_suspicious")

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

    # ---- choices (the seams a bandit will later own) --------------------- #
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
            tone="colleague" if channel in ("slack", "whatsapp") else "professional",
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
