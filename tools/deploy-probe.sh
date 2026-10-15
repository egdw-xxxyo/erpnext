#!/bin/bash
# Counts what users would see during a deploy. Start it before the deploy, stop
# it (Ctrl-C, or `kill` when it runs in the background — a background job does
# not get SIGINT) or let it run out after; it prints every failed request as it
# happens and a summary at the end. Exit status 0 only when nothing failed.
#
#   tools/deploy-probe.sh [base-url] [seconds]
#   tools/deploy-probe.sh http://localhost:8080 600
#
# Four request classes, because they break for different reasons:
#   get     GET  /api/method/ping       backend reachable
#   post    POST /api/method/ping       a non-idempotent request, which nginx never retries
#   asset   a hashed bundle captured at start   a tab loaded before the deploy keeps its files
#   socket  GET  /socket.io polling     realtime routing
#
# "slow" (over 2s) is expected around the cutover and is not a failure.

BASE="${1:-http://localhost:8080}"
DURATION="${2:-0}"
SLOW_MS=2000

ASSET=$(curl -s -m 15 "$BASE/login" | grep -oE '/assets/[A-Za-z0-9_./-]+\.bundle\.[A-Z0-9]+\.(js|css)' | head -1)
if [ -z "$ASSET" ]; then
  echo "probe: no hashed bundle found on $BASE/login — is the site up?" >&2
  exit 2
fi
echo "probe: $BASE, asset $ASSET"

TOTAL=0
BAD=0
SLOW=0
START=$(date +%s)

summary() {
  echo "probe: total=$TOTAL bad=$BAD slow=$SLOW seconds=$(($(date +%s) - START))"
  [ "$BAD" -eq 0 ]
  exit $?
}
trap summary INT TERM

check() {
  local name="$1" want="$2" out code ms
  shift 2
  out=$(curl -s -o /dev/null -m 15 -w '%{http_code} %{time_total}' "$@" 2>/dev/null)
  code="${out%% *}"
  ms=$(awk -v t="${out##* }" 'BEGIN {printf "%d", t * 1000}')
  TOTAL=$((TOTAL + 1))
  if [ "$code" != "$want" ]; then
    BAD=$((BAD + 1))
    echo "$(date +%H:%M:%S) BAD  $name code=$code ${ms}ms"
  elif [ "$ms" -gt "$SLOW_MS" ]; then
    SLOW=$((SLOW + 1))
    echo "$(date +%H:%M:%S) slow $name ${ms}ms"
  fi
}

while :; do
  check get 200 "$BASE/api/method/ping"
  check post 200 -X POST "$BASE/api/method/ping"
  check asset 200 "$BASE$ASSET"
  check socket 200 "$BASE/socket.io/?EIO=4&transport=polling"
  if [ "$DURATION" -gt 0 ] && [ $(($(date +%s) - START)) -ge "$DURATION" ]; then
    summary
  fi
  sleep 0.2
done
