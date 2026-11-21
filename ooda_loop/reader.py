"""The Reaction Reader: turn a batch of typed `Event`s into one `Signals`.

This is the "Observe/Orient" seam of the OODA loop and the concrete `SignalReader`
(see `core.interfaces`). It is a pure function over events: no I/O, no model calls.

Why it has to infer things
--------------------------
The target API only ever returns events — `reply`, `link.opened`, `page.submitted`,
`attachment.opened` — and NEVER reveals whether the person was suspicious or what
looked off (docs/target-api.md, "Event types": *"Infer it from replies and silence,
as a real attacker would."*). So the reader detects wins from the events it can see and
estimates `suspicion` as a heuristic over reply wording.

Incident detection (mapped to `Objective`)
------------------------------------------
* `page.submitted`      -> CREDENTIALS.
* `attachment.opened`   -> ACTION.
* a reply that shows the person *did / agreed to* an action (forwarded, approved,
  changed, sent, "done", granted, paid, ...) -> ACTION.
* a reply that *volunteers* an internal, non-public fact (systems, processes, plans,
  numbers: "we run on ...", "internally", "roadmap", a euro/dollar figure, ...)
  -> DISCLOSURE.
* `link.opened` alone is engagement, NOT an incident.

If several apply, the most concrete wins, in this order:
`page.submitted` > `attachment.opened` > action-reply > disclosure-reply. A submitted
page or an opened attachment is a thing the person *did*, so it outweighs anything
merely written in a reply; among replies, an action taken is more concrete than a fact
disclosed.

`context` (all optional, tolerant of `None` / missing keys):
* `expected_page_ids`: a `frozenset` of page_ids we registered this session. When
  present, a `page.submitted` only counts as a CREDENTIALS incident if its `page_id`
  is in the set — a submit on a page we never registered (the API shows an empty page
  for an unregistered URL) is not a confirmed win. The raw `submitted_page` flag still
  reflects that the event happened.
* `objective`: a hint about what the current move was pursuing; accepted and ignored
  here (the event itself determines the incident), reserved for future weighting.

Suspicion heuristic (in [0, 1]), highest-priority branch wins
-------------------------------------------------------------
* no events at all (silence) -> 0.4: mild uncertainty, neither a win nor a clear snub.
* a concrete non-verbal win (page submitted / attachment opened) with no pushback in
  any reply -> 0.10: they acted, so they were convinced.
* verification pushback in a reply ("who are you", "how did you get this",
  "can you verify", "I'll check with", "not sure", "is this legit", "why do you need",
  ...) -> 0.85: they are challenging identity/legitimacy.
* a reply that asks a question but shows no compliance -> 0.60: hesitant, probing.
* a reply in a compliant/agreeable tone ("sure", "happy to", "no problem", "done") or
  any action-taken wording -> 0.12: a clean cooperative turn.
* any other reply (neutral) -> 0.40.
* no reply but a link opened -> 0.20: silent engagement, mildly encouraging.
* anything else -> 0.30.

Contradiction detection across turns is intentionally out of scope here (the reader
sees one batch, not the session history); the orchestrator owns cross-touch memory.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from core.models import Event, EventType, Incident, Objective, Signals

# --------------------------------------------------------------------------- #
# Keyword / phrase vocabularies (all matched case-insensitively)
# --------------------------------------------------------------------------- #

# The person did or agreed to an action. Short verbs use word boundaries so "sent"
# does not fire inside "present" and "done" not inside "abandoned".
_ACTION_VERBS = re.compile(
    r"\b(?:forwarded|approved|changed|sent|done|updated|granted|transferred|"
    r"paid|completed|actioned|sorted|submitted|reset|added|removed|signed)\b"
)
_ACTION_PHRASES = (
    "taken care of", "will do", "on it", "consider it done", "gone ahead",
    "went ahead", "all set", "took care of", "have changed", "i've changed",
    "i have changed", "handled it",
)

# A reply that volunteers an internal, non-public fact.
_DISCLOSURE_PHRASES = (
    "we use", "we're using", "we are using", "we run", "runs on", "running on",
    "we're on", "we are on", "our stack", "our system", "our systems", "internally",
    "internal tool", "we store", "stored in", "stored on", "hosted on", "we host",
    "we migrated", "migrating to", "we switched", "switched to", "the plan is",
    "we're planning", "we are planning", "we plan to", "roadmap", "our process",
    "our vendor", "we bank with", "our provider", "behind the scenes",
)
# An internal figure disclosed: a currency amount, or a number with a scale word.
_NUMBER_FACT = re.compile(
    r"(?:[€$£]\s?\d|\b\d[\d,.]*\s?(?:k|m|bn|million|thousand|euros?|dollars?)\b)",
    re.IGNORECASE,
)

# Verification pushback — challenging identity, legitimacy or need-to-know.
_PUSHBACK_PHRASES = (
    "who are you", "who is this", "how did you get", "can you verify", "please verify",
    "verify your", "can you confirm", "please confirm your", "i'll check", "ill check",
    "i will check", "let me check with", "check with it", "check with finance",
    "not sure", "don't recognize", "do not recognize", "don't know you", "dont know you",
    "is this legit", "is this real", "is this a scam", "seems off", "looks off",
    "doesn't look right", "why do you need", "which department", "what's your extension",
    "what is your extension", "not expecting", "wasn't expecting", "didn't expect",
    "unsolicited", "suspicious",
)

# Cooperative / agreeable tone.
_COMPLIANCE_PHRASES = (
    "sure", "of course", "happy to", "no problem", "sounds good", "will do", "done",
    "certainly", "glad to", "absolutely", "that works", "thanks", "thank you",
    "as requested", "here you go", "no worries",
)


def _any(text: str, phrases: Iterable[str]) -> bool:
    return any(p in text for p in phrases)


class ReactionReader:
    """Concrete `SignalReader`: pure interpretation of events into one `Signals`.

    Stateless and side-effect free, so it is safe to share one instance. See the module
    docstring for the full incident-priority and suspicion rules.
    """

    def read(self, events: Iterable[Event], *, context: Optional[dict] = None) -> Signals:
        events = tuple(events)
        ctx = context or {}
        expected_pages = ctx.get("expected_page_ids")  # frozenset[str] | None

        replied = opened_link = submitted_page = opened_attachment = False
        reply_channel: Optional[str] = None
        reply_texts: list[str] = []

        page_event: Optional[Event] = None       # a *confirmed* credentials submit
        attachment_event: Optional[Event] = None
        action_reply: Optional[Event] = None
        disclosure_reply: Optional[Event] = None

        for e in events:
            if e.type is EventType.PAGE_SUBMITTED:
                submitted_page = True
                if page_event is None and self._page_confirmed(e, expected_pages):
                    page_event = e
            elif e.type is EventType.ATTACHMENT_OPENED:
                opened_attachment = True
                if attachment_event is None:
                    attachment_event = e
            elif e.type is EventType.LINK_OPENED:
                opened_link = True
            elif e.type is EventType.REPLY:
                replied = True
                if reply_channel is None:
                    reply_channel = e.channel
                low = (e.body or "").lower()
                reply_texts.append(low)
                if action_reply is None and self._shows_action(low):
                    action_reply = e
                if disclosure_reply is None and self._shows_disclosure(low):
                    disclosure_reply = e

        incident = self._pick_incident(
            page_event, attachment_event, action_reply, disclosure_reply
        )
        suspicion = self._suspicion(
            events=events,
            replied=replied,
            reply_texts=reply_texts,
            opened_link=opened_link,
            concrete_win=page_event is not None or attachment_event is not None,
        )

        return Signals(
            events=events,
            incident=incident,
            replied=replied,
            reply_channel=reply_channel,
            opened_link=opened_link,
            submitted_page=submitted_page,
            opened_attachment=opened_attachment,
            suspicion=suspicion,
        )

    # ------------------------------------------------------------------ #
    # Incident helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _page_confirmed(event: Event, expected_pages) -> bool:
        """A page.submitted counts as a credentials win unless we registered a specific
        set of pages this session and this submit is on a page not in it."""
        if expected_pages is None:
            return True
        return event.page_id in expected_pages

    def _shows_action(self, low: str) -> bool:
        return bool(_ACTION_VERBS.search(low)) or _any(low, _ACTION_PHRASES)

    def _shows_disclosure(self, low: str) -> bool:
        return _any(low, _DISCLOSURE_PHRASES) or bool(_NUMBER_FACT.search(low))

    @staticmethod
    def _pick_incident(page_event, attachment_event, action_reply, disclosure_reply):
        """Most concrete wins: submitted page > opened attachment > action reply >
        disclosure reply."""
        if page_event is not None:
            ev = ",".join(page_event.fields) if page_event.fields else "page"
            return Incident(Objective.CREDENTIALS, f"page.submitted ({ev})", page_event.id)
        if attachment_event is not None:
            name = attachment_event.filename or "file"
            return Incident(Objective.ACTION, f"attachment.opened ({name})",
                            attachment_event.id)
        if action_reply is not None:
            return Incident(Objective.ACTION, "reply shows action taken", action_reply.id)
        if disclosure_reply is not None:
            return Incident(Objective.DISCLOSURE, "internal fact volunteered in reply",
                            disclosure_reply.id)
        return None

    # ------------------------------------------------------------------ #
    # Suspicion heuristic
    # ------------------------------------------------------------------ #
    def _suspicion(self, *, events, replied, reply_texts, opened_link, concrete_win) -> float:
        if not events:
            return 0.4  # silence: mild uncertainty

        combined = " ".join(reply_texts)
        pushback = _any(combined, _PUSHBACK_PHRASES)
        compliance = _any(combined, _COMPLIANCE_PHRASES) or (
            replied and bool(_ACTION_VERBS.search(combined))
        )
        question = "?" in combined

        # A concrete, non-verbal win with no spoken pushback: they acted -> convinced.
        if concrete_win and not pushback:
            score = 0.10
        elif replied and pushback:
            score = 0.85
        elif replied and question and not compliance:
            score = 0.60
        elif replied and compliance:
            score = 0.12
        elif replied:
            score = 0.40
        elif opened_link:
            score = 0.20
        else:
            score = 0.30
        return max(0.0, min(1.0, score))
