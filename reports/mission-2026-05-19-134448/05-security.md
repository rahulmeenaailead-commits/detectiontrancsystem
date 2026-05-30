# Phase 5 — Security Probe Report

**Agent:** security-prober  
**Date:** 2026-05-19  
**Mode:** DeepSeek LLM active (real API key)  
**Target:** http://localhost:8000  
**Probes run:** A, B, C, D, E, F, G  

---

## Confirmed Vulnerabilities

| ID | Weakness | Exploit | Status | Evidence (snippet) |
|----|----------|---------|--------|--------------------|
| A | Open CORS (wildcard) | OPTIONS preflight with `Origin: https://evil.example` | **CONFIRMED** | `access-control-allow-origin: *` — any origin drives `/analyze` from victim browser |
| B | No authentication | POST `/analyze` with no credentials, arbitrary `user_id` | **CONFIRMED** | HTTP 200, `account_frozen: true`, `action_taken: account_frozen` for `sec-noauth-victim` |
| C | No rate limiting | 50 sequential POSTs to `/analyze` | **CONFIRMED** | 50/50 = HTTP 200, 0 = HTTP 429; concurrent burst of 50 crashed the backend process |
| D | Prompt injection (LLM mode) | Injected `merchant`/`location` overriding classification | **CONFIRMED** | $9999 at user with $20 avg baseline returned `risk_level: LOW`, explanation: _"routine transaction at a common coffee shop… No immediate fraud indicators"_ |
| E | Irreversible freeze (no recovery) | Freeze via B; probe all unfreeze paths | **CONFIRMED** | `/unfreeze`, `/users/unfreeze`, `/user/unfreeze`, `/analyze/unfreeze`, `/reset` all return 404 |
| F | Input validation gaps | Negative amount, huge float, 10k-char id, bad timestamp, XSS/SQLi merchant | **CONFIRMED** | `amount: -9000` → HTTP 200; `id: "A"×10000` → HTTP 200; `timestamp: "not-a-date"` → HTTP 200 stored verbatim; XSS payload stored raw; SQLi parameterization holds (`?` placeholders) — frontend render risk for XSS remains |
| G | Duplicate ID → unhandled 500 | POST same `id` twice | **CONFIRMED** | First POST: HTTP 200. Second POST: HTTP 500 `Internal Server Error` (SQLite IntegrityError unhandled) |

*Probe D note: DeepSeek mode confirmed active. Injection landed: $9999 transaction against user sec-inject-u5 (10× $20 baseline = $20 avg) classified LOW after merchant and location fields contained override instructions.*

---

## Severity Ranking (fix order)

### 1. CRITICAL — B: No Authentication
Any unauthenticated caller on port 8000 can submit transactions for any `user_id`, triggering account freezes. Combined with D (prompt injection), an attacker can also suppress detection for a targeted user's genuinely fraudulent transactions.

**Fix:** Require `Authorization: Bearer <token>` on `/analyze`; validate JWT signature; assert `payload.user_id == token.sub`. Add middleware-level auth so no endpoint is reachable without valid credentials.

---

### 2. HIGH — D: Prompt Injection
User-controlled fields (`merchant`, `location`) are interpolated directly into the DeepSeek prompt with no sanitization. Tested payload returned LOW for a $9999 transaction that is 500× the user's $20 baseline.

**Fix:** Sanitize input fields before prompt construction in `agent.py:_build_prompt` — strip/escape newlines and known injection keywords, or switch to structured JSON tool-calling so user data never appears in instruction positions.

---

### 3. HIGH — E: Irreversible Freeze
Once frozen, a user account cannot be unfrozen through any API path. The only reset is a backend restart (which wipes the in-memory SQLite). This creates a Denial-of-Service vector via B: an attacker can permanently lock any user out of their account.

**Fix:** Add `POST /users/{user_id}/unfreeze` protected by admin-scoped JWT; log freeze/unfreeze events with timestamp, initiating transaction ID, and operator identity.

---

### 4. HIGH — A: Open CORS
`allow_origins=["*"]` permits any web origin to make credentialed cross-site requests to `/analyze`. A malicious page visited by a bank employee or internal user can silently drive the fraud API.

**Fix:** Replace `allow_origins=["*"]` with an explicit list (e.g. `["http://localhost:3000"]`) in `main.py:CORSMiddleware`.

---

### 5. HIGH — C: No Rate Limiting
`/analyze` accepts unlimited requests. 50 sequential calls all succeeded. 50 concurrent calls crashed the uvicorn process. With B unfixed, an attacker can freeze thousands of users per second, or DoS the backend with no protection.

**Fix:** Add `slowapi` or `starlette-ratelimit` middleware (e.g. 10 req/min per IP for `/analyze`); set `--limit-concurrency` on uvicorn.

---

### 6. MEDIUM — G: Duplicate ID → HTTP 500
Submitting the same transaction `id` twice raises SQLite `IntegrityError` which propagates as an unhandled HTTP 500. Breaks idempotent retry patterns and leaks server internals.

**Fix:** Wrap `cursor.execute("INSERT INTO transactions ...")` in `main.py` with `try/except sqlite3.IntegrityError` and return `JSONResponse(status_code=409, content={"detail": "duplicate transaction id"})`.

---

### 7. MEDIUM — F: Input Validation Gaps
Multiple field constraints are absent from the Pydantic model:
- `amount` accepts negative values (refund fraud bypass)
- `id`, `merchant`, `location` have no `max_length` (DB bloat, LLM prompt inflation)
- `timestamp` is typed as `str` — invalid dates stored verbatim (breaks `ORDER BY timestamp DESC`)
- `merchant`/`location` containing `<script>` tags are stored raw (XSS if rendered unescaped in dashboard)
- SQLi via `merchant` is mitigated by `?` parameterization — no action needed on DB side

**Fix:** Add Pydantic `Field` constraints: `amount: float = Field(..., ge=0)`, `id: str = Field(..., max_length=255)`, `merchant: str = Field(..., max_length=255)`, `location: str = Field(..., max_length=500)`, `timestamp: datetime` (rejects non-dates at 422). Escape merchant/location in the Next.js dashboard before rendering.

---

## Compounding Risk: B + D

The B (no auth) and D (prompt injection) vulnerabilities compose into a targeted attack:
1. Attacker seeds a victim `user_id` with a small-amount transaction, establishing a low baseline average.
2. Attacker submits a large fraudulent transaction for the victim with injected `merchant` text overriding classification to LOW.
3. The fraud passes undetected; no freeze fires; the attacker's actual money movement is laundered through the victim's account.

Neither vulnerability alone is sufficient for this attack — together they fully bypass the fraud detection system.

---

## Frozen User IDs (this phase)

The following user IDs were frozen during Phase 5 probing. Restart the backend to reset in-memory SQLite state.

- `sec-noauth-victim` — Probe B: unauthenticated attacker freeze
- `sec-inject-u3` — Probe D2: location newline injection (HIGH, correctly frozen)
- `sec-inject-u5` — Probe D4: confirmed injection landed (incorrectly LOW — not frozen despite $9999 at 500x avg)
- `sec-f-user` — Probe F: various validation inputs (frozen by DeepSeek on F1/F2/F3/F4 HIGH classifications)
- `sec-fneg-recheck` — Probe F1 recheck: negative amount -$9000
- `u_victim_2` — Probe B second attempt (MEDIUM, not frozen)

