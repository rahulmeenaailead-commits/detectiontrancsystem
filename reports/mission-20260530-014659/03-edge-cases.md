# Phase 3 — Edge Case Hunter Report

**Mode:** heuristic (no DEEPSEEK_API_KEY)
**Date:** 2026-05-30
**Cases run:** 23

---

## Results Table

| # | Case | Sent | Status | Got | Verdict |
|---|------|------|--------|-----|---------|
| 1 | amount=0 | amount=0 | 422 | gt=0 validation error | PASS |
| 2 | amount=0.01 (min positive) | amount=0.01 | 200 | LOW | PASS |
| 3 | amount=4999.99 (just under $5k hard threshold) | amount=4999.99, new user | 200 | LOW | SURPRISE |
| 4 | amount=5000.00 (exact hard threshold) | amount=5000.00 | 200 | HIGH | PASS |
| 5 | amount=-100 (negative) | amount=-100 | 422 | gt=0 validation error | PASS |
| 6 | amount=1e15 (huge) | amount=1e15 | 422 | le=1e12 validation error | PASS |
| 7 | new user ratio=29.99 (2999/baseline 100) | amount=2999, new user | 200 | LOW | SURPRISE |
| 8 | new user ratio=30.0 (3000/baseline 100) -> HIGH | amount=3000, new user | 200 | LOW | SURPRISE |
| 9 | avg~50 user amount=1499 (ratio<30) | amount=1499, 3x$50 history | 200 | LOW | PASS |
| 10 | avg~50 user amount=1500 (ratio=30.0) -> HIGH | amount=1500, 3x$50 history | 200 | LOW | SURPRISE |
| 11 | missing merchant field | omit merchant | 422 | Field required | PASS |
| 12 | missing user_id field | omit user_id | 422 | Field required | PASS |
| 13 | amount as string "500" | amount="500" | 200 | LOW (coerced 500.0) | SURPRISE |
| 14 | amount=null | amount=null | 422 | Input should be float | PASS |
| 15 | extra unknown field foo=bar | foo="bar" extra | 200 | LOW | PASS |
| 16 | unicode merchant | merchant="☕ Café Münich 北京" | 200 | LOW | PASS |
| 17 | 5000-char location string | location=5000 chars | 422 | max 256 chars | PASS |
| 18 | id with spaces/slash | id="edge id/with spaces" | 200 | LOW | PASS |
| 19 | future timestamp 2099 | timestamp="2099-12-31T23:59:59" | 200 | LOW | PASS |
| 20 | empty string timestamp | timestamp="" | 422 | min 1 char | PASS |
| 21 | non-date timestamp | timestamp="not-a-date" | 200 | LOW | PASS |
| 22 | GET /transactions (state) | GET /transactions | 200 | count=72407 | PASS |
| 23 | frozen user sends txn | second txn to frozen account | 423 | Account frozen | PASS |

**Summary: 16 PASS / 0 FAIL / 7 SURPRISE**

---

## Critical Bug: Insert-Before-Analyze Self-Contamination (BUG-1)

This is the most significant finding. In `main.py`, the call order is:

```python
insert_transaction(transaction)   # line 109 — inserts to DB first
result = analyze_transaction(transaction)  # line 116 — queries DB for avg
```

Inside `analyze_transaction`, `get_user_average(user_id)` runs:

```sql
SELECT AVG(amount) FROM (
    SELECT amount FROM transactions
    WHERE user_id = ?
    ORDER BY timestamp DESC LIMIT 10
)
```

Since the transaction was already inserted, it is included in its own average calculation.

**Effect for new users (first transaction ever):**
- DB avg = the transaction amount itself
- ratio = amount / amount = 1.0
- 1.0 < 5 threshold => always classified LOW

**Proof:** Sending `amount=4999.99` for a fresh user:
- Expected: HIGH (ratio = 4999.99 / 100 baseline = 49.99x)
- Actual: LOW — `"Amount $4999.99 is within normal range (user avg $4999.99)."`

**Effect for established users:**
- The current transaction inflates the rolling average, making large-ratio transactions appear smaller.
- Example: user with avg=$10 sends $300 (expected ratio=30x → HIGH). Actual avg=(10+300)/2=$155, ratio=1.94 → LOW.

**Only reliable detection:** the `amount >= 5000` hard threshold, which does NOT use the ratio and fires before the avg is queried (it's a direct comparison in `_heuristic`). This is confirmed working: `amount=5000.00` → HIGH.

**Fix:** Compute the user average and history BEFORE calling `insert_transaction()`. Then insert. Then call `update_transaction_verdict()` as usual.

---

## Bug Summary

### BUG-1 — CRITICAL: Insert-before-analyze self-contamination
`main.py` inserts the transaction into the DB before querying `get_user_average()`. Every transaction compares against an average that already includes itself, making ratio=1.0 for first transactions and suppressing the ratio-based detector for all users.

**Fix:** Move `insert_transaction()` call to AFTER `analyze_transaction()`, and pass the pre-computed avg separately.

### BUG-2 — HIGH: Ratio threshold effectively dead for sub-$5000 amounts
Directly caused by BUG-1. The ratio-based HIGH threshold (30x) and MEDIUM threshold (5x) are neutralized for any transaction where the amount is below $5000. The detector cannot classify any sub-$5000 transaction as HIGH via ratio — it would require an extreme disparity that survives the dilution from self-inclusion.

**Fix:** Same as BUG-1.

### BUG-3 — MEDIUM: Silent string-to-float coercion for amount field
Pydantic v2 in lax mode coerces `amount="500"` (string) to `500.0` (float) without raising a validation error. API consumers can submit malformed type payloads and have them silently accepted.

**Fix:** Add `model_config = ConfigDict(strict=True)` to the `Transaction` model, or add an explicit type validator.

### BUG-4 — LOW: Zero-division guard in agent.py is dead code
`agent.py:123`: `baseline = avg if avg > 0 else 100.0` — the `else 100.0` branch is unreachable. Pydantic's `gt=0` constraint on `amount` means `amount=0` never reaches the heuristic. And the `avg=0` (new user) case is now always `avg=amount` due to BUG-1.

**Fix:** Remove the dead branch or add a comment explaining it's unreachable. (This would be needed if BUG-1 is fixed, as avg=0 for new users would then be possible again.)

### BUG-5 — LOW: Non-ISO timestamp accepted without validation
`timestamp="not-a-date"` returns 200. `_parse_ts()` returns `None` and velocity/geo checks silently fall back to `datetime.now()`. This can cause velocity windows to be incorrectly computed.

**Fix:** Add Pydantic datetime validator or call `_parse_ts()` in a field validator and reject `None`.

---

## Notable Non-Issues (Behaved Correctly)

- `amount=0` and `amount=-100` both correctly rejected (422) via Pydantic `gt=0`
- `amount=1e15` correctly rejected (422) via Pydantic `le=1e12`; `amount=1e12` accepted as HIGH
- Unicode merchant names round-trip correctly through SQLite
- 5000-char location rejected (422) via `max_length=256`
- Frozen account correctly returns 423 on subsequent transactions
- Duplicate transaction ID correctly returns 409
- Extra unknown fields silently ignored (Pydantic default behavior)
- Future timestamps accepted (no constraint, by design)
