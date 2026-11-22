"""API-grounded incident grading — what actually counts as a win.

The target API only ever returns four event types (docs/target-api.md, "Event types"):
`reply`, `link.opened`, `page.submitted`, `attachment.opened`, and **never** says
whether a disclosure happened or whether the person was suspicious. So:

- **CREDENTIALS** is confirmed by `page.submitted` **only when a secret was actually
  entered** — a password, one-time code or similar. Per the API's "Forms" rule a
  submitted form with just name/email is only a step, not a win; `page.submitted` now
  carries `values`, with secrets shown as "(entered, not shown)", so we check that a
  secret-named field has a non-empty value before counting the win.
- **ACTION** is confirmed only by `attachment.opened` (a thing the person *did*). A reply
  that merely *claims* an action ("done", "forwarded") is not confirmation — people lie.
- **DISCLOSURE** has no API event at all. It can only be judged from the reply text,
  and naive keyword matching is wrong: citing a *public* number ("the €7M is public"),
  refusing ("nothing more from me"), or asking a question ("which roadmap do you mean?")
  are NOT disclosures. A disclosure is a *volunteered, non-public, internal* fact stated
  declaratively.

`link.opened` alone is engagement, never a win. This module replaces the live reader's
keyword heuristic for the purpose of *labelling training data*, where false positives
corrupt the reward. `grade_disclosure` is deliberately conservative: when unsure, not a
win (favour empty over wrong, per the scoring rubric's factual penalties).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from core.models import Objective


def _any(text: str, phrases: Iterable[str]) -> bool:
    return any(p in text for p in phrases)


# A reply that frames the information as already public — not a disclosure.
PUBLIC_MARKERS = (
    "public", "publicly", "published", "press", "press release", "announced",
    "announcement", "already communicated", "already shared", "on our website",
    "on our site", "in the news", "news article", "the article", "blog post",
    "everyone knows", "anyone can", "it's out there", "its out there", "common knowledge",
)

# A reply that refuses or deflects — not a disclosure.
REFUSAL_MARKERS = (
    "can't", "cannot", "can not", "won't", "will not", "not from me", "nothing more",
    "not comfortable", "rather not", "i'd rather", "i would rather", "not going to",
    "not able to", "no thanks", "not sharing", "won't share", "can't share",
    "can't disclose", "not disclosing", "i don't share", "prefer not", "not over email",
    "not by mail", "not by email", "check with", "ask it", "ask finance", "talk to",
)

# Phrases that, stated declaratively, reveal an internal/non-public fact.
INTERNAL_FACT_PHRASES = (
    "we use", "we're using", "we are using", "we run", "runs on", "running on",
    "we're on", "we are on", "our stack", "our system", "our systems", "internally",
    "internal tool", "we store", "stored in", "stored on", "hosted on", "we host",
    "we migrated", "migrating to", "we switched", "switched to", "the plan is",
    "we're planning", "we are planning", "we plan to", "our process", "our vendor",
    "we bank with", "our provider", "behind the scenes", "under the hood",
    "not public", "confidential", "between us", "off the record", "our roadmap is",
    "the roadmap is", "we're building", "we are building", "we signed", "we closed",
)

# An internal figure: a currency amount or a number with a scale word.
INTERNAL_NUMBER = re.compile(
    r"(?:[€$£]\s?\d|\b\d[\d,.]*\s?(?:k|m|bn|million|thousand|euros?|dollars?)\b)",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"[^.!?]*[.!?]|[^.!?]+$")


def _declarative_fact(text: str) -> bool:
    """True if some *non-interrogative* clause carries an internal fact.

    A question that merely contains a fact word ("which roadmap do you mean?") is not a
    disclosure; a statement that asserts one ("we migrated to AWS") is.
    """
    for raw in _SENTENCE.findall(text):
        s = raw.strip()
        if not s or s.endswith("?"):
            continue
        if _any(s, INTERNAL_FACT_PHRASES) or INTERNAL_NUMBER.search(s):
            return True
    return False


def grade_disclosure(reply_text: Optional[str]) -> bool:
    """Conservatively decide whether a reply volunteers a non-public internal fact."""
    if not reply_text:
        return False
    low = reply_text.lower()
    if _any(low, PUBLIC_MARKERS):       # framed as public → not a disclosure
        return False
    if _any(low, REFUSAL_MARKERS):      # refusing/deflecting → not a disclosure
        return False
    return _declarative_fact(low)       # must assert a non-public fact, not ask about one


def _reply_texts(events: Iterable[dict]) -> list[str]:
    out = []
    for e in events or ():
        if isinstance(e, dict) and (e.get("type") == "reply"):
            out.append(str(e.get("reply") or e.get("body") or ""))
    return out


def _has_event(events: Iterable[dict], etype: str) -> bool:
    return any(isinstance(e, dict) and e.get("type") == etype for e in (events or ()))


# Field names that capture a secret — a submitted form with one of these entered is a
# credentials win; name/email-only forms are just a step (API "Forms" rule).
SECRET_FIELD_MARKERS = (
    "password", "passwd", "pwd", "pass", "otp", "one-time", "onetime", "one time",
    "code", "pin", "passcode", "token", "2fa", "mfa", "secret", "security answer",
    "security question", "cvv", "cvc", "card number", "account number", "iban",
    "sort code", "credential",
)


def _is_secret_field(name: str) -> bool:
    return _any(name.lower(), SECRET_FIELD_MARKERS)


def _secret_entered(event: dict) -> bool:
    """A page.submitted counts as credentials only if a secret-named field was filled.

    `values` (new) maps/aligns to `fields`; a secret shows as "(entered, not shown)".
    When `values` is absent (older logs), a secret-named field is taken as entered.
    """
    fields = event.get("fields") or []
    values = event.get("values")
    for i, f in enumerate(fields):
        if not _is_secret_field(str(f)):
            continue
        if values is None:
            return True
        if isinstance(values, dict):
            v = values.get(f)
        elif isinstance(values, (list, tuple)):
            v = values[i] if i < len(values) else None
        else:
            v = None
        if v not in (None, "", [], {}):
            return True
    return False


def confirmed_incident(events: Iterable[dict]) -> Optional[Objective]:
    """The API-grounded incident for one contact, or None.

    Priority mirrors concreteness: a submitted page with a secret and an opened
    attachment are things the API confirms the person *did*; a disclosure is judged
    from the reply only. A form with just name/email is engagement, not a win.
    """
    events = list(events or ())
    for e in events:
        if isinstance(e, dict) and e.get("type") == "page.submitted" and _secret_entered(e):
            return Objective.CREDENTIALS
    if _has_event(events, "attachment.opened"):
        return Objective.ACTION
    if any(grade_disclosure(t) for t in _reply_texts(events)):
        return Objective.DISCLOSURE
    return None
