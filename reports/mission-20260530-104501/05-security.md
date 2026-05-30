# Phase 5 — Security Probe Report

**Date:** 2026-05-30  
**Mode:** Heuristic (DeepSeek key invalid — LLM not called)  
**API:** http://localhost:8000

## Confirmed Vulnerabilities

| ID | Weakness | Verdict | Evidence |
|----|----------|---------|----------|
| A | Open CORS | NOT_CONFIRMED | CORS restricted to `localhost:3000`; evil-origin OPTIONS returned 400, no `Access-Control-Allow-Origin` echoed |
| B | No authentication | NOT_CONFIRMED | All endpoints return HTTP 401 without valid `X-Api-Key` header; `require_api_key` dependency enforced |
| C | No rate limiting | PARTIAL | 15 burst requests all 200 (under 60/min limit); slowapi configured but per-IP only — no per-user/per-key limit |
| D | Prompt injection | PARTIAL | Injection strings stored unsanitized and reflected in `explanation` field; heuristic unaffected, but LLM mode untested and XSS risk present |
| E | Irreversible freeze | CONFIRMED | `POST /unfreeze` returns 404 — no unfreeze endpoint exists; freeze is permanent until process restart |
| F | Weak input validation | PARTIAL | Timestamp `not-a-date` accepted (200 OK); XSS payload in merchant accepted and stored unescaped; negative/huge/long values properly rejected (422) |
| G | Type confusion / duplicate IDs | PARTIAL | String `"9000"` coerced to float (200 OK, HIGH freeze triggered); bool `true` coerced to 1.0 (200 OK); array/object rejected (422); duplicate IDs now return 409 |

**Confirmed: 1/7 | Partial: 4/7 | Not-Confirmed: 2/7**

## Severity Ranking (fix order)

1. **E — Irreversible Freeze (HIGH):** No recovery path. Any HIGH transaction permanently locks a user. Fix: implement `POST /unfreeze/{user_id}` with audit log and elevated auth.

2. **D — Prompt Injection / Stored XSS (HIGH):** Injection strings reach DB unescaped and are reflected in `explanation`. In LLM mode, prompt injection may manipulate risk classification. Fix: sanitize text fields before LLM prompt construction; escape HTML in dashboard output.

3. **C — Rate Limiting Gaps (MEDIUM):** Per-IP limit only (60/min). Attacker with distributed IPs or using the same key across multiple hosts can exceed effective rate. Fix: add per-user_id and per-API-key rate limiting.

4. **F — Bad Timestamp Accepted (MEDIUM):** `timestamp: "not-a-date"` stored as plain string, bypassing any time-based fraud logic that might depend on valid timestamps. Fix: add `datetime` type to Pydantic model.

5. **G — String/Bool Amount Coercion (LOW):** Pydantic silently coerces string `"9000"` and bool `true` to float. Not exploitable for bypass (HIGH still triggers), but unexpected behavior. Fix: use `strict=True` on amount field.

6. **A — CORS (LOW):** Already restricted. Ensure production env does not override `CORS_ORIGINS` to `*`.

7. **B — Auth (LOW):** Auth is enforced. Rotate the hardcoded default key `sentinel-dev-key`.

## Frozen Users (restart backend to reset)

- `u_sec_inject` — froze via prompt injection probe (amount $9999)
- `u_sec_freeze2` — froze via irreversible freeze probe (amount $9999)
- `u_sec_g` — froze via string-amount type confusion probe (amount "9000" coerced to $9000)
