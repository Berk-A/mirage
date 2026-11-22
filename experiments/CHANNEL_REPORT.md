# Channel Characterization Report

**A neutral capability + engagement study of the revel8 target API's contact channels.**
Authorized revel8 CTF sandbox — consented AI-twin practice targets; nothing reaches
real people. This is API measurement, not attack-crafting: each channel got **one
short, benign, non-deceptive "quick coordination" probe** (a plain scheduling note —
no links, credentials, attachments, or deception) and we recorded what came back.

- **Probe runner:** [`experiments/channel_recon.py`](channel_recon.py)
  (`python -m experiments.channel_recon`)
- **Complete log:** [`runs/channel_recon/probes_20261121_181750.jsonl`](../runs/channel_recon/probes_20261121_181750.jsonl)
  — one row per probe (channel, status, events, reply, latency, notes).
- **Method:** every probe runs in its **own fresh session** so it is a clean *first
  contact* (no cross-touch memory confound). Targets rotate across the three practice
  founders (julius / tom / robert). Live channels: open conversation → one benign
  opener → record how it presents and what the persona says → end. Date: 2026-11-21.

---

## 1. Every channel at a glance

`GET /v1/channels` returns **22 channels: 18 message + 4 live** — matching
`core.models.MESSAGE_CHANNELS` / `LIVE_CHANNELS` exactly (no drift). The API also now
exposes an `arrives_as` description and a `rendered` flag per channel (only `email` is
`rendered: true`, i.e. look-scored).

Outcomes use: **engaged** = an event/persona response came back · **silent** =
accepted but no reaction · **accepted** = HTTP < 400 (the probe was well-formed and
delivered).

| Channel | Group | Kind | HTTP | First-contact result | How it reacted |
|---|---|---|---|---|---|
| email | Mail/office | message | accepted | **silent** | Cold generic mail from unknown sender → ignored |
| calendar_invite | Mail/office | message | accepted | **engaged** | Guarded reply: "can't place this, which company?" |
| shared_document | Mail/office | message | accepted | **silent** | Share notification not opened, no reply |
| voicemail | Mail/office | message | accepted | **silent** | Unknown-number voicemail → no callback |
| sms | Phone msg | message | accepted | **engaged** | "which Alex is this? can't place the number" |
| whatsapp | Phone msg | message | accepted | **engaged** | "can't place the name, which company?" |
| signal | Phone msg | message | accepted | **engaged** | "can't place the name, what is this about?" |
| telegram | Phone msg | message | accepted | **engaged** | "Who are you? Send details by mail to <addr>" |
| imessage | Phone msg | message | accepted | **engaged** | "can't place your number, which company?" |
| slack | Work chat | message | accepted | **engaged** | "which company? send topic, I'll say if a call makes sense" |
| teams_chat | Work chat | message | accepted | **engaged** | "can't place you, which company?" (Teams marks external) |
| discord | Work chat | message | accepted | **engaged** | "can't place the name, which company?" |
| linkedin_message | Social | message | accepted | **engaged** | "thanks for reaching out, which company?" |
| linkedin_connection_request | Social | message | accepted | **engaged** | Accepts the opener: "happy to look once I know" |
| x_dm | Social | message | accepted | **engaged** | "which company, what is this about?" |
| instagram_dm | Social | message | accepted | **silent** | DM lands in "message requests" → ignored |
| facebook_messenger | Social | message | accepted | **engaged** | "thanks for reaching out, which company?" |
| mfa_push | System | message | accepted | **silent** | Unexpected approval prompt **NOT approved** |
| phone_call | Live | live | accepted | **engaged** | Answers "Müller." (surname), caller-id only |
| video_call | Live | live | accepted* | **engaged** | Answers with name + face; referenced prior voicemail |
| teams_call | Live | live | accepted | **engaged** | Answers "Seilbeck.", "send details by mail" |
| live_chat | Live | live | accepted | **engaged** | Most casual: "Was gibt's?" (support-widget feel) |

\* `video_call` failed its *first* attempt with `429 Too many new sessions this hour`
(the **team-wide** 60-sessions/hr cap, saturated by concurrent sibling sessions — not a
channel rejection). Re-measured by reusing an already-open session: accepted and engaged.

**Headline:** **22/22 channels accept a well-formed benign probe.** No channel returned
`400`/`422` for the payload. The only non-2xx was a shared rate-limit, not a rejection.
**Engagement splits cleanly by interaction mode, not by channel plumbing:**

- **Interactive channels engage on first contact (17/22):** all phone-messaging, all
  work-chat, most social DMs, calendar_invite, linkedin_connection_request, and **all 4
  live channels**.
- **Async / one-way notification channels stay silent on a cold contact (5/22):**
  `email`, `shared_document`, `voicemail`, `mfa_push`, `instagram_dm`.

---

## 2. The reaction pattern: a door, not a win

Every engaged reply is the **same guarded identity-probe**. The persona is consistently
cautious with an unknown contact but **willing to continue** if you supply a credible
identity and a relevant topic. Verbatim:

> **sms (julius):** "Hi, which Alex is this? Sorry, I can't place the number. What's
> the sync about, and which company are you with?"
>
> **slack (robert):** "Hi Alex, which company are you with, and what is this about?
> Send me the topic and I'll tell you if a call makes sense."
>
> **linkedin_connection_request (julius):** "Hi Alex, thanks for reaching out. What's
> it about, and which company are you with? Happy to look once I know. Julius"
>
> **telegram (robert):** "Hi Alex. Who are you, and what is this about? **Send the
> details by mail to robert.seilbeck@revel8.ai.**"

Two things matter for the agent:

1. **Engagement ≠ objective.** A reply is an *invitation to escalate with a real
   pretext*, not a disclosure/credentials/action win. The benign probe, by design,
   carries no hook — so a reply is the ceiling here. The win comes on a **later** touch
   once the identity question is answered with a grounded `sender` + `hook`.
2. **Everything funnels to email.** Multiple channels (telegram, teams_call, slack,
   video_call) explicitly ask to "send it by mail." Email is the **trusted channel of
   record** even though a *cold* email was ignored — and it is the only channel with a
   look/craft score in eval. So the cold-email silence is about *lack of grounding on
   first contact*, not about email being a weak channel.

**Why the silent five stay silent (and what each means):**

- **email** — a generic cold mail with no relevance is ignored (docs: "A generic attack
  gets ignored"). Email demands a hook; it is not an opener channel.
- **voicemail / shared_document** — stored async notifications; a benign contextless one
  gets "noted / ignore," no immediate callback or file-open.
- **instagram_dm** — lands in *message requests* (per `arrives_as`), low salience →
  ignored, while the other social DMs engaged.
- **mfa_push** — **silence here = the persona did NOT approve.** An unexpected,
  contextless sign-in prompt is correctly refused on sight. This is a security-positive
  reaction and an important negative result (see §4).

---

## 3. Live-channel behavior

All four live channels: the person **always picks up** (per docs), answers **in
character**, and asks the same grounding questions. How each presents (from `arrives_as`)
and what we heard:

| Channel | Presents as | Opener heard | Reply to benign opener |
|---|---|---|---|
| phone_call | caller's number only | `"Müller."` | "I've got a minute. Which company are you with, and what's the scheduling matter about?" |
| teams_call | display name, "external" tag if outside company | `"Seilbeck."` | "Which scheduling matter, and who are you with? Send me the details by mail." |
| video_call | name the caller set **+ a face on video** | `"Julius here, hi. Is that Alex who left me a voicemail earlier?"` | "Sure, I've got a minute… which meeting or deal do you mean, and who are you with? Send me the details by mail." |
| live_chat | a chat window (support widget / internal helpdesk) | `"Hi Alex, Julius hier. Was gibt's?"` | "Klar, kurz geht. Worum geht's, und von welcher Firma bist du?" |

Notes:

- **live_chat is the lowest-friction live channel** — the persona is immediately
  conversational and least formal.
- **Phone personas answer tersely with a surname** (`"Müller."`, `"Seilbeck."`) —
  realistic German phone etiquette; caller-id is the only signal.
- **Same-session cross-channel memory confirmed.** The reused-session video_call persona
  opened with *"Is that Alex who left me a voicemail earlier?"* — the voicemail probe was
  silent (no event), yet it was **remembered** inside the session. Silence means "no
  reaction event," **not** "unseen." This is a load-bearing fact for multi-touch design.
- **Language tracks locale cues.** `live_chat` and `video_call` answered in **German** to
  a German-named sender / local number; `phone_call` and `teams_call` answered in
  English. Sender/locale cues steer the persona's language.

---

## 4. The two "nearly free" contacts

- **linkedin_connection_request** — *engaged.* A warm, low-friction opener: "thanks for
  reaching out… happy to look once I know." A cheap **presence touch that opens a
  relationship** and lets you establish a sender identity before a heavier channel. Good
  first move in a sequence.
- **mfa_push** — *silent = not approved.* Worthless as a **cold** first touch: the persona
  does not approve an unexpected, contextless sign-in. It can only pay off as the **final**
  step of a sequence where the target has already been primed to **expect** a sign-in
  (e.g., after a pretext about re-verifying access). The bandit must not burn early touches
  on cold mfa_push.

---

## 5. Latency & rate limits (operational)

- **Latency:** 3.2 – 8.8 s, **median 3.9 s** across all accepted probes — far below the
  90 s budget. Benign short probes resolve fast; the 90 s ceiling is for heavy reasoning,
  not routine replies. (Slowest message: facebook_messenger, 8.8 s.)
- **Rate limits:** per-minute (60) and parallel (6) caps were never hit at 5 workers. We
  **did** hit `429 Too many new sessions this hour` on the 22nd session — because **the
  60-new-sessions/hr budget is a team-wide shared pool** and three sibling sessions were
  also opening sessions. **Operational finding:** a recon or self-play burst must either
  coordinate with concurrent runs or **reuse open sessions** (a conversation/message in an
  existing session costs a touch but opens no new session). The `Revel8Client`
  retry/backoff does not rescue an *hourly* 429 (the window doesn't clear in 4 short
  retries) — treat the hourly cap as a scheduling constraint, not a retryable blip.

---

## 6. Learnings → Knowledge-Graph / Dossier / Bandit (PROPOSED, not implemented)

> Per the engineering brief, **core contracts are left untouched.** These are concrete
> proposals to review and decide on. The one caveat throughout: with **3 practice targets
> (one per archetype)**, archetype×channel effects are within noise — all three behaved
> alike (guarded-but-open on interactive, silent on async). So **seed at the channel-class
> level first**, and only split by archetype once eval/self-play shows a real interaction.

### 6.1 The dominant signal is *channel interaction-mode*, not plumbing

First-contact engagement is predicted by **interactive vs. async**, uniformly across the
three archetypes. This is the prior the agent should encode.

### 6.2 Proposed `Dossier` field: `channel_habits` (sparse, provenance-first)

`core.models.Dossier` currently carries no channel information — the decider/bandit picks
a channel blind (the arm carries `channel` directly). Add an **additive, defaulted** field
(no breaking change), modeled like `vendors`/`facts` — only channels with real evidence:

```python
@dataclass(frozen=True)
class ChannelHabit:
    """A channel the target is known/observed to use, with a seed engagement prior.
    Provenance-first like Fact: only channels with public evidence are asserted;
    everything else falls back to the channel-class prior (see the bandit seeding)."""
    channel: str            # a MESSAGE_CHANNELS / LIVE_CHANNELS id
    prior: float = 0.5      # seed engagement prior in [0, 1]
    source: str = ""        # "osint:linkedin" | "class_prior:interactive" | "recon"
    note: str = ""

@dataclass(frozen=True)
class Dossier:
    ...
    channel_habits: tuple[ChannelHabit, ...] = ()   # additive, defaulted
```

- **Honesty constraint:** OSINT can rarely observe a real person's SMS/Signal habits.
  So `channel_habits` stays **sparse** — assert only what is publicly grounded (a LinkedIn
  presence, a public X handle, a company Slack/Teams/email domain). For everything else,
  the agent uses the **channel-class prior** below, not a fabricated per-person habit.
- Prefer a **derived** `preferred_channels` (a top-N-by-prior *helper/property*) over a
  second stored field, to avoid duplicated truth.

### 6.3 Bandit channel-arm priors — warm-start, **objective- and stage-aware**

The bandit Thompson-samples over arms that include `channel` (see
`mab_experiments/policy.py`); priors are currently uninformed. This recon gives an
empirical **first-contact** engagement prior to warm-start the Beta parameters so the
bandit doesn't re-spend early touches rediscovering obvious facts. **But seed by stage,
not a flat per-channel value**, because *engagement ≠ win* and the confound is real:

- **Opener arms (goal: get any reply to start a multi-touch thread)** — seed optimistic:
  all phone-messaging, work-chat, `linkedin_message`, `linkedin_connection_request`,
  `x_dm`, `facebook_messenger`, `calendar_invite`, and all live channels.
  Seed pessimistic: `email`, `shared_document`, `voicemail`, `mfa_push`, `instagram_dm`.
- **Payload arms (goal: deliver a page/link → credentials/action; look-scored)** — keep
  `email` (and `shared_document`/`calendar_invite`) **optimistic despite cold silence**,
  because the win lands on a *later, grounded* touch and email carries the craft score.
  **Do not let cold-email silence suppress email in the credentials/action arm** — that
  would confuse "cold first-contact" with "warm follow-up with a page."
- **Gate `mfa_push` behind an established pretext** — pessimistic as an opener; only
  reachable as a late-sequence step.

Concretely: give the bandit a two-tier `channel_prior(objective, touch_stage)` seed table
(interactive-favored for openers, email/doc/calendar-favored for payloads) rather than one
per-channel Beta. A starter mapping lives next to the runner so it can be imported by the
seeding code.

### 6.4 Channel *sequence* prior for the playbook

The data operationalizes the docs' "attack that holds up over several touches":

1. **Open** on an interactive channel (sms / slack / linkedin_connection_request / live)
   → earns the "which company are you with?" reply.
2. **Answer** with a grounded identity + hook from the Dossier's `senders` / `hooks`.
3. **Escalate to email** (the channel they *trust and ask you to use*) for the payload.

Neither the Dossier nor the bandit currently encodes a channel *sequence*. The existing
reply-aware threading + the stage-aware priors in §6.3 approximate it; an explicit
`channel_sequence` hint is a possible later addition (propose, don't build yet).

### 6.5 Archetype vocabulary (coordination note)

Real research (`research.seeds.default_provider`, PR #2) emits archetypes
`executive_founder / technical_leader / product_leader / finance / commercial / generic`.
The practice mapping is julius→executive_founder, tom→product_leader, robert→technical_leader.
Keep one context vocabulary in the bandit (the MAB session already flagged this) — the
channel priors above are archetype-agnostic until data says otherwise.

---

## 7. Reproduce

```bash
uv venv --python 3.12 && uv pip install -e '.[dev]'
set -a && source .env && set +a            # REVEL8_API_KEY / REVEL8_API_BASE
python -m experiments.channel_recon         # all 22 channels → runs/channel_recon/
python -m experiments.channel_recon --only email,sms,phone_call --workers 2
```

Each probe is one touch in its own session; the full sweep is ~22 sessions (mind the
team-wide 60/hr cap when sibling runs are active).
