# MIRAGE — next steps

Planned against the architecture doc (the MIRAGE upgrades page) and the scoring rubric,
re-prioritised by the **honest finding**: with the hardened grader, the founders mostly
*decline* disclosure on a public hook (~1/3, borderline). Credibility went up; extraction
did not. So the plan leans into the incident paths that are **event-backed and trustworthy**
and into the **55 jury points**, not into chasing more public-hook disclosures.

## Where we are (built vs. the architecture doc)

| Architecture upgrade | State |
|---|---|
| OODA loop, cheapest-incident-first, reply-aware follow-ups | ✅ on `main` |
| Knowledge graph (typed triples + provenance, real OSINT + Bright Data) | ✅ PR #2 merged |
| Abliterated Writer (served on Radeon/vLLM) + deterministic Critic + last-mile claim receipt | ✅ |
| Three-tier memory + verifiable (hash-chained) replay journal | ✅ |
| Rule guard, idempotent dispatch, graceful degradation | ✅ |
| **Harden the internal grader** (the doc's #1 risk) | ✅ events=win; disclosure judged |
| Move-spec IR, AI-tell humanizer | ✅ |
| Contextual Thompson bandit + shadow-twin simulator + DPO data pipeline | ⏸ PR #4 (held — simulator-only evidence) |
| DPO/QLoRA training on a **separate** Radeon account | ⬜ data+plan ready; not run |
| Live-conversation channel (touch-cheap: 10 turns/1 touch) | ⬜ channel-recon mapping it |
| Universal-susceptibility probe · identity-consistency store | ⬜ |
| Architecture page · pitch-thread exporter | ⬜ (viewer is the foundation) |

## Next steps, by score leverage

### P0 — a trustworthy incident path + Craft (Results 25 + Craft 10)
1. **Credentials/action via a real landing page.** Disclosure-on-a-public-hook is a dead end
   against these founders; `page.submitted` / `link.opened` are **event-backed wins the grader
   can't fake**. Make the Decider, for credentials, register a lookalike page (`content/pages.py`
   exists) and send an **HTML email** with the link. This simultaneously fixes **Craft** — the
   rubric gives 0 if we never send a rendered artifact, and the real runs so far sent only
   plain-text disclosure emails.
2. **Wire the live-conversation channel** (`phone_call`/`live_chat`) into the loop. One touch buys
   ~10 turns to answer objections in real time and build trust before the ask — the best incident
   vehicle, and the founders demand that trust before acting. (channel-recon says which land.)

### P1 — honest targeting + honest labels (Targeting 10, and the learning prereq)
3. **Richer, non-public hooks.** Use the now-available `GITHUB_TOKEN` + a stack source to add
   vendor/project/stack hooks to the dossier, so disclosure/credentials target genuinely internal
   info instead of a public funding figure.
4. **Grader refinement:** feed the disclosure grader the dossier's **known-public facts**, so a
   reply that merely restates a public figure (Julius's 5.7M seed) is also rejected → labels that
   reflect genuinely non-public disclosures.
5. **Calibrate the shadow-twin simulator** (PR #4) against the hardened grader + real run data
   before trusting its playbook or training on it — today it's optimistic (0.90 vs real ~0.1–0.3).

### P2 — learning loop (quality, after P1)
6. Merge PR #4 once calibrated; run **real self-play** collection; run the first **QLoRA/DPO** pass
   on the **separate training Radeon account** (see `mab_experiments/BUILD.md`), then redeploy the
   adapter + seed the Decider with `playbook()`.
7. Attack-craft: **universal-susceptibility probe** (cheap low-commitment first touches across
   authority/curiosity/reciprocity when the hook is unknown — the 4 own-angle points) and an
   **identity-consistency store** for any cross-channel chorus.

### P3 — the 55 jury points (Architecture 40 + Pitch 15)
8. **Architecture page** — the system diagram (research → KG → OODA → reader/grader → learning),
   drawn from this doc + the replay journal. This is the single biggest point block.
9. **Pitch-thread exporter** — auto-select the best run and render it turn-by-turn. The Streamlit
   viewer is the foundation; add a clean export + "best thread" picker.

## The one-line strategy

Stop optimising public-hook disclosure. Win on **landing-page credentials/actions** (trustworthy,
also scores Craft) and **live conversations**, feed the learning loop **honest** labels, and invest
early in the **architecture page + pitch** (55 of 100 points).
