# Phase 6 — Load Test (`POST /analyze`)

**Status:** COMPLETED (run directly by the orchestrator — the `load-tester` subagent hit repeated stream-idle timeouts).
**Backend:** hardened build, authenticated with `X-API-Key: sentinel-dev-key`. Full valid payload, unique `user_id`/`id` per request, small amounts (stay LOW) to avoid velocity-freeze/423 skew.

## Concurrency ramp

| Concurrency | Requests | %200 | rps | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|---|
| 1  | 5  | 100% | 104  | 1.7  | 41.0* | 41.0* |
| 2  | 8  | 100% | 844  | 2.3  | 2.5  | 2.5  |
| 5  | 15 | 100% | 982  | 4.6  | 5.6  | 5.6  |
| 10 | 20 | 100% | 962  | 9.3  | 12.2 | 12.2 |
| 20 | 40 | 100% | 871  | 20.4 | 23.6 | 23.7 |
| 50 | 60 | 100% | 1317 | 32.9 | 38.9 | 39.2 |

\* c=1 p95 reflects one-time cold-start warmup; steady-state p50 ≈ 1.7 ms.

**Rate-limit probe:** 90 *simultaneous* requests → **90 × 200, 0 × 429**. Totals across the phase: **238 requests, 238 × 200, 0 errors, 0 rate-limited, 0 timeouts.**

## Findings

- **Performance is healthy.** Steady-state p50 ≈ 1.7 ms; p95 ≤ ~39 ms even at concurrency 50; peak ~1300 rps. No 5xx, no timeouts, no knee within c ≤ 50.
- **Latency scales ~linearly with concurrency** (p50 ≈ 0.65 ms × c) → requests **serialize** on a single global SQLite lock rather than running in parallel. Fine at demo scale; a throughput ceiling under heavy real load.
- **Rate limiting is configured but NOT enforced.** Code declares `60/minute` (`SENTINEL_ANALYZE_RATE`, [main.py:34](../../backend/main.py#L34) / [:96](../../backend/main.py#L96)) with a `@limiter.limit` decorator and a `RateLimitExceeded` handler — but **`SlowAPIMiddleware` is never added** (only `CORSMiddleware`, [main.py:56](../../backend/main.py#L56)). The decorator is inert without it, so the limit never fires. Confirms the prior-mission "no rate limiting" finding; corrects Phase 5's "PARTIAL/configured."
- **Consequence:** `/analyze` has no abuse ceiling beyond auth — a valid key can drive unbounded volume (amplifies the card-testing / enumeration gap from Phase 4).
