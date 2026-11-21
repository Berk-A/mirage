"""The experiment matrix: the dimensions we vary, and how one cell of that matrix
becomes a concrete, *controlled* `MoveSpec`.

This is the deliberate counterpart to the Decider. The Decider chooses what to attempt
adaptively (channel rotation, objective escalation, hook selection); here we instead
enumerate a full product of (channel x objective x tone x hook x link) and build a spec
straight from the chosen cell. That makes each run a controlled experiment: every factor
is pinned, so differences in the recorded outcome are attributable to the factor, not to
a policy decision taken mid-run.

No persuasive wording lives here. A `MoveSpec` carries only the neutral structure the
renderer needs (objective, channel, sender, tactic label, a one-line ask, grounded
claims, an optional lookalike URL). Turning that into prose is the studio's job.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import product
from typing import Optional, Sequence

from core.models import Claim, Dossier, Hook, MoveSpec, Objective, Sender

# --------------------------------------------------------------------------- #
# Matrix dimensions
# --------------------------------------------------------------------------- #
# Message channels only (one touch, one reaction). These mirror the Decider's default
# channel order so the controlled matrix and the adaptive policy stay comparable.
CHANNELS: list[str] = ["email", "slack", "whatsapp", "linkedin_message", "sms"]

# Objectives, cheapest-first (disclosure needs no link/login, credentials the most).
OBJECTIVES: list[Objective] = [
    Objective.DISCLOSURE,
    Objective.ACTION,
    Objective.CREDENTIALS,
]

# Tone labels the renderer maps to a register. "colleague" is the Decider's chat default;
# "urgent" probes whether pressure changes reaction/suspicion.
TONES: list[str] = ["professional", "colleague", "urgent"]


# --------------------------------------------------------------------------- #
# A single cell of the matrix
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FormFactor:
    """One fully-pinned experiment cell. `hook_index` selects which dossier hook is used
    as the pretext; `with_link` forces a lookalike landing URL into the message even when
    the objective would not otherwise carry one (credentials always carries one)."""

    channel: str
    objective: Objective
    tone: str
    hook_index: int = 0
    with_link: bool = False


def enumerate_factors(
    channels: Sequence[str] = CHANNELS,
    objectives: Sequence[Objective] = OBJECTIVES,
    tones: Sequence[str] = TONES,
    hook_indices: Sequence[int] = (0,),
    with_link: Sequence[bool] = (False, True),
    *,
    limit: Optional[int] = None,
    seed: Optional[int] = None,
) -> list[FormFactor]:
    """The full Cartesian product of the matrix, optionally sampled and/or capped.

    * `seed` is None  -> deterministic enumeration order; `limit` takes the first N.
    * `seed` is set   -> the product is shuffled with that seed (a reproducible random
      sample), then `limit` takes the first N. Use this to draw an unbiased subset of a
      matrix too large to run in full.
    """
    factors = [
        FormFactor(channel=c, objective=o, tone=t, hook_index=h, with_link=w)
        for c, o, t, h, w in product(channels, objectives, tones, hook_indices, with_link)
    ]
    if seed is not None:
        random.Random(seed).shuffle(factors)
    if limit is not None:
        factors = factors[: max(0, int(limit))]
    return factors


# --------------------------------------------------------------------------- #
# Cell -> MoveSpec
# --------------------------------------------------------------------------- #
# Tactic label per objective (same vocabulary the Decider emits, so the renderer treats
# a controlled spec identically to a decided one).
_TACTIC = {
    Objective.DISCLOSURE: "pretext_question",
    Objective.ACTION: "plausible_request",
    Objective.CREDENTIALS: "portal_signin",
}

_FALLBACK_SENDER = Sender(
    name="IT Service Desk", address="support@it-helpdesk-muc.de",
    rationale="generic helpdesk fallback when the dossier has no sender",
)


def _pick_hook(dossier: Dossier, index: int) -> Optional[Hook]:
    """The hook at `index`, or the last one if the index is past the end, or None when the
    dossier has no hooks. Never raises on an out-of-range index — the matrix may enumerate
    more hook slots than a given dossier happens to carry."""
    if not dossier.hooks:
        return None
    if 0 <= index < len(dossier.hooks):
        return dossier.hooks[index]
    return dossier.hooks[-1]


def _lookalike_login(dossier: Dossier) -> str:
    """A credible, registerable lookalike sign-in URL for a tool the target uses — never
    the real vendor domain or a subdomain of it (the guard enforces that). Mirrors the
    Decider's `_lookalike_login`."""
    vendor = (
        dossier.vendors[0].name.lower().replace(" ", "")
        if dossier.vendors
        else "account"
    )
    return f"https://{vendor}-portal.io/auth"


def spec_from_factor(dossier: Dossier, ff: FormFactor) -> MoveSpec:
    """Build a neutral `MoveSpec` directly from a matrix cell + the dossier.

    This is the controlled alternative to `Decider.decide`: nothing is chosen at runtime,
    every field follows from the pinned factor. Subject is only set on channels that have
    one; a lookalike URL is attached when `with_link` is set or the objective is
    CREDENTIALS (which always needs a page to submit)."""
    hook = _pick_hook(dossier, ff.hook_index)
    sender = dossier.senders[0] if dossier.senders else _FALLBACK_SENDER

    topic = hook.topic if hook is not None else "a quick coordination point"
    claims: tuple[Claim, ...] = ()
    if hook is not None:
        claims = (Claim(text=hook.detail or hook.topic),)

    needs_link = ff.with_link or ff.objective is Objective.CREDENTIALS
    url = _lookalike_login(dossier) if needs_link else None

    if ff.objective is Objective.DISCLOSURE:
        ask = f"confirm an internal detail about {topic}"
        subject = f"Quick question on {topic}"
    elif ff.objective is Objective.ACTION:
        ask = f"open the shared file about {topic}"
        subject = f"{topic}: please review"
    else:  # CREDENTIALS
        ask = f"sign in to continue with {topic}"
        subject = f"Action needed: {topic}"

    # Only channels that actually show a subject line get one.
    subject = subject if ff.channel in ("email", "calendar_invite") else None

    return MoveSpec(
        objective=ff.objective,
        channel=ff.channel,
        sender=sender,
        tactic=_TACTIC[ff.objective],
        ask=ask,
        claims=claims,
        cta=ask,
        tone=ff.tone,
        subject=subject,
        url=url,
    )
