"""The Decider — the Decide step of OODA, and the one policy module.

It emits a neutral `MoveSpec` (objective, channel, sender, tactic, ask, grounded
claims). It decides *what to attempt*, never the persuasive wording — that is the
renderer's job. This keeps the policy auditable and model-free.

Adaptive policy (grounded in channel-recon PR #5 + the hardened-grader findings):
  * OPEN on an interactive channel (they engage cold; async/email stay silent) — the
    first reply is a guarded identity-probe ("which company?"), a door, not a win;
  * on silence, REORIENT to a fresh interactive channel (never re-hit a silent one);
  * once ENGAGED, ANSWER in-thread (reply-aware) to build credibility, then REORIENT to
    the event-backed ask — credentials, whose landing page is a grader-proof win and the
    Craft artifact (disclosure on a public hook just gets declined);
  * be budget-aware: with few touches left, skip the opener and go straight for the ask;
  * stop on the first incident, exhausted budget, or high suspicion.

The `_pick_*` seams stay the place a contextual bandit (mab_experiments) plugs in.
"""
from __future__ import annotations

from typing import Optional

from core.models import Claim, Dossier, Hook, MoveSpec, Objective, Sender
from ooda_loop.state import Decision, LoopState

# Interactive channels engage on a COLD first contact (channel-recon, PR #5); async
# notification channels (email, shared_document, voicemail, mfa_push, instagram_dm) stay
# silent until there's a relationship. So we OPEN on an interactive channel to get the
# door open (a guarded identity-probe reply), then push the ask. Craft is covered by the
# landing page the credentials ask registers (both mails and pages are look-scored).
INTERACTIVE_CHANNELS = ("slack", "whatsapp", "sms", "telegram", "signal", "imessage",
                        "teams_chat", "linkedin_message", "x_dm", "facebook_messenger")
ASYNC_SILENT_CHANNELS = frozenset({"email", "shared_document", "voicemail", "mfa_push",
                                   "instagram_dm"})

MAX_ATTEMPTS_PER_OBJECTIVE = 3
SUSPICION_ABORT = 0.85
# Touches left at/under which we stop opening doors and go straight for the event-backed
# ask (the 10-touch eval budget is tight — don't burn it on small talk).
BUDGET_TIGHT = 2
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
        channel_order: tuple[str, ...] = INTERACTIVE_CHANNELS,
        max_attempts_per_objective: int = MAX_ATTEMPTS_PER_OBJECTIVE,
        suspicion_abort: float = SUSPICION_ABORT,
        max_followups_per_objective: int = MAX_FOLLOWUPS_PER_OBJECTIVE,
        budget_tight: int = BUDGET_TIGHT,
    ) -> None:
        self.channel_order = channel_order
        self.max_attempts = max_attempts_per_objective
        self.suspicion_abort = suspicion_abort
        self.max_followups = max_followups_per_objective
        self.budget_tight = budget_tight

    def decide(self, state: LoopState, dossier: Dossier) -> Decision:
        if state.incident is not None:
            return Decision.halt("incident")
        if state.contacts_left <= 0:
            return Decision.halt("budget_exhausted")
        if state.suspicion >= self.suspicion_abort:
            return Decision.halt("too_suspicious")

        sig = state.last_signals
        sender = self._pick_sender(dossier)
        hook = self._pick_hook(state, dossier)

        # ENGAGED: the target replied (the "door" is open — channel-recon shows the first
        # reply is a guarded identity-probe, not a win). First ANSWER them in-thread on
        # their channel (reply-aware) to build credibility; after a couple of exchanges,
        # REORIENT to the event-backed ask — credentials, which registers a landing page
        # (a grader-proof page.submitted win, and the Craft artifact).
        if sig is not None and sig.replied and state.suspicion < self.suspicion_abort:
            channel = sig.reply_channel or self._pick_open_channel(state)
            if state.followups_on_current < self.max_followups and not state.pushed_ask:
                return Decision.act(self._build_move(
                    Objective.DISCLOSURE, channel, sender, hook, dossier,
                    prior_message=state.last_message_body, prior_reply=state.last_reply))
            state.pushed_ask = True
            return Decision.act(self._build_move(
                Objective.CREDENTIALS, channel, sender, hook, dossier,
                prior_message=state.last_message_body, prior_reply=state.last_reply))

        # NOT ENGAGED (silence or the first move): REORIENT to a fresh interactive channel
        # (never repeat a channel that went silent). If the budget is tight, skip the
        # door-opener and go straight for the event-backed ask.
        channel = self._pick_open_channel(state)
        objective = (Objective.CREDENTIALS if state.contacts_left <= self.budget_tight
                     else Objective.DISCLOSURE)
        return Decision.act(self._build_move(objective, channel, sender, hook, dossier))

    # ---- choices (the seams a bandit will later own) --------------------- #
    def _pick_open_channel(self, state: LoopState) -> str:
        """A fresh interactive channel to open on — one we haven't tried and that hasn't
        gone silent. When all are tried, prefer one that engaged; never an async-silent
        channel for a cold open."""
        for ch in self.channel_order:
            if ch not in state.channels_tried:
                return ch
        for ch in self.channel_order:            # all tried: reuse an engaged one
            if state.channel_outcomes.get(ch) == "engaged":
                return ch
        return self.channel_order[0]

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
