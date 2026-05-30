# Phase 3 — Edge Case Hunter Report

**Date:** 2026-05-30  
**Mode:** Heuristic (no DeepSeek key)  
**Total cases:** 36 | PASS: 27 | FAIL: 0 | SURPRISE: 9

---

## Summary

The Pydantic validation layer is solid for the obvious cases: zero/negative/oversized amounts, missing required fields, empty/whitespace strings, and oversized strings are all correctly rejected with 422. No 5xx crashes were observed. However, five structural bugs were found, two of which are critical to fraud-detection effectiveness.

---

## Results Table

| # | Case | Status | Got | Verdict |
|---|------|--------|-----|---------|
| 1 | amount=0 | 422 | validation error (gt:0) | PASS |
| 2 | amount=0.01 | 200 | LOW | PASS |
| 3 | amount=4999.99 | 200 | LOW | PASS |
| 4 | amount=5000.00 | 200 | HIGH | PASS |
| 5 | amount=5000.01 | 200 | HIGH | PASS |
| 6 | amount=-100 | 422 | validation error | PASS |
| 7 | amount=1e15 | 422 | validation error (le:1e12) | PASS |
| 8 | amount=1e12 (at le limit) | 200 | HIGH | PASS |
| 9 | New user, first txn $3000 (self-contam) | 200 | LOW — "user avg $3000.00" | SURPRISE |
| 10 | New user, first txn $2999 | 200 | LOW | PASS |
| 11 | Established user (3x$10) sends $300 | 200 | LOW (ratio suppressed to 3.6x) | SURPRISE |
| 12 | Ratio=30 needs 31+ seed txns; velocity freeze fires at 5 | N/A | untestable | SURPRISE |
| 13 | amount as JSON string "5000" | 200 | HIGH (silently coerced) | SURPRISE |
| 14 | amount as JSON bool true | 200 | LOW (coerced to 1.0) | SURPRISE |
| 15 | amount as null | 422 | validation error | PASS |
| 16 | missing amount | 422 | Field required | PASS |
| 17 | missing merchant | 422 | Field required | PASS |
| 18 | missing user_id | 422 | Field required | PASS |
| 19 | extra unknown fields | 200 | LOW — extras ignored | PASS |
| 20 | empty merchant "" | 422 | string_too_short | PASS |
| 21 | merchant whitespace-only | 422 | string_too_short (after strip) | PASS |
| 22 | unicode merchant "☕ Café Münich 北京" | 200 | LOW — round-trips correctly | PASS |
| 23 | merchant 256 chars (at limit) | 200 | LOW | PASS |
| 24 | merchant 257 chars (over limit) | 422 | string_too_long | PASS |
| 25 | location 5000 chars | 422 | string_too_long | PASS |
| 26 | id with spaces/slashes | 200 | LOW — stored verbatim | PASS |
| 27 | timestamp future 2099 | 200 | LOW — accepted | PASS |
| 28 | timestamp "not-a-date" | 200 | LOW — accepted, no parse error | SURPRISE |
| 29 | GET /transactions | 200 | 77833 records | PASS |
| 30 | user_id with spaces/slashes | 200 | LOW — stored verbatim | PASS |
| 31 | duplicate transaction id | 409 | Conflict on second | PASS |
| 32 | frozen user re-submission | 423 | Account frozen | PASS |
| 33 | amount bool false (=0) | 422 | validation error | PASS |
| 34 | amount bool true (=1.0) | 200 | LOW, stored as 1 | SURPRISE |
| 35 | 4999.99 vs 5000.00 exact boundary | 200/200 | LOW / HIGH | PASS |
| 36 | user_id 128 vs 129 chars | 200 / 422 | boundary enforced | PASS |

---

## Top 5 Bugs / Recommendations

### BUG-1 (CRITICAL) — Insert-before-analyze self-contamination
`main.py:109` calls `insert_transaction(transaction)` before `agent.py:205` calls `get_user_average`. For a new user's first $3000 transaction, the average is already $3000, so ratio = 1.0 and the result is LOW. The ratio heuristic is completely blind on first transactions and severely suppressed on subsequent ones (a $300 spike after 3x$10 history shows ratio of only 3.6x instead of 30x). The ratio rule is effectively dead code in normal operation.

**Fix:** Call `get_user_average` before `insert_transaction`, or exclude the current transaction ID from the average query.

### BUG-2 (SURPRISE) — String amounts silently coerced
`amount: "5000"` (JSON string) is accepted and processed as float 5000.0 due to Pydantic's default lax coercion for `float` fields. The API returns 200 + HIGH correctly in this case, but it means malformed clients are silently accommodated rather than told to fix their payload.

**Fix:** Add `@field_validator('amount', mode='before')` that raises `ValueError` if `isinstance(v, (str, bool))`.

### BUG-3 (SURPRISE) — Boolean amounts silently coerced
`amount: true` is accepted as 1.0. Same Pydantic lax-mode issue. Same fix as BUG-2.

### BUG-4 (SURPRISE) — Timestamp accepts non-date strings
`timestamp: "not-a-date"` returns 200. The field is typed `str` with no format constraint. When `_parse_ts` fails it returns `None` and the velocity/geo-velocity checks fall back to `datetime.now(utc)`, silently substituting wall-clock time. An attacker sending `timestamp: "1970-01-01T00:00:00"` causes the velocity window to be anchored far in the past, defeating velocity controls.

**Fix:** Use `datetime` type for the field, or add a validator enforcing ISO-8601 format and rejecting strings that do not parse.

### BUG-5 (SURPRISE) — Ratio path is practically unreachable
Mathematical analysis: overcoming self-contamination to reach ratio >= 30 requires N >= 31 prior seed transactions. The velocity freeze fires at 5 transactions within 5 minutes, so no normal user session can build sufficient history through the API to trigger the ratio rule. The `ratio >= RATIO_THRESHOLD` branch in `_heuristic` is dead in practice.

**Fix:** Resolving BUG-1 (compute avg before insert) directly fixes this — the ratio rule then works correctly from the very first transaction.
