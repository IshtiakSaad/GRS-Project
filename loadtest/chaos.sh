#!/usr/bin/env bash
# Chaos run: stop the task broker (redis-broker) in the middle of steady submissions.
#   loadtest/chaos.sh                       # local stack
#   COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml" loadtest/chaos.sh
# Passes when (1) every submission succeeded while the broker was down, and (2) after it
# came back, every "request received" message was delivered: none lost, none failed.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

C="docker compose ${COMPOSE_FILES:-}"
NETWORK="$($C config --format json | ${PYTHON:-python3} -c 'import json,sys; print(json.load(sys.stdin)["name"])')_default"
DOWN_FOR="${DOWN_FOR:-30}"
PSQL="$C exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -qtA"
SINCE=$($PSQL -c "SELECT now()")

echo "== steady submissions for 100 s; broker stops at 20 s for ${DOWN_FOR} s"
docker run --rm --network "$NETWORK" -e HOST="${GRS_DOMAIN:-localhost}" \
  -e USERS="${USERS:-300}" -e USER_OFFSET="${USER_OFFSET:-0}" \
  -v "${LOADTEST_DIR:-$PWD/loadtest}:/scripts" grafana/k6:1.3.0 run --quiet \
  --summary-export=/scripts/results/chaos-k6.json /scripts/chaos.js &
K6=$!

sleep 20
echo "== $(date -u +%T) stopping redis-broker"
$C stop redis-broker
sleep "$DOWN_FOR"
echo "== $(date -u +%T) starting redis-broker"
$C start redis-broker
wait $K6 && K6_OK=1 || K6_OK=0

echo "== waiting for the sweeper to deliver what the broker missed"
query="SELECT count(*) FILTER (WHERE status IN ('PENDING','LEASED')) || ' ' ||
       count(*) FILTER (WHERE status = 'SENT') || ' ' ||
       count(*) FILTER (WHERE status = 'FAILED') || ' ' || count(*)
       FROM notification WHERE template = 'request_submitted' AND created_at >= '$SINCE'"
for i in $(seq 1 36); do
  read -r pending sent failed total <<<"$($PSQL -c "$query")"
  echo "   t+$((i * 5))s  pending=$pending sent=$sent failed=$failed total=$total"
  [ "$pending" = "0" ] && break
  sleep 5
done

echo
if [ "$K6_OK" = "1" ] && [ "$pending" = "0" ] && [ "$failed" = "0" ] && [ "$total" -gt 0 ]; then
  echo "PASS: $total submissions during the outage, $sent messages delivered, 0 lost, 0 failed"
else
  echo "FAIL: k6_ok=$K6_OK pending=$pending failed=$failed total=$total" >&2
  exit 1
fi
