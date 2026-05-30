# Sentinel — Mission Report

**Run:** `mission-20260530-104501` · **Date:** 2026-05-30
**Backend:** `http://localhost:8000` — single hardened FastAPI process, PID 8366, up continuously since 2026-05-27 16:24 (no restart during this mission). File-based `sentinel.db` (not in-memory).
**Mode:** Effective heuristic (DeepSeek key present but non-functional → deterministic rules).
**Auth:** Required — `X-API-Key: sentinel-dev-key` (code default). Unauthenticated → 401.
**Method:** 6 specialist subagents dispatched sequentially. Phases 2/4 needed retries; the `load-tester` (Phase 6) repeatedly hit subagent stream-idle timeouts, so the orchestrator ran that ramp directly. All findings below were re-verified by the orchestrator against the live build.

---

## Executive summary

The service is **operationally solid but a weak fraud detector.** It is faster and far more hardened than its own docs claim (CLAUDE.md is stale): auth, restricted CORS, input validation, reversible freeze, and 409 de-dup are all in place, and it serves ~1300 rps with p50 ≈ 1.7 ms and zero errors. **The real problem is detection efficacy:** only **2 of 6** named attack patterns are caught, and the only dependable HIGH trigger is the `$5000` absolute amount (plus an accidental velocity freeze). The marquee **30× ratio rule is dead code** because each transaction contaminates its own baseline before analysis.

**Verdict by area:** Contract ✅ · Performance ✅ · Hardening ✅ (mostly) · **Detection ❌** · **Rate limiting ❌ (inert)** · Audit integrity ⚠️.

---

## Phase results

| # | Phase | Result | Headline |
|---|---|---|---|
| 1 | regression-validator | MIXED | Contract 16/17; **4/4 classification drift** from self-contamination; `/unfreeze` mutates audit trail |
| 2 | fraud-simulator | DONE | 60 sent → LOW 20 / MED 0 / HIGH 5; **velocity-freeze cascade** 423-rejected 35; all 5 users frozen |
| 3 | edge-case-hunter | DONE | 36 cases: **27 PASS / 0 FAIL / 9 SURPRISE**; validation solid; ratio branch is dead code |
| 4 | attack-scenario-runner | DONE | **Coverage 2/6 (33%)** — only mule (amount) + merchant (incidental) |
| 5 | security-prober | DONE* | 7 weaknesses probed; *2 verdicts corrected by orchestrator (see below)* |
| 6 | load-tester | DONE | 238/238 = 200, p50 1.7 ms, p95 ≤ 39 ms @ c50, ~1300 rps; **rate limit inert** |

---

## Top findings (deduplicated, corrected, ranked)

### 1. CRITICAL — Insert-before-analyze self-contamination → ratio detection is dead code
`POST /analyze` inserts the transaction ([main.py:109](../../backend/main.py#L109)) **before** the agent computes the user's running average ([agent.py:205](../../backend/agent.py#L205)). A new user's first `$3000` txn therefore sees `avg = 3000, ratio = 1.0 → LOW`. The 30× rule needs ≥31 prior txns to fire even once, but the velocity rule freezes the account at 5 — so **the ratio branch is unreachable in practice.** This is the single highest-value fix and the root cause of all four Phase-1 classification drifts (e.g., `$100` at Whole Foods expected MEDIUM, got LOW).

### 2. HIGH — Detection coverage is 2/6
| Scenario | Caught | Why |
|---|---|---|
| card-testing | ❌ | no per-user rolling velocity counter wired to the pattern |
| account-takeover | ❌ | `$4800 < $5000`; ratio rule is dead code |
| structuring/smurfing | ❌ | no sub-threshold aggregation (`sum` over window) |
| mule-transfer | ✅ | absolute amount ≥ $5000 |
| geo-impossible | ❌ | no geo-distance vs elapsed-time check exists |
| merchant-anomaly | ⚠️ | only caught incidentally via the velocity freeze, not on merchant merit |

The engine is effectively **binary (LOW/HIGH)**; MEDIUM (0.5) almost never fires. Reliable HIGH triggers reduce to: amount ≥ $5000, OR 5 txns/user/5 min (velocity → freeze).

### 3. HIGH — Rate limiting is configured but NOT enforced *(corrects Phase 5)*
Code declares `60/minute` (`SENTINEL_ANALYZE_RATE`, [main.py:34](../../backend/main.py#L34)/[:96](../../backend/main.py#L96)) with a `@limiter.limit` decorator and a `RateLimitExceeded` handler — but **`SlowAPIMiddleware` is never registered** (only `CORSMiddleware`, [main.py:56](../../backend/main.py#L56)). Orchestrator proof: **90 simultaneous requests → 90 × 200, 0 × 429** (238 total in the minute, all 200). `/analyze` has no abuse ceiling beyond auth — directly amplifying the card-testing gap.

### 4. MEDIUM — `/unfreeze` destroys the audit trail (but freeze IS reversible) *(corrects Phase 5)*
Phase 5 reported "irreversible freeze CONFIRMED," but that was a **path error** — it called `/unfreeze` and `/unfreeze?user_id=`; the real route is `POST /unfreeze/{user_id}` ([main.py:138](../../backend/main.py#L138)). Orchestrator verified the full cycle: `$9999 → HIGH+frozen → 423 while frozen → POST /unfreeze/{id} → 200 → next txn LOW`. **Freeze is reversible.** The real issue (from Phase 1) is that `unfreeze_user()` *overwrites historical* `account_frozen`/`action_taken` rows, erasing the forensic record of the freeze.

### 5. MEDIUM — Stored injection / potential dashboard XSS
Injection/HTML payloads in `merchant` are stored verbatim and echoed back in the `explanation` field. LLM prompt-injection is moot here (heuristic mode never calls the model), but **if the Next.js dashboard renders `explanation`/`merchant` unescaped, this is stored XSS.**

### 6. LOW — Hardcoded default API key + lax numeric coercion
`SENTINEL_API_KEY` defaults to `"sentinel-dev-key"` in source ([main.py:28](../../backend/main.py#L28)) — a disclosure risk if deployed without an override. Separately, `amount` accepts `"5000"` (string) and `true` (bool) via Pydantic coercion → 200; the correct risk level is still returned, so this is cosmetic, but malformed payloads are normalized silently rather than rejected.

### 7. INFO — Single-threaded SQLite serializes under load
Latency scales ~linearly with concurrency (p50 ≈ 0.65 ms × c; 1.7 ms → 32.9 ms across c=1→50) — requests serialize on one global SQLite lock. Fine at demo scale; a throughput ceiling under heavy real load.

---

## What's actually GOOD (and contradicts the "hackathon-only" CLAUDE.md notes)

- **Auth enforced** on every route via `require_api_key` (X-API-Key).
- **CORS restricted** to `CORS_ORIGINS` (default `localhost:3000`) — not `["*"]`.
- **Input validation present:** `amount` `gt=0, le=1e12, allow_inf_nan=False`; string `min_length`; custom 422 handler. Zero/negative/huge/empty inputs correctly rejected.
- **Freeze is reversible** via `/unfreeze/{user_id}`.
- **Duplicate transaction id → 409.**
- **Performance:** 238/238 = 200, p50 ≈ 1.7 ms, p95 ≤ 39 ms @ c50, ~1300 rps peak, no 5xx/timeouts.

> ⚠️ **Doc drift:** CLAUDE.md still describes in-memory SQLite, open CORS, no auth, and no `/unfreeze`. The code has moved well past that (file DB, auth, CORS, rate-limit scaffold, `/unfreeze`, BrightData). Update CLAUDE.md.

---

## Recommended fixes (priority order)

1. **Move `insert_transaction()` to AFTER `analyze_transaction()`** (or compute the baseline excluding the current row). Unblocks the ratio rule and fixes all classification drift. *(Finding 1)*
2. **Wire real detectors:** rolling per-user velocity counter feeding the score (not just the freeze), sub-threshold aggregation for structuring, and a geo-distance/elapsed-time check. *(Finding 2)*
3. **Register `app.add_middleware(SlowAPIMiddleware)`** so the declared `60/minute` limit actually fires. *(Finding 3)*
4. **Make freeze/unfreeze append-only** — keep an event log instead of overwriting historical rows. *(Finding 4)*
5. **Escape `explanation`/`merchant` in the dashboard**, and sanitize/limit stored text. *(Finding 5)*
6. **Remove the hardcoded key default**; fail closed if `SENTINEL_API_KEY` is unset in non-dev. *(Finding 6)*

---

## Orchestrator corrections to subagent output (audit trail)

| Claim | Source | Correction | Evidence |
|---|---|---|---|
| "Backend swapped to hardened build mid-mission" | orchestrator's initial read | **Wrong** — same PID 8366 since May 27; agents simply authenticated with the discovered key | `ps` elapsed 2d20h; Phase 4 brief cites the key |
| "Irreversible freeze CONFIRMED" | Phase 5 | **Wrong** — wrong URL; freeze reversible via `/unfreeze/{user_id}` | full freeze→unfreeze cycle verified 200 |
| "Rate limit PARTIAL / configured (60/min)" | Phase 5 | **Understated** — limit is inert (middleware missing) | 90 simultaneous → 0×429 |

## Artifacts
`01-regression.{json,md}` · `02-fraud-sim.json` · `03-edge-cases.{json,md}` · `04-attacks.{json,md}` · `05-security.{json,md}` · `06-load.{json,md}` · `MISSION_REPORT.md`
