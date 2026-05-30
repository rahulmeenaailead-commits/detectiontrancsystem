# Phase 4 — Attack Scenario Coverage Report

**Mode:** DeepSeek LLM (real API key active)
**Date:** 2026-05-19
**Agent:** attack-scenario-runner

---

## Coverage Matrix

| Scenario | Expected | Got | Account Frozen | Verdict |
|---|---|---|---|---|
| card-testing | MEDIUM/HIGH | LOW (all 10) | no | MISS |
| account-takeover | HIGH | MEDIUM | no | MISS |
| structuring/smurfing | HIGH | LOW (all 6) | no | MISS |
| mule-transfer | HIGH + frozen | HIGH + frozen | yes | CATCH |
| geo-impossible | HIGH (tx2) | LOW (both) | no | MISS |
| merchant-anomaly | HIGH | MEDIUM | no | PARTIAL-MISS |

**Detected: 1 / 6 | Coverage: 16.7%**

---

## Scenario Detail

### 1. Card Testing (card-u1)

10 probing transactions ranging $1.00–$8.75 at varied merchants (Amazon, Shell Gas, McDonald's, Uber, etc.), sent 30 seconds apart. All 10 returned **LOW**. No velocity detection exists — Sentinel evaluates each transaction in isolation against the user's amount average. The pattern as a whole is a textbook card-testing attack but is completely invisible to the system.

**True risk:** MEDIUM/HIGH (velocity + low-amount probe pattern)
**Got:** LOW x10

---

### 2. Account-Takeover (ato-u1)

Baseline: 8 transactions at $8.50–$45.00 (avg $24.09) at Dunkin Donuts, Starbucks, Whole Foods, CVS, etc.
Attack: $4500.00 at "Luxury Watches Ltd", Dubai, UAE, at 03:17.

**True ratio: 186.8x** (well above the 30x HIGH threshold).

BUG-1 (self-contamination) inflated the average to $521.42 (9 txns including the attack), deflating the shown ratio to **8.6x -> MEDIUM** instead of HIGH. The foreign location (Dubai) and unusual hour (03:17) were mentioned in the explanation but the LLM did not escalate to HIGH with only 8.6x ratio.

**Expected:** HIGH + account frozen
**Got:** MEDIUM, not frozen
**Root cause:** BUG-1 ratio contamination. Fix: compute avg BEFORE INSERT.

---

### 3. Structuring / Smurfing (smurf-u1)

6 transactions at $4950–$4999, each just below the $5000 absolute threshold, at different merchants (Casino Royale, Hotel Grand, Jewelry Palace, Car Rentals Plus, Electronics Hub, Travel Agency).

All 6 returned **LOW**. The absolute threshold rule never fired (each < $5000). Self-contamination made the ratio ~1.0 for every transaction (all similar amounts). Total laundered: **$29,869.50** without a single flag.

**Expected:** HIGH (structuring/structuring pattern)
**Got:** LOW x6
**Root cause:** No sub-threshold aggregation rule. The $5000 threshold is trivially bypassed by staying at $4999.

---

### 4. Mule Transfer (mule-u1)

Single transaction: $9000.00 at "Unknown Wire Transfer", Lagos, Nigeria.

**Result: HIGH + account_frozen = CATCH.**

The $5000 absolute threshold rule fired correctly. DeepSeek also identified the high-risk corridor and suspicious merchant. Note: self-contamination still occurred (ratio shown as 1.0 on new user) but the amount rule was sufficient.

**Explanation:** "Transaction of $9000.00 at Unknown Wire Transfer (Lagos, Nigeria) is 1.0x this user's recent average of $9000.00. The amount, location, and merchant pattern are strongly inconsistent with the user's baseline behavior. Recommend immediate account freeze pending customer verification."

---

### 5. Geo-Impossible (geo-u1)

- tx1: $40, Cafe Local, New York, NY (T)
- tx2: $40, Cafe Local, Tokyo, Japan (T+90s) — ~10,900 km gap

Both returned **LOW**. Sentinel has no mechanism to compare the current transaction's location against prior transactions for the same user. The LLM received only the current transaction's context, not the prior NYC transaction, so it had no signal to detect the impossibility.

**Expected:** HIGH on tx2 (implied speed ~440,000 km/h — physically impossible)
**Got:** LOW (both)
**Root cause:** No geo-velocity check. Prior transaction data is not passed to the agent.

---

### 6. Merchant Anomaly (merch-u1)

Baseline: 10 transactions at $6.25–$25.00 at Starbucks and Whole Foods (avg $12.75).
Attack: $800.00 at "Crypto Exchange ZZZ", same city, normal hour.

**True ratio: 62.7x** (should be HIGH). BUG-1 again inflated avg to $91.17 (11 txns including attack), deflating ratio to **8.8x -> MEDIUM**. DeepSeek noted crypto exchange in explanation but returned MEDIUM, not HIGH.

**Expected:** HIGH (62x ratio + merchant category mismatch)
**Got:** MEDIUM, not frozen
**Root cause:** BUG-1. With correct avg ($12.75), ratio = 62.7x, heuristic fires HIGH.

---

## Gaps

- **GAP-1 — No transaction velocity detection** (card-testing)
  Fix: Rolling count per user_id over 5-minute window. >= 5 txns in 5 min -> MEDIUM; >= 8 -> HIGH. Weight when all amounts < $15.

- **GAP-2 — BUG-1 self-contamination defeats ratio detection** (ATO, merchant-anomaly)
  Fix: In main.py, call get_user_average BEFORE the INSERT. Fixes ATO (186.8x -> HIGH) and merchant-anomaly (62.7x -> HIGH).

- **GAP-3 — No location-change escalation** (ATO)
  Fix: If current location not in user's prior locations AND ratio > 5x -> escalate to HIGH. Pass location history to LLM prompt.

- **GAP-4 — No sub-threshold aggregation / structuring detection** (smurfing)
  Fix: Rolling 24h sum per user_id. If 3+ transactions in $4500-$5000 range within 1 hour, or 24h sum > $10,000 -> HIGH structuring flag.

- **GAP-5 — No geo-velocity check** (geo-impossible)
  Fix: Fetch prior transaction location + timestamp for user. Compute haversine distance. If implied speed > 900 km/h -> HIGH. Pass prior location/timestamp to LLM as context.

- **GAP-6 — No merchant category baseline** (merchant-anomaly, secondary)
  Fix: Fix BUG-1 first. Optionally pass user's top 3 historical merchants to LLM prompt as context for category-shift detection.

---

## Summary

The sole detection was mule-transfer, which succeeded only because the $9000 amount triggered the absolute $5000 threshold — not because of any contextual reasoning about the user's baseline. Every other scenario required either temporal context (velocity, geo) or correct ratio computation (which BUG-1 defeats), neither of which Sentinel currently provides.

**4 of 5 missed detections are directly caused by two root bugs:**
1. BUG-1 (self-contamination) — exploitable by any new user to launder ATO and merchant-anomaly attacks.
2. No temporal/spatial context propagation to the detection agent.

