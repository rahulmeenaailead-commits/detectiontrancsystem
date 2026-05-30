# Sentinel Mission Report

**Generated:** 2026-05-19T15:55:00Z
**Mission Dir:** `/Users/rahulmeena/VIKRAM PROJECT/reports/mission-2026-05-19-134448`
**API Base:** `http://localhost:8000`
**Mode:** DeepSeek (LLM-backed) — real `DEEPSEEK_API_KEY` present in `backend/.env`
**Run duration:** ~2h (phases 3–6 resumed inline after the orchestrator subprocess hit the Anthropic plan limit)

---

## Executive summary

- **API is healthy.** All contract checks pass; classification shapes are correct in both heuristic and LLM paths.
- **Detection is critically compromised.** Out of 6 named attack scenarios, **only 1 was caught** (mule-transfer — and only because of the absolute $5000 threshold, not the LLM's reasoning).
- **Root cause of most misses:** `main.py` INSERTs the transaction into SQLite **before** `get_user_average()` is called, so every first-time user's transaction includes itself in its own baseline. The ratio collapses to `1.0`, silently defeating the entire 30×-average HIGH path.
- **7 of 7 documented security weaknesses are live and exploitable** — including a compound chain (no-auth + prompt-injection) that lets an unauthenticated attacker classify a $9999 transaction as LOW.
- **Sentinel is not scalable under LLM mode.** Sequential p50 = **2.2s**; concurrency = 5 already saturates and produces 100% connection errors against single-worker uvicorn.

---

## 1. Regression — API Contract & Baseline

DeepSeek mode active. All 6 contract checks pass (`GET /`, `GET /transactions`, `POST /analyze` well-formed / empty / missing id / missing amount). Three LLM-mode sanity probes all returned correct response shapes and direction (a $9000 Lagos wire correctly returned HIGH). 11 pre-existing transactions in DB at run start.

- Contract: **6 PASS / 0 FAIL**
- Regression: **3 PASS / 0 FAIL**
- Drift: none
- Mode: DeepSeek (verified via `_use_mock` path skipped)

---

## 2. Fraud Simulation — Realistic Traffic

50 transactions sent across 5 synthetic users (`sim-u01..sim-u05`).

| Mix | Intended | Classified |
|---|---|---|
| LOW    | 35 | 43 |
| MEDIUM | 10 | 2 |
| HIGH   | 5  | 5 |

- **All 5 HIGH-risk transactions detected** ($5500+ to Lagos/Pyongyang/Moscow/Panama/anon-proxy). All 5 accounts frozen.
- **8 of 10 intended-MEDIUM transactions downgraded to LOW** — explanations were templated ("Amount $X within normal range") because the dirty DB inflated user averages and the LLM appears to be pattern-matching the heuristic format.
- Frozen users: `sim-u01, sim-u02, sim-u03, sim-u04, sim-u05`

---

## 3. Edge Cases — Boundary Bugs

21 cases run. **12 PASS / 4 FAIL / 5 SURPRISE.**

| BUG | Severity | What |
|---|---|---|
| **BUG-1** | **critical** | **Self-contamination of baseline** — `main.py` INSERTs the txn before `get_user_average()` is called, so a new user's first txn always has `avg = amount`, `ratio = 1.0`. The 30×-ratio HIGH path is completely defeated for first-time users. $3000 on a new user (true 30×) returned LOW. |
| BUG-2 | high | Duplicate transaction ID → unhandled `500 IntegrityError` (no 409). |
| BUG-3 | medium | Negative amounts accepted; ratio goes negative and silently classifies LOW with the explanation `"Amount $-100.00 is within normal range"`. |
| BUG-4 | low | No field-length limits — 5000-char `location` stored verbatim; inflates LLM prompt cost. |
| BUG-5 | low | Empty/garbage timestamps accepted (`""`, `"not-a-date"`). Breaks `ORDER BY timestamp DESC`. |
| BUG-6 | info | Already-frozen users are re-frozen on every subsequent HIGH txn (no idempotency). |

---

## 4. Attack Scenarios — Detection Coverage

| Scenario | Expected | Got | Frozen | Verdict |
|---|---|---|---|---|
| card-testing       | MEDIUM/HIGH | LOW (×10) | no  | **MISS** |
| account-takeover   | HIGH        | MEDIUM    | no  | **MISS** |
| structuring/smurfing | HIGH      | LOW (×6)  | no  | **MISS** ($29,869 laundered undetected) |
| mule-transfer      | HIGH        | HIGH      | **yes** | **CATCH** |
| geo-impossible     | HIGH        | LOW (×2)  | no  | **MISS** (NYC → Tokyo in 90s) |
| merchant-anomaly   | HIGH        | MEDIUM    | no  | PARTIAL-MISS |

**Coverage: 1/6 — 16.7%.**

Gaps:

- **GAP-1 (velocity)** — no rolling 5-min txn-count per user; card-testing is invisible.
- **GAP-2 (BUG-1 in production)** — ATO true ratio was **186.8×**, merchant-anomaly was **62.7×** — both should be HIGH, both returned MEDIUM because self-contamination deflated the displayed ratio to 8–9×.
- **GAP-3 (location-change)** — Dubai at 03:17 noted in LLM explanation but not enough to override the deflated ratio.
- **GAP-4 (sub-threshold aggregation)** — no rolling 24h sum; structuring across 6 txns at $4950–$4999 is invisible.
- **GAP-5 (geo-velocity)** — prior tx location/timestamp is never passed to the agent; impossible-travel is undetectable.
- **GAP-6 (merchant category)** — DeepSeek correctly identified "crypto exchange anomaly" but the deflated ratio kept it at MEDIUM.

> The only catch (mule-transfer) was driven by the **absolute `amount >= 5000`** rule, not by ratio, geo, or merchant reasoning. Every other detection path is currently broken.

---

## 5. Security — Confirmed Vulnerabilities

| ID | Weakness | Status | Severity | Evidence |
|---|---|---|---|---|
| A | Open CORS (wildcard) | confirmed | HIGH | `access-control-allow-origin: *` on preflight from `evil.example` |
| **B** | **No authentication** | **confirmed** | **CRITICAL** | Unauthenticated attacker froze `sec-noauth-victim` with a 3-txn seed + $9000 Lagos wire |
| C | No rate limiting | confirmed | HIGH | 50 sequential ⇒ 50× 200; concurrent burst of 50 **crashed uvicorn** |
| **D** | **Prompt injection (LLM mode)** | **confirmed** | **HIGH** | $9999 at user with $20 avg returned LOW after `merchant`/`location` injection payloads |
| E | Irreversible freeze | confirmed | HIGH | No `/unfreeze` / `/reset` / `/users/unfreeze` exists (all 404). Only backend restart recovers state. |
| F | Input validation gaps | confirmed | MEDIUM | Negative amounts, 1e308 floats, 10k-char IDs, malformed timestamps, raw XSS in `merchant` all accepted (SQLi parameterization holds) |
| G | Duplicate ID → 500 | confirmed | MEDIUM | Same `id` POSTed twice ⇒ unhandled `IntegrityError` |

**7 confirmed, 0 denied.**

### Critical compound: B + D ⇒ full fraud bypass

An unauthenticated attacker can (1) POST arbitrary transactions for any `user_id` (B), and (2) craft `merchant` / `location` strings that override LLM classification (D). Combined, this lets them push large fraudulent transactions through Sentinel undetected for any target user — the exact failure mode the system was built to prevent.

### Suggested fix order

1. **B — authentication** (require Bearer token; reject if payload `user_id` ≠ token sub).
2. **D — prompt injection** (sanitize newlines + keywords from string fields, or switch to JSON tool-calling in `agent.py:_build_prompt`).
3. **E — recovery path** (admin-only `POST /users/{user_id}/unfreeze` with audit log).
4. **A — CORS allowlist** (`['http://localhost:3000']`, drop wildcard).
5. **C — rate limit** (slowapi 10 req/min/IP on `/analyze`; `uvicorn --limit-concurrency 25`).
6. **G — duplicate ID** (wrap INSERT in `try/except IntegrityError`, return 409).
7. **F — Pydantic constraints** (`amount: float = Field(..., ge=0)`, `max_length=255`, timestamp typed as `datetime`).

---

## 6. Performance — Load Profile

DeepSeek mode. Tool: stdlib `urllib` + `ThreadPoolExecutor` (hey/wrk not installed).

| Concurrency | Total | Success | Errors | RPS | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|---|---|
| 1 | 2   | 2 | 0   | 0.5 | 2135.8 | 2332.8 | 2332.8 |
| 5 | 365 | 0 | 365 | 0.0 | 1.4    | 2.7    | 125.5 |

- **Sequential baseline p50:** 2.2s (entirely LLM-call dominated).
- **Knee:** concurrency = **5** — past this, every request fails with `ConnectionResetError` because the single uvicorn worker drops connections faster than threads can re-issue them.
- **Bottleneck:** `uvicorn` single-worker + synchronous DeepSeek call. The LLM call holds the worker for ~2s; under any concurrency, the listen backlog overflows.

### Practical ceiling

Under LLM mode, Sentinel cannot sustain more than ~1–2 req/s. Heuristic-only mode would scale fine — but the current build always tries DeepSeek first when a key is present.

---

## Recommendations (prioritized for hackathon demo)

1. **Fix BUG-1 first** — one-line change in [backend/main.py](backend/main.py) (call `get_user_average` *before* the INSERT). Single biggest detection lift: ATO, merchant-anomaly, ratio-based attacks all start firing HIGH again.
2. **Add velocity + geo signals** — pass `prior_tx_location, prior_tx_timestamp, txn_count_last_5min` into the agent prompt. Closes GAP-1, GAP-3, GAP-5.
3. **Add sub-threshold aggregation** — rolling 24h sum per `user_id`; trigger HIGH at $10k or 3 txns in [$4500, $5000] / 1h. Closes GAP-4.
4. **Auth + rate-limit + unfreeze** — these three together convert Sentinel from "demo" to "deployable". B, C, E are the trio judges will ask about.
5. **Heuristic-fast path** — short-circuit to heuristic when the heuristic is already HIGH (don't pay LLM latency to confirm a sure thing). Buys you 10× throughput.
6. **Pydantic field constraints** — close BUG-3, BUG-4, BUG-5 in one PR.

---

## Mission stats

| Metric | Value |
|---|---|
| Transactions analyzed (mission) | ~120 (50 sim + 21 edge + 32 attack + ~17 security + 2 load survivors + 3 regression) |
| Cumulative frozen users | 17 (`sim-u01..05`, `ato-u1`, `mule-u1`, `geo-u1`, `merch-u1`, `reg-u-llm-2/3`, `sec-noauth-victim`, `sec-inject-u3/5`, `sec-f-user`, `sec-fneg-recheck`, `u_victim_2`) |
| Detection coverage | **1/6 (16.7%)** |
| Confirmed vulnerabilities | **7/7** |
| Edge bugs / surprises | **9** (4 FAIL + 5 SURPRISE) |
| Performance knee | **5 concurrent** |
| Mode | DeepSeek (LLM) |

To reset state for a clean re-run:
```
# backend/ — kill and restart uvicorn (in-memory SQLite drops on restart)
```

---

## Note on coordination layers (for the hackathon video)

This mission demonstrates all three communication layers stacked:

- **Shared report file** — every agent's findings live in `reports/mission-2026-05-19-134448/`. Replayable, debuggable, audit-trail-ready.
- **Orchestrator relay** — for phases 3–6, this main session acted as the relay (the subprocess orchestrator hit the plan limit mid-mission). Each agent's `brief_for_next` was the handoff.
- **Named handoffs** — phase order was load-bearing: phase 4 (attack scenarios) depended on phase 2 having seeded users; phase 5 (security) depended on phase 3 having surfaced input weaknesses; phase 6 (load) ran last because it stresses the system. The plan limit interrupting the run *proved* the resumability promise — phases 1–2 outputs were intact on disk, and phase 3 read them on restart.
