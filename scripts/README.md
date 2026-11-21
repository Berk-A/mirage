# scripts — driving the API by hand

`api.sh` is a thin `curl` wrapper so you can poke the revel8 target API from the
terminal before any agent code exists. It reads `REVEL8_API_KEY` and `REVEL8_API_BASE`
from the environment and adds auth, a 150 s timeout, and a fresh `Idempotency-Key` per
call.

## Setup

```bash
cp .env.example .env     # paste your team key into .env (gitignored)
set -a; source .env; set +a
chmod +x scripts/api.sh
```

## The core loop

```bash
scripts/api.sh scenarios                 # who you can target + objectives + touch budget
scripts/api.sh new practice              # -> {"session_id":"s_...","touch_budget":30,...}
SID=s_xxxxxxxxxx

# send a first email (from-name/address default to a placeholder; override with env)
FROM_NAME="Lena Hofer" FROM_ADDR="lena.hofer@eventcrew-muc.de" \
  scripts/api.sh send "$SID" julius email "Speaker logistics for Thursday" "Hi Julius, ..."

scripts/api.sh events "$SID"             # every event so far (reply / link.opened / ...)
scripts/api.sh session "$SID"            # touches_used, status
scripts/api.sh end "$SID"
```

`"events": []` in a `send` response means the person ignored it — follow up, switch
channel, or stop.

## Raw curl equivalents (what the wrapper sends)

```bash
# list scenarios
curl -sS "$REVEL8_API_BASE/scenarios" \
  -H "Authorization: Bearer $REVEL8_API_KEY" | jq .

# open a session
curl -sS -X POST "$REVEL8_API_BASE/sessions" \
  -H "Authorization: Bearer $REVEL8_API_KEY" -H "Content-Type: application/json" \
  -d '{"scenario_id":"practice"}' | jq .

# send a message (allow up to 90s; the persona runs a model)
curl -sS -X POST "$REVEL8_API_BASE/sessions/$SID/messages" \
  -H "Authorization: Bearer $REVEL8_API_KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" --max-time 150 \
  -d '{"to":"julius","channel":"email",
       "from":{"name":"Lena Hofer","address":"lena.hofer@eventcrew-muc.de"},
       "subject":"Speaker logistics for Thursday","body":"Hi Julius, ..."}' | jq .
```

## Things the docs make you care about

- **Touches:** practice = 30/session (unlimited sessions); eval = 10/session, 3 sessions.
  Every message and every conversation turn costs one touch. A whole conversation (up to
  10 turns) costs **one** touch.
- **Only events come back.** Never suspicion. Infer it from replies and silence.
- **Retries:** on 429/502/503/504 wait and retry (same `Idempotency-Key` → no double
  touch). On **400/422 the same body fails again — change it, don't retry.** `422` can
  mean the persona declined.
- **Domains:** lookalike domains for senders/pages are fine; a real org's own domain
  voids the session.

See [`../docs/target-api.md`](../docs/target-api.md) for the full spec (conversations,
landing pages, assets, all channels, error codes).
