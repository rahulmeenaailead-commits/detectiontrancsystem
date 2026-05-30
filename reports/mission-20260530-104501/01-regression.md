# Phase 1 — Regression Validator Report
**Date:** 2026-05-30 | **Mode:** Effective Heuristic (DeepSeek key set but non-functional)

---

## Overall Result: MIXED

- Contract: **16 PASS / 1 FAIL**
- Regression: **4 PASS / 4 FAIL**
- Schema valid: YES
- Classification drift: YES (self-contamination bug)

---

## Part 1 — Contract Validation

| Check | Result |
|-------|--------|
| GET / returns 200 + {status:ok, service:Sentinel} | PASS |
| GET / body shape correct | PASS |
| GET /transactions returns 200 + array | PASS |
| GET /transactions — all 11 required keys present | PASS |
| GET /transactions — amount is number (float) | PASS |
| GET /transactions — fraud_score is number (float) | PASS |
| GET /transactions — account_frozen is bool | PASS |
| GET /transactions — risk_level in {LOW,MEDIUM,HIGH} | PASS |
| GET /transactions — auth required (401 without key) | PASS |
| POST /analyze 200 on well-formed body | PASS |
| POST /analyze response keys present | PASS |
| POST /analyze fraud_score mapping (HIGH=1.0) | PASS |
| POST /analyze action_taken=account_frozen iff HIGH+frozen | PASS |
| POST /analyze empty body -> 422 | PASS |
| POST /analyze missing id -> 422 | PASS |
| POST /analyze missing amount -> 422 | PASS |
| **POST /unfreeze retroactively mutates transaction records** | **FAIL** |

### Contract FAIL — Audit Trail Mutation

`unfreeze_user()` in `database.py` line 151-153 executes:
```sql
UPDATE transactions SET account_frozen=0, action_taken='unfrozen'
WHERE user_id=? AND account_frozen=1
```
This overwrites the original HIGH-risk transaction's `action_taken` field from `"account_frozen"` to `"unfrozen"` and flips `account_frozen` to `False`. The audit trail is destroyed: after an unfreeze, `GET /transactions` shows no evidence that any account was ever frozen. Observed on transaction `reg2-t6` ($5000 Best Buy, HIGH risk).

---

## Part 2 — Regression Fixture

**Mode:** Effective heuristic (DEEPSEEK_API_KEY set but key is non-functional; fallback silently active)

**Self-contamination confirmed:** `main.py` calls `insert_transaction()` at line 109 BEFORE `analyze_transaction()` at line 116. The new transaction is therefore included in `get_user_average()` when computing its own risk baseline.

**Seed:** 5 x $20 at Starbucks for user `reg2-u1` (all LOW, confirmed).

| # | Amount | Merchant | Expected | Actual | Verdict | Notes |
|---|--------|----------|----------|--------|---------|-------|
| 1 | $25 | Starbucks | LOW | LOW | PASS | Post-insert avg=$20.83, ratio=1.20 |
| 2 | $100 | Whole Foods | MEDIUM | LOW | FAIL | Post-insert avg=$32.14, ratio=3.11 < 5 |
| 3 | $99 | Whole Foods | LOW | LOW | PASS | ratio well below 5 |
| 4 | $600 | Best Buy | HIGH | MEDIUM | FAIL | Pre-insert avg=$40.50 (ratio=14.81), post=$102.67 (ratio=5.84) — 30x threshold missed both ways |
| 5 | $599 | Best Buy | MEDIUM | LOW | FAIL | Post-insert avg=$152.30, ratio=3.93 < 5 |
| 6 | $5000 | Best Buy | HIGH | HIGH | PASS | Absolute $5000 threshold hit regardless |
| 7 | $4999 | Best Buy | HIGH | LOW | FAIL | $1 below absolute; baseline inflated to ~$593 by prior txns, ratio=8.43 < 30 |
| 8 | $50 | Amazon (new user reg2-u2) | LOW | LOW | PASS | Baseline $100 (no history), ratio=0.5 |

### Key Finding — Self-Contamination Bug

The insert-before-analyze ordering causes a snowball effect through the test sequence:

1. T1 ($25) raises baseline from $20.00 to $20.83
2. T2 ($100) further raises to $32.14 — ratio drops from expected 4.80 to actual 3.11
3. T3 ($99) raises to $40.50
4. T4 ($600) raises to $102.67 — ratio drops from 14.81 to 5.84 (MEDIUM not HIGH)
5. T5 ($599) raises to $152.30 — ratio drops to 3.93 (LOW not MEDIUM)
6. T6 ($5000) raises to ~$593 — absolute threshold saves this one
7. T7 ($4999) — baseline now ~$593, ratio=8.43; amount $1 below absolute; both thresholds missed

**Verdict:** The ratio-based HIGH threshold (30x) is effectively unreachable in practice once a user has any transaction history. The only reliable HIGH trigger is the $5000 absolute threshold.

### Account Frozen Verification

Only T6 ($5000) was correctly flagged HIGH and frozen at analysis time. Post-unfreeze, the record shows `account_frozen=False, action_taken='unfrozen'` — the audit mutation bug confirmed.

---

## Mode Detection Note

The `DEEPSEEK_API_KEY` in `backend/.env` is `[REDACTED]` — a non-placeholder value. The agent code sets `_use_deepseek=True` and attempts real LLM calls. However, 100% of response explanations match the exact heuristic template strings. The key is either invalid/expired, causing silent fallback to heuristic via the exception handler at `agent.py` line 243.

---

## Summary for Phase 2

- Effective mode: heuristic (deterministic)
- $5000 absolute threshold is the only reliable HIGH trigger
- 30x ratio threshold is compromised by self-contamination
- Velocity/geo-velocity/structuring rules are active and may fire independently
- DB contains 77k+ prior transactions — use fresh user ID prefixes
- /unfreeze retroactively mutates transaction records (audit trail unreliable)
