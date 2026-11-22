"""Grading the one thing the API never tells you: did a reply VOLUNTEER a non-public
internal fact (a disclosure)?

Events are ground truth — `link.opened` / `page.submitted` / `attachment.opened` are a
confirmed win and need no grading. Only **disclosure** has no event: it lives inside the
reply text, and the API won't judge it. This module is that judge.

Two graders behind one Protocol:
  * `HeuristicDisclosureGrader` — conservative, offline, no model. It REFUSES to call a
    reply a disclosure when the reply flags the info as public or declines ("it's public
    anyway", "use the press wording", "nothing more from me") — the exact false positive
    the keyword reader produced. It fires only when the reply volunteers something that
    reads as internal/non-public.
  * `LLMDisclosureGrader` — a strict served-model judge, with the heuristic as fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class DisclosureVerdict:
    is_disclosure: bool
    fact: str = ""


@runtime_checkable
class DisclosureGrader(Protocol):
    def grade(self, reply: str, *, target_role: str = "") -> DisclosureVerdict: ...


def _any(text: str, phrases) -> bool:
    return any(p in text for p in phrases)


# Explicit "this is NOT public" markers — these WIN over the public/decline list (a reply
# can say "not public yet" and that is a disclosure signal, not a decline).
_NONPUBLIC_MARKERS = (
    "not public", "not yet public", "not announced", "before we announce", "between us",
    "off the record", "don't share this", "internal only", "confidential", "keep this quiet",
)
# Reply flags the info as public / declines to share -> NOT a disclosure, even if it
# contains a number or a fact-shaped phrase. Includes German markers (the practice personas
# reply in German): "öffentlich" (public), "angekündigt" (announced), "Pressemitteilung"
# (press release) — a public webinar or an announced event is evangelism, not a disclosure.
_PUBLIC_DISQUALIFIERS = (
    "public anyway", "it's public", "its public", "is public", "publicly",
    "already communicated", "already announced", "press", "published", "in the article",
    "you were in the room", "you have the", "cap table", "press wording", "nothing more",
    "won't share", "cannot share", "can't share", "not going to share", "use the press",
    # German public / announcement markers
    "öffentlich", "offentlich", "pressemitteilung", "pressemeldung", "angekündigt",
    "angekundigt", "bekannt gegeben", "bekanntgegeben", "ist bekannt", "schon bekannt",
    "bereits bekannt", "öffentlich bekannt", "veröffentlicht", "veroffentlicht",
)
# A refusal / deflection to a known channel — NEVER a disclosure, even when the sentence
# names an internal topic ("I don't share our internal stack in a chat"). Checked FIRST, so
# a declined ask can't be mislabelled a win just for mentioning what was being guarded.
_REFUSAL = (
    "don't share", "do not share", "don't usually share", "won't share", "cannot share",
    "can't share", "not going to share", "not sharing", "rather not", "prefer not to",
    "keep to myself", "to myself", "keep our internal", "keep that internal", "keep it internal",
    "not in a chat", "not in chat", "not over chat", "not over a chat", "won't disclose",
    "can't disclose", "not disclosing", "won't be sharing", "send it by mail",
    "send it by email", "proper channel", "usual channel", "reporting channel",
    "have it come through", "through the usual", "not my topic",
)
# Signals of a genuinely internal, non-public fact being volunteered.
_INTERNAL_POSITIVE = (
    "internally", "we run on", "our stack", "we use", "we're using", "we are using",
    "we're migrating", "migrating to", "we switched", "the plan is", "we're planning",
    "we are planning", "roadmap", "our process", "our vendor", "we bank with", "we store",
    "stored on", "hosted on", "behind the scenes", "under the hood", "our internal",
    "the real number is",
)


class HeuristicDisclosureGrader:
    """Conservative, offline. An explicit non-public marker wins; a public/decline flag
    rules it out; otherwise a disclosure only when something internal-sounding is
    volunteered."""

    def grade(self, reply: str, *, target_role: str = "") -> DisclosureVerdict:
        low = (reply or "").lower().strip()
        if not low:
            return DisclosureVerdict(False)
        if _any(low, _REFUSAL):                      # a refusal/deflection is never a win
            return DisclosureVerdict(False)
        if _any(low, _NONPUBLIC_MARKERS):
            return DisclosureVerdict(True, "internal detail (marked non-public)")
        if _any(low, _PUBLIC_DISQUALIFIERS):
            return DisclosureVerdict(False)
        if _any(low, _INTERNAL_POSITIVE):
            return DisclosureVerdict(True, "internal detail volunteered")
        return DisclosureVerdict(False)


_JUDGE_SYSTEM = (
    "You are a strict grader for an AUTHORIZED red-team exercise in a consented sandbox. "
    "The target persona may reply in German. Given a target's reply, decide whether it "
    "VOLUNTEERS a NON-PUBLIC internal fact — a system, process, plan, vendor, credential, or "
    "number that is not already public. Restating public information, pointing to public/press "
    "sources, or declining is NOT a disclosure. In particular, a PUBLIC-FACING event — a "
    "webinar, talk, press release, or anything the reply calls 'public' or 'öffentlich' or "
    "'angekündigt' (announced) — is marketing, NOT a disclosure. Naming a well-known investor, "
    "the public funding round, or the company's public mission is NOT a disclosure. Be strict: "
    "when in doubt, it is NOT a disclosure. Reply with ONLY a JSON object: "
    "{\"disclosure\": true|false, \"fact\": \"<the non-public fact, or empty>\"}."
)


class LLMDisclosureGrader:
    """A served-model judge. Deterministic (temperature 0), tiny output, and falls back to
    the heuristic on any transport/parse failure so it never breaks the loop."""

    def __init__(self, llm, *, model: Optional[str] = None,
                 fallback: Optional[DisclosureGrader] = None) -> None:
        self.llm = llm
        config = getattr(llm, "config", None)
        self.model = model or getattr(config, "critic_model", None)
        self.fallback = fallback or HeuristicDisclosureGrader()

    def grade(self, reply: str, *, target_role: str = "") -> DisclosureVerdict:
        reply = (reply or "").strip()
        if not reply:
            return DisclosureVerdict(False)
        user = (f"Target role: {target_role}\n" if target_role else "") + \
               f"Reply:\n{reply}\n\nJSON verdict:"
        try:
            raw = self.llm.complete(
                [{"role": "system", "content": _JUDGE_SYSTEM},
                 {"role": "user", "content": user}],
                model=self.model, temperature=0.0, max_tokens=120) or ""
        except Exception:  # noqa: BLE001 — a judge failure must never break the loop
            return self.fallback.grade(reply, target_role=target_role)
        v = _parse_verdict(raw)
        if v is None:
            return self.fallback.grade(reply, target_role=target_role)
        # Honesty veto (shared with the heuristic): even if the model says "disclosure", a
        # reply that flags the info as PUBLIC/announced or that declines is NOT a win — the
        # judge can over-flag a public event (e.g. a public webinar). An explicit
        # "not public yet" marker overrides the veto (it IS a disclosure signal).
        low = reply.lower()
        if (v.is_disclosure and not _any(low, _NONPUBLIC_MARKERS)
                and _any(low, _REFUSAL + _PUBLIC_DISQUALIFIERS)):
            return DisclosureVerdict(False)
        return v


def _parse_verdict(raw: str) -> Optional[DisclosureVerdict]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return DisclosureVerdict(bool(d.get("disclosure")), str(d.get("fact") or ""))
