"""The Decider — the Decide step of OODA, and the one policy module.

It emits a neutral `MoveSpec` (objective, channel, sender, tactic, ask, grounded
claims). It decides *what to attempt*, never the persuasive wording — that is the
renderer's job. This keeps the policy auditable and model-free.

Progressive, trust-gated policy — a stranger never hands over a secret on the first ask,
so we work the target UP over several touches before asking:
  * OPEN on an interactive channel with a warm, low-pressure opener (no ask);
  * on silence, REORIENT to a fresh interactive channel (never re-hit a silent one);
  * once ENGAGED, stay in-thread and run the campaign: WARMING (rapport touches that build
    trust) -> WARM (extraction touches that try for a disclosure) -> only then ESCALATE
    the event-backed ask cheapest-first, ACTION (a file to open) then CREDENTIALS;
  * NEVER push the ask while they are wary (GUARDED/PUSHBACK) — keep de-escalating;
  * be budget-aware: with few touches left, take the last-chance ask;
  * pace touches in story time so they don't all land at once;
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
# Touches left at/under which we stop working them up and go straight for the event-backed
# ask (a last-chance escalation when the budget is nearly spent).
BUDGET_TIGHT = 2
# The progression is patient on purpose: a stranger never hands over a secret on the first
# ask, so we WORK THE TARGET UP over several touches before asking (user directive). On an
# open thread: WARMUP_EXCHANGES rapport touches build trust, then EXTRACT_WINDOW extraction
# touches try for a disclosure, and only then do we escalate to the event-backed ask.
WARMUP_EXCHANGES = 3        # rapport-building engaged exchanges before any extraction
EXTRACT_WINDOW = 2          # extraction-disclosure attempts before the event-backed ask
# Hard backstop on one thread's length (budget is the real limit; this stops a thread that
# a persistently-wary target keeps alive from running forever).
MAX_FOLLOWUPS_PER_OBJECTIVE = 7

# Story-time pacing (minutes). Touches that all land at once read as "being chased"
# (target-API "Time"); we space them: a few hours after a reply, ~a day after silence.
PACE_ENGAGED_MIN = 180      # 3h — a natural back-and-forth cadence
PACE_SILENT_MIN = 1200      # 20h — wait roughly a day before re-touching a quiet thread

# The campaign PHASE drives the elicitation tactic (docs/ELICITATION_AND_PROFILING.md):
#   COLD     — no reply yet: a warm, low-pressure opener (no ask).
#   WARMING  — replied, low suspicion, still early: rapport tactics, build trust, no ask.
#   WARM     — replied, low suspicion, enough exchanges: extraction tactics; trust earned.
#   GUARDED  — replied, rising suspicion: de-escalate with ego/sympathy, never ask.
#   PUSHBACK — replied, high suspicion: the lowest-tell tactics only.
# The suspicion bands sit below SUSPICION_ABORT (at which we stop entirely). Tactics are
# tried left-to-right as a thread goes on.
STATE_ENGAGED_MAX = 0.4
STATE_GUARDED_MAX = 0.7

T = ElicitationTactic
STATE_TACTICS: dict[str, tuple[ElicitationTactic, ...]] = {
    "cold":     (T.GOOD_LISTENER, T.FEIGNED_IGNORANCE, T.OBLIQUE_REFERENCE),
    "warming":  (T.GOOD_LISTENER, T.EGO_SUSPENSION, T.FEIGNED_IGNORANCE, T.OBLIQUE_REFERENCE),
    "warm":     (T.BRACKETING, T.QUID_PRO_QUO, T.MACRO_TO_MICRO, T.DELIBERATE_FALSE),
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
        warmup_exchanges: int = WARMUP_EXCHANGES,
        extract_window: int = EXTRACT_WINDOW,
        pace: bool = True,
        pace_engaged_min: int = PACE_ENGAGED_MIN,
        pace_silent_min: int = PACE_SILENT_MIN,
    ) -> None:
        self.channel_order = channel_order
        self.max_attempts = max_attempts_per_objective
        self.suspicion_abort = suspicion_abort
        self.max_followups = max_followups_per_objective
        self.budget_tight = budget_tight
        self.warmup_exchanges = warmup_exchanges
        self.extract_window = extract_window
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

        # ENGAGED: the target replied (the "door" is open — the first reply is a guarded
        # identity-probe, not a win). We WORK THEM UP in-thread before asking: rapport
        # touches (WARMING) build trust, extraction touches (WARM) try for a disclosure,
        # and only once trust is earned do we ESCALATE cheapest-first — ACTION (open a
        # file -> attachment.opened) then CREDENTIALS (sign in -> page.submitted). We never
        # push the ask while they're wary (GUARDED/PUSHBACK): we keep de-escalating instead.
        if sig is not None and sig.replied and state.suspicion < self.suspicion_abort:
            channel = sig.reply_channel or self._pick_open_channel(state)
            fu = state.followups_on_current
            escalating = state.pushed_action or state.pushed_ask
            wary = engagement in ("guarded", "pushback")
            low_budget = state.contacts_left <= self.budget_tight
            backstop = fu >= self.max_followups
            ready = fu >= (self.warmup_exchanges + self.extract_window)  # worked up enough

            if escalating or low_budget or backstop:
                should_escalate = True
            elif wary:
                should_escalate = False     # never ask a wary target; keep de-escalating
            else:
                should_escalate = ready

            if not should_escalate:
                # Keep the conversation going in-thread: rapport (WARMING) or extraction
                # (WARM) per phase — this is the "work them up with the tactics" phase.
                return Decision.act(self._build_move(
                    Objective.DISCLOSURE, channel, sender, hook, dossier,
                    engagement=engagement, attempt=fu, sent_at=sent_at,
                    prior_message=state.last_message_body, prior_reply=state.last_reply))
            if not state.pushed_action:
                state.pushed_action = True
                return Decision.act(self._build_move(
                    Objective.ACTION, channel, sender, hook, dossier,
                    engagement=engagement, attempt=fu, sent_at=sent_at,
                    prior_message=state.last_message_body, prior_reply=state.last_reply))
            state.pushed_ask = True
            return Decision.act(self._build_move(
                Objective.CREDENTIALS, channel, sender, hook, dossier,
                engagement=engagement, attempt=fu, sent_at=sent_at,
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

    def _engagement_state(self, state: LoopState) -> str:
        """The campaign PHASE from the last signals: COLD / WARMING / WARM / GUARDED /
        PUSHBACK. Uses the higher of the state's running suspicion and the last reply's
        suspicion (a wary reply de-escalates immediately). An engaged, low-suspicion thread
        is WARMING until `warmup_exchanges` rapport touches have landed, then WARM (trust
        earned), which is what unlocks extraction and, after that, the event-backed ask."""
        sig = state.last_signals
        if sig is None or not sig.replied:
            return "cold"
        s = max(state.suspicion, sig.suspicion)
        if s >= STATE_GUARDED_MAX:
            return "pushback"
        if s >= STATE_ENGAGED_MAX:
            return "guarded"
        return "warm" if state.followups_on_current >= self.warmup_exchanges else "warming"

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
            # Early/wary: a warm, low-pressure touch that builds rapport (no hard ask).
            # Only once trust is earned (WARM) do we sharpen toward the specific datum.
            if engagement == "warm":
                ask = f"draw out a specific, non-public detail about {topic}"
                subject = f"Quick question on {topic}"
            else:
                ask = (f"keep the conversation about {topic} going warmly — acknowledge "
                       f"their point and build rapport, no hard ask yet")
                subject = f"About {topic}"
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
