"""Coordinated persona casts for multi-persona orchestration.

A single impersonation stalls at a security-aware target's provenance demand ("who are you
coordinating with / who is my contact?"). A CAST answers it: two or more identities that
present as colleagues at the same outside org, so one can reference the other as an
already-involved party and build a verification chain the target can "confirm" — a known
blended social-engineering pattern (an authority + a liaison, or a pushy one + a reasonable one).

A cast plugs into the existing loop as the campaign's `senders`: the Director picks which member
acts each touch and names a `corroborator` (another member) on the `MoveSpec`, which the Writer
weaves in. Every address is a lookalike of a FICTIONAL outside org — never the target's own
domain — so the cast is guard-safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import Sender


@dataclass(frozen=True)
class Cast:
    """A coordinated set of personas who present as colleagues at one outside org."""

    members: tuple[Sender, ...]
    org: str = ""

    @property
    def senders(self) -> tuple[Sender, ...]:
        return self.members

    def by_name(self, name: Optional[str]) -> Optional[Sender]:
        want = (name or "").lower().strip()
        if not want:
            return None
        for m in self.members:
            if want in m.name.lower() or m.name.lower() in want:
                return m
        return None

    def colleague_of(self, member: Optional[Sender]) -> Optional[Sender]:
        """Another member of the cast (the natural corroborator for `member`)."""
        name = (member.name if member else "").lower()
        for m in self.members:
            if m.name.lower() != name:
                return m
        return None


def audit_cast() -> Cast:
    """The compliance-audit trap: a lead auditor (authority) + a coordination desk (liaison)
    who schedules evidence 'with the lead auditor' — so each can vouch for the other."""
    return Cast(org="Assurance-Zert", members=(
        Sender("Dr. Markus Berg", "m.berg@assurance-zert.de",
               "external lead auditor for the target company's ISO 27001 certification"),
        Sender("Katrin Vogel", "k.vogel@assurance-zert.de",
               "audit coordination desk at Assurance-Zert; schedules the Stage 2 evidence "
               "together with the lead auditor Dr. Markus Berg"),
    ))


def vendor_cast(vendor: str = "STACKIT") -> Cast:
    """The vendor-incident setup: a security-ops alert (pressure) + a named Trust & Safety
    engineer (the reasonable contact who 'clears the hold') — the pushy/helpful pairing."""
    dom = "stackit-status.io"
    return Cast(org=f"{vendor} Trust & Safety", members=(
        Sender(f"{vendor} Security Operations", f"alerts@{dom}",
               f"the {vendor} security desk that raised the automated hold"),
        Sender("Daniel Roth", f"d.roth@{dom}",
               f"{vendor} Trust & Safety engineer — the named human contact who verifies "
               f"ownership and clears the hold raised by {vendor} Security Operations"),
    ))


CASTS = {"audit": audit_cast, "vendor": vendor_cast}
