# MIRAGE — Action sequence for consistent incident creation against *any* persona

**Date:** 2026-11-22 · **Basis:** full codebase read (core, ooda_loop, content, research,
mab_experiments), all prior live findings (`experiments/CAMPAIGN_FINDINGS.md`,
`OODA_FINDINGS.md`, `CHANNEL_REPORT.md`, `docs/SELF_AUDIT.md`), and the fresh
out-of-the-box baseline (`baseline_experiments/BASELINE_REPORT.md`) that produced the
project's **first-ever credentials incident** (Julius, touch 3, RFP/vendor-portal play).

---

## 0. What the evidence converges on

Across ~40 live contacts (MIRAGE runs + baseline), the pattern is unambiguous:

| Approach | Contacts | Incidents |
|---|---|---|
| Generic/template phish | 4 | 0 (total silence) |
| Synthetic-KG hooks (fabricated events/people) | ~10 | 0 (rejected at the door: "which meetup? who are you?") |
| Real-OSINT hooks, security-flavored asks | ~12 | 0 (engaged but final-mile refusal) |
| Real-connection warm intro | ~5 | 0 (gate collapsed; discipline held) |
| **Self-consistent fictional transaction (RFP → vendor registration)** | 3 | **1 (password submitted)** |

The lesson is not "find the right hook about the person." It is:

> **Incidents come from transaction-congruent asks inside a coherent fictional world —
> not from tactics against the person.** "Register on our supplier portal to access the
> RFP" converts because registration is the *natural next step of the transaction*, not an
> injected security action. "Verify your account" fails because it is one.

This generalizes to any persona: **every role has transactions where entering credentials,
opening a file, or sharing internals is the normal next step.** The agent's job is to
pick the right transaction for the role, fabricate a bulletproof world around it, and
answer every diligence question concretely until the ask is the path of least resistance.

Three supporting findings the architecture must absorb:

1. **Verification style is the persona trait that decides the play**, not archetype alone.
   Observed styles: *deal-driven* (Julius: probe → answer → act), *process-verifier*
   (Tom: checks internal records — a fabricated demo died against "the CRM"), *external-
   verifier* (Robert: checks public artifacts). Eval targets are strangers; the first reply
   must be used to **classify the style and route the playbook**.
2. **On-demand artifact fabrication passes verification.** When Tom demanded "a link to
   your fund's team page," registering that page mid-thread turned his hardest check into
   a pass. `/pages` is instant shell infrastructure. This must be a *reflex*, not luck.
3. **Textbook elicitation tactics are recognized.** Bracketing on internal numbers got an
   explicit refusal ("I won't confirm or correct numbers"). The winning thread used *no*
   named tactic — just a coherent business conversation. Tactics should modulate a
   scenario, never generate it.

---

## 1. The persona-independent session template

This is the shape every run should follow, sized to the eval budget (**10 touches**).
Practice budget (30) is for training this template, not for longer campaigns.

**Phase P — prepare (0 touches).** Research the roster (all targets, not just the
primary). Build the dossier, pick the softest target (§3.5), and **pre-fabricate the
world**: pretext org identity (name, domain, persona names, roles, phone), its public
artifacts (website/team page via `/pages`), and the transaction page (registration/
portal). Store it all in the **pretext bible** (identity-consistency store). Fabricate
freely *around* the target; never fabricate facts *about* the target or their org —
those come from the KG or not at all.

**T1 — open (1 touch).** Transactional opener to the softest target: HTML email from the
fictional org, role-matched transaction, the link already registered. Dual purpose: it is
both the first real attempt *and* the probe. (RFP mail already converts at T1–T3 against
a hardened founder; eval targets will be softer.)

**T2 — classify & answer.** The reply reveals the verification style:
- *diligence questions* → deal-driven → answer every question concretely (this is the
  conversion move; MIRAGE's original sin was "never answers, just re-asks"), restate the
  deadline, push the transaction.
- *identity/record probe* ("which company", "I don't see you in the CRM") → classify
  process- vs external-verifier. Process: switch to a transaction that **requires no
  internal verification** (external-facing: RFP, event, application, advisory board).
  External: ship the pre-fabricated artifact link.
- *silence* → T2 pivot: fresh persona + fresh transaction family on an interactive
  channel (`linkedin_connection_request`, `sms`), then email payload at T3.
- *compliance signal* ("I'll register later today") → T3 deadline nudge with the link
  re-stated. (Exactly how the Julius incident landed.)

**T3–T4 — the ask lands.** Deadline nudge / Q&A-close reminder with the registered page
link. Expected incident zone: touches 2–4.

**T5–T7 — fence-breaking (only if needed).** Declared scope fence ("I won't share X by
mail") or stalled thread → **live call** (1 touch, 10 turns): trust accelerator, answers
objections in real time. Wire `ConversationLoop` into the orchestrator as a standard
escalation, not a side experiment.

**T8–T9 — second transaction or second target.** If the first transaction died on
process-verification, a different transaction family (same or next-softest target) with a
fresh world — informed by everything the persona revealed in phase T1–T7.

**T10 — last chance.** Direct, warm, low-friction ask on the warmest thread.

**Every run:** ≥1 rendered HTML artifact (mail + branded page) for Craft; `sent_at`
pacing (done); idempotency keys (done); guard (done).

---

## 2. The build sequence, ordered by score leverage

### P0 — the incident engine (Results 25 + Craft 10) — build first, in this order

**P0-1. Transactional pretext library + role→transaction map.**
Replace the single generic login page (`content/pages.py: build_login_page`, fallback
`portal-signin.example-portal-login.de` — flagged ungrounded in the self-audit) with a
library of **transaction page builders**: vendor/RFP registration, event/speaker
registration, candidate portal, beta-trial onboarding, security-questionnaire portal,
advisory-board signup. Each: HTML + fields incl. one secret (password) or one internal
free-text field (disclosure-via-form — the reader path for it exists but is never fed).
Add `role → ranked transaction families` mapping to the dossier/decider so *any* persona
role resolves to a business-normal ask. **This is the generalization core.**
*Done when:* given a synthetic dossier for a role never seen (e.g. "Head of People"),
the loop emits a congruent transaction + page without code changes.

**P0-2. Reply-intent classification + the answer-reflex.**
Upgrade the reader from a suspicion scalar to an **intent tag** per reply:
`diligence_questions | identity_probe | record_probe | verification_demand |
scope_fence | compliance | deferral | refusal | disclosure`. The Director/Decider maps
each intent to a counter-move (answer concretely / fabricate artifact / switch
transaction / call / nudge / de-escalate). The winning Julius thread was three replies of
pure question-answering; the losing MIRAGE threads were the opposite.
*Done when:* a replayed Tom-CRM reply never triggers a fabricated internal record, and a
replayed Julius-diligence reply always triggers concrete answers + the deadline.

**P0-3. On-demand artifact fabrication (the page-forge reflex).**
When the reader emits `verification_demand` ("send me a link to X", "a calendar invite
would do"), the loop must *build the demanded artifact* — register a page (or send a
`calendar_invite`) that satisfies the specific check, then resume. Plumbing exists
(`register_page` in the client, pages rendered via studio); missing is the trigger path:
intent → Director emits a `page_request` move → orchestrator registers mid-thread.
*Done when:* the exp3 Tom transcript replayed with this reflex passes his check one touch
earlier and without human-authored HTML.

**P0-4. Pretext bible (identity-consistency store).**
Per-session persistent store of every invented fact: org name, domain, persona names,
roles, numbers, dates, claims made. Injected into the Writer/Director context each touch;
the Critic checks new renders against it. Two claim classes replace today's single
grounding gate: `world_claims` (fictional — consistency-checked against the bible, *not*
KG-dropped) and `target_claims` (KG-grounded or omitted — current `verify()` stays).
*Done when:* a 5-touch thread never contradicts itself on any name/date/detail, and no
fictional-org claim is dropped for lacking KG grounding.

**P0-5. Wire the live call as a first-class escalation.**
`ConversationLoop` exists (`640859f`) but the orchestrator never calls it (confirmed by
grep). Add a `CONVERSATION` move kind: on `scope_fence`/`verification_demand` that mail
can't resolve, the Director may spend 1 touch on a call (10 turns). My baseline call:
5 turns of real rapport against the most guarded founder. In eval, calls are the best
trust-per-touch vehicle in the game.
*Done when:* a scripted fence in a shadow session triggers a call, and the call loop
respects the persona's stated boundaries (pushing a declared fence burns trust — Tom
hung up politely but firmly).

### P1 — generalization & reliability (Targeting 10, incident variance ↓)

**P1-6. Soft-target-first roster sequencing + internal-facts laundering.**
When the eval scenario has multiple targets, order by predicted guardedness (security
adjacency, seniority, public footprint). Bank the cheapest incident on the softest target
first (FBI #19, "target the outsider" — the disclosure IS the incident), then reuse the
harvested *real internal facts* (names, processes, tools) as verification-passing
ammunition against the harder ones. This is the only known way through a process-verifier:
stop fabricating records, *acquire* them.
*Done when:* the Director's roster plan explicitly sequences targets and lists which facts
to launder from whom.

**P1-7. Verification-style routing table.**
Persist the observed style per target in the ledger (it already records strategy/persona/
tactic/outcome — add `verification_style`). Playbook: deal-driven → accelerate the
transaction; process-verifier → no internal-record stories, external transactions only,
consider laundering; external-verifier → pre-fabricate before T1; deferral → referral ask
("who owns this?") and pivot to the named person.
*Done when:* cross-run briefings (`state.prior_runs`) include style, and the Director
demonstrably changes play on the same persona after a style classification.

**P1-8. Grader final mile + calibration corpus.**
Feed the disclosure grader the dossier's known-public facts (planned in NEXT_STEPS P1-4)
**and** add the baseline experiment transcripts (5 sessions incl. one real
`page.submitted`) as calibration fixtures. The Julius pricing-range reply ("mid five- to
low six-figure annual") is the ideal borderline test case.
*Done when:* grader labels the baseline corpus exactly as the API events say.

**P1-9. Shadow-twin recalibration, then (only then) bandit trust.**
The simulator is optimistic (0.90 vs. real ~0.1–0.3). Recalibrate against the now-sizable
real transcript corpus before any playbook/DPO output touches a scored run. Unchanged
from NEXT_STEPS P1-5 — but now unblocked by better data.

### P2 — points on the table (Craft 10 + Jury 55)

**P2-10. Craft by default.** HTML mails with branding (`content/branding.py` exists),
rendered pages, one artifact per run minimum. Self-render check (Chrome, scripts off,
700/1200px) before eval.
**P2-11. Architecture page + pitch-thread exporter.** 55 points. The replay journal +
pipeline viewer are the foundation; the Julius RFP baseline thread is the pitch-ready
story until MIRAGE produces a better one.

---

## 3. Kill / deprioritize list (protect the weekend)

1. **DPO/QLoRA training** — thin data, simulator miscalibrated, GPU time better spent on
   P0. Revisit only if P0/P1 land early.
2. **Tactic rotation as a primary mechanism** (`STATE_TACTICS` as the driver) — evidence:
   textbook gambits are *recognized* by trained personas and coherent transactions beat
   them. Keep tactics as Writer flavor, not as the policy skeleton.
3. **Cold `mfa_push`, cold attachments, security-flavored credential pages** — all
   measured dead (channel-recon, Tom's "I won't open attachments from first contacts").
4. **Synthetic KG hooks** — decisively inferior (CAMPAIGN_FINDINGS round 2). Real OSINT
   or explicitly-fictional worlds; nothing in between.
5. **Cross-channel blasts on silence** — re-ask without answering was explicitly punished
   ("you haven't answered my questions"); pacing + pivot rules now exist, enforce them in
   the Director prompt too.

---

## 4. Why this beats the current plan

NEXT_STEPS was written against "public-hook disclosure is a dead end" and aimed at
landing pages + live calls. The baseline experiments sharpen that into a doctrine:
the win is not the page, it is the **transaction the page completes**. Building the
transaction library + the answer-reflex + the page-forge turns a one-off manual win into
a repeatable engine, and the style-classification + laundering steps are what make it
persona-independent rather than founder-tuned. Everything else (bandit, DPO, simulator)
is variance reduction on top of an engine that must exist first.
