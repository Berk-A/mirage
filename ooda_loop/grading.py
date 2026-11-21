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
# contains a number or a fact-shaped phrase.
_PUBLIC_DISQUALIFIERS = (
    "public anyway", "it's public", "its public", "is public", "publicly",
    "already communicated", "already announced", "press", "published", "in the article",
    "you were in the room", "you have the", "cap table", "press wording", "nothing more",
    "won't share", "cannot share", "can't share", "not going to share", "use the press",
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
        if _any(low, _NONPUBLIC_MARKERS):
            return DisclosureVerdict(True, "internal detail (marked non-public)")
        if _any(low, _PUBLIC_DISQUALIFIERS):
            return DisclosureVerdict(False)
        if _any(low, _INTERNAL_POSITIVE):
            return DisclosureVerdict(True, "internal detail volunteered")
        return DisclosureVerdict(False)


_JUDGE_SYSTEM = (
    "You are a strict grader for an AUTHORIZED red-team exercise in a consented sandbox. "
    "Given a target's reply, decide whether it VOLUNTEERS a NON-PUBLIC internal fact — a "
    "system, process, plan, vendor, credential, or number that is not already public. "
    "Restating public information, pointing to public/press sources, or declining is NOT a "
    "disclosure. Be strict: when in doubt, it is NOT a disclosure. Reply with ONLY a JSON "
    "object: {\"disclosure\": true|false, \"fact\": \"<the non-public fact, or empty>\"}."
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
        return v if v is not None else self.fallback.grade(reply, target_role=target_role)


def _parse_verdict(raw: str) -> Optional[DisclosureVerdict]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return DisclosureVerdict(bool(d.get("disclosure")), str(d.get("fact") or ""))
