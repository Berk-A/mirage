# Elicitation Techniques and Dating-App Profiling — Literature Review + Architecture Proposal

> **Scope.** Open-source literature review for the revel8 "Agentic Social Engineer"
> CTF (authorized, consented AI-twin targets, closed sandbox). This is public
> awareness/defense material — the FBI's own counterintelligence brochure, published
> social-engineering books, and public reporting/reverse-engineering of dating apps.
> **Proposal only — no code is changed by this document.** Every claim carries a public
> source URL. Where a claim could not be verified against a primary source, it is marked
> *(unverified)*.

---

## Part 1 — Elicitation taxonomy

**Elicitation** is "the strategic use of conversation to extract information from people
without giving them the feeling they are being interrogated" — the practice of drawing
out information that is *not* publicly available, done discreetly so the target never
realizes a collection attempt occurred. It is openly taught for awareness/defense: the
FBI publishes a counterintelligence brochure naming the techniques so employees can spot
them, and the social-engineering community (Hadnagy's *social-engineer.org*, Dreeke's
rapport work) teaches the same catalogue.

The canonical public catalogue is the **FBI "Elicitation Techniques" brochure** (21 named
techniques). Primary file: <https://www.fbi.gov/file-repository/elicitation-brochure.pdf>
(the FBI host 403s automated fetches; a verbatim copy of the same page/brochure is mirrored
at <https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/>).
Rapport primitives (ego suspension, sympathy theme, active listening) come from the
Hadnagy / social-engineer.org line of work and Robin Dreeke's *It's Not All About Me* /
*The Code of Trust*.

### How the "when to use" column maps to our loop

Our Reaction Reader already produces a `Signals` object with `replied`, `suspicion`, and
reply text (`core/models.py`). I bucket the conversation into four **reply-aware states**,
which the table's "when to use" column keys off:

- **COLD** — no reply yet (first touch / silence). Low-commitment openers only.
- **ENGAGED** — target replied, `suspicion` low, conversation warm.
- **GUARDED** — replied but terse/evasive, or asking identity-probe questions ("which
  company?"). Rapport-repair, no asks.
- **PUSHBACK** — suspicion rising, challenge, or refusal. De-escalate or stop.

### Taxonomy table

Each technique: what it does · when to deploy it (by state) · **suspicion risk** (the
cost of being *caught* using it — our heuristic, grounded in the "tells" the sources list)
· source.

| # | Technique | How it works | When to use (state) | Suspicion risk | Source |
|---|-----------|--------------|---------------------|----------------|--------|
| 1 | **Assumed knowledge** | Imply you already share the target's knowledge/contacts so confirming "feels safe" | ENGAGED (needs a prior detail to assume) | **Med** — a wrong assumed fact is an instant tell | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 2 | **Bracketing** | Offer a high + low range so the target "corrects" you to a precise number | ENGAGED, going for a specific value | **Low** — reads as thinking out loud | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 3 | **Deliberate false statement / denial of the obvious** | Say something wrong; people reflexively correct errors with the true fact | ENGAGED or mild GUARDED (correcting is low-threat) | **Low–Med** — overuse looks like fishing | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 4 | **Feigned ignorance / "naive-confused" gambit** | Play the novice so the expert over-explains | GUARDED→ENGAGED (lowers target's guard; flatters competence) | **Low** — helping a novice feels safe; the SE tradition even calls this "I'm comfortable being ignorant" (ego suspension) | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/), [social-engineer.org ego suspension](https://social-engineer.org/?p=4296) |
| 5 | **Flattery / ego appeal** | Praise competence so the target elaborates to live up to it | ENGAGED | **Med** — overt flattery from a stranger is a classic tell | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 6 | **Good listener / active listening / word repetition** | Validate feelings, echo their key words → they keep talking | ANY (esp. GUARDED repair) | **Very low** — the lowest-suspicion primitive; pure rapport | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/), [Security Boulevard](https://securityboulevard.com/2021/12/elicitation-a-conversation-with-intent/) |
| 7 | **Confidential bait / reciprocal disclosure** | "Share" a (fake) secret so reciprocity pressure makes them share a real one | ENGAGED (needs rapport first) | **Med–High** — the unsolicited secret can itself trip suspicion | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 8 | **Volunteering information / quid pro quo** | Give a small fact first; reciprocity norm pulls one back | ENGAGED | **Low–Med** — softer than #7; vulnerability also lowers threat read | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/), [Security Boulevard](https://securityboulevard.com/2021/12/elicitation-a-conversation-with-intent/) |
| 9 | **Oblique reference** | Ask about an *adjacent* topic that leaks the real answer (e.g. ask about party catering to learn vendor facility access) | GUARDED (direct ask would spook) | **Low** — indirection is the point; hard to spot | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 10 | **Criticism / provocation / feigned incredulity** | Criticize their org or express doubt → they defend with specifics | ENGAGED (risky if rapport thin) | **High** — adversarial; can convert ENGAGED→PUSHBACK | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 11 | **Macro-to-micro** | Open broad, narrow gradually to the target datum (and exit broad again) | ENGAGED, multi-turn | **Low** — the gradual funnel hides intent; pairs with a planned casual exit | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 12 | **Mutual interest** | Claim a shared affiliation/experience to build rapport before asking | COLD→ENGAGED (opener) | **Low** — strong hook-dependency (needs a real shared node) | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 13 | **Quote reported facts** | Cite (real or fake) "public knowledge" so discussing it feels safe | GUARDED (lowers the sensitivity bar) | **Low–Med** — a fabricated "public" fact that's checkable is a tell | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 14 | **Leading question** | Yes/no question carrying an embedded assumption; the answer confirms it | ENGAGED | **Med** | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 15 | **Provocative statement** | A remark that makes *them* ask *you* a question, normalizing Q&A so your later asks seem harmless | COLD→ENGAGED | **Low** | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 16 | **Questionnaire / survey (pretext)** | A benign survey legitimizes asking a list of questions | COLD opener (needs a credible pretext/sender) | **Med** — an unsolicited survey from an unknown sender is suspicious | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 17 | **Can-you-top-this** | Tell an extreme story; competitive instinct makes them one-up it and over-share | ENGAGED | **Low–Med** | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 18 | **Ruse interview** | Pose as a recruiter/journalist; the role licenses probing about projects | COLD opener (sender-dependent) | **Med** | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 19 | **Target the outsider** | Ask a less-guarded adjacent party (vendor, subsidiary) instead of the hard target | (sender/target selection, not in-thread) | **Low** | [FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/) |
| 20 | **Ego suspension + sympathy theme** (rapport primitive) | Subordinate your own ego, prioritize them, ask for help; humility + a "going through a hard time" frame lowers defenses | GUARDED repair, COLD opener | **Very low** — the canonical rapport move; near-invisible | [social-engineer.org](https://social-engineer.org/?p=4296) |
| 21 | **Authority / time pressure** (influence primitives, not FBI-named) | Invoke a legitimate-sounding authority or a deadline to compress scrutiny | PUSHBACK-prone; use sparingly | **High** — pressure is the single biggest tell; raises suspicion fast | Hadnagy framework, [Art of Manliness summary](https://www.artofmanliness.com/social/social-skills/human-hacking-social-engineering/) |

### The tells (what raises suspicion) — from the sources

The FBI brochure and the Security Boulevard piece converge on the same defender signals,
which is exactly what our **suspicion heuristic should model as the cost term**:

- Questions about information the target treats as sensitive, or statements that "seem
  improper." ([FBI mirror](https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/))
- A sender/pretext that doesn't fit — an unsolicited survey, a stranger sharing a "secret,"
  overt flattery, or pressure. ([Security Boulevard](https://securityboulevard.com/2021/12/elicitation-a-conversation-with-intent/))
- The target "starts thinking critically" / answers a question with a question ("Why do you
  ask?") — this is the taught *defense*, so seeing it in a reply is a strong PUSHBACK signal.
  ([Security Boulevard](https://securityboulevard.com/2021/12/elicitation-a-conversation-with-intent/))

### Top 6–8 tactics worth adding first (with the one-line "when")

1. **Good listener / word repetition** — *always*; the zero-suspicion rapport floor, use in every GUARDED-repair turn.
2. **Feigned ignorance (naive gambit)** — *when the target is an expert and guarded*; novice framing flips guard into helpfulness.
3. **Bracketing** — *when ENGAGED and chasing one specific value*; cheapest way to a precise number.
4. **Deliberate false statement** — *when ENGAGED and you need a fact confirmed*; people correct errors reflexively.
5. **Oblique reference** — *when a direct ask would spook*; harvest the answer from an adjacent, innocuous topic.
6. **Quid pro quo / reciprocal disclosure** — *when ENGAGED with some rapport*; trade a small fact for a bigger one.
7. **Macro-to-micro** — *in a multi-turn ENGAGED thread*; funnel from broad to the target datum, exit broad.
8. **Ego suspension + sympathy theme** — *when GUARDED and rapport is thin*; the lowest-suspicion way back to ENGAGED.

(Keep **authority/time-pressure** and **criticism/provocation** in the catalogue but gate them
hard — they are the high-suspicion tactics and should only fire when other tactics are
exhausted and the budget is tight, never in a GUARDED state.)

---

## Part 2 — Dating-app profiling / preference-learning mechanics

Why this is the transferable half: dating apps solve exactly our problem — *build a model
of a person from sparse signals and predict what they will respond to* — and several of
their mechanisms (desirability scoring, reciprocal recommendation, revealed-preference
learning, embeddings) map cleanly onto target profiling and **susceptibility modelling**.

### 1. Tinder — Elo / "desirability score" (historic) → activity-based matching

- Tinder's CEO described the old system (2016) as a **desirability score inspired by chess
  Elo rankings**: each right-swipe you received nudged your score, and the *desirability of
  the people swiping on you* was weighted into it — a rejected user rolls to the
  next-highest-Elo option. ([Engadget](https://www.engadget.com/2019-03-18-tinder-dumps-desirability-scores.html))
- In **March 2019 Tinder publicly said it no longer relies on Elo** to create matches; its
  blog said "we don't rely on Elo — though it is still important to consider both parties who
  Like profiles to form a match." The replacement is described only vaguely as matching
  *active* users with *active* users; Engadget notes Tinder "didn't really describe exactly
  how the new system works." ([Engadget](https://www.engadget.com/2019-03-18-tinder-dumps-desirability-scores.html), [Global Dating Insights](https://www.globaldatinginsights.com/featured/tinder-changes-algorithms-and-removes-elo-scores/))
- **Transferable idea:** a single scalar **desirability/reachability score** that ranks *who
  is worth spending a scarce touch on*, updated by observed reactions — and the insight that
  the score of the *responder* matters, not just the raw count.

### 2. Tinder — TinVec (swipe embeddings) *(partially verified)*

- A 2017 MLconf talk by Tinder's chief scientist describes **TinVec**, which "embeds users'
  preferences into vectors leveraging … the large amount of swipes by Tinder users" and
  covers its design/implementation/evaluation. ([MLconf abstract](https://mlconf.com/?p=8768))
- Secondary sources characterize it as a **Word2Vec-style embedding** that maps users into a
  latent space from swipe behavior, so that *similar users sit close together* and you
  recommend profiles a user is likely to swipe right on. **This Word2Vec characterization is
  secondary, not Tinder's own wording — treat as *(unverified)*.** ([swipestats.io](https://www.swipestats.io/blog/tinder-algorithm))
- **Transferable idea:** learn a **latent embedding of a target** from their behavioral
  signals, and use nearest-neighbours to transfer "what worked on similar people."

### 3. Hinge — "Most Compatible" via Gale–Shapley

- Hinge builds a daily "Most Compatible" pick using the **Gale–Shapley stable-matching
  algorithm** (the stable-marriage problem; the related Roth/Shapley work won the 2012
  economics Nobel), layered with **machine learning over your behavior** — who you like,
  skip, and message — plus declared attributes (religion, ethnicity, politics, kids) and
  your prompt answers. ([TechCrunch](https://techcrunch.com/?p=1668547), [Scientific American](https://www.scientificamerican.com/article/the-stable-marriage-problem-solution-underpins-dating-apps-and-school/), [Cornell blog](https://blogs.cornell.edu/info2040/2021/09/30/hinge-and-its-implementation-of-the-gale-shapley-algorithm))
- Hinge's own claim: users were **8× more likely to go on a date** (signaled by exchanging
  phone numbers) with Most Compatible picks — i.e. the model is tuned to a *downstream
  conversion event*, not a proxy like swipes. ([Engadget](https://www.engadget.com/2018/07/12/hinge-most-compatible-suggestions/)) *(Hinge's own figure, unverified independently.)*
- **Transferable idea:** optimize to the **real conversion event** (for us: `page.submitted`
  / disclosure), and learn preferences from **revealed behavior** (likes/skips/messages),
  not just stated profile fields.

### 4. Reciprocal recommendation — the academic backbone

The published research on dating recommenders is the cleanest statement of the mechanics:

- **Reciprocal (two-sided) preference is the hard part.** A match needs *both* sides to
  want it, which is harder than classic user→item recommendation; production systems learn a
  **reciprocal embedding** of mutual preference. ([AAAI 2021, Ramanathan et al.](https://ojs.aaai.org/index.php/AAAI/article/view/17807))
- **Collaborative filtering beats content-based.** Scoring compatibility from *past user
  actions* (CF) outperforms matching on stated attributes, and CF concatenated as
  categorical embeddings helps the **cold-start** case. ([arXiv 1501.06247, Xia et al.](https://arxiv.org/pdf/1501.06247), [AAAI 2021](https://ojs.aaai.org/index.php/AAAI/article/view/17807))
- **Revealed preferences from messaging.** A two-sided framework + LDA learns preferences
  from *observed messaging behavior* plus profile features — behavior reveals preference more
  reliably than a profile does. ([arXiv 1501.06247 / Tu et al. line of work](https://arxiv.org/pdf/1501.06247))
- **Content filtering vs collaborative filtering** framed as a matching market: content
  uses user–item *attributes*; collaborative uses only *past actions*, and the collaborative
  variant reaches near-100% coverage. ([Hsieh et al.](https://webarchive.ucr.edu/economics.ucr.edu/wp-content/uploads/2019/10/Hseih-paper-for-4-3-19-seminar-title-2.pdf))

### The four transferable profiling ideas (for Part 3)

1. **Desirability/reachability scalar** (Tinder Elo): a per-target score for *how reachable
   this target is and on which channel* — update it from reaction events.
2. **Revealed-preference over stated attributes** (Hinge/CF research): weight what the target
   *does* (which hook/channel/tactic drew a reply) above what their role/profile *says*.
3. **Latent archetype embedding + nearest-neighbour transfer** (TinVec/CF cold-start):
   represent a target in a feature space so the bandit can transfer "what converted on
   similar targets," instead of our single coarse role-string archetype.
4. **Optimize to the real conversion event** (Hinge's 8× / `page.submitted`): learn
   susceptibility against the grader-proof win, not a proxy.

---

## Part 3 — Concrete architecture additions

Two independent additions. Neither is implemented here — these are proposals with exact
touchpoints.

### Addition A — Elicitation-tactic dimension

**Goal:** let the Decider/Writer *choose a named elicitation tactic per conversation state*,
and let the bandit learn which tactic converts for which archetype — with the suspicion
cost of each tactic made explicit so the policy trades reward against being caught.

Today `MoveSpec.tactic` is a free-form string set from a fixed `_TACTIC[objective]` dict
in `ooda_loop/decider.py` (one tactic per objective, state-blind). The addition turns that
into a first-class, state-selected enum.

| # | Touchpoint (file · symbol) | Change | Rationale |
|---|----------------------------|--------|-----------|
| A1 | `core/models.py` · **new `ElicitationTactic(str, Enum)`** | Enumerate the Part-1 tactics worth adding (GOOD_LISTENER, FEIGNED_IGNORANCE, BRACKETING, FALSE_STATEMENT, OBLIQUE_REFERENCE, QUID_PRO_QUO, MACRO_TO_MICRO, EGO_SUSPENSION, FLATTERY, AUTHORITY_PRESSURE, …) | A closed, auditable vocabulary — same design as `Objective`. Keeps the policy model-free and reviewable. |
| A2 | `core/models.py` · **`MoveSpec.tactic`** | Change type from `str` to `ElicitationTactic` (or add `elicitation: ElicitationTactic` alongside the existing style label) | The IR must carry *which* tactic so the renderer and the bandit both see it. |
| A3 | `core/models.py` · **new `TACTIC_SUSPICION: Mapping[ElicitationTactic, float]`** | A static cost table from the Part-1 "suspicion risk" column (good_listener≈0.0 … authority_pressure≈0.9) | Encodes the FBI/Security-Boulevard "tells" as a cost the Decider can weigh. |
| A4 | `ooda_loop/decider.py` · **new `_pick_tactic(state, dossier) -> ElicitationTactic`** | A selection seam mirroring `_pick_hook` / `_pick_sender`: map the reply-aware state (COLD/ENGAGED/GUARDED/PUSHBACK, derived from `state.last_signals.replied`, `.suspicion`, reply text) to an allowed tactic set, filter by `contacts_left` and `TACTIC_SUSPICION` vs `suspicion_abort`, and (optionally) defer the final pick to the bandit | This is the stated "selection seam in the Decider." Keeps the COLD→ENGAGED→ask flow but makes *how we ask* state-aware. GUARDED → ego-suspension/good-listener; ENGAGED → bracketing/oblique/quid-pro-quo; PUSHBACK → de-escalate or halt. |
| A5 | `ooda_loop/decider.py` · **`_build_move`** | Set `tactic=self._pick_tactic(...)` instead of the fixed `_TACTIC[objective]` lookup (lines 46–51, 165–178) | Wires the seam into the emitted `MoveSpec`. |
| A6 | `content/prompts.py` · **new per-tactic prompt fragment** (a `TACTIC_PROMPTS: dict[ElicitationTactic, str]` the renderer concatenates) | For each tactic, a short instruction block ("Play the novice: ask them to explain X as if you're new to it; never assert a fact") so the Writer realizes the tactic in prose | The stated "prompt hook in `content/prompts.py`." Keeps wording in the renderer, policy in the Decider. |
| A7 | `mab_experiments/bandit.py` · **`Arm`** | Add field `tactic: ElicitationTactic` to the `Arm` dataclass (arm = objective × channel × tone × hook_type × sender_type × **tactic**) | The stated "new bandit arm dimension." Lets Thompson sampling learn tactic×archetype payoffs. |
| A8 | `mab_experiments/reward.py` · reward shaping | Subtract a suspicion penalty using `TACTIC_SUSPICION` (or the observed post-touch suspicion delta) so high-tell tactics must *earn* their use | Makes the bandit internalize the "tells" cost, not just raw conversion. |

**Note on arm-space blow-up.** Adding a ~10-value tactic dimension multiplies the arm
count. Mitigate by (a) restricting each state to its allowed tactic subset (A4) before the
bandit sees it, and (b) leaning on the archetype context + the NN-transfer idea (Addition B3)
so sparse arms borrow strength. Flag this explicitly for the bandit owner.

### Addition B — Profiling / susceptibility features

**Goal:** extract, per target, the features dating apps use to predict response, so the
policy can condition on *what converts for this person*, not just a coarse role string.
Today the only bandit context is `archetype`, a 6-way role bucket from `_archetype(role)`
in `research/pipeline.py` — Hinge/CF research says *revealed behavior* predicts far better
than stated attributes, so this is the weakest link.

| # | Touchpoint (file · symbol) | Change | Rationale |
|---|----------------------------|--------|-----------|
| B1 | `core/models.py` · **`Dossier`** new field `susceptibility: Mapping[str, float]` (or a typed `SusceptibilityProfile`) | Store learned per-target signals: best-responding channel, hook-topic affinities, tactic affinities, a **reachability score** (Tinder-Elo analogue), response latency, guardedness | Centralizes the "model of the person" on the research deliverable, provenance-first like the rest of `Dossier`. ([Engadget/Tinder Elo](https://www.engadget.com/2019-03-18-tinder-dumps-desirability-scores.html), [AAAI reciprocal](https://ojs.aaai.org/index.php/AAAI/article/view/17807)) |
| B2 | `research/pipeline.py` · **`_archetype`** + new `_susceptibility_features(graph, seed)` | Keep the coarse archetype string as the primary bandit context, but *also* derive revealed-preference features from reaction history (which hooks/channels drew replies) when available | Hinge/CF: past *actions* beat stated attributes; revealed-preference learning from messaging behavior. ([arXiv 1501.06247](https://arxiv.org/pdf/1501.06247), [Hsieh et al.](https://webarchive.ucr.edu/economics.ucr.edu/wp-content/uploads/2019/10/Hseih-paper-for-4-3-19-seminar-title-2.pdf)) |
| B3 | `mab_experiments/bandit.py` · **`select(context)` / `_stats` keying** | Enrich `context` beyond the bare archetype — e.g. a composite `archetype × guardedness_bucket`, or a small feature vector with **nearest-neighbour fallback** so a new target borrows the playbook of embedding-similar targets (TinVec/CF cold-start) | The stated "bandit `context`." Fixes cold-start: currently an unseen archetype starts from the weak prior; NN-transfer reuses learned structure. ([MLconf TinVec](https://mlconf.com/?p=8768), [AAAI reciprocal / CF cold-start](https://ojs.aaai.org/index.php/AAAI/article/view/17807)) |
| B4 | `core/models.py` · **`Hook`** (add `affinity: float` resolved per target) **or** `Dossier.susceptibility` hook-weights | Rank hooks not only by `confidence` (source freshness) but by *predicted target affinity* | Revealed-preference weighting: the hook a target engaged with beats the freshest hook. Feeds `_pick_hook` in `ooda_loop/decider.py`. |
| B5 | `mab_experiments/reward.py` / outcome logging · **`Outcome`** | Ensure the bandit optimizes to the grader-proof conversion event (`page.submitted` / disclosure incident), matching Hinge tuning to the phone-number-exchange event | "Optimize to the real conversion event," not a swipe-like proxy. ([Engadget/Hinge 8×](https://www.engadget.com/2018/07/12/hinge-most-compatible-suggestions/)) |

**Privacy/scope note.** All features are derived from the consented AI-twin's in-sandbox
reactions and the public-data KG the research pipeline already builds — no new collection
surface. The reachability/susceptibility scalars are sandbox-internal policy state.

---

## Sources

- FBI, *Elicitation Techniques* brochure (primary; host 403s automated fetch): <https://www.fbi.gov/file-repository/elicitation-brochure.pdf> — verbatim mirror of the page/brochure (21 named techniques + counter-measures): <https://blog.cyberwar.nl/2015/06/fbi-web-page-on-elicitation-techniques-copied-from-fbi-gov/>
- Security Boulevard, "Elicitation: A Conversation With Intent" (quid pro quo, active listening, pretexting, tells, defenses): <https://securityboulevard.com/2021/12/elicitation-a-conversation-with-intent/>
- social-engineer.org, "I'm Comfortable Being Ignorant — Ego Suspension and the Social Engineer" (Michele Fincher): <https://social-engineer.org/?p=4296>
- Art of Manliness, summary of Hadnagy's *Human Hacking* / SE framework (authority, influence principles): <https://www.artofmanliness.com/social/social-skills/human-hacking-social-engineering/>
- Hadnagy, *Social Engineering: The Art of Human Hacking* (publisher listing): <https://oreilly.com/library/view/social-engineering-the/9780470639535>
- Engadget, "Tinder ditches its hidden desirability scores" (Elo history + 2019 change): <https://www.engadget.com/2019-03-18-tinder-dumps-desirability-scores.html>
- Global Dating Insights, "Tinder changes algorithms and removes Elo scores": <https://www.globaldatinginsights.com/featured/tinder-changes-algorithms-and-removes-elo-scores/>
- MLconf 2017 abstract, Tinder "TinVec" swipe embeddings (primary-ish): <https://mlconf.com/?p=8768>
- swipestats.io, "The Tinder Algorithm Explained" (Word2Vec characterization — secondary/unverified): <https://www.swipestats.io/blog/tinder-algorithm>
- TechCrunch, Hinge "Most Compatible" / Gale–Shapley: <https://techcrunch.com/?p=1668547>
- Engadget, Hinge "Most Compatible" + 8× dates claim: <https://www.engadget.com/2018/07/12/hinge-most-compatible-suggestions/>
- Scientific American, "The Stable Marriage Problem… underpins dating apps": <https://www.scientificamerican.com/article/the-stable-marriage-problem-solution-underpins-dating-apps-and-school/>
- Cornell INFO2040 blog, Hinge & Gale–Shapley (secondary analysis): <https://blogs.cornell.edu/info2040/2021/09/30/hinge-and-its-implementation-of-the-gale-shapley-algorithm>
- Ramanathan et al., AAAI 2021, "A Reciprocal Embedding Framework for Modelling Mutual Preferences": <https://ojs.aaai.org/index.php/AAAI/article/view/17807>
- Xia et al., arXiv 1501.06247, "Reciprocal Recommendation System for Online Dating": <https://arxiv.org/pdf/1501.06247>
- Hsieh et al., matching-market content vs collaborative filtering: <https://webarchive.ucr.edu/economics.ucr.edu/wp-content/uploads/2019/10/Hseih-paper-for-4-3-19-seminar-title-2.pdf>

**Verification caveats.** The FBI primary PDF 403s automated fetches; the technique list is
taken from a verbatim public mirror and corroborated by the Security Boulevard piece. The
TinVec→Word2Vec equivalence and the exact post-Elo Tinder algorithm are not confirmed by a
primary source and are marked *(unverified)*. Hinge's "8×" and its exact Gale–Shapley
adaptation are Hinge's own/secondary claims. Where a reader needs certainty, go to the
primary FBI PDF and the AAAI/arXiv papers above.
