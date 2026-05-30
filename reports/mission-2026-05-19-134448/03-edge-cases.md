# Edge-Case Hunter — Phase 3 Report

**Date:** 2026-05-19  
**Mode:** DeepSeek (real API key active)  
**IDs used:** `ec2-*` / `ec2-u*` (fresh, no collision with prior phases)  
**Total cases:** 21 | **PASS:** 12 | **FAIL:** 4 | **SURPRISE:** 5

---

## Results Table

| # | Case | Sent | Status | Got | Verdict |
|---|------|------|--------|-----|---------|
| 1 | amount=0 | new user, amount=0 | 200 | LOW (avg=0→baseline=100, ratio=0) | PASS |
| 2 | amount=0.01 | new user, amount=0.01 | 200 | LOW (avg=$0.01 self-contaminated, ratio=1.0) | SURPRISE |
| 3 | amount=4999.99 | new user, amount=4999.99 | 200 | LOW (avg=$4999.99 self-contaminated, ratio=1.0) | FAIL |
| 4 | amount=5000.00 | new user, amount=5000.00 | 200 | HIGH (amount>=5000 rule fires) | PASS |
| 5 | amount=-100 | new user, amount=-100 | 200 | LOW (avg=-100→baseline=100, ratio=-1.0) | SURPRISE |
| 6 | amount=1e15 | new user, amount=1e15 | 200 | HIGH (amount>=5000, no overflow) | PASS |
| 7a | ratio=29.99 new user | amount=2999, baseline should be 100 | 200 | LOW (self-contaminated avg=$2999, ratio=1.0) | FAIL |
| 7b | ratio=30.0 new user | amount=3000, baseline should be 100 | 200 | LOW (self-contaminated avg=$3000, ratio=1.0) | FAIL |
| 8a | ratio=29.98 seeded avg | amount=1499, user seeded at $50 | 200 | MEDIUM (avg=$291.50 diluted, ratio=5.1) | SURPRISE |
| 8b | ratio=30.0 seeded avg | amount=1500, user seeded at $50 | 200 | MEDIUM (avg=$291.67, ratio=5.1 — missed HIGH) | FAIL |
| 9 | missing merchant | no merchant field | 422 | Field required | PASS |
| 10 | missing user_id | no user_id field | 422 | Field required | PASS |
| 11 | amount as string "500" | amount="500" | 200 | LOW (Pydantic coerced to 500.0) | PASS |
| 12 | amount=null | amount=null | 422 | float_type error | PASS |
| 13 | extra field foo=bar | extra foo field | 200 | LOW (field silently ignored) | PASS |
| 14 | unicode merchant | merchant="☕ Café Münich 北京" | 200 | LOW (unicode stored/returned correctly) | PASS |
| 15 | 5000-char location | location=5000×"A" | 200 | LOW (all 5000 chars stored, no truncation) | SURPRISE |
| 16 | id with spaces/slash | id="ec2 16/test" | 200 | LOW (accepted, stored verbatim) | PASS |
| 17 | future timestamp 2099 | timestamp="2099-12-31T23:59:59" | 200 | LOW (no validation) | PASS |
| 18 | empty timestamp | timestamp="" | 200 | LOW (empty string stored) | SURPRISE |
| 19 | non-date timestamp | timestamp="not-a-date" | 200 | LOW (garbage stored) | PASS |
| 20 | GET /transactions | empty-looking call | 200 | 126 transactions returned | PASS |
| 21 | HIGH txn on frozen user | second HIGH to frozen account | 200 | HIGH, action_taken=account_frozen (re-freeze) | SURPRISE |

---

## Bugs and Recommendations

### BUG-1 (Critical) — Self-contamination of user average baseline

**Root cause:** `main.py:34-46` INSERTs the transaction into SQLite before `agent.py:74` calls `get_user_average`. The average query (`database.py:37-49`) includes the just-inserted row. Every first-time user therefore has `avg = amount`, making `ratio = 1.0`, which defeats all ratio-based detection.

**Evidence:**
- Case 7b: $3000 to a brand-new user (should be 30x baseline=100 → HIGH) returned LOW with explanation "Amount $3000.00 is within normal range (user avg $3000.00)."
- Case 3: $4999.99 to a new user returned LOW.
- Case 8b: seeded user with 5× $50 transactions then sent $1500 — the avg became $291.67 (6 txns including current), ratio=5.1 → MEDIUM instead of HIGH.

**Fix:** Move the `get_user_average` call (or pass its result) to before the INSERT in `main.py`, or exclude the current `transaction.id` from the avg subquery:
```sql
SELECT AVG(amount) FROM (
    SELECT amount FROM transactions
    WHERE user_id = ? AND id != ?
    ORDER BY timestamp DESC LIMIT 10
)
```

---

### BUG-2 (High) — Duplicate transaction ID causes unhandled 500

**Root cause:** The `INSERT INTO transactions` in `main.py` has no exception handling. When a duplicate `id` is sent (SQLite UNIQUE PRIMARY KEY violation), an `IntegrityError` propagates uncaught, returning a bare 500 with body `Internal Server Error`.

**Evidence:** Re-submitting any previously used transaction ID returns 500 immediately.

**Fix:** Wrap the INSERT in `try/except sqlite3.IntegrityError` and return HTTP 409 Conflict, or use `INSERT OR IGNORE` plus a subsequent SELECT to return the existing record.

---

### BUG-3 (Medium) — Negative amounts accepted and classified LOW

**Root cause:** The `Transaction` Pydantic model has no `ge=0` constraint on `amount`. A negative amount produces a negative user average, which triggers the `baseline = avg if avg > 0 else 100.0` guard, yielding `ratio = -100/100 = -1.0`. Neither threshold (`>= 30` or `>= 5`) fires, so classification falls through to LOW. The explanation reads "Amount $-100.00 is within normal range."

**Fix:** Add `amount: float = Field(..., ge=0)` (or `gt=0`) in `models.py`.

---

### BUG-4 (Low) — No field length limits; 5000-char location stored without truncation

**Root cause:** No `max_length` on any string field in `models.py`. The 5000-character location string was accepted, stored in SQLite, echoed back verbatim, and sent in its entirety to the DeepSeek LLM prompt. This inflates token costs and could trigger rate-limit errors or prompt truncation by the LLM.

**Fix:** Add `Field(..., max_length=255)` (or similar) for `location`, `merchant`, `timestamp`, and `id`.

---

### BUG-5 (Low) — Empty and non-date timestamps accepted silently

**Root cause:** `timestamp` is typed as `str`, not `datetime`. Empty string `""` and `"not-a-date"` both pass Pydantic validation, are stored verbatim, and are passed to the LLM prompt. The `ORDER BY timestamp DESC` sort in `list_transactions` produces undefined ordering for malformed values.

**Fix:** Type `timestamp` as `datetime` in `models.py` (Pydantic v2 will validate ISO-8601 automatically), or add a `field_validator`.

---

### BUG-6 (Informational) — Frozen users re-frozen redundantly on each subsequent HIGH transaction

**Root cause:** `freeze_user()` executes unconditionally whenever `risk == "HIGH"`. There is no pre-check for existing frozen status. The transaction is processed normally and `action_taken` is always set to `"account_frozen"` even if the account was already frozen.

**Impact:** Extra DB writes on every HIGH transaction for a frozen account; `action_taken` field is misleading (implies a new action occurred). A frozen-account check could also be a useful early-exit for compliance workflows.

**Fix:** In `agent.py`, before calling `freeze_user`, query whether the user is already frozen and set `action_taken = "already_frozen"` if so.

---

## Key Structural Note

The explanations returned in DeepSeek mode match the heuristic template verbatim for all cases ("Amount $X is within normal range (user avg $Y). No action required."). This is consistent with the observation from phase 2 that the LLM is either following fallback paths or has learned to mimic the heuristic format for clear-cut cases. The self-contamination bug (BUG-1) means the LLM is being fed a prompt where the user's average is always equal to the current transaction amount for new users — which may explain the uniform LOW outcomes even in DeepSeek mode.
