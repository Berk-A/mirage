#!/usr/bin/env bash
# One command to run an eval try end-to-end (or a practice e2e).
#   ./scripts/eval.sh                  # one eval try against the eval roster
#   ./scripts/eval.sh --tries 3        # the full 3-try eval
#   ./scripts/eval.sh --scenario practice --targets julius   # practice e2e
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
exec "$PY" -m experiments.run_eval "$@"
