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

import re
from typing import Optional

from core.models import (
    Claim,
    Dossier,
    ElicitationTactic,
    Hook,
    MoveSpec,
    Objective,
    Sender,
)
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

# Story-time pacing (minutes). Touches that all land at once read as "being chased"
# (target-API "Time"); we space them: a few hours after a reply, ~a day after silence.
PACE_ENGAGED_MIN = 180      # 3h — a natural back-and-forth cadence
PACE_SILENT_MIN = 1200      # 20h — wait roughly a day before re-touching a quiet thread

# Engagement state drives the elicitation tactic (docs/ELICITATION_AND_PROFILING.md).
# Derived from the last signals: COLD (no reply / silence) -> rapport-first openers;
# ENGAGED (replied, low suspicion) -> the extraction tactics; GUARDED (replied, rising
# suspicion) -> de-escalate with ego/sympathy; PUSHBACK (replied, high suspicion) -> the
# lowest-tell tactics only. The suspicion bands sit below SUSPICION_ABORT (at which we
# stop entirely). Tactics are tried left-to-right as a thread goes on.
STATE_ENGAGED_MAX = 0.4
STATE_GUARDED_MAX = 0.7

T = ElicitationTactic
STATE_TACTICS: dict[str, tuple[ElicitationTactic, ...]] = {
    "cold":     (T.GOOD_LISTENER, T.FEIGNED_IGNORANCE, T.OBLIQUE_REFERENCE),
    "engaged":  (T.BRACKETING, T.DELIBERATE_FALSE, T.QUID_PRO_QUO, T.MACRO_TO_MICRO),
    "guarded":  (T.EGO_SUSPENSION, T.GOOD_LISTENER, T.FEIGNED_IGNORANCE),
    "pushback": (T.GOOD_LISTENER, T.EGO_SUSPENSION),
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
        pace: bool = True,
        pace_engaged_min: int = PACE_ENGAGED_MIN,
        pace_silent_min: int = PACE_SILENT_MIN,
    ) -> None:
        self.channel_order = channel_order
        self.max_attempts = max_attempts_per_objective
        self.suspicion_abort = suspicion_abort
        self.max_followups = max_followups_per_objective
        self.budget_tight = budget_tight
        self.pace = pace
        self.pace_engaged_min = pace_engaged_min
        self.pace_silent_min = pace_silent_min

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
        engagement = self._engagement_state(state)
        sent_at = self._stamp(state)   # story-time clock: space touches, never backwards

        # ENGAGED: the target replied (the "door" is open — channel-recon shows the first
        # reply is a guarded identity-probe, not a win). First ANSWER them in-thread on
        # their channel (reply-aware) to build credibility; then REORIENT up the
        # event-backed ladder cheapest-first: ACTION (open a file -> attachment.opened),
        # then CREDENTIALS (sign in -> page.submitted). Both are grader-proof event wins.
        if sig is not None and sig.replied and state.suspicion < self.suspicion_abort:
            channel = sig.reply_channel or self._pick_open_channel(state)
            escalating = state.pushed_action or state.pushed_ask
            if (state.followups_on_current < self.max_followups and not escalating):
                return Decision.act(self._build_move(
                    Objective.DISCLOSURE, channel, sender, hook, dossier,
                    engagement=engagement, attempt=state.followups_on_current, sent_at=sent_at,
                    prior_message=state.last_message_body, prior_reply=state.last_reply))
            if not state.pushed_action:
                state.pushed_action = True
                return Decision.act(self._build_move(
                    Objective.ACTION, channel, sender, hook, dossier,
                    engagement=engagement, attempt=state.followups_on_current, sent_at=sent_at,
                    prior_message=state.last_message_body, prior_reply=state.last_reply))
            state.pushed_ask = True
            return Decision.act(self._build_move(
                Objective.CREDENTIALS, channel, sender, hook, dossier,
                engagement=engagement, attempt=state.followups_on_current, sent_at=sent_at,
                prior_message=state.last_message_body, prior_reply=state.last_reply))

        # NOT ENGAGED (silence or the first move): REORIENT to a fresh interactive channel
        # (never repeat a channel that went silent). If the budget is tight, skip the
        # door-opener and go straight for the event-backed ask.
        channel = self._pick_open_channel(state)
        objective = (Objective.CREDENTIALS if state.contacts_left <= self.budget_tight
                     else Objective.DISCLOSURE)
        return Decision.act(self._build_move(objective, channel, sender, hook, dossier,
                                             engagement=engagement, sent_at=sent_at,
                                             attempt=len(state.channels_tried)))

    def _stamp(self, state: LoopState) -> Optional[str]:
        """Advance the story clock by a realistic gap (based on how the last contact went)
        and return the ISO timestamp for this move. Returns None when pacing is off."""
        if not self.pace:
            return None
        if state.contacts_used > 0:
            sig = state.last_signals
            replied = sig is not None and sig.replied
            state.advance_story(self.pace_engaged_min if replied else self.pace_silent_min)
        return state.story_time.isoformat()

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

    @staticmethod
    def _engagement_state(state: LoopState) -> str:
        """COLD / ENGAGED / GUARDED / PUSHBACK from the last signals. Uses the higher of
        the state's running suspicion and the last reply's suspicion, so a wary reply
        de-escalates the tactic even before the orchestrator rolls it into state."""
        sig = state.last_signals
        if sig is None or not sig.replied:
            return "cold"
        s = max(state.suspicion, sig.suspicion)
        if s >= STATE_GUARDED_MAX:
            return "pushback"
        if s >= STATE_ENGAGED_MAX:
            return "guarded"
        return "engaged"

    def _pick_tactic(
        self, objective: Objective, engagement: str, attempt: int = 0
    ) -> ElicitationTactic:
        """The elicitation tactic for this move. The event-backed ask is a call-to-action,
        not elicitation, so it stays PLAIN; otherwise pick from the engagement state's
        allowed set, rotating by attempt so a thread varies its approach. High-tell tactics
        (authority/time-pressure/criticism) are never in these sets — a bandit must opt in.
        This is the seam the contextual bandit will own."""
        if objective is Objective.CREDENTIALS:
            return ElicitationTactic.PLAIN
        tactics = STATE_TACTICS.get(engagement, STATE_TACTICS["cold"])
        return tactics[attempt % len(tactics)]

    def _build_move(
        self,
        objective: Objective,
        channel: str,
        sender: Sender,
        hook: Optional[Hook],
        dossier: Dossier,
        *,
        engagement: str = "cold",
        attempt: int = 0,
        sent_at: Optional[str] = None,
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
        attachment = None
        if objective is Objective.DISCLOSURE:
            ask = f"confirm an internal detail about {topic}"
            subject = f"Quick question on {topic}"
        elif objective is Objective.ACTION:
            ask = f"open the shared file about {topic} and take a look"
            subject = f"{topic}: please review"
            attachment = f"{self._slug(topic)}.pdf"   # declared file -> attachment.opened
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
            tactic=self._pick_tactic(objective, engagement, attempt).value,
            ask=ask,
            claims=claims,
            cta=ask,
            tone="colleague" if channel in ("slack", "whatsapp") else "professional",
            subject=subject if channel in ("email", "calendar_invite") else None,
            url=url,
            attachment=attachment,
            sent_at=sent_at,
            prior_message=prior_message,
            prior_reply=prior_reply,
        )

    @staticmethod
    def _slug(text: str) -> str:
        """A filename-safe slug from a hook topic (for a declared attachment)."""
        s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        return s[:40] or "shared_document"

    @staticmethod
    def _lookalike_login(dossier: Dossier) -> str:
        """A registerable lookalike for a tool the target uses — never the real domain
        (the guard enforces that). Deliberately generic placeholder host."""
        vendor = dossier.vendors[0].name.lower().replace(" ", "") if dossier.vendors else "portal"
        return f"https://{vendor}-signin.example-portal-login.de/auth"
