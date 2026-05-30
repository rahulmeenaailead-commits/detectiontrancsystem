#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
API_KEY="${SENTINEL_API_KEY:-sentinel-dev-key}"

post () { # $1 = JSON body
  curl -sS -X POST "$API_URL/analyze" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "$1" | head -c 200
  echo
}

echo "Sending 5 normal transactions to $API_URL ..."
# Distinct user per txn: the velocity rule freezes a user at 5 txns / 5 min, so
# hammering a single id would flip the 5th "normal" txn to HIGH.
for i in 1 2 3 4 5; do
  amount=$((40 + RANDOM % 30))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  post "{\"id\":\"normal-$i-$RANDOM\",\"user_id\":\"normal-u$i\",\"amount\":$amount,\"location\":\"NYC\",\"timestamp\":\"$ts\",\"merchant\":\"Coffee Shop\"}"
  sleep 0.3
done

echo
echo "Sending 3 HIGH-risk transactions ..."
LOCATIONS=("Lagos, Nigeria" "Pyongyang, DPRK" "Tehran, Iran")
MERCHANTS=("Unknown Wire Transfer" "Crypto Exchange XYZ" "Offshore Holdings Ltd")
# Distinct fresh user per HIGH txn: a HIGH verdict freezes that account, so each
# needs its own id — otherwise the 2nd and 3rd would hit 423 Locked. This also
# lets the dashboard's "Accounts frozen" counter climb to 3.
for i in 0 1 2; do
  amount=$((5000 + RANDOM % 10000))
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  post "{\"id\":\"attack-$i-$RANDOM\",\"user_id\":\"attack-u$i\",\"amount\":$amount,\"location\":\"${LOCATIONS[$i]}\",\"timestamp\":\"$ts\",\"merchant\":\"${MERCHANTS[$i]}\"}"
  sleep 0.3
done

echo
echo "Done. Open http://localhost:3000 to see the dashboard."
