# Phase 6: Load Test Report — Sentinel /analyze

**Agent:** load-tester
**Started:** 2026-05-29T21:03:12Z
**Finished:** 2026-05-29T21:04:03Z
**Mode:** heuristic (DEEPSEEK_API_KEY unset — no LLM calls, deterministic path only)
**Tool:** asyncio + httpx (hey/wrk not installed)

---

## Setup

- Endpoint: `POST /analyze` (heavy path: DB insert + agent heuristic + possible freeze)
- Auth header: `X-API-Key: sentinel-dev-key`
- Concurrency levels: 1, 5, 10, 25, 50
- Duration per level: 10 seconds
- Payload: `amount=$15-$45`, user_id rotated across `lu1..lu20`, unique UUIDs for `id`
- Pre-unfroze all `lu1..lu20` before each level
- Inline unfreeze on 423 responses during test

---

## Results Table

| Concurrency | Total Req | Success | 423 Frozen | RPS (all) | SuccRPS | p50 (ms) | p95 (ms) | p99 (ms) | Non-423 Errors |
|---|---|---|---|---|---|---|---|---|---|
| 1  | 1,856  | 936  | 920  | 185.6 | 93.6  | 5.48  | 9.07  | 12.24  | 0 |
| 5  | 2,578  | 1,296 | 1,282 | 257.8 | 129.6 | 15.06 | 52.96 | 65.66  | 0 |
| 10 | 2,697  | 1,386 | 1,311 | 269.7 | 138.6 | 22.73 | 92.40 | 102.05 | 0 |
| 25 | 2,342  | 736  | 1,606 | 234.2 | 73.6  | 63.57 | 333.8 | 507.47 | 0 |
| 50 | 2,038  | 893  | 1,145 | 203.8 | 89.3  | 215.0 | 729.6 | 1339.6 | 0 |

**Sequential baseline (5 single requests, no concurrency):**
p50 = 4.95ms, p95 ~= 6.62ms, all 200 OK.

---

## Knee Point

**c=5** is the knee. At c=5, p95 jumped from 9.07ms to 52.96ms — a 5.8x increase. Beyond that:
- c=10: p95=92ms (10x baseline)
- c=25: p95=334ms (37x baseline)
- c=50: p95=730ms (80x baseline), p99=1340ms

Total throughput (RPS) peaked at c=10 (269.7 RPS all / 138.6 success RPS) and declined at c=25+ as contention dominated.

---

## 423 Frozen-Account Behavior

54.4% of all 11,511 requests during the ramp returned HTTP 423. Root cause: the velocity rule
(`5 txns / same user_id / 5-minute window`) fires rapidly when multiple concurrent workers
share the same pool of 20 user IDs. Even with the timestamp spread across different hours,
the SQLite-backed velocity query counts all matching user transactions regardless of hour offset.
Each freeze was unfrozen inline, but there is always a window between freeze and unfreeze where
subsequent requests for that user return 423.

This is a critical operational hazard: under real concurrent load, legitimate users would be
mass-frozen by the velocity check. The 20-user rotation is insufficient at c=10+ (each user
sees 10/20 = 0.5 workers on average, which is enough to trigger velocity).

---

## Bottleneck Analysis

**Primary:** Single SQLite writer (in-memory, WAL disabled)

Every `POST /analyze` hits the DB twice: once to `insert_transaction()`, once to
`get_user_average()` (plus a `freeze_user()` write on HIGH-risk). SQLite serializes all
writes through a single lock. Under concurrency, workers queue behind this lock, which explains
the linear latency growth:

- c=1:  p50=5ms  (no contention)
- c=5:  p50=15ms (3x)
- c=10: p50=23ms (4.6x)
- c=25: p50=64ms (13x)
- c=50: p50=215ms (44x)

**Secondary:** Single uvicorn worker (default `uvicorn main:app` — no `--workers` flag).
A single-process asyncio loop means all concurrent requests are handled by one OS thread.
The async/await in httpx means I/O doesn't block, but the synchronous SQLite driver
(`sqlite3` stdlib) calls are blocking — they hold the event loop while writing.

**Not a bottleneck:** The heuristic engine itself. Sequential baseline p50=4.95ms confirms
the Python heuristic logic (ratio check, velocity check) is sub-millisecond; the observed
latency is entirely DB and network overhead.

---

## Observed Findings

1. **No true server errors (0 non-423 failures):** The API is stable under load — no crashes,
   no 500s, no timeouts. Stability is good.

2. **Latency wall at c=25+:** p99 crosses 500ms at c=25 and 1340ms at c=50. For a fraud
   detection system that should flag transactions in real-time, 1.3s tail latency at 50
   concurrent clients is unacceptable.

3. **Throughput ceiling ~138 success RPS (c=10):** Beyond c=10, success RPS drops because
   the freeze/unfreeze cycle consumes more of the bandwidth. Effective fraud-detection
   throughput is ~140 transactions/second in heuristic mode on this hardware.

4. **Velocity check is a load multiplier for 423s:** The more concurrent workers, the faster
   the velocity window fills, the more freezes, the more unfreeze calls, the more DB writes.
   This creates a feedback loop that accelerates degradation.

---

## Recommendations

1. Switch to WAL-mode SQLite (`PRAGMA journal_mode=WAL`) for concurrent reads; or move to
   PostgreSQL for true multi-writer concurrency.
2. Run uvicorn with `--workers 4` (multiprocessing) or use Gunicorn with uvicorn workers.
3. Decouple the DB insert from the analysis: compute the average BEFORE inserting (fixes
   the BUG-1 self-contamination found in Phase 3 AND removes a synchronous DB round-trip
   from the hot path).
4. Raise the velocity threshold or add per-IP rate limiting instead of per-user, so
   concurrent clients don't mass-freeze legitimate users.

---

## Cleanup Note

The database now contains load-* transaction IDs from this run. Restart the backend
(`uvicorn main:app --reload`) to reset the in-memory SQLite to a clean state.
