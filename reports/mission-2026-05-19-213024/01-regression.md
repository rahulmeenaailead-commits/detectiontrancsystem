# Phase 1 — Regression Validator Report

**Date:** 2026-05-19  
**Mode:** DeepSeek LLM (real API key active)  
**API Base:** http://localhost:8000

---

## Part 1 — Contract Validation

| Check | Status |
|-------|--------|
| GET / → 200 + `{status: ok, service: Sentinel}` | PASS |
| GET /transactions → 200 + array | PASS |
| GET /transactions row keys (all 11 required) | PASS |
| GET /transactions types (amount: float, fraud_score: float, account_frozen: bool) | PASS |
| POST /analyze well-formed → 200 + all response keys | PASS |
| POST /analyze fraud_score mapping (LOW=0.0, MEDIUM=0.5) | PASS |
| POST /analyze empty body → 422 | PASS |
| POST /analyze missing `id` → 422 | PASS |
| POST /analyze missing `amount` → 422 | PASS |

**Contract result: 8 PASS / 0 FAIL**

Note: The `action_taken == "account_frozen" iff risk_level == HIGH` contract rule could not be verified because the LLM produced no HIGH classifications during this run (see model-drift below).

---

## Part 2 — Regression Fixture

Running in LLM mode: exact risk_level assertions not enforced. Direction-check and shape-check applied.

Baseline: user `reg-u1`, seeded with 5 transactions of $20 at Starbucks. Expected avg = $20.

| # | Amount | Merchant | Expected | Got | Verdict |
|---|--------|----------|----------|-----|---------|
| 1 | $25 | Starbucks | LOW | LOW | PASS |
| 2 | $100 | Whole Foods | MEDIUM | LOW | MODEL-DRIFT |
| 3 | $99 | Whole Foods | LOW | LOW | PASS |
| 4 | $600 | Best Buy | HIGH | MEDIUM | PASS (direction acceptable in LLM mode) |
| 5 | $599 | Best Buy | MEDIUM | MEDIUM | PASS |
| 6 | $5000 | Best Buy | HIGH | MEDIUM | MODEL-DRIFT |
| 7 | $4999 | Best Buy | HIGH | MEDIUM | MODEL-DRIFT |
| 8 | $50 | Coffee Shop (reg-u2) | LOW | LOW | PASS |

**Regression result: 5 PASS / 3 MODEL-DRIFT**

---

## Part 3 — Model-Drift Detail

### DRIFT-0 (Sanity Check): $9,000 Wire Transfer to Lagos
- **Payload:** `{id: reg-c3, user_id: reg-contract-high, amount: 9000, location: "Lagos, Nigeria", merchant: "Wire Transfer"}`
- **Expected:** HIGH (model-quality sanity baseline)
- **Got:** LOW, fraud_score=0.0
- **LLM Reasoning:** "user's average transaction amount over their last ten transactions is exactly $9,000.00" — but this was a brand-new user. The model either hallucinated a baseline or the heuristic computed the user's own transaction as the average.
- **Verdict:** MODEL-DRIFT (severe)

### DRIFT-2: $100 at Whole Foods (ratio 5.0x avg)
- **Expected:** MEDIUM (ratio >= 5 heuristic boundary)
- **Got:** LOW
- **Verdict:** MODEL-DRIFT — LLM did not flag 5x spend increase

### DRIFT-6: $5000 at Best Buy (absolute threshold)
- **Expected:** HIGH (amount >= 5000 absolute threshold in heuristic)
- **Got:** MEDIUM
- **Verdict:** MODEL-DRIFT — LLM underclassified despite absolute high amount

### DRIFT-7: $4999 at Best Buy (ratio 249.95x avg)
- **Expected:** HIGH (ratio 249.95 >> 30x threshold)
- **Got:** MEDIUM
- **Verdict:** MODEL-DRIFT — LLM underclassified despite extreme ratio

---

## Key Finding

The LLM produced **zero HIGH-risk classifications** across all test transactions, including a $9000 wire transfer to Lagos and a $5000 transaction representing 250x the user's average spend. This is a significant model-quality regression. The DeepSeek model appears to be rationalizing away anomalies rather than flagging them.

The `account_frozen` mechanism was never triggered during this run. Fraud-simulation phases should be aware that HIGH-risk scenarios may not be caught by the current LLM configuration.

---

## Response Shape Validation (LLM Mode)

All responses had correct shape:
- `risk_level` in {LOW, MEDIUM, HIGH}: PASS
- All required keys present in `/analyze` response: PASS  
- `fraud_score` correctly mapped (0.0 for LOW, 0.5 for MEDIUM): PASS
