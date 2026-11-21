# Live campaign findings — chasing a real, API-confirmed win

Run with `experiments/live_campaign.py` against the revel8 practice API (authorized
sandbox: AI twins, nothing reaches real people). Every reaction graded by the
API-grounded `mab_experiments.grading.confirmed_incident`. Logs in `runs/campaign_live/`
(gitignored).

## What was tried (10 live contacts across the 3 founders)

| # | target | channel | pretext | result |
|---|--------|---------|---------|--------|
| 1 | tom | email | design-partner sends "questions" PDF for his Q1 webinar | refused: "I'd rather not open attachments cold" |
| 2 | tom | email | referred design candidate asks team size / stack / process | refused → careers page / People & Culture |
| 3 | julius | email | co-panelist compares outbound→PLG numbers | refused: "I don't share CAC or team numbers ahead of time" |
| 4 | julius | email | organiser (Lena Hofer) → speaker-hub login | refused: "I'd rather not set up a new login" |
| 5 | julius | email | organiser sends run-of-show PDF (he'd said PDF ok) | deferred: "I'll hold off on the PDF… put it in the mail text" |
| 6 | julius | email | HubSpot "account paused — verify" phish | ignored (no events) |
| 7 | robert | email | not-for-attribution journalist on the migration | ignored (no events) |
| 8 | robert | email | cloud-provider "re-auth before tonight's cutover" | refused: "no cutover scheduled… not signing in off a mailed link" |
| 9 | julius | phone | analyst, "real story not press", probes CAC/pipeline | deflected numbers; **volunteered "we're still mostly outbound-led, the PLG story is smaller than people think"** |
| 10 | julius | phone | probes in-house vs agency + tooling | ended call: "I don't go through our setup or tools on a first call" |

**API-confirmed wins: 0.** No `page.submitted`, `attachment.opened`, or hard disclosure.
Closest: #9, a soft strategic characterisation — correctly *not* scored by the grader
(no concrete system/number/plan).

## Why nothing landed — the wall is verification, not effort

The personas are well-calibrated. Across email and a live call they consistently:

- refuse attachments, links and new logins from unverified senders;
- **gate on checkable verification** — "who's the organiser?", "send the change ticket /
  contract", "which fund exactly?", "who referred you?" — which *invented* details cannot
  satisfy, because (per the API docs) **the twins can look things up**;
- chat, but won't volunteer hard internal facts (numbers, tools, setup) on a first,
  cold contact;
- recognise obvious phishing (the HubSpot "verify" was ignored).

## What a win actually requires (evidence-based)

1. **Real, checkable OSINT grounding.** Pretexts must reference facts the twin can verify
   (a real event + real organiser, a real vendor relationship, a real mutual contact), so
   the verification gate passes. This is exactly the `research/` pipeline's job; the
   current synthetic dossier is plausible but not web-verifiable, so every bluff stalls.
2. **Patient, multi-touch relationship.** They defer, not refuse — "send me a mail and
   I'll see what I can share." A win is a 2nd/3rd-contact outcome after trust, not a
   one-shot. Julius already cracked the door (#9); the follow-up he invited is the thread
   to work.
3. **Congruent, low-friction concrete asks** once trust exists — open a doc that's clearly
   from a known party, confirm on a portal that matches an expectation they already hold.

This is a real result, not a failure: it quantifies how hard the targets are and shows the
bandit/writer are not the bottleneck — the **grounding + patience** are. Grinding more
cold one-shots burns touches without moving the needle.
