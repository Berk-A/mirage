#!/usr/bin/env bash
# Thin wrapper over the revel8 target API for driving it by hand from the terminal.
#
#   export REVEL8_API_KEY=...        (or: set -a; source .env; set +a)
#   scripts/api.sh scenarios
#   scripts/api.sh new practice
#   scripts/api.sh send <sid> julius email "Subject" "Body text"
#   scripts/api.sh events <sid>
#
# Sender identity can be overridden per call:
#   FROM_NAME="Lena Hofer" FROM_ADDR="lena.hofer@eventcrew-muc.de" scripts/api.sh send ...
set -euo pipefail

BASE="${REVEL8_API_BASE:-https://target-api.apps.01.cf.eu01.stackit.cloud/v1}"
KEY="${REVEL8_API_KEY:-}"
FROM_NAME="${FROM_NAME:-Lena Hofer}"
FROM_ADDR="${FROM_ADDR:-lena.hofer@eventcrew-muc.de}"

usage() { sed -n '2,13p' "$0"; }
case "${1:-help}" in help|-h|--help) usage; exit 0 ;; esac

if [[ -z "$KEY" ]]; then
  echo "REVEL8_API_KEY is not set. Run: set -a; source .env; set +a" >&2
  exit 1
fi

# curl with auth, JSON, a generous timeout (persona model can take up to 90s),
# and a fresh Idempotency-Key per call so a retry never double-spends a touch.
req() {
  local method="$1" path="$2" data="${3:-}"
  local -a args=(-sS -X "$method" "${BASE}${path}"
    -H "Authorization: Bearer ${KEY}"
    -H "Content-Type: application/json"
    -H "Idempotency-Key: $(uuidgen)"
    --max-time 150)
  [[ -n "$data" ]] && args+=(-d "$data")
  curl "${args[@]}"
}

pretty() { jq . 2>/dev/null || cat; }

cmd="${1:-help}"; shift || true
case "$cmd" in
  scenarios) req GET /scenarios | pretty ;;
  channels)  req GET /channels  | pretty ;;
  sessions)  req GET /sessions  | pretty ;;

  new)  # new <scenario_id=practice>
    req POST /sessions "$(jq -nc --arg s "${1:-practice}" '{scenario_id:$s}')" | pretty ;;

  session)  req GET "/sessions/$1" | pretty ;;          # session <sid>
  events)   req GET "/sessions/$1/events" | pretty ;;   # events  <sid>
  end)      req POST "/sessions/$1/end" | pretty ;;     # end     <sid>

  send)  # send <sid> <to> <channel> <subject> <body>
    sid="$1"; to="$2"; channel="$3"; subject="${4:-}"; body="${5:-}"
    payload=$(jq -nc \
      --arg to "$to" --arg ch "$channel" --arg sub "$subject" --arg body "$body" \
      --arg fn "$FROM_NAME" --arg fa "$FROM_ADDR" \
      '{to:$to, channel:$ch, from:{name:$fn, address:$fa}, body:$body}
       + (if $sub == "" then {} else {subject:$sub} end)')
    req POST "/sessions/$sid/messages" "$payload" | pretty ;;

  page)  # page <sid> <url> <title> <field1> [field2 ...]
    sid="$1"; url="$2"; title="$3"; shift 3
    fields=$(printf '%s\n' "$@" | jq -R . | jq -sc .)
    payload=$(jq -nc --arg u "$url" --arg t "$title" --argjson f "$fields" \
      '{url:$u, title:$t, fields:$f}')
    req POST "/sessions/$sid/pages" "$payload" | pretty ;;

  raw)  # raw <METHOD> <path> [json-body]    e.g. raw GET /scenarios
    req "$1" "$2" "${3:-}" | pretty ;;

  help|*)
    sed -n '2,13p' "$0" ;;
esac
