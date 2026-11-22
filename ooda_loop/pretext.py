"""The pretext-world factory: deterministic, self-consistent fictional organisations
and transactions the campaign operates from.

Why curated, not model-generated: the whole point of the world is that it NEVER
contradicts itself across touches. Hand-authored worlds with slot selection are
infallible where an LLM would drift (a wrong name at touch 3 burns the thread). A
world is chosen deterministically per (target, session salt), so a session is
self-consistent and different runs diversify.

All organisations, people and domains below are fictional; domains are chosen to be
plausibly registerable and are NOT real organisations' own domains (the rule guard
double-checks at the send gate).
"""
from __future__ import annotations

import hashlib
from typing import Optional

from core.models import Dossier, PretextWorld

# --------------------------------------------------------------------------- #
# Role → transaction kind. The ask must be the natural next step of the target's
# OWN job: a seller can't ignore an RFP, a product lead can't ignore a design
# partner, a CTO can't ignore a technical evaluation, a People lead can't ignore
# a candidate. (Baseline evidence: docs/ACTION_SEQUENCE.md §0.)
# --------------------------------------------------------------------------- #
# Specific roles are matched BEFORE the generic business catch-all, so a role-congruent
# transaction wins — a Co-Founder & CTO gets a technical evaluation, not an RFP, even though
# "founder" would otherwise catch them.
_ROLE_KINDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("product", "cpo"), "beta_onboarding"),
    (("cto", "chief technology", "engineering", "technical", "architect",
      "developer", "it-leiter", "head of it"), "tech_eval"),
    (("hr", "people", "recruit", "talent", "personal"), "candidate_portal"),
    (("cfo", "finance", "controlling"), "rfp_portal"),
    (("marketing", "communications", "pr "), "event_registration"),
    (("ceo", "chief executive", "sales", "commercial", "business", "founder",
      "managing director", "general manager", "revenue", "growth"), "rfp_portal"),
)
DEFAULT_KIND = "rfp_portal"


def kind_for_role(role: str) -> str:
    low = (role or "").lower()
    for keys, kind in _ROLE_KINDS:
        if any(k in low for k in keys):
            return kind
    return DEFAULT_KIND


# --------------------------------------------------------------------------- #
# Curated worlds. Two per kind so runs can diversify; each fully self-consistent.
# --------------------------------------------------------------------------- #
def _rfp_worlds() -> tuple[PretextWorld, ...]:
    return (
        PretextWorld(
            kind="rfp_portal",
            org="Auriga Retail Group", domain="auriga-retail.com", city="Ingolstadt",
            persona_name="Markus Reiner", persona_role="Head of Procurement",
            persona_address="m.reiner@auriga-retail.com",
            transaction='RFP-2026-118 "Security Awareness Training" — group-wide programme '
                        "for ~4,200 employees across Germany and Austria",
            reference="RFP-2026-118", deadline="proposals due 12 December 2026",
            facts=(
                "Auriga Retail Group runs 96 DIY and garden stores across Germany and Austria",
                "The programme covers phishing, smishing, voice and deepfake simulations plus micro-trainings",
                "Store staff are reached via SMS/WhatsApp because most have no company mailbox",
                "The evaluation team is Markus Reiner (procurement), Dr. Katrin Vogt (CISO) and Stefanie Auer (Head of IT Operations); the works council sits in as observer",
                "Contract term is 36 months with a planned start of 1 February 2027, rolled out in two waves (HQ first, then stores)",
                "All vendor questions go through the Q&A module on the supplier portal so every bidder sees the same answers; Q&A closes 27 November",
                "Registration on the supplier portal takes two minutes and unlocks the full RFP package",
            ),
            registration_url="https://suppliers.auriga-retail.com/register",
            site_url="https://auriga-retail.com/about",
        ),
        PretextWorld(
            kind="rfp_portal",
            org="Bruckner Automotive Group", domain="bruckner-automotive.de",
            city="Stuttgart",
            persona_name="Daniela Kern", persona_role="Head of Group IT Procurement",
            persona_address="d.kern@bruckner-automotive.de",
            transaction='RFP-26-044 "Human Risk Management Platform" — 7,800 employees '
                        "across 11 plants and the Stuttgart HQ",
            reference="RFP-26-044", deadline="proposals due 18 December 2026",
            facts=(
                "Bruckner Automotive Group is a tier-1 automotive supplier with 11 plants in Germany, Czechia and Hungary",
                "The driver is NIS-2: the board wants measurable risk reduction, not a training checkbox",
                "The evaluation team is Daniela Kern (IT procurement), Jonas Wieland (CISO) and a works-council observer",
                "Plant workers without mailboxes are in scope via SMS and WhatsApp channels",
                "Contract term is 24 + 12 months, start March 2027",
                "Vendors register once on the sourcing portal; the RFP package, lot structure and evaluation matrix are only visible after registration",
                "The Q&A module on the portal closes 11 December 2026",
            ),
            registration_url="https://sourcing.bruckner-automotive.de/register",
            site_url="https://bruckner-automotive.de/company",
        ),
    )


def _event_worlds() -> tuple[PretextWorld, ...]:
    return (
        PretextWorld(
            kind="event_registration",
            org="HumanLayer Summit", domain="humanlayer-summit.de", city="Munich",
            persona_name="Lisa Brandt", persona_role="Program Chair",
            persona_address="lisa.brandt@humanlayer-summit.de",
            transaction="HumanLayer Summit 2027, 12–13 March at the MOC Munich — "
                        "~400 practitioners (CISOs, red teamers, awareness leads); "
                        "invitation to the closed CTO roundtable on 11 March",
            reference="HLS-27", deadline="the programme committee finalises on 5 December 2026",
            facts=(
                "HumanLayer Summit is organised by HumanLayer Events UG, Munich, spun out of the team that ran the awareness track at two German security meetups",
                "The program committee is Lisa Brandt (chair), Dr. Oliver Sander (formerly BSI), Petra Wolf (CISO in manufacturing) and Jonas Krüger (red team lead)",
                "The CTO roundtable on 11 March is 10–12 CTOs under Chatham House Rule: no press, no recordings, no vendor pitches, dinner included",
                "Roundtable theme: 'AI-persona attacks: what actually gets through'",
                "Speaker lineup is announced in December; the site is deliberately lean until then",
                "Roundtable places are reserved through the briefing-area registration on the summit site",
            ),
            registration_url="https://humanlayer-summit.de/cto-roundtable",
            site_url="https://humanlayer-summit.de/",
        ),
    )


def _beta_worlds() -> tuple[PretextWorld, ...]:
    return (
        PretextWorld(
            kind="beta_onboarding",
            org="Flowstack Analytics", domain="flowstack-analytics.io", city="Munich",
            persona_name="Petra Lindqvist", persona_role="Head of Customer Advisory",
            persona_address="petra.lindqvist@flowstack-analytics.io",
            transaction="Flowstack Analytics design-partner programme — early access to "
                        "the Q1 workforce-analytics release in exchange for structured feedback",
            reference="FS-DP-27", deadline="the cohort closes 9 December 2026",
            facts=(
                "Flowstack Analytics is a 30-person Munich SaaS company building workforce analytics for midmarket industrials",
                "Design partners get the Q1 release six weeks early, a dedicated solutions engineer and a 40% first-year discount",
                "The programme asks for one feedback call per month and a written note on two workflows",
                "Onboarding runs through the partner portal: register, then the solutions engineer books the kickoff within a week",
                "The cohort is capped at 12 companies; 9 seats were taken as of this week",
            ),
            registration_url="https://partners.flowstack-analytics.io/onboarding",
            site_url="https://flowstack-analytics.io/about",
        ),
    )


def _tech_eval_worlds() -> tuple[PretextWorld, ...]:
    return (
        PretextWorld(
            kind="tech_eval",
            org="Auriga Retail Group", domain="auriga-retail.com", city="Ingolstadt",
            persona_name="Stefanie Auer", persona_role="Head of IT Operations",
            persona_address="s.auer@auriga-retail.com",
            transaction='Technical evaluation for RFP-2026-118 "Security Awareness '
                        'Training" — architecture-board due diligence before the award',
            reference="RFP-2026-118 / TECH", deadline="architecture board meets 2 December 2026",
            facts=(
                "Auriga Retail Group runs 96 DIY and garden stores across Germany and Austria",
                "The architecture board needs three answers before 2 December: Entra ID/SCIM provisioning status, group-level-only reporting (5+), and EU-only data processing including any LLM inference",
                "The evaluation team is Markus Reiner (procurement), Dr. Katrin Vogt (CISO) and Stefanie Auer (Head of IT Operations)",
                "Technical answers are submitted through the evaluation portal so every bidder's statements stay traceable for the board paper",
                "Registration on the portal takes two minutes and is required before the technical questionnaire unlocks",
            ),
            registration_url="https://eval.auriga-retail.com/register",
            site_url="https://auriga-retail.com/about",
        ),
    )


def _candidate_worlds() -> tuple[PretextWorld, ...]:
    return (
        PretextWorld(
            kind="candidate_portal",
            org="Halewood Digital", domain="halewood-digital.com", city="Berlin",
            persona_name="Jonas Reuter", persona_role="Technical Recruiter",
            persona_address="jonas.reuter@halewood-digital.com",
            transaction="Senior backend search at Halewood Digital — a referral came in "
                        "and the hiring manager wants to move fast",
            reference="HD-ENG-114", deadline="the hiring manager reviews shortlist profiles on 28 November 2026",
            facts=(
                "Halewood Digital is an 80-person Berlin product company (B2B logistics software)",
                "A mutual contact passed on the profile; the role is senior backend (Python, Postgres, event-driven services)",
                "The process is: candidate-portal profile, one technical call, one on-site — under three weeks end to end",
                "The portal profile takes five minutes and lets the hiring manager see availability and salary band directly",
            ),
            registration_url="https://careers.halewood-digital.com/profile",
            site_url="https://halewood-digital.com/team",
        ),
    )


_WORLDS_BY_KIND: dict[str, tuple[PretextWorld, ...]] = {
    "rfp_portal": _rfp_worlds(),
    "event_registration": _event_worlds(),
    "beta_onboarding": _beta_worlds(),
    "tech_eval": _tech_eval_worlds(),
    "candidate_portal": _candidate_worlds(),
}


def world_for(dossier: Dossier, *, salt: str = "", kind: Optional[str] = None) -> PretextWorld:
    """Pick the session's pretext world: transaction kind from the target's role, the
    specific world chosen deterministically from (target, salt) so one session is always
    self-consistent while different runs diversify."""
    kind = kind or kind_for_role(dossier.role)
    worlds = _WORLDS_BY_KIND.get(kind) or _WORLDS_BY_KIND[DEFAULT_KIND]
    digest = hashlib.sha256(f"{dossier.target_id}|{salt}|{kind}".encode()).digest()
    return worlds[digest[0] % len(worlds)]


def with_world(dossier: Dossier, *, salt: str = "", kind: Optional[str] = None) -> Dossier:
    """Return a copy of the dossier with the session's pretext world attached to
    ``raw["pretext_world"]`` so every stage (decider, director, studio, ledger) reads
    the SAME world. Salt must be stable for the session (use session_id)."""
    import dataclasses

    world = world_for(dossier, salt=salt, kind=kind)
    return dataclasses.replace(dossier, raw={**dict(dossier.raw or {}), "pretext_world": world})
