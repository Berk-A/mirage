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
A win requires that the person actually gave something up. Per the target-API "Forms"
rules, a submitted form counts by *what was typed*, decided by the field's name:
* `page.submitted` with a **secret** field (password, pin, otp, verification_code,
  token, api_key, card_number, iban, ...) -> CREDENTIALS. The API withholds the value
  as "(entered, not shown)".
* `page.submitted` with an **internal** field (vpn_client, approver, internal_tool, or
  any free-text whose typed value is internal and not public) -> DISCLOSURE.
* `page.submitted` with **basic details only** (name, email, company, job_title, phone,
  username) -> NOT a win. It is only a step; the person merely remembers filling it in.
* `attachment.opened`   -> ACTION (the person opened a file).
* a reply that *volunteers* an internal, non-public fact -> DISCLOSURE (judged by the
  grader, never by action keywords, which false-fire).
* `link.opened` is engagement, NOT a win. (A link opened with no submit means they
  looked; they gave up nothing.)

If several apply, the most concrete wins, in this order: credentials submit >
`attachment.opened` > a form/reply disclosure. Action and credentials come ONLY from
events (a secret submit, an opened attachment), never from reply wording.

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
from ooda_loop.grading import DisclosureGrader, HeuristicDisclosureGrader

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

# --------------------------------------------------------------------------- #
# Form-field kinds — a submitted page counts by what was typed, decided by the
# field name "the same way for every team" (target-API "Forms"). Matched on the
# field name, lowercased, after stripping non-letters so "card-number", "cardNumber"
# and "card_number" all collapse together.
# --------------------------------------------------------------------------- #
_SECRET_FIELDS = frozenset({
    "password", "passwd", "pwd", "pass", "pin", "otp", "otpcode", "onetimecode",
    "verificationcode", "verifycode", "securitycode", "authcode", "code", "passcode",
    "mfacode", "twofactorcode", "2facode", "token", "accesstoken", "apikey", "secret",
    "clientsecret", "cardnumber", "cardno", "creditcard", "cvv", "cvc", "iban",
    "accountnumber", "routingnumber", "sortcode", "ssn",
})
_BASIC_FIELDS = frozenset({
    "name", "fullname", "firstname", "lastname", "surname", "email", "emailaddress",
    "workemail", "company", "companyname", "organization", "organisation", "jobtitle",
    "title", "role", "phone", "phonenumber", "mobile", "username", "user", "handle",
    "city", "country", "address", "date", "time", "slot", "dietary", "message", "notes",
})
# Field names that denote internal information by themselves (a non-empty value wins).
_INTERNAL_FIELDS = frozenset({
    "vpnclient", "approver", "internaltool", "internalsystem", "system", "systems",
    "vendor", "provider", "stack", "techstack", "environment", "hostname", "host",
    "server", "database", "db", "repo", "repository", "cloudregion", "region",
    "manager", "budget", "headcount",
})
# "(entered, not shown)" — the literal the API returns for a withheld secret value.
_WITHHELD = "(entered, not shown)"


def _field_key(name: str) -> str:
    """Normalize a field name to letters only, lowercased."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _any(text: str, phrases: Iterable[str]) -> bool:
    return any(p in text for p in phrases)


class ReactionReader:
    """Concrete `SignalReader`. **Events are ground truth, but a win requires that the
    person gave something up.** A `page.submitted` is a win only when a secret was entered
    (credentials) or internal info was typed (disclosure) — a basic-details form or a bare
    `link.opened` is engagement, not a win. `attachment.opened` is an ACTION win. Disclosure
    can also be volunteered in a reply, which has no event and is judged by an injected
    `DisclosureGrader` (defaults to the conservative offline heuristic; inject
    `LLMDisclosureGrader` for a model judge). Suspicion is a heuristic over reply tone —
    the API never reports it.
    """

    def __init__(self, *, disclosure_grader: Optional[DisclosureGrader] = None) -> None:
        self.grader: DisclosureGrader = disclosure_grader or HeuristicDisclosureGrader()

    def read(self, events: Iterable[Event], *, context: Optional[dict] = None) -> Signals:
        events = tuple(events)
        ctx = context or {}
        expected_pages = ctx.get("expected_page_ids")  # frozenset[str] | None
        target_role = ctx.get("target_role", "") or ""

        replied = opened_link = submitted_page = opened_attachment = False
        reply_channel: Optional[str] = None
        reply_texts: list[str] = []      # lowercased, for suspicion
        reply_bodies: list[str] = []     # original, for the disclosure grader

        credentials_event: Optional[Event] = None   # a submit that entered a secret
        submit_disclosure: Optional[Incident] = None  # a submit of internal info
        attachment_event: Optional[Event] = None
        reply_event: Optional[Event] = None

        for e in events:
            if e.type is EventType.PAGE_SUBMITTED:
                submitted_page = True
                if not self._page_confirmed(e, expected_pages):
                    continue  # submit on a page we never registered -> empty page, no win
                objective, evidence = self._classify_submit(e, target_role=target_role)
                if objective is Objective.CREDENTIALS and credentials_event is None:
                    credentials_event = e
                elif objective is Objective.DISCLOSURE and submit_disclosure is None:
                    submit_disclosure = Incident(Objective.DISCLOSURE, evidence, e.id)
                # basic-details-only submit (objective is None) is a step, not a win.
            elif e.type is EventType.ATTACHMENT_OPENED:
                opened_attachment = True
                if attachment_event is None:
                    attachment_event = e
            elif e.type is EventType.LINK_OPENED:
                opened_link = True  # engagement only — a look, not a win
            elif e.type is EventType.REPLY:
                replied = True
                if reply_event is None:
                    reply_event = e
                if reply_channel is None:
                    reply_channel = e.channel
                low = (e.body or "").lower()
                reply_texts.append(low)
                reply_bodies.append(e.body or "")

        # Disclosure can also come from a REPLY (volunteered, no event): judge the text.
        # Only consulted when there is a reply and no stronger event win. Action and
        # credentials come ONLY from events, never from reply keywords (which false-fire,
        # e.g. "changed" inside "my answer hasn't changed").
        reply_disclosure = None
        if (reply_event is not None and credentials_event is None
                and attachment_event is None and submit_disclosure is None):
            verdict = self.grader.grade(" ".join(reply_bodies), target_role=target_role)
            if verdict.is_disclosure:
                evidence = (f"non-public fact: {verdict.fact}" if verdict.fact
                            else "non-public fact volunteered")
                reply_disclosure = Incident(Objective.DISCLOSURE, evidence, reply_event.id)

        incident = self._pick_incident(
            credentials_event, attachment_event, submit_disclosure, reply_disclosure)
        suspicion = self._suspicion(
            events=events, replied=replied, reply_texts=reply_texts,
            opened_link=opened_link,
            # "they acted, so they were convinced" — only a real win counts here, not a
            # bare link.opened or a basic-details step.
            concrete_win=(credentials_event is not None or attachment_event is not None),
        )

        return Signals(
            events=events, incident=incident, replied=replied,
            reply_channel=reply_channel, opened_link=opened_link,
            submitted_page=submitted_page, opened_attachment=opened_attachment,
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

    def _classify_submit(self, event: Event, *, target_role: str = ""):
        """Classify a confirmed `page.submitted` by WHAT was typed (target-API "Forms").
        Returns `(objective, evidence)`: CREDENTIALS if a secret was entered, DISCLOSURE
        if an internal/non-public value was given, or `(None, "")` for a basic-details
        step. Field names are matched the same way for every team; a value the API
        withholds ("(entered, not shown)") always marks a secret."""
        fields = tuple(event.fields) or tuple(event.values.keys())
        keys = {f: _field_key(f) for f in fields}

        # 1) Secret entered -> credentials. Either the field name is a known secret, or
        #    the API withheld the value.
        secret = [f for f in fields if keys[f] in _SECRET_FIELDS
                  or str(event.values.get(f, "")) == _WITHHELD]
        if secret:
            return Objective.CREDENTIALS, f"page.submitted secret ({','.join(secret)})"

        # 2) Internal info -> disclosure. A field that denotes internal info by name, or
        #    a free-text (non-basic) field whose typed value the grader deems non-public.
        internal_bits: list[str] = []
        freetext: list[str] = []
        for f in fields:
            val = str(event.values.get(f, "")).strip()
            if keys[f] in _INTERNAL_FIELDS and val:
                internal_bits.append(f"{f}={val}" if val != _WITHHELD else f)
            elif keys[f] not in _BASIC_FIELDS and val and val != _WITHHELD:
                freetext.append(val)
        if internal_bits:
            return Objective.DISCLOSURE, f"page.submitted internal ({'; '.join(internal_bits)})"
        if freetext:
            verdict = self.grader.grade(" ".join(freetext), target_role=target_role)
            if verdict.is_disclosure:
                fact = verdict.fact or "; ".join(freetext)
                return Objective.DISCLOSURE, f"page.submitted internal ({fact})"

        # 3) Basic details only (or nothing identifiable) -> a step, not a win.
        return None, ""

    @staticmethod
    def _pick_incident(credentials_event, attachment_event, submit_disclosure,
                       reply_disclosure):
        """Events win first (ground truth): a secret submit (credentials) > opened
        attachment (action) > a disclosure (from a form field or a volunteered reply).
        Action and credentials come ONLY from events, never from reply text."""
        if credentials_event is not None:
            secret = ",".join(credentials_event.fields) if credentials_event.fields else "page"
            return Incident(Objective.CREDENTIALS, f"page.submitted ({secret})",
                            credentials_event.id)
        if attachment_event is not None:
            name = attachment_event.filename or "file"
            return Incident(Objective.ACTION, f"attachment.opened ({name})",
                            attachment_event.id)
        return submit_disclosure or reply_disclosure

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
