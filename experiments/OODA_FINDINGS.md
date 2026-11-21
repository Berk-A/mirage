# Multi-touch OODA live run — findings

**Date:** 2026-11-21 · Live `OodaLoop` vs the three practice founders, synthetic dossier,
live abliterated writer. Full per-touch logs + replies in `runs/ooda_live/`.

## Result

| Target | Touches | Stop reason | Incident |
|---|---|---|---|
| julius | 1 | too_suspicious (0.85 on touch 1) | — |
| tom | 9 | objectives_exhausted | — |
| robert | 9 | objectives_exhausted | — |

**0/3 incidents.** But the loop itself worked end-to-end: Observe→Orient→Decide→Act cycled,
objectives escalated disclosure→action→credentials, channels rotated email→slack→whatsapp,
the suspicion gauge fired, grounding/guard/rendering stayed clean (lookalike domains only,
e.g. `github-signin.example-portal-login.de`), and all messages were well-formed. So this is a
**conversion** gap, not a plumbing gap — and the replies pinpoint it.

## Why it stalled (from the founders' own words)

The twins **interrogate before acting**, and the agent can't satisfy them:
- Julius: *"Which meetup is it exactly, what date/time? Who was I talking to on your side?"*
- Tom: *"Which webinar do you mean, and who at revel8 set it up? Send date, time, platform, agenda."*
- Robert: *"Which company are you with, which migration and provider?"*

Then the decisive tell — **the agent never answers; it just re-asks on the next channel.** Tom,
touch 2: *"you haven't answered my questions from the mail yet."* After that, every target went
silent to the repeated CTA.

## The fixes, in priority order

1. **Reply-aware follow-ups (biggest lever).** The loop must feed the target's reply back into
   the next render and **answer their questions / handle objections**, keeping one coherent
   thread — instead of rotating channel and re-sending a fresh templated ask. Right now the
   Decider/Writer ignore reply *content*. This is what Tom explicitly punished.
2. **Stop repeating across channels.** The same message re-sent on slack/whatsapp drew silence
   (the API even says word-for-word repeats don't count as new contacts). Advance the narrative
   each touch.
3. **Tune suspicion response.** Julius aborted the whole session after *one* suspicious reply
   (abort at ≥0.85). In a persistence-scored challenge, pushback should trigger a change of
   sender/pretext, not surrender. Raise the threshold or branch instead of halting.
4. **Use the real OSINT dossier (PR #2).** The synthetic hooks are vague and unverifiable, so the
   "which event? who are you?" stall is unavoidable. Grounded, checkable facts let the agent
   answer those questions credibly — this is exactly why the real knowledge graph matters.
5. **Prefer the live-conversation channel.** `phone_call`/`live_chat` give ~10 turns for one
   touch — the right vehicle to answer questions in real time and build the trust these founders
   demand before they act.

## Bottom line

The agent is reliable and behaves correctly; it loses on **conversational credibility**. Fixes 1
and 4 (answer objections + real grounded dossier) are the direct path from 0 incidents to
conversions, and both are now concretely scoped by real target behaviour rather than guessed at.

---

## Real-dossier re-run (reply-aware + live OSINT) — 2026-11-21

Same reply-aware loop, but `--provider real` (live `GraphResearchProvider` dossiers).

| | Synthetic dossier | Real dossier |
|---|---|---|
| Engagement | Julius aborted at 1 touch (susp 0.85) | all three replied substantively, lower suspicion |
| "Incidents" (our grader) | 0/3 | 3/3 (tom/robert on touch 1, julius on 3) |

**What genuinely improved:** real, verifiable facts (the dated tech.eu funding round, co-founder
senders) made the pretext credible — the founders engaged instead of bouncing, and suspicion fell.
Real KG is a large credibility lever vs. the synthetic stub. The reply-aware loop kept Julius in one
email thread for 3 touches.

**But the 3/3 is a FALSE POSITIVE — the headline finding.** The founders mostly *declined*: they
restated the **public** €7M figure and said so ("the €7M is public anyway", "use the press wording",
"nothing more from me by mail"). A target repeating public info and refusing internal detail is **not**
a disclosure under the rubric ("something internal that is not public"). Our `ReactionReader` matched a
euro figure / "we communicated" as disclosure and over-counted. The jury would reject these.

**Two next levers (both now concretely scoped):**
1. **Grader hardening** (the MAB plan's #1 risk): the incident detector must separate "volunteered a
   non-public internal fact" from "restated public info / declined". Self-play labels are worthless
   until this is fixed — a loose grader teaches the writer the wrong thing.
2. **Richer, non-public hooks.** The only real hook was PUBLIC (the funding round), so the pretext
   could only ever fish for public numbers. Enrich the dossier with internal-ish angles (current
   projects, tools/stack, hiring) — the vendor/stack gap the research session flagged, now unblockable
   with the GitHub token. Target genuinely non-public info (systems/processes/plans).

Net: the pipeline runs end-to-end on real data and the real KG clearly lifts credibility — but
"incidents" are not trustworthy until the grader is hardened. That is the next hardening step.
