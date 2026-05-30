# Sentinel Mission Report

**Mission:** 2026-05-23-183042
**Mode:** DeepSeek LLM (real key) + heuristic fallback during load test
**Phases run:** 6 / 6 (regression → fraud-sim → edge-cases → attacks → security → load)

---

## Executive Summary

Sentinel's API contract holds, the LLM gives credible verdicts on most clearly-suspicious traffic, and the autonomous freeze mechanism works as designed. **However, three classes of issues block any real deployment:**

1. **Detection gaps** — card-testing, structuring, and geo-impossible attacks pass undetected. Sentinel evaluates each transaction in isolation, with no velocity or geo-distance signal.
2. **Security posture is hackathon-grade only** — open CORS, no auth, no rate limit, irreversible freeze, and a trivial crash-via-duplicate-ID DoS.
3. **Performance ceiling is essentially zero** — server saturates at c=2 in heuristic mode and crashes outright. Single uvicorn worker + in-memory SQLite single-writer lock.

---

## Phase 1 — Regression Validator

- **9 / 9 contract checks passed.** Response shapes for `GET /`, `GET /transactions`, `POST /analyze` all conform; missing-field requests return 422.
- LLM-mode direction sanity: `$9000 → Lagos` returned MEDIUM (acceptable; not HIGH because new user had no history).
- **Mild drift observation:** the LLM under-escalates large amounts for *zero-history* users — a model-quality note, not a contract violation.

## Phase 2 — Fraud Simulator

- **52 transactions posted** across u1–u5. Distribution: **LOW 38 / MEDIUM 5 / HIGH 9.** All 5 users frozen.
- **7 misclassifications:**
  - `$15 Subway / u1 → HIGH` — u1's average was inflated by a prior $17k seed txn, so a tiny charge looked like a fraudster test purchase.
  - `$380 Apple Store, $275 Samsung → LOW` — same skewed average hid moderate spikes.
  - `$340 MGM Casino` → HIGH (LLM escalated on merchant category, even at small $).
  - Travel/retail moderate spikes consistently get benefit of the doubt.
- Takeaway: **per-user average is contaminable** — one outlier in history reshapes every future verdict.

## Phase 3 — Edge Cases (25 cases / 17 PASS / 1 FAIL / 7 SURPRISE)

- **FAIL — Duplicate transaction ID crashes the server (HTTP 500).** `main.py:34` does a bare INSERT; SQLite UNIQUE constraint raises unhandled `IntegrityError`. Reliable crash with any replayed ID.
- **SURPRISE — Hard thresholds bypassed in LLM mode.** $5000 absolute and 30× ratio rules in `agent.py` never fire when a real DeepSeek key is set. A $1 quadrillion transaction for a new user was classified **LOW** ("amount matches the user's average").
- **SURPRISE — Negative amounts accepted, no `Field(gt=0)` constraint.** `-$100` was stored and flagged HIGH by the LLM (false positive on a malformed-but-not-fraud input).
- Other edge wins: $0 handled cleanly (no divide-by-zero), unicode/long strings stored without crash.

## Phase 4 — Attack Scenarios (3 / 6 detected)

| Scenario | Verdict | Why |
|---|---|---|
| Card testing (10 micro-charges) | **MISSED** | No velocity counter. Each $1–$10 charge looks normal in isolation. |
| Account takeover | **DETECTED** | 122× ratio + Dubai @ 03:17 caught. Account frozen. |
| Structuring (6× $4,940) | **MISSED** | No sub-threshold aggregation. Each looks "normal" once user avg is set. |
| Mule transfer | **DETECTED** | $9k + Lagos hit the absolute threshold. |
| Geo-impossible (NY → Tokyo in 90s) | **MISSED** | No travel-speed / geo-distance check exists. |
| Merchant anomaly (crypto) | **DETECTED** | Amount ratio + merchant category flagged. |

**Three critical detection gaps:** velocity, geo-velocity, sub-threshold aggregation.

## Phase 5 — Security (6 / 7 weaknesses CONFIRMED)

| Weakness | Verdict | Sev |
|---|---|---|
| Open CORS | CONFIRMED | MED |
| No authentication | CONFIRMED | **HIGH** |
| No rate limiting | CONFIRMED | **HIGH** |
| Prompt injection (merchant/location → LOW) | NOT_EXPLOITABLE | LOW |
| Irreversible freeze (no unfreeze route) | CONFIRMED | **HIGH** |
| Weak input validation (negatives, 1e308, 10k-char IDs) | CONFIRMED | MED |
| Duplicate-ID crash (HTTP 500) | CONFIRMED | **HIGH** |

- **No-auth + open CORS** = any browser on any origin can freeze any `user_id`.
- **DoS** = 20 concurrent requests crashes the server; restart is the only recovery.
- Prompt injection held on the two payloads tested — latent risk remains because merchant/location strings still interpolate unsanitized into the prompt.

## Phase 6 — Load Test

| c | RPS | p50 | p95 | p99 | err |
|---|---|---|---|---|---|
| 1 | 0.27 | 4,558 ms | 4,582 ms | 4,582 ms | 0% |
| 2 | "2,218"* | <1 ms | 1 ms | 1.4 ms | 100% |

\* Sub-ms latency + 100% errors = instant connection-refused, not real responses.

- **Knee point: c=2.**
- **Saturation behavior: hard crash.** Post-test: `curl` exit 7.
- Bottleneck: single uvicorn worker + in-memory SQLite single-writer lock. Zero concurrency headroom.
- Note: c=1 already showed ~4.5 s/req, so the system was degraded heading into the ramp.

---

## Prioritized Fix List

**P0 — Crash / DoS:**
1. Wrap `INSERT` in `try/except IntegrityError` → return 409, not 500. (`main.py:34`)
2. Add a rate limit (e.g. `slowapi`) on `/analyze`.
3. Run uvicorn with `--workers N` and replace in-memory SQLite with persistent SQLite + WAL, or Postgres.

**P0 — Security:**
4. Add an auth header check; tighten CORS to your dashboard origin only.
5. Add `POST /unfreeze` (or admin route) with auth — irreversible freeze + no-auth is a guaranteed customer-support disaster.

**P1 — Detection:**
6. Add a per-user velocity counter (e.g. ≥5 txns / 5 min → flag).
7. Add a geo-velocity check (impossible-travel given prior location + timestamp).
8. Add sub-threshold aggregation (rolling sum near a structuring threshold).

**P1 — Input:**
9. `Field(gt=0)` on `amount`; max-length caps on ID/merchant/location; reject inf/NaN.

**P2 — Model quality:**
10. Pass last-N transaction window to the LLM (not just user average) so a single outlier can't permanently reshape verdicts.
11. Enforce the documented hard thresholds (`$5000` / `30×`) *before* the LLM is consulted — they should be a floor, not an alternative path.
